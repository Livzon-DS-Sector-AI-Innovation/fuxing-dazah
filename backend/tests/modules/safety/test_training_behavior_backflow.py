"""链4 回流单轮测试：隐患表三违作业行 → 违章档案幂等建行。

接缝（用户确认双接缝之①）：Bitable 直读 opener 协议替身——hazard/violation
两客户端均注入假实现，不触飞书。口径见
.scratch/s6-training-behavior-r1/spec.md。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior import backflow


def _hazard(no: str, category: str = "三违作业") -> dict:
    return {
        "record_id": f"rec-{no}",
        "fields": {
            "隐患编号": no,
            "隐患类别（AI）": category,
            "隐患描述（AI）": f"{no} 的三违描述",
            "检查日期": 1_762_934_400_000,
        },
    }


def _violation(no: str) -> dict:
    return {"record_id": f"v-{no}", "fields": {"关联隐患编号": no}}


class FakeClient:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.created: list[dict] = []

    async def list_all_records(self, **kwargs) -> list[dict]:
        return self.records

    async def create_record(self, fields: dict) -> dict:
        self.created.append(fields)
        return {"record_id": f"new-{len(self.created)}"}


def _opener(hazard_records: list[dict], violation_records: list[dict]):
    hazard_client = FakeClient(hazard_records)
    violation_client = FakeClient(violation_records)

    def open_client(domain: str, kind: str):
        if (domain, kind) == ("hazard", "hazard"):
            return hazard_client
        if (domain, kind) == ("training_behavior", "violation"):
            return violation_client
        raise BitableConfigError(f"未配置: {domain}/{kind}")

    return open_client, hazard_client, violation_client


class TestRunBackflowRound:
    async def test_creates_rows_for_new_violation_operation(self) -> None:
        opener, _, violation_client = _opener(
            [_hazard("YH-1"), _hazard("YH-2", category="设备设施")], []
        )
        outcome = await backflow.run_backflow_round(opener=opener)
        assert outcome["status"] == "ok"
        assert outcome["created"] == 1
        row = violation_client.created[0]
        assert row["关联隐患编号"] == "YH-1"
        assert row["违章描述"] == "YH-1 的三违描述"
        assert row["状态"] == "纠正中"

    async def test_idempotent_against_existing_nos(self) -> None:
        opener, _, violation_client = _opener(
            [_hazard("YH-1")], [_violation("YH-1")]
        )
        outcome = await backflow.run_backflow_round(opener=opener)
        assert outcome["created"] == 0
        assert violation_client.created == []

    async def test_hazard_domain_not_connected_is_soft_skip(self) -> None:
        opener, _, violation_client = _opener(
            [], [_violation("YH-x")]
        )

        def failing_opener(domain: str, kind: str):
            if kind == "hazard":
                raise BitableConfigError("hazard 域未接入")
            return opener(domain, kind)

        outcome = await backflow.run_backflow_round(opener=failing_opener)
        assert outcome["status"] == "not_connected"
        assert violation_client.created == []

    async def test_violation_domain_not_connected_is_soft_skip(self) -> None:
        def failing_opener(domain: str, kind: str):
            if (domain, kind) == ("training_behavior", "violation"):
                raise BitableConfigError("violation 域未接入")
            return _opener([_hazard("YH-1")], [])[0](domain, kind)

        outcome = await backflow.run_backflow_round(opener=failing_opener)
        assert outcome["status"] == "not_connected"
