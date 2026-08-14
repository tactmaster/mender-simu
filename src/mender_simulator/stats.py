"""Thread-safe fleet metrics collection."""

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Deque, List, Tuple


@dataclass
class ThreadBucket:
    devices: int = 0
    started: int = 0
    polls_ok: int = 0
    rate_limited: int = 0
    timeouts: int = 0
    errors: int = 0


# (time_str, rich-markup message)
EventEntry = Tuple[str, str]


class FleetStats:
    """Collects per-thread counters and a recent-event log.

    All methods are safe to call from any thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._threads: Dict[int, ThreadBucket] = {}
        self._events: Deque[EventEntry] = deque(maxlen=40)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_thread(self, thread_id: int, device_count: int) -> None:
        with self._lock:
            self._threads[thread_id] = ThreadBucket(devices=device_count)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_device_started(self, thread_id: int) -> None:
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id].started += 1

    def record_poll_ok(self, thread_id: int) -> None:
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id].polls_ok += 1

    def record_timeout(self, thread_id: int, endpoint: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id].timeouts += 1
            self._events.appendleft((
                ts,
                f"[yellow]TMO[/] T[cyan]{thread_id}[/] [dim]{endpoint}[/]",
            ))

    def record_429(self, thread_id: int, endpoint: str, retry_after: int) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id].rate_limited += 1
            self._events.appendleft((
                ts,
                f"[bold yellow]429[/] T[cyan]{thread_id}[/] "
                f"[yellow]{endpoint}[/] — backoff [bold yellow]{retry_after}s[/]",
            ))

    def record_error(self, thread_id: int, endpoint: str, detail: str = "") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        snippet = (detail[:60] + "…") if len(detail) > 60 else detail
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id].errors += 1
            self._events.appendleft((
                ts,
                f"[bold red]ERR[/] T[cyan]{thread_id}[/] "
                f"[red]{endpoint}[/] {snippet}",
            ))

    # ------------------------------------------------------------------
    # Read-out (snapshot copy, safe to use outside the lock)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "elapsed": time.monotonic() - self._start,
                "threads": {
                    tid: ThreadBucket(
                        b.devices, b.started, b.polls_ok, b.rate_limited, b.timeouts, b.errors
                    )
                    for tid, b in self._threads.items()
                },
                "events": list(self._events),
            }
