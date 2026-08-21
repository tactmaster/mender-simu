"""Configuration loading and validation utilities."""

import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any
from dataclasses import dataclass, field

MENDER_CONF_PATH = "/etc/mender/mender.conf"

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Server configuration."""

    url: str
    tenant_token: str
    poll_interval: int = 30
    personal_access_token: str = ""


@dataclass
class SimulatorConfig:
    """Simulator settings."""

    success_rate: float = 0.8
    log_file: str = "simulator.log"
    log_level: str = "INFO"
    database_path: str = "devices.db"
    num_threads: int = 4
    connection_limit: int = 25


@dataclass
class IndustryConfig:
    """Industry profile configuration."""

    name: str
    enabled: bool
    count: int
    bandwidth_kbps: int
    id_prefix: str
    id_format: str
    inventory: Dict[str, Any]
    preauth: bool = True
    extra_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    """Main configuration container."""

    server: ServerConfig
    simulator: SimulatorConfig
    industries: Dict[str, IndustryConfig]
    error_messages: list


def load_config(config_path: str = "config/config.yaml") -> Config:
    """
    Load and validate configuration from YAML file.

    Args:
        config_path: Path to configuration file

    Returns:
        Validated Config object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path, "r") as f:
        raw_config = yaml.safe_load(f)

    # Parse server config, falling back to /etc/mender/mender.conf
    server_data = raw_config.get("server", {})
    mender_conf = _load_mender_conf()
    server = ServerConfig(
        url=server_data.get("url")
        or mender_conf.get("ServerURL", "https://hosted.mender.io"),
        tenant_token=server_data.get("tenant_token")
        or mender_conf.get("TenantToken", ""),
        poll_interval=server_data.get("poll_interval", 30),
        personal_access_token=server_data.get("personal_access_token", ""),
    )

    # Parse simulator config
    sim_data = raw_config.get("simulator", {})
    simulator = SimulatorConfig(
        success_rate=sim_data.get("success_rate", 0.8),
        log_file=sim_data.get("log_file", "simulator.log"),
        log_level=sim_data.get("log_level", "INFO"),
        database_path=sim_data.get("database_path", "devices.db"),
        num_threads=sim_data.get("num_threads", 4),
        connection_limit=sim_data.get("connection_limit", 25),
    )

    # Parse industry profiles
    industries = {}
    for name, data in raw_config.get("industries", {}).items():
        # Extract known fields
        known_fields = {
            "enabled",
            "preauth",
            "count",
            "bandwidth_kbps",
            "id_prefix",
            "id_format",
            "inventory",
        }
        extra = {k: v for k, v in data.items() if k not in known_fields}

        industries[name] = IndustryConfig(
            name=name,
            enabled=data.get("enabled", False),
            count=data.get("count", 10),
            bandwidth_kbps=data.get("bandwidth_kbps", 500),
            id_prefix=data.get("id_prefix", "DEV"),
            id_format=data.get("id_format", "DEV-{serial}"),
            inventory=data.get("inventory", {}),
            preauth=data.get("preauth", True),
            extra_config=extra,
        )

    # Error messages
    error_messages = raw_config.get("error_messages", ["Unknown error during update"])

    config = Config(
        server=server,
        simulator=simulator,
        industries=industries,
        error_messages=error_messages,
    )

    _validate_config(config)
    logger.info(f"Configuration loaded from {config_path}")

    return config


def _load_mender_conf() -> Dict[str, Any]:
    """Load fallback values from /etc/mender/mender.conf if it exists."""
    path = Path(MENDER_CONF_PATH)
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        logger.info(f"Loaded fallback config from {MENDER_CONF_PATH}")
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read {MENDER_CONF_PATH}: {e}")
        return {}


def _validate_config(config: Config) -> None:
    """Validate configuration values."""
    if not config.server.url:
        raise ValueError("Server URL is required")

    if (
        not config.server.tenant_token
        or config.server.tenant_token == "YOUR_TENANT_TOKEN_HERE"
    ):
        logger.warning("Tenant token not configured - authentication will fail")

    if not config.server.personal_access_token:
        logger.warning(
            "personal_access_token not configured - device preauthorization "
            "is disabled. New devices will require manual acceptance in the "
            "Mender UI."
        )

    if config.server.poll_interval < 5:
        raise ValueError("Poll interval must be at least 5 seconds")

    if not 0 <= config.simulator.success_rate <= 1:
        raise ValueError("Success rate must be between 0 and 1")

    enabled_industries = [i for i in config.industries.values() if i.enabled]
    if not enabled_industries:
        logger.warning("No industries are enabled")


def get_enabled_industries(config: Config) -> Dict[str, IndustryConfig]:
    """Get only enabled industry profiles."""
    return {
        name: industry
        for name, industry in config.industries.items()
        if industry.enabled
    }
