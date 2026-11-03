"""安全模块 × Super-agent 底座桥接 —— 冒烟①② 接线（§6 触点的安全侧落点）。

依赖方向：safety → platform.superagent（模块引平台，方向正确；底座零 safety import）。

- 冒烟①：workticket 速递格投递旁挂 effects（开关 SAFETY_SUPERAGENT_DIGEST_CELL_EFFECTS，
  默认关=原路径直调逐字节不变；开=入队 digest_cell_upsert effect，chat_id 行内权威）
- 冒烟②：hazard 督办轮询收编 bitable_poll Source（T04 落位，开关
  SAFETY_HAZARD_SUPERVISION_VIA_SUPERAGENT）

handler 注册幂等：bootstrap 重复调用不重复注册。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date as date_type
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


# ═══════════════════════════════════════════════════════════════
# 开关（safety app_config，热切换）
# ═══════════════════════════════════════════════════════════════


def digest_cell_effects_enabled() -> bool:
    """冒烟①开关：速递格投递走 superagent effects（默认关）。"""
    from app.modules.safety.app_config.store import store

    raw = (store.get_raw("SAFETY_SUPERAGENT_DIGEST_CELL_EFFECTS") or "").strip().lower()
    return raw in _TRUE


def supervision_via_superagent() -> bool:
    """冒烟②开关：督办轮询改走 superagent bitable_poll Source（默认关=原路径）。"""
    from app.modules.safety.app_config.store import store

    raw = (store.get_raw("SAFETY_HAZARD_SUPERVISION_VIA_SUPERAGENT") or "").strip().lower()
    return raw in _TRUE


# ═══════════════════════════════════════════════════════════════
# 冒烟①：digest_cell_upsert effect
# ═══════════════════════════════════════════════════════════════


async def _digest_cell_upsert_handler(payload: dict[str, Any]) -> None:
    """执行侧：行内 chat_id 是唯一权威（修「push 指定群被总卡吞 chat_id」根因）。"""
    from app.modules.safety.feishu.daily_digest import (
        DigestCell,
        upsert_daily_digest,
    )

    cell = DigestCell(**payload["cell"])
    report_date = date_type.fromisoformat(payload["date"])
    ok = await upsert_daily_digest(
        report_date,
        payload["key"],
        cell,
        board=payload.get("board") or "safety",
        chat_id=payload.get("chat_id"),
    )
    if not ok:
        # upsert 返回 False（板停用/建卡失败等）→ 视为失败走退避重试（先存后做的可对账性）
        raise RuntimeError(
            f"upsert_daily_digest returned False (key={payload.get('key')})"
        )


async def post_workticket_safety_cell(
    session: AsyncSession,
    *,
    digest_date: date_type,
    cell: Any,
) -> str:
    """workticket 格投递双路径（冒烟①旁挂点）。

    Returns:
        "direct" / "direct_failed"（原路径，行为不变）或 "effects"（入队成功）。
    """
    if not digest_cell_effects_enabled():
        from app.modules.safety.feishu.daily_digest import upsert_daily_digest

        ok = await upsert_daily_digest(digest_date, "workticket", cell)
        return "direct" if ok else "direct_failed"

    from app.modules.safety.feishu.daily_digest import digest_chat_id
    from app.platform.superagent.effects import enqueue_effect

    await enqueue_effect(
        session,
        "digest_cell_upsert",
        {
            "date": digest_date.isoformat(),
            "key": "workticket",
            "board": "safety",
            # 行内地址：入队时解析一次，执行侧不得重新解析/覆盖
            "chat_id": digest_chat_id(),
            "cell": asdict(cell),
        },
        dedupe_key=f"digest_cell:safety:{digest_date.isoformat()}:workticket",
    )
    logger.info(
        "冒烟①：workticket 速递格已入队 effects（date=%s）", digest_date,
    )
    return "effects"


# ═══════════════════════════════════════════════════════════════
# 冒烟②：hazard 督办 bitable_poll 收编
# ═══════════════════════════════════════════════════════════════


async def _hazard_ledger_fetcher(watermark_ms: int) -> list[dict[str, Any]]:
    """hazard 台账拉取（与整轮版 _fetch_targets 同筛选 A∪B，客户端侧水位过滤）。

    A. 未关闭/整改中（需算等级）；B. 仍标督办中（可能需置 closed）。
    """
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct.supervision import _fetch_targets

    client = SafetyBitableClient()
    records = await _fetch_targets(client)
    out = []
    for rec in records:
        lms = rec.get("last_modified_time")
        if lms is not None and int(lms) >= watermark_ms:
            out.append(rec)
        elif lms is None:
            # 无修改时间戳的记录：保守放行（指纹幂等兜底，不会重复派生）
            out.append(rec)
    return out


async def _supervision_writeback_handler(payload: dict[str, Any]) -> None:
    """执行侧：按 Trigger 快照字段重算督办等级并回写（幂等：只写变化）。"""
    from app.modules.safety.service.hazard_direct.supervision import (
        run_supervision_for_record,
    )

    record = {
        "record_id": payload.get("record_id", ""),
        "fields": payload.get("fields") or {},
    }
    await run_supervision_for_record(record)


# ═══════════════════════════════════════════════════════════════
# 注册（bootstrap 调用，幂等）
# ═══════════════════════════════════════════════════════════════


def register_superagent_bridge() -> None:
    """把安全侧 effect handler / fetcher 注册进底座（进程启动一次；测试可重复调用）。"""
    from app.platform.superagent.bitable_poll import (
        get_bitable_fetcher,
        register_bitable_fetcher,
    )
    from app.platform.superagent.effects import (
        get_effect_handler,
        register_effect_handler,
    )

    if get_effect_handler("digest_cell_upsert") is None:
        register_effect_handler("digest_cell_upsert", _digest_cell_upsert_handler)
    if get_effect_handler("supervision_writeback") is None:
        register_effect_handler("supervision_writeback", _supervision_writeback_handler)
    if get_effect_handler("needs_human_cell") is None:
        register_effect_handler("needs_human_cell", _needs_human_cell_handler)
    if get_bitable_fetcher("hazard_ledger") is None:
        register_bitable_fetcher("hazard_ledger", _hazard_ledger_fetcher)
    if get_bitable_fetcher("fire_alarm_ledger") is None:
        register_bitable_fetcher("fire_alarm_ledger", _fire_alarm_ledger_fetcher)

    # dm_admin 真发接线（平台注入点 ← 安全通知原语；平台零业务依赖）
    from app.platform.superagent.effects import set_dm_sender

    set_dm_sender(_send_admin_dm)


async def _send_admin_dm(open_id: str, text: str) -> bool:
    """DM 发送（安全应用通知原语；失败返回 False 走 effects 退避重试）。"""
    from app.modules.safety.feishu.notification import send_user_card

    try:
        return bool(await send_user_card(
            open_id,
            title="Super-agent 告警",
            content=text,
        ))
    except Exception:
        logger.exception("dm_admin 发送失败: %s", open_id)
        return False


async def bootstrap_superagent_policy_seed() -> None:
    """基线 Policy 播种（无 Policy 时；消防候选规则 observe 模式）。"""
    try:
        await seed_baseline_policy_if_absent()
    except Exception:
        logger.exception("Super-agent 基线 Policy 播种失败（忽略，可手动补）")


# ═══════════════════════════════════════════════════════════════
# 「需要人」格（cron_tick 源 → effect：底座自己的格子走自己的链）
# ═══════════════════════════════════════════════════════════════


async def _needs_human_cell_handler(payload: dict[str, Any]) -> None:
    """每日 08:00 构建「需要人」格投递速递总卡（只读摘要；处置走 REST）。"""
    from datetime import UTC, datetime

    from app.core.database import async_session_factory
    from app.modules.safety.feishu.daily_digest import (
        DigestCell,
        digest_chat_id,
        upsert_daily_digest,
    )
    from app.platform.superagent.watchdog import build_needs_human_snapshot

    async with async_session_factory() as session:
        snapshot = await build_needs_human_snapshot(session)

    lines: list[str] = []
    if snapshot["await_accept"]["count"]:
        lines.append(f"**待验收** {snapshot['await_accept']['count']} 项")
    if snapshot["await_answer"]["count"]:
        lines.append(f"**待回答** {snapshot['await_answer']['count']} 项")
    if snapshot["blocked_stale"]["count"]:
        lines.append(f"**受阻超时** {snapshot['blocked_stale']['count']} 项")
    replay = snapshot["observe_replay"]
    if replay["count"]:
        lines.append(f"**observe 待回放** {replay['count']} 条")

    cell = DigestCell(
        tag_color="orange" if lines else "green",
        tag_text="需要人",
        title="Super-agent 需要人",
        stats=" ｜ ".join(lines) if lines else "今日无需人工处理",
        zone="转正/忽略经底座 REST（管理员）" if replay["count"] else "",
        detail="\n".join(
            [f"- {x}" for x in (
                snapshot["await_accept"]["items"]
                + snapshot["await_answer"]["items"]
                + snapshot["blocked_stale"]["items"]
                + [f"observe {i['rule_id']}: {_fmt_fields(i['fields'])}（{i['trigger_key'][:40]}）"
                   for i in replay["items"]]
            )] or ["（空）"]
        )[:4000],
    )
    ok = await upsert_daily_digest(
        datetime.now(UTC).date(), "superagent_needs_human", cell,
        chat_id=digest_chat_id(),
    )
    if not ok:
        raise RuntimeError("needs_human cell upsert returned False")


def _fmt_fields(fields: dict[str, Any]) -> str:
    """observe 回放一行摘要（安全域字段；仅展示，不参与授权）。"""
    keys = ("报警性质", "部门", "原因分类", "整改状态")
    parts = [str(fields.get(k) or "") for k in keys]
    return "·".join(p for p in parts if p) or "（无字段）"


# ═══════════════════════════════════════════════════════════════
# 冒烟③：消防报警候选规则（R1 §1.2 拍板口径）observe 挂载
# ═══════════════════════════════════════════════════════════════

#: 消防候选白名单（P1 已定方向：按原因分类判断；值集配置驱动可热调）
FIRE_CAUSE_ALLOWLIST = ("现场着火", "硫化氢引发", "氨水引发", "甲烷引发")
FIRE_NATURE_EXCLUDE = ("测试报警", "测试性质", "演练引发")
FIRE_FAULT_RULE_EXCLUDE_CAUSES = ("测试", "演练引发")
FIRE_FAULT_NATURE = "故障报警"


def fire_candidate_rule() -> dict[str, Any]:
    """消防候选规则声明（R1 口径：白名单 ∪ 故障子规则，排除计划内性质）。"""
    return {
        "rule_id": "fire_alarm_candidate",
        "enabled": True,
        "source": "safety.fire_alarm",
        "executor": "noop_exec",
        "conditions": [
            # 排除：性质 ∈ {测试报警, 测试性质, 演练引发}
            {"field": "fields.报警性质", "op": "not_in", "values": list(FIRE_NATURE_EXCLUDE)},
            # 命中：原因 ∈ 白名单 ∪ (性质=故障报警 且 原因 ∉ {测试, 演练引发})
            {"any_of": [
                {"field": "fields.原因分类", "op": "in", "values": list(FIRE_CAUSE_ALLOWLIST)},
                {"all_of": [
                    {"field": "fields.报警性质", "op": "equals", "values": [FIRE_FAULT_NATURE]},
                    {"field": "fields.原因分类", "op": "not_in",
                     "values": list(FIRE_FAULT_RULE_EXCLUDE_CAUSES)},
                ]},
            ]},
        ],
    }


async def seed_baseline_policy_if_absent() -> str | None:
    """无 Policy 时播种基线（消防候选规则 + observe 模式）。返回版本号。"""
    from app.core.database import async_session_factory
    from app.platform.superagent.policy import apply_new_policy, get_current_policy

    async with async_session_factory() as session:
        current = await get_current_policy(session)
        if current is not None:
            return current.version_hash
        policy, _ = await apply_new_policy(
            session, rules=[fire_candidate_rule()], accept_mode="observe",
        )
        await session.commit()
        logger.info("Super-agent 基线 Policy 已播种（fire_alarm_candidate, observe）")
        return policy.version_hash


async def _fire_alarm_ledger_fetcher(watermark_ms: int) -> list[dict[str, Any]]:
    """消防报警表拉取：业务时间窗（报警时间倒序+提前终止）+ 客户端侧修改水位过滤。

    消防表不支持系统字段（修改时间）过滤（1254018 实测），水位增量改在
    客户端做；窗口滚动 30 天（候选规则本就面向近期，量级 ~170 条/页内）。
    """
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.service.bitable_direct import reader as bd_reader

    client = bd_reader.resolve_client("fire_alarm", "alarm")
    now = datetime.now(UTC)
    records = await bd_reader.fetch_window_records(
        client,
        time_field="报警时间",
        start=now - timedelta(days=30),
        end=now + timedelta(days=1),
        page_size=500,
        automatic_fields=True,
    )
    out = []
    for rec in records or []:
        lms = rec.get("last_modified_time")
        if lms is None or int(lms) >= watermark_ms:
            out.append(rec)  # 无时间戳保守放行（指纹幂等兜底）
    return out
