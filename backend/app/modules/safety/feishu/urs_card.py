"""URS 智能审核 — 飞书卡片构建与回调处理（卡片 JSON 2.0）。

通知对象仅申请人（D8）；卡片回调挂载在 business_agent_bot_handler.card.action.trigger，
通过 payload["scope"] == "urs" 路由到 handle_urs_card_action。

卡片更新约定（2026-09-14 仓库机器人点击实测，本模块同机制）：WS 回调响应里
携带卡片更新不生效，统一改「纯 ACK + PATCH 原卡」（message_id 取回调事件
context.open_message_id）；toast 仅作锦上添花（生效则展示，不生效无碍）。
"""

import asyncio
import logging
import uuid
from typing import Any

from app.modules.safety.feishu.notification import (
    build_card_dict,
    button_row,
    send_user_card,
)

logger = logging.getLogger(__name__)

# 风险等级 → emoji
_RISK_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
_DIM_LABELS = {
    "mechanical": "机械", "electrical": "电气", "data": "数据",
    "environmental": "环境", "chemical": "化学",
}
_APPLICABILITY_EMOJI = {"mandatory": "🔴", "recommended": "🟡", "not_applicable": "❌"}


def _btn(value: dict, text: str, btn_type: str = "default") -> dict:
    """构建卡片按钮。value 与 behaviors[type=callback].value 双写同值
    （2.0 字段表首选 behaviors，旧式 value 仍被事件回传——回调解析两侧兼容）。"""
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": btn_type,
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def _action_row(*buttons: dict) -> dict:
    return button_row(*buttons)


def _patch_message_id(event_data: dict) -> str:
    """回调事件中的原卡 message_id（2.0 事件在 context）。"""
    context = event_data.get("context") or {}
    return str(context.get("open_message_id") or "")


async def _patch_card(event_data: dict, card: dict) -> None:
    """PATCH 替换回调来源卡片为 card（失败仅告警，不阻断回调）。"""
    from app.modules.safety.feishu.notification import update_card

    msg_id = _patch_message_id(event_data)
    if not msg_id:
        logger.warning("URS 卡片回调缺少 context.open_message_id，跳过卡片更新")
        return
    ok = await update_card(msg_id, card)
    if not ok:
        logger.warning("URS 卡片 PATCH 失败: message_id=%s", msg_id)


# ════════════════════════════════════════════════════════════════
# 内容构建
# ════════════════════════════════════════════════════════════════


def build_assessment_card(report: Any) -> dict:
    """评估结果卡（五维画像 + 综合等级 + 置信度）。"""
    risk = report.overall_risk_level or "low"
    emoji = _RISK_EMOJI.get(risk, "🟢")
    profile = report.risk_profile or {}

    lines = [
        f"设备类别：{report.equipment_category or '—'}｜申请部门：{report.department or '—'}",
        "———",
        "**五维风险画像**",
    ]
    for key, label in _DIM_LABELS.items():
        dim = profile.get(key) or {}
        level = dim.get("level", "low")
        indicators = "、".join(dim.get("indicators") or []) or "无"
        lines.append(f"{_RISK_EMOJI.get(level, '⚪')} {label}风险={level}（{indicators}）")
    lines.append("———")
    lines.append(f"**综合风险：{emoji} {risk}** ｜ 置信度 {int((report.ai_confidence or 0) * 100)}%")

    if report.review_status == "human_review":
        lines.append("⚠️ 置信度不足，需人工复核风险画像。")

    elements: list = []
    if report.review_status == "human_review":
        elements.append(_action_row(
            _btn({"scope": "urs", "action": "urs_confirm", "urs_id": str(report.id)}, "✅ 确认画像", "primary"),
        ))
    return build_card_dict(
        f"{emoji} URS 审核结果：{report.equipment_name}",
        "\n".join(lines),
        header_template="blue",
        elements=elements,
    )


def build_conclusion_card(report: Any, items: list[Any] | None = None) -> dict:
    """结论卡（全文直出，无按钮）：基本信息 + 评分结论 + 五维画像（含依据与
    AI 摘要）+ 逐条审核统计与不通过条目 + 整改要求 + AI 总结。

    2026-09-18 产品简化：原「查看详情」按钮展开详情卡的交互取消，
    全部内容直接进结论卡（items 为空时跳过逐条审核段）。
    """
    grade = report.grade or "—"
    conclusion = report.conclusion or "—"
    cn = "✅ 通过" if conclusion == "approved" else "❌ 不通过"
    risk = report.overall_risk_level or "low"
    profile = report.risk_profile or {}

    lines = [
        f"URS 编号：{report.urs_no}",
        f"设备：{report.equipment_name}｜类别：{report.equipment_category or '—'}",
        f"申请部门：{report.department or '—'}｜申请人：{report.applicant_name or '—'}",
        "———",
        f"**评分：{report.score if report.score is not None else '—'} 分（{grade} 级）｜结论：{cn}**",
        "———",
        f"**五维风险画像**（综合 {_RISK_EMOJI.get(risk, '⚪')} {risk}"
        f"｜置信度 {int((report.ai_confidence or 0) * 100)}%）",
    ]
    for key, label in _DIM_LABELS.items():
        dim = profile.get(key) or {}
        level = dim.get("level", "low")
        indicators = "、".join(dim.get("indicators") or []) or "无"
        lines.append(f"{_RISK_EMOJI.get(level, '⚪')} {label}={level}（{indicators}）")
        evidence = str(dim.get("evidence") or "").strip()
        if evidence:
            lines.append(f"　依据：{evidence[:80]}")
    reasoning = str(report.risk_profile_reasoning or "").strip()
    if reasoning:
        lines.append(f"AI 评估摘要：{reasoning[:200]}")

    # 逐条审核（items 未传/为空 → 跳过该段）
    applicable = [
        it for it in (items or [])
        if getattr(it, "applicability", None) in ("mandatory", "recommended")
    ]
    if applicable:
        passed = sum(1 for it in applicable if it.review_status == "passed")
        failed = sum(1 for it in applicable if it.review_status == "failed")
        veto_hit = sum(1 for it in applicable if it.is_veto and it.review_status == "failed")
        lines.append("———")
        lines.append(
            f"**逐条审核**：适用 {len(applicable)} 项｜✅ 通过 {passed}｜❌ 不通过 {failed}"
            + (f"｜⚠️ 否决项命中 {veto_hit}" if veto_hit else "")
        )
        for it in [x for x in applicable if x.review_status == "failed"][:8]:
            tag = "否决" if it.is_veto else "强制"
            lines.append(f"- {it.item_no} [{tag}] {it.standard_title}：{(it.review_comment or '—')[:60]}")

    reqs = report.rectification_requirements or []
    if reqs:
        lines.append("———")
        lines.append(f"**整改要求（{len(reqs)} 项）**")
        for i, req in enumerate(reqs[:10], 1):
            lines.append(f"{i}. {req.get('requirement') or req.get('item_no')}")
        if len(reqs) > 10:
            lines.append(f"… 等共 {len(reqs)} 项")

    summary = report.review_result.get("summary") if report.review_result else None
    if summary:
        lines.append("———")
        lines.append(str(summary))
    lines.append("———")
    lines.append("ℹ️ 本结论为 AI 辅助判断，仅供参考。")

    return build_card_dict(
        f"URS 审核结论：{report.equipment_name}",
        "\n".join(lines),
        header_template="orange" if conclusion == "rejected" else "green",
    )


def build_appeal_result_card(report: Any) -> dict:
    """申诉重评结果卡（新旧画像对比 + 调整依据）。"""
    appeal = report.appeal_result or {}
    old_overall = appeal.get("old_overall") or "?"
    new_overall = report.overall_risk_level or "?"
    lines = [
        f"设备：{report.equipment_name}",
        "———",
        f"**申诉理由**：{report.appeal_reason or '—'}",
        "———",
        f"**风险画像调整**：{_RISK_EMOJI.get(old_overall, '⚪')} {old_overall} → {_RISK_EMOJI.get(new_overall, '⚪')} {new_overall}",
        f"**调整依据**：{appeal.get('basis') or '重新评估完成'}",
        f"**当前状态**：{report.review_status}",
    ]
    return build_card_dict(
        f"URS 申诉结果：{report.equipment_name}",
        "\n".join(lines),
        header_template="purple",
        elements=[
            _action_row(_btn({"scope": "urs", "action": "urs_view", "urs_id": str(report.id)}, "查看详情", "primary")),
        ],
    )


def build_detail_card(report: Any, items: list[Any]) -> dict[str, Any]:
    """详情卡：画像依据 + 逐条审核结果 + 整改要求（结论卡/评估卡「查看详情」的展开）。

    与结论卡/评估卡的差异：补充每维风险依据、AI 推理摘要、逐条审核统计与
    不通过条目、全量整改要求——这些在摘要卡上放不下。
    """
    risk = report.overall_risk_level or "low"
    profile = report.risk_profile or {}
    lines = [
        f"URS 编号：{report.urs_no}",
        f"设备：{report.equipment_name}｜类别：{report.equipment_category or '—'}",
        f"申请部门：{report.department or '—'}｜申请人：{report.applicant_name or '—'}",
        f"当前状态：{report.review_status}",
        "———",
        f"**五维风险画像**（综合 {_RISK_EMOJI.get(risk, '⚪')} {risk}｜置信度 {int((report.ai_confidence or 0) * 100)}%）",
    ]
    for key, label in _DIM_LABELS.items():
        dim = profile.get(key) or {}
        level = dim.get("level", "low")
        indicators = "、".join(dim.get("indicators") or []) or "无"
        lines.append(f"{_RISK_EMOJI.get(level, '⚪')} {label}={level}（{indicators}）")
        evidence = str(dim.get("evidence") or "").strip()
        if evidence:
            lines.append(f"　依据：{evidence[:80]}")
    reasoning = str(report.risk_profile_reasoning or "").strip()
    if reasoning:
        lines.append(f"AI 评估摘要：{reasoning[:200]}")

    # 逐条审核（适配完成前 items 的 applicability 为空 → 跳过该段）
    applicable = [
        it for it in items
        if getattr(it, "applicability", None) in ("mandatory", "recommended")
    ]
    if applicable:
        passed = sum(1 for it in applicable if it.review_status == "passed")
        failed = sum(1 for it in applicable if it.review_status == "failed")
        veto_hit = sum(1 for it in applicable if it.is_veto and it.review_status == "failed")
        lines.append("———")
        lines.append(
            f"**逐条审核**：适用 {len(applicable)} 项｜✅ 通过 {passed}｜❌ 不通过 {failed}"
            + (f"｜⚠️ 否决项命中 {veto_hit}" if veto_hit else "")
        )
        failed_items = [it for it in applicable if it.review_status == "failed"]
        for it in failed_items[:8]:
            tag = "否决" if it.is_veto else "强制"
            lines.append(f"- {it.item_no} [{tag}] {it.standard_title}：{(it.review_comment or '—')[:60]}")
        if len(failed_items) > 8:
            lines.append(f"… 等共 {len(failed_items)} 项不通过")

    reqs = report.rectification_requirements or []
    if reqs:
        lines.append("———")
        lines.append(f"**整改要求（{len(reqs)} 项）**")
        for i, req in enumerate(reqs[:10], 1):
            lines.append(f"{i}. {req.get('requirement') or req.get('item_no')}")
        if len(reqs) > 10:
            lines.append(f"… 等共 {len(reqs)} 项")

    summary = report.review_result.get("summary") if report.review_result else None
    if summary:
        lines.append("———")
        lines.append(str(summary))

    buttons = [
        _btn({"scope": "urs", "action": "urs_back", "urs_id": str(report.id)}, "◀ 返回", "default"),
    ]
    return build_card_dict(
        f"🔍 URS 审核详情：{report.equipment_name}",
        "\n".join(lines),
        header_template="blue",
        elements=[_action_row(*buttons)],
    )


# ════════════════════════════════════════════════════════════════
# 主动通知（URSService 调用，仅申请人）
# ════════════════════════════════════════════════════════════════


async def notify_assessment_result(report: Any) -> bool:
    if not report.applicant_open_id:
        return False
    card = build_assessment_card(report)
    body = card["body"]["elements"]
    return await send_user_card(
        open_id=report.applicant_open_id,
        title=card["header"]["title"]["content"],
        content=str(body[0].get("content") or ""),
        elements=body[1:],
    )


async def notify_conclusion(report: Any, items: list[Any] | None = None) -> bool:
    if not report.applicant_open_id:
        return False
    card = build_conclusion_card(report, items)
    body = card["body"]["elements"]
    return await send_user_card(
        open_id=report.applicant_open_id,
        title=card["header"]["title"]["content"],
        content=str(body[0].get("content") or ""),
        elements=body[1:],
    )


async def notify_appeal_result(report: Any) -> bool:
    if not report.applicant_open_id:
        return False
    card = build_appeal_result_card(report)
    body = card["body"]["elements"]
    return await send_user_card(
        open_id=report.applicant_open_id,
        title=card["header"]["title"]["content"],
        content=str(body[0].get("content") or ""),
        elements=body[1:],
    )


# ════════════════════════════════════════════════════════════════
# 卡片回调（card.action.trigger，payload["scope"] == "urs"）
# ════════════════════════════════════════════════════════════════


async def handle_urs_card_action(payload: dict, event_data: dict) -> dict | None:
    """处理 URS 卡片按钮回调：执行动作后 PATCH 原卡，返回纯 ACK（None）。

    辅助判断模式仅保留信息浏览类动作（查看详情/返回/确认画像——最后者为
    Web 提交路径的中间卡所有，飞书直传链路不再产生需确认的中间卡）。
    """
    action = payload.get("action")
    urs_id_raw = payload.get("urs_id")
    if not action or not urs_id_raw:
        return None
    try:
        report_id = uuid.UUID(urs_id_raw)
    except (ValueError, TypeError):
        return None

    if action == "urs_view":
        return await _show_detail(report_id, event_data)
    if action == "urs_back":
        return await _show_summary_card(report_id, event_data)
    if action == "urs_confirm":
        return await _confirm_assessment(report_id, event_data)
    return None


async def _fetch_report(report_id: uuid.UUID):
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        from app.modules.safety.service.ehs_change.urs import URSService

        return await URSService(db).get_report(report_id)


async def _fetch_report_and_items(report_id: uuid.UUID) -> tuple[Any, list[Any]]:
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        from app.modules.safety.service.ehs_change.urs import URSService

        svc = URSService(db)
        report = await svc.get_report(report_id)
        items = await svc.get_items(report_id) if report else []
        return report, items


async def _show_detail(report_id: uuid.UUID, event_data: dict[str, Any]) -> dict[str, Any] | None:
    """查看详情：PATCH 为详情卡（画像依据 + 逐条审核 + 整改要求）。

    此前对已出结论的报告重发同一张结论卡，用户看不到任何变化。
    """
    report, items = await _fetch_report_and_items(report_id)
    if report is None:
        return {"toast": {"type": "error", "content": "记录不存在"}}
    await _patch_card(event_data, build_detail_card(report, items))
    return None


async def _show_summary_card(report_id: uuid.UUID, event_data: dict[str, Any]) -> dict[str, Any] | None:
    """详情卡「返回」：PATCH 回结论卡/评估卡摘要视图（旧卡兼容；结论卡现为全文直出）。"""
    report, items = await _fetch_report_and_items(report_id)
    if report is None:
        return {"toast": {"type": "error", "content": "记录不存在"}}
    card = (
        build_conclusion_card(report, items)
        if report.conclusion
        else build_assessment_card(report)
    )
    await _patch_card(event_data, card)
    return None


async def _confirm_assessment(report_id: uuid.UUID, event_data: dict) -> dict | None:
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            from app.modules.safety.service.ehs_change.urs import URSService

            report = await URSService(db).confirm_assessment(report_id)
            await db.commit()
        if report is None:
            return {"toast": {"type": "error", "content": "记录不存在"}}
        await _patch_card(event_data, build_assessment_card(report))
        # 确认后自动续跑适配+结论（对话上传链路的「全自动」承诺；
        # 无 corrections 时 confirm 不触发适配，此处补链）
        if report.review_status == "assessment_confirmed":
            asyncio.create_task(_run_confirmed_chain_background(report_id))
        return None
    except ValueError as e:
        return {"toast": {"type": "error", "content": str(e)}}


async def _run_confirmed_chain_background(report_id: uuid.UUID) -> None:
    """画像人工确认后，后台自动完成标准适配 + 审核结论（失败告警不打扰用户）。"""
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            from app.modules.safety.service.ehs_change.urs import URSService

            report = await URSService(db).run_adaptation_and_conclusion(report_id)
            await db.commit()
        logger.info(
            "URS 确认后链路完成: report_id=%s status=%s",
            report_id, report.review_status if report else None,
        )
    except Exception:
        logger.exception("URS 确认后链路失败: report_id=%s", report_id)


async def send_urs_review_pdf(report_id: uuid.UUID) -> bool:
    """结论完成后把 PDF 审核报告发回来源会话（辅助判断：文件进、文件出）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.ehs_change.urs import URSService

    chat_id: str | None = None
    urs_no = ""
    pdf_bytes = b""
    async with async_session_factory() as db:
        svc = URSService(db)
        report = await svc.get_report(report_id)
        if report is None or not report.source_chat_id:
            logger.warning("URS PDF 发送跳过（无来源会话）: report_id=%s", report_id)
            return False
        chat_id = report.source_chat_id
        urs_no = report.urs_no
        try:
            pdf_bytes = await svc.export_pdf(report_id)
        except Exception:
            logger.exception("URS PDF 导出失败: report_id=%s", report_id)
            return False
    if not pdf_bytes:
        return False

    from datetime import datetime

    from app.modules.safety.feishu.chat_sender import send_file_to_chat

    filename = f"{urs_no}_URS审核报告_{datetime.now().strftime('%Y%m%d')}.pdf"
    sent = await send_file_to_chat(chat_id, pdf_bytes, filename)
    if sent:
        logger.info("URS PDF 审核报告已发送: report_id=%s file=%s", report_id, filename)
    return sent


async def notify_review_failed(
    report_id: uuid.UUID, error_message: str | None, applicant_open_id: str | None,
) -> bool:
    """全链路评估失败时通知申请人（失败不静默）。"""
    if not applicant_open_id:
        return False
    reason = (error_message or "").strip() or "未知原因"
    return await send_user_card(
        open_id=applicant_open_id,
        title="❌ URS 审核评估失败",
        content=(
            f"很抱歉，本次 URS 文档的 AI 评估未能完成。\n\n"
            f"失败原因：{reason[:300]}\n\n"
            f"请稍后重试或联系管理员。"
        ),
        header_template="red",
    )
