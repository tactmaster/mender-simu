"""Industry profiles for device identity and inventory generation."""

import random
from typing import Dict, Any
from datetime import datetime

from ..utils.config import IndustryConfig
from .geo_data import random_land_location, random_remote_site_location


class IndustryProfile:
    """Generates realistic device identities and inventory for each industry."""

    def __init__(self, config: IndustryConfig):
        self.config = config
        self.name = config.name

    def generate_device_identity(self, index: int) -> Dict[str, str]:
        """
        Generate unique device identity based on industry.

        Args:
            index: Device index within this industry

        Returns:
            Identity data dictionary
        """
        generators = {
            "automotive": self._generate_automotive_identity,
            "smart_buildings": self._generate_smart_buildings_identity,
            "medical": self._generate_medical_identity,
            "industrial_iot": self._generate_industrial_identity,
            "retail": self._generate_retail_identity,
            "ev_charging": self._generate_ev_charging_identity,
            "off_highway": self._generate_off_highway_identity,
        }

        generator = generators.get(self.name, self._generate_generic_identity)
        return generator(index)

    def generate_static_inventory(
        self, device_id: str, poll_interval: int = 30
    ) -> Dict[str, Any]:
        """
        Generate static inventory attributes (called once at device creation).

        Args:
            device_id: The device identifier
            poll_interval: Polling interval in seconds

        Returns:
            Static inventory data dictionary
        """
        base_inventory = dict(self.config.inventory)

        # Add common static attributes
        base_inventory["device_id"] = device_id
        base_inventory["industry"] = self.name
        base_inventory["simulator_version"] = "1.2.0"
        base_inventory["poll_interval_seconds"] = poll_interval

        # Assign a random real-world (land-based) location and a hostname,
        # matching the inventory attribute names real Mender devices report.
        base_inventory.update(random_land_location())
        base_inventory["hostname"] = f"{self.name}-{device_id[:8]}"

        # Format artifact_name as {device_type}-{version} for Mender compatibility
        version = base_inventory.get("artifact_name", "unknown")
        device_type = base_inventory.get("device_type", "unknown")
        full_artifact_name = f"{device_type}-{version}"
        base_inventory["artifact_name"] = full_artifact_name
        base_inventory["rootfs-image.version"] = full_artifact_name

        # Add industry-specific static attributes
        enrichers = {
            "automotive": self._enrich_automotive_static,
            "smart_buildings": self._enrich_smart_buildings_static,
            "medical": self._enrich_medical_static,
            "industrial_iot": self._enrich_industrial_static,
            "retail": self._enrich_retail_static,
            "ev_charging": self._enrich_ev_charging_static,
            "off_highway": self._enrich_off_highway_static,
        }

        enricher = enrichers.get(self.name)
        if enricher:
            enricher(base_inventory)

        return base_inventory

    def update_telemetry(self, inventory: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update telemetry/dynamic attributes (called on each poll).

        Args:
            inventory: Existing inventory to update

        Returns:
            Updated inventory with new telemetry values
        """
        # Update common dynamic attributes
        inventory["last_seen"] = datetime.utcnow().isoformat()

        # Add industry-specific telemetry
        updaters = {
            "automotive": self._update_automotive_telemetry,
            "smart_buildings": self._update_smart_buildings_telemetry,
            "medical": self._update_medical_telemetry,
            "industrial_iot": self._update_industrial_telemetry,
            "retail": self._update_retail_telemetry,
            "ev_charging": self._update_ev_charging_telemetry,
            "off_highway": self._update_off_highway_telemetry,
        }

        updater = updaters.get(self.name)
        if updater:
            updater(inventory)

        return inventory

    def calculate_download_time(self, content_length_bytes: int) -> float:
        """
        Calculate simulated download time based on virtual bandwidth.

        Args:
            content_length_bytes: Size of artifact in bytes

        Returns:
            Download time in seconds
        """
        bandwidth_bytes_per_sec = self.config.bandwidth_kbps * 1024
        if bandwidth_bytes_per_sec <= 0:
            return 1.0

        base_time = content_length_bytes / bandwidth_bytes_per_sec

        # Add some jitter (±10%)
        jitter = random.uniform(0.9, 1.1)
        return base_time * jitter

    # Identity generators

    def _generate_automotive_identity(self, index: int) -> Dict[str, str]:
        """Generate VIN-based identity for automotive."""
        manufacturers = self.config.extra_config.get(
            "manufacturers", ["WVWZZZ", "3VWDP7"]
        )
        manufacturer = random.choice(manufacturers)
        year = random.choice("ABCDEFGHJKLMNPRSTVWXY")  # VIN year codes
        serial = f"{index:06d}"

        vin = f"{manufacturer}{year}{serial}"[:17].ljust(17, "0")

        return {
            "mac": self._generate_mac(),
            "vin": vin,
        }

    def _generate_smart_buildings_identity(self, index: int) -> Dict[str, str]:
        """Generate identity for smart buildings."""
        oui_prefixes = self.config.extra_config.get(
            "oui_prefixes", ["00:1A:2B", "DC:A6:32"]
        )
        oui = random.choice(oui_prefixes)
        device_part = ":".join([f"{random.randint(0, 255):02X}" for _ in range(3)])
        mac = f"{oui}:{device_part}"
        serial_number = f"BMS{index:08d}"

        return {
            "mac": mac,
            "serial_number": serial_number,
        }

    def _generate_medical_identity(self, index: int) -> Dict[str, str]:
        """Generate identity for medical devices."""
        serial_number = f"MED{index:08d}"

        return {
            "mac": self._generate_mac(),
            "serial_number": serial_number,
        }

    def _generate_industrial_identity(self, index: int) -> Dict[str, str]:
        """Generate identity for industrial IoT."""
        serial_number = f"IND{index:08d}"

        return {
            "mac": self._generate_mac(),
            "serial_number": serial_number,
        }

    def _generate_retail_identity(self, index: int) -> Dict[str, str]:
        """Generate POS terminal identity for retail."""
        pos_sn = f"POS{index:08d}"

        return {
            "mac": self._generate_mac(),
            "pos_sn": pos_sn,
        }

    def _generate_ev_charging_identity(self, index: int) -> Dict[str, str]:
        """Generate identity for EV charging stations."""
        networks = self.config.extra_config.get(
            "networks", ["NET-WEST", "NET-EAST", "NET-CENTRAL"]
        )
        network = random.choice(networks)
        station_id = f"ST{index // 4:05d}"  # 4 ports per station
        port_id = f"P{(index % 4) + 1}"
        evse_id = f"EVC-{network}-{station_id}-{port_id}"

        return {
            "mac": self._generate_mac(),
            "evse_id": evse_id,
        }

    def _generate_off_highway_identity(self, index: int) -> Dict[str, str]:
        """Generate PIN-based identity for off-highway machines.

        Uses a Product Identification Number (PIN), the ISO 10261 analogue
        of a VIN used by construction/agriculture/mining equipment
        telematics (e.g. CAT, John Deere, Komatsu).
        """
        manufacturers = self.config.extra_config.get(
            "manufacturers", ["CAT", "DEER", "KMTS", "VOLV"]
        )
        manufacturer = random.choice(manufacturers)
        serial = f"{index:08d}"
        pin = f"{manufacturer}{serial}"[:17].ljust(17, "0")

        return {
            "mac": self._generate_mac(),
            "pin": pin,
        }

    def _generate_generic_identity(self, index: int) -> Dict[str, str]:
        """Generate generic device identity."""
        return {
            "mac": self._generate_mac(),
            "serial": f"DEV-{index:08d}",
        }

    # Inventory enrichers

    # Static inventory enrichers (called once at device creation)

    def _enrich_automotive_static(self, inventory: Dict[str, Any]) -> None:
        """Add static automotive attributes."""
        variants = self.config.inventory.get("oem_variant", ["standard"])
        inventory["oem_variant"] = random.choice(variants)
        # Initial odometer value (will increment in telemetry)
        inventory["odometer_km"] = random.randint(0, 200000)

    def _enrich_smart_buildings_static(self, inventory: Dict[str, Any]) -> None:
        """Add static smart building attributes."""
        zones = self.config.inventory.get("zone_types", ["hvac"])
        inventory["zone_type"] = random.choice(zones)
        inventory["floor"] = random.randint(1, 50)
        inventory["room_count"] = random.randint(1, 20)

    def _enrich_medical_static(self, inventory: Dict[str, Any]) -> None:
        """Add static medical device attributes."""
        device_classes = self.config.extra_config.get("device_classes", ["II", "III"])
        inventory["fda_device_class"] = random.choice(device_classes)
        compliance = self.config.inventory.get("compliance", ["FDA-510k"])
        inventory["compliance_standards"] = compliance
        inventory["calibration_due"] = "2025-06-15"
        inventory["software_validated"] = True

    def _enrich_industrial_static(self, inventory: Dict[str, Any]) -> None:
        """Add static industrial IoT attributes."""
        plants = self.config.extra_config.get("plants", ["PLANT-A", "PLANT-B"])
        inventory["plant_id"] = random.choice(plants)
        inventory["line"] = f"L{random.randint(1, 10):02d}"
        inventory["unit"] = f"U{random.randint(0, 99):03d}"
        protocols = self.config.inventory.get("protocols", ["modbus"])
        inventory["supported_protocols"] = protocols
        inventory["plc_connected"] = random.choice([True, False])

    def _enrich_retail_static(self, inventory: Dict[str, Any]) -> None:
        """Add static retail POS attributes."""
        regions = self.config.extra_config.get("regions", ["NA", "EU"])
        inventory["region"] = random.choice(regions)
        inventory["store_id"] = str(random.randint(1000, 9999))
        modules = self.config.inventory.get("payment_modules", ["chip"])
        inventory["payment_modules"] = modules
        inventory["receipt_printer"] = random.choice([True, False])

    def _enrich_ev_charging_static(self, inventory: Dict[str, Any]) -> None:
        """Add static EV charging station attributes."""
        charger_types = self.config.inventory.get(
            "charger_types", ["ac-level2-7kW", "dc-fast-50kW"]
        )
        inventory["charger_type"] = random.choice(charger_types)
        protocols = self.config.inventory.get("protocols", ["ocpp-2.0.1"])
        inventory["supported_protocols"] = protocols
        connectors = self.config.inventory.get("connector_types", ["ccs2", "type2"])
        inventory["connector_type"] = random.choice(connectors)
        inventory["max_power_kw"] = random.choice([3, 7, 11, 22, 50, 150])
        inventory["location_type"] = random.choice(
            ["highway", "urban", "shopping-center", "workplace", "residential"]
        )
        inventory["sessions_total"] = random.randint(0, 50000)

    def _enrich_off_highway_static(self, inventory: Dict[str, Any]) -> None:
        """Add static off-highway machine attributes."""
        equipment_types = self.config.inventory.get(
            "equipment_types",
            ["excavator", "bulldozer", "wheel_loader", "backhoe", "mining_truck"],
        )
        inventory["equipment_type"] = random.choice(equipment_types)
        protocols = self.config.inventory.get("protocols", ["j1939"])
        inventory["supported_protocols"] = protocols
        inventory["engine_hours"] = round(random.uniform(0, 15000), 1)
        inventory["fuel_capacity_liters"] = random.choice([200, 400, 600, 1000])
        inventory["fuel_level_percent"] = random.randint(40, 100)
        inventory["gps_enabled"] = True

        # Off-highway equipment operates at mine/quarry/farm sites, not
        # city centers — override the generic city-based geo location
        # already applied in generate_static_inventory().
        inventory.update(random_remote_site_location())

    # Dynamic attribute updaters (called on each poll)
    # Note: Mender is NOT a real-time telemetry system. These are device
    # status attributes that change infrequently, not sensor readings.

    def _update_automotive_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update automotive status attributes."""
        # Odometer only increments slowly (device status, not real-time)
        current_km = inventory.get("odometer_km", 0)
        inventory["odometer_km"] = current_km + random.randint(0, 10)

    def _update_smart_buildings_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update smart building status attributes."""
        # HVAC mode changes infrequently
        if random.random() < 0.1:  # 10% chance to change
            inventory["hvac_mode"] = random.choice(
                ["cooling", "heating", "idle", "auto"]
            )

    def _update_medical_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update medical device status attributes."""
        # Device operational status, not patient data
        pass  # Medical devices report static inventory only

    def _update_industrial_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update industrial IoT status attributes."""
        # Uptime increments (hours since last boot)
        current_uptime = inventory.get("uptime_hours", 0)
        inventory["uptime_hours"] = current_uptime + round(random.uniform(0.5, 1), 2)

    def _update_retail_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update retail POS status attributes."""
        # Device operational status only
        pass  # POS terminals report static inventory only

    def _update_ev_charging_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update EV charging station status attributes."""
        # Charging session counter increments slowly
        current_sessions = inventory.get("sessions_total", 0)
        if random.random() < 0.3:  # 30% chance of a new session since last poll
            inventory["sessions_total"] = current_sessions + 1
        # Charger availability status
        inventory["charger_status"] = random.choice(
            ["available", "charging", "available", "available", "faulted"]
        )

    def _update_off_highway_telemetry(self, inventory: Dict[str, Any]) -> None:
        """Update off-highway machine status attributes."""
        # Engine hours only increment while the machine is operating
        current_hours = inventory.get("engine_hours", 0)
        inventory["engine_hours"] = round(current_hours + random.uniform(0, 2), 1)

        # Fuel drains slowly, with occasional refuels back to near-full
        current_fuel = inventory.get("fuel_level_percent", 100)
        if random.random() < 0.1:  # 10% chance of a refuel since last poll
            inventory["fuel_level_percent"] = random.randint(90, 100)
        else:
            inventory["fuel_level_percent"] = max(
                0, current_fuel - random.uniform(0, 3)
            )

        if random.random() < 0.1:  # 10% chance to change
            inventory["machine_status"] = random.choice(
                ["idle", "operating", "maintenance"]
            )

    # Helpers

    def _generate_mac(self) -> str:
        """Generate random MAC address."""
        return ":".join([f"{random.randint(0, 255):02X}" for _ in range(6)])

    def get_success_probability(self) -> float:
        """Get success probability for updates based on industry."""
        # Medical devices should have higher success rate (more stable)
        if self.name == "medical":
            return 0.95
        # Industrial devices may have more failures due to harsh environments
        if self.name == "industrial_iot":
            return 0.75
        # EV chargers in outdoor/public locations are prone to connectivity issues
        if self.name == "ev_charging":
            return 0.78
        # Off-highway machines (mines, farms, remote job sites) often have
        # poor connectivity
        if self.name == "off_highway":
            return 0.72
        # Default
        return 0.80
