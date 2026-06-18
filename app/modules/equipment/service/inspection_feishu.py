"""巡检飞书交互服务 — 引导式巡检流程。

支持两种巡检模式：
- 线路巡检：按路线 → 地点 → 设备顺序逐台引导
- 设备巡检：按设备列表逐台引导

命令系统：
  开始   — 创建会话，进入引导模式
  提交   — 确认 AI 分析结果并提交
  跳过   — 跳过当前设备
  进度   — 查看整体进度
  继续   — 前往下一台设备
  取消   — 取消当前待确认结果
  帮助   — 查看命令列表
  修改 X  — 用自然语言修改检查项结果

也支持直接发送照片进入 AI 分析流程，或直接发送文字描述手动提交。
"""

import base64
import json
import logging
import os
import uuid
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.core.exceptions import AppException
from app.modules.equipment.feishu.notification import send_user_card
from app.modules.equipment.models.inspection import InspectionPhoto, InspectionTask
from app.modules.equipment.service.inspection_session import (
    SessionState,
    advance_to_next_equipment,
    clear_session,
    get_current_equipment,
    get_progress,
    get_session,
    mark_equipment_completed,
    mark_equipment_skipped,
    save_session,
    set_pending_results,
)

logger = logging.getLogger(__name__)

_UPLOAD_DIR = "uploads/inspection"
os.makedirs(_UPLOAD_DIR, exist_ok=True)

# 命令关键词映射
_START_COMMANDS = {"开始", "开始巡检", "start"}
_SUBMIT_COMMANDS = {"提交", "确认", "确认提交", "submit", "ok", "好的"}
_SKIP_COMMANDS = {"跳过", "skip", "pass"}
_PROGRESS_COMMANDS = {"进度", "状态", "progress", "status"}
_CONTINUE_COMMANDS = {"继续", "下一台", "下一个", "next", "continue"}
_CANCEL_COMMANDS = {"取消", "放弃", "取消提交", "cancel", "abort"}
_EXIT_COMMANDS = {"退出", "返回", "exit", "quit", "back"}
_HELP_COMMANDS = {"帮助", "help", "?", "？"}


# ═══════════ 主入口 ═══════════


async def process_feishu_image(
    *,
    user_id: str,
    open_id: str,
    message_id: str,
    image_key: str,
    chat_id: str,
    chat_type: str,
) -> None:
    """处理从飞书收到的巡检照片。

    新流程：查用户 → 查活跃任务 → 确定当前设备 → 下载 → AI分析 → 发确认卡片 → 存会话。
    如果用户没有活跃会话，自动创建引导会话并定位到第一个未提交设备。
    """
    if not user_id:
        logger.warning("消息缺少 sender user_id，忽略")
        return

    async with async_session_factory() as db:
        # 1. 查找用户
        user = await _find_user_by_user_id(db, user_id)
        if not user:
            await _reply_text(open_id, "未找到您的系统账号，请先在系统中完成飞书绑定。")
            return

        # 2. 获取或创建会话 — 优先使用已有会话的任务，避免跳到其他任务
        session = await get_session(open_id)
        if session:
            # 已有会话 → 使用会话中的任务
            task_id = uuid.UUID(session["task_id"])
            result = await db.execute(
                select(InspectionTask).where(
                    InspectionTask.id == task_id,
                    InspectionTask.is_deleted == False,  # noqa: E712
                )
            )
            task = result.scalar_one_or_none()
            if not task or task.status != "执行中":
                await clear_session(open_id)
                await _reply_text(open_id, "当前会话中的任务已结束，请回复「开始」重新选择。")
                return
        else:
            # 无会话 → 查找最新活跃任务，自动创建会话
            task = await _find_active_task(db, user.id)
            if not task:
                await _reply_text(open_id, "当前没有执行中的巡检任务。\n请先在系统中开始巡检。")
                return
            session = await _auto_create_session(db, task, open_id)
            if session is None:
                await _reply_text(open_id, "无法确定巡检设备，请回复「开始」手动进入巡检。")
                return

        # 4. 确定当前设备
        cur_eq = get_current_equipment(session)
        if cur_eq is None:
            await _reply_text(open_id, "所有设备均已处理完毕。\n回复「进度」查看巡检完成情况。")
            return

        equipment_id = uuid.UUID(cur_eq["equipment_id"])
        equipment_name = cur_eq.get("equipment_name", "未知设备")

        # 5. 下载图片
        image_bytes, mime_type = await _download_image(message_id, image_key)
        if not image_bytes:
            await _reply_text(open_id, "图片下载失败，请重新发送。")
            return

        # 6. 保存照片
        photo = await _save_photo(db, task.id, equipment_id, image_bytes)
        logger.info("巡检照片已保存: task=%s, photo=%s", task.task_no, photo.id)

        # 7. AI 分析
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            from app.modules.equipment.service.ai.service import (
                analyze_inspection_photo,
            )

            results = await analyze_inspection_photo(
                db=db,
                task_id=task.id,
                equipment_id=equipment_id,
                image_base64=image_b64,
                image_mime_type=mime_type or "image/jpeg",
            )
        except Exception as e:
            logger.exception("AI 分析失败: task=%s", task.task_no)
            await _reply_text(
                open_id, f"AI 分析失败：{e}\n照片已保存，请手动描述检查结果。"
            )
            return

        # 8. 保存会话并进入确认状态，发送结果卡片
        await set_pending_results(open_id, results)
        await _send_confirm_card(open_id, task, results, equipment_name)


async def process_feishu_text(
    open_id: str, text: str, user_id: str = ""
) -> None:
    """处理飞书文本消息 — 命令路由 + 手动提交解析。

    优先级：命令 > 修改（确认状态）> 手动提交（引导状态）

    Args:
        open_id: 飞书应用级用户 ID
        text: 用户发送的文本
        user_id: 飞书租户级用户 ID（可选，用于用户查找）
    """
    text = text.strip()
    if not text:
        return

    # ── 0. 选择状态：数字输入选择任务/工单 ──
    from app.modules.equipment.service.inspection_session import (
        clear_selection,
        get_selection,
    )

    selection = await get_selection(open_id)
    if selection:
        if text in _CANCEL_COMMANDS:
            await clear_selection(open_id)
            await _reply_text(open_id, "已取消选择。")
            return
        # 尝试匹配纯数字
        try:
            num = int(text)
            options = selection.get("options", [])
            opt = next((o for o in options if o.get("index") == num), None)
            if opt:
                await clear_selection(open_id)
                if selection.get("select_type") == "inspection":
                    await _handle_inspection_selection(open_id, opt)
                elif selection.get("select_type") == "work_order":
                    await _handle_work_order_selection(open_id, opt)
                return
        except ValueError:
            pass
        await _reply_text(open_id, "请输入有效数字选择，或回复「取消」放弃。")
        return

    # ── 1. 全局命令（无需会话也生效）──
    if text in _HELP_COMMANDS:
        await _cmd_help(open_id)
        return

    session = await get_session(open_id)

    # ── 1.5. 退出命令（需要会话）──
    if text in _EXIT_COMMANDS:
        if session:
            task_no = session.get("task_no", "")
            await clear_session(open_id)
            await _reply_text(
                open_id,
                f"已退出巡检任务 **{task_no}**。\n"
                "回复「**开始**」重新选择巡检任务。\n"
                "回复「**工单**」查看工单。",
            )
        else:
            await _reply_text(
                open_id,
                "当前没有进行中的巡检任务。\n"
                "回复「**开始**」选择巡检任务。\n"
                "回复「**工单**」查看工单。",
            )
        return

    # ── 2. 开始命令（随时可调用）──
    if text in _START_COMMANDS:
        await _cmd_start(open_id, user_id)
        return

    # ── 3. 有会话时的命令 ──
    if session:
        state = session.get("state", "")

        # 确认状态下的命令
        if state == SessionState.CONFIRMING:
            if text in _SUBMIT_COMMANDS:
                await _cmd_submit(open_id, session)
            elif text in _CANCEL_COMMANDS:
                await _cmd_cancel(open_id, session)
            elif text.startswith("修改") or text.startswith("修正"):
                await _cmd_modify(open_id, session, text)
            elif text in _PROGRESS_COMMANDS:
                await _cmd_progress(open_id, session)
            elif text in _HELP_COMMANDS:
                await _cmd_help(open_id)
            else:
                # 确认状态下的自然语言视为修改
                await _cmd_modify(open_id, session, text)
            return

        # 引导状态下的命令
        if state == SessionState.GUIDING:
            if text in _SKIP_COMMANDS:
                await _cmd_skip(open_id, session)
            elif text in _PROGRESS_COMMANDS:
                await _cmd_progress(open_id, session)
            elif text in _CONTINUE_COMMANDS:
                await _cmd_continue(open_id, session)
            elif text in _SUBMIT_COMMANDS:
                await _reply_text(open_id, "当前没有待确认的检查结果。\n请先发送照片或文字描述检查结果。")
            else:
                # 尝试作为手动提交解析
                await _handle_manual_submit(open_id, session, text)
            return

        # 其他状态
        if text in _PROGRESS_COMMANDS:
            await _cmd_progress(open_id, session)
        else:
            await _reply_text(open_id, "当前状态不支持此操作，请回复「帮助」查看可用命令。")
        return

    # ── 4. 无会话时的提示 ──
    await _reply_text(
        open_id,
        "当前没有活跃的巡检任务。\n\n"
        "**快速开始：**\n"
        "1. 在系统中开始一个巡检任务\n"
        "2. 收到通知卡片后，回复「**开始**」进入引导模式\n\n"
        "或者直接发送巡检照片，系统会自动匹配任务。\n"
        "回复「**帮助**」查看完整命令列表。",
    )


# ═══════════ 命令实现 ═══════════


async def _cmd_start(open_id: str, user_id: str = "") -> None:
    """创建巡检引导会话，发送第一台设备卡片。

    多个活跃任务时展示选择列表，1个时自动选中。
    重要：DB 操作和 Redis/HTTP 操作严格分离，避免 greenlet 上下文冲突。
    """
    # === Phase 1: 只做 DB 和 Redis，收集数据 ===
    active_task_ids: list[uuid.UUID] = []
    active_task_infos: list[dict] = []
    session_exists = False
    session_task_id: str | None = None

    session = await get_session(open_id)
    if session:
        session_exists = True
        session_task_id = session["task_id"]

    async with async_session_factory() as db:
        if session_exists and session_task_id:
            task_id = uuid.UUID(session_task_id)
            task = await _get_full_task(db, task_id)
            equipment_order = await _build_equipment_order(db, task)
            completed, skipped = await _get_processed_equipment_ids(db, task_id)
            first_idx = 0
            for i, eq in enumerate(equipment_order):
                if eq["equipment_id"] not in completed and eq["equipment_id"] not in skipped:
                    first_idx = i
                    break
            await save_session(
                open_id=open_id, task_id=str(task_id),
                plan_type=task.plan_type or "设备巡检",
                task_no=task.task_no,
                route_name=task.route.name if task.route else "",
                equipment_order=equipment_order,
                completed_equipment_ids=list(completed),
                skipped_equipment_ids=list(skipped),
                current_equipment_index=first_idx,
                state=SessionState.GUIDING,
            )
            return

        db_user = await _resolve_user_for_text(db, open_id, user_id)
        if not db_user:
            await _reply_text(open_id, "未找到您的系统账号，请先在系统中完成飞书绑定。")
            return

        result = await db.execute(
            select(InspectionTask)
            .options(
                selectinload(InspectionTask.route),
                selectinload(InspectionTask.equipment),
            )
            .where(
                InspectionTask.assigned_to == db_user.id,
                InspectionTask.status == "执行中",
                InspectionTask.is_deleted == False,  # noqa: E712
            )
            .order_by(InspectionTask.started_at.desc())
        )
        active_tasks = result.scalars().all()

        if not active_tasks:
            await _reply_text(
                open_id,
                "当前没有执行中的巡检任务。\n请先在系统中为您分配巡检任务并点击「开始」。",
            )
            return

        if len(active_tasks) == 1:
            active_task_ids = [active_tasks[0].id]
        else:
            for i, t in enumerate(active_tasks, 1):
                eq_count = await _count_task_equipment(db, t)
                target = (
                    t.route.name if t.route
                    else (t.equipment.name if t.equipment else f"{eq_count}台设备")
                )
                active_task_infos.append({
                    "index": i,
                    "task_id": str(t.id),
                    "task_no": t.task_no,
                    "plan_type": t.plan_type or "设备巡检",
                    "target": target,
                    "equipment_count": eq_count,
                })

    # === Phase 2: 纯 Redis/HTTP 操作（不持有 DB session）===
    if session_exists:
        # 续接会话 → 发引导卡片
        session = await get_session(open_id)
        if session:
            await _send_guide_card(open_id, session)
        return

    if active_task_ids:
        # 单个任务 → 自动选中
        await _select_and_guide(open_id, active_task_ids[0])
        return

    # 多个任务 → 展示选择列表
    lines = [
        f"**📋 您有 {len(active_task_infos)} 个执行中的巡检任务：**",
        "",
    ]
    options: list[dict] = []
    for info in active_task_infos:
        plan_label = "🔵" if info["plan_type"] == "线路巡检" else "🟠"
        lines.append(
            f"**{info['index']}.** {plan_label} {info['task_no']} · {info['plan_type']}\n"
            f"   ↳ {info['target']} · {info['equipment_count']}台设备"
        )
        options.append({
            "index": info["index"],
            "task_id": info["task_id"],
            "task_no": info["task_no"],
        })

    lines.append("")
    lines.append("回复数字（**1** / **2** / **3**）选择要执行的巡检任务。")
    lines.append("回复「取消」放弃选择。")

    from app.modules.equipment.service.inspection_session import save_selection

    await save_selection(open_id, select_type="inspection", options=options)
    await send_user_card(
        open_id=open_id,
        title="📋 选择巡检任务",
        content="\n".join(lines),
        receive_id_type="open_id",
    )


async def _select_and_guide(open_id: str, task_id: uuid.UUID) -> None:
    """选中任务 → 构建设备顺序 → 保存会话 → 发引导卡片。"""
    # Phase 1: DB 操作
    async with async_session_factory() as db:
        task = await _get_full_task(db, task_id)
        equipment_order = await _build_equipment_order(db, task)
        if not equipment_order:
            await _reply_text(open_id, "该任务没有关联设备，请在系统中配置。")
            return

        completed, skipped = await _get_processed_equipment_ids(db, task_id)

        first_idx = 0
        for i, eq in enumerate(equipment_order):
            if eq["equipment_id"] not in completed and eq["equipment_id"] not in skipped:
                first_idx = i
                break

        task_no = task.task_no
        plan_type = task.plan_type or "设备巡检"
        route_name = task.route.name if task.route else ""

    # Phase 2: Redis + 卡片（不持有 DB session）
    await save_session(
        open_id=open_id,
        task_id=str(task_id),
        plan_type=plan_type,
        task_no=task_no,
        route_name=route_name,
        equipment_order=equipment_order,
        completed_equipment_ids=list(completed),
        skipped_equipment_ids=list(skipped),
        current_equipment_index=first_idx,
        state=SessionState.GUIDING,
    )

    session = await get_session(open_id)
    if session:
        await _send_guide_card(open_id, session)


async def _count_task_equipment(db: AsyncSession, task: InspectionTask) -> int:
    """统计任务的设备数量 — 用查询计数避免 lazy load。"""
    if task.equipment_ids:
        return len(task.equipment_ids)
    if task.equipment_id:
        return 1
    if task.route_id:
        from app.modules.equipment.models.inspection_route_location import (
            RouteLocation,
            RouteLocationEquipment,
        )

        # 直接查询计数，不通过 relationship 访问
        loc_result = await db.execute(
            select(RouteLocation.id).where(
                RouteLocation.route_id == task.route_id,
                RouteLocation.is_deleted == False,  # noqa: E712
            )
        )
        loc_ids = [row for row in loc_result.scalars().all()]
        if not loc_ids:
            return 0
        eq_result = await db.execute(
            select(func.count()).where(
                RouteLocationEquipment.route_location_id.in_(loc_ids),
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
            )
        )
        return eq_result.scalar_one()
    return 0


async def _cmd_submit(open_id: str, session: dict) -> None:
    """提交当前设备的待确认结果。"""
    results = session.get("pending_results")
    if not results:
        await _reply_text(open_id, "当前没有待确认的检查结果。")
        return

    task_id = session["task_id"]
    cur_eq = get_current_equipment(session)
    if not cur_eq:
        await _reply_text(open_id, "找不到当前设备信息，请回复「开始」重新进入。")
        return

    equipment_id = cur_eq["equipment_id"]
    equipment_name = cur_eq.get("equipment_name", "未知设备")
    task_no = session.get("task_no", "")

    try:
        # Phase 1: DB 操作
        completed: Any = None
        all_done = False
        records = [
            {
                "template_item_id": r["template_item_id"],
                "result": r["result"],
                "actual_value": r.get("actual_value"),
                "remark": r.get("remark"),
            }
            for r in results
        ]

        async with async_session_factory() as db:
            from app.modules.equipment.service.inspection import (
                complete_task,
                submit_equipment_check,
            )

            await submit_equipment_check(
                db=db,
                task_id=uuid.UUID(task_id),
                equipment_id=uuid.UUID(equipment_id),
                records=records,
            )
            await db.commit()

        # Phase 2: Redis + 卡片（不持有 DB session）
        await mark_equipment_completed(open_id, equipment_id)
        session_after = await advance_to_next_equipment(open_id)
        if session_after is None:
            all_done = True
            plan_type = session.get("plan_type", "")
            async with async_session_factory() as db:
                if plan_type == "线路巡检":
                    from app.modules.equipment.service.inspection import (
                        submit_route_check,
                    )
                    from app.modules.equipment import repository as repo
                    records_db = await repo.get_records_by_task(
                        db, uuid.UUID(task_id),
                    )
                    has_abnormal = any(r.result == "异常" for r in records_db)
                    completed_obj = await submit_route_check(
                        db, uuid.UUID(task_id),
                        overall_result="异常" if has_abnormal else "正常",
                    )
                else:
                    completed_obj = await complete_task(db, uuid.UUID(task_id))
                await db.commit()
            completed = completed_obj
            await clear_session(open_id)

        if all_done:
            overall = completed.overall_result if completed else "正常"
            icon = "⚠️" if overall == "异常" else "✅"
            abnormal = [r for r in results if r["result"] == "异常"]
            lines = [
                f"**任务：**{task_no}",
                f"**设备：**{equipment_name}",
                f"**提交项数：**{len(records)} 项",
                "",
                f"**{icon} 全部设备巡检完成！**",
                f"总体结果：{overall}",
            ]
            if abnormal:
                lines.append("")
                lines.append("**异常项已自动生成工单：**")
                for item in abnormal:
                    v = f" → {item['actual_value']}" if item.get("actual_value") else ""
                    lines.append(f"⚠️ {item['item_name']}{v}")
            await send_user_card(
                open_id=open_id,
                title=f"{icon} 巡检任务已完成 - {task_no}",
                content="\n".join(lines),
                receive_id_type="open_id",
            )
        else:
            progress = get_progress(session_after) if session_after else {}
            next_eq = get_current_equipment(session_after) if session_after else None
            next_name = next_eq["equipment_name"] if next_eq else ""

            lines = [
                f"**✅ {equipment_name} — 已提交 {len(records)} 项**",
                "",
                f"📊 进度：{progress.get('done', 0)}/{progress.get('total', 0)} 已完成"
                + (f"（{progress.get('skipped', 0)} 跳过）" if progress.get('skipped', 0) > 0 else ""),
            ]
            if next_eq:
                lines.append(f"⏭️ 下一台：**{next_name}**")
                lines.append("")
                lines.append("回复「**继续**」开始检查下一台设备。")

            await send_user_card(
                open_id=open_id,
                title=f"✅ 检查完成 - {equipment_name}",
                content="\n".join(lines),
                receive_id_type="open_id",
            )
    except AppException as e:
        await _reply_text(open_id, f"提交失败：{e.message}")
    except Exception:
        logger.exception("提交异常: open_id=%s, task=%s", open_id, task_no)
        await _reply_text(open_id, "提交时发生异常，请稍后重试。")


async def _cmd_skip(open_id: str, session: dict) -> None:
    """跳过当前设备。"""
    cur_eq = get_current_equipment(session)
    if not cur_eq:
        await _reply_text(open_id, "找不到当前设备。")
        return

    equipment_id = cur_eq["equipment_id"]
    equipment_name = cur_eq.get("equipment_name", "未知设备")
    task_id = session["task_id"]
    task_no = session.get("task_no", "")

    try:
        # Phase 1: DB 操作
        all_done = False
        completed: Any = None

        async with async_session_factory() as db:
            from app.modules.equipment.service.inspection import (
                complete_task,
                skip_equipment_check,
            )

            await skip_equipment_check(
                db=db,
                task_id=uuid.UUID(task_id),
                equipment_id=uuid.UUID(equipment_id),
                reason="现场无法检查",
            )
            await db.commit()

        # Phase 2: Redis + 卡片（不持有 DB session）
        await mark_equipment_skipped(open_id, equipment_id)

        session_after = await advance_to_next_equipment(open_id)
        if session_after is None:
            all_done = True
            plan_type = session.get("plan_type", "")
            async with async_session_factory() as db:
                if plan_type == "线路巡检":
                    from app.modules.equipment.service.inspection import (
                        submit_route_check,
                    )
                    from app.modules.equipment import repository as repo
                    records_db = await repo.get_records_by_task(
                        db, uuid.UUID(task_id),
                    )
                    has_abnormal = any(r.result == "异常" for r in records_db)
                    completed_obj = await submit_route_check(
                        db, uuid.UUID(task_id),
                        overall_result="异常" if has_abnormal else "正常",
                    )
                else:
                    completed_obj = await complete_task(db, uuid.UUID(task_id))
                await db.commit()
            completed = completed_obj
            await clear_session(open_id)

        if all_done:
            overall = completed.overall_result if completed else "正常"
            await send_user_card(
                open_id=open_id,
                title=f"✅ 巡检任务已完成 - {task_no}",
                content=(
                    f"**{equipment_name}** 已跳过。\n\n"
                    f"所有设备已处理完毕，任务已完成。\n"
                    f"总体结果：{overall}"
                ),
                receive_id_type="open_id",
            )
        else:
            progress = get_progress(session_after) if session_after else {}
            next_eq = get_current_equipment(session_after) if session_after else None
            lines = [
                f"**⏭️ 已跳过：{equipment_name}**",
                "",
                f"📊 进度：{progress.get('done', 0)}/{progress.get('total', 0)} 已完成"
                + (f"（{progress.get('skipped', 0)} 跳过）" if progress.get('skipped', 0) > 0 else ""),
            ]
            if next_eq:
                lines.append(f"⏭️ 下一台：**{next_eq['equipment_name']}**")
                lines.append("")
                lines.append("回复「**继续**」开始检查下一台设备。")
            await send_user_card(
                open_id=open_id,
                title=f"⏭️ 跳过 - {equipment_name}",
                content="\n".join(lines),
                receive_id_type="open_id",
            )
    except AppException as e:
        await _reply_text(open_id, f"跳过失败：{e.message}")
    except Exception:
        logger.exception("跳过异常: open_id=%s", open_id)
        await _reply_text(open_id, "跳过时发生异常，请稍后重试。")


async def _cmd_progress(open_id: str, session: dict) -> None:
    """查看当前巡检进度。"""
    progress = get_progress(session)
    task_no = session.get("task_no", "")
    plan_type = session.get("plan_type", "")
    route_name = session.get("route_name", "")
    cur_eq = get_current_equipment(session)

    emoji = {"completed": "✅", "skipped": "⏭️", "pending": "⬜"}

    lines = [
        f"**📊 巡检进度 · {task_no}**",
        "",
    ]
    if plan_type == "线路巡检" and route_name:
        lines.append(f"**路线：**{route_name}")
    lines.append(f"**类型：**{plan_type}")
    lines.append("")

    # 按地点分组展示
    for loc in progress["locations"]:
        loc_name = loc["location_name"]
        if loc_name:
            # 检查该地点是否有当前设备
            has_current = any(e["equipment_id"] == (cur_eq["equipment_id"] if cur_eq else "")
                              and e["status"] == "pending" for e in loc["equipment"])
            if has_current:
                lines.append(f"**🔍 {loc_name} ← 当前位置**")
            else:
                lines.append(f"**{loc_name}**")
        for eq in loc["equipment"]:
            icon = emoji.get(eq["status"], "⬜")
            detail = eq["equipment_no"] or ""
            detail_str = f" ({detail})" if detail else ""
            if eq["status"] == "pending" and cur_eq and eq["equipment_id"] == cur_eq["equipment_id"]:
                lines.append(f"  🔍 {icon} **{eq['equipment_name']}**{detail_str} ← 当前")
            else:
                lines.append(f"  {icon} {eq['equipment_name']}{detail_str}")

    lines.append("")
    lines.append(
        f"已完成：{progress['done']}/{progress['total']}"
        + (f" · 跳过：{progress['skipped']}" if progress['skipped'] > 0 else "")
        + (f" · 待检：{progress['remaining']}" if progress['remaining'] > 0 else "")
    )

    if cur_eq and progress["remaining"] > 0:
        lines.append("")
        lines.append("回复「**继续**」开始检查当前设备。")

    await send_user_card(
        open_id=open_id,
        title=f"📊 巡检进度 - {task_no}",
        content="\n".join(lines),
        receive_id_type="open_id",
    )


async def _cmd_continue(open_id: str, session: dict) -> None:
    """继续巡检 — 发送当前设备引导卡片。"""
    cur_eq = get_current_equipment(session)
    if cur_eq is None:
        await _reply_text(open_id, "所有设备均已处理完毕！\n回复「进度」查看巡检完成情况。")
        return

    await _send_guide_card(open_id, session)


async def _cmd_cancel(open_id: str, session: dict) -> None:
    """取消当前待确认结果，回到引导状态。"""
    from app.modules.equipment.service.inspection_session import update_session

    await update_session(
        open_id,
        pending_results=None,
        state=SessionState.GUIDING,
    )

    cur_eq = get_current_equipment(session)
    eq_name = cur_eq["equipment_name"] if cur_eq else "当前设备"

    await _reply_text(
        open_id,
        f"已取消 **{eq_name}** 的待确认结果。\n可重新发送照片或文字描述检查结果。",
    )


async def _cmd_modify(open_id: str, session: dict, user_text: str) -> None:
    """处理用户对巡检结果的修改（使用 AI 解析）。"""
    current_results = session.get("pending_results")
    if not current_results:
        await _reply_text(open_id, "当前没有待修改的检查结果。\n请先发送巡检照片。")
        return

    # 使用 AI 解析修改
    from app.modules.equipment.service.ai.client import AIAnalysisError, QwenClient
    from app.modules.equipment.service.ai.prompts import (
        CORRECTION_SYSTEM_PROMPT,
        build_correction_user_prompt,
    )

    client = QwenClient()
    try:
        user_prompt = build_correction_user_prompt(current_results, user_text)
        raw_response = await client.parse_correction(
            system_prompt=CORRECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except AIAnalysisError as e:
        logger.warning("AI 修正解析失败: open_id=%s, error=%s", open_id, e)
        await _reply_text(
            open_id,
            f"无法理解您的修改：{e.message}\n请换一种方式描述，或发送新照片重新分析。",
        )
        return
    except httpx.RequestError as e:
        logger.exception("AI 修正请求失败: open_id=%s", open_id)
        await _reply_text(open_id, f"AI 服务暂时不可用：{e}\n请稍后再试。")
        return
    finally:
        await client.close()

    # 解析 AI 响应
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        logger.warning("AI 修正返回非 JSON: open_id=%s", open_id)
        await _reply_text(open_id, "无法理解您的修改，请换一种方式描述。")
        return

    ai_items = parsed.get("items", [])
    if not isinstance(ai_items, list) or len(ai_items) == 0:
        await _reply_text(open_id, "无法理解您的修改，请换一种方式描述。")
        return

    # 按 template_item_id 映射
    ai_map: dict[str, dict] = {}
    for item in ai_items:
        tid = item.get("template_item_id")
        if tid:
            ai_map[tid] = item

    updated_results: list[dict] = []
    for r in current_results:
        tid = r["template_item_id"]
        if tid in ai_map:
            ai_item = ai_map[tid]
            result_value = ai_item.get("result", r["result"])
            if result_value not in ("正常", "异常", "跳过"):
                result_value = r["result"]
            updated_results.append({
                "template_item_id": tid,
                "item_name": r["item_name"],
                "expected_result": r.get("expected_result"),
                "result": result_value,
                "actual_value": ai_item.get("actual_value") or None,
                "remark": ai_item.get("remark") or None,
            })
        else:
            updated_results.append(r)

    # 更新会话
    from app.modules.equipment.service.inspection_session import update_session

    await update_session(open_id, pending_results=updated_results)

    # 发送修改后的结果卡片
    cur_eq = get_current_equipment(session)
    equipment_name = cur_eq.get("equipment_name", "未知设备") if cur_eq else "未知设备"
    task_no = session.get("task_no", "")

    normal = sum(1 for r in updated_results if r["result"] == "正常")
    abnormal = sum(1 for r in updated_results if r["result"] == "异常")
    skip = sum(1 for r in updated_results if r["result"] == "跳过")

    lines = [
        f"**任务：**{task_no}",
        f"**设备：**{equipment_name}",
        "",
        "---",
        "**✏️ 修改后结果：**",
        "",
    ]
    for r in updated_results:
        icon = {"正常": "✅", "异常": "⚠️", "跳过": "⏭️"}.get(r["result"], "⬜")
        v = f" → {r['actual_value']}" if r.get("actual_value") else ""
        rm = f"（{r['remark']}）" if r.get("remark") else ""
        lines.append(f"{icon} **{r['item_name']}**：{r['result']}{v}{rm}")

    lines.append("")
    lines.append("---")
    lines.append(f"汇总：✅ 正常 {normal} | ⚠️ 异常 {abnormal} | ⏭️ 跳过 {skip}")
    lines.append("")
    lines.append("📌 回复「**提交**」保存 · 继续发送文字修改 · 回复「**取消**」放弃")

    await send_user_card(
        open_id=open_id,
        title=f"✏️ 修改后 - {equipment_name}",
        content="\n".join(lines),
        receive_id_type="open_id",
    )


async def _cmd_help(open_id: str) -> None:
    """发送帮助信息。"""
    await send_user_card(
        open_id=open_id,
        title="🤖 巡检助手 · 命令指南",
        content=(
            "**📸 拍照巡检**\n"
            "直接发送设备到位照片，AI 自动识别检查项。\n\n"
            "**📝 手动提交**\n"
            "直接文字描述检查结果，AI 自动解析。\n"
            "例如：「第1项正常 66.5℃，第2项异常 0.35MPa 压力偏低」\n\n"
            "**⌨️ 文字命令**\n"
            "- **开始** — 进入巡检引导模式\n"
            "- **提交** — 确认并提交当前结果\n"
            "- **跳过** — 跳过当前设备\n"
            "- **进度** — 查看整体巡检进度\n"
            "- **继续** — 开始检查下一台设备\n"
            "- **取消** — 放弃当前待确认结果\n"
            "- **修改** — 发送文字描述修改检查项\n"
            "- **帮助** — 查看此列表\n\n"
            "**💡 提示**\n"
            "- 线路巡检按地点顺序逐台引导\n"
            "- 每台设备拍照后 AI 自动分析\n"
            "- 异常项请填写实际值和备注\n"
            "- 设备无法检查时可回复「跳过」"
        ),
        receive_id_type="open_id",
    )


# ═══════════ 手动提交 ═══════════


async def _handle_manual_submit(open_id: str, session: dict, user_text: str) -> None:
    """处理手动文字提交 — 使用 AI 解析非结构化文本。"""
    cur_eq = get_current_equipment(session)
    if not cur_eq:
        await _reply_text(open_id, "找不到当前设备，请回复「开始」重新进入。")
        return

    equipment_id = cur_eq["equipment_id"]
    equipment_name = cur_eq.get("equipment_name", "未知设备")
    task_id = session["task_id"]

    await _reply_text(open_id, "🤖 正在解析您提交的检查结果...")

    try:
        async with async_session_factory() as db:
            from app.modules.equipment.service.ai.service import (
                parse_manual_submission,
            )

            results = await parse_manual_submission(
                db=db,
                task_id=uuid.UUID(task_id),
                equipment_id=uuid.UUID(equipment_id),
                user_text=user_text,
                equipment_name=equipment_name,
            )

            if not results:
                await _reply_text(open_id, "AI 未能从文本中解析出检查结果，请换一种方式描述。")
                return

            # 保存结果并进入确认状态
            await set_pending_results(open_id, results)

            # 发送确认卡片
            task_no = session.get("task_no", "")
            await _send_confirm_card_from_results(open_id, task_no, equipment_name, results)

            await _reply_text(
                open_id,
                "📌 回复「**提交**」保存结果 · 回复「**修改**」调整 · 回复「**取消**」放弃",
            )
    except AppException as e:
        await _reply_text(open_id, f"提交失败：{e.message}")
    except Exception:
        logger.exception("手动提交解析异常: open_id=%s", open_id)
        await _reply_text(open_id, "AI 解析失败，请换一种方式描述或直接发送照片。")


# ═══════════ 卡片发送 ═══════════


async def _send_guide_card(open_id: str, session: dict) -> None:
    """发送当前设备的引导卡片（含检查项、地点信息）。"""
    cur_eq = get_current_equipment(session)
    if not cur_eq:
        return

    task_id = session["task_id"]
    plan_type = session.get("plan_type", "")
    equipment_name = cur_eq.get("equipment_name", "未知设备")
    equipment_no = cur_eq.get("equipment_no", "")
    location_name = cur_eq.get("location_name", "")
    progress = get_progress(session)
    current_idx = session.get("current_equipment_index", 0)

    # Phase 1: DB 获取检查项
    items: list[dict] = []
    async with async_session_factory() as db:
        from app.modules.equipment.service.ai.service import (
            get_inspection_items_for_session,
        )
        items = await get_inspection_items_for_session(
            db, uuid.UUID(task_id), uuid.UUID(cur_eq["equipment_id"])
        )

    # Phase 2: 构建卡片并发送（不持有 DB session）
    lines = []
    if plan_type == "线路巡检" and location_name:
        loc_set: set[str] = set()
        for eq in session.get("equipment_order", []):
            ln = eq.get("location_name", "")
            if ln:
                loc_set.add(ln)
        total_locs = len(loc_set) if loc_set else 1
        loc_idx = sum(1 for ln in sorted(loc_set) if ln <= location_name)
        lines.append(f"**📍 第 {loc_idx}/{total_locs} 站 · {location_name}**")

    lines += [
        f"**🔧 设备 {current_idx + 1}/{progress['total']}：{equipment_name}**",
        "",
    ]

    if equipment_no:
        lines.append(f"设备编号：{equipment_no}")

    if items:
        lines.append("")
        lines.append("**📋 检查项目：**")
        lines.append("")
        for i, item in enumerate(items):
            expected = f"（标准：{item['expected_result']}）" if item.get("expected_result") else ""
            lines.append(f"{i + 1}. **{item['item_name']}**{expected}")

    lines.append("")
    lines.append(f"📊 进度：{progress['done']}/{progress['total']} 已完成")
    if progress["skipped"] > 0:
        lines.append(f"⏭️ {progress['skipped']} 台已跳过")
    lines.append("")
    lines.append("📸 请拍摄设备到位照片，或直接文字描述检查结果。")
    lines.append("回复「**跳过**」跳过此设备 · 回复「**进度**」查看整体进度")

    await send_user_card(
        open_id=open_id,
        title=f"🔍 {plan_type} - {equipment_name}",
        content="\n".join(lines),
        receive_id_type="open_id",
    )


async def _send_confirm_card(
    open_id: str,
    task: InspectionTask,
    results: list[dict],
    equipment_name: str,
) -> None:
    """发送 AI 分析结果确认卡片。"""
    normal = sum(1 for r in results if r["result"] == "正常")
    abnormal = sum(1 for r in results if r["result"] == "异常")
    skip = sum(1 for r in results if r["result"] == "跳过")

    lines = [
        f"**任务：**{task.task_no}",
        f"**设备：**{equipment_name}",
        "",
        "---",
        "**🤖 AI 分析结果：**",
        "",
    ]
    for r in results:
        icon = {"正常": "✅", "异常": "⚠️", "跳过": "⏭️"}.get(r["result"], "⬜")
        v = f" → {r['actual_value']}" if r.get("actual_value") else ""
        rm = f"（{r['remark']}）" if r.get("remark") else ""
        lines.append(f"{icon} **{r['item_name']}**：{r['result']}{v}{rm}")

    lines.append("")
    lines.append("---")
    lines.append(f"汇总：✅ 正常 {normal} | ⚠️ 异常 {abnormal} | ⏭️ 跳过 {skip}")
    lines.append("")
    lines.append("📌 回复「**提交**」保存 · 发送文字修改 · 回复「**取消**」放弃")

    await send_user_card(
        open_id=open_id,
        title=f"🤖 AI 分析 - {equipment_name}",
        content="\n".join(lines),
        receive_id_type="open_id",
    )


async def _send_confirm_card_from_results(
    open_id: str, task_no: str, equipment_name: str, results: list[dict]
) -> None:
    """发送确认卡片（从结果列表，无需 ORM 对象）。"""
    normal = sum(1 for r in results if r["result"] == "正常")
    abnormal = sum(1 for r in results if r["result"] == "异常")
    skip = sum(1 for r in results if r["result"] == "跳过")

    lines = [
        f"**任务：**{task_no}",
        f"**设备：**{equipment_name}",
        "",
        "---",
        "**📝 检查结果：**",
        "",
    ]
    for r in results:
        icon = {"正常": "✅", "异常": "⚠️", "跳过": "⏭️"}.get(r["result"], "⬜")
        v = f" → {r['actual_value']}" if r.get("actual_value") else ""
        rm = f"（{r['remark']}）" if r.get("remark") else ""
        lines.append(f"{icon} **{r['item_name']}**：{r['result']}{v}{rm}")

    lines.append("")
    lines.append("---")
    lines.append(f"汇总：✅ 正常 {normal} | ⚠️ 异常 {abnormal} | ⏭️ 跳过 {skip}")

    await send_user_card(
        open_id=open_id,
        title=f"📝 检查结果 - {equipment_name}",
        content="\n".join(lines),
        receive_id_type="open_id",
    )


# ═══════════ 辅助函数 ═══════════


async def _resolve_user_for_text(
    db: AsyncSession, open_id: str, user_id: str
) -> Any | None:
    """根据 open_id / user_id 查找系统用户（用于文本消息路径）。"""
    from app.platform.identity.models import User

    user = None
    if user_id:
        user = await _find_user_by_user_id(db, user_id)
    if not user:
        user = await _find_user_by_user_id(db, open_id)
    if not user:
        result = await db.execute(
            select(User).where(
                User.feishu_open_id == open_id,
                User.is_deleted == False,  # noqa: E712
            )
        )
        user = result.scalar_one_or_none()
    return user


async def _find_user_by_user_id(
    db: AsyncSession, user_id: str
) -> Any | None:
    """根据飞书 user_id 查找系统用户。"""
    from app.platform.identity.models import User

    result = await db.execute(
        select(User).where(
            User.feishu_user_id == user_id,
            User.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def _find_active_task(
    db: AsyncSession, user_id: uuid.UUID
) -> InspectionTask | None:
    """查找用户正在执行的最新巡检任务。"""
    result = await db.execute(
        select(InspectionTask)
        .where(
            InspectionTask.assigned_to == user_id,
            InspectionTask.status == "执行中",
            InspectionTask.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionTask.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()



async def _get_full_task(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask:
    """带完整关系加载的获取任务。"""
    from app.modules.equipment.models.inspection import InspectionRoute

    result = await db.execute(
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route).selectinload(InspectionRoute.locations_rel),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.assignee),
        )
        .where(
            InspectionTask.id == task_id,
            InspectionTask.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one()


async def _build_equipment_order(
    db: AsyncSession, task: InspectionTask
) -> list[dict]:
    """构建任务关联的设备顺序列表（含地点信息）。
    纯 SQL 查询，不依赖 ORM relationship 遍历，避免 WS 上下文懒加载。
    """
    order: list[dict] = []

    if task.route_id:
        from app.modules.equipment.models.equipment import Equipment, Location
        from app.modules.equipment.models.inspection_route_location import (
            RouteLocation,
            RouteLocationEquipment,
        )

        loc_stmt = (
            select(RouteLocation, Location.name)
            .outerjoin(Location, RouteLocation.location_id == Location.id)
            .where(
                RouteLocation.route_id == task.route_id,
                RouteLocation.is_deleted == False,  # noqa: E712
            )
            .order_by(RouteLocation.sort_order)
        )
        loc_rows = (await db.execute(loc_stmt)).all()
        for loc, loc_name in loc_rows:
            eq_stmt = (
                select(RouteLocationEquipment, Equipment.name, Equipment.equipment_no)
                .join(Equipment, RouteLocationEquipment.equipment_id == Equipment.id)
                .where(
                    RouteLocationEquipment.route_location_id == loc.id,
                    RouteLocationEquipment.is_deleted == False,  # noqa: E712
                    Equipment.is_deleted == False,  # noqa: E712
                )
                .order_by(RouteLocationEquipment.sort_order)
            )
            eq_rows = (await db.execute(eq_stmt)).all()
            for eq, eq_name, eq_no in eq_rows:
                order.append({
                    "equipment_id": str(eq.equipment_id),
                    "equipment_name": eq_name,
                    "equipment_no": eq_no or "",
                    "location_name": loc_name or "",
                    "location_sort_order": loc.sort_order,
                })
    elif task.equipment_ids:
        from app.modules.equipment.models.equipment import Equipment

        for eid_str in task.equipment_ids:
            eid = uuid.UUID(eid_str) if isinstance(eid_str, str) else eid_str
            eq_result = await db.execute(
                select(Equipment.name, Equipment.equipment_no).where(
                    Equipment.id == eid,
                    Equipment.is_deleted == False,  # noqa: E712
                )
            )
            row = eq_result.one_or_none()
            if row:
                order.append({
                    "equipment_id": str(eid),
                    "equipment_name": row.name,
                    "equipment_no": row.equipment_no or "",
                    "location_name": "",
                    "location_sort_order": 0,
                })
    elif task.equipment_id:
        from app.modules.equipment.models.equipment import Equipment

        eq_result = await db.execute(
            select(Equipment.name, Equipment.equipment_no).where(
                Equipment.id == task.equipment_id,
                Equipment.is_deleted == False,  # noqa: E712
            )
        )
        row = eq_result.one_or_none()
        if row:
            order.append({
                "equipment_id": str(task.equipment_id),
                "equipment_name": row.name,
                "equipment_no": row.equipment_no or "",
                "location_name": "",
                "location_sort_order": 0,
            })

    return order


async def _get_processed_equipment_ids(
    db: AsyncSession, task_id: uuid.UUID
) -> tuple[set[str], set[str]]:
    """获取已处理和已跳过的设备 ID 集合。"""
    from app.modules.equipment.models.inspection_template import InspectionRecord

    result = await db.execute(
        select(
            InspectionRecord.equipment_id,
            InspectionRecord.result,
        ).where(
            InspectionRecord.task_id == task_id,
            InspectionRecord.is_deleted == False,  # noqa: E712
        )
    )
    rows = result.all()
    completed: set[str] = set()
    skipped: set[str] = set()
    # 按设备分组：如果某设备有非"跳过"的记录 → completed，否则 → skipped
    eq_results: dict[str, list[str]] = {}
    for row in rows:
        eq_results.setdefault(str(row.equipment_id), []).append(row.result)
    for eid, results_list in eq_results.items():
        if all(r == "跳过" for r in results_list):
            skipped.add(eid)
        else:
            completed.add(eid)
    return completed, skipped


async def _auto_create_session(
    db: AsyncSession, task: InspectionTask, open_id: str
) -> dict | None:
    """自动创建引导会话（拍照触发时用）。"""
    task = await _get_full_task(db, task.id)
    equipment_order = await _build_equipment_order(db, task)
    if not equipment_order:
        return None

    completed, skipped = await _get_processed_equipment_ids(db, task.id)
    first_idx = 0
    for i, eq in enumerate(equipment_order):
        if eq["equipment_id"] not in completed and eq["equipment_id"] not in skipped:
            first_idx = i
            break

    await save_session(
        open_id=open_id,
        task_id=str(task.id),
        plan_type=task.plan_type or "设备巡检",
        task_no=task.task_no,
        route_name=task.route.name if task.route else "",
        equipment_order=equipment_order,
        completed_equipment_ids=list(completed),
        skipped_equipment_ids=list(skipped),
        current_equipment_index=first_idx,
        state=SessionState.GUIDING,
    )

    return await get_session(open_id)


async def _download_image(
    message_id: str, image_key: str
) -> tuple[bytes | None, str | None]:
    """从飞书下载消息中的图片。"""
    from lark_oapi.api.im.v1.model.get_message_resource_request import (
        GetMessageResourceRequest,
    )

    from app.modules.equipment.feishu.client import (
        get_equipment_feishu_client,
        get_equipment_tenant_token,
    )

    client = await get_equipment_feishu_client()
    token = await get_equipment_tenant_token(client)

    req = (
        GetMessageResourceRequest.builder()
        .message_id(message_id)
        .file_key(image_key)
        .type("image")
        .build()
    )
    req.headers["Authorization"] = f"Bearer {token}"

    try:
        resp = await client.im.v1.message_resource.aget(req)
        if resp.code == 0 and resp.file:
            image_bytes = resp.file.read()
            logger.info(
                "图片下载成功: message_id=%s, size=%d bytes",
                message_id, len(image_bytes),
            )
            return image_bytes, "image/jpeg"
        else:
            logger.error("图片下载失败: code=%s, msg=%s", resp.code, resp.msg)
            return None, None
    except Exception:
        logger.exception(
            "图片下载异常: message_id=%s, image_key=%s", message_id, image_key,
        )
        return None, None


async def _save_photo(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    image_bytes: bytes,
) -> InspectionPhoto:
    """保存巡检照片到文件和数据库。"""
    filename = f"{uuid.uuid4()}_feishu.jpg"
    file_path = os.path.normpath(os.path.join(_UPLOAD_DIR, filename))

    with open(file_path, "wb") as f:
        f.write(image_bytes)

    photo = InspectionPhoto(
        task_id=task_id,
        equipment_id=equipment_id,
        file_name=filename,
        file_path=file_path,
        file_size=len(image_bytes),
    )
    db.add(photo)
    await db.commit()

    result = await db.execute(
        select(InspectionPhoto).where(InspectionPhoto.id == photo.id)
    )
    return result.scalar_one()


async def _handle_inspection_selection(open_id: str, opt: dict) -> None:
    """处理巡检任务选择。"""
    task_id = uuid.UUID(opt["task_id"])
    await _select_and_guide(open_id, task_id)


async def _handle_work_order_selection(open_id: str, opt: dict) -> None:
    """处理工单选择（查看详情或完成）。"""
    wo_no = opt.get("work_order_no", "")
    wo_status = opt.get("status", "")

    if wo_status == "执行中":
        await send_user_card(
            open_id=open_id,
            title=f"📋 工单 {wo_no}",
            content=(
                f"**{wo_no}** · {opt.get('order_type', '')}\n"
                f"设备：{opt.get('equipment_name', '')}\n"
                f"状态：{wo_status}\n\n"
                f"发送「完成 {wo_no} 描述」提交完成。\n"
                f"或发送「完成 {opt['index']} 描述」使用序号。"
            ),
            receive_id_type="open_id",
        )
    else:
        await send_user_card(
            open_id=open_id,
            title=f"📋 工单 {wo_no}",
            content=(
                f"**{wo_no}** · {opt.get('order_type', '')}\n"
                f"设备：{opt.get('equipment_name', '')}\n"
                f"状态：{wo_status}"
            ),
            receive_id_type="open_id",
        )


async def _reply_text(open_id: str, text: str) -> None:
    """发送纯文本消息（使用简化卡片）。"""
    await send_user_card(
        open_id=open_id,
        title="💬 巡检助手",
        content=text,
        receive_id_type="open_id",
    )
