"""对话式指令处理（fill_service.py 拆分）。"""

import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime

from app.core.time import today as _app_today
from app.modules.quality import storage as quality_storage
from app.modules.quality.feishu import event_client
from app.modules.quality.feishu.fill_service._common import (
    _ARCHIVE_MODE,
    _ARCHIVE_MODE_TS,
    _BATCH_RE,
    _CREATE_DENY_TEXT,
    _LAST_BATCH,
    _LAST_IMAGE,
    _LAST_IMAGE_TS,
    _PAIR_RE,
    _PENDING_DOC_SELECT,
    _allowed,
    _allowed_create,
    _doc_to_card_dict,
    _download_image,
    _extract_command,
    _frontend_task_link,
    _known_codes,
    _limit_text,
    _norm_sop,
    _prune_stale_state,
    _resolve_docs_by_batch,
    _resolve_task_by_batch,
    _task_doc_file_nos,
    _today_str,
    _unfilled_groups,
)
from app.modules.quality.feishu.message import send_chat_text
from app.modules.quality.models import QualityTestTask
from app.modules.quality.repository import (
    list_test_results,
    update_test_results_fill,
)
from app.modules.quality.service import TestTaskService, spawn_background

logger = logging.getLogger(__name__)

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
        filled = sum(1 for r in rows if r.is_pass is not None)
        await send_fill_card(
            chat_id, batch, [("生物组", bio_rows), ("理化组", chem_rows)],
            progress=f"已填 {filled}/{len(rows)}",
        )

async def _reply_today_report(chat_id: str) -> None:
    """一句话查询「今天出报」：今日出报任务清单 + 待复核数。"""
    from app.core.database import async_session_factory
    from app.modules.quality.repository import (
        list_test_results,
        list_test_tasks,
        list_test_tasks_by_report_date,
    )

    today = _today_str()
    async with async_session_factory() as db:
        tasks = await list_test_tasks_by_report_date(db, today)
        review_items, _ = await list_test_tasks(
            db, product_name=None, status="pending_review", page=1, page_size=200
        )
        lines: list[str] = []
        for t in tasks:
            rows = await list_test_results(db, t.id)
            filled = sum(1 for r in rows if r.is_pass is not None)
            status_label = {
                "in_progress": "填报中",
                "pending_review": "待复核",
                "completed": "已完成",
            }.get(t.status, t.status)
            file_nos = await _task_doc_file_nos(db, t)
            sop_suffix = f"｜标准文件：{'、'.join(file_nos)}" if file_nos else ""
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}｜{status_label} {filled}/{len(rows)}{sop_suffix}"
            )
    text = f"📅 今日出报任务（{today}）：\n" + ("\n".join(lines) if lines else "无")
    if review_items:
        text += f"\n\n🔍 待复核：{len(review_items)} 项（可发「待复核」查看清单）"
    await send_chat_text(chat_id, text)


async def _reply_reported_tasks(chat_id: str, date_str: str) -> None:
    """「X.XX 已出报任务」：按出报日期查已完成任务清单（含标准文件与链接）。"""
    from app.core.database import async_session_factory
    from app.modules.quality.repository import list_test_tasks_by_report_date

    async with async_session_factory() as db:
        tasks = await list_test_tasks_by_report_date(db, date_str)
        lines: list[str] = []
        for t in tasks:
            if t.status != "completed":
                continue
            file_nos = await _task_doc_file_nos(db, t)
            sop_suffix = f"｜标准文件：{'、'.join(file_nos)}" if file_nos else ""
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}（{t.specification or '-'}）{sop_suffix}\n"
                f"  🔗 {_frontend_task_link(str(t.id))}"
            )
    await send_chat_text(
        chat_id,
        f"📤 {date_str} 已出报任务：" + ("\n" + "\n".join(lines) if lines else " 无"),
    )


async def _reply_pending_review(chat_id: str) -> None:
    """一句话查询「待复核」：待复核任务清单。"""
    from app.core.database import async_session_factory
    from app.modules.quality.repository import list_test_tasks

    async with async_session_factory() as db:
        items, _ = await list_test_tasks(
            db, product_name=None, status="pending_review", page=1, page_size=200
        )
        lines = [
            f"- {t.product_name} 批号 {t.batch_number}" + (
                f"（出报日期 {t.report_date}）" if t.report_date else ""
            )
            for t in items
        ]
    await send_chat_text(
        chat_id,
        "🔍 待复核任务：" + ("\n" + "\n".join(lines) if lines else " 无"),
    )


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

    # 图片消息：归档模式连拍自动归档；否则暂存并提示「附件 批号 XXX」
    msg_raw = event.get("event", {}).get("message", {})
    if msg_raw.get("message_type") == "image":
        try:
            image_key = json.loads(msg_raw.get("content", "{}")).get("image_key", "")
        except Exception:
            image_key = ""
        if not chat_id or not image_key:
            return
        _prune_stale_state()
        task_id = _ARCHIVE_MODE.get(chat_id)
        if task_id:
            image_data = await _download_image(msg_raw.get("message_id", ""), image_key)
            if image_data is None:
                await send_chat_text(chat_id, "⚠️ 图片下载失败，请重发")
                return
            from app.core.database import async_session_factory
            from app.modules.quality.repository import create_task_attachment

            async with async_session_factory() as db:
                filename = f"机器人上传_{image_key[:12]}.jpg"
                object_key = f"{task_id}/{uuid.uuid4().hex[:12]}_{filename}"
                quality_storage.upload_attachment(object_key, image_data, "image/jpeg")
                await create_task_attachment(db, {
                    "task_id": uuid.UUID(task_id), "filename": filename, "content_type": "image/jpeg",
                    "object_key": object_key, "size": len(image_data),
                    "source": "manual", "remark": "归档模式连拍自动归档",
                })
                await db.commit()
            await send_chat_text(chat_id, "📷 已归档（归档模式中，继续发图；发「结束」退出）")
        else:
            _LAST_IMAGE[chat_id] = {"message_id": msg_raw.get("message_id", ""), "file_key": image_key}
            _LAST_IMAGE_TS[chat_id] = time.monotonic()
            await send_chat_text(
                chat_id,
                "📷 已收到图片。请回复「附件 批号 XXX」归档；连拍多张可先发「归档模式 批号 XXX」",
            )
        return
    if not chat_id or not text:
        return
    if chat_type != "p2p" and not _allowed(chat_id, sender or ""):
        return
    batch_m = _BATCH_RE.search(text)
    # 省略批号沿用上次（帮助文案宣传的能力）：填报/进度/附件类指令自动套用本会话最近批号
    if not batch_m:
        kw_first = text.strip()
        last_batch = _LAST_BATCH.get(chat_id)
        if last_batch and ("填报" in kw_first or "填写" in kw_first or "进度" in kw_first or "附件" in kw_first):
            batch_m = _BATCH_RE.search(f"批号 {last_batch}")
    if not batch_m:
        kw = text.strip()
        from app.modules.quality.feishu.message import (
            send_batch_form_card,
            send_help_card,
            send_menu_card,
        )

        # 一句话查询：今日出报单（流水号+产品+批号）
        if "出报单" in kw or ("报告单" in kw and ("今天" in kw or "今日" in kw)):
            from app.core.database import async_session_factory
            from app.modules.quality.repository import list_report_records_by_date

            async with async_session_factory() as rdb:
                items = await list_report_records_by_date(rdb, _today_str())
            lines = [f"- {it.serial_no or '-'}｜{it.product_name}｜批号 {it.batch_number}" for it in items]
            await send_chat_text(
                chat_id,
                "📄 今日报告单（流水号｜产品｜批号）：" + ("\n" + "\n".join(lines) if lines else " 暂无"),
            )
            return

        # 一句话查询：X.XX 已出报任务 / 今天出报 / 待复核（无批号）
        _reported_m = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", kw) or re.search(
            r"(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)", kw
        )
        if "已出报" in kw and _reported_m:
            if len(_reported_m.groups()) == 3:
                _year, _mo, _day = (int(g) for g in _reported_m.groups())
            else:
                _year = _app_today().year
                _mo, _day = int(_reported_m.group(1)), int(_reported_m.group(2))
            await _reply_reported_tasks(chat_id, f"{_year:04d}-{_mo:02d}-{_day:02d}")
            return
        if "出报" in kw and ("今天" in kw or "今日" in kw):
            await _reply_today_report(chat_id)
            return
        if "待复核" in kw or "待审核" in kw:
            await _reply_pending_review(chat_id)
            return

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
        if kw in ("结束", "结束归档"):
            _ARCHIVE_MODE.pop(chat_id, None)
            _ARCHIVE_MODE_TS.pop(chat_id, None)
            await send_chat_text(chat_id, "✅ 归档模式已退出")
            return

        # 批号片段模糊查询：报候选批号
        if ("进度" in kw or "填报" in kw or "建任务" in kw):
            frag = re.search(r"([A-Za-z0-9-]{3,})", kw)
            if frag:
                from app.core.database import async_session_factory
                from app.modules.quality.repository import (
                    list_test_tasks_by_batch_fuzzy,
                )

                async with async_session_factory() as fdb:
                    hits = await list_test_tasks_by_batch_fuzzy(fdb, frag.group(1))
                if hits:
                    lines = "\n".join(
                        f"- {t.product_name} 批号 {t.batch_number}（{t.status}）" for t in hits
                    )
                    await send_chat_text(
                        chat_id,
                        f"🔎 批号「{frag.group(1)}」匹配：\n{lines}\n请用完整批号继续",
                    )
                else:
                    await send_chat_text(chat_id, f"🔎 未找到包含「{frag.group(1)}」的批号")
                return

        if "帮助" in kw or kw in ("指令", "命令"):
            await send_help_card(chat_id)
            return
        if "菜单" in kw or "开始" in kw or kw.lower() in ("hi", "hello", "你好"):
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
        # 「归档模式 批号 XXX」：连拍多张自动归档
        if not pairs and "归档模式" in text:
            async with async_session_factory() as db:
                task = await _resolve_task_by_batch(db, batch)
                if not task:
                    await send_chat_text(chat_id, f"⚠️ 批号 {batch} 未找到任务")
                    return
                _ARCHIVE_MODE[chat_id] = str(task.id)
                _ARCHIVE_MODE_TS[chat_id] = time.monotonic()
            _LAST_BATCH[chat_id] = batch
            await send_chat_text(
                chat_id,
                f"📸 归档模式已开启（批号 {batch}）。连发图片将自动归档为原始证据，发「结束」退出",
            )
            return

        # 「附件 批号 XXX」：把最近一张图片归档为任务原始证据附件
        if not pairs and "附件" in text:
            _prune_stale_state()
            info = _LAST_IMAGE.get(chat_id)
            if not info:
                await send_chat_text(chat_id, "⚠️ 尚未收到图片，请先发送图片，再回复「附件 批号 XXX」")
                return
            async with async_session_factory() as db:
                task = await _resolve_task_by_batch(db, batch)
                if not task:
                    await send_chat_text(chat_id, f"⚠️ 批号 {batch} 未找到任务，无法归档")
                    return
                image_data = await _download_image(info["message_id"], info["file_key"])
                if image_data is None:
                    await send_chat_text(chat_id, "⚠️ 图片下载失败，请重发图片")
                    return
                filename = f"机器人上传_{info['file_key'][:12]}.jpg"
                object_key = f"{task.id}/{uuid.uuid4().hex[:12]}_{filename}"
                quality_storage.upload_attachment(object_key, image_data, "image/jpeg")
                from app.modules.quality.repository import create_task_attachment

                await create_task_attachment(db, {
                    "task_id": task.id, "filename": filename, "content_type": "image/jpeg",
                    "object_key": object_key, "size": len(image_data),
                    "source": "manual", "remark": "机器人图片消息自动归档",
                })
                await db.commit()
            _LAST_IMAGE.pop(chat_id, None)
            _LAST_IMAGE_TS.pop(chat_id, None)
            await send_chat_text(chat_id, f"✅ 图片已归档为批号 {batch} 的原始证据附件，可在任务详情中查看")
            return

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

        # 「修正 批号 X 项目 值」：覆盖已填结果重新判定（复核人/检验员改错）
        if pairs and "修正" in text:
            async with async_session_factory() as db:
                task = await _resolve_task_by_batch(db, batch)
                if not task:
                    await send_chat_text(chat_id, f"⚠️ 批号 {batch} 未找到任务")
                    return
                if task.status not in ("in_progress", "pending_review"):
                    await send_chat_text(chat_id, f"⚠️ 批号 {batch} 状态为 {task.status}，不可修正")
                    return
                rows = await list_test_results(db, task.id)
                norm_rows = {TestTaskService._norm_name(r.item_name): r for r in rows}
                updates = []
                done: list[str] = []
                for name, value_str in pairs:
                    value = float(value_str)
                    row = norm_rows.get(TestTaskService._norm_name(name))
                    if row is None or row.judge_mode != "auto":
                        continue
                    verdict = TestTaskService._judge_value(
                        row.operator, row.limit_min, row.limit_max, value
                    )
                    if verdict is None:
                        continue
                    unit = TestTaskService._unit_of(row.standard_text)
                    if verdict is False:
                        # 不合格不落库：仅发提醒
                        from app.modules.quality.feishu.fill_service import (
                            notify_unqualified,
                        )
                        spawn_background(notify_unqualified(
                            task.product_name, task.batch_number, row.item_name,
                            f"{value}{unit}", _limit_text(row, unit), origin_chat_id=chat_id,
                        ))
                        done.append(f"{row.item_name}={value}{unit}（🚨不合格，未落库）")
                        continue
                    updates.append({
                        "result_id": row.id, "result_text": str(value), "result_value": value,
                        "is_pass": True, "source": "manual", "inspection_record_id": None,
                        "filled_by": None, "filled_at": datetime.now(UTC),
                    })
                    done.append(f"{row.item_name}={value}{unit}（合格，已修正）")
                if updates:
                    await update_test_results_fill(db, updates)
                await db.commit()
            _LAST_BATCH[chat_id] = batch
            await send_chat_text(chat_id, f"✅ 批号 {batch} 修正：\n" + ("\n".join(done) if done else "未识别到可修正的项目"))
            return

        # 「进度 批号 XXX」/「批号 X 还差什么」：进度查询（五态：未创建/待分配/填报中/待复核/已出报）
        if not pairs and ("进度" in text or "还差" in text or "待填" in text or "差什么" in text):
            t = await _resolve_task_by_batch(db, batch)
            if not t:
                await send_chat_text(
                    chat_id,
                    f"⚠️ 批号 {batch} 未创建任务（可发送「建任务 批号 {batch}」创建）",
                )
                return
            _LAST_BATCH[chat_id] = batch
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
            filled = sum(1 for r in rows if r.is_pass is not None)
            await send_fill_card(
                chat_id, batch, [("生物组", bio_rows), ("理化组", chem_rows)],
                progress=f"已填 {filled}/{len(rows)}",
            )
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
                    # 不合格不落库：仅发提醒，由人工处理
                    try:
                        from app.modules.quality.feishu.fill_service import (
                            notify_unqualified,
                        )
                        spawn_background(notify_unqualified(
                            task.product_name, task.batch_number, target.item_name,
                            f"{value}{unit}", _limit_text(target, unit), origin_chat_id=chat_id,
                        ))
                    except Exception:
                        logger.exception("不合格提醒推送失败")
                    alerts.append(
                        f"{target.item_name}={value}{unit}（限度 {_limit_text(target, unit)}）"
                    )
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
        lines.append("🚨 不合格未落库：")
        lines.extend(f"- {a}" for a in alerts)
        lines.append("请人工处理")
    await send_chat_text(chat_id, "\n".join(lines))
