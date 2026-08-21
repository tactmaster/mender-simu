"""Mender Authentication Client."""

import asyncio
import aiohttp
import logging
import json
from typing import Optional

from .base import BaseClient
from ..utils.crypto import sign_data
from .exceptions import DeviceNotAcceptedError, RateLimitError, RequestTimeoutError

logger = logging.getLogger(__name__)


class AuthClient(BaseClient):
    """Handles device authentication with Mender server."""

    def __init__(
        self,
        server_url: str,
        tenant_token: str,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.tenant_token = tenant_token
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session = session is None

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_session(self) -> None:
        """Ensure HTTP session is created."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True

    async def close(self) -> None:
        """Close the HTTP session if owned by this client."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def authenticate(
        self, identity_data: dict, public_key_pem: str, private_key_pem: str
    ) -> Optional[str]:
        """
        Authenticate device with Mender server.

        Args:
            identity_data: Device identity attributes
            public_key_pem: Device's public key in PEM format
            private_key_pem: Device's private key for signing

        Returns:
            JWT token if successful, None otherwise
        """
        await self._ensure_session()

        url = f"{self.server_url}/api/devices/v1/authentication/auth_requests"

        # Prepare the authentication request body
        auth_request = {
            "id_data": json.dumps(identity_data),
            "pubkey": public_key_pem,
            "tenant_token": self.tenant_token,
        }

        # Sign the request body — offloaded to thread pool so RSA doesn't
        # block the event loop
        request_body = json.dumps(auth_request, separators=(",", ":"))
        loop = asyncio.get_running_loop()
        signature = await loop.run_in_executor(
            None, sign_data, private_key_pem, request_body.encode("utf-8")
        )

        headers = {"Content-Type": "application/json", "X-MEN-Signature": signature}

        logger.debug(f"Auth request to: {url}")

        try:
            async with self._session.post(
                url, data=request_body, headers=headers
            ) as response:
                if response.status == 200:
                    token = await response.text()
                    logger.info(
                        "Device authenticated successfully: %s",
                        identity_data.get("mac", identity_data),
                    )
                    return token
                elif response.status == 401:
                    logger.debug(f"Device not accepted/preauthorized: {identity_data}")
                    raise DeviceNotAcceptedError("Device not accepted")
                elif response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        f"Rate limited during auth, retry after {retry_after}s",
                        retry_after=retry_after,
                        endpoint="auth",
                    )
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Authentication failed ({response.status}): {error_text}"
                    )
                    return None

        except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError) as e:
            raise RequestTimeoutError(str(e), endpoint="auth")
        except aiohttp.ClientError as e:
            logger.error(f"Authentication request failed: {e}")
            return None

    async def check_token_valid(self, token: str) -> bool:
        """
        Check if the authentication token is still valid.

        Args:
            token: JWT authentication token

        Returns:
            True if token is valid, False otherwise
        """
        await self._ensure_session()

        # Try to access a protected endpoint
        url = f"{self.server_url}/api/devices/v1/inventory/device/attributes"

        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self._session.get(url, headers=headers) as response:
                return response.status != 401
        except aiohttp.ClientError:
            return False
