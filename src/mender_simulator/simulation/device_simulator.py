"""Device simulator for handling update lifecycle."""

import asyncio
import logging
import random
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiohttp

from ..db.models import Device, DeploymentStatus, DeviceStatus
from ..db.database import DatabaseManager
from ..client.base import DEFAULT_TIMEOUT
from ..client.auth import AuthClient
from ..client.inventory import InventoryClient
from ..client.deployments import DeploymentsClient, DeploymentState, Deployment
from ..client.exceptions import (
    AuthenticationError,
    DeviceNotAcceptedError,
    RateLimitError,
    RequestTimeoutError,
)
from ..client.preauth import PreauthClient
from ..stats import FleetStats
from ..utils.config import Config
from .. import __version__
from .profiles import IndustryProfile


def _get_host_mac() -> str:
    """Return the MAC address of the host machine."""
    mac = uuid.getnode()
    return ":".join(f"{(mac >> (8 * i)) & 0xFF:02x}" for i in reversed(range(6)))


logger = logging.getLogger(__name__)


class DeviceSimulator:
    """Simulates a single Mender device's behavior."""

    def __init__(
        self,
        device: Device,
        profile: IndustryProfile,
        config: Config,
        db: DatabaseManager,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.device = device
        self.profile = profile
        self.config = config
        self.db = db

        # Share a single aiohttp session across all clients for this device
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session = session is None

        self.auth_client = AuthClient(
            config.server.url, config.server.tenant_token, session=session
        )
        self.inventory_client = InventoryClient(config.server.url, session=session)
        self.deployments_client = DeploymentsClient(config.server.url, session=session)

        self._running = False
        self._current_deployment: Optional[Deployment] = None
        self._force_poll_event = asyncio.Event()
        self._stats: Optional[FleetStats] = None
        self._thread_id: int = 0
        self._has_polled = False

    def set_session(self, session: aiohttp.ClientSession) -> None:
        """Inject a shared HTTP session into all clients (owned externally)."""
        for client in (
            self.auth_client,
            self.inventory_client,
            self.deployments_client,
        ):
            client._session = session
            client._owns_session = False

    async def start(self) -> None:
        """Start the device simulation loop."""
        self._running = True
        logger.info(f"Device {self.device.device_id} starting simulation")

        # Create shared session if we own it, and inject into clients
        if self._owns_session:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
            self.auth_client._session = self._session
            self.auth_client._owns_session = False
            self.inventory_client._session = self._session
            self.inventory_client._owns_session = False
            self.deployments_client._session = self._session
            self.deployments_client._owns_session = False
            if self._preauth_client:
                self._preauth_client._session = self._session
                self._preauth_client._owns_session = False

        try:
            # Spread initial polls randomly across one poll interval to avoid
            # a thundering herd when many devices start at the same time.
            jitter = random.uniform(0, self.config.server.poll_interval)
            await asyncio.sleep(jitter)

            # Initial authentication — skip if a token was already loaded from DB
            if not self.device.auth_token:
                if not await self._authenticate():
                    logger.warning(
                        f"Device {self.device.device_id} failed initial auth, "
                        "will retry on next poll"
                    )

            # Main simulation loop
            while self._running:
                await self._poll_cycle()
                # Wait for poll_interval or force_poll signal
                try:
                    await asyncio.wait_for(
                        self._force_poll_event.wait(),
                        timeout=self.config.server.poll_interval,
                    )
                    # Force poll was triggered
                    self._force_poll_event.clear()
                    logger.info(
                        f"Device {self.device.device_id} - Force poll triggered"
                    )
                except asyncio.TimeoutError:
                    # Normal timeout, continue with next poll
                    pass

        except asyncio.CancelledError:
            logger.info(f"Device {self.device.device_id} simulation cancelled")
        finally:
            await self._cleanup()

    def force_poll(self) -> None:
        """Trigger an immediate poll cycle."""
        self._force_poll_event.set()

    async def stop(self) -> None:
        """Stop the device simulation."""
        self._running = False
        logger.info(f"Device {self.device.device_id} stopping")

    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
        else:
            await self.auth_client.close()
            await self.inventory_client.close()
            await self.deployments_client.close()

    async def _authenticate(self) -> bool:
        """Authenticate device with Mender server, retrying on rate limit."""
        logger.debug(f"Device {self.device.device_id} authenticating")

        for attempt in range(6):
            try:
                token = await self.auth_client.authenticate(
                    self.device.identity_data,
                    self.device.rsa_public_key,
                    self.device.rsa_private_key,
                )
            except DeviceNotAcceptedError:
                logger.info(
                    f"Device {self.device.device_id} not accepted — triggering preauth"
                )
                await self._trigger_preauth()
                return False
            except RateLimitError as e:
                if self._stats:
                    self._stats.record_429(self._thread_id, "auth", e.retry_after)
                backoff = e.retry_after + random.uniform(0, 10)
                logger.debug(
                    f"Device {self.device.device_id} auth rate limited, "
                    f"retrying in {backoff:.0f}s"
                )
                await asyncio.sleep(backoff)
                continue
            except RequestTimeoutError as e:
                if self._stats:
                    self._stats.record_timeout(self._thread_id, e.endpoint)
                await asyncio.sleep(random.uniform(5, 15))
                continue

            if token:
                self.device.auth_token = token
                await self.db.update_device_auth_token(self.device.device_id, token)
                logger.info(
                    f"Device {self.device.device_id} authenticated successfully"
                )
                return True

            return False

        # Auth failed — try to re-preauthorize and retry once
        if self._preauth_client:
            logger.info(
                f"Device {self.device.device_id} auth failed, "
                "attempting re-preauthorization..."
            )
            preauth_ok = await self._preauth_client.preauthorize_device(
                self.device.identity_data,
                self.device.rsa_public_key,
            )
            if preauth_ok:
                token = await self.auth_client.authenticate(
                    self.device.identity_data,
                    self.device.rsa_public_key,
                    self.device.rsa_private_key,
                )
                if token:
                    self.device.auth_token = token
                    await self.db.update_device_auth_token(self.device.device_id, token)
                    logger.info(
                        f"Device {self.device.device_id} re-preauthorized and "
                        "authenticated successfully"
                    )
                    return True

        return False

    async def _trigger_preauth(self) -> None:
        """Self-preauthorize this device via the management API."""
        pat = self.config.server.personal_access_token
        if not pat:
            return
        preauth_client = PreauthClient(self.config.server.url, pat)
        try:
            success = await preauth_client.preauthorize_device(
                self.device.identity_data, self.device.rsa_public_key
            )
            if success:
                self.device.preauthorized = True
                await self.db.save_device(self.device)
        finally:
            await preauth_client.close()

    async def _poll_cycle(self) -> None:
        """Execute one polling cycle."""
        # Ensure we have valid auth
        if not self.device.auth_token:
            if not await self._authenticate():
                return

        # Update last poll time
        await self.db.update_last_poll(self.device.device_id)

        try:
            # Send inventory update
            inv_ok = await self._update_inventory()
            if not inv_ok and self._stats:
                self._stats.record_error(self._thread_id, "inventory", "update failed")

            # Check for deployments
            deployment = await self._check_deployment()
            if deployment:
                await self._process_deployment(deployment)

            if self._stats:
                self._stats.record_poll_ok(self._thread_id)
                if not self._has_polled:
                    self._stats.record_device_started(self._thread_id)
                    self._has_polled = True

        except RequestTimeoutError as e:
            if self._stats:
                self._stats.record_timeout(self._thread_id, e.endpoint)
        except RateLimitError as e:
            if self._stats:
                self._stats.record_429(self._thread_id, e.endpoint, e.retry_after)
            backoff = e.retry_after + random.uniform(0, 10)
            logger.warning(
                f"Device {self.device.device_id} rate limited on {e.endpoint} — "
                f"backing off {backoff:.0f}s"
            )
            await asyncio.sleep(backoff)
            # Force immediate retry after backoff — don't also wait poll_interval
            self.force_poll()
        except AuthenticationError:
            # Token expired — clear it and re-auth next cycle (normal, not an error)
            logger.debug(
                f"Device {self.device.device_id} token expired, will re-authenticate"
            )
            self.device.auth_token = None
            await self.db.update_device_auth_token(self.device.device_id, None)

    async def _update_inventory(self) -> bool:
        """Update device inventory on server. Returns True on success."""
        if not self.device.auth_token:
            return True  # nothing to do, not an error

        # Update only telemetry, keep static attributes
        inventory = self.profile.update_telemetry(self.device.inventory_data)
        inventory["simulator_version"] = __version__
        inventory["host_mac"] = self._host_mac
        self.device.inventory_data = inventory

        success = await self.inventory_client.update_inventory(
            self.device.auth_token, inventory
        )

        if success:
            await self.db.save_device(self.device)
            logger.debug(f"Device {self.device.device_id} telemetry updated")

        return success

    async def _check_deployment(self) -> Optional[Deployment]:
        """Check for pending deployments."""
        if not self.device.auth_token:
            return None

        device_provides = {
            "device_type": self.device.inventory_data.get("device_type", "unknown"),
            "artifact_name": self.device.inventory_data.get("artifact_name", "unknown"),
        }
        checksum = self.device.inventory_data.get("rootfs-image.checksum")
        if checksum:
            device_provides["rootfs-image.checksum"] = checksum

        return await self.deployments_client.check_for_deployment(
            self.device.auth_token, device_provides
        )

    async def _process_deployment(self, deployment: Deployment) -> None:
        """Process a deployment through all stages."""
        logger.info(
            f"Device {self.device.device_id} processing deployment "
            f"{deployment.id} - {deployment.artifact_name}"
        )

        self._current_deployment = deployment
        self.device.current_status = DeviceStatus.UPDATING
        await self.db.update_device_status(self.device.device_id, DeviceStatus.UPDATING)

        # Create deployment status record
        status = DeploymentStatus(
            device_id=self.device.device_id,
            deployment_id=deployment.id,
            artifact_name=deployment.artifact_name,
            status="downloading",
        )
        await self.db.save_deployment_status(status)

        # Determine if this update will succeed
        # Use config success_rate if set, otherwise use industry-specific rate
        success_rate = self.config.simulator.success_rate
        will_succeed = random.random() < success_rate

        try:
            # Stage 1: Downloading
            await self._stage_downloading(deployment, status)

            # Stage 2: Installing
            await self._stage_installing(deployment, status)

            # Stage 3: Rebooting
            await self._stage_rebooting(deployment, status)

            # Stage 4: Final status
            if will_succeed:
                await self._stage_success(deployment, status)
            else:
                error_msg = random.choice(self.config.error_messages)
                await self._stage_failure(deployment, status, error_msg)

        except RateLimitError:
            raise  # let _poll_cycle handle the backoff
        except Exception as e:
            logger.exception(f"Deployment error for {self.device.device_id}: {e}")
            await self._stage_failure(deployment, status, str(e))

        finally:
            self._current_deployment = None
            self.device.current_status = DeviceStatus.IDLE
            await self.db.update_device_status(self.device.device_id, DeviceStatus.IDLE)

    async def _stage_downloading(
        self, deployment: Deployment, status: DeploymentStatus
    ) -> None:
        """Simulate downloading stage."""
        logger.info(
            f"Device {self.device.device_id} - DOWNLOADING {deployment.artifact_name}"
        )

        await self.deployments_client.update_deployment_status(
            self.device.auth_token, deployment.id, DeploymentState.DOWNLOADING
        )

        # Calculate download time based on virtual bandwidth
        download_time = self.profile.calculate_download_time(deployment.artifact_size)
        download_time = max(download_time, 2.0)  # Minimum 2 seconds

        # Simulate progress updates
        steps = 10
        for i in range(steps):
            progress = int((i + 1) / steps * 100)
            status.progress = progress
            status.status = "downloading"
            await self.db.save_deployment_status(status)

            logger.debug(f"Device {self.device.device_id} downloading: {progress}%")

            await asyncio.sleep(download_time / steps)

    async def _stage_installing(
        self, deployment: Deployment, status: DeploymentStatus
    ) -> None:
        """Simulate installing stage."""
        logger.info(
            f"Device {self.device.device_id} - INSTALLING {deployment.artifact_name}"
        )

        await self.deployments_client.update_deployment_status(
            self.device.auth_token, deployment.id, DeploymentState.INSTALLING
        )

        status.status = "installing"
        await self.db.save_deployment_status(status)

        # Simulate installation time (5-15 seconds)
        install_time = random.uniform(5, 15)
        await asyncio.sleep(install_time)

    async def _stage_rebooting(
        self, deployment: Deployment, status: DeploymentStatus
    ) -> None:
        """Simulate rebooting stage."""
        logger.info(f"Device {self.device.device_id} - REBOOTING")

        await self.deployments_client.update_deployment_status(
            self.device.auth_token, deployment.id, DeploymentState.REBOOTING
        )

        status.status = "rebooting"
        await self.db.save_deployment_status(status)

        # Simulate reboot time (3-8 seconds)
        reboot_time = random.uniform(3, 8)
        await asyncio.sleep(reboot_time)

    async def _stage_success(
        self, deployment: Deployment, status: DeploymentStatus
    ) -> None:
        """Handle successful deployment."""
        logger.info(
            f"Device {self.device.device_id} - SUCCESS - "
            f"Updated to {deployment.artifact_name}"
        )

        await self.deployments_client.update_deployment_status(
            self.device.auth_token, deployment.id, DeploymentState.SUCCESS
        )

        status.status = "success"
        status.completed_at = datetime.utcnow()
        await self.db.save_deployment_status(status)

        # Update device artifact name and rootfs-image.version
        # deployment.artifact_name already has full name (e.g., tcu-4g-lte-v1.1.0)
        self.device.inventory_data["artifact_name"] = deployment.artifact_name
        self.device.inventory_data["rootfs-image.version"] = deployment.artifact_name
        await self.db.save_device(self.device)

        # Send updated inventory immediately so Mender shows "Current software"
        await self.inventory_client.update_inventory(
            self.device.auth_token, self.device.inventory_data
        )
        logger.info(
            f"Device {self.device.device_id} - Inventory updated with new artifact_name"
        )
        # Note: No logs sent on success, only on failure

    async def _stage_failure(
        self, deployment: Deployment, status: DeploymentStatus, error_message: str
    ) -> None:
        """Handle failed deployment."""
        logger.warning(f"Device {self.device.device_id} - FAILURE - {error_message}")

        await self.deployments_client.update_deployment_status(
            self.device.auth_token,
            deployment.id,
            DeploymentState.FAILURE,
            substate=error_message,
        )

        status.status = "failure"
        status.completed_at = datetime.utcnow()
        status.error_message = error_message
        await self.db.save_deployment_status(status)

        # Send failure logs
        logs = self._generate_failure_logs(deployment, error_message)
        await self.deployments_client.send_deployment_logs(
            self.device.auth_token, deployment.id, logs
        )

    def _generate_failure_logs(
        self, deployment: Deployment, error_message: str
    ) -> List[Dict[str, Any]]:
        """Generate realistic failure logs."""
        now = datetime.utcnow().isoformat() + "Z"  # RFC3339 format required by Mender
        return [
            {
                "timestamp": now,
                "level": "info",
                "message": f"Starting update to {deployment.artifact_name}",
            },
            {"timestamp": now, "level": "info", "message": "Artifact downloaded"},
            {
                "timestamp": now,
                "level": "warning",
                "message": "Potential issue detected during installation",
            },
            {
                "timestamp": now,
                "level": "error",
                "message": f"Update failed: {error_message}",
            },
            {
                "timestamp": now,
                "level": "info",
                "message": "Initiating rollback to previous version",
            },
            {
                "timestamp": now,
                "level": "info",
                "message": "Rollback completed, system stable",
            },
        ]
