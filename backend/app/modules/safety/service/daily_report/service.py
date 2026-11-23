"""AI+安全日报同源核心——卡片回调与 REST 共用（window_guard 模式）。

职责边界：
- 快路径（≤2.9s ACK 契约）：submit 表单提交 = 查重 upsert + 历史追加 + toast
- 慢路径（后台 task）：AI 评价、负责人汇总、群卡刷新——LLM 秒级到分钟级，
  绝不占回调窗口；REST 端点为 E2E 确定性可显式 inline await
- 群入口卡一日一张：Redis 锚 msg_id，PATCH 优先/失败重建（daily_digest 同款）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.redis import get_redis

from . import aggregation, cards, config, evaluation, store
from .cards import DailyCardState

logger = logging.getLogger(__name__)

#: 群入口卡 msg_id Redis 锚（TTL 7 天，对齐 daily_digest）
_CARD_MSG_TTL_SECONDS = 7 * 24 * 3600

#: 状态字典键（get_status / REST 返回口径）
STAGE_FIRST = "first"
STAGE_FINAL = "final"
STAGE_REVISE = "revise"


def _card_msg_key(date_key: str) -> str:
    return f"safety:daily_report:card_msg:{date_key}"


async def _is_leader(open_id: str) -> bool:
    """负责人判定：名单角色=负责人 或 平台 admin（fail-closed）。"""
    if not open_id:
        return False
    try:
        for member in await store.load_roster():
            if member.open_id == open_id and member.role == store.ROLE_LEADER:
                return True
    except Exception:  # noqa: BLE001
        logger.exception("日报名单读取异常（负责人判定回退 admin 链）")
    return await _is_admin(open_id)


async def _is_admin(open_id: str) -> bool:
    """平台 admin 校验（r3_card._operator_is_admin 同一权限链）。"""
    if not open_id:
        return False
    try:
        from app.core.database import async_session_factory
        from app.platform.identity.repository import UserRepository
        from app.platform.permission.deps import get_user_permissions

        async with async_session_factory() as session:
            user = await UserRepository().get_by_feishu_open_id(session, open_id)
            if user is None:
                return False
            perms = await get_user_permissions(str(user.id), session)
            return "permission:role:manage" in perms
    except Exception:  # noqa: BLE001 — 权限校验失败即拒绝
        logger.exception("日报权限校验异常（拒绝）: open_id=%s", open_id)
        return False


async def _roster_name(open_id: str) -> str:
    """open_id → 展示名（名单 → open_id 尾段兜底）。"""
    try:
        for member in await store.load_roster():
            if member.open_id == open_id:
                return member.name or open_id[-8:]
    except Exception:  # noqa: BLE001
        pass
    return open_id[-8:]


async def _notify_operator_failure(open_id: str, text: str) -> None:
    """慢路径失败 DM 操作者（卡片路径无 REST 返回可看，静默即黑洞）。"""
    from app.modules.safety.feishu.notification import send_user_card

    try:
        await send_user_card(open_id, "AI+安全日报", text, header_template="red")
    except Exception:  # noqa: BLE001 — 通知失败只留日志
        logger.exception("日报失败通知发送异常: open_id=%s", open_id)


# ═══════════════════════════════════════════════════════════
# 群入口卡（一日一张）
# ═══════════════════════════════════════════════════════════

async def compute_state(date_key: str) -> DailyCardState:
    """聚合名单 + 记录 + 历史评价 + 汇总 → 汇总卡状态快照（图3 全员模块化）。"""
    import json as _json

    roster, records, summary = await asyncio.gather(
        store.load_roster(),
        store.list_reports(date_key),
        store.get_summary(date_key),
    )
    record_of = {r.open_id: r for r in records}

    # 历史表最近一轮 AI 评价 → overall（已完成者的"AI补充后摘要"素材）
    overall_of: dict[str, str] = {}
    try:
        history_client = store.client_for(config.KIND_HISTORY)
        if history_client is not None:
            for row in await history_client.list_all_records(
                filter_info=store.date_key_filter(date_key), strict=False,
            ):
                f = row.get("fields", {})
                if store.plain(f.get(store.FH_STAGE)) != store.HIST_EVAL:
                    continue
                oid = store.plain(f.get(store.FH_OPEN_ID))
                try:
                    payload = _json.loads(store.plain(f.get(store.FH_CONTENT)) or "{}")
                except ValueError:
                    continue
                overall_of[oid] = str(payload.get("overall") or "")
    except Exception:  # noqa: BLE001 — 历史读失败不挡卡片
        logger.warning("日报历史表读取失败（AI 摘要行降级为空）")

    members: list[cards.MemberView] = []
    for m in roster:
        name = m.name or m.open_id[-8:]
        rec = record_of.get(m.open_id)
        if rec is None:
            members.append(cards.MemberView(
                open_id=m.open_id, name=name, status="none",
                work_brief="", done_brief="", ai_line="", full_text="",
            ))
            continue
        status = {
            store.ST_DONE: "done",
            store.ST_PENDING: "pending",
            store.ST_EVAL_ERROR: "eval_error",
        }.get(rec.status, "pending")
        first_advice = next(
            (line[3:].strip() for line in rec.ai_advice.splitlines()
             if line.startswith("1. ")),
            "",
        )
        if status == "done":
            overall = overall_of.get(m.open_id, "")
            ai_line = f"AI补充后摘要：{overall}" if overall else ""
        elif status == "pending":
            ai_line = f"AI建议：{first_advice}" if first_advice else "AI 评价进行中…"
        elif status == "eval_error":
            ai_line = "AI 评价异常，重试入口在本人私信卡片"
        else:
            ai_line = ""
        # 折叠面板五段全文（速递格子详情）：段标题+原文，未完成附 AI 建议
        full_lines: list[str] = []
        for key in cards.SECTION_INPUT_NAMES:
            text = (rec.sections.get(key) or "").strip()
            if text:
                full_lines.append(f"**{cards.SECTION_META[key][0]}**")
                full_lines.append(text)
                full_lines.append("")
        if status != "done" and rec.ai_advice:
            full_lines.append("**AI 评价与修改建议**（每天仅一轮）")
            full_lines.append(rec.ai_advice)
        members.append(cards.MemberView(
            open_id=m.open_id, name=name, status=status,
            work_brief=rec.sections.get("work", ""),
            done_brief=rec.sections.get("done", ""),
            ai_line=ai_line,
            full_text="\n".join(full_lines).strip(),
        ))

    submitted = sum(1 for mv in members if mv.status != "none")
    ai_done = sum(
        1 for mv in members
        if mv.status == "done" or (mv.status == "pending" and "AI建议" in mv.ai_line)
    )
    pending = sum(1 for mv in members if mv.status == "pending")
    pushed = sum(1 for mv in members if mv.status == "done")

    draft_md, published_at = "", ""
    if summary:
        draft_md, published_at = summary[1], summary[2]
    return DailyCardState(
        date_key=date_key,
        members=tuple(members),
        total=len(roster),
        submitted=submitted,
        ai_done=ai_done,
        pending=pending,
        pushed=pushed,
        draft_markdown=draft_md,
        published_at=published_at,
    )


async def refresh_daily_card(date_key: str | None = None) -> str | None:
    """upsert 当日入口卡：有锚先 PATCH，失败/无锚则发新卡并回写锚。

    历史日期护栏：锚不存在时只为当天建卡（防旧日期误重建）。
    """
    from app.modules.safety.feishu.notification import send_group_card, update_card

    date_key = config.normalize_date_key(date_key)
    if not config.enabled():
        logger.info("日报总闸未开，跳过入口卡刷新")
        return None
    state = await compute_state(date_key)
    card = cards.build_daily_card(state)
    chat_id = config.chat_id()

    redis = await get_redis()
    anchored = await redis.get(_card_msg_key(date_key))
    if anchored:
        anchored = anchored.decode() if isinstance(anchored, bytes) else str(anchored)
        if await update_card(anchored, card):
            return anchored
        logger.warning("日报入口卡 PATCH 失败，重建: date=%s", date_key)

    if date_key != config.today_key():
        logger.warning("历史日期无锚不重建入口卡: date=%s", date_key)
        return None
    msg_id = await send_group_card(
        chat_id,
        f"安全部门日报汇总 | {date_key}",
        "",
        elements=cards.daily_card_elements(state),
        header_template="green" if state.published_at else "blue",
        subtitle=cards.daily_card_subtitle(state),
    )
    if msg_id:
        await redis.set(_card_msg_key(date_key), msg_id, ex=_CARD_MSG_TTL_SECONDS)
    return msg_id


# ═══════════════════════════════════════════════════════════
# 提交（快路径）+ 后处理（慢路径）
# ═══════════════════════════════════════════════════════════

async def submit(
    operator_open_id: str,
    sections: dict[str, str],
    date_key: str | None = None,
) -> dict[str, Any]:
    """表单提交核心：查重 upsert + 历史追加。返回提交结果（含 stage）。

    返回 {"ok": bool, "stage": "first"|"final"|"revise", "record_id", "message"}
    注意：本函数含多次飞书 API 调用（≈1s/次），**只允许在后台任务或 REST
    上下文调用**，绝不能放进卡片回调 2.9s ACK 窗口（2026-11-18 真机实测：
    串行 3 次调用即被 wait_for 取消，写入腰斩且无 toast）。
    """
    if not config.enabled():
        return {"ok": False, "message": "功能未开启"}
    if not operator_open_id:
        return {"ok": False, "message": "无法识别提交人"}
    date_key = config.normalize_date_key(date_key)
    roster = await store.load_roster()
    name = next((m.name for m in roster if m.open_id == operator_open_id), "") \
        or operator_open_id[-8:]
    record_id, outcome = await store.upsert_report(
        date_key, operator_open_id, name, sections, config.bj_now(),
    )
    if not record_id:
        return {"ok": False, "message": "写入多维表格失败（连接未配置？）"}

    stage = {"created": STAGE_FIRST, "final": STAGE_FINAL, "revise": STAGE_REVISE}[outcome]
    await store.append_history(
        date_key, operator_open_id, name,
        store.HIST_FIRST if stage == STAGE_FIRST else store.HIST_FINAL,
        {"sections": sections},
    )
    message = {
        STAGE_FIRST: "初稿已提交，AI 评价生成中，建议稍后私信你；进度已同步至群「安全部门日报汇总」",
        STAGE_FINAL: "最终版已提交，已更新至群里「安全部门日报汇总」✅",
        STAGE_REVISE: "内容已更新至群里「安全部门日报汇总」✅",
    }[stage]
    return {"ok": True, "stage": stage, "record_id": record_id, "message": message}


#: 提交在途护栏（同人同日的并发提交只跑一条链，防双击竞态建重复记录）
_SUBMIT_INFLIGHT: set[tuple[str, str]] = set()


async def submit_and_notify(
    operator_open_id: str,
    sections: dict[str, str],
    date_key: str | None = None,
    *,
    source_msg_id: str = "",
) -> None:
    """卡片回调的后台提交链：upsert + 历史留痕 + **原表单卡原地变更为结果态** + 后处理。

    提交成功/失败都 PATCH 原表单卡为状态卡（用户拍板 2026-11-18：提交后
    原卡片变更状态，不再另发确认卡）；无 source_msg_id（REST 等场景）回退 DM。
    """
    date_key = config.normalize_date_key(date_key)
    key = (operator_open_id, date_key)
    if key in _SUBMIT_INFLIGHT:
        await _patch_or_dm(source_msg_id, operator_open_id,
                           cards.build_submitted_state_card(date_key, "上一次提交仍在处理中，请稍候勿重复点击", error=True))
        return
    _SUBMIT_INFLIGHT.add(key)
    try:
        result = await submit(operator_open_id, sections, date_key)
        if not result["ok"]:
            await _patch_or_dm(
                source_msg_id, operator_open_id,
                cards.build_submitted_state_card(date_key, result["message"], error=True),
            )
            return
        await _patch_or_dm(
            source_msg_id, operator_open_id,
            cards.build_submitted_state_card(date_key, result["message"]),
        )
        await post_submit(operator_open_id, result["stage"], date_key)
    except Exception:  # noqa: BLE001 — 后台链兜底，失败必达操作者
        logger.exception("日报后台提交链失败: operator=%s", operator_open_id)
        await _patch_or_dm(
            source_msg_id, operator_open_id,
            cards.build_submitted_state_card(date_key, "提交处理异常，请重试或联系管理员", error=True),
        )
    finally:
        _SUBMIT_INFLIGHT.discard(key)


async def _patch_or_dm(source_msg_id: str, open_id: str, card: dict[str, Any]) -> None:
    """原表单卡原地 PATCH；无锚/失败回退 DM，绝不静默。"""
    from app.modules.safety.feishu.notification import send_user_card_dict, update_card

    if source_msg_id and await update_card(source_msg_id, card):
        return
    try:
        await send_user_card_dict(open_id, card)
    except Exception:  # noqa: BLE001
        logger.exception("日报结果通知异常: open_id=%s", open_id)


async def post_submit(
    operator_open_id: str,
    stage: str,
    date_key: str | None = None,
) -> None:
    """提交后处理：首次提交触发 AI 评价；其余只刷新群卡。"""
    date_key = config.normalize_date_key(date_key)
    if stage == STAGE_FIRST:
        await run_evaluation(date_key, operator_open_id)
    else:
        await refresh_daily_card(date_key)


# ═══════════════════════════════════════════════════════════
# AI 一轮评价
# ═══════════════════════════════════════════════════════════

async def run_evaluation(
    date_key: str,
    operator_open_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """执行/重试一轮评价：回填 → DM 建议/失败卡 → 刷新群卡。"""
    from app.modules.safety.feishu.notification import send_user_card_dict

    if not config.enabled():
        return {"ok": False, "error": "功能未开启"}
    date_key = config.normalize_date_key(date_key)
    record = await store.find_report(date_key, operator_open_id)
    if record is None:
        return {"ok": False, "error": "当日无初稿记录"}
    if record.status == store.ST_DONE:
        return {"ok": False, "error": "已提交最终版，不再评价"}
    if record.ai_advice and record.status == store.ST_PENDING and not force:
        return {"ok": False, "error": "本轮评价已完成（每天仅一轮）"}

    from .profiles import profile_for

    result = await evaluation.evaluate_sections(record.sections, profile_for(record.name))
    name = record.name or await _roster_name(operator_open_id)
    if result["ok"]:
        advice_text = "\n".join(f"{i}. {s}" for i, s in enumerate(result["suggestions"], 1))
        await store.write_evaluation(record.record_id, advice_text)
        await store.append_history(
            date_key, operator_open_id, name, store.HIST_EVAL,
            {"suggestions": result["suggestions"], "overall": result["overall"]},
        )
        card = cards.build_suggestion_card(
            date_key, name, record.sections, result["suggestions"], result["overall"],
        )
        await send_user_card_dict(operator_open_id, card)
        await refresh_daily_card(date_key)
        return {"ok": True, "count": len(result["suggestions"])}

    await store.write_evaluation(record.record_id, "", error=True)
    card = cards.build_eval_fail_card(date_key, result["error"])
    await send_user_card_dict(operator_open_id, card)
    await refresh_daily_card(date_key)
    return {"ok": False, "error": result["error"]}


# ═══════════════════════════════════════════════════════════
# 表单 DM / 汇总 / 发布
# ═══════════════════════════════════════════════════════════

async def open_form_dm(operator_open_id: str, date_key: str | None = None) -> bool:
    """DM 四段表单卡；已有记录则预填当前内容（修改路径）。

    含查表+发卡两次飞书调用——回调窗口内同样只能后台化调用本函数。
    """
    from app.modules.safety.feishu.notification import send_user_card_dict

    from .profiles import profile_for

    date_key = config.normalize_date_key(date_key)
    record = await store.find_report(date_key, operator_open_id)
    defaults = record.sections if record is not None else None
    name = (record.name if record is not None else "") or await _roster_name(operator_open_id)
    card = cards.build_form_card(date_key, defaults, profile=profile_for(name))
    msg_id = await send_user_card_dict(operator_open_id, card)
    return bool(msg_id)


async def open_form_dm_notify(operator_open_id: str, date_key: str | None = None) -> None:
    """后台开表单链：失败 DM 告知（不静默）。"""
    try:
        if not await open_form_dm(operator_open_id, date_key):
            await _notify_operator_failure(operator_open_id, "填写表单发送失败，请稍后在群卡重试")
    except Exception:  # noqa: BLE001
        logger.exception("开表单链失败: operator=%s", operator_open_id)
        await _notify_operator_failure(operator_open_id, "填写表单发送异常，请稍后在群卡重试")


async def generate_leader(
    operator_open_id: str,
    date_key: str | None = None,
) -> dict[str, Any]:
    """负责人汇总：只聚合已完成最终版，写汇总草稿，刷群卡。"""
    if not config.enabled():
        return {"ok": False, "error": "功能未开启"}
    date_key = config.normalize_date_key(date_key)
    if not await _is_leader(operator_open_id):
        return {"ok": False, "error": "仅部门负责人可生成汇总"}
    summary = await store.get_summary(date_key)
    if summary is not None and summary[2]:
        return {"ok": False, "error": "当日日报已发布，不允许覆盖汇总"}
    records = [r for r in await store.list_reports(date_key) if r.status == store.ST_DONE]
    result = await aggregation.aggregate_reports(records, date_key)
    if not result["ok"]:
        await _notify_operator_failure(
            operator_open_id, f"{date_key} 负责人日报生成失败：{result['error']}",
        )
        return result
    record_id = await store.upsert_summary(date_key, result["report_markdown"], config.bj_now())
    if not record_id:
        return {"ok": False, "error": "汇总表写入失败（连接未配置？）"}
    await refresh_daily_card(date_key)
    return {"ok": True, "based_on": len(records)}


async def publish(
    operator_open_id: str,
    date_key: str | None = None,
) -> dict[str, Any]:
    """发布：写发布时间 + 全文日报卡发群 + 刷群卡。"""
    from app.modules.safety.feishu.notification import send_group_card

    if not config.enabled():
        return {"ok": False, "error": "功能未开启"}
    date_key = config.normalize_date_key(date_key)
    if not await _is_leader(operator_open_id):
        return {"ok": False, "error": "仅部门负责人可发布"}
    summary = await store.get_summary(date_key)
    if summary is None or not summary[1]:
        return {"ok": False, "error": "尚未生成汇总草稿"}
    record_id, markdown, published_at = summary
    if published_at:
        return {"ok": False, "error": "当日日报已发布"}
    msg_id = await send_group_card(
        config.chat_id(),
        f"【部门日报】{date_key}",
        markdown,
        header_template="green",
    )
    if not msg_id:
        return {"ok": False, "error": "全文日报发送失败，稍后可重试发布"}
    if not await store.mark_summary_published(record_id, config.bj_now()):
        return {"ok": False, "error": "发布时间写入失败（全文已发群，请勿重复发布）"}
    await refresh_daily_card(date_key)
    return {"ok": True, "message_id": msg_id}


async def get_status(date_key: str | None = None) -> dict[str, Any]:
    """状态视图（REST 读口径）：全员模块 + 四格统计 + 汇总态。"""
    date_key = config.normalize_date_key(date_key)
    state = await compute_state(date_key)
    return {
        "date_key": date_key,
        "enabled": config.enabled(),
        "chat_id": config.chat_id(),
        "total": state.total,
        "submitted": state.submitted,
        "ai_done": state.ai_done,
        "pending": state.pending,
        "pushed": state.pushed,
        "members": [
            {
                "name": mv.name,
                "status": mv.status,
                "ai_line": mv.ai_line,
            }
            for mv in state.members
        ],
        "summary_generated": bool(state.draft_markdown),
        "published_at": state.published_at,
    }
