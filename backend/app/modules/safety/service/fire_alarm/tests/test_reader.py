"""Ticket 01：FireAlarmView 忠实替身与读取器协议单测。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.service.fire_alarm import reader, renderer
from app.modules.safety.service.fire_alarm.aggregator import (
    aggregate_daily,
    aggregate_weekly,
)
from app.modules.safety.service.fire_alarm.daily_dm import build_alarm_card

TARGET_DATE = date(2026, 3, 12)
WEEK_START = date(2026, 3, 9)
WEEK_END = date(2026, 3, 15)
MS = int(datetime(2026, 3, 12, 2, 0, tzinfo=UTC).timestamp() * 1000)


def _record_data() -> dict[str, Any]:
    return {
        "alarm_time": datetime(2026, 3, 12, 2, 0, tzinfo=UTC),
        "alarm_type": "火灾报警",
        "department": "动力车间",
        "department_leader_name": "张三",
        "building": "1号装置",
        "location": "压缩机房",
        "alarm_nature": "误报",
        "cause_category": "设备故障",
        "cause_description": "传感器老化误触发",
        "ai_dimension": "equipment",
        "ai_reason_analysis": "传感器老化导致误报",
        "ai_rectification_direction": "更换传感器并定期校验",
        "ai_analyzed_at": datetime(2026, 3, 12, 3, 0, tzinfo=UTC),
    }


def _make_orm(record_id: str) -> FireAlarmRecord:
    data = _record_data()
    record = FireAlarmRecord(**data)
    record.id = uuid4()
    record.feishu_record_id = record_id
    record.source = "bitable"
    record.synced_at = datetime(2026, 3, 12, 3, 30, tzinfo=UTC)
    return record


def _make_view(record_id: str) -> reader.FireAlarmView:
    return reader.FireAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        source="bitable",
        synced_at=datetime(2026, 3, 12, 3, 30, tzinfo=UTC),
        **_record_data(),
    )


class _FixedDatetime:
    """冻结 renderer.datetime.now()，保证两份输出可比。"""

    @classmethod
    def now(cls) -> datetime:
        return datetime(2026, 3, 12, 17, 30)


class FakeReader:
    """读取器替身：证明协议可注入。"""

    async def get_records_by_date(self, target_date: date) -> list[reader.FireAlarmView]:
        return [_make_view("rec-day")]

    async def get_records_by_rolling_window(
        self, target_date: date
    ) -> tuple[list[reader.FireAlarmView], datetime, datetime]:
        start = datetime(2026, 3, 11, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 12, 9, 0, tzinfo=UTC)
        return [_make_view("rec-rolling")], start, end

    async def get_records_by_week(
        self, week_start: date, week_end: date
    ) -> list[reader.FireAlarmView]:
        return [_make_view("rec-week")]


def test_to_view_maps_fields_metadata_and_ai_columns() -> None:
    record = {
        "record_id": "rec001",
        "fields": {
            "报警时间": MS,
            "报警类型": "火灾报警",
            "报警部门负责人.部门": ["动力车间"],
            "报警部门负责人": [{"id": "ou_1", "name": "张三"}],
            "报警楼栋": "1号装置",
            "报警部位": "压缩机房",
            "报警性质": "误报",
            "报警原因分类": "设备故障",
            "具体报警原因": "传感器老化误触发",
            "AI维度": "设备设施",
            "AI原因分析": "传感器老化导致误报",
            "AI整改方向": "更换传感器并定期校验",
            "AI分析时间": MS,
        },
    }

    synced_at = datetime(2026, 3, 12, 4, 0, tzinfo=UTC)
    view = reader.to_view(record, synced_at=synced_at)

    assert view.id == "rec001"
    assert view.feishu_record_id == "rec001"
    assert view.source == "bitable"
    assert view.synced_at == synced_at
    assert view.alarm_time == datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
    assert view.alarm_type == "火灾报警"
    assert view.department == "动力车间"
    assert view.department_leader_name == "张三"
    assert view.building == "1号装置"
    assert view.location == "压缩机房"
    assert view.alarm_nature == "误报"
    assert view.cause_category == "设备故障"
    assert view.cause_description == "传感器老化误触发"
    assert view.ai_dimension == "equipment"
    assert view.ai_reason_analysis == "传感器老化导致误报"
    assert view.ai_rectification_direction == "更换传感器并定期校验"
    assert view.ai_analyzed_at == datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
    assert view.created_at is None
    assert view.updated_at is None
    assert view.is_deleted is False


def test_to_view_keeps_empty_ai_fields_empty() -> None:
    view = reader.to_view({"record_id": "rec002", "fields": {}})

    assert view.id == "rec002"
    assert view.alarm_time is None
    assert view.ai_dimension is None
    assert view.ai_reason_analysis is None
    assert view.ai_rectification_direction is None
    assert view.ai_analyzed_at is None


def test_reader_protocol_accepts_injected_fake() -> None:
    fake: reader.FireAlarmRecordsReader = FakeReader()
    assert isinstance(fake, reader.FireAlarmRecordsReader)


def test_view_is_faithful_substitute_for_aggregation_and_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer, "datetime", _FixedDatetime)

    orm_records = [_make_orm("rec001"), _make_orm("rec002")]
    view_records = [_make_view("rec001"), _make_view("rec002")]

    agg_orm_daily = aggregate_daily(orm_records, TARGET_DATE)
    agg_view_daily = aggregate_daily(cast(Any, view_records), TARGET_DATE)
    agg_orm_weekly = aggregate_weekly(orm_records, WEEK_START, WEEK_END)
    agg_view_weekly = aggregate_weekly(cast(Any, view_records), WEEK_START, WEEK_END)

    assert renderer.render_daily_report(agg_orm_daily, {}) == renderer.render_daily_report(
        agg_view_daily, {}
    )
    assert renderer.render_weekly_report(
        agg_orm_weekly, {}
    ) == renderer.render_weekly_report(agg_view_weekly, {})
    assert build_alarm_card(orm_records[0]) == build_alarm_card(view_records[0])
