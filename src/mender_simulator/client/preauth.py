"""Mender Preauthorization Client (Management API)."""

import asyncio
import aiohttp
import logging
from typing import Dict, Optional

from .base import BaseClient

logger = logging.getLogger(__name__)


class PreauthClient(BaseClient):
    """Preauthorizes devices via the Mender Management API.

    Requires a Personal Access Token (PAT) with management permissions.
    See: https://docs.mender.io/server-integration/preauthorizing-devices
    """

    def __init__(
        self,
        server_url: str,
        personal_access_token: str,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        super().__init__(server_url, session=session)
        self.personal_access_token = personal_access_token

    async def preauthorize_device(
        self, identity_data: Dict[str, str], public_key_pem: str
    ) -> bool:
        """Preauthorize a device on the Mender server.

        Calls POST /api/management/v2/devauth/devices so the device is
        automatically accepted when it connects for the first time.

        Args:
            identity_data: Device identity attributes (e.g. {"mac": "..."})
            public_key_pem: Device's RSA public key in PEM format

        Returns:
            True if preauthorized (or already preauthorized), False on error.
        """
        await self._ensure_session()

        url = f"{self.server_url}/api/management/v2/devauth/devices"
        headers = {
            "Authorization": f"Bearer {self.personal_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "identity_data": identity_data,
            "pubkey": public_key_pem,
        }

        backoff = 5
        for attempt in range(5):
            try:
                async with self._session.post(
                    url, json=payload, headers=headers
                ) as resp:
                    if resp.status == 201:
                        logger.debug(f"Device preauthorized: {identity_data}")
                        return True
                    elif resp.status == 409:
                        # Already exists with this identity/key — treat as success
                        logger.debug(f"Device already preauthorized: {identity_data}")
                        return True
                    elif resp.status == 429:
                        backoff = int(resp.headers.get("Retry-After", backoff))
                        logger.debug(f"Preauth rate limited, retrying in {backoff}s")
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 120)
                        continue
                    else:
                        body = await resp.text()
                        logger.error(
                            f"Preauth failed ({resp.status}) for "
                            f"{identity_data}: {body}"
                        )
                        return False

            except aiohttp.ClientError as e:
                logger.error(f"Preauth request failed for {identity_data}: {e}")
                return False

        logger.error(f"Preauth gave up after retries for {identity_data}")
        return False
