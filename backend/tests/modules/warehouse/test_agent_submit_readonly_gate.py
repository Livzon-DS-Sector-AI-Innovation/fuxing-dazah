"""Agent 单据写 Base 只读闸（2026-11-04 生产版只读切换）。

契约：
- 闸语义：显式 ``agent_submit_enabled`` 1/0 优先；缺省随
  ``bitable_env_mode``（prod 拒写 fail-safe / test 放行，历史行为不变）；
- 五条提交链入口统一拦截：prod 下 confirm 后提交直接 DraftFlowError，
  不触 adapter（不发起任何 Base 请求）；
- test 下闸放行，行为与历史一致（后续状态前置照常生效）。

接缝：runtime_store.get_value 按 key 打桩；get_adapter 打桩为 fail-fast。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.warehouse.agent.pipeline.draft_flow import DraftFlowError
from app.modules.warehouse.agent.pipeline import submit as submit_module


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, Any],
) -> None:
    """按 key 打桩 runtime_store.get_value（缺省空串）。"""
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    monkeypatch.setattr(
        runtime_store, "get_value", lambda key, _v=values: _v.get(key, "")
    )


class TestGateSemantics:
    def test_test_mode_default_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_runtime(monkeypatch, {"bitable_env_mode": "test"})
        assert submit_module.agent_base_write_allowed() is True

    def test_prod_mode_default_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_runtime(monkeypatch, {"bitable_env_mode": "prod"})
        assert submit_module.agent_base_write_allowed() is False

    def test_prod_with_explicit_1_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_runtime(
            monkeypatch,
            {"bitable_env_mode": "prod", "agent_submit_enabled": "1"},
        )
        assert submit_module.agent_base_write_allowed() is True

    def test_test_with_explicit_0_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_runtime(
            monkeypatch,
            {"bitable_env_mode": "test", "agent_submit_enabled": "0"},
        )
        assert submit_module.agent_base_write_allowed() is False

    def test_illegal_override_falls_back_to_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_runtime(
            monkeypatch,
            {"bitable_env_mode": "prod", "agent_submit_enabled": "yes"},
        )
        assert submit_module.agent_base_write_allowed() is False


def _dummy_draft() -> SimpleNamespace:
    """闸在状态检查之前——最小桩即可（不触 DB 模型必填列）。"""
    return SimpleNamespace(draft_no="D-TEST-001", status="pending_confirm")


@pytest.mark.asyncio
async def test_submit_receipt_blocked_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch, {"bitable_env_mode": "prod"})
    monkeypatch.setattr(
        submit_module,
        "get_adapter",
        lambda: pytest.fail("prod 只读模式下不得触 adapter"),
    )
    with pytest.raises(DraftFlowError, match="只读模式"):
        await submit_module.submit_receipt(None, _dummy_draft())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_submit_receipt_passes_gate_in_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """test 环境闸放行——落在状态前置上（证明未被只读闸拦截）。"""
    _patch_runtime(monkeypatch, {"bitable_env_mode": "test"})
    with pytest.raises(DraftFlowError, match="仅 confirmed 可提交"):
        await submit_module.submit_receipt(None, _dummy_draft())  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fn",
    [submit_module.submit_gmp, submit_module.submit_outbound,
     submit_module.submit_picking, submit_module.submit_finished_receipt],
)
async def test_all_submit_chains_blocked_in_prod(
    monkeypatch: pytest.MonkeyPatch, fn: Any
) -> None:
    _patch_runtime(monkeypatch, {"bitable_env_mode": "prod"})
    monkeypatch.setattr(
        submit_module,
        "get_adapter",
        lambda: pytest.fail("prod 只读模式下不得触 adapter"),
    )
    with pytest.raises(DraftFlowError, match="只读模式"):
        await fn(None, _dummy_draft())  # type: ignore[arg-type]
