"""菜单与卡片回调（fill_service.py 拆分）。"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.quality.feishu import event_client
from app.modules.quality.feishu.client import (
    QUALITY_FEISHU_CHAT_IDS,
)
from app.modules.quality.feishu.fill_service._commands import (
    _build_progress_text,
    _reply_existing_task,
)
from app.modules.quality.feishu.fill_service._common import (
    _CREATE_DENY_TEXT,
    _PENDING_DOC_SELECT,
    _allowed_create,
    _doc_to_card_dict,
    _known_codes,
    _limit_text,
    _resolve_docs_by_batch,
    _resolve_task_by_batch,
    _today_str,
    _unfilled_groups,
)
from app.modules.quality.feishu.message import send_chat_text
from app.modules.quality.repository import (
    list_test_results,
    update_test_results_fill,
)
from app.modules.quality.service import spawn_background

logger = logging.getLogger(__name__)

@event_client.on_event("application.bot.menu_v6")
async def handle_bot_menu_event(event: dict[str, Any]) -> None:
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
    # 标注 Any：事件 JSON 取值本为动态类型，是否 dict 已由 isinstance 就地校验
    operator_id_obj: Any = (
        operator.get("operator_id") if isinstance(operator.get("operator_id"), dict) else {}
    )
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
async def handle_card_action(event: dict[str, Any]) -> dict[str, Any] | None:
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
                filled2 = sum(1 for r in r2 if r.is_pass is not None)
                await send_fill_card(
                    chat_id, batch2, [("生物组", bio2), ("理化组", chem2)],
                    progress=f"已填 {filled2}/{len(r2)}",
                )
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
        return None

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
            return None
        rows = await list_test_results(db, task.id)
        rows_by_id = {str(r.id): r for r in rows}
        updates: list[dict[str, Any]] = []
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
                    # 不合格不落库：仅发提醒，由人工处理
                    try:
                        from app.modules.quality.feishu.fill_service import (
                            notify_unqualified,
                        )
                        spawn_background(notify_unqualified(
                            task.product_name, task.batch_number, row.item_name,
                            f"{value}{unit}", _limit_text(row, unit), origin_chat_id=chat_id,
                        ))
                    except Exception:
                        logger.exception("不合格提醒推送失败")
                    alerts.append(
                        f"{row.item_name}={value}{unit}（限度 {_limit_text(row, unit)}）"
                    )
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

        last_card = feishu_msg.get_last_fill_card(chat_id, batch)
        if last_card:
            submitted_group: int | None = action_value.get("group")

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

            groups: list[tuple[str, list[dict[str, Any]], bool, str | None]] = [
                ("生物组", bio_left, submitted_group == 0, _group_text(0)),
                ("理化组", chem_left, submitted_group == 1, _group_text(1)),
            ]
            new_card = feishu_msg.build_fill_card(batch, groups)
            feishu_msg._LAST_FILL_CARD[(chat_id, batch)] = new_card
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
