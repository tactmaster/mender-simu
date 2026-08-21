"""Base HTTP client with shared session management and timeouts."""

import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)

#: Default timeout for all HTTP requests (60s total, 10s connect).
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10)


class BaseClient:
    """Base class for Mender API clients.

    Provides shared session management, timeouts, and cleanup logic.
    """

    def __init__(
        self, server_url: str, session: Optional[aiohttp.ClientSession] = None
    ):
        self.server_url = server_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session = session is None

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_session(self) -> None:
        """Ensure HTTP session is created with default timeout."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
            self._owns_session = True

    async def close(self) -> None:
        """Close the HTTP session if owned by this client."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
