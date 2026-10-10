"""危化品库存日报追加投递「危险品日报」群 — 单测（无 DB / 无飞书依赖）。

覆盖（2026-09-30 需求）：
- 总卡开启：投「安全速递」格子后，同款单格速递版式追加投递危险品日报群
- 无 Excel（缺席格）同样追加投递
- env SAFETY_CHEMICAL_DAILY_EXTRA_CHAT_ID=off 停用追加
- 总卡关闭（旧独立群卡分支）：主群照发 + 追加投递仍执行
- 主 chat_id 未配置：整体跳过（既有契约不变）

全部发送/存储桩注入，不打真实飞书接口。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.safety.chemical_inventory import daily_job

D = date(2026, 9, 30)
EXTRA_CHAT = "oc_ae9c3a305430cb196e42130f69b052bc"  # 危险品日报群（默认加投目标）


def _analysis(**kw: Any) -> SimpleNamespace:
    """有分析结果的 analysis 替身（send_daily_summary 用到的属性集）。"""
    return SimpleNamespace(
        report_date=kw.get("report_date", D),
        over_limit_items=kw.get("over_limit_items", []),
        over_limit_count=kw.get("over_limit_count", 0),
        surge_count=kw.get("surge_count", 0),
        decline_count=kw.get("decline_count", 0),
        has_risk=kw.get("has_risk", lambda: False),
    )


def _stubs(monkeypatch: pytest.MonkeyPatch, *, digest_on: bool = True) -> tuple[
    AsyncMock, AsyncMock, AsyncMock,
]:
    """注入 upsert_daily_digest / send_digest_cell_card / send_group_card 桩。

    build_daily_summary 一并桩掉（渲染细节由 daily_report 自己的单测覆盖），
    本文件只验证投递接线。
    """
    upsert = AsyncMock(return_value=True)
    extra_send = AsyncMock(return_value="om_extra")
    group_send = AsyncMock(return_value="om_group")
    monkeypatch.setattr(
        "app.modules.safety.feishu.daily_digest.upsert_daily_digest", upsert,
    )
    monkeypatch.setattr(
        "app.modules.safety.feishu.daily_digest.send_digest_cell_card", extra_send,
    )
    monkeypatch.setattr(
        "app.modules.safety.feishu.daily_digest.digest_enabled",
        lambda: digest_on,
    )
    monkeypatch.setattr(daily_job, "send_group_card", group_send)
    monkeypatch.setattr(daily_job, "build_daily_summary", lambda r: "日报正文")
    return upsert, extra_send, group_send


async def test_digest_mode_sends_extra_group_after_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily_job, "CHEMICAL_DAILY_EXTRA_CHAT_ID", EXTRA_CHAT)
    upsert, extra_send, group_send = _stubs(monkeypatch, digest_on=True)

    result = {"analysis": _analysis(over_limit_count=1)}
    ret = await daily_job.send_daily_summary(result, chat_id="oc_main")

    assert ret == "digest"
    assert upsert.await_count == 1
    assert group_send.await_count == 0  # 总卡开启不发独立群卡
    # 追加投递：目标=危险品日报群，标题带日期，格子与总卡同源
    extra_send.assert_awaited_once()
    args, kwargs = extra_send.await_args
    assert args[0].tag_text == "危化品库存"
    assert kwargs["chat_id"] == EXTRA_CHAT
    assert kwargs["title"] == f"📌 危化品库存日报 | {D.isoformat()}"


async def test_absence_cell_also_sent_to_extra_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """今日无 Excel：缺席格投总卡后同样追加投递危险品日报群。"""
    monkeypatch.setattr(daily_job, "CHEMICAL_DAILY_EXTRA_CHAT_ID", EXTRA_CHAT)
    upsert, extra_send, _ = _stubs(monkeypatch, digest_on=True)

    result = {"skipped": True, "reason": "no_files_today", "analysis": None}
    ret = await daily_job.send_daily_summary(result, chat_id="oc_main")

    assert ret == "digest"
    assert upsert.await_count == 1
    extra_send.assert_awaited_once()
    assert extra_send.await_args.args[0].stats == "今日未收到日报 Excel，无库存分析"


async def test_extra_disabled_by_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily_job, "CHEMICAL_DAILY_EXTRA_CHAT_ID", "off")
    upsert, extra_send, _ = _stubs(monkeypatch, digest_on=True)

    ret = await daily_job.send_daily_summary(
        {"analysis": _analysis()}, chat_id="oc_main",
    )
    assert ret == "digest"
    assert upsert.await_count == 1
    assert extra_send.await_count == 0


async def test_non_digest_mode_still_sends_extra_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """总卡关闭：主群发独立群卡（旧行为不变），追加投递照常执行。"""
    monkeypatch.setattr(daily_job, "CHEMICAL_DAILY_EXTRA_CHAT_ID", EXTRA_CHAT)
    _, extra_send, group_send = _stubs(monkeypatch, digest_on=False)

    ret = await daily_job.send_daily_summary(
        {"analysis": _analysis()}, chat_id="oc_main",
    )

    assert ret == "om_group"
    assert group_send.await_count == 1
    extra_send.assert_awaited_once()
    assert extra_send.await_args.kwargs["chat_id"] == EXTRA_CHAT


async def test_unconfigured_chat_skips_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主 chat_id 未配置：主推送与追加投递整体跳过（既有契约）。"""
    monkeypatch.setattr(daily_job, "CHEMICAL_DAILY_EXTRA_CHAT_ID", EXTRA_CHAT)
    upsert, extra_send, group_send = _stubs(monkeypatch, digest_on=True)

    ret = await daily_job.send_daily_summary({"analysis": _analysis()}, chat_id=None)
    assert ret is None
    assert upsert.await_count == 0
    assert extra_send.await_count == 0
    assert group_send.await_count == 0


async def test_extra_failure_does_not_break_digest_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """追加投递失败（返回 None）只告警，不影响返回值 digest=True。"""
    monkeypatch.setattr(daily_job, "CHEMICAL_DAILY_EXTRA_CHAT_ID", EXTRA_CHAT)
    upsert, extra_send, _ = _stubs(monkeypatch, digest_on=True)
    extra_send.return_value = None

    ret = await daily_job.send_daily_summary(
        {"analysis": _analysis()}, chat_id="oc_main",
    )
    assert ret == "digest"
    assert upsert.await_count == 1
