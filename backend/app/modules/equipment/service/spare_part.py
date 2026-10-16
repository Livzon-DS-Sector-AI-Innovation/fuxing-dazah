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
    StockWarningResponse,
)
from app.modules.equipment.service.data_scope import verify_write_ownership

logger = logging.getLogger(__name__)


async def create_spare_part(
    db: AsyncSession,
    data: SparePartCreate,
    ctx: EquipmentAccessContext,
) -> SparePart:
    """创建备件，自动创建库存记录。department_id 自动从用户部门获取。"""
    if await repo.exists_spare_part_by_code(db, data.code):
        raise DuplicateException("备件编码", data.code)

    create_data = data.model_dump()
    # 自动归属用户部门
    if not create_data.get("department_id") and ctx.visible_department_ids:
        create_data["department_id"] = ctx.visible_department_ids[0]

    spare_part = await repo.create_spare_part(db, create_data)

    await repo.create_stock(db, {"spare_part_id": spare_part.id})

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
        department_id=department_id,
        page=page,
        page_size=page_size,
    )
    # 批量填充 department_name（缓存去重，避免 API 层直接调用 repo）
    dept_cache: dict[uuid.UUID, str] = {}
    for sp in spare_parts:
        if sp.department_id:
            if sp.department_id not in dept_cache:
                dept_info = await repo.get_department_info(db, sp.department_id)
                dept_cache[sp.department_id] = dept_info["name"] if dept_info else ""
            sp.department_name = dept_cache.get(sp.department_id, "")  # type: ignore[attr-defined]
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

    if "code" in update_data:
        code_exists = await repo.exists_spare_part_by_code(
            db, update_data["code"], exclude_id=spare_part_id
        )
        if code_exists:
            raise DuplicateException("备件编码", update_data["code"])

    result = await repo.update_spare_part(db, spare_part_id, update_data)
    if not result:
        raise NotFoundException("备件", str(spare_part_id))
    return result


async def delete_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> bool:
    """删除备件"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    await verify_write_ownership(ctx, spare_part, "department_id", "department_id")
    return await repo.delete_spare_part(db, spare_part_id)


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
        },
    )

    await db.flush()
    await db.refresh(stock)
    return stock


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
        },
    )

    await db.flush()
    await db.refresh(stock)
    return stock


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
            },
        )

    await db.flush()
    await db.refresh(stock)
    return stock


async def get_stock_warnings(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
) -> list[StockWarningResponse]:
    """获取库存预警（受数据范围限制）"""
    warnings = await repo.get_stock_warnings(db, ctx)
    result = []
    for spare_part, stock in warnings:
        result.append(
            StockWarningResponse(
                spare_part_id=spare_part.id,
                code=spare_part.code,
                name=spare_part.name,
                specification=spare_part.specification,
                unit=spare_part.unit,
                current_qty=stock.current_qty,
                min_qty=stock.safety_qty,
                shortage=stock.safety_qty - stock.current_qty,
            )
        )
    return result


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
                            },
                        )
                        await db.flush()

                imported += 1
                continue

            # ── 新编码建档 ──
            # 部门权限校验
            department_id = default_dept_id
            if not ctx.is_unrestricted:
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
