"""票据 10：直读路径的 AI 审计不再传非 UUID 的 resource_id。

改造后逐条分析的对象是 FireAlarmView，其 id 等于飞书记录 ID（字符串），
而 ai_call_audits.resource_id 是 UUID 列  直接传会导致审计写库失败（生产落地时实测）。
本测试锁定：不传 resource_id，飞书记录 ID 改写到 extra。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from app.modules.safety.service.fire_alarm import analyst as analyst_module
from app.modules.safety.service.fire_alarm.reader import FireAlarmView

FEISHU_ID = "recvvbByaanxaw"


class RecordingScope:
    """替换 ai_audit_scope：记录调用参数，不做任何落库。"""

    def __init__(self, captured: list[dict[str, Any]], **kwargs: Any) -> None:
        self.captured = captured
        self.kwargs = kwargs

    def __enter__(self) -> RecordingScope:
        self.captured.append(self.kwargs)
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeAi:
    async def chat_parsed(
        self, *, messages: Any = None, expected_keys: Any = None,
        temperature: float = 0.3, **kw: Any,
    ) -> dict[str, Any]:
        return {
            "dimension": "设备设施",
            "reason_analysis": "原因分析",
            "rectification_direction": "整改方向",
        }


class _StubRetrieval:
    markdown = ""


class StubRetriever:
    def __init__(self, session: Any = None) -> None:
        pass

    async def retrieve(self, **kw: Any) -> _StubRetrieval:
        return _StubRetrieval()


def _view() -> FireAlarmView:
    return FireAlarmView(
        id=FEISHU_ID,
        feishu_record_id=FEISHU_ID,
        source="bitable",
        synced_at=datetime(2026, 9, 17, 3, 0, tzinfo=UTC),
        alarm_time=datetime(2026, 9, 14, 2, 0, tzinfo=UTC),
        alarm_type="火灾报警",
        department="动力车间",
        department_leader_name="张三",
        building="1号装置",
        location="压缩机房",
        alarm_nature="误报",
        cause_description="传感器老化误触发",
    )


async def test_per_record_audit_omits_resource_id_and_keeps_feishu_id(
    monkeypatch: Any,
) -> None:
    from app.modules.safety.knowledge import retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "SafetyKnowledgeRetriever", StubRetriever)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        analyst_module,
        "ai_audit_scope",
        lambda **kwargs: RecordingScope(captured, **kwargs),
    )

    analyst = analyst_module.FireAlarmAnalyst(session=None, ai_service=FakeAi())
    result = await analyst.analyze_per_records(cast(Any, [_view()]))

    assert FEISHU_ID in result
    assert len(captured) == 1
    scope = captured[0]
    assert scope["resource_type"] == "fire_alarm_record"
    assert "resource_id" not in scope, "resource_id 是 UUID 列，不能传飞书记录 ID"
    assert scope["extra"] == {"feishu_record_id": FEISHU_ID}
