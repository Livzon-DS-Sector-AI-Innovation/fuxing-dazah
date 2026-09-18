"""先 Base 后镜像写路径 helper（V3.0 分期A Ticket 06，架构定案 2B）。

本地库存状态类写操作统一走本模块：**先写 Base（权威）→ 成功后本地事务写
（状态 + 流转日志）；Base 失败 → 整体失败，本地零变更**。

三态映射（质询 Round 1/2 定案，唯一事实源）：
    normal=合格 / quarantine=待检 / frozen=不合格
回写目标：material_receipt.上一状态（material_stock 的 QC 字段全为
lookup 不可写，见 bitable_schema 实测）。

记录定位：按库存行 batch_no 检索 material_receipt.物料批号（单选 select
过滤）。定位不到 = 本地镜像行无 Base 源记录，按 2B 不允许本地单方面改，
抛 BaseMirrorError（调用方决定逐条跳过或整单失败）。

**回写总开关**（``bitable_writeback_enabled`` 运行参数，默认 0=关）：
关闭时不触 Base——库存状态变更退化为本地直写（V3A 前行为）、确认门
停用（不建单、确认点击拒绝）。上线前置：与仓储部确认「上一状态」列
无自动化占用后在配置中心置 1。

调用方语义：
- expiry_freeze：逐条串行回写，失败条目跳过并记录，不回滚已成功条目；
- web_stock_status：单行严格失败（HTTP 502 + 明确报错，本地零变更）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_cells import cell_text
from app.modules.warehouse.models import WarehouseStock, WarehouseStockStatusLog

logger = logging.getLogger(__name__)

# 本地库存三态 → material_receipt.上一状态（单选）
STOCK_STATUS_TO_BASE: dict[str, str] = {
    "normal": "合格",
    "quarantine": "待检",
    "frozen": "不合格",
}


def bitable_writeback_enabled() -> bool:
    """多维表格回写总开关（runtime 配置 bitable_writeback_enabled，0/1）。

    读取异常一律按关闭处理（kill switch 语义：fail-safe off）。
    """
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    try:
        return int(runtime_store.get_value("bitable_writeback_enabled")) == 1
    except Exception:  # noqa: BLE001 — 开关读不到 = 不写 Base
        logger.warning("回写开关读取失败，按关闭处理", exc_info=True)
        return False


class BaseMirrorError(Exception):
    """Base 写失败/定位失败（本地零变更，由调用方决定后续）。"""


async def resolve_receipt_record_id(
    adapter: WarehouseBitableAdapter,
    *,
    batch_no: str,
    material_name: str | None = None,
) -> str | None:
    """按物料批号定位 material_receipt 记录；定位不到返回 None。

    同批号多条命中时优先物料名称完全一致的记录（同批号分次收货消歧），
    仍无法消歧取首条并告警。
    """
    if not batch_no:
        return None
    page = await adapter.search_records_page(
        "material_receipt",
        filter_json={
            "conjunction": "and",
            "conditions": [
                {"field_name": "物料批号", "operator": "is", "value": [batch_no]}
            ],
        },
        field_names=["物料批号", "物料名称"],
        limit=5,
    )
    records = page.get("records") or []
    if not records:
        return None
    if len(records) > 1:
        matched = None
        if material_name:
            for record in records:
                # 物料名称富文本分段/类型包裹由规范解析展开后精确比对
                name_text = cell_text((record.get("fields") or {}).get("物料名称"))
                if name_text.strip() == material_name.strip():
                    matched = record
                    break
        if matched is not None:
            return str(matched.get("record_id") or "")
        logger.warning(
            "物料批号 %r 在 Base 命中 %d 条记录且无法按名称消歧，取首条",
            batch_no, len(records),
        )
    return str(records[0].get("record_id") or "")


async def apply_stock_status_base_first(
    db: AsyncSession,
    stock: WarehouseStock,
    new_status: str,
    *,
    reason: str = "",
    operator_id: Any = None,
    adapter: WarehouseBitableAdapter | None = None,
) -> str | None:
    """先写 Base 上一状态，成功后本地写状态 + 日志；失败抛 BaseMirrorError。

    返回回写成功的 Base record_id；**总开关关闭时退化为本地直写**
    （不触 Base，返回 None）。本函数不 commit（由调用方 session 上下文
    统一提交/回滚）；开关开启时保证「Base 成功前本地零变更」。
    """
    base_value = STOCK_STATUS_TO_BASE.get(new_status)
    if base_value is None:
        raise BaseMirrorError(f"未知的库存状态: {new_status!r}")

    if not bitable_writeback_enabled():
        logger.info(
            "回写开关关闭，库存状态变更走本地直写: batch_no=%s -> %s",
            stock.batch_no, new_status,
        )
        _write_local_status(db, stock, new_status, reason=reason, operator_id=operator_id)
        return None

    adapter = adapter or WarehouseBitableAdapter()
    record_id = await resolve_receipt_record_id(
        adapter, batch_no=stock.batch_no or "", material_name=stock.material_name
    )
    if not record_id:
        raise BaseMirrorError(
            f"物料批号 {stock.batch_no!r} 在 Base（material_receipt）未找到对应记录，"
            f"按「先 Base 后镜像」约定拒绝本地单方面变更"
        )

    try:
        await adapter.update_record("material_receipt", record_id, {"上一状态": base_value})
    except Exception as exc:
        raise BaseMirrorError(
            f"Base 写入失败（material_receipt.上一状态={base_value}）: {exc}"
        ) from exc

    # Base 成功 → 本地镜像写（状态 + 日志）
    _write_local_status(db, stock, new_status, reason=reason, operator_id=operator_id)
    return record_id


def _write_local_status(
    db: AsyncSession,
    stock: WarehouseStock,
    new_status: str,
    *,
    reason: str,
    operator_id: Any,
) -> None:
    """本地状态 + 流转日志写（Base 成功后 / 开关关闭时的本地直写共用）。"""
    old_status = stock.status
    stock.status = new_status
    db.add(
        WarehouseStockStatusLog(
            stock_id=stock.id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            operator_id=operator_id,
        )
    )
