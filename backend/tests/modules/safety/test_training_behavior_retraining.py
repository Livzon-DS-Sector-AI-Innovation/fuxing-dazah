"""链5 定向培训要点卡：AI 插件 + 触发单轮测试。

接缝（用户确认双接缝）：① opener 替身（violation/training 两客户端注入）
② ai_service 构造注入（假 chat_parsed）。推送开关默认关=不调任何发送函数。
口径见 .scratch/s6-training-behavior-r1/spec.md 链5 节。
"""

from __future__ import annotations

from app.modules.safety.ai_violation_retraining import (
    ViolationRetrainingError,
    ViolationRetrainingInput,
    ViolationRetrainingPlugin,
)
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior import retraining

_RAW_AI = {
    "summary": "高处作业安全帽佩戴专项要点",
    "key_points": [
        "进入生产区必须正确佩戴安全帽并系紧下颏带",
        "高处作业前检查安全帽外观与有效期",
    ],
}


class FakeAIService:
    def __init__(self, raw: dict | Exception = _RAW_AI) -> None:
        self.raw = raw
        self.calls: list[dict] = []

    async def chat_parsed(self, *, messages, expected_keys, temperature=None):
        self.calls.append(
            {"messages": messages, "expected_keys": expected_keys}
        )
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


class FakeViolationClient:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.updated: list[tuple[str, dict]] = []

    async def list_all_records(self, **kwargs) -> list[dict]:
        return self.records

    async def update_record(self, record_id: str, fields: dict) -> None:
        self.updated.append((record_id, fields))


class FakeTrainingClient:
    def __init__(self, records: list[dict] | None = None) -> None:
        self.records: list[dict] = records or []
        self.created: list[dict] = []
        self.fail_create = False

    async def list_all_records(self, **kwargs) -> list[dict]:
        return self.records

    async def create_record(self, fields: dict) -> dict:
        if self.fail_create:
            raise RuntimeError("bitable write boom")
        self.created.append(fields)
        return {"record_id": f"t-{len(self.created)}"}


def _violation_row(
    rec_id: str = "recV1",
    *,
    handling: str | None = "停工培训",
    level: str | None = None,
    retraining_note: str | None = None,
    desc: str = "未佩戴安全帽登高作业",
) -> dict:
    fields: dict = {"违章描述": desc}
    if handling:
        fields["处理方式"] = handling
    if level:
        fields["违章等级"] = level
    if retraining_note:
        fields["定向培训"] = retraining_note
    return {"record_id": rec_id, "fields": fields}


def _opener(violation_records: list[dict]):
    violation_client = FakeViolationClient(violation_records)
    training_client = FakeTrainingClient()

    def open_client(domain: str, kind: str):
        if (domain, kind) == ("training_behavior", "violation"):
            return violation_client
        if (domain, kind) == ("training_behavior", "training"):
            return training_client
        raise BitableConfigError(f"未配置: {domain}/{kind}")

    return open_client, violation_client, training_client


# ── 插件 ────────────────────────────────────────────────────────


class TestPlugin:
    async def test_generate_returns_card(self) -> None:
        service = FakeAIService()
        plugin = ViolationRetrainingPlugin(service)
        output = await plugin.generate(
            ViolationRetrainingInput(
                description="未佩戴安全帽登高作业",
                category="操作违章",
                level="严重",
                handling="停工培训",
            )
        )
        assert output.summary == "高处作业安全帽佩戴专项要点"
        assert len(output.key_points) == 2
        assert "安全帽" in output.card_markdown
        # prompt 携带违章上下文
        user_msg = service.calls[0]["messages"][1]["content"]
        assert "未佩戴安全帽登高作业" in user_msg

    async def test_ai_failure_raises_plugin_error(self) -> None:
        plugin = ViolationRetrainingPlugin(FakeAIService(RuntimeError("boom")))
        try:
            await plugin.generate(
                ViolationRetrainingInput(description="x")
            )
            raise AssertionError("应抛 ViolationRetrainingError")
        except ViolationRetrainingError:
            pass


# ── 触发单轮 ────────────────────────────────────────────────────


class TestRunRetrainingRound:
    async def test_generates_card_and_training_row_push_off(self) -> None:
        opener, violation_client, training_client = _opener(
            [_violation_row("recV1")]
        )
        pushes: list[dict] = []

        async def send_card(**kwargs) -> None:
            pushes.append(kwargs)

        outcome = await retraining.run_retraining_round(
            opener=opener,
            ai_service=FakeAIService(),
            push_enabled=lambda: False,
            send_card=send_card,
        )
        assert outcome["status"] == "ok"
        assert outcome["generated"] == 1
        assert outcome["pushed"] == 0
        assert pushes == []  # 开关关：绝不发送

        rec_id, update_fields = violation_client.updated[0]
        assert rec_id == "recV1"
        assert update_fields["定向培训"].startswith("已生成待推送")
        assert "安全帽" in update_fields["定向培训"]

        training_row = training_client.created[0]
        assert training_row["培训类别"] == "专项培训"
        assert training_row["状态"] == "未开始"
        assert training_row["关联违章编号"] == "recV1"
        assert "安全帽" in training_row["备注"]

    async def test_needs_training_conditions(self) -> None:
        # 等级=严重（无停工培训）触发；一般+批评教育 不触发；已生成跳过
        opener, _, training_client = _opener([
            _violation_row("recA", handling=None, level="严重"),
            _violation_row("recB", handling="批评教育", level=None),
            _violation_row("recC", handling="停工培训",
                           retraining_note="已生成待推送（2026-10-22）"),
        ])
        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=FakeAIService(),
            push_enabled=lambda: False, send_card=None,
        )
        assert outcome["generated"] == 1
        assert training_client.created[0]["关联违章编号"] == "recA"

    async def test_push_on_sends_card(self) -> None:
        opener, _, _ = _opener([_violation_row("recV1")])
        pushes: list[dict] = []

        async def send_card(**kwargs) -> None:
            pushes.append(kwargs)

        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=FakeAIService(),
            push_enabled=lambda: True, send_card=send_card,
        )
        assert outcome["pushed"] == 1
        assert pushes and "安全帽" in pushes[0]["card_markdown"]

    async def test_ai_failure_skips_row_without_writes(self) -> None:
        opener, violation_client, training_client = _opener(
            [_violation_row("recV1")]
        )
        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=FakeAIService(RuntimeError("boom")),
            push_enabled=lambda: True, send_card=None,
        )
        assert outcome["status"] == "ok"
        assert outcome["generated"] == 0
        assert outcome["failed"] == 1
        assert violation_client.updated == []
        assert training_client.created == []

    async def test_domain_not_connected_soft_skip(self) -> None:
        def opener(domain: str, kind: str):
            raise BitableConfigError("未接入")

        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=FakeAIService(),
            push_enabled=lambda: False, send_card=None,
        )
        assert outcome["status"] == "not_connected"

    async def test_default_push_switch_is_off(self) -> None:
        assert retraining.default_push_enabled() is False

    async def test_batch_limit_defers_excess(self) -> None:
        rows = [
            _violation_row(f"rec{i}", level="严重") for i in range(7)
        ]
        opener, _, training_client = _opener(rows)
        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=FakeAIService(),
            push_enabled=lambda: False, send_card=None,
        )
        assert outcome["generated"] == retraining.BATCH_LIMIT
        assert outcome["deferred"] == 2
        assert len(training_client.created) == 5

    async def test_repair_marker_when_training_row_exists(self) -> None:
        violation_client = FakeViolationClient([_violation_row("recV1")])
        training_client = FakeTrainingClient()
        # 培训行已存在（标记曾写失败的自愈场景）
        training_client.records = [
            {"record_id": "t-old", "fields": {"关联违章编号": "recV1"}}
        ]

        def opener(domain: str, kind: str):
            if kind == "violation":
                return violation_client
            return training_client

        service = FakeAIService()
        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=service,
            push_enabled=lambda: False, send_card=None,
        )
        assert outcome["repaired"] == 1
        assert outcome["generated"] == 0
        assert service.calls == []  # 不重跑 AI
        assert training_client.created == []  # 不重复建行
        assert violation_client.updated[0][1]["定向培训"].startswith(
            "已生成待推送"
        )

    async def test_training_create_failure_leaves_no_marker_for_retry(self) -> None:
        opener, violation_client, training_client = _opener(
            [_violation_row("recV1")]
        )
        training_client.fail_create = True
        outcome = await retraining.run_retraining_round(
            opener=opener, ai_service=FakeAIService(),
            push_enabled=lambda: False, send_card=None,
        )
        assert outcome["failed"] == 1
        assert outcome["generated"] == 0
        assert violation_client.updated == []  # 无标记 → 下轮整体重试
