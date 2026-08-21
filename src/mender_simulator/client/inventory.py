"""Mender Inventory Client."""

import aiohttp
import logging
from typing import Dict, Any, List, Optional

from .base import BaseClient
from .exceptions import AuthenticationError, RateLimitError, RequestTimeoutError

logger = logging.getLogger(__name__)


class InventoryClient(BaseClient):
    """Handles device inventory updates with Mender server."""

    def _format_inventory(self, inventory_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Format inventory data for Mender API.

        Mender expects inventory as a list of {name, value} objects.
        """
        formatted = []
        for key, value in inventory_data.items():
            if isinstance(value, list):
                # Lists are sent as-is
                formatted.append({"name": key, "value": value})
            elif isinstance(value, bool):
                formatted.append({"name": key, "value": str(value).lower()})
            else:
                formatted.append({"name": key, "value": str(value)})
        return formatted

    async def update_inventory(
        self, token: str, inventory_data: Dict[str, Any]
    ) -> bool:
        """
        Send inventory update to Mender server.

        Args:
            token: Authentication JWT token
            inventory_data: Device inventory attributes

        Returns:
            True if successful, False otherwise
        """
        await self._ensure_session()

        url = f"{self.server_url}/api/devices/v1/inventory/device/attributes"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        formatted_inventory = self._format_inventory(inventory_data)

        try:
            async with self._session.patch(
                url, json=formatted_inventory, headers=headers
            ) as response:
                if response.status == 200:
                    logger.debug("Inventory updated successfully")
                    return True
                elif response.status == 401:
                    logger.warning("Authentication token expired or invalid")
                    raise AuthenticationError("Token expired")
                elif response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        f"Rate limited during inventory update, "
                        f"retry after {retry_after}s",
                        retry_after=retry_after,
                        endpoint="inventory",
                    )
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Inventory update failed ({response.status}): {error_text}"
                    )
                    return False

        except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError) as e:
            raise RequestTimeoutError(str(e), endpoint="inventory")
        except aiohttp.ClientError as e:
            logger.error(f"Inventory update request failed: {e}")
            return False

    async def get_inventory(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get current device inventory from server.

        Args:
            token: Authentication JWT token

        Returns:
            Inventory data dict or None if failed
        """
        await self._ensure_session()

        url = f"{self.server_url}/api/devices/v1/inventory/device/attributes"

        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self._session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Convert from list format back to dict
                    return {item["name"]: item["value"] for item in data}
                else:
                    return None

        except aiohttp.ClientError as e:
            logger.error(f"Get inventory request failed: {e}")
            return None
