"""Rich live dashboard for the fleet simulator."""

import asyncio

import rich.box
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .stats import FleetStats


def _uptime(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render(stats: FleetStats) -> Group:
    snap = stats.snapshot()
    threads = snap["threads"]
    events = snap["events"]

    total_devices = sum(b.devices for b in threads.values())
    total_started = sum(b.started for b in threads.values())
    total_ok = sum(b.polls_ok for b in threads.values())
    total_429 = sum(b.rate_limited for b in threads.values())
    total_timeouts = sum(b.timeouts for b in threads.values())
    total_errors = sum(b.errors for b in threads.values())

    # ── Summary header ──────────────────────────────────────────────────
    hdr = Text(justify="left")
    hdr.append(f" Uptime: {_uptime(snap['elapsed'])}  │  ")
    hdr.append(f"Devices: {total_started:,}/{total_devices:,}  │  ")
    hdr.append(f"Polls OK: {total_ok:,}", style="green")
    hdr.append("  │  ")
    hdr.append(
        f"429s: {total_429:,}",
        style="bold yellow" if total_429 else "dim",
    )
    hdr.append("  │  ")
    hdr.append(
        f"Timeouts: {total_timeouts:,}",
        style="bold yellow" if total_timeouts else "dim",
    )
    hdr.append("  │  ")
    hdr.append(
        f"Errors: {total_errors:,}",
        style="bold red" if total_errors else "dim",
    )
    hdr.append("  │  ")
    hdr.append("q to quit", style="dim")

    # ── Per-thread table ────────────────────────────────────────────────
    tbl = Table(box=rich.box.SIMPLE_HEAD, show_edge=False, pad_edge=True)
    tbl.add_column("Thread", style="cyan", width=8, justify="right")
    tbl.add_column("Total", justify="right", width=8)
    tbl.add_column("Started", justify="right", style="green", width=9)
    tbl.add_column("Polls OK", justify="right", style="green", width=10)
    tbl.add_column("429s", justify="right", width=7)
    tbl.add_column("Timeouts", justify="right", width=10)
    tbl.add_column("Errors", justify="right", width=8)

    for tid in sorted(threads):
        b = threads[tid]
        tbl.add_row(
            str(tid),
            f"{b.devices:,}",
            f"{b.started:,}",
            f"{b.polls_ok:,}",
            f"[bold yellow]{b.rate_limited}[/]" if b.rate_limited else "[dim]0[/]",
            f"[bold yellow]{b.timeouts}[/]" if b.timeouts else "[dim]0[/]",
            f"[bold red]{b.errors}[/]" if b.errors else "[dim]0[/]",
        )

    # ── Recent events ───────────────────────────────────────────────────
    ev_lines = (
        "\n".join(f"[dim]{ts}[/]  {msg}" for ts, msg in events[:20])
        if events
        else "[dim]No events yet — waiting for first poll…[/]"
    )

    return Group(
        Panel(hdr, title="[bold cyan]Mender Fleet Simulator[/]", border_style="cyan"),
        Panel(tbl, title="Worker Threads", border_style="dim"),
        Panel(ev_lines, title="Events  [dim](429s · errors)[/]", border_style="dim"),
    )


async def dashboard_loop(
    live: Live,
    stats: FleetStats,
    stop: asyncio.Event,
) -> None:
    """Asyncio task: re-renders the live display every second until shutdown."""
    while not stop.is_set():
        try:
            live.update(render(stats))
        except Exception:
            pass
        await asyncio.sleep(1.0)
