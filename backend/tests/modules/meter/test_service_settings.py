"""全局设置 service 层功能测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter import service


class TestGetMeterSettings:
    async def test_creates_default_on_first_call(self, db_session: AsyncSession) -> None:
        """首次调用不存在配置行，自动创建默认 17:45。"""
        result = await service.get_meter_settings(db_session)
        assert result == {"notify_time": "17:45"}

    async def test_returns_updated_value(self, db_session: AsyncSession) -> None:
        """更新后再读取应返回新值。"""
        await service.update_meter_settings(db_session, "08:30")
        result = await service.get_meter_settings(db_session)
        assert result == {"notify_time": "08:30"}


class TestUpdateMeterSettings:
    async def test_valid_time(self, db_session: AsyncSession) -> None:
        """合法时间应更新成功。"""
        result = await service.update_meter_settings(db_session, "09:15")
        assert result == {"notify_time": "09:15"}

    @pytest.mark.parametrize("bad", ["abc", "17点45", "25:99", "12:60", "-1:00"])
    async def test_invalid_time_rejected(self, db_session: AsyncSession, bad: str) -> None:
        """非法格式或越界时间应抛 ValueError。"""
        with pytest.raises(ValueError):
            await service.update_meter_settings(db_session, bad)
