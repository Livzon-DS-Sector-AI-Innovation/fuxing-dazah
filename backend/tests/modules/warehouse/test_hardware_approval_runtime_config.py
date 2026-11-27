"""五金审批运行参数迁移测试（2026-11-26：env → runtime_configs 双通道）。

覆盖：读取链走 runtime_store（DB 行覆盖 env / env 兜底 / 默认）、
_scrap/_return_form_config 的非法 JSON 容错、RECONCILE 开关语义、
通道工厂按配置切换。全 mock runtime_store（不打真 DB），模式照
test_runtime_config_consumers.py。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.warehouse.hardware import approval_channel as ac


class _StubStore:
    """runtime_store 替身：固定值表（测试体内可改）。"""

    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get_value(self, key: str) -> Any:
        return self.values.get(key)


def _patch_store(monkeypatch: pytest.MonkeyPatch, values: dict[str, Any]) -> None:
    import app.modules.warehouse.ops_config.runtime_store as rs

    monkeypatch.setattr(rs.runtime_store, "get_value", _StubStore(values).get_value)


def test_approval_code_reads_runtime_store(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_store(monkeypatch, {"hardware_approval_code": "  CODE-1  "})
    assert ac.get_approval_code() == "CODE-1"


def test_channel_factory_switches_by_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """通道工厂按运行参数切换：feishu+code→飞书通道；否则 manual。"""
    _patch_store(
        monkeypatch,
        {"hardware_approval_channel": "feishu", "hardware_approval_code": "CODE-1"},
    )
    channel = ac.get_approval_channel()
    assert isinstance(channel, ac.FeishuApprovalChannel) and channel.approval_code == "CODE-1"
    assert ac.feishu_channel_configured() is True

    _patch_store(monkeypatch, {"hardware_approval_channel": "manual", "hardware_approval_code": "CODE-1"})
    assert isinstance(ac.get_approval_channel(), ac.ManualApprovalChannel)
    assert ac.feishu_channel_configured() is False

    # code 缺失时 feishu 也不就绪
    _patch_store(monkeypatch, {"hardware_approval_channel": "feishu", "hardware_approval_code": ""})
    assert isinstance(ac.get_approval_channel(), ac.ManualApprovalChannel)


def test_scrap_form_config_bad_json_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    """widgets JSON 非法 → 按未配置处理（不抛异常，返回空配置）。"""
    _patch_store(
        monkeypatch,
        {
            "hardware_scrap_kind_value": "SCRAP-KIND",
            "hardware_scrap_form_widgets": "{not-json",
        },
    )
    cfg = ac._scrap_form_config()
    assert cfg["kind_value"] == "SCRAP-KIND"
    assert not any(cfg.get(k) for k in ("dept", "starter", "reason", "items", "doc_no"))


def test_scrap_branch_ready_only_when_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_store(
        monkeypatch,
        {
            "hardware_approval_channel": "feishu",
            "hardware_approval_code": "CODE-1",
            "hardware_scrap_kind_value": "SCRAP-KIND",
            "hardware_scrap_form_widgets": '{"dept":"w1","starter":"w2","reason":"w3","items":"w4","doc_no":"w5"}',
        },
    )
    assert ac.scrap_branch_configured() is True
    assert isinstance(ac.get_scrap_approval_channel(), ac._ScrapFeishuApprovalChannel)

    # 缺 kind_value → 未就绪
    _patch_store(
        monkeypatch,
        {
            "hardware_approval_channel": "feishu",
            "hardware_approval_code": "CODE-1",
            "hardware_scrap_kind_value": "",
            "hardware_scrap_form_widgets": '{"dept":"w1","starter":"w2","reason":"w3","items":"w4","doc_no":"w5"}',
        },
    )
    assert ac.scrap_branch_configured() is False


def test_return_branch_ready_only_when_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_store(
        monkeypatch,
        {
            "hardware_approval_channel": "feishu",
            "hardware_approval_code": "CODE-1",
            "hardware_return_kind_value": "RET-KIND",
            "hardware_return_form_widgets": (
                '{"dept":"w1","starter":"w2","source_req_no":"w3",'
                '"items":"w4","return_no":"w5","reason":"w6"}'
            ),
        },
    )
    assert ac.return_branch_configured() is True
    assert isinstance(ac.get_return_approval_channel(), ac._ReturnFeishuApprovalChannel)


def test_approver_node_id_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_store(monkeypatch, {"hardware_approval_node_id": "NODE-X"})
    assert ac.get_approver_node_id() == "NODE-X"
    _patch_store(monkeypatch, {})
    assert ac.get_approver_node_id() == ""


async def test_reconcile_gate_reads_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """对账任务开关：0=空转返回；1=继续执行（mock reconcile 验证被调用与否）。"""
    from app.modules.warehouse.hardware import approval_ingest
    from app.modules.warehouse.hardware import scheduled as sch

    calls: list[bool] = []

    async def _fake_reconcile(db):  # noqa: ANN001
        calls.append(True)
        return {}

    # scheduled 函数体内延迟 import，patch 须打在源模块属性上
    monkeypatch.setattr(approval_ingest, "reconcile_recent_instances", _fake_reconcile)

    # 关：直接 return（不触达 reconcile）
    _patch_store(monkeypatch, {"hardware_approval_reconcile_enabled": 0})
    await sch._run_scheduled_approval_reconcile()
    assert calls == []

    # 开：执行
    _patch_store(monkeypatch, {"hardware_approval_reconcile_enabled": 1})
    await sch._run_scheduled_approval_reconcile()
    assert calls == [True]
