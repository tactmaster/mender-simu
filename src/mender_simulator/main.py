"""
Mender Fleet Simulator - Main Orchestration Script

This script orchestrates multiple simulated Mender devices using asyncio
for efficient concurrent operation.
"""

import asyncio
import glob
import math
import os
import select
import signal
import sys
import logging
import argparse
import termios
import threading
import tty
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import aiohttp
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler

from . import __version__
from .db.database import DatabaseManager
from .db.models import Device
from .utils.config import load_config, get_enabled_industries, Config
from .utils.crypto import generate_rsa_keypair
from .simulation.profiles import IndustryProfile
from .simulation.device_simulator import DeviceSimulator
from .client.auth import AuthClient
from .client.inventory import InventoryClient
from .client.preauth import PreauthClient
from .stats import FleetStats
from .dashboard import dashboard_loop, render


# Configure logging
def setup_logging(
    log_file: str,
    log_level: str,
    console: Optional[Console] = None,
) -> None:
    """Configure logging for the simulator.

    When a rich Console is supplied (dashboard mode) all console output is
    routed through it so the Live display doesn't produce artefacts.
    Console level is capped at WARNING to keep the dashboard readable.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)

    if console:
        rich_handler = RichHandler(
            console=console, show_path=False, markup=True, rich_tracebacks=True
        )
        rich_handler.setLevel(logging.WARNING)
        root_logger.addHandler(rich_handler)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        root_logger.addHandler(console_handler)

    # Remove log files older than 10 days
    _cleanup_old_logs(Path(log_file), max_days=10)


def _cleanup_old_logs(log_path: Path, max_days: int = 10) -> None:
    """Delete daily log files older than *max_days*."""
    pattern = str(log_path.parent / f"{log_path.stem}_*{log_path.suffix}")
    cutoff = datetime.now() - timedelta(days=max_days)

    for filepath in glob.glob(pattern):
        name = Path(filepath).stem  # e.g. "simulator_2026-04-10"
        # Extract the date suffix after the last underscore
        parts = name.rsplit("_", 1)
        if len(parts) != 2:
            continue
        try:
            file_date = datetime.strptime(parts[1], "%Y-%m-%d")
        except ValueError:
            continue
        if file_date < cutoff:
            Path(filepath).unlink()
            logging.getLogger(__name__).debug(f"Removed old log: {filepath}")


logger = logging.getLogger(__name__)


def _join_thread(thread: threading.Thread) -> None:
    """Block until a worker thread finishes (max 30 s)."""
    thread.join(timeout=30)


class DeviceWorker:
    """Runs a partition of device simulators in a dedicated OS thread.

    Each worker owns:
      - its own asyncio event loop
      - a shared aiohttp.ClientSession (with TCPConnector) for all its devices
      - its own DatabaseManager connection to avoid cross-loop aiosqlite issues
    """

    def __init__(
        self,
        thread_id: int,
        simulators: List[DeviceSimulator],
        db_path: str,
        connection_limit: int,
        stats: Optional["FleetStats"] = None,
    ):
        self.thread_id = thread_id
        self.simulators = simulators
        self.db_path = db_path
        self.connection_limit = connection_limit
        self.stats = stats

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Entry point called by the worker thread."""
        asyncio.run(self._run_loop())

    async def _run_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()

        connector = aiohttp.TCPConnector(limit=self.connection_limit)
        # sock_connect only times out the TCP handshake itself, not pool
        # slot acquisition. total=60 acts as the overall safety net so
        # requests don't hang indefinitely.
        timeout = aiohttp.ClientTimeout(total=60, sock_connect=15)
        session = aiohttp.ClientSession(connector=connector, timeout=timeout)

        db = DatabaseManager(self.db_path)
        await db.connect()

        # Register with stats collector and inject session/DB/stats into every simulator
        if self.stats:
            self.stats.register_thread(self.thread_id, len(self.simulators))
        for simulator in self.simulators:
            simulator.set_session(session)
            simulator.db = db
            simulator._stats = self.stats
            simulator._thread_id = self.thread_id

        logger.info(
            f"Worker-{self.thread_id}: {len(self.simulators)} devices, "
            f"connection_limit={self.connection_limit}"
        )

        tasks: List[asyncio.Task] = []
        try:
            self._ready.set()

            for simulator in self.simulators:
                task = asyncio.create_task(simulator.start())
                tasks.append(task)
                await asyncio.sleep(0)

            await self._shutdown_event.wait()

        finally:
            for simulator in self.simulators:
                await simulator.stop()

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            await db.close()
            await session.close()

    # ------------------------------------------------------------------
    # Thread-safe control
    # ------------------------------------------------------------------

    def signal_shutdown(self) -> None:
        """Tell this worker's event loop to stop (thread-safe)."""
        if self._loop and self._shutdown_event:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

    def signal_force_poll(self) -> None:
        """Trigger an immediate poll on every device in this worker (thread-safe)."""
        if self._loop:
            for simulator in self.simulators:
                self._loop.call_soon_threadsafe(simulator.force_poll)


class FleetOrchestrator:
    """Orchestrates the fleet of simulated devices."""

    def __init__(self, config: Config, stats: Optional["FleetStats"] = None):
        self.config = config
        self.stats = stats
        self.db: Optional[DatabaseManager] = None
        self.simulators: List[DeviceSimulator] = []
        self._workers: List[DeviceWorker] = []
        self._threads: List[threading.Thread] = []
        self._shutdown_event = asyncio.Event()
        self._shutting_down = False

    async def start(self) -> None:
        """Initialize and start all device simulators."""
        logger.info("=" * 60)
        logger.info("Mender Fleet Simulator Starting")
        logger.info("=" * 60)

        # Initialize database (used only for setup; workers open their own connections)
        self.db = DatabaseManager(self.config.simulator.database_path)
        await self.db.connect()

        # Load or create devices
        await self._initialize_devices()

        # Partition simulators across worker threads
        num_threads = max(
            1, min(self.config.simulator.num_threads, len(self.simulators))
        )
        chunk_size = math.ceil(len(self.simulators) / num_threads)
        chunks = [
            self.simulators[i : i + chunk_size]
            for i in range(0, len(self.simulators), chunk_size)
        ]

        logger.info(
            f"Starting {len(self.simulators)} simulators across "
            f"{len(chunks)} worker thread(s) "
            f"(connection_limit={self.config.simulator.connection_limit} per thread)"
        )

        for i, chunk in enumerate(chunks):
            worker = DeviceWorker(
                thread_id=i,
                simulators=chunk,
                db_path=self.config.simulator.database_path,
                connection_limit=self.config.simulator.connection_limit,
                stats=self.stats,
            )
            thread = threading.Thread(
                target=worker.run,
                name=f"device-worker-{i}",
                daemon=True,
            )
            self._workers.append(worker)
            self._threads.append(thread)
            thread.start()
            # Wait for worker's event loop to be ready without blocking the main loop
            # (keeps Ctrl-C responsive during startup)
            await asyncio.get_running_loop().run_in_executor(None, worker._ready.wait)

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Gracefully stop all worker threads."""
        logger.info("Initiating graceful shutdown...")

        for worker in self._workers:
            worker.signal_shutdown()

        # Wait for all threads to finish without blocking the event loop
        if self._threads:
            loop = asyncio.get_running_loop()
            await asyncio.gather(
                *(loop.run_in_executor(None, _join_thread, t) for t in self._threads)
            )

        if self.db:
            await self.db.close()

        logger.info("Shutdown complete")
        self._shutdown_event.set()

    def signal_shutdown(self) -> None:
        """Signal the orchestrator to shut down (idempotent)."""
        if self._shutting_down:
            return
        self._shutting_down = True
        asyncio.create_task(self.stop())

    def signal_force_poll(self) -> None:
        """Signal all devices to perform an immediate poll cycle."""
        logger.info("=" * 40)
        logger.info("SIGUSR1 received - Forcing immediate poll for all devices")
        logger.info("=" * 40)
        for worker in self._workers:
            worker.signal_force_poll()

    async def _initialize_devices(self) -> None:
        """Load existing devices or create new ones based on config."""
        enabled_industries = get_enabled_industries(self.config)

        if not enabled_industries:
            logger.warning("No industries enabled in configuration")
            return

        logger.info(f"Enabled industries: {list(enabled_industries.keys())}")

        for industry_name, industry_config in enabled_industries.items():
            profile = IndustryProfile(industry_config)

            # Check existing devices for this industry
            existing = await self.db.get_devices_by_industry(industry_name)
            existing_count = len(existing)
            target_count = industry_config.count

            logger.info(
                f"Industry '{industry_name}': {existing_count} existing, "
                f"{target_count} configured"
            )

            # Keep only target_count devices active; mark the rest for decommission
            active_devices = existing[:target_count]
            excess_devices = existing[target_count:]

            for device in active_devices:
                device.inventory_data.pop("decommission", None)
                await self.db.save_device(device)
                simulator = DeviceSimulator(device, profile, self.config, self.db)
                self.simulators.append(simulator)

            if excess_devices:
                logger.info(
                    f"Industry '{industry_name}': decommissioning "
                    f"{len(excess_devices)} excess devices"
                )
                await self._decommission_excess_devices(excess_devices)

            # Create new devices if needed
            if existing_count < target_count:
                new_devices = await self._create_devices(
                    profile, target_count - existing_count, existing_count
                )
                for device in new_devices:
                    simulator = DeviceSimulator(device, profile, self.config, self.db)
                    self.simulators.append(simulator)

        # Preauthorize only new (never-preauthorized) devices for
        # industries that have preauth enabled
        pat = self.config.server.personal_access_token
        if pat:
            simulators_to_preauth = [
                s
                for s in self.simulators
                if not s.device.preauthorized
                and self.config.industries.get(s.device.industry_profile) is not None
                and self.config.industries[s.device.industry_profile].preauth
            ]
            if simulators_to_preauth:
                logger.info(f"Preauthorizing {len(simulators_to_preauth)} new devices")
                await self._preauthorize_all_devices(pat, simulators_to_preauth)
            else:
                logger.info("All devices already preauthorized, skipping")

        # Summary
        counts = await self.db.count_devices_by_industry()
        total = sum(counts.values())
        logger.info(f"Total devices initialized: {total}")
        for industry, count in counts.items():
            logger.info(f"  - {industry}: {count} devices")

    async def _decommission_excess_devices(self, devices: List[Device]) -> None:
        """Send final inventory with decommission=true, then delete from DB.

        Each excess device authenticates, sends its inventory one last time
        with ``decommission: true``, and is then removed from the database.
        """
        auth_client = AuthClient(
            self.config.server.url,
            self.config.server.tenant_token,
        )
        inv_client = InventoryClient(self.config.server.url)

        try:
            for device in devices:
                # Authenticate
                token = await auth_client.authenticate(
                    device.identity_data,
                    device.rsa_public_key,
                    device.rsa_private_key,
                )
                if not token:
                    logger.warning(
                        f"Device {device.device_id} could not authenticate "
                        "for final inventory — deleting from DB anyway"
                    )
                    await self.db.delete_device(device.device_id)
                    continue

                # Send inventory with decommission flag
                device.inventory_data["decommission"] = True
                sent = await inv_client.update_inventory(token, device.inventory_data)
                if sent:
                    logger.info(
                        f"Device {device.device_id} sent decommission inventory"
                    )
                else:
                    logger.warning(
                        f"Device {device.device_id} failed to send decommission "
                        "inventory — deleting from DB anyway"
                    )

                # Remove from database
                await self.db.delete_device(device.device_id)
                logger.info(f"Device {device.device_id} removed from database")
        finally:
            await auth_client.close()
            await inv_client.close()

    async def _preauthorize_all_devices(
        self, pat: str, simulators: Optional[List[DeviceSimulator]] = None
    ) -> None:
        """Preauthorize devices on the Mender server.

        Args:
            pat: Personal Access Token for the management API.
            simulators: Subset of simulators to preauthorize. Defaults to all.
        """
        targets = simulators if simulators is not None else self.simulators
        preauth_client = PreauthClient(self.config.server.url, pat)
        # Management API rate limits are strict — keep concurrency low
        sem = asyncio.Semaphore(5)

        async def _preauth_one(simulator: "DeviceSimulator") -> bool:
            async with sem:
                success = await preauth_client.preauthorize_device(
                    simulator.device.identity_data, simulator.device.rsa_public_key
                )
                if success:
                    simulator.device.preauthorized = True
                    await self.db.save_device(simulator.device)
                return success

        try:
            results = await asyncio.gather(*(_preauth_one(s) for s in targets))
        finally:
            await preauth_client.close()

        ok = sum(results)
        fail = len(results) - ok
        logger.info(f"Preauthorization complete: {ok} succeeded, {fail} failed")

    async def _create_devices(
        self, profile: IndustryProfile, count: int, start_index: int
    ) -> List[Device]:
        """Create new devices for an industry profile."""
        devices = []

        logger.info(f"Creating {count} new devices for {profile.name}")

        for i in range(count):
            index = start_index + i

            # Generate identity
            identity = profile.generate_device_identity(index)
            device_id = f"{profile.config.id_prefix}-{profile.name}-{index:06d}"

            # Generate RSA keypair
            private_key, public_key = generate_rsa_keypair()

            # Generate initial static inventory
            inventory = profile.generate_static_inventory(
                device_id, poll_interval=self.config.server.poll_interval
            )

            # Create device
            device = Device(
                device_id=device_id,
                identity_data=identity,
                rsa_private_key=private_key,
                rsa_public_key=public_key,
                industry_profile=profile.name,
                current_status="idle",
                inventory_data=inventory,
            )

            # Save to database
            await self.db.save_device(device)
            devices.append(device)

            logger.debug(f"Created device: {device_id}")

        logger.info(f"Created {len(devices)} devices for {profile.name}")
        return devices


async def main(config_path: str, live: Optional[Live] = None) -> None:
    """Main entry point for the simulator."""
    # Load configuration
    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    # Setup logging (route console output through rich when dashboard is active)
    setup_logging(
        config.simulator.log_file,
        config.simulator.log_level,
        console=live.console if live else None,
    )

    # Create stats collector and orchestrator
    stats = FleetStats()
    orchestrator = FleetOrchestrator(config, stats=stats)

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def handle_shutdown_signal(sig):
        logger.info(f"Received signal {sig.name}")
        orchestrator.signal_shutdown()

    def handle_force_poll_signal():
        orchestrator.signal_force_poll()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown_signal(s))

    # SIGUSR1 triggers immediate poll (use: kill -USR1 <pid>)
    loop.add_signal_handler(signal.SIGUSR1, handle_force_poll_signal)

    # Start live dashboard refresh task (renders once per second)
    if live:
        live.update(render(stats))  # show initial frame immediately
        asyncio.create_task(dashboard_loop(live, stats, orchestrator._shutdown_event))

    # Run orchestrator
    try:
        await orchestrator.start()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        await orchestrator.stop()
        sys.exit(1)


def _keyboard_listener(stop: threading.Event) -> None:
    """Background thread: press 'q' or 'Q' to trigger graceful shutdown."""
    if not sys.stdin.isatty():
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while not stop.is_set():
            if select.select([sys.stdin], [], [], 0.2)[0]:
                ch = sys.stdin.read(1)
                if ch.lower() == "q":
                    os.kill(os.getpid(), signal.SIGINT)
                    return
    except Exception:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def run():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Mender Fleet Simulator - Simulate device fleets for Mender.io"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config/config.yaml",
        help="Path to configuration file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--version", action="version", version=f"Mender Fleet Simulator {__version__}"
    )

    args = parser.parse_args()

    # Run with a live dashboard
    console = Console()
    kb_stop = threading.Event()
    kb_thread = threading.Thread(
        target=_keyboard_listener, args=(kb_stop,), daemon=True
    )
    kb_thread.start()
    try:
        with Live(console=console, refresh_per_second=1, screen=False) as live:
            asyncio.run(main(args.config, live))
    finally:
        kb_stop.set()
        kb_thread.join(timeout=1)


if __name__ == "__main__":
    run()
