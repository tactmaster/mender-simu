"""Mender Deployments Client."""

import aiohttp
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from .base import BaseClient
from .exceptions import AuthenticationError, RateLimitError, RequestTimeoutError

logger = logging.getLogger(__name__)


class DeploymentState(Enum):
    """Possible deployment states."""

    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    REBOOTING = "rebooting"
    SUCCESS = "success"
    FAILURE = "failure"
    ALREADY_INSTALLED = "already-installed"


@dataclass
class Deployment:
    """Represents a pending deployment."""

    id: str
    artifact_name: str
    artifact_uri: str
    artifact_size: int


class DeploymentsClient(BaseClient):
    """Handles deployment checks and status updates with Mender server."""

    async def check_for_deployment(
        self, token: str, device_provides: dict
    ) -> Optional[Deployment]:
        """
        Check for pending deployments (Deployments API v2).

        Args:
            token: Authentication JWT token
            device_provides: Dict of device attributes (device_type, artifact_name,
                             rootfs-image.checksum, etc.)

        Returns:
            Deployment object if available, None otherwise
        """
        await self._ensure_session()

        url = f"{self.server_url}/api/devices/v2/deployments/device/deployments/next"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {"device_provides": device_provides, "update_control_map": False}

        try:
            async with self._session.post(
                url, headers=headers, json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    artifact = data.get("artifact", {})

                    deployment = Deployment(
                        id=data.get("id", ""),
                        artifact_name=artifact.get("artifact_name", ""),
                        artifact_uri=artifact.get("source", {}).get("uri", ""),
                        artifact_size=artifact.get("source", {}).get("size", 0),
                    )

                    logger.info(f"Deployment available: {deployment.artifact_name}")
                    return deployment

                elif response.status == 204:
                    # No deployment available
                    return None
                elif response.status == 401:
                    logger.warning("Authentication token expired or invalid")
                    raise AuthenticationError("Token expired")
                elif response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        f"Rate limited during deployment check, "
                        f"retry after {retry_after}s",
                        retry_after=retry_after,
                        endpoint="deployments/check",
                    )
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Deployment check failed ({response.status}): {error_text}"
                    )
                    return None

        except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError) as e:
            raise RequestTimeoutError(str(e), endpoint="deployments")
        except aiohttp.ClientError as e:
            logger.error(f"Deployment check request failed: {e}")
            return None

    async def update_deployment_status(
        self,
        token: str,
        deployment_id: str,
        state: DeploymentState,
        substate: Optional[str] = None,
    ) -> bool:
        """
        Update deployment status.

        Args:
            token: Authentication JWT token
            deployment_id: Deployment ID
            state: New deployment state
            substate: Optional substate message

        Returns:
            True if successful, False otherwise
        """
        await self._ensure_session()

        url = (
            f"{self.server_url}/api/devices/v1/deployments"
            f"/device/deployments/{deployment_id}/status"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {"status": state.value}
        if substate:
            payload["substate"] = substate

        try:
            async with self._session.put(
                url, json=payload, headers=headers
            ) as response:
                if response.status in (200, 204):
                    logger.debug(
                        f"Deployment {deployment_id} status updated to {state.value}"
                    )
                    return True
                elif response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        f"Rate limited during status update, "
                        f"retry after {retry_after}s",
                        retry_after=retry_after,
                        endpoint="deployments/status",
                    )
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Status update failed ({response.status}): {error_text}"
                    )
                    return False

        except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError) as e:
            raise RequestTimeoutError(str(e), endpoint="deployments/status")
        except aiohttp.ClientError as e:
            logger.error(f"Status update request failed: {e}")
            return False

    async def send_deployment_logs(
        self, token: str, deployment_id: str, logs: List[Dict[str, Any]]
    ) -> bool:
        """
        Send deployment logs to server.

        Args:
            token: Authentication JWT token
            deployment_id: Deployment ID
            logs: List of log entries with timestamp, level, message

        Returns:
            True if successful, False otherwise
        """
        await self._ensure_session()

        url = (
            f"{self.server_url}/api/devices/v1/deployments"
            f"/device/deployments/{deployment_id}/log"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {"messages": logs}

        try:
            async with self._session.put(
                url, json=payload, headers=headers
            ) as response:
                if response.status in (200, 204):
                    logger.debug(f"Logs sent for deployment {deployment_id}")
                    return True
                elif response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        f"Rate limited during log upload, retry after {retry_after}s",
                        retry_after=retry_after,
                        endpoint="deployments/logs",
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"Log upload failed ({response.status}): {error_text}")
                    return False

        except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError) as e:
            raise RequestTimeoutError(str(e), endpoint="deployments/logs")
        except aiohttp.ClientError as e:
            logger.error(f"Log upload request failed: {e}")
            return False

    async def download_artifact(
        self, token: str, artifact_uri: str, progress_callback=None
    ) -> bool:
        """
        Simulate downloading an artifact (reads headers for size, does not
        actually download).

        Args:
            token: Authentication JWT token
            artifact_uri: URI to download artifact from
            progress_callback: Optional callback for progress updates

        Returns:
            True if artifact is accessible, False otherwise
        """
        await self._ensure_session()

        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self._session.head(artifact_uri, headers=headers) as response:
                if response.status == 200:
                    content_length = response.headers.get("Content-Length", "0")
                    logger.debug(f"Artifact accessible, size: {content_length} bytes")
                    return True
                else:
                    logger.error(f"Artifact not accessible ({response.status})")
                    return False

        except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectorError) as e:
            raise RequestTimeoutError(str(e), endpoint="deployments/artifact")
        except aiohttp.ClientError as e:
            logger.error(f"Artifact download check failed: {e}")
            return False
