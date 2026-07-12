"""巡检相关 MCP Tools：提交检查项、上传照片、查询任务、管理任务状态、进度查询、检查项模板。"""

from __future__ import annotations

import base64
import uuid
from typing import Any

from fastmcp.tools.base import ToolResult
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.modules.equipment.mcp_tools._helpers import (
    _get_template_item_map,
    _it_to_dict,
    _resolve_equipment,
)
from app.modules.equipment.models.inspection_route_location import (
    RouteLocation,
    RouteLocationEquipment,
)
from app.modules.equipment.repository.inspection import (
    get_equipment_names_by_ids,
    get_equipment_nos_by_ids,
    get_task_by_no,
    get_task_equipment_completed_ids,
)
from app.modules.equipment.service.inspection import (
    close_task as close_inspection_task,
)
from app.modules.equipment.service.inspection import (
    complete_task as complete_inspection_task,
)
from app.modules.equipment.service.inspection import (
    get_task_by_id as get_inspection_task_by_id,
)
from app.modules.equipment.service.inspection import (
    get_tasks as get_inspection_tasks,
)
from app.modules.equipment.service.inspection import (
    save_photo_from_base64,
    submit_equipment_check,
)
from app.modules.equipment.service.inspection import (
    start_task as start_inspection_task,
)
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp

# ─────────────────────────────────────────────────────────────
# Tool 4: 提交巡检表单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def submit_inspection(
    task_no: str,
    equipment: str,
    operator_id: str,
    check_items: list[dict[str, Any]],
) -> ToolResult:
    """
    提交设备巡检表单，逐项记录检查结果。

    支持线路巡检和设备巡检两种模式：
    - 设备巡检：直接使用 task 上绑定的 template_ids 查找检查项
    - 线路巡检：从路线 → 地点 → 设备的模板绑定中查找检查项（自动合并多模板）

    如果所有设备都已提交，自动完成该巡检任务。

    如需上传巡检照片，请使用 submit_inspection_photos 工具。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        equipment: 设备编号（如 EQ-001）或 UUID
        operator_id: 实际操作人的 user_id 或姓名
        check_items: 检查项列表，每项包含：
            - item_name: 检查项目名称（必需）
            - result: 检查结果，可选值：正常 / 异常 / 跳过（必需）
            - actual_value: 实测值（可选）。数值型检查项只填纯数字（如 25.3），
              勿带单位/文字，否则会被拒绝并要求重填。
            - remark: 备注（可选）
    """
    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    try:
        eq = await _resolve_equipment(db, equipment)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)
    equipment_uuid = eq.id

    task_uuid = task.id

    # 校验 check_items
    valid_results = {"正常", "异常", "跳过"}
    for item in check_items:
        item_name = item.get("item_name", "")
        result = item.get("result", "")
        if not item_name:
            return ToolResult(
                content="提交失败：每个检查项必须提供 item_name。",
                structured_content={"error": "缺少 item_name"},
                is_error=True,
            )
        if result not in valid_results:
            return ToolResult(
                content=f"提交失败：检查项「{item_name}」的结果值「{result}」无效，可选值：正常 / 异常 / 跳过。",
                structured_content={"error": f"无效的检查结果：{item_name}={result}"},
                is_error=True,
            )
        if result == "异常" and not item.get("actual_value") and not item.get("remark"):
            return ToolResult(
                content=f"提交失败：检查项「{item_name}」结果为【异常】，必须填写实际值（actual_value）或备注（remark）。",
                structured_content={"error": f"异常项缺少 actual_value/remark：{item_name}"},
                is_error=True,
            )

    # 加载模板项映射（支持线路巡检多模板，按设备过滤）
    name_to_id = await _get_template_item_map(db, task, equipment_uuid)

    if not name_to_id:
        if task.route_id:
            msg = "该路线尚未配置设备检查模板，请先在系统中配置模板后再提交。"
        else:
            msg = "该任务未绑定检查模板，请先在系统中配置模板后再提交。"
        return ToolResult(content=msg, structured_content={"error": msg}, is_error=True)

    # 构建 name ↔ id 双向映射（排除冲突标记 ""）
    id_to_name = {v: k for k, v in name_to_id.items() if v}

    # 构建 records
    records: list[dict[str, Any]] = []
    for item in check_items:
        rec: dict[str, Any] = {
            "result": item["result"],
            "actual_value": item.get("actual_value", ""),
            "remark": item.get("remark", ""),
        }
        tid = item.get("template_item_id")
        if tid:
            if tid not in id_to_name:
                available = "、".join([k for k, v in name_to_id.items() if v][:10])
                return ToolResult(
                    content=f"提交失败：template_item_id「{tid}」无效，数据库中没有此检查项。\n"
                            f"请使用 get_inspection_check_items 获取正确的 template_item_id。\n"
                            f"可用检查项：{available}",
                    structured_content={
                        "error": f"无效的 template_item_id：{tid}",
                        "available": [k for k, v in name_to_id.items() if v][:10],
                    },
                    is_error=True,
                )
            rec["template_item_id"] = tid
        else:
            item_name = item["item_name"]
            mapped_id = name_to_id.get(item_name)
            if mapped_id is None:
                available = "、".join([k for k in name_to_id if name_to_id[k]][:10])
                return ToolResult(
                    content=f"提交失败：未找到检查项「{item_name}」。\n"
                            f"可用检查项：{available}\n"
                            f"请确认检查项名称与模板完全一致。",
                    structured_content={"error": f"未知检查项：{item_name}", "available": [k for k in name_to_id if name_to_id[k]][:10]},
                    is_error=True,
                )
            if not mapped_id:
                return ToolResult(
                    content=f"提交失败：检查项「{item_name}」在多个模板中存在，无法通过名称定位。\n"
                            f"请使用 get_inspection_check_items 获取正确的 template_item_id，"
                            f"并在提交时提供 template_item_id 而非 item_name。",
                    structured_content={
                        "error": f"检查项名称冲突：{item_name}",
                        "hint": "使用 template_item_id 替代 item_name",
                    },
                    is_error=True,
                )
            rec["template_item_id"] = mapped_id
        records.append(rec)

    # 提交
    try:
        submitted = await submit_equipment_check(db, task_uuid, equipment_uuid, records)
    except Exception as e:
        await db.rollback()
        return ToolResult(
            content=f"提交失败：系统内部错误。\n详情：{e}",
            structured_content={"error": str(e)},
            is_error=True,
        )

    # 显式提交事务
    await db.commit()

    # 重新查询任务状态
    task_after = await get_inspection_task_by_id(db, task_uuid)
    all_done = task_after.status == "已完成"

    lines = [
        f"任务 {task.task_no} · 设备 {eq.equipment_no}（{eq.name}）提交成功！",
        f"已记录 {len(submitted)} 项检查结果",
    ]
    if all_done:
        lines.append("所有设备均已提交，巡检任务已完成！")
    else:
        lines.append("还有待检设备，请继续巡检。")
    content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={
            "success": True,
            "task_no": task.task_no,
            "equipment_no": eq.equipment_no,
            "submitted_count": len(submitted),
            "all_done": all_done,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 4.5: 上传巡检照片
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def submit_inspection_photos(
    task_no: str,
    equipment: str,
    operator_id: str,
    images: list[str],
) -> ToolResult:
    """
    为指定巡检任务的设备上传现场照片。

    照片存储在 inspection_photos 表中，关联到任务和设备。
    任务必须处于「执行中」状态才能上传。
    支持 JPG、PNG、WEBP、BMP 格式，单张最大 10MB。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        equipment: 设备编号（如 EQ-001）或 UUID
        operator_id: 实际操作人的 user_id 或姓名
        images: 巡检照片的 base64 编码列表（不含 data:image/xxx;base64, 前缀）
    """
    # ═══════════ 阶段 1: 图片前置校验（不访问 DB）═══════════

    if not images:
        return ToolResult(
            content="上传失败：images 参数不能为空列表。请提供至少一张巡检照片的 base64 编码。",
            structured_content={"success": False, "error": "images 不能为空"},
            is_error=True,
        )

    max_size = 10 * 1024 * 1024  # 10 MB
    valid_magics: dict[bytes, str] = {
        b"\xff\xd8\xff": "JPG",
        b"\x89PNG": "PNG",
        b"RIFF": "WEBP",
        b"BM": "BMP",
    }
    supported_formats = "、".join(sorted(set(valid_magics.values())))

    validation_errors: list[dict[str, Any]] = []
    decoded_images: list[bytes] = []

    for i, img in enumerate(images):
        idx = i + 1

        if not isinstance(img, str) or not img.strip():
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片数据为空，请提供有效的 base64 编码字符串",
            })
            decoded_images.append(b"")
            continue

        try:
            content = base64.b64decode(img, validate=True)
        except Exception as e:
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片 base64 解码失败：{e}。请确保传入的是不含前缀的纯 base64 字符串",
            })
            decoded_images.append(b"")
            continue

        if len(content) > max_size:
            size_mb = len(content) / 1024 / 1024
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片大小 {size_mb:.1f}MB 超过上限 10MB，请压缩后再上传",
            })
            decoded_images.append(b"")
            continue

        if len(content) < 64:
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片数据过小（{len(content)} bytes），可能不是有效图片",
            })
            decoded_images.append(b"")
            continue

        magic = content[:4]
        recognized = any(magic.startswith(mb) for mb in valid_magics)
        if not recognized:
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片格式无法识别，仅支持 {supported_formats} 格式",
            })
            decoded_images.append(b"")
            continue

        decoded_images.append(content)

    if validation_errors:
        reason_lines = [e["reason"] for e in validation_errors]
        return ToolResult(
            content=f"图片校验失败，共 {len(validation_errors)} 张图片有问题：\n" + "\n".join(f"  · {r}" for r in reason_lines),
            structured_content={
                "success": False,
                "error": "图片校验失败",
                "validation_errors": validation_errors,
            },
            is_error=True,
        )

    # ═══════════ 阶段 2: 解析用户、任务、设备 ═══════════

    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    if task.status != "执行中":
        return ToolResult(
            content=f"任务「{task_no}」当前状态为「{task.status}」，只有「执行中」的任务才能上传照片。",
            structured_content={
                "error": f"任务状态不允许上传照片：当前为「{task.status}」，需要「执行中」",
            },
            is_error=True,
        )

    try:
        eq = await _resolve_equipment(db, equipment)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    task_uuid = task.id
    equipment_uuid = eq.id

    # ═══════════ 阶段 3: 上传照片（best-effort）═══════════

    success_count = 0
    failed_count = 0
    failed_details: list[dict[str, Any]] = []

    for i, img_b64 in enumerate(images):
        idx = i + 1
        try:
            await save_photo_from_base64(db, task_uuid, equipment_uuid, img_b64)
            success_count += 1
        except Exception as e:
            await db.rollback()
            failed_count += 1
            failed_details.append({
                "index": idx,
                "reason": f"第{idx}张图片保存失败：{e}",
            })

    await db.commit()

    # ═══════════ 阶段 4: 返回结果 ═══════════

    if success_count == 0:
        reason_lines = [d["reason"] for d in failed_details]
        return ToolResult(
            content=f"上传失败：{failed_count} 张照片全部未能保存。\n" + "\n".join(f"  · {r}" for r in reason_lines),
            structured_content={
                "success": False,
                "task_no": task.task_no,
                "equipment_no": eq.equipment_no,
                "photo_count": 0,
                "failed_count": failed_count,
                "failed_details": failed_details,
            },
            is_error=True,
        )

    parts = [
        f"任务 {task.task_no} · 设备 {eq.equipment_no}（{eq.name}）",
        f"成功上传 {success_count} 张照片",
    ]
    if failed_count:
        parts.append(f"{failed_count} 张失败")

    return ToolResult(
        content="，".join(parts) + "。",
        structured_content={
            "success": True,
            "task_no": task.task_no,
            "equipment_no": eq.equipment_no,
            "photo_count": success_count,
            "failed_count": failed_count,
            "failed_details": failed_details,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 5: 查询巡检任务
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def list_inspection_tasks(
    operator_id: str,
    status: str | None = None,
) -> ToolResult:
    """
    查询指定用户的巡检任务列表。

    Args:
        operator_id: 实际操作人的 user_id 或姓名（替谁查）
        status: 任务状态过滤，可选值：待执行 / 执行中 / 已完成 / 已关闭。
                 不传则只返回待处理的任务（待执行 + 执行中）。
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")

    if status:
        valid_statuses = {"待执行", "执行中", "已完成", "已关闭"}
        if status not in valid_statuses:
            raise ValueError(
                f"无效的任务状态 '{status}'，可选值：{' / '.join(valid_statuses)}"
            )

    tasks, _total = await get_inspection_tasks(
        db, ctx, assigned_to=user.id, status=status, page=1, page_size=100,
    )
    if not status:
        tasks = [t for t in tasks if t.status in ("待执行", "执行中")]
    result = [_it_to_dict(t) for t in tasks]

    # 补充多设备任务的 equipment_name 和 equipment_no
    need_enrich: list[dict[str, Any]] = []
    all_eq_ids: set[uuid.UUID] = set()
    for r in result:
        if not r["equipment_name"] and r.get("equipment_ids"):
            need_enrich.append(r)
            for eid_str in r["equipment_ids"]:
                all_eq_ids.add(uuid.UUID(eid_str))

    if need_enrich:
        name_map = await get_equipment_names_by_ids(db, list(all_eq_ids))
        no_map = await get_equipment_nos_by_ids(db, list(all_eq_ids))
        for r in need_enrich:
            names = [
                name_map.get(uuid.UUID(eid), eid[:8] + "…")
                for eid in r["equipment_ids"]
            ]
            nos = [
                no_map.get(uuid.UUID(eid), "")
                for eid in r["equipment_ids"]
            ]
            if names:
                r["equipment_name"] = "、".join(n for n in names[:3] if n)
                if len(names) > 3:
                    r["equipment_name"] += f" 等{len(names)}台"
            if nos:
                r["equipment_no"] = "、".join(n for n in nos[:3] if n)
                if len(nos) > 3:
                    r["equipment_no"] += f" 等{len(nos)}台"

    if not result:
        content = f"{user.name} 当前没有待处理的巡检任务。"
    else:
        lines = [f"{user.name} 共有 {len(result)} 个巡检任务："]
        for t in result:
            eq_label = t["equipment_name"] or t.get("equipment_no", "") or f"{t['equipment_count']}台设备"
            route_label = f"路线「{t['route_name']}」" if t["route_name"] else ""
            lines.append(
                f"- [{t['status']}] {t['task_no']} "
                f"({t['plan_type']}{' · ' + route_label if route_label else ''} · {eq_label})"
            )
        content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={"result": result, "total": len(result)},
    )


# ─────────────────────────────────────────────────────────────
# Tool 6: 修改巡检任务状态
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def update_inspection_task(
    task_no: str,
    action: str,
    operator_id: str,
    remark: str | None = None,
) -> ToolResult:
    """
    修改巡检任务状态：开始执行、完成、或关闭任务。

    - action="start"：任务从"待执行"变为"执行中"
    - action="complete"：任务从"执行中"变为"已完成"（设备巡检和线路巡检均支持）
    - action="close"：任务变为"已关闭"

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        action: 操作类型，可选值 start / complete / close
        operator_id: 实际操作人的 user_id 或姓名
        remark: 备注说明，action=close 时作为关闭原因
    """
    db = get_db()
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    if action not in ("start", "complete", "close"):
        return ToolResult(
            content=f"无效的操作类型「{action}」，可选值：start（开始执行）、complete（完成）、close（关闭）。",
            structured_content={"error": f"无效操作：{action}"},
            is_error=True,
        )

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")
    task_uuid = task.id
    old_status = task.status
    route_label = f"（路线「{task.route.name}」）" if task.route else ""

    if action == "start":
        result = await start_inspection_task(db, task_uuid, ctx)
        content = f"任务 {result.task_no} 已开始执行{route_label}，状态：{old_status} → {result.status}"
    elif action == "complete":
        result = await complete_inspection_task(db, task_uuid, ctx)
        content = f"任务 {result.task_no} 已完成{route_label}，状态：{old_status} → {result.status}"
    else:
        result = await close_inspection_task(db, task_uuid, remark=remark)
        reason = f"，原因：{remark}" if remark else ""
        content = f"任务 {result.task_no} 已关闭{route_label}{reason}，状态：{old_status} → {result.status}"

    await db.commit()

    return ToolResult(
        content=content,
        structured_content={
            "success": True,
            "task_no": result.task_no,
            "old_status": old_status,
            "new_status": result.status,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 7: 查询巡检任务进度
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def get_inspection_task_progress(
    task_no: str,
    operator_id: str,
) -> ToolResult:
    """
    查询巡检任务中每台设备的检查进度：哪些已提交、哪些待检。

    Agent 可据此告诉用户「任务 X 共 N 台设备，已完成 M 台，还剩 A、B、C 待检」。
    适用于用户说了"我要提交巡检"但不知道当前进度时，Agent 主动查询并引导。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        operator_id: 实际操作人的 user_id 或姓名
    """
    db = get_db()
    await resolve_user(db, operator_id)

    task = await get_task_by_no(db, task_no)
    if not task:
        raise ValueError(f"未找到任务：{task_no}")
    task_uuid = task.id

    # 收集任务涉及的所有设备
    equipments: list[dict[str, Any]] = []

    if task.route_id:
        loc_stmt = select(RouteLocation).where(
            RouteLocation.route_id == task.route_id,
            RouteLocation.is_deleted == False,  # noqa: E712
        ).options(
            selectinload(RouteLocation.location),
        ).order_by(RouteLocation.sort_order)
        locs = (await db.execute(loc_stmt)).scalars().all()

        for loc in locs:
            eq_stmt = select(RouteLocationEquipment).where(
                RouteLocationEquipment.route_location_id == loc.id,
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
            ).options(
                selectinload(RouteLocationEquipment.equipment),
            ).order_by(RouteLocationEquipment.sort_order)
            eqs = (await db.execute(eq_stmt)).scalars().all()
            for eq in eqs:
                equipments.append({
                    "equipment_id": str(eq.equipment_id),
                    "equipment_name": eq.equipment.name if eq.equipment else "",
                    "equipment_no": eq.equipment.equipment_no if eq.equipment else "",
                    "location_name": loc.location.name if loc.location else "",
                    "sort_order": eq.sort_order,
                })
    elif task.equipment_ids or task.equipment_id:
        eq_ids: list[str] = list(task.equipment_ids or [])
        if task.equipment_id:
            eid_str = str(task.equipment_id)
            if eid_str not in eq_ids:
                eq_ids.append(eid_str)

        name_map = await get_equipment_names_by_ids(
            db, [uuid.UUID(eid) for eid in eq_ids]
        )
        no_map = await get_equipment_nos_by_ids(
            db, [uuid.UUID(eid) for eid in eq_ids]
        )
        for eid_str in eq_ids:
            equipments.append({
                "equipment_id": eid_str,
                "equipment_name": name_map.get(uuid.UUID(eid_str), ""),
                "equipment_no": no_map.get(uuid.UUID(eid_str), ""),
                "location_name": "",
                "sort_order": 0,
            })

    completed_ids = await get_task_equipment_completed_ids(db, task_uuid)
    completed_set = {str(cid) for cid in completed_ids}

    for eq in equipments:
        eq["checked"] = eq["equipment_id"] in completed_set

    pending = [eq for eq in equipments if not eq["checked"]]
    checked = [eq for eq in equipments if eq["checked"]]

    route_label = f" · 路线「{task.route.name}」" if task.route else ""
    lines = [
        f"任务 {task.task_no}（{task.plan_type}{route_label}）",
        f"进度：{len(checked)}/{len(equipments)} 已完成，{len(pending)} 台待检",
    ]
    if pending:
        lines.append("待检设备：")
        for eq in pending:
            loc = f"（{eq['location_name']}）" if eq.get("location_name") else ""
            no = f" {eq['equipment_no']}" if eq.get("equipment_no") else ""
            lines.append(f"  - {eq['equipment_name']}{no}{loc}  [{eq['equipment_id']}]")
    if checked:
        lines.append("已检设备：")
        for eq in checked:
            no = f" {eq['equipment_no']}" if eq.get("equipment_no") else ""
            lines.append(f"  - {eq['equipment_name']}{no}  [{eq['equipment_id']}]")
    content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={
            "task_id": str(task.id),
            "task_no": task.task_no,
            "plan_type": task.plan_type,
            "status": task.status,
            "route_name": task.route.name if task.route else "",
            "total_equipments": len(equipments),
            "checked_count": len(checked),
            "pending_count": len(pending),
            "equipments": equipments,
            "pending_equipments": pending,
            "checked_equipments": checked,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 8: 查询设备巡检检查项模板
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def get_inspection_check_items(
    task_no: str,
    equipment: str,
    operator_id: str,
) -> ToolResult:
    """
    查询巡检任务中某台设备需要检查的模板项列表（含检查项名称和预期值）。

    Agent 据此告诉用户「请检查以下项目：温度（标准25±2℃）、压力（标准<0.5MPa）...」，
    并在用户发送照片后，将检查项列表传给视觉模型进行分析。

    支持线路巡检（路线→地点→设备→模板链）和设备巡检（equipment_templates映射）。

    数值型检查项（data_type=numeric）须提交纯数字实测值，单位已在配置中，勿混入 actual_value。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        equipment: 设备编号（如 EQ-001）或 UUID
        operator_id: 实际操作人的 user_id 或姓名
    """
    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    try:
        eq = await _resolve_equipment(db, equipment)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    from app.modules.equipment.service.inspection import get_inspection_items

    items, tpl_names = await get_inspection_items(db, task, eq.id)

    item_dicts = [
        {
            "template_item_id": str(item.id),
            "item_name": item.item_name,
            "expected_result": item.expected_result or "",
            "data_type": item.data_type,
            "unit": item.unit or "",
            "sort_order": item.sort_order,
            "template_name": tpl_names.get(item.id, ""),
        }
        for item in items
    ]

    if not item_dicts:
        content = f"设备 {eq.equipment_no}（{eq.name}）没有配置检查项。请先在系统中为此设备绑定巡检模板。"
    else:
        lines = [
            f"设备 {eq.equipment_no}（{eq.name}）的检查项（共 {len(item_dicts)} 项）：",
        ]
        for item in item_dicts:
            std = f"（标准：{item['expected_result']}）" if item["expected_result"] else ""
            tpl = f" [{item['template_name']}]" if item["template_name"] else ""
            if item["data_type"] == "numeric":
                unit_label = f"·单位{item['unit']}" if item["unit"] else ""
                type_hint = f"（数值{unit_label}，请填纯数字）"
            else:
                type_hint = ""
            lines.append(f"{item['sort_order'] + 1}. {item['item_name']}{type_hint}{std}{tpl}")
        content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={
            "task_no": task.task_no,
            "equipment_no": eq.equipment_no,
            "items": item_dicts,
        },
    )
