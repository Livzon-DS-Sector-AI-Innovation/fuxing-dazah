from __future__ import annotations

from datetime import datetime

from app.modules.energy.adapters.base import BasePlatformAdapter, CollectResult


class PlatformBAdapter(BasePlatformAdapter):
    """平台 B 适配器"""

    platform_code = "platform_b"

    async def fetch_energy_data(
        self,
        device_codes: list[str],
        target_hour: datetime,
        api_endpoint: str,
    ) -> list[CollectResult]:
        # TODO: 等待提供 API 文档后实现
        raise NotImplementedError("平台 B 适配器尚未实现，请提供 API 文档")
