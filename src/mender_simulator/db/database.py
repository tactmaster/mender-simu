"""Database manager for async SQLite operations."""

import aiosqlite
import logging
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from .models import Device, DeploymentStatus

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async SQLite database manager for device persistence."""

    def __init__(self, db_path: str = "devices.db"):
        self.db_path = Path(db_path)
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Initialize database connection and create tables."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        # WAL mode allows concurrent readers + one writer across threads
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")

    async def close(self) -> None:
        """Close database connection gracefully."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    async def _create_tables(self) -> None:
        """Create required database tables if they don't exist."""
        await self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                identity_data TEXT NOT NULL,
                rsa_private_key TEXT NOT NULL,
                rsa_public_key TEXT NOT NULL,
                industry_profile TEXT NOT NULL,
                current_status TEXT DEFAULT 'idle',
                auth_token TEXT,
                preauthorized INTEGER NOT NULL DEFAULT 0,
                inventory_data TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_poll TEXT
            );

            CREATE TABLE IF NOT EXISTS deployment_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                deployment_id TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                FOREIGN KEY (device_id) REFERENCES devices(device_id),
                UNIQUE(device_id, deployment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_devices_industry ON devices(industry_profile);
            CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(current_status);
            CREATE INDEX IF NOT EXISTS idx_deployment_device ON deployment_status(device_id);
        """)
        await self._connection.commit()

        # Migrate existing DBs: add preauthorized column if missing
        async with self._connection.execute(
            "SELECT name FROM pragma_table_info('devices') WHERE name='preauthorized'"
        ) as cursor:
            if not await cursor.fetchone():
                await self._connection.execute(
                    "ALTER TABLE devices ADD COLUMN preauthorized INTEGER NOT NULL DEFAULT 0"
                )
                await self._connection.commit()

    async def save_device(self, device: Device) -> None:
        """Insert or update a device in the database."""
        device.updated_at = datetime.utcnow()
        data = device.to_dict()

        await self._connection.execute("""
            INSERT OR REPLACE INTO devices (
                device_id, identity_data, rsa_private_key, rsa_public_key,
                industry_profile, current_status, auth_token, preauthorized,
                inventory_data, created_at, updated_at, last_poll
            ) VALUES (
                :device_id, :identity_data, :rsa_private_key, :rsa_public_key,
                :industry_profile, :current_status, :auth_token, :preauthorized,
                :inventory_data, :created_at, :updated_at, :last_poll
            )
        """, data)
        await self._connection.commit()
        logger.debug(f"Device saved: {device.device_id}")

    async def get_device(self, device_id: str) -> Optional[Device]:
        """Retrieve a device by ID."""
        async with self._connection.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Device.from_dict(dict(row))
        return None

    async def get_all_devices(self) -> List[Device]:
        """Retrieve all devices from the database."""
        async with self._connection.execute("SELECT * FROM devices") as cursor:
            rows = await cursor.fetchall()
        return [Device.from_dict(dict(row)) for row in rows]

    async def get_devices_by_industry(self, industry: str) -> List[Device]:
        """Retrieve all devices for a specific industry profile."""
        async with self._connection.execute(
            "SELECT * FROM devices WHERE industry_profile = ?", (industry,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [Device.from_dict(dict(row)) for row in rows]

    async def delete_device(self, device_id: str) -> bool:
        """Delete a device from the database."""
        cursor = await self._connection.execute(
            "DELETE FROM devices WHERE device_id = ?", (device_id,)
        )
        await self._connection.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"Device deleted: {device_id}")
        return deleted

    async def update_device_status(self, device_id: str, status: str) -> None:
        """Update device status."""
        await self._connection.execute(
            "UPDATE devices SET current_status = ?, updated_at = ? WHERE device_id = ?",
            (status, datetime.utcnow().isoformat(), device_id)
        )
        await self._connection.commit()

    async def update_device_auth_token(self, device_id: str, token: Optional[str]) -> None:
        """Update device authentication token."""
        await self._connection.execute(
            "UPDATE devices SET auth_token = ?, updated_at = ? WHERE device_id = ?",
            (token, datetime.utcnow().isoformat(), device_id)
        )
        await self._connection.commit()

    async def update_last_poll(self, device_id: str) -> None:
        """Update the last poll timestamp for a device."""
        now = datetime.utcnow().isoformat()
        await self._connection.execute(
            "UPDATE devices SET last_poll = ?, updated_at = ? WHERE device_id = ?",
            (now, now, device_id)
        )
        await self._connection.commit()

    async def count_devices(self) -> int:
        """Count total devices in database."""
        async with self._connection.execute("SELECT COUNT(*) FROM devices") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_devices_by_industry(self) -> dict:
        """Count devices grouped by industry."""
        counts = {}
        async with self._connection.execute(
            "SELECT industry_profile, COUNT(*) FROM devices GROUP BY industry_profile"
        ) as cursor:
            async for row in cursor:
                counts[row[0]] = row[1]
        return counts

    # Deployment status methods
    async def save_deployment_status(self, status: DeploymentStatus) -> None:
        """Save or update deployment status."""
        data = status.to_dict()
        await self._connection.execute("""
            INSERT OR REPLACE INTO deployment_status (
                device_id, deployment_id, artifact_name, status,
                progress, started_at, completed_at, error_message
            ) VALUES (
                :device_id, :deployment_id, :artifact_name, :status,
                :progress, :started_at, :completed_at, :error_message
            )
        """, data)
        await self._connection.commit()

    async def get_deployment_status(
        self, device_id: str, deployment_id: str
    ) -> Optional[DeploymentStatus]:
        """Get deployment status for a device."""
        async with self._connection.execute(
            "SELECT * FROM deployment_status WHERE device_id = ? AND deployment_id = ?",
            (device_id, deployment_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return DeploymentStatus.from_dict(dict(row))
        return None

    async def get_active_deployments(self) -> List[DeploymentStatus]:
        """Get all active (non-completed) deployments."""
        async with self._connection.execute(
            "SELECT * FROM deployment_status WHERE status NOT IN ('success', 'failure')"
        ) as cursor:
            rows = await cursor.fetchall()
        return [DeploymentStatus.from_dict(dict(row)) for row in rows]
