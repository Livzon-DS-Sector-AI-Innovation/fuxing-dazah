"""作业票违规票 @ 分管安全员——部门映射与 @ 标签解析单测。

覆盖 service 层三段链路：
  - ``_config_safety_officer``：申请单位 → DEPARTMENT_CONFIG 安全员姓名
    （精确命中 / 互包含容错 / 未配置 / 空值）
  - ``_officer_names_for_tickets``：仅真实违规票映射（数据不足票不 @）
  - ``resolve_officer_mentions``：姓名 → 安全应用 open_id → ``<at id=…></at>``，
    解析不到降级纯文本姓名，解析异常不阻断
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.workticket_review.parser import WorkTicket
from app.modules.safety.workticket_review.rule_engine import RuleNo, Violation
from app.modules.safety.workticket_review.service import (
    _config_safety_officer,
    _officer_names_for_tickets,
    resolve_officer_mentions,
)

TZ = ZoneInfo("Asia/Shanghai")


def _violation(detail: str, *, not_applicable: bool = False) -> Violation:
    return Violation(
        rule_no=RuleNo.TIME_ORDER,
        rule_name="时间顺序链",
        detail=detail,
        key_times=[],
        not_applicable=not_applicable,
    )


def _ticket(
    ticket_no: str,
    *,
    apply_unit: str = "",
    start: bool = True,
) -> WorkTicket:
    return WorkTicket(
        ticket_no=ticket_no,
        ticket_type="hot_work",
        start_time=datetime(2026, 11, 17, 8, 30, tzinfo=TZ) if start else None,
        apply_unit=apply_unit,
    )


# ── _config_safety_officer ──

def test_config_safety_officer_exact_hit() -> None:
    assert _config_safety_officer("环保工程中心") == "罗建华"
    assert _config_safety_officer("提炼工程一部") == "郑雅杰"


def test_config_safety_officer_fuzzy_containment() -> None:
    """互包含容错：短名命中带括号全称键。"""
    assert _config_safety_officer("质量控制部") == "翁日生"
    assert _config_safety_officer("  提炼工程二部  ") == "李伟豪"


def test_config_safety_officer_unconfigured_or_empty() -> None:
    assert _config_safety_officer("合规监察部") is None  # 有配置但无安全员
    assert _config_safety_officer("不存在的部门") is None
    assert _config_safety_officer("") is None
    assert _config_safety_officer("   ") is None


# ── _officer_names_for_tickets ──

def _fixture() -> tuple[list[WorkTicket], dict[str, list[Violation]]]:
    real = _ticket("DH-REAL", apply_unit="环保工程中心")  # 真实违规 → 映射
    insufficient = _ticket("SX-INS", apply_unit="发酵工程部")  # 仅数据不足 → 不映射
    unconfigured = _ticket("DH-NOCFG", apply_unit="合规监察部")  # 无安全员 → 不映射
    tickets = [real, insufficient, unconfigured]
    violations = {
        "DH-REAL": [_violation("申请晚于气体分析")],
        "SX-INS": [_violation("数据不足：缺少 开始时间、结束时间")],
        "DH-NOCFG": [_violation("申请晚于气体分析")],
    }
    return tickets, violations


def test_officer_names_only_real_violations() -> None:
    tickets, violations = _fixture()
    assert _officer_names_for_tickets(tickets, violations) == {
        "DH-REAL": "罗建华",
    }


def test_officer_names_empty_when_no_real_violations() -> None:
    tickets, violations = _fixture()
    violations = {
        "DH-REAL": [_violation("数据不足：缺少 结束时间")],
        "SX-INS": [_violation("数据不足：缺少 开始时间")],
        "DH-NOCFG": [],
    }
    assert _officer_names_for_tickets(tickets, violations) == {}


# ── resolve_officer_mentions ──

async def test_resolve_officer_mentions_at_tag_and_fallback(
    monkeypatch: Any,
) -> None:
    """命中 open_id 渲染 @ 标签；未命中降级纯文本姓名。"""
    from app.modules.safety.feishu import mention

    async def _fake_resolve(names: Any) -> dict[str, str]:
        return {"罗建华": "ou_luo"} if "罗建华" in names else {}

    monkeypatch.setattr(mention, "resolve_open_ids", _fake_resolve)
    tickets, violations = _fixture()
    # 再加一张同部门真实违规票（姓名批量解析去重）
    tickets.append(_ticket("DH-REAL2", apply_unit="环保工程中心"))
    violations["DH-REAL2"] = [_violation("申请晚于气体分析")]
    # 加一张「部门有安全员但 open_id 解析不到」的票 → 纯文本兜底
    tickets.append(_ticket("DH-PLAIN", apply_unit="安全工程中心"))
    violations["DH-PLAIN"] = [_violation("申请晚于气体分析")]

    out = await resolve_officer_mentions(tickets, violations)
    assert out["DH-REAL"] == "<at id=ou_luo></at>"
    assert out["DH-REAL2"] == "<at id=ou_luo></at>"
    assert out["DH-PLAIN"] == "王海霞"  # resolve_open_ids 未返回 → 纯文本姓名
    assert "SX-INS" not in out and "DH-NOCFG" not in out


async def test_resolve_officer_mentions_degrades_on_error(
    monkeypatch: Any,
) -> None:
    """resolve_open_ids 抛异常时全部降级纯文本，不阻断审核。"""
    from app.modules.safety.feishu import mention

    async def _boom(names: Any) -> dict[str, str]:
        raise RuntimeError("token 获取失败")

    monkeypatch.setattr(mention, "resolve_open_ids", _boom)
    tickets, violations = _fixture()
    out = await resolve_officer_mentions(tickets, violations)
    assert out == {"DH-REAL": "罗建华"}


async def test_resolve_officer_mentions_empty_when_none_mapped() -> None:
    assert await resolve_officer_mentions([], {}) == {}
    tickets, violations = _fixture()
    violations = {"DH-REAL": [_violation("数据不足：缺少 结束时间")]}
    assert await resolve_officer_mentions(tickets, violations) == {}
