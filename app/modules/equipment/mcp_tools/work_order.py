"""工单相关 MCP Tools：查询工单、操作工单、上传照片。"""

from __future__ import annotations

import base64
from typing import Any

from fastmcp.tools.base import ToolResult

from app.modules.equipment.mcp_tools._helpers import (
    _resolve_work_order,
    _wo_to_dict,
)
from app.modules.equipment.repository.work_order import (
    get_user_work_orders,
)
from app.modules.equipment.service import (
    complete_work_order,
    start_work_order,
)
from app.modules.equipment.service.work_order_image import (
    save_photo_from_base64,
)
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp

# ─────────────────────────────────────────────────────────────
# Tool 1: 查询用户维护工单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def list_work_orders(
    operator_id: str,
    status: str | None = None,
) -> ToolResult:
    """
    查询指定用户的维护工单列表。
    适用于维修人员查看自己当前需要处理的工单，
    Agent 替其查看工单列表，可按工单状态过滤。

    Args:
        operator_id: 实际操作人的 user_id 或姓名（替谁查）
        status: 工单状态过滤，可选值：待处理 / 执行中 / 待验收 / 已完成 / 已关闭。
                 不传则默认返回「执行中」的工单（维修人当前正在处理的）。
    """
    db = get_db()
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    work_orders = await get_user_work_orders(db, user.id)

    valid_statuses = {"待处理", "执行中", "待验收", "已完成", "已关闭"}
    if status:
        if status not in valid_statuses:
            return ToolResult(
                content=f"无效的工单状态「{status}」，可选值：待处理 / 执行中 / 待验收 / 已完成 / 已关闭。",
                structured_content={"error": f"无效状态：{status}"},
                is_error=True,
            )
        work_orders = [wo for wo in work_orders if wo.status == status]
    else:
        # 默认只返回「执行中」的工单
        status = "执行中"
        work_orders = [wo for wo in work_orders if wo.status == "执行中"]

    result = [_wo_to_dict(wo) for wo in work_orders]
    if not result:
        return ToolResult(
            content=f"{user.name} 当前没有「{status}」状态的工单。",
            structured_content={"result": [], "total": 0},
        )
    lines = [f"{user.name} 共有 {len(result)} 个工单："]
    for wo in result:
        eq_label = f"{wo['equipment_name']}（{wo['equipment_no']}）" if wo["equipment_no"] else wo["equipment_name"]
        img_info = f"📷{wo['image_count']}张" if wo["image_count"] else ""
        parts = [f"  [{wo['status']}] {wo['work_order_no']}"]
        parts.append(f"（{wo['order_type']} · {eq_label}）")
        if wo["priority"]:
            parts.append(f" 优先级：{wo['priority']}")
        if img_info:
            parts.append(f" {img_info}")
        if wo["repair_detail"]:
            parts.append(f"\n    维修描述：{wo['repair_detail'][:80]}{'…' if len(wo['repair_detail']) > 80 else ''}")
        lines.append("".join(parts))
    return ToolResult(
        content="\n".join(lines),
        structured_content={"result": result, "total": len(result)},
    )


# ─────────────────────────────────────────────────────────────
# Tool 2: 开始/提交/完成工单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def operate_work_order(
    work_order: str,
    action: str,
    operator_id: str,
    repair_detail: str | None = None,
) -> ToolResult:
    """
    对维护工单执行状态流转操作：开始维修、提交验收、或完成维修。

    Args:
        work_order: 工单编号（如 WO-20260616-0001）或工单 UUID
        action: 操作类型，可选值：
            - start：开始维修，工单从「待处理」变为「执行中」
            - submit：提交验收，工单从「执行中」变为「待验收」（需 repair_detail）
            - complete：同 submit，提交验收
        operator_id: 实际操作人的 user_id 或姓名
        repair_detail: 维修过程描述，action=submit/complete 时必需。
                       应详细描述维修过程和结果，如「更换了轴承密封圈，设备恢复正常运转」。
    """
    db = get_db()
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    if action not in ("start", "submit", "complete"):
        return ToolResult(
            content=f"无效的操作类型「{action}」，可选值：start（开始维修）、submit（提交验收）、complete（提交验收）。",
            structured_content={"error": f"无效操作：{action}"},
            is_error=True,
        )

    try:
        wo = await _resolve_work_order(db, work_order)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")
    eq_name = wo.equipment.name if wo.equipment else "未知设备"

    if action == "start":
        result = await start_work_order(db, wo.id, ctx)
        await db.commit()
        return ToolResult(
            content=f"工单 {result.work_order_no} 已开始维修（{eq_name}），状态：待处理 → {result.status}",
            structured_content={
                "success": True,
                "work_order_no": result.work_order_no,
                "old_status": "待处理",
                "new_status": result.status,
            },
        )

    # submit / complete：提交验收
    if not repair_detail or not repair_detail.strip():
        return ToolResult(
            content="提交验收时需要提供 repair_detail（维修过程描述），请描述维修过程和结果后重试。\n例如：「更换了轴承密封圈，设备恢复正常运转」",
            structured_content={"error": "缺少 repair_detail"},
            is_error=True,
        )

    if wo.status != "执行中":
        return ToolResult(
            content=f"工单 {wo.work_order_no} 当前状态为「{wo.status}」，只有「执行中」的工单才能提交验收。",
            structured_content={"error": f"当前状态 {wo.status} 不允许提交验收"},
            is_error=True,
        )

    from app.modules.equipment.schemas.work_order import WorkOrderComplete

    data = WorkOrderComplete(repair_detail=repair_detail.strip())
    result = await complete_work_order(db, wo.id, data, ctx)
    await db.commit()

    # 使用 re-fetched result 的 images（已 eager loaded），避免访问已过期的 wo.images
    result_images = result.images if result.images is not None else []
    img_info = f"，已上传 {len(result_images)} 张现场照片" if result_images else ""
    target_info = "待验收（已飞书通知责任人确认）" if result.status == "待验收" else result.status
    return ToolResult(
        content=f"工单 {result.work_order_no} 已提交验收（{eq_name}）{img_info}\n状态：执行中 → {target_info}\n维修描述：{repair_detail.strip()[:200]}",
        structured_content={
            "success": True,
            "work_order_no": result.work_order_no,
            "old_status": "执行中",
            "new_status": result.status,
            "image_count": len(result_images),
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 3: 上传工单现场照片
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def submit_work_order_photos(
    work_order: str,
    operator_id: str,
    images: list[str],
) -> ToolResult:
    """
    为指定工单上传现场照片（维修前/维修后等）。

    照片存储在 work_order_images 表中，关联到工单。
    提交验收时，照片会随飞书通知卡片一起发送给责任人。
    支持 JPG、PNG、WEBP、BMP 格式，单张最大 10MB，每个工单最多 9 张。

    Args:
        work_order: 工单编号（如 WO-20260616-0001）或工单 UUID
        operator_id: 实际操作人的 user_id 或姓名
        images: 照片的 base64 编码列表（不含 data:image/xxx;base64, 前缀）
    """
    # ═══════════ 阶段 1: 图片前置校验（不访问 DB）═══════════

    if not images:
        return ToolResult(
            content="上传失败：images 参数不能为空列表。请提供至少一张照片的 base64 编码。",
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

    for i, img in enumerate(images):
        idx = i + 1

        if not isinstance(img, str) or not img.strip():
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片数据为空，请提供有效的 base64 编码字符串",
            })
            continue

        try:
            content = base64.b64decode(img, validate=True)
        except Exception as e:
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片 base64 解码失败：{e}。请确保传入的是不含前缀的纯 base64 字符串",
            })
            continue

        if len(content) > max_size:
            size_mb = len(content) / 1024 / 1024
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片大小 {size_mb:.1f}MB 超过上限 10MB，请压缩后再上传",
            })
            continue

        if len(content) < 64:
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片数据过小（{len(content)} bytes），可能不是有效图片",
            })
            continue

        magic = content[:4]
        recognized = any(magic.startswith(mb) for mb in valid_magics)
        if not recognized:
            validation_errors.append({
                "index": idx,
                "reason": f"第{idx}张图片格式无法识别，仅支持 {supported_formats} 格式",
            })
            continue

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

    # ═══════════ 阶段 2: 解析用户和工单 ═══════════

    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    try:
        wo = await _resolve_work_order(db, work_order)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    wo_id = wo.id
    wo_no = wo.work_order_no
    eq_name = wo.equipment.name if wo.equipment else "未知设备"

    # ═══════════ 阶段 3: 上传照片 ═══════════

    success_count = 0
    failed_count = 0
    failed_details: list[dict[str, Any]] = []

    for i, img_b64 in enumerate(images):
        idx = i + 1
        try:
            # 使用 savepoint 隔离每张图片的保存，单张失败不影响已成功的记录
            async with db.begin_nested():
                await save_photo_from_base64(db, wo_id, img_b64)
            success_count += 1
        except Exception as e:
            failed_count += 1
            failed_details.append({
                "index": idx,
                "reason": f"第{idx}张照片保存失败：{e}",
            })

    await db.commit()

    # ═══════════ 阶段 4: 返回结果 ═══════════

    if success_count == 0:
        reason_lines = [d["reason"] for d in failed_details]
        return ToolResult(
            content=f"上传失败：{failed_count} 张照片全部未能保存。\n" + "\n".join(f"  · {r}" for r in reason_lines),
            structured_content={
                "success": False,
                "work_order_no": wo_no,
                "equipment_name": eq_name,
                "photo_count": 0,
                "failed_count": failed_count,
                "failed_details": failed_details,
            },
            is_error=True,
        )

    parts = [
        f"工单 {wo_no}（{eq_name}）",
        f"成功上传 {success_count} 张照片",
    ]
    if failed_count:
        parts.append(f"{failed_count} 张失败")

    return ToolResult(
        content="，".join(parts) + "。",
        structured_content={
            "success": True,
            "work_order_no": wo_no,
            "equipment_name": eq_name,
            "photo_count": success_count,
            "failed_count": failed_count,
            "failed_details": failed_details,
        },
    )
