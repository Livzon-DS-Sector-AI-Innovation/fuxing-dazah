from __future__ import annotations

import pytest


@pytest.fixture
def sample_device_config_data():
    return {
        "platform_code": "platform_a",
        "platform_device_code": "WD-001",
        "device_name": "1号水表",
        "energy_type": "water",
        "api_endpoint": "/api/v1/water/hourly",
        "workshop": "发酵车间",
        "production_line": "发酵产线A",
        "monitor_level": "normal",
        "unit": "m3",
        "collection_interval": 60,
        "is_enabled": True,
    }
