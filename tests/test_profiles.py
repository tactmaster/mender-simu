"""Tests for industry profiles."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mender_simulator.simulation.profiles import IndustryProfile
from mender_simulator.utils.config import IndustryConfig


@pytest.fixture
def automotive_config():
    """Create automotive industry config."""
    return IndustryConfig(
        name="automotive",
        enabled=True,
        count=10,
        bandwidth_kbps=500,
        id_prefix="VIN",
        id_format="VIN-{serial}",
        inventory={
            "device_type": "tcu-4g-lte",
            "artifact_name": "v1.0.0",
            "kernel_version": "5.0.0",
            "oem_variant": ["standard", "premium"],
        },
        extra_config={"manufacturers": ["WVWZZZ", "3VWDP7"]},
    )


@pytest.fixture
def medical_config():
    """Create medical industry config."""
    return IndustryConfig(
        name="medical",
        enabled=True,
        count=5,
        bandwidth_kbps=2000,
        id_prefix="FDA",
        id_format="FDA-{serial}",
        inventory={
            "device_type": "patient-monitor-icu",
            "artifact_name": "v5.0.0",
            "compliance": ["FDA-510k", "CE-MDR"],
        },
        extra_config={"device_classes": ["II", "III"]},
    )


class TestIndustryProfile:
    """Tests for IndustryProfile."""

    def test_generate_automotive_identity(self, automotive_config):
        """Test automotive identity generation."""
        profile = IndustryProfile(automotive_config)

        identity = profile.generate_device_identity(0)

        assert "mac" in identity
        assert "vin" in identity
        assert "device_type" not in identity  # device_type is inventory only
        assert len(identity["vin"]) == 17  # VIN is 17 characters

    def test_generate_medical_identity(self, medical_config):
        """Test medical device identity generation."""
        profile = IndustryProfile(medical_config)

        identity = profile.generate_device_identity(0)

        # Medical identity only has mac and serial_number
        assert "mac" in identity
        assert "serial_number" in identity
        assert identity["serial_number"].startswith("MED")
        # fda_udi is NOT in identity (moved to inventory)
        assert "fda_udi" not in identity

    def test_generate_unique_identities(self, automotive_config):
        """Test that identities are unique."""
        profile = IndustryProfile(automotive_config)

        identities = [profile.generate_device_identity(i) for i in range(10)]
        vins = [id["vin"] for id in identities]

        # All VINs should be unique
        assert len(set(vins)) == len(vins)

    def test_generate_static_inventory(self, automotive_config):
        """Test static inventory generation."""
        profile = IndustryProfile(automotive_config)

        inventory = profile.generate_static_inventory("TEST-001")

        assert inventory["device_id"] == "TEST-001"
        assert inventory["industry"] == "automotive"
        assert inventory["device_type"] == "tcu-4g-lte"
        assert "simulator_version" in inventory
        # last_seen is telemetry, not in static inventory
        assert "last_seen" not in inventory

    def test_generate_static_inventory_enrichment(self, automotive_config):
        """Test that industry-specific static attributes are added."""
        profile = IndustryProfile(automotive_config)

        inventory = profile.generate_static_inventory("TEST-001")

        # Automotive-specific static attributes
        assert "oem_variant" in inventory
        assert "odometer_km" in inventory
        # battery_voltage is telemetry, not in static inventory
        assert "battery_voltage" not in inventory

    def test_update_telemetry(self, automotive_config):
        """Test telemetry update adds dynamic attributes."""
        profile = IndustryProfile(automotive_config)

        inventory = profile.generate_static_inventory("TEST-001")
        inventory = profile.update_telemetry(inventory)

        # Dynamic attributes should be present
        # Note: Mender is NOT real-time telemetry, only device status
        assert "last_seen" in inventory
        assert "odometer_km" in inventory


class TestDownloadTimeCalculation:
    """Tests for download time calculation."""

    def test_calculate_download_time(self, automotive_config):
        """Test download time calculation."""
        profile = IndustryProfile(automotive_config)

        # 500 KB/s bandwidth, 5MB file = ~10 seconds
        artifact_size = 5 * 1024 * 1024  # 5 MB
        download_time = profile.calculate_download_time(artifact_size)

        # Should be approximately 10 seconds (with jitter)
        assert 9 < download_time < 12

    def test_calculate_download_time_zero_bandwidth(self):
        """Test handling of zero bandwidth."""
        config = IndustryConfig(
            name="test",
            enabled=True,
            count=1,
            bandwidth_kbps=0,
            id_prefix="TST",
            id_format="TST-{serial}",
            inventory={},
        )
        profile = IndustryProfile(config)

        download_time = profile.calculate_download_time(1000000)

        assert download_time == 1.0  # Default minimum

    def test_calculate_download_time_small_file(self, automotive_config):
        """Test download time for small files."""
        profile = IndustryProfile(automotive_config)

        # Very small file
        download_time = profile.calculate_download_time(1024)

        # Should be very quick
        assert download_time < 1


class TestSuccessProbability:
    """Tests for success probability."""

    def test_medical_higher_success_rate(self, medical_config):
        """Test that medical devices have higher success rate."""
        profile = IndustryProfile(medical_config)
        assert profile.get_success_probability() == 0.95

    def test_automotive_default_success_rate(self, automotive_config):
        """Test default success rate for automotive."""
        profile = IndustryProfile(automotive_config)
        assert profile.get_success_probability() == 0.80

    def test_industrial_lower_success_rate(self):
        """Test that industrial devices have lower success rate."""
        config = IndustryConfig(
            name="industrial_iot",
            enabled=True,
            count=10,
            bandwidth_kbps=250,
            id_prefix="IND",
            id_format="IND-{serial}",
            inventory={},
        )
        profile = IndustryProfile(config)
        assert profile.get_success_probability() == 0.75

    def test_ev_charging_success_rate(self):
        """Test that EV charging devices have a specific success rate."""
        config = IndustryConfig(
            name="ev_charging",
            enabled=True,
            count=8,
            bandwidth_kbps=1000,
            id_prefix="EVC",
            id_format="EVC-{serial}",
            inventory={},
            extra_config={"networks": ["NET-WEST", "NET-EAST"]},
        )
        profile = IndustryProfile(config)
        assert profile.get_success_probability() == 0.78


class TestEVChargingProfile:
    """Tests for EV Charging profile."""

    @pytest.fixture
    def ev_charging_config(self):
        return IndustryConfig(
            name="ev_charging",
            enabled=True,
            count=8,
            bandwidth_kbps=1000,
            id_prefix="EVC",
            id_format="EVC-{serial}",
            inventory={
                "device_type": "ev-charger-ocpp-2.0",
                "artifact_name": "v1.2.0",
                "charger_types": ["ac-level2-7kW", "dc-fast-50kW"],
                "protocols": ["ocpp-2.0.1"],
                "connector_types": ["ccs2", "type2"],
            },
            extra_config={"networks": ["NET-WEST", "NET-EAST", "NET-CENTRAL"]},
        )

    def test_generate_ev_charging_identity(self, ev_charging_config):
        """Test EV charging station identity generation."""
        profile = IndustryProfile(ev_charging_config)

        identity = profile.generate_device_identity(0)

        assert "mac" in identity
        assert "evse_id" in identity
        assert identity["evse_id"].startswith("EVC-")

    def test_ev_charging_identity_unique(self, ev_charging_config):
        """Test that EV charging identities are unique."""
        profile = IndustryProfile(ev_charging_config)

        identities = [profile.generate_device_identity(i) for i in range(8)]
        evse_ids = [id["evse_id"] for id in identities]

        assert len(set(evse_ids)) == len(evse_ids)

    def test_ev_charging_static_inventory(self, ev_charging_config):
        """Test EV charging static inventory attributes."""
        profile = IndustryProfile(ev_charging_config)

        inventory = profile.generate_static_inventory("EVC-TEST-001")

        assert inventory["device_id"] == "EVC-TEST-001"
        assert inventory["industry"] == "ev_charging"
        assert inventory["device_type"] == "ev-charger-ocpp-2.0"
        assert "charger_type" in inventory
        assert "supported_protocols" in inventory
        assert "connector_type" in inventory
        assert "max_power_kw" in inventory
        assert "location_type" in inventory
        assert "sessions_total" in inventory

    def test_ev_charging_telemetry_update(self, ev_charging_config):
        """Test EV charging telemetry updates charger_status and sessions."""
        profile = IndustryProfile(ev_charging_config)

        inventory = profile.generate_static_inventory("EVC-TEST-001")
        inventory = profile.update_telemetry(inventory)

        assert "last_seen" in inventory
        assert "charger_status" in inventory
        assert inventory["charger_status"] in ["available", "charging", "faulted"]


class TestOffHighwayProfile:
    """Tests for off-highway machine profile."""

    @pytest.fixture
    def off_highway_config(self):
        return IndustryConfig(
            name="off_highway",
            enabled=True,
            count=6,
            bandwidth_kbps=300,
            id_prefix="PIN",
            id_format="PIN-{serial}",
            inventory={
                "device_type": "telematics-gateway-j1939",
                "artifact_name": "v1.0.0",
                "equipment_types": ["excavator", "bulldozer", "wheel_loader"],
                "protocols": ["j1939"],
            },
            extra_config={"manufacturers": ["CAT", "DEER"]},
        )

    def test_generate_off_highway_identity(self, off_highway_config):
        """Test off-highway machine identity generation."""
        profile = IndustryProfile(off_highway_config)

        identity = profile.generate_device_identity(0)

        assert "mac" in identity
        assert "pin" in identity
        assert len(identity["pin"]) == 17

    def test_off_highway_identity_unique(self, off_highway_config):
        """Test that off-highway PINs are unique."""
        profile = IndustryProfile(off_highway_config)

        identities = [profile.generate_device_identity(i) for i in range(6)]
        pins = [id["pin"] for id in identities]

        assert len(set(pins)) == len(pins)

    def test_off_highway_static_inventory(self, off_highway_config):
        """Test off-highway static inventory attributes."""
        profile = IndustryProfile(off_highway_config)

        inventory = profile.generate_static_inventory("PIN-TEST-001")

        assert inventory["device_id"] == "PIN-TEST-001"
        assert inventory["industry"] == "off_highway"
        assert inventory["device_type"] == "telematics-gateway-j1939"
        assert "equipment_type" in inventory
        assert "supported_protocols" in inventory
        assert "engine_hours" in inventory
        assert "fuel_capacity_liters" in inventory
        assert "fuel_level_percent" in inventory
        assert inventory["gps_enabled"] is True
        # Geo location is applied to every industry, including this one
        assert "geo-lat" in inventory
        assert "geo-lon" in inventory
        assert "geo-city" in inventory

    def test_off_highway_telemetry_update(self, off_highway_config):
        """Test off-highway telemetry increments engine hours and fuel."""
        profile = IndustryProfile(off_highway_config)

        inventory = profile.generate_static_inventory("PIN-TEST-001")
        initial_hours = inventory["engine_hours"]
        inventory = profile.update_telemetry(inventory)

        assert "last_seen" in inventory
        assert inventory["engine_hours"] >= initial_hours
        assert 0 <= inventory["fuel_level_percent"] <= 100

    def test_off_highway_success_rate(self):
        """Test that off-highway machines have a specific success rate."""
        config = IndustryConfig(
            name="off_highway",
            enabled=True,
            count=6,
            bandwidth_kbps=300,
            id_prefix="PIN",
            id_format="PIN-{serial}",
            inventory={},
            extra_config={"manufacturers": ["CAT", "DEER"]},
        )
        profile = IndustryProfile(config)
        assert profile.get_success_probability() == 0.72
