"""库存日快照服务：驾驶舱环比/趋势的数据底座。

内存安全（兄弟仓宁夏实测教训：单会话累积 ORM 行对象曾把 2C4G 进程推到 OOM）：
- 聚合一次取回（每物料一行，数量级 = 物料数，不加载 ORM 实体）；
- 落库逐物料使用独立短会话，分批 gc，避免单会话 identity map 膨胀；
- FIXED_TIME 语义是"当天 00:00 已过即触发"，重启会误触发，
  因此定时触发侧限定凌晨窗口（00:00-06:00）执行。
"""

from __future__ import annotations

import gc
import logging
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.warehouse.models import WarehouseStock, WarehouseStockDailySnapshot

logger = logging.getLogger(__name__)

# 快照执行窗口（北京时间，不含结束时刻）
_SNAPSHOT_WINDOW_START_HOUR = 0
_SNAPSHOT_WINDOW_END_HOUR = 6
# 每处理 N 个物料主动回收一次内存
_GC_EVERY_N_MATERIALS = 50

# 运行互斥标志：快照执行期间拒绝重入
_snapshot_running = False


def is_in_snapshot_window(now_cn: datetime) -> bool:
    """北京时间 now 是否处于快照执行窗口（00:00-06:00，含头不含尾）。"""
    return _SNAPSHOT_WINDOW_START_HOUR <= now_cn.hour < _SNAPSHOT_WINDOW_END_HOUR


async def build_stock_snapshot_rows(
    db: AsyncSession, snapshot_date: date
) -> list[dict[str, object]]:
    """聚合当日库存（仅未删除行），返回快照行 dict 列表（每物料一行）。"""
    stmt = (
        select(
            WarehouseStock.material_id,
            WarehouseStock.material_code,
            WarehouseStock.material_name,
            func.sum(WarehouseStock.quantity).label("total_quantity"),
            func.count().label("stock_rows"),
        )
        .where(WarehouseStock.is_deleted.is_(False))
        .group_by(
            WarehouseStock.material_id,
            WarehouseStock.material_code,
            WarehouseStock.material_name,
        )
    )
    result = await db.execute(stmt)
    return [
        {
            "snapshot_date": snapshot_date,
            "material_id": row.material_id,
            "material_code": row.material_code,
            "material_name": row.material_name,
            "total_quantity": row.total_quantity if row.total_quantity is not None else Decimal("0"),
            "stock_rows": int(row.stock_rows or 0),
        }
        for row in result.all()
    ]


async def upsert_snapshot_rows(db: AsyncSession, rows: list[dict[str, object]]) -> int:
    """幂等写入快照（同日同物料覆盖，未删除行部分唯一索引为仲裁索引）。"""
    for row in rows:
        stmt = pg_insert(WarehouseStockDailySnapshot).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["snapshot_date", "material_id"],
            index_where=text("is_deleted = false"),
            set_={
                "material_code": stmt.excluded.material_code,
                "material_name": stmt.excluded.material_name,
                "total_quantity": stmt.excluded.total_quantity,
                "stock_rows": stmt.excluded.stock_rows,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
    return len(rows)


async def run_stock_daily_snapshot(snapshot_date: date | None = None) -> int:
    """生成（或覆盖）指定业务日的库存快照，返回写入物料数。

    运行互斥：已有快照任务在跑时直接跳过（返回 0），不清理他人标志。
    显式传入 snapshot_date 供回补/测试使用，不受窗口限制。
    """
    global _snapshot_running
    if _snapshot_running:
        logger.info("warehouse stock snapshot already running, skip")
        return 0
    _snapshot_running = True
    try:
        target_date = snapshot_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        async with async_session_factory() as session:
            rows = await build_stock_snapshot_rows(session, target_date)

        written = 0
        for idx, row in enumerate(rows, start=1):
            async with async_session_factory() as session:
                await upsert_snapshot_rows(session, [row])
                await session.commit()
            written += 1
            if idx % _GC_EVERY_N_MATERIALS == 0:
                gc.collect()

        logger.info(
            "warehouse stock snapshot completed: date=%s materials=%d",
            target_date,
            written,
        )
        return written
    finally:
        _snapshot_running = False
