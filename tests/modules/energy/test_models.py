from __future__ import annotations

from app.modules.energy.models import (
    CollectStatus,
    EnergyData,
    EnergyDeviceConfig,
    EnergyType,
    MonitorLevel,
)


class TestEnergyDeviceConfig:
    def test_create_instance(self, sample_device_config_data):
        config = EnergyDeviceConfig(**sample_device_config_data)
        assert config.platform_code == "zhiheng"
        assert config.platform_device_code == "WD-001"
        assert config.energy_type == "water"
        assert config.is_enabled is True

    def test_default_values(self, sample_device_config_data):
        config = EnergyDeviceConfig(**sample_device_config_data)
        assert config.monitor_level == "normal"
        assert config.collection_interval == 60


class TestEnergyData:
    def test_create_instance(self):
        data = EnergyData(
            device_config_id="00000000-0000-0000-0000-000000000001",
            timestamp="2024-01-01T08:00:00",
            value=100.5,
            unit="m3",
        )
        assert data.value == 100.5
        assert data.unit == "m3"


class TestEnums:
    def test_energy_type_values(self):
        assert EnergyType.ELECTRICITY.value == "electricity"
        assert EnergyType.WATER.value == "water"
        assert EnergyType.GAS.value == "gas"

    def test_monitor_level_values(self):
        assert MonitorLevel.NORMAL.value == "normal"
        assert MonitorLevel.IMPORTANT.value == "important"
        assert MonitorLevel.URGENT.value == "urgent"

    def test_collect_status_values(self):
        assert CollectStatus.SUCCESS.value == "success"
        assert CollectStatus.PARTIAL.value == "partial"
        assert CollectStatus.FAILED.value == "failed"
