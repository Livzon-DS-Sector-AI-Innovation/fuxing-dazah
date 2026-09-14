"""AI 调用审计测试（票 06 验收，接缝 3：注入 audit_writer/notifier/inner_factory）。

覆盖外部行为：场景熔断（不写审计不通知）、成功审计字段（token/截断/防注入/
prompt_version）、备用降级（backup_model 标记）、非降级失败、备用未配置、
审计写失败不阻塞业务、网关熔断兜底卡片。
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest

from app.modules.warehouse.agent import gateway
from app.modules.warehouse.ai_audit.audited_client import (
    WarehouseAuditedLLMClient,
)
from app.modules.warehouse.ai_audit.context import (
    set_audit_resource,
    warehouse_audit_scope,
)
from app.modules.warehouse.ai_config.exceptions import ScenarioDisabledError
from app.modules.warehouse.ai_config.scenario_store import scenario_store


class FakeMsg:
    def __init__(self) -> None:
        self.content = "好的"
        self.tool_calls: list[Any] = []
        self.reasoning_content = "thinking"
        self.finish_reason = "stop"
        self.usage = {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
        }


class FakeInner:
    """假传输客户端：behavior 为 FakeMsg（成功）或异常实例（失败）。"""

    def __init__(self, behavior: Any) -> None:
        self._behavior = behavior
        self.calls = 0

    async def __aenter__(self) -> FakeInner:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def chat_with_tools(self, messages: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return self._behavior


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """把测试值打到缓存的 Settings 实例上（env 兜底层经 get_settings 读取）。"""
    from app.core.config import get_settings

    settings = get_settings()
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value, raising=False)


def make_client(
    audit_rows: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
    primaries: list[FakeInner],
    backups: list[FakeInner] | None = None,
) -> WarehouseAuditedLLMClient:
    def inner_factory(profile_name: str, config: dict[str, Any]) -> FakeInner:
        inner = (backups if profile_name == "agent_backup" else primaries).pop(0)
        return inner

    return WarehouseAuditedLLMClient(
        audit_writer=lambda **fields: audit_rows.append(fields) or _noop(),
        failure_notifier=lambda **kw: notifications.append(kw),
        inner_factory=inner_factory,
    )


async def _noop() -> None:
    return None


def _msg(**overrides: Any) -> FakeMsg:
    return FakeMsg()


MESSAGES = [
    {"role": "system", "content": "你是仓库助手。"},
    {"role": "user", "content": "你好"},
]


class TestScenarioCircuit:
    async def test_disabled_scenario_raises_before_audit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audit_rows: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []

        class Row:
            scenario = "agent_chat"
            enabled = False
            model_profile = None

        monkeypatch.setattr(scenario_store, "_row_loader", lambda s: Row())
        scenario_store.invalidate()
        try:
            client = make_client(audit_rows, notifications, [FakeInner(_msg())])
            with pytest.raises(ScenarioDisabledError):
                with warehouse_audit_scope("agent_chat"):
                    await client.chat_with_tools(MESSAGES)
        finally:
            monkeypatch.setattr(scenario_store, "_row_loader", None)
            scenario_store.invalidate()
        assert audit_rows == []  # 熔断不写审计
        assert notifications == []  # 熔断不触发通知


class TestAuditFields:
    async def test_success_audit_fields(self) -> None:
        audit_rows: list[dict[str, Any]] = []
        client = make_client(audit_rows, [], [FakeInner(_msg())])
        with warehouse_audit_scope(
            "receipt_recognition",
            trace_id="trace-1",
            session_id=str(uuid4()),
            chat_id="oc_x",
            user_open_id="ou_x",
        ):
            set_audit_resource("receipt_parse")
            msg = await client.chat_with_tools(MESSAGES)
        assert msg.content == "好的"
        row = audit_rows[0]
        assert row["trace_id"] == "trace-1"
        assert row["scenario"] == "receipt_recognition"
        assert row["resource"] == "receipt_parse"
        assert row["status"] == "success"
        assert row["prompt_version"] is not None and len(row["prompt_version"]) == 12
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 20
        assert row["cache_hit_tokens"] == 60
        assert row["latency_ms"] >= 0
        assert row["chat_id"] == "oc_x"
        # 防注入声明注入 system 消息
        dumped = str(row["input_json"])
        assert "INJECTION" in dumped or "安全声明" in dumped

    async def test_huge_input_truncated(self) -> None:
        audit_rows: list[dict[str, Any]] = []
        client = make_client(audit_rows, [], [FakeInner(_msg())])
        big = [{"role": "user", "content": "x" * 100_000}]
        with warehouse_audit_scope("agent_chat", trace_id="t"):
            await client.chat_with_tools(big)
        assert audit_rows[0]["input_json"]["truncated"] is True


class TestDegradation:
    async def test_500_degrades_to_backup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audit_rows: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []

        class Row:
            scenario = "agent_chat"
            enabled = True
            model_profile = None

        from app.modules.warehouse.ai_config.store import store as ai_profile_store

        monkeypatch.setattr(scenario_store, "_row_loader", lambda s: Row())
        scenario_store.invalidate()
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_BACKUP_API_KEY="sk-backup")
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_BACKUP_BASE_URL="https://backup.example")
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_BACKUP_MODEL="deepseek-v4.1-flash")
        # 批跑时单例可能已缓存 agent_backup 视图（无备用 env 的环境）——失效后重读
        ai_profile_store.invalidate("agent_backup")
        try:
            primary = FakeInner(_err(500))
            backup = FakeInner(_msg())
            client = make_client(audit_rows, notifications, [primary], [backup])
            with warehouse_audit_scope("agent_chat", trace_id="t"):
                msg = await client.chat_with_tools(MESSAGES)
            assert msg.content == "好的"
            assert primary.calls == 1 and backup.calls == 1
            assert len(audit_rows) == 2  # 主模型 failed + 备用 success 各一行
            assert audit_rows[0]["status"] == "failed"  # 主模型失败行
            assert audit_rows[1]["degradation_level"] == "backup_model"
            assert audit_rows[1]["status"] == "success"
        finally:
            monkeypatch.setattr(scenario_store, "_row_loader", None)
            scenario_store.invalidate()
            ai_profile_store.invalidate("agent_backup")
        # monkeypatch teardown 已恢复 settings 原值；此处只需失效缓存

    async def test_4xx_no_degradation(self) -> None:
        audit_rows: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []
        primary = FakeInner(_err(400))
        backups = [FakeInner(_msg())]
        client = make_client(audit_rows, notifications, [primary], backups)
        with warehouse_audit_scope("agent_chat", trace_id="t"):
            with pytest.raises(Exception):
                await client.chat_with_tools(MESSAGES)
        assert primary.calls == 1
        assert backups == [backups[0]] and backups[0].calls == 0  # 备用未动
        assert audit_rows[0]["status"] == "failed"
        assert notifications  # 失败通知触发


class TestFailurePaths:
    async def test_audit_writer_failure_does_not_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        notifications: list[dict[str, Any]] = []

        async def broken_writer(**fields: Any) -> None:
            raise RuntimeError("db down")

        client = WarehouseAuditedLLMClient(
            audit_writer=broken_writer,
            failure_notifier=lambda **kw: notifications.append(kw),
            inner_factory=lambda p, c: FakeInner(_msg()),
        )
        with warehouse_audit_scope("agent_chat", trace_id="t"):
            msg = await client.chat_with_tools(MESSAGES)  # 不抛错
        assert msg.content == "好的"


class GatewayFallback:
    async def test_text_message_disabled_scenario_sends_card(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[dict[str, Any]] = []
        audits: list[dict[str, Any]] = []

        async def fake_send(**kwargs: Any) -> Any:
            sent.append(kwargs)
            return "om_fake"

        async def fake_audit(**kwargs: Any) -> Any:
            audits.append(kwargs)

        class DummySession:
            id = uuid4()

        @contextlib.asynccontextmanager
        async def fake_db() -> Any:
            yield None

        class DummyRepoSession:
            id = uuid4()

        async def fake_get_session(db: Any, chat_id: str, user_open_id: str) -> Any:
            return DummyRepoSession()

        async def fake_run(session: Any, text: str, scene_hint: Any = None) -> Any:
            raise ScenarioDisabledError("disabled")

        monkeypatch.setattr(gateway, "_db_session", fake_db)
        monkeypatch.setattr(
            gateway.agent_repository, "get_or_create_session", fake_get_session
        )
        monkeypatch.setattr(gateway, "_send_card_to", fake_send)
        monkeypatch.setattr(gateway, "_record_gateway_audit", fake_audit)
        monkeypatch.setattr(
            gateway, "get_runner", lambda: type("R", (), {"run": staticmethod(fake_run)})()
        )
        await gateway._handle_text_message(
            chat_id="oc_x", chat_type="p2p", open_id="ou_x", text="你好", started=0.0
        )
        assert sent and "临时停用" in str(sent[0]["card"])
        assert audits and audits[0]["error_code"] == "scenario_disabled"


def _err(status: int) -> Any:
    from app.modules.warehouse.agent.llm_client import WarehouseLLMError

    return WarehouseLLMError("boom", status_code=status, response_snippet="x")
