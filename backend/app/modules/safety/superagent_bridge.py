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

    # R1 消防扫描源（二期）：cron 门控 + 记录粒度 Trigger（扩展点注册制）
    from app.platform.superagent.sources import source_registry

    if source_registry.get("cron_scan") is None:
        from app.modules.safety.service.alarm_hazard_r1.scan_source import (
            FireAlarmScanSource,
        )

        source_registry.register(FireAlarmScanSource())

    # R2 监护人持证扫描源（自有 kind：cron_scan 已被 R1 消防源占用）
    if source_registry.get("guardian_cert_scan") is None:
        from app.modules.safety.service.guardian_r2.scan_source import (
            GuardianCertScanSource,
        )

        source_registry.register(GuardianCertScanSource())
    # R2 成绩轮询源 + fetcher（bitable_poll 子类，翻译 _derived）
    if source_registry.get("guardian_score_poll") is None:
        from app.modules.safety.service.guardian_r2.score_source import (
            GuardianScorePollSource,
        )

        source_registry.register(GuardianScorePollSource())
    if get_bitable_fetcher("guardian_score_ledger") is None:
        from app.modules.safety.service.guardian_r2.score_source import (
            guardian_score_fetcher,
        )

        register_bitable_fetcher("guardian_score_ledger", guardian_score_fetcher)

    # R3 运维信号扫描源（三期应用：定时任务失败/RAG 故障/依赖断连自动开单诊断）
    if source_registry.get("ops_scan") is None:
        from app.modules.safety.service.ops_selfheal_r3.scan_source import (
            OpsScanSource,
        )

        source_registry.register(OpsScanSource())

    # R1 程序执行器 + P4 群卡 outbox sender（二期）
    from app.platform.superagent.executors import get_executor, register_executor

    if get_executor("alarm_hazard_create") is None:
        from app.modules.safety.service.alarm_hazard_r1.executor import (
            alarm_hazard_create,
        )

        register_executor("alarm_hazard_create", alarm_hazard_create)
    # R2 程序执行器（T04 起逐票注册：提醒 DM → 成绩映射 → 取消资格/恢复）
    if get_executor("guardian_remind_dm") is None:
        from app.modules.safety.service.guardian_r2.executor import (
            guardian_remind_dm,
        )

        register_executor("guardian_remind_dm", guardian_remind_dm)
    if get_executor("guardian_score_map") is None:
        from app.modules.safety.service.guardian_r2.executor import (
            guardian_score_map,
        )

        register_executor("guardian_score_map", guardian_score_map)
    if get_executor("guardian_qualify_revoke") is None:
        from app.modules.safety.service.guardian_r2.executor import (
            guardian_qualify_revoke,
        )

        register_executor("guardian_qualify_revoke", guardian_qualify_revoke)
    if get_executor("guardian_qualify_restore") is None:
        from app.modules.safety.service.guardian_r2.executor import (
            guardian_qualify_restore,
        )

        register_executor("guardian_qualify_restore", guardian_qualify_restore)
    # R3 运维自愈执行器 + 修复/收口 effect handlers（三期应用）
    if get_executor("r3_ops_heal") is None:
        from app.modules.safety.service.ops_selfheal_r3.executor import r3_ops_heal

        register_executor("r3_ops_heal", r3_ops_heal)
    if get_effect_handler("r3_repair") is None:
        from app.modules.safety.service.ops_selfheal_r3.actions import (
            r3_repair_handler,
        )

        register_effect_handler("r3_repair", r3_repair_handler)
    if get_effect_handler("r3_closure_card") is None:
        from app.modules.safety.service.ops_selfheal_r3.actions import (
            r3_closure_card_handler,
        )

        register_effect_handler("r3_closure_card", r3_closure_card_handler)
    from app.platform.superagent.effects import register_outbox_sender

    try:
        register_outbox_sender("feishu_card", _feishu_card_sender)
    except ValueError:
        pass  # 已注册（bootstrap 幂等）
    try:
        register_outbox_sender("feishu_dm_card", _feishu_dm_card_sender)
    except ValueError:
        pass  # 已注册（bootstrap 幂等）

    # dm_admin 真发接线（平台注入点 ← 安全通知原语；平台零业务依赖）
    from app.platform.superagent.effects import set_dm_sender

    set_dm_sender(_send_admin_dm)

    # P2-2 G3：危险源辨识重放执行器（协议收编；同步留痕模式不依赖它）
    if get_executor("hazard_id_script") is None:
        from app.modules.safety.ai_hazard_identification.superagent_trace import (
            register_hazard_id_executor,
        )

        register_hazard_id_executor()


async def _feishu_card_sender(channel: dict[str, Any], body: dict[str, Any]) -> bool:
    """outbox 卡片发送（行内 chat_id 唯一权威；失败 False 走退避重试）。"""
    from app.modules.safety.feishu.notification import send_group_card

    try:
        mid = await send_group_card(
            str(channel.get("chat_id") or ""),
            title=str(body.get("title") or ""),
            content=str(body.get("content") or ""),
        )
        return bool(mid)
    except Exception:
        logger.exception("feishu_card 发送失败: chat=%s", channel.get("chat_id"))
        return False


async def _feishu_dm_card_sender(channel: dict[str, Any], body: dict[str, Any]) -> bool:
    """outbox 私信卡片发送（R2 监护人提醒；行内 open_id 唯一权威）。"""
    from app.modules.safety.feishu.notification import send_user_card

    try:
        mid = await send_user_card(
            str(channel.get("open_id") or ""),
            title=str(body.get("title") or ""),
            content=str(body.get("content") or ""),
        )
        return bool(mid)
    except Exception:
        logger.exception("feishu_dm_card 发送失败: open=%s", channel.get("open_id"))
        return False


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
    """safety 侧 Policy 播种/升版（规则随代码部署生效；accept_mode 切换权留给人工）。

    Policy 全局单现行版本——必须**组合播种**（现行=R1+R2+五金 HW 三组合同版本），
    只播子集会把其他模块规则从现行版本挤掉（版本哈希不同即升版覆盖）。
    """
    try:
        await ensure_guardian_r2_policy()
    except Exception:
        logger.exception("Super-agent safety Policy ensure 失败（忽略，可手动补）")


async def ensure_guardian_r2_policy(session: AsyncSession | None = None) -> str | None:
    """幂等确保现行 Policy 为 R1+R2 组合规则集（沿用现行 accept_mode/admission）。

    - 无 Policy：播种组合规则 + observe
    - 内容不同：apply_new_policy 升版——沿用现行 accept_mode 与 admission
      （模式切换是人工权限，部署不得覆盖）
    - ensure_r1_policy 保留给 R1 replay 脚本隔离使用（会播 r1-only 版本，
      生产 bootstrap 不再调用它）
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.alarm_hazard_r1.rule import r1_fire_rule
    from app.modules.safety.service.guardian_r2.rule import (
        guardian_remind_rule,
        guardian_restore_rule,
        guardian_revoke_rule,
        guardian_score_map_rule,
    )
    from app.platform.superagent.policy import (
        apply_new_policy,
        get_current_policy,
        policy_version_hash,
    )

    own_session = session is None
    ses = session or async_session_factory()
    try:
        rules = [
            r1_fire_rule(),
            guardian_remind_rule(),
            guardian_revoke_rule(),
            guardian_restore_rule(),
            guardian_score_map_rule(),
        ]
        # 五金库二期 M6（2026-11-05）：HW 规则并入组合（全局单 Policy 版本，
        # 单播会把其他模块规则挤掉——此处是三组合唯一会合点）
        from app.modules.warehouse.hardware.superagent.rule import (
            hardware_alert_rules,
        )

        rules.extend(hardware_alert_rules())
        # R3 运维自愈（2026-11-12）：两源规则并入组合（四组会合点；
        # 沿用现行 accept_mode/admission，部署不覆盖人工模式决定）
        from app.modules.safety.service.ops_selfheal_r3.rule import r3_ops_rules

        rules.extend(r3_ops_rules())
        current = await get_current_policy(ses)
        mode = current.accept_mode if current is not None else "observe"
        admission = (current.admission if current is not None else {}) or {}
        if current is not None and current.version_hash == policy_version_hash(
            rules, mode, admission,
        ):
            return current.version_hash
        policy, _ = await apply_new_policy(
            ses, rules=rules, accept_mode=mode, admission=admission,
        )
        if own_session:
            await ses.commit()
        logger.info(
            "Super-agent safety Policy（R1+R2）已就绪（%s, mode=%s）",
            policy.version_hash[:12], mode,
        )
        return policy.version_hash
    finally:
        if own_session:
            await ses.close()


async def ensure_r1_policy(session: AsyncSession | None = None) -> str | None:
    """幂等确保现行 Policy 为 R1 规则集（白名单∪故障∪闭环，实测字段名）。

    - 无 Policy：播种 R1 规则 + observe（冒烟③基线模式）
    - 有 Policy 且内容不同：apply_new_policy 升版——**沿用现行 accept_mode 与
      admission**（规则是代码的一部分随部署生效；模式切换是人工权限，部署
      不得覆盖人工 auto/observe 决定）
    - 内容一致：幂等返回现行版本号
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.alarm_hazard_r1.rule import r1_fire_rule
    from app.platform.superagent.policy import (
        apply_new_policy,
        get_current_policy,
        policy_version_hash,
    )

    own_session = session is None
    ses = session or async_session_factory()
    try:
        rules = [r1_fire_rule()]
        current = await get_current_policy(ses)
        mode = current.accept_mode if current is not None else "observe"
        admission = (current.admission if current is not None else {}) or {}
        if current is not None and current.version_hash == policy_version_hash(
            rules, mode, admission,
        ):
            return current.version_hash
        policy, _ = await apply_new_policy(
            ses, rules=rules, accept_mode=mode, admission=admission,
        )
        if own_session:
            await ses.commit()
        logger.info("Super-agent R1 Policy 已就绪（%s, mode=%s）", policy.version_hash[:12], mode)
        return policy.version_hash
    finally:
        if own_session:
            await ses.close()


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
