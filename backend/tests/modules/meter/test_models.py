"""meter 模块 ORM 模型结构测试。"""

from __future__ import annotations

from datetime import time
from typing import cast

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter.models import (
    CalibrationReport,
    Department,
    GasDetectorRecord,
    InstrumentRecord,
    MeterSettings,
)


class TestTableLayout:
    def test_schema_isolation(self) -> None:
        """所有业务表位于 meter schema 下。"""
        assert InstrumentRecord.__tablename__ == "instrument_records"
        assert InstrumentRecord.__table_args__[-1]["schema"] == "meter"
        assert GasDetectorRecord.__tablename__ == "gas_detector_records"
        assert GasDetectorRecord.__table_args__[-1]["schema"] == "meter"
        assert CalibrationReport.__tablename__ == "calibration_reports"
        assert CalibrationReport.__table_args__[-1]["schema"] == "meter"
        assert Department.__tablename__ == "departments"
        assert Department.__table_args__[-1]["schema"] == "meter"
        assert MeterSettings.__tablename__ == "meter_settings"
        assert MeterSettings.__table_args__[-1]["schema"] == "meter"

    def test_soft_delete_field_exists(self) -> None:
        """所有业务模型继承 BaseModel，具备软删除能力。"""
        for model in (InstrumentRecord, GasDetectorRecord, CalibrationReport, Department):
            assert hasattr(model, "is_deleted")


class TestInstrumentRecord:
    async def test_anomaly_flags_defaults_to_empty_dict(self, db_session: AsyncSession) -> None:
        """anomaly_flags 默认应为空 dict（flush 后生效）。"""
        record = InstrumentRecord(asset_number="A1", instrument_name="压力表")
        db_session.add(record)
        await db_session.flush()
        assert record.anomaly_flags == {}

    def test_reports_relationship(self) -> None:
        """器具应配置与报告的关联关系。"""
        assert InstrumentRecord.reports.property is not None


class TestCalibrationReport:
    def test_single_parent_check_constraint_declared(self) -> None:
        """报告必须恰好关联一个父记录（DB 级约束已声明）。"""
        table = cast(Table, CalibrationReport.__table__)
        names = [getattr(c, "name", "") for c in table.constraints]
        assert "ck_calibration_reports_single_parent" in names


class TestDepartment:
    async def test_defaults(self, db_session: AsyncSession) -> None:
        """部门默认空负责人列表、提醒开关关闭。"""
        dept = Department(source="instrument", name="质量部")
        db_session.add(dept)
        await db_session.flush()
        assert not dept.heads
        assert dept.auto_notify_enabled is False


class TestMeterSettings:
    async def test_default_notify_time(self, db_session: AsyncSession) -> None:
        """提醒时间默认为 17:45。"""
        settings = MeterSettings()
        db_session.add(settings)
        await db_session.flush()
        assert settings.notify_time == time(17, 45)
