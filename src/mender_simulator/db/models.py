"""Data models for device persistence."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
import json


class DeviceStatus(str, Enum):
    """Possible device states."""

    IDLE = "idle"
    UPDATING = "updating"


@dataclass
class Device:
    """Represents a simulated Mender device."""

    device_id: str
    identity_data: Dict[str, str]
    rsa_private_key: str
    rsa_public_key: str
    industry_profile: str
    current_status: str = DeviceStatus.IDLE
    auth_token: Optional[str] = None
    preauthorized: bool = False
    inventory_data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_poll: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert device to dictionary for database storage."""
        return {
            "device_id": self.device_id,
            "identity_data": json.dumps(self.identity_data),
            "rsa_private_key": self.rsa_private_key,
            "rsa_public_key": self.rsa_public_key,
            "industry_profile": self.industry_profile,
            "current_status": self.current_status,
            "auth_token": self.auth_token,
            "preauthorized": int(self.preauthorized),
            "inventory_data": json.dumps(self.inventory_data),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Device":
        """Create device from database row."""
        return cls(
            device_id=data["device_id"],
            identity_data=json.loads(data["identity_data"]),
            rsa_private_key=data["rsa_private_key"],
            rsa_public_key=data["rsa_public_key"],
            industry_profile=data["industry_profile"],
            current_status=data["current_status"],
            auth_token=data["auth_token"],
            preauthorized=bool(data.get("preauthorized", 0)),
            inventory_data=(
                json.loads(data["inventory_data"]) if data["inventory_data"] else {}
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            last_poll=(
                datetime.fromisoformat(data["last_poll"]) if data["last_poll"] else None
            ),
        )

    def get_identity_string(self) -> str:
        """Get identity data as JSON string for Mender API."""
        return json.dumps(self.identity_data)


@dataclass
class DeploymentStatus:
    """Tracks deployment status for a device."""

    device_id: str
    deployment_id: str
    artifact_name: str
    status: str  # downloading, installing, rebooting, success, failure
    progress: int = 0  # 0-100
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "device_id": self.device_id,
            "deployment_id": self.deployment_id,
            "artifact_name": self.artifact_name,
            "status": self.status,
            "progress": self.progress,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeploymentStatus":
        """Create from database row."""
        return cls(
            device_id=data["device_id"],
            deployment_id=data["deployment_id"],
            artifact_name=data["artifact_name"],
            status=data["status"],
            progress=data["progress"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data["completed_at"]
                else None
            ),
            error_message=data["error_message"],
        )
