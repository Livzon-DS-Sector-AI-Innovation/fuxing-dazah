"""Spare part service: business logic for spare parts and stock."""

import io
import logging
import uuid
from typing import Any, cast

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.equipment import repository as repo
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.spare_part import (
    SparePart,
    SparePartStock,
)
from app.modules.equipment.schemas.equipment import (
    EquipmentImportResponse,
    ImportRowError,
)
from app.modules.equipment.schemas.spare_part import (
    SparePartCreate,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
    StockOutboundRequest,
    StockSettingsRequest,
    StockWarningResponse,
)
from app.modules.equipment.service.data_scope import verify_write_ownership

logger = logging.getLogger(__name__)


async def create_spare_part(
    db: AsyncSession,
    data: SparePartCreate,
    ctx: EquipmentAccessContext,
) -> SparePart:
    """创建备件，自动创建库存记录（含安全库存/库位等设置与期初库存）。"""
    if await repo.exists_spare_part_by_code(db, data.code):
        raise DuplicateException("备件编码", data.code)

    create_data = data.model_dump()
    # 库存设置不入主数据表，建档时写入库存行
    initial_qty = create_data.pop("initial_qty", 0)
    stock_init = {
        "current_qty": initial_qty,
        "safety_qty": create_data.pop("safety_qty", 0),
        "min_order_qty": create_data.pop("min_order_qty", 1),
        "warehouse_location": create_data.pop("warehouse_location", None),
    }

    # 自动归属用户部门；超管（无可见部门列表）必须显式指定，
    # 否则产出无主备件——verify_write_ownership 对 None 放行，人人可改
    if not create_data.get("department_id"):
        if ctx.visible_department_ids:
            create_data["department_id"] = ctx.visible_department_ids[0]
        else:
            raise AppException(message="无法确定归属部门，请显式指定归属部门")

    spare_part = await repo.create_spare_part(db, create_data)

    stock_init["spare_part_id"] = spare_part.id
    await repo.create_stock(db, stock_init)

    # 期初库存记一条入库流水，保持与「先建档再入库」路径账目一致
    if initial_qty > 0:
        await repo.create_transaction(
            db,
            {
                "spare_part_id": spare_part.id,
                "transaction_type": "入库",
                "quantity": initial_qty,
                "remark": "期初库存",
                "created_by": ctx.user.id,
            },
        )

    return spare_part


async def get_spare_part_by_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> SparePart:
    """获取备件"""
    spare_part = await repo.get_spare_part_by_id(db, spare_part_id)
    if not spare_part:
        raise NotFoundException("备件", str(spare_part_id))
    return spare_part


async def get_spare_parts(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    category: str | None = None,
    keyword: str | None = None,
    is_active: bool | None = None,
    low_stock: bool | None = None,
    department_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SparePart], int]:
    """获取备件列表，批量填充 department_name。"""
    spare_parts, total = await repo.get_spare_parts(
        db,
        ctx,
        category=category,
        keyword=keyword,
        is_active=is_active,
        low_stock=low_stock,
        department_id=department_id,
        page=page,
        page_size=page_size,
    )
    # 批量填充 department_name（一次查询，避免逐行 N+1）
    dept_ids = {sp.department_id for sp in spare_parts if sp.department_id}
    if dept_ids:
        names = await repo.get_department_names_by_ids(db, list(dept_ids))
        for sp in spare_parts:
            if sp.department_id:
                sp.department_name = names.get(sp.department_id, "")  # type: ignore[attr-defined]
    return spare_parts, total


async def update_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: SparePartUpdate,
    ctx: EquipmentAccessContext,
) -> SparePart:
    """更新备件"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    await verify_write_ownership(ctx, spare_part, "department_id", "department_id")

    update_data = data.model_dump(exclude_unset=True)

    # 归属部门不随主数据随意变更：受限用户不能清空（会产出人人可读的无主行）
    # 也不能移到可见范围外；超管保留改派能力（历史无主数据的修复入口）
    if "department_id" in update_data:
        new_dept = update_data["department_id"]
        if not ctx.is_unrestricted:
            if new_dept is None:
                raise ForbiddenException("无权清空备件归属部门")
            if new_dept not in ctx.visible_department_ids:
                raise ForbiddenException("无权将备件归属到其他部门")

    if "code" in update_data:
        code_exists = await repo.exists_spare_part_by_code(
            db, update_data["code"], exclude_id=spare_part_id
        )
        if code_exists:
            raise DuplicateException("备件编码", update_data["code"])

    result = await repo.update_spare_part(db, spare_part_id, update_data)
    if not result:
        raise NotFoundException("备件", str(spare_part_id))
    # flush 后 updated_at 等服务端生成列已过期，序列化时懒加载会触发
    # MissingGreenlet——重新查询取新对象返回（cancel_batch 同模式）
    return cast(SparePart, await repo.get_spare_part_by_id(db, spare_part_id))


async def delete_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> bool:
    """删除备件（软删）：库存必须先归零，关联行随删，避免留孤儿数据。"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    await verify_write_ownership(ctx, spare_part, "department_id", "department_id")

    # 加锁读取：否则并发入库可在「读到 0」与「软删库存行」之间插入，
    # 已提交的入库数量会随库存行一起被软删，账实丢失
    stock = await repo.get_stock_by_spare_part_id(db, spare_part_id, for_update=True)
    if stock and stock.current_qty > 0:
        raise AppException(
            message=(
                f"备件当前库存 {stock.current_qty} {spare_part.unit}，"
                "请先盘点归零或出库后再删除"
            )
        )

    await repo.delete_equipment_spare_parts_by_spare_part(db, spare_part_id)
    if stock:
        stock.is_deleted = True
        await db.flush()
    return await repo.delete_spare_part(db, spare_part_id)


async def update_stock_settings(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: StockSettingsRequest,
    ctx: EquipmentAccessContext,
) -> SparePartStock:
    """更新库存设置（安全库存/最小采购批量/库位），不产生数量流水。"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    await verify_write_ownership(ctx, spare_part, "department_id", "department_id")

    stock = await get_stock_by_spare_part_id(db, spare_part_id, for_update=True)

    update_data = data.model_dump(exclude_unset=True)
    if "safety_qty" in update_data and update_data["safety_qty"] is not None:
        stock.safety_qty = update_data["safety_qty"]
    if "min_order_qty" in update_data and update_data["min_order_qty"] is not None:
        stock.min_order_qty = update_data["min_order_qty"]
    # warehouse_location 显式传 null 也可清空（传空串同理）
    if "warehouse_location" in update_data:
        stock.warehouse_location = update_data["warehouse_location"] or None

    stock.updated_by = ctx.user.id
    await db.flush()
    # 重新查询：flush 后服务端生成列过期，原对象直接序列化会 MissingGreenlet
    return cast(
        SparePartStock, await repo.get_stock_by_spare_part_id(db, spare_part_id)
    )


async def get_stock_by_spare_part_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    for_update: bool = False,
) -> SparePartStock:
    """获取库存记录（for_update=True 时加行锁，供先校验后增减的写路径使用）"""
    stock = await repo.get_stock_by_spare_part_id(db, spare_part_id, for_update=for_update)
    if not stock:
        raise NotFoundException("库存记录", str(spare_part_id))
    return stock


def _ensure_inbound_allowed(spare_part: SparePart) -> None:
    """停用备件拒绝入库/上架（出库清库存不受限）"""
    if not spare_part.is_active:
        raise AppException(
            message=f"备件「{spare_part.name}」已停用，请先启用再入库"
        )


async def inbound_stock(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: StockInboundRequest,
    ctx: EquipmentAccessContext | None = None,
) -> SparePartStock:
    """入库"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if ctx:
        await verify_write_ownership(ctx, spare_part, "department_id", "department_id")
    _ensure_inbound_allowed(spare_part)

    stock = await repo.update_stock_qty(db, spare_part_id, data.quantity)
    if not stock:
        raise NotFoundException("库存记录", str(spare_part_id))

    if data.warehouse_location is not None:
        stock.warehouse_location = data.warehouse_location

    await repo.create_transaction(
        db,
        {
            "spare_part_id": spare_part_id,
            "transaction_type": "入库",
            "quantity": data.quantity,
            "remark": data.remark,
            "created_by": ctx.user.id if ctx else None,
        },
    )

    await db.flush()
    # 重新查询：flush 后服务端生成列过期，原对象直接序列化会 MissingGreenlet
    return cast(SparePartStock, await repo.get_stock_by_spare_part_id(db, spare_part_id))


async def outbound_stock(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: StockOutboundRequest,
    ctx: EquipmentAccessContext | None = None,
) -> SparePartStock:
    """出库（手动领用/报废；工单领料走 work_order.consume_materials）"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if ctx:
        await verify_write_ownership(ctx, spare_part, "department_id", "department_id")

    # 加锁读取：校验与扣减必须在同一行锁内，否则并发出库会双双通过校验后互相覆盖
    stock = await get_stock_by_spare_part_id(db, spare_part_id, for_update=True)

    if stock.current_qty < data.quantity:
        raise AppException(
            message=f"库存不足，当前库存 {stock.current_qty}，出库数量 {data.quantity}"
        )

    stock = cast(SparePartStock, await repo.update_stock_qty(db, spare_part_id, -data.quantity))
    if not stock:
        raise NotFoundException("库存记录", str(spare_part_id))

    await repo.create_transaction(
        db,
        {
            "spare_part_id": spare_part_id,
            "transaction_type": "出库",
            "quantity": -data.quantity,
            "remark": data.remark,
            "created_by": ctx.user.id if ctx else None,
        },
    )

    await db.flush()
    # 重新查询：flush 后服务端生成列过期，原对象直接序列化会 MissingGreenlet
    return cast(SparePartStock, await repo.get_stock_by_spare_part_id(db, spare_part_id))


async def adjust_stock(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: StockAdjustRequest,
    ctx: EquipmentAccessContext | None = None,
) -> SparePartStock:
    """盘点调整"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if ctx:
        await verify_write_ownership(ctx, spare_part, "department_id", "department_id")

    stock = await get_stock_by_spare_part_id(db, spare_part_id, for_update=True)

    diff = data.new_qty - stock.current_qty

    if diff != 0:
        stock = cast(SparePartStock, await repo.update_stock_qty(db, spare_part_id, diff))
        if not stock:
            raise NotFoundException("库存记录", str(spare_part_id))

        await repo.create_transaction(
            db,
            {
                "spare_part_id": spare_part_id,
                "transaction_type": "盘点调整",
                "quantity": diff,
                "remark": data.remark,
                "created_by": ctx.user.id if ctx else None,
            },
        )

    await db.flush()
    # 重新查询：flush 后服务端生成列过期，原对象直接序列化会 MissingGreenlet
    return cast(SparePartStock, await repo.get_stock_by_spare_part_id(db, spare_part_id))


async def get_stock_warnings(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
) -> list[StockWarningResponse]:
    """获取库存预警（受数据范围限制）"""
    warnings = await repo.get_stock_warnings(db, ctx)
    result = []
    for spare_part, stock in warnings:
        shortage = stock.safety_qty - stock.current_qty
        # 建议补货量：缺口按最小采购批量向上取整到整数倍
        batch = stock.min_order_qty if stock.min_order_qty > 0 else 1
        suggested = ((shortage + batch - 1) // batch) * batch
        result.append(
            StockWarningResponse(
                spare_part_id=spare_part.id,
                code=spare_part.code,
                name=spare_part.name,
                specification=spare_part.specification,
                unit=spare_part.unit,
                current_qty=stock.current_qty,
                min_qty=stock.safety_qty,
                shortage=shortage,
                min_order_qty=stock.min_order_qty,
                warehouse_location=stock.warehouse_location,
                suggested_qty=suggested,
            )
        )
    return result


def _ensure_read_access(spare_part: SparePart, ctx: EquipmentAccessContext) -> None:
    """读操作归属校验：防止跨部门按 ID 枚举（历史无归属数据放行）。"""
    if (
        not ctx.is_unrestricted
        and spare_part.department_id is not None
        and spare_part.department_id not in ctx.visible_department_ids
    ):
        raise ForbiddenException("无权查看其他部门的备件")


async def ensure_spare_part_readable(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> SparePart:
    """读入口统一的归属校验：不存在抛 404，越权抛 403"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    _ensure_read_access(spare_part, ctx)
    return spare_part


async def get_stock_with_access(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> SparePartStock:
    """按 ID 查库存，并做与详情一致的归属读校验"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    _ensure_read_access(spare_part, ctx)
    return await get_stock_by_spare_part_id(db, spare_part_id)


async def get_spare_part_detail(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> SparePart:
    """备件详情（带库存/关联设备数/待验收占用），保证与列表口径一致。"""
    spare_part = await repo.get_spare_part_with_stock_by_id(db, spare_part_id)
    if not spare_part:
        raise NotFoundException("备件", str(spare_part_id))
    _ensure_read_access(spare_part, ctx)

    reserved = await repo.get_reserved_quantities(db, [spare_part.id])
    spare_part.reserved_qty = reserved.get(spare_part.id, 0)  # type: ignore[attr-defined]
    if spare_part.department_id:
        names = await repo.get_department_names_by_ids(db, [spare_part.department_id])
        spare_part.department_name = names.get(spare_part.department_id, "")  # type: ignore[attr-defined]
    return spare_part


# ==================== Excel 导入 ====================

# 模板列（0-based）
SP_COL_CODE = 0          # A: 备件编码 *
SP_COL_NAME = 1           # B: 备件名称 *
SP_COL_SPECIFICATION = 2  # C: 规格型号
SP_COL_UNIT = 3           # D: 计量单位 *
SP_COL_CATEGORY = 4       # E: 备件分类
SP_COL_DEFAULT_SUPPLIER = 5  # F: 默认供应商
SP_COL_UNIT_PRICE = 6     # G: 参考单价（元）
SP_COL_QUANTITY = 7       # H: 初始库存数量（已有编码时为入库数量）
SP_COL_SAFETY_QTY = 8     # I: 安全库存

SP_TEMPLATE_HEADERS = [
    ("备件编码 *", 18),       # A
    ("备件名称 *", 24),       # B
    ("规格型号", 22),         # C
    ("计量单位 *", 12),       # D
    ("备件分类", 16),         # E
    ("默认供应商", 22),       # F
    ("参考单价（元）", 16),    # G
    ("初始库存数量", 14),     # H
    ("安全库存", 12),         # I
]


def _sp_cell_str(row: tuple[Any, ...], col: int) -> str | None:
    val = row[col] if col < len(row) else None
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _parse_decimal(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_import_qty(value: Any) -> int | None:
    """导入数量解析：空→0；整数或整值浮点→int；负数/非数字→None（非法）。"""
    if value is None:
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        qty: int = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        qty = int(value)
    else:
        s = str(value).strip()
        if not s:
            return 0
        try:
            f = float(s)
        except ValueError:
            return None
        if not f.is_integer():
            return None
        qty = int(f)
    return qty if qty >= 0 else None


IMPORT_MODE_ACCUMULATE = "accumulate"
IMPORT_MODE_OVERWRITE = "overwrite"
IMPORT_MODES = (IMPORT_MODE_ACCUMULATE, IMPORT_MODE_OVERWRITE)


def _is_blank_cell(value: Any) -> bool:
    """单元格是否留空（用于区分「留空=不改」与「填 0=清零」）"""
    return value is None or (isinstance(value, str) and not value.strip())


def generate_spare_part_template_bytes() -> io.BytesIO:
    """生成备件导入模板 Excel 文件的字节流"""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "备件管理"

    header_font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    example_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")

    ws.freeze_panes = "A3"

    # 表头（第1行）
    for i, (label, width) in enumerate(SP_TEMPLATE_HEADERS, start=1):
        cell = ws.cell(row=1, column=i, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(i)].width = width

    # 示例数据（第2行）
    examples = [
        "SP-001",
        "轴承密封圈",
        "Φ50×Φ34×7",
        "个",
        "机械密封",
        "XX密封件有限公司",
        "85.50",
        "50",
        "10",
    ]
    ws.row_dimensions[2].height = 28
    for i, example in enumerate(examples, start=1):
        cell = ws.cell(row=2, column=i, value=example)
        cell.fill = example_fill
        cell.border = thin_border
        cell.alignment = Alignment(vertical="center")
        cell.font = Font(name="微软雅黑", size=9, italic=True, color="808080")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


async def import_spare_parts_from_excel(
    db: AsyncSession,
    file_bytes: bytes,
    ctx: EquipmentAccessContext,
    mode: str = IMPORT_MODE_ACCUMULATE,
) -> EquipmentImportResponse:
    """从 Excel 文件字节流导入备件。

    mode 只影响「编码已存在」的行：
    - accumulate（默认）：表格数量累加进库存，仅刷新参考单价；
    - overwrite：表格填了的字段以表格为准（含库存数量、安全库存、单价等），
      留空的字段保持系统原值——重传同一份文件结果一致。
    """
    if mode not in IMPORT_MODES:
        raise ValueError(f"不支持的导入模式：{mode}")
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))

    if "备件管理" not in wb.sheetnames:
        raise ValueError("Excel 中缺少「备件管理」工作表，请使用模板文件")

    ws = wb["备件管理"]
    rows = list(ws.iter_rows(min_row=3, values_only=True))

    imported = 0
    skipped = 0
    errors: list[ImportRowError] = []
    warnings: list[ImportRowError] = []

    # ── 预加载系统数据（按编码索引现有备件，供重复编码累加入库） ──
    existing_result = await db.execute(
        select(SparePart).where(SparePart.is_deleted == False)  # noqa: E712
    )
    existing_by_code: dict[str, SparePart] = {
        sp.code: sp for sp in existing_result.scalars().all()
    }

    # 确定导入目标部门
    if ctx.visible_department_ids:
        default_dept_id = ctx.visible_department_ids[0]
    else:
        default_dept_id = None

    for row_num, row in enumerate(rows, start=3):
        try:
            values = [_sp_cell_str(row, c) for c in range(9)]
            if not any(values):
                continue

            code = values[SP_COL_CODE]
            name = values[SP_COL_NAME]
            unit = values[SP_COL_UNIT]

            # 必填校验
            missing = []
            if not code:
                missing.append("备件编码")
            if not name:
                missing.append("备件名称")
            if not unit:
                missing.append("计量单位")
            if missing:
                warnings.append(
                    ImportRowError(
                        row=row_num,
                        message=f"缺少必填项: {', '.join(missing)}，已跳过",
                    )
                )
                skipped += 1
                continue
            assert code is not None and name is not None and unit is not None

            # 解析数量/安全库存/单价
            qty_raw = row[SP_COL_QUANTITY] if SP_COL_QUANTITY < len(row) else None
            safety_raw = row[SP_COL_SAFETY_QTY] if SP_COL_SAFETY_QTY < len(row) else None
            qty = _parse_import_qty(qty_raw)
            safety_qty = _parse_import_qty(safety_raw)
            existing = existing_by_code.get(code)

            # 数值列校验：只拦真正会用到的列——累加模式下已有编码只用数量，
            # 安全库存填错不该把这行的数量一起丢掉（覆盖模式会写安全库存，仍需有效）。
            need_safety = existing is None or mode == IMPORT_MODE_OVERWRITE
            if qty is None or (need_safety and safety_qty is None):
                bad_field = "初始库存数量" if qty is None else "安全库存"
                bad_raw = qty_raw if qty is None else safety_raw
                warnings.append(
                    ImportRowError(
                        row=row_num,
                        message=f"{bad_field}「{bad_raw}」无效，需为非负整数，已跳过",
                    )
                )
                skipped += 1
                continue
            if not need_safety and safety_qty is None:
                warnings.append(
                    ImportRowError(
                        row=row_num,
                        message=f"安全库存「{safety_raw}」无效，累加入库不写该列，已忽略",
                    )
                )

            raw_price = row[SP_COL_UNIT_PRICE] if SP_COL_UNIT_PRICE < len(row) else None
            unit_price = _parse_decimal(raw_price)

            if existing is not None:
                # ── 已有编码 → 按模式累加入库 / 覆盖 ──
                try:
                    await verify_write_ownership(
                        ctx, existing, "department_id", "department_id"
                    )
                except ForbiddenException:
                    errors.append(
                        ImportRowError(
                            row=row_num,
                            message=f"备件编码「{code}」已存在，且无权对其所属部门入库",
                        )
                    )
                    skipped += 1
                    continue

                is_overwrite = mode == IMPORT_MODE_OVERWRITE
                if not is_overwrite and qty <= 0:
                    warnings.append(
                        ImportRowError(
                            row=row_num,
                            message=f"备件编码「{code}」已存在且数量为空/0，未入库",
                        )
                    )
                    skipped += 1
                    continue

                async with db.begin_nested():
                    if is_overwrite:
                        # 表格填了的字段以表格为准，留空的不动
                        for field, value in (
                            ("name", name),
                            ("specification", values[SP_COL_SPECIFICATION]),
                            ("unit", unit),
                            ("category", values[SP_COL_CATEGORY]),
                            ("default_supplier", values[SP_COL_DEFAULT_SUPPLIER]),
                        ):
                            if value is not None:
                                setattr(existing, field, value)
                        if unit_price is not None:
                            existing.unit_price = unit_price

                        locked = await repo.get_stock_by_spare_part_id(
                            db, existing.id, for_update=True
                        )
                        if not locked:
                            raise NotFoundException("库存记录", str(existing.id))
                        if not _is_blank_cell(safety_raw):
                            assert safety_qty is not None  # need_safety 时非法值已拦行
                            locked.safety_qty = safety_qty
                        if not _is_blank_cell(qty_raw):
                            diff = qty - locked.current_qty
                            if diff:
                                locked.current_qty = qty
                                await repo.create_transaction(
                                    db,
                                    {
                                        "spare_part_id": existing.id,
                                        "transaction_type": "盘点调整",
                                        "quantity": diff,
                                        "remark": "Excel导入覆盖",
                                        "created_by": ctx.user.id if ctx else None,
                                    },
                                )
                        await db.flush()
                    else:
                        # 累加：表数量入账 + 刷新参考单价
                        locked = await repo.update_stock_qty(db, existing.id, qty)
                        if not locked:
                            raise NotFoundException("库存记录", str(existing.id))
                        if unit_price is not None:
                            existing.unit_price = unit_price
                        await repo.create_transaction(
                            db,
                            {
                                "spare_part_id": existing.id,
                                "transaction_type": "入库",
                                "quantity": qty,
                                "remark": "Excel导入入库",
                                "created_by": ctx.user.id if ctx else None,
                            },
                        )
                        await db.flush()

                imported += 1
                continue

            # ── 新编码建档 ──
            # 部门必须可确定（超管也不例外），否则产出无归属备件
            department_id = default_dept_id
            if not department_id:
                errors.append(
                    ImportRowError(
                        row=row_num,
                        message="无法确定归属部门，导入失败",
                    )
                )
                skipped += 1
                continue

            # 创建备件（使用 SAVEPOINT 隔离每行）
            async with db.begin_nested():
                spare_part = SparePart(
                    code=code,
                    name=name,
                    specification=values[SP_COL_SPECIFICATION],
                    unit=unit,
                    category=values[SP_COL_CATEGORY],
                    default_supplier=values[SP_COL_DEFAULT_SUPPLIER],
                    unit_price=unit_price,
                    is_active=True,
                    department_id=department_id,
                    created_by=ctx.user.id if ctx else None,
                    updated_by=ctx.user.id if ctx else None,
                )
                db.add(spare_part)
                await db.flush()

                # 创建库存记录（带初始数量与安全库存）
                db.add(SparePartStock(
                    spare_part_id=spare_part.id,
                    current_qty=qty,
                    safety_qty=safety_qty,
                ))
                await db.flush()

                # 数量 > 0 时记录初始库存入库流水
                if qty > 0:
                    await repo.create_transaction(
                        db,
                        {
                            "spare_part_id": spare_part.id,
                            "transaction_type": "入库",
                            "quantity": qty,
                            "remark": "Excel导入初始库存",
                            "created_by": ctx.user.id if ctx else None,
                        },
                    )

            existing_by_code[code] = spare_part
            imported += 1

        except Exception as e:
            errors.append(
                ImportRowError(
                    row=row_num,
                    message=f"导入异常: {e}",
                )
            )
            skipped += 1
            logger.warning("备件导入行 %d 失败: %s", row_num, e)

    return EquipmentImportResponse(
        imported=imported,
        skipped=skipped,
        errors=errors,
        warnings=warnings,
    )
