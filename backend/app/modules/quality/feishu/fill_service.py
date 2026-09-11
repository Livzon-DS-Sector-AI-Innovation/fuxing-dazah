"""对话式填报：@机器人发指令 → 解析 → 按标准库限度判定 → 写入检验任务 → 群内回执。

指令格式示例：
    @消息推送机器人 批号 HAF2608001B 水分 4.5 炽灼残渣 0.10 残留溶剂(乙醇) 30
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from app.modules.quality.feishu import event_client
from app.modules.quality.feishu.client import (
    QUALITY_FEISHU_CHAT_IDS,
    QUALITY_FEISHU_CREATE_USER_IDS,
    QUALITY_FEISHU_USER_IDS,
)
from app.modules.quality.feishu.message import send_chat_text
from app.modules.quality.models import QualityStandardDocument, QualityTestTask
from app.modules.quality.repository import (
    get_test_task_by_batch,
    get_test_task_by_batch_number,
    list_standard_documents,
    list_test_results,
    update_test_results_fill,
)
from app.modules.quality.service import TestTaskService

logger = logging.getLogger(__name__)

_BATCH_RE = re.compile(r"批\s*号[：:\s]*([A-Za-z0-9-]+)")
_PAIR_RE = re.compile(r"([一-鿿][^\s]*)\s+(\d+(?:\.\d+)?)")

# 液相计算表解析覆盖的项目名片段（这些项目上传计算表自动填入，表单卡片不再列出）
# 生物组项目（微生物/效价/含量类），其余归理化组
_BIO_PATTERNS = ["需氧菌", "效价", "含量"]
_LC_SHEET_PATTERNS = ["杂质", "万古霉素", "总杂质", "任何未知杂质", "rs"]


def _extract_command(event: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """从 im.message.receive_v1 事件提取 (chat_id, sender_open_id, 消息文本, chat_type)。"""
    try:
        ev = event.get("event", {})
        msg = ev.get("message", {})
        chat_id = msg.get("chat_id")
        sender = (ev.get("sender", {}).get("sender_id") or {}).get("open_id")
        content = msg.get("content", "{}")
        text = json.loads(content).get("text", "")
        return chat_id, sender, text, msg.get("chat_type", "group")
    except Exception:
        return None, None, None, None


def _allowed(chat_id: str, sender: str) -> bool:
    if QUALITY_FEISHU_CHAT_IDS and chat_id not in QUALITY_FEISHU_CHAT_IDS:
        return False
    if QUALITY_FEISHU_USER_IDS and sender not in QUALITY_FEISHU_USER_IDS:
        return False
    return True


def _allowed_create(sender: str) -> bool:
    """新建任务权限：配置了 QUALITY_FEISHU_CREATE_USER_IDS 时仅白名单用户可建；空 = 不限制。"""
    if not QUALITY_FEISHU_CREATE_USER_IDS:
        return True
    return bool(sender) and sender in QUALITY_FEISHU_CREATE_USER_IDS


_CREATE_DENY_TEXT = "⛔ 你没有新建任务的权限，请联系质量管理员"


async def _known_codes(db) -> list[str]:
    """标准库已配置的全部产品代号（错误提示用）。"""
    docs = await list_standard_documents(db)
    return sorted({(d.product_code or "").strip() for d in docs if (d.product_code or "").strip()})


async def _resolve_docs_by_batch(db, batch: str) -> list[QualityStandardDocument]:
    """批号必然含产品代号：按批号开头收敛到该代号的标准文件（标准文档）。"""
    docs = await list_standard_documents(db)
    _, matched = TestTaskService._match_docs_by_batch_code(docs, batch)
    return matched


def _doc_to_card_dict(doc: QualityStandardDocument) -> dict:
    return {
        "id": str(doc.id),
        "file_no": doc.file_no,
        "product_code": doc.product_code,
        "product_internal_code": doc.product_internal_code,
    }


async def _resolve_task_by_batch(db, batch: str) -> QualityTestTask | None:
    """按批号查任务；同批号跨产品时用批号代号收敛到对应产品。"""
    task = await get_test_task_by_batch_number(db, batch)
    if not task:
        return None
    matched = await _resolve_docs_by_batch(db, batch)
    if not matched:
        return task

    def _norm(n: str) -> str:
        return re.sub(r"\s+", "", n)

    if _norm(task.product_name) in {_norm(d.product_name) for d in matched}:
        return task
    return await get_test_task_by_batch(db, matched[0].product_name, batch)


# 标准文件多选点选卡片的进行中勾选状态（按批号隔离，任务创建成功后清除）
_PENDING_DOC_SELECT: dict[str, set[str]] = {}


async def _reply_existing_task(chat_id: str, batch: str, task: QualityTestTask) -> None:
    """批号已有任务时的回执：不允许重复创建，带状态进度；填报中的任务另发填报卡片。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.message import send_chat_text, send_fill_card

    async with async_session_factory() as db:
        rows = await list_test_results(db, task.id)
    status_label = {
        "in_progress": "填报中",
        "pending_review": "待复核",
        "completed": "已完成",
        "void": "已作废",
    }.get(task.status, task.status)
    await send_chat_text(
        chat_id,
        f"⚠️ 批号 {batch} 已存在检验任务（{status_label}，"
        f"已判定 {sum(1 for r in rows if r.is_pass is not None)}/{len(rows)} 项），不允许重复创建",
    )
    if task.status == "in_progress":
        bio_rows, chem_rows = _unfilled_groups(rows)
        await send_fill_card(chat_id, batch, [("生物组", bio_rows), ("理化组", chem_rows)])


async def _build_progress_text(db, batch: str, task: QualityTestTask) -> str:
    """进度查询文本：填报中（列已填/待填项目）/ 待分配（未到出报日）/ 已出报（出报时间）/ 已作废。"""
    from app.modules.quality.repository import get_latest_report_record_by_task

    rows = await list_test_results(db, task.id)
    filled_rows = [r for r in rows if r.is_pass is not None]
    filled_names = [
        f"{r.item_name}={r.result_value if r.result_value is not None else r.result_text}"
        for r in filled_rows
    ]
    filled_show = "、".join(filled_names)
    lines = [f"📊 批号 {batch}：{task.product_name}"]
    if task.status == "void":
        lines.append("状态：已作废")
        return "\n".join(lines)
    if task.status == "completed":
        latest = await get_latest_report_record_by_task(db, task.id)
        if latest and latest.created_at:
            report_time = latest.created_at.strftime("%Y-%m-%d %H:%M")
        else:
            report_time = task.report_date or "-"
        lines.append(f"状态：✅ 已出报（出报时间：{report_time}）")
        lines.append(f"进度：已判定 {len(filled_rows)}/{len(rows)} 项")
        if filled_rows:
            lines.append(f"项目结果：{filled_show}")
        return "\n".join(lines)
    if task.status == "pending_review":
        lines.append("状态：🔍 待复核（已全部填报，等待专员审核）")
        lines.append(f"进度：已判定 {len(filled_rows)}/{len(rows)} 项")
        if filled_rows:
            lines.append(f"项目结果：{filled_show}")
        return "\n".join(lines)
    # in_progress
    if task.report_date and task.report_date > _today_str():
        lines.append(f"状态：⏳ 待分配（出报日期 {task.report_date}，还没到出报日期）")
    elif task.report_date:
        lines.append(f"状态：📝 填报中（出报日期 {task.report_date}）")
    else:
        lines.append("状态：📝 填报中（未填出报日期）")
    lines.append(f"进度：已判定 {len(filled_rows)}/{len(rows)} 项")
    if filled_rows:
        lines.append(f"已填项目：{filled_show}")
    unfilled = [r.item_name for r in rows if r.is_pass is None]
    if unfilled:
        lines.append(f"待填项目：{'、'.join(unfilled)}")
    return "\n".join(lines)


@event_client.on_event("im.message.receive_v1")
async def handle_fill_command(event: dict) -> None:
    """对话式填报入口。"""
    chat_id, sender, text, chat_type = _extract_command(event)
    logger.info("质量飞书消息: chat=%s chat_type=%s sender=%s text=%r", chat_id, chat_type, sender, text)
    if not chat_id or not text:
        return
    if chat_type != "p2p" and not _allowed(chat_id, sender or ""):
        return
    batch_m = _BATCH_RE.search(text)
    if not batch_m:
        kw = text.strip()
        from app.modules.quality.feishu.message import (
            send_batch_form_card,
            send_menu_card,
        )

        # 机器人自定义菜单指令：无批号裸关键词 → 对应批号输入卡片
        if "建任务" in kw or kw == "新建任务":
            await send_batch_form_card(chat_id, "create_task")
            return
        if kw and ("填报" in kw or "填写" in kw):
            await send_batch_form_card(chat_id, "fill")
            return
        if "进度" in kw:
            await send_batch_form_card(chat_id, "progress")
            return
        if "菜单" in kw or "帮助" in kw or "开始" in kw or kw.lower() in ("hi", "hello", "你好"):
            await send_menu_card(chat_id)
            return
        if chat_type == "p2p":
            await send_menu_card(chat_id)
            return
        await send_chat_text(chat_id, "⚠️ 未识别批号。格式：批号 XXX 项目 数值 …（如：批号 HAF2608001B 水分 4.5），或直接发「填报 批号 XXX」打开表单")
        return
    batch = batch_m.group(1)
    pairs = _PAIR_RE.findall(text)

    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        # 「建任务 批号 XXX」：批号自动识别代号 → 标准文件（可多选）→ 建任务卡片
        if not pairs and "建任务" in text:
            from app.modules.quality.feishu.message import (
                send_create_task_card,
                send_pick_doc_card,
            )

            if not _allowed_create(sender or ""):
                await send_chat_text(chat_id, _CREATE_DENY_TEXT)
                return
            # 已存在任务：不允许重复创建/编辑，回执状态并下发填报卡片
            existing = await _resolve_task_by_batch(db, batch)
            if existing:
                await _reply_existing_task(chat_id, batch, existing)
                return
            matched = await _resolve_docs_by_batch(db, batch)
            if not matched:
                known = await _known_codes(db)
                await send_chat_text(
                    chat_id,
                    f"⚠️ 批号 {batch} 开头未匹配产品代号（标准库代号：{'、'.join(known) or '未配置'}），无法建任务",
                )
                return
            doc_dicts = [_doc_to_card_dict(d) for d in matched]
            if len(matched) == 1:
                await send_create_task_card(chat_id, batch, doc_dicts)
            else:
                _PENDING_DOC_SELECT.pop(batch, None)
                await send_pick_doc_card(chat_id, batch, doc_dicts, set())
            return

        # 「进度 批号 XXX」：进度查询（四态：未创建/待分配/填报中/已出报）
        if not pairs and "进度" in text:
            t = await _resolve_task_by_batch(db, batch)
            if not t:
                await send_chat_text(
                    chat_id,
                    f"⚠️ 批号 {batch} 未创建任务（可发送「建任务 批号 {batch}」创建）",
                )
                return
            await send_chat_text(chat_id, await _build_progress_text(db, batch, t))
            return

        task = await _resolve_task_by_batch(db, batch)
        if not task:
            await send_chat_text(chat_id, f"⚠️ 未找到批号 {batch} 的检验任务，请先在系统建任务")
            return
        if task.status != "in_progress":
            hint = {
                "pending_review": "待复核中，请专员审核",
                "completed": "已完成（已出报）",
                "void": "已作废",
            }.get(task.status, task.status)
            await send_chat_text(chat_id, f"⚠️ 批号 {batch} 的任务状态为 {hint}，不可填报")
            return

        # 只发「填报 批号 XXX」无数值 → 发表单卡片
        if not pairs and ("填报" in text or "填写" in text):
            from app.modules.quality.feishu.message import send_fill_card

            rows = await list_test_results(db, task.id)
            bio_rows, chem_rows = _unfilled_groups(rows)
            if not bio_rows and not chem_rows:
                await send_chat_text(
                    chat_id,
                    f"✅ 批号 {batch} 的数值型项目已全部填写，或剩余项目均由液相计算表解析覆盖（请上传计算表自动填入）",
                )
                return
            await send_fill_card(chat_id, batch, [("生物组", bio_rows), ("理化组", chem_rows)])
            return

        rows = await list_test_results(db, task.id)
        norm_rows = {TestTaskService._norm_name(r.item_name): r for r in rows}
        updates: list[dict] = []
        filled: list[str] = []
        problems: list[str] = []
        unmatched_names: list[str] = []
        alerts: list[str] = []  # 不合格明细（不落库，仅发提醒）
        for name, value_str in pairs:
            value = float(value_str)
            row = norm_rows.get(TestTaskService._norm_name(name))
            if row is None:
                unmatched_names.append(name)
                continue
            # 相同 SOP 号自动匹配：填一次，同 SOP 的未填行按各自限度判定落库
            sop = _norm_sop(row.sop_no)
            targets = (
                [r for r in rows if _norm_sop(r.sop_no) == sop and r.is_pass is None] if sop else [row]
            )
            for target in targets:
                if target.judge_mode == "manual":
                    problems.append(f"{target.item_name} 为文字型项目，请用「文字项一键合格」或人工判定")
                    continue
                verdict = TestTaskService._judge_value(
                    target.operator, target.limit_min, target.limit_max, value
                )
                if verdict is None:
                    problems.append(f"{target.item_name} 限度缺失，无法自动判定")
                    continue
                unit = TestTaskService._unit_of(target.standard_text)
                if verdict is False:
                    # 不合格不落库：记录台账并发提醒，由人工处理
                    await TestTaskService.record_unqualified_event(
                        db, task, target, value, "manual", notify=True, origin_chat_id=chat_id,
                    )
                    limit_text = (
                        f"{target.operator or ''} {target.limit_min if target.limit_min is not None else ''}"
                        f"{target.limit_max if target.limit_max is not None else ''}{unit}"
                    ).strip()
                    alerts.append(f"{target.item_name}={value}{unit}（限度 {limit_text}）")
                    continue
                updates.append({
                    "result_id": target.id,
                    "result_text": str(value),
                    "result_value": value,
                    "is_pass": verdict,
                    "source": "manual",
                    "inspection_record_id": None,
                    "filled_by": None,
                    "filled_at": datetime.now(UTC),
                })
                filled.append(f"{target.item_name}={value}{unit}（合格）")
        if updates:
            await update_test_results_fill(db, updates)
        advanced = await TestTaskService.auto_advance_pending_review(db, task.id)
        await db.commit()

    lines = [f"✅ 批号 {batch} 已落库 {len(filled)} 项："]
    if filled:
        lines.append("，".join(filled))
    if advanced:
        lines.append("🔍 已全部填报完成，进入待复核，请专员审核")
    if unmatched_names:
        lines.append("⚠️ 未匹配项目：" + "、".join(unmatched_names) + "（请核对标准库项目名）")
    if problems:
        lines.append("⚠️ " + "；".join(problems))
    if alerts:
        lines.append("🚨 不合格未落库（已记录台账）：")
        lines.extend(f"- {a}" for a in alerts)
        lines.append("请人工处理")
    await send_chat_text(chat_id, "\n".join(lines))


@event_client.on_event("application.bot.menu_v6")
async def handle_bot_menu_event(event: dict) -> None:
    """机器人自定义菜单点击事件（响应动作=推送事件）：event_key → 对应批号输入卡片。"""
    ev = event.get("event", {})
    key = str(ev.get("event_key") or ev.get("eventKey") or "").strip()
    key_lower = key.lower()
    if "create" in key_lower or "建任务" in key or "新建" in key:
        nxt = "create_task"
    elif "fill" in key_lower or "填报" in key or "填写" in key:
        nxt = "fill"
    elif "progress" in key_lower or "进度" in key:
        nxt = "progress"
    else:
        logger.warning("质量飞书菜单事件未识别 event_key: %s", key)
        return
    from app.modules.quality.feishu.message import (
        build_batch_form_card,
        send_batch_form_card,
        send_user_interactive_card,
    )

    # 优先单聊：菜单事件无群上下文，按操作人 open_id 发单聊卡片
    # 事件结构：event.operator.operator_id.open_id（实测嵌套两层）
    operator = ev.get("operator") if isinstance(ev.get("operator"), dict) else {}
    operator_id_obj = operator.get("operator_id") if isinstance(operator.get("operator_id"), dict) else {}
    operator_open_id = (
        operator_id_obj.get("open_id")
        or operator.get("open_id")
        or ev.get("operator_open_id")
        or ""
    )
    if operator_open_id:
        await send_user_interactive_card(operator_open_id, build_batch_form_card(nxt))
        return
    # 取不到操作人时回落到配置的全部白名单群
    for cid in QUALITY_FEISHU_CHAT_IDS:
        await send_batch_form_card(cid, nxt)


@event_client.on_event("card.action.trigger")
async def handle_card_action(event: dict) -> None:
    """卡片回调入口：表单提交 → 解析 form_value → 写入任务 → 群内回执。"""
    ev = event.get("event", {})
    action_value = (ev.get("action") or {}).get("value") or {}
    form_value = (ev.get("action") or {}).get("form_value") or {}
    ctx = ev.get("context") or {}
    chat_id = ctx.get("open_chat_id") or ctx.get("chat_id")
    # 卡片操作人（用于建任务权限校验）
    operator_ev = ev.get("operator") if isinstance(ev.get("operator"), dict) else {}
    sender = operator_ev.get("open_id") or ""
    if not sender:
        operator_id_obj = operator_ev.get("operator_id")
        if isinstance(operator_id_obj, dict):
            sender = operator_id_obj.get("open_id") or ""

    # 建任务卡片提交
    # 菜单导航按钮 → 批号输入卡片
    if action_value.get("action") == "menu":
        from app.modules.quality.feishu.message import send_batch_form_card

        if chat_id:
            await send_batch_form_card(chat_id, action_value.get("next", "fill"))
        return None

    # 批号输入提交 → 路由到建任务/填报/进度
    if action_value.get("action") == "batch_input":
        from app.core.database import async_session_factory
        from app.modules.quality.feishu.message import (
            send_batch_form_card,
            send_create_task_card,
            send_fill_card,
            send_pick_doc_card,
        )

        nxt = action_value.get("next", "fill")
        batch2 = (form_value.get("batch") or "").strip()
        if not batch2:
            return {"type": "toast", "toast": {"type": "info", "content": "请输入批号"}}
        if nxt == "create_task":
            if not _allowed_create(sender):
                return {"type": "toast", "toast": {"type": "warning", "content": _CREATE_DENY_TEXT}}
            if chat_id:
                async with async_session_factory() as db3:
                    # 已存在任务：不允许重复创建/编辑
                    t3 = await _resolve_task_by_batch(db3, batch2)
                    if t3:
                        await _reply_existing_task(chat_id, batch2, t3)
                        return None
                    matched = await _resolve_docs_by_batch(db3, batch2)
                    if not matched:
                        known = await _known_codes(db3)
                        await send_chat_text(
                            chat_id,
                            f"⚠️ 批号 {batch2} 开头未匹配产品代号（标准库代号：{'、'.join(known) or '未配置'}），无法建任务",
                        )
                        return None
                    doc_dicts = [_doc_to_card_dict(d) for d in matched]
                    if len(matched) == 1:
                        await send_create_task_card(chat_id, batch2, doc_dicts)
                    else:
                        _PENDING_DOC_SELECT.pop(batch2, None)
                        await send_pick_doc_card(chat_id, batch2, doc_dicts, set())
            return None
        if nxt == "progress":
            async with async_session_factory() as db2:
                t2 = await _resolve_task_by_batch(db2, batch2)
                if not t2:
                    if chat_id:
                        await send_chat_text(chat_id, f"⚠️ 批号 {batch2} 未创建任务")
                    return None
                if chat_id:
                    await send_chat_text(chat_id, await _build_progress_text(db2, batch2, t2))
            return None
        # nxt == fill → 直接发填报卡片
        async with async_session_factory() as db2:
            t2 = await _resolve_task_by_batch(db2, batch2)
            if not t2:
                if chat_id:
                    await send_chat_text(chat_id, f"⚠️ 未找到批号 {batch2} 的任务，请先建任务")
                return None
            r2 = await list_test_results(db2, t2.id)
            bio2, chem2 = _unfilled_groups(r2)
            if chat_id:
                await send_fill_card(chat_id, batch2, [("生物组", bio2), ("理化组", chem2)])
        return None

    if action_value.get("action") == "doc_query_submit":
        # 输入标准文件编号查询 → 累加进已选清单，卡片原地更新（可反复搜索多选）
        from app.core.database import async_session_factory
        from app.modules.quality.feishu.message import build_pick_doc_card

        if not _allowed_create(sender):
            return {"type": "toast", "toast": {"type": "warning", "content": _CREATE_DENY_TEXT}}
        batch = action_value.get("batch", "")
        query = (form_value.get("doc_query") or "").strip()
        async with async_session_factory() as db:
            existing = await _resolve_task_by_batch(db, batch)
            if existing:
                if chat_id:
                    await _reply_existing_task(chat_id, batch, existing)
                return {"type": "toast", "toast": {"type": "warning", "content": "该批号已存在检验任务，不允许重复创建"}}
            matched = await _resolve_docs_by_batch(db, batch)
            if not matched:
                return {"type": "toast", "toast": {"type": "warning", "content": "未找到该批号对应的标准文件"}}
            tokens = [t.strip().upper() for t in re.split(r"[、，,;；|/\s]+", query) if t.strip()]
            if not tokens:
                return {"type": "toast", "toast": {"type": "warning", "content": "请输入标准文件编号"}}
            matched_tokens: set[str] = set()
            picks = []
            for d in matched:
                hay = f"{d.file_no} {d.product_internal_code or ''} {d.version or ''}".upper()
                for t in tokens:
                    if t in hay:
                        picks.append(d)
                        matched_tokens.add(t)
            unmatched = [t for t in tokens if t not in matched_tokens]
            selected = _PENDING_DOC_SELECT.setdefault(batch, set())
            for d in picks:
                selected.add(str(d.id))
        notice = f"⚠️ 未匹配：{'、'.join(unmatched)}（未加入选择）" if unmatched else ""
        card = build_pick_doc_card(batch, [_doc_to_card_dict(d) for d in matched], selected, notice)
        return {"type": "card_updated", "card": {"type": "raw", "data": card}}

    if action_value.get("action") == "doc_clear":
        # 清空已选标准文件，卡片原地更新
        from app.core.database import async_session_factory
        from app.modules.quality.feishu.message import build_pick_doc_card

        batch = action_value.get("batch", "")
        _PENDING_DOC_SELECT.pop(batch, None)
        async with async_session_factory() as db:
            matched = await _resolve_docs_by_batch(db, batch)
        if not matched:
            return {"type": "toast", "toast": {"type": "warning", "content": "未找到该批号对应的标准文件"}}
        card = build_pick_doc_card(batch, [_doc_to_card_dict(d) for d in matched], set())
        return {"type": "card_updated", "card": {"type": "raw", "data": card}}

    if action_value.get("action") == "doc_toggle":
        # 标准文件多选点选卡片：切换勾选并原地更新卡片
        from app.core.database import async_session_factory
        from app.modules.quality.feishu.message import build_pick_doc_card

        batch = action_value.get("batch", "")
        doc_id = action_value.get("doc_id", "")
        selected = _PENDING_DOC_SELECT.setdefault(batch, set())
        if doc_id in selected:
            selected.discard(doc_id)
        else:
            selected.add(doc_id)
        async with async_session_factory() as db:
            matched = await _resolve_docs_by_batch(db, batch)
        if not matched:
            return {"type": "toast", "toast": {"type": "warning", "content": "未找到该批号对应的标准文件"}}
        card = build_pick_doc_card(batch, [_doc_to_card_dict(d) for d in matched], selected)
        return {"type": "card_updated", "card": {"type": "raw", "data": card}}

    if action_value.get("action") == "doc_confirm":
        # 确认所选标准文件 → 发建任务卡片
        from app.core.database import async_session_factory
        from app.modules.quality.feishu.message import send_create_task_card
        from app.modules.quality.repository import get_standard_document

        if not _allowed_create(sender):
            return {"type": "toast", "toast": {"type": "warning", "content": _CREATE_DENY_TEXT}}
        batch = action_value.get("batch", "")
        selected = _PENDING_DOC_SELECT.get(batch, set())
        if not selected:
            return {"type": "toast", "toast": {"type": "warning", "content": "请先勾选至少一份标准文件"}}
        docs = []
        async with async_session_factory() as db:
            for doc_id in selected:
                doc = await get_standard_document(db, uuid.UUID(doc_id))
                if doc:
                    docs.append(doc)
        if not docs:
            return {"type": "toast", "toast": {"type": "warning", "content": "所选标准文件已不存在，请重新发起建任务"}}
        if chat_id:
            await send_create_task_card(chat_id, batch, [_doc_to_card_dict(d) for d in docs])
        return None

    if action_value.get("action") == "create_task":
        from app.core.database import async_session_factory
        from app.modules.quality.repository import get_standard_document
        from app.modules.quality.schemas import TestTaskCreate
        from app.modules.quality.service import TestTaskService

        if not _allowed_create(sender):
            return {"type": "toast", "toast": {"type": "warning", "content": _CREATE_DENY_TEXT}}
        batch = action_value.get("batch", "")
        doc_ids = action_value.get("doc_ids") or []
        prod_date = (form_value.get("prod_date") or "").strip()
        spec = (form_value.get("spec") or "").strip()
        # 日期分隔符归一化：支持 2026.01.01 / 2026/01/01
        prod_date = prod_date.replace(".", "-").replace("/", "-") or ""
        report_date = (form_value.get("report_date") or "").strip()
        report_date = report_date.replace(".", "-").replace("/", "-")
        async with async_session_factory() as db:
            docs = []
            for did in doc_ids:
                doc = await get_standard_document(db, uuid.UUID(did))
                if doc:
                    docs.append(doc)
            if not docs:
                if chat_id:
                    await send_chat_text(chat_id, "⚠️ 未找到所选标准文件，请重新发起建任务")
                return None
            try:
                # 后端 create_task 会再校验批号代号与所选标准文件归属一致
                await TestTaskService.create_task(db, TestTaskCreate(
                    product_name=docs[0].product_name,
                    batch_number=batch,
                    production_date=prod_date or None,
                    specification=spec or None,
                    report_date=report_date or None,
                    standard_document_ids=[d.id for d in docs],
                ))
                await db.commit()
            except Exception as e:
                if chat_id:
                    await send_chat_text(chat_id, f"⚠️ 建任务失败：{e}")
                return None
        _PENDING_DOC_SELECT.pop(batch, None)
        if report_date and report_date == _today_str():
            note = "已下发填报卡片"
        elif report_date:
            note = f"出报日期 {report_date} 当天自动推送填报卡片"
        else:
            note = "未填出报日期，不推送（可在系统列表补录）"
        file_nos = [d.file_no for d in docs]
        if chat_id:
            await send_chat_text(
                chat_id,
                f"✅ 批号 {batch} 任务已创建（标准文件 {len(docs)} 份：{'、'.join(file_nos)}），{note}",
            )
        # 原地替换建任务表单为确认卡片：表单已移除，不可再次提交/编辑
        from app.modules.quality.feishu.message import build_task_created_card

        return {
            "type": "card_updated",
            "card": {"type": "raw", "data": build_task_created_card(batch, file_nos, note)},
        }

    if action_value.get("action") != "fill_form":
        if chat_id:
            await send_chat_text(chat_id, f"✅ 卡片回调收到，按钮值: {json.dumps(action_value, ensure_ascii=False)}")
        return

    # 表单提交：field_key 经 map 还原成结果行 ID 列表（相同 SOP 合并组）或项目名 → 校验判定 → 写库
    from app.core.database import async_session_factory
    batch = action_value.get("batch", "")
    name_map = action_value.get("map") or {}
    async with async_session_factory() as db:
        task = await _resolve_task_by_batch(db, batch)
        if not task or task.status != "in_progress":
            if chat_id:
                hint = {
                    "pending_review": "待复核中，请专员审核",
                    "completed": "已完成（已出报）",
                    "void": "已作废",
                }.get(task.status if task else "", "不存在")
                await send_chat_text(chat_id, f"⚠️ 批号 {batch} 任务{hint}，不可填报")
            return
        rows = await list_test_results(db, task.id)
        rows_by_id = {str(r.id): r for r in rows}
        updates: list[dict] = []
        results: list[str] = []
        alerts: list[str] = []  # 不合格明细（不落库，仅发提醒）
        for key, value_str in form_value.items():
            if value_str in (None, ""):
                continue
            try:
                value = float(str(value_str))
            except ValueError:
                continue
            raw = name_map.get(key, key)
            # 相同 SOP 合并组：map 值为 JSON 化的行 ID 列表，逐行按各自限度判定
            try:
                row_ids = json.loads(raw) if raw.startswith("[") else None
            except (TypeError, ValueError):
                row_ids = None
            if row_ids:
                targets = [rows_by_id[rid] for rid in row_ids if rid in rows_by_id]
            else:
                row = next(
                    (r for r in rows if TestTaskService._norm_name(r.item_name) == TestTaskService._norm_name(raw)),
                    None,
                )
                targets = [row] if row else []
            for row in targets:
                if row.judge_mode != "auto":
                    continue
                verdict = TestTaskService._judge_value(row.operator, row.limit_min, row.limit_max, value)
                if verdict is None:
                    continue
                unit = TestTaskService._unit_of(row.standard_text)
                if verdict is False:
                    # 不合格不落库：记录台账并发提醒，由人工处理
                    await TestTaskService.record_unqualified_event(
                        db, task, row, value, "manual", notify=True, origin_chat_id=chat_id,
                    )
                    limit_text = (
                        f"{row.operator or ''} {row.limit_min if row.limit_min is not None else ''}"
                        f"{row.limit_max if row.limit_max is not None else ''}{unit}"
                    ).strip()
                    alerts.append(f"{row.item_name}={value}{unit}（限度 {limit_text}）")
                    continue
                updates.append({
                    "result_id": row.id,
                    "result_text": str(value),
                    "result_value": value,
                    "is_pass": verdict,
                    "source": "manual",
                    "inspection_record_id": None,
                    "filled_by": None,
                    "filled_at": datetime.now(UTC),
                })
                results.append(f"{row.item_name}={value}{unit}（合格）")
        if updates:
            await update_test_results_fill(db, updates)
        advanced = await TestTaskService.auto_advance_pending_review(db, task.id)
        await db.commit()
    if chat_id:
        await send_chat_text(
            chat_id,
            f"✅ 批号 {batch} 表单提交已落库 {len(updates)} 项：\n" +
            ("，".join(results) if results else "无有效数值") +
            ("\n🚨 不合格未落库（已记录台账）：" + "\n".join(f"- {a}" for a in alerts) + "\n请人工处理" if alerts else "") +
            ("\n🔍 已全部填报完成，进入待复核，请专员审核" if advanced else ""),
        )
        # 卡片原地更新：已提交组的表单区替换为确认文本
        from app.modules.quality.feishu import message as feishu_msg

        card = feishu_msg.get_last_fill_card(batch)
        if card:
            submitted_group = action_value.get("group")

            async with async_session_factory() as db2:
                task2 = await _resolve_task_by_batch(db2, batch)
                rows2 = await list_test_results(db2, task2.id) if task2 else []

            bio_left, chem_left = _unfilled_groups(rows2)

            def _group_text(group_idx: int) -> str:
                if group_idx != submitted_group:
                    return "✅ 已提交"
                parts = ["✅ 已提交："]
                if results:
                    parts.append("\n".join(results))
                if alerts:
                    parts.append("🚨 不合格未落库：")
                    parts.extend(f"- {a}" for a in alerts)
                return "\n".join(parts)

            groups = [
                ("生物组", bio_left, submitted_group == 0, _group_text(0)),
                ("理化组", chem_left, submitted_group == 1, _group_text(1)),
            ]
            new_card = feishu_msg.build_fill_card(batch, groups)
            feishu_msg._LAST_FILL_CARD[batch] = new_card
            return {
                "type": "card_updated",
                "card": {"type": "raw", "data": new_card},
            }
        return {
            "type": "toast",
            "toast": {
                "type": "success",
                "content": f"已落库 {len(updates)} 项" + ("" if len(updates) else "（未识别到有效数值）"),
            },
        }
    return None


def _today_str() -> str:
    """服务器本地日期 YYYY-MM-DD（与每日推送/出报日期口径一致）。"""
    return datetime.now().strftime("%Y-%m-%d")


def _norm_sop(s: str | None) -> str:
    """SOP 号归一化（去空白+大写），相同 SOP 判定用。"""
    return re.sub(r"\s+", "", s or "").upper()


def _unfilled_groups(rows: list) -> tuple[list[dict], list[dict]]:
    """未填报的数值型项目按 生物组/理化组 分组。

    相同 SOP 号合并为一个输入（填写一次、提交时按组内每行限度分别判定自动匹配）；
    组 entry：{label, map_value}，map_value 为 JSON 化的结果行 ID 列表。
    （液相解析覆盖项与默认规则项排除。）
    """
    candidates = [
        r for r in rows
        if r.judge_mode == "auto" and r.is_pass is None
        and not any(pat in TestTaskService._norm_name(r.item_name) for pat in _LC_SHEET_PATTERNS)
        and TestTaskService._norm_name(r.item_name) not in TestTaskService._DEFAULT_FILL_RULES
    ]
    groups: dict[str, list] = {}
    order: list[str] = []
    for r in candidates:
        sop = _norm_sop(r.sop_no)
        key = f"sop:{sop}" if sop else f"item:{TestTaskService._norm_name(r.item_name)}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    def _build(rs: list) -> dict:
        names: list[str] = []
        limits: list[str] = []
        for r in rs:
            if r.item_name not in names:
                names.append(r.item_name)
            limit = (
                f"{r.operator or ''} {r.limit_min if r.limit_min is not None else ''}"
                f"{r.limit_max if r.limit_max is not None else ''}"
                f"{TestTaskService._unit_of(r.standard_text)}"
            ).strip()
            if limit not in limits:
                limits.append(limit)
        sop_label = (rs[0].sop_no or "").strip()
        label = (f"{sop_label} " if sop_label else "") + "、".join(names) + f"（{'；'.join(limits)}）"
        return {"label": label, "map_value": json.dumps([str(r.id) for r in rs])}

    out = [_build(groups[k]) for k in order]
    bio_rows = [r for r in out if any(p in r["label"] for p in _BIO_PATTERNS)]
    chem_rows = [r for r in out if r not in bio_rows]
    return bio_rows, chem_rows


async def push_task_reminder(task: QualityTestTask, rows: list) -> None:
    """向配置的群推送单个任务的提醒文本 + 分组填报卡片（无待填项时仅文本）。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text, send_fill_card

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    report_note = f"，出报日期 {task.report_date}" if task.report_date else ""
    bio_rows, chem_rows = _unfilled_groups(rows)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        await send_chat_text(
            chat_id,
            f"📋 检验任务：{task.product_name} 批号 {task.batch_number}（{task.specification or '-'}）{report_note}\n请在下方卡片填报；液相类项目上传计算表自动填入。",
        )
        if bio_rows or chem_rows:
            await send_fill_card(chat_id, task.batch_number, [("生物组", bio_rows), ("理化组", chem_rows)])


async def notify_unqualified(
    product_name: str,
    batch: str,
    item_name: str,
    value_text: str,
    limit_text: str,
    origin_chat_id: str = "",
) -> None:
    """不合格飞书提醒（@ 负责人；未配置提醒人时纯 post 文本群通知）。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_ALERT_USER_IDS,
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_alert_post

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    title = "🚨 检验不合格提醒"
    lines = [
        f"批号 {batch}（{product_name}）",
        f"项目 {item_name}：实测 {value_text}（限度 {limit_text}）",
        "请尽快人工处理",
    ]
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        if chat_id == origin_chat_id:
            continue  # 当前会话已在回执中展示明细，不重复打扰
        await send_alert_post(chat_id, QUALITY_FEISHU_ALERT_USER_IDS, title, lines)


async def notify_pending_review(task_id: str) -> None:
    """任务自动进入待复核后提醒配置群（fire-and-forget，专员进系统审核）。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.repository import get_test_task

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    task = None
    for _ in range(10):
        async with async_session_factory() as db:
            task = await get_test_task(db, uuid.UUID(task_id))
        if task:
            break
        await asyncio.sleep(0.5)
    if not task or task.status != "pending_review":
        return
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        await send_chat_text(
            chat_id,
            f"🔍 批号 {task.batch_number}（{task.product_name}）已全部填报完成，待复核，请专员进入系统审核",
        )


async def notify_task_created(task_id: str) -> None:
    """建任务/补录出报日期后的推送（fire-and-forget，不阻塞主流程）。

    推送时机规则（用户确认）：仅当任务的出报日期为「今天」才推送——
    无出报日期或出报日期在未来/过去均不在此处推送（未来出报日期由每日推送在当天触发）。
    """
    from app.core.database import async_session_factory
    from app.modules.quality.repository import get_test_task, list_test_results

    # 重试等待：调用方事务可能尚未提交，稍等片刻再查任务
    task: QualityTestTask | None = None
    for _ in range(10):
        async with async_session_factory() as db:
            task = await get_test_task(db, uuid.UUID(task_id))
        if task:
            break
        await asyncio.sleep(0.5)
    if not task or not task.report_date:
        return
    if task.report_date != _today_str():
        return
    async with async_session_factory() as db:
        rows = await list_test_results(db, task.id)
    await push_task_reminder(task, rows)
