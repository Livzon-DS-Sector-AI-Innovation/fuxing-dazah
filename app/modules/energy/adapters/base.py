from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class CollectResult:
    """单次采集结果"""

    def __init__(
        self,
        device_code: str,
        timestamp: datetime,
        value: float,
        unit: str = "",
        raw_data: dict[str, Any] | None = None,
    ) -> None:
        self.device_code = device_code
        self.timestamp = timestamp
        self.value = value
        self.unit = unit
        self.raw_data = raw_data


class BasePlatformAdapter(ABC):
    """三方平台适配器抽象基类"""

    platform_code: str
    platform_name: str = ""

    @abstractmethod
    async def fetch_energy_data(
        self,
        device_codes: list[str],
        target_hour: datetime,
        api_endpoint: str,
        is_daily: bool = False,
    ) -> list[CollectResult]:
        """从平台获取指定设备列表在目标小时的能耗数据

        Args:
            device_codes: 三方平台设备编码列表
            target_hour: 目标小时（如 2024-01-01 08:00 表示 08:00-09:00 的数据）
                         当 is_daily=True 时，表示目标日期，时间范围为当天 00:00 ~ 次日 00:00
            api_endpoint: API 路径
            is_daily: 是否为日汇总采集（全天范围而非单小时）

        Returns:
            采集结果列表，每个设备一条记录
        """
        ...
