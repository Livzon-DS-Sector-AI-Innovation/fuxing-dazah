"""检定提醒、总览统计、日期聚合与飞书通知 service 层功能测试。

隔离策略：dev 库有大量存量到期记录，alerts 用唯一部门 + department 筛选；
send_calibration_reminders 用 get_notifiable_departments 打桩只处理测试部门。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter import repository as repo
from app.modules.meter import service
from tests.modules.meter.conftest import (
    create_department,
    create_gas_detector,
    create_instrument,
)


class TestCalibrationAlerts:
    async def test_days_before_zero_includes_overdue(self, db_session: AsyncSession) -> None:
        """days_before=0 时已过期记录应出现且 days_until_due 为负。"""
        dept = f"TEST-ALERT-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() - timedelta(days=10)
        )
        alerts = await service.get_calibration_alerts(
            db_session, days_before=0, department=dept
        )
        assert len(alerts) == 1
        assert alerts[0]["days_until_due"] == -10

    async def test_positive_days_before_excludes_overdue(self, db_session: AsyncSession) -> None:
        """未来窗口（days_before>0）不应包含已过期记录。"""
        dept = f"TEST-ALERT-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() - timedelta(days=10)
        )
        alerts = await service.get_calibration_alerts(
            db_session, days_before=30, department=dept
        )
        assert alerts == []

    async def test_includes_only_within_window(self, db_session: AsyncSession) -> None:
        """仅窗口内的记录出现在提醒中。"""
        dept = f"TEST-ALERT-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=20)
        )
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=60)
        )
        alerts = await service.get_calibration_alerts(
            db_session, days_before=30, department=dept
        )
        assert len(alerts) == 1
        assert alerts[0]["days_until_due"] == 20

    async def test_source_filter(self, db_session: AsyncSession) -> None:
        """source 筛选只返回对应数据源。"""
        dept = f"TEST-ALERT-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=5)
        )
        await create_gas_detector(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=5)
        )
        alerts = await service.get_calibration_alerts(
            db_session, source="instrument", department=dept
        )
        assert {a["source"] for a in alerts} == {"instrument"}
        assert len(alerts) == 1

    async def test_department_filter(self, db_session: AsyncSession) -> None:
        """部门筛选只返回指定部门记录。"""
        dept = f"TEST-ALERT-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=5)
        )
        await create_instrument(
            db_session, next_calibration_date=date.today() + timedelta(days=5)
        )
        alerts = await service.get_calibration_alerts(db_session, department=dept)
        assert len(alerts) == 1
        assert alerts[0]["department"] == dept

    async def test_alert_fields_shape(self, db_session: AsyncSession) -> None:
        """提醒项应包含 id/编号/位置等展示字段。"""
        inst = await create_instrument(
            db_session,
            location="一车间",
            next_calibration_date=date.today() + timedelta(days=3),
        )
        alerts = await service.get_calibration_alerts(db_session, department=inst.department)
        assert alerts[0]["id"] == str(inst.id)
        assert alerts[0]["serial_number"] == inst.serial_number
        assert alerts[0]["location"] == "一车间"


class TestMeterOverview:
    async def test_invalid_source_rejected(self, db_session: AsyncSession) -> None:
        """非法 source 应抛 ValueError。"""
        with pytest.raises(ValueError):
            await service.get_meter_overview(db_session, "other")

    async def test_source_selection(self, db_session: AsyncSession) -> None:
        """按 source 返回对应数据源的统计。"""
        dept = f"TEST-OV-{uuid4().hex[:8]}"
        await create_instrument(db_session, department=dept, status="停用")
        stats = await service.get_meter_overview(db_session, "instrument")
        assert stats["total"] >= 1
        detector_stats = await service.get_meter_overview(db_session, "gas_detector")
        assert "total" in detector_stats


class TestDateStats:
    async def test_tree_structure_and_order(self, db_session: AsyncSession) -> None:
        """日期聚合应组装为 年→月→日 嵌套树并按日期降序。"""
        from app.modules.meter.schemas import InstrumentFilter

        dept = f"TEST-DS-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, calibration_date=date(2026, 1, 15)
        )
        await create_instrument(
            db_session, department=dept, calibration_date=date(2026, 1, 15)
        )
        await create_instrument(
            db_session, department=dept, calibration_date=date(2026, 3, 2)
        )
        await create_instrument(
            db_session, department=dept, calibration_date=date(2025, 12, 1)
        )
        stats = await service.get_instrument_date_stats(
            db_session, InstrumentFilter(department=dept), "calibration_date"
        )
        assert stats["field"] == "calibration_date"
        years = stats["years"]
        assert [y["year"] for y in years] == [2026, 2025]
        jan = years[0]["months"][0]
        assert jan["month"] == 3
        assert jan["count"] == 1
        assert years[1]["months"][0]["month"] == 12

    async def test_gas_detector_date_stats(self, db_session: AsyncSession) -> None:
        """探测器日期聚合同样可用。"""
        from app.modules.meter.schemas import GasDetectorFilter

        dept = f"TEST-DSG-{uuid4().hex[:8]}"
        await create_gas_detector(
            db_session, department=dept, calibration_date=date(2026, 5, 5)
        )
        stats = await service.get_gas_detector_date_stats(
            db_session, GasDetectorFilter(department=dept), "calibration_date"
        )
        assert stats["years"][0]["year"] == 2026


class TestBuildDateStatsTree:
    def test_empty_rows(self) -> None:
        """空数据应返回空树。"""
        assert service._build_date_stats_tree([]) == []

    def test_aggregates_counts(self) -> None:
        """父级 count 应为子级之和。"""
        rows = [
            {"year": 2026, "month": 8, "day": 1, "count": 2},
            {"year": 2026, "month": 8, "day": 2, "count": 1},
            {"year": 2026, "month": 7, "day": 30, "count": 5},
        ]
        tree = service._build_date_stats_tree(rows)
        assert tree[0]["count"] == 8
        assert tree[0]["months"][0]["month"] == 8
        assert tree[0]["months"][0]["days"][0]["day"] == 2


class TestSendCalibrationReminders:
    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        enabled: bool = True,
        depts: list[Any] | None = None,
    ) -> AsyncMock:
        """打桩：全局开关、飞书发送、通知部门列表（隔离 dev 库存量部门）。"""
        monkeypatch.setattr(
            "app.core.config.get_settings",
            lambda: SimpleNamespace(METER_CALIBRATION_AUTO_NOTIFY_ENABLED=enabled),
        )
        send_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "app.platform.integrations.feishu.notification.send_user_card", send_mock
        )
        monkeypatch.setattr(
            repo, "get_notifiable_departments", AsyncMock(return_value=depts or [])
        )
        return send_mock

    async def test_no_notifiable_departments_does_nothing(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """没有可通知部门时直接返回全 0。"""
        send_mock = self._patch(monkeypatch, enabled=True, depts=[])
        result = await service.send_calibration_reminders(db_session)
        assert result == {"sent": 0, "skipped": 0, "errors": 0}
        send_mock.assert_not_awaited()

    async def test_global_switch_off_skips(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全局开关关闭时跳过发送。"""
        send_mock = self._patch(monkeypatch, enabled=False)
        result = await service.send_calibration_reminders(db_session)
        assert result == {"sent": 0, "skipped": 0, "errors": 0}
        send_mock.assert_not_awaited()

    async def test_sends_card_per_head(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """每个负责人各收到一封，标题含部门名。"""
        dept_name = f"TEST-NOTIFY-{uuid4().hex[:8]}"
        dept = await create_department(
            db_session,
            auto_notify_enabled=True,
            name=dept_name,
            heads=[
                {"name": "张三", "feishu_open_id": "ou_1"},
                {"name": "李四", "feishu_open_id": "ou_2"},
            ],
        )
        send_mock = self._patch(monkeypatch, enabled=True, depts=[dept])
        await create_instrument(
            db_session,
            department=dept_name,
            calibration_unit="市计量院",
            next_calibration_date=date.today() + timedelta(days=5),
        )
        result = await service.send_calibration_reminders(db_session)
        assert result["sent"] == 1
        assert send_mock.await_count == 2
        title = send_mock.await_args_list[0].kwargs["title"]
        assert dept_name in title

    async def test_skips_jiliangshi_and_stopped_records(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """计量室单位与停用记录不应出现在提醒中。"""
        dept_name = f"TEST-NOTIFY-{uuid4().hex[:8]}"
        dept = await create_department(
            db_session,
            auto_notify_enabled=True,
            name=dept_name,
            heads=[{"name": "张三", "feishu_open_id": "ou_1"}],
        )
        send_mock = self._patch(monkeypatch, enabled=True, depts=[dept])
        await create_instrument(
            db_session,
            department=dept_name,
            calibration_unit="计量室",
            next_calibration_date=date.today() + timedelta(days=3),
        )
        await create_instrument(
            db_session,
            department=dept_name,
            status="停用",
            next_calibration_date=date.today() + timedelta(days=3),
        )
        result = await service.send_calibration_reminders(db_session)
        assert result["sent"] == 0
        send_mock.assert_not_awaited()

    async def test_four_window_grouping(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """4 个时间窗口的分组标题应出现在卡片正文中。"""
        dept_name = f"TEST-NOTIFY-{uuid4().hex[:8]}"
        dept = await create_department(
            db_session,
            auto_notify_enabled=True,
            name=dept_name,
            heads=[{"name": "张三", "feishu_open_id": "ou_1"}],
        )
        send_mock = self._patch(monkeypatch, enabled=True, depts=[dept])
        # 每个窗口放一条：今天到期 / 未来 5 天 / 未来 20 天 / 未来 60 天
        await create_instrument(db_session, department=dept_name, next_calibration_date=date.today())
        await create_instrument(
            db_session, department=dept_name, next_calibration_date=date.today() + timedelta(days=5)
        )
        await create_instrument(
            db_session, department=dept_name, next_calibration_date=date.today() + timedelta(days=20)
        )
        await create_instrument(
            db_session, department=dept_name, next_calibration_date=date.today() + timedelta(days=60)
        )
        result = await service.send_calibration_reminders(db_session)
        assert result["sent"] == 1
        assert send_mock.await_args is not None
        content = send_mock.await_args.kwargs["content"]
        assert "今天到期" in content
        assert "未来 7 天到期" in content
        assert "未来 30 天到期" in content
        assert "未来 90 天到期" in content

    async def test_send_failure_counts_error(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """发送失败应计入 errors 而不是 sent。"""
        dept_name = f"TEST-NOTIFY-{uuid4().hex[:8]}"
        dept = await create_department(
            db_session,
            auto_notify_enabled=True,
            name=dept_name,
            heads=[{"name": "张三", "feishu_open_id": "ou_1"}],
        )
        self._patch(monkeypatch, enabled=True, depts=[dept])
        monkeypatch.setattr(
            "app.platform.integrations.feishu.notification.send_user_card",
            AsyncMock(return_value=False),
        )
        await create_instrument(
            db_session, department=dept_name, next_calibration_date=date.today() + timedelta(days=3)
        )
        result = await service.send_calibration_reminders(db_session)
        assert result["sent"] == 0
        assert result["errors"] == 1

    async def test_prefers_user_id_over_open_id(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """identity 有姓名→user_id 映射时优先用 user_id。"""
        from app.platform.identity.models import User

        dept_name = f"TEST-NOTIFY-{uuid4().hex[:8]}"
        dept = await create_department(
            db_session,
            auto_notify_enabled=True,
            name=dept_name,
            heads=[{"name": "张三", "feishu_open_id": "ou_fallback"}],
        )
        send_mock = self._patch(monkeypatch, enabled=True, depts=[dept])
        await create_instrument(
            db_session, department=dept_name, next_calibration_date=date.today() + timedelta(days=3)
        )
        db_session.add(User(name="张三", feishu_user_id="uid_zhangsan"))
        await db_session.flush()

        await service.send_calibration_reminders(db_session)
        assert send_mock.await_args is not None
        kwargs = send_mock.await_args.kwargs
        assert kwargs["open_id"] == "uid_zhangsan"
        assert kwargs["receive_id_type"] == "user_id"

    async def test_falls_back_to_open_id(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """identity 无映射时回退到负责人档案里的 open_id。"""
        dept_name = f"TEST-NOTIFY-{uuid4().hex[:8]}"
        dept = await create_department(
            db_session,
            auto_notify_enabled=True,
            name=dept_name,
            heads=[{"name": "无档案用户", "feishu_open_id": "ou_orphan"}],
        )
        send_mock = self._patch(monkeypatch, enabled=True, depts=[dept])
        await create_instrument(
            db_session, department=dept_name, next_calibration_date=date.today() + timedelta(days=3)
        )
        await service.send_calibration_reminders(db_session)
        assert send_mock.await_args is not None
        kwargs = send_mock.await_args.kwargs
        assert kwargs["open_id"] == "ou_orphan"
        assert kwargs["receive_id_type"] == "open_id"
