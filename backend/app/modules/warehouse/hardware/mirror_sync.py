"""五金库物资目录镜像同步器（平台→Bitable 单向，2026-11-17 T1）。

镜像表「五金库物资目录（平台镜像·单向）」（领/退料审批表单的引用数据源）：
平台 hardware_materials 为唯一权威，本模块把平台态单向刷到 Bitable——
员工在审批表单里选到的永远是平台在册物资 + 近实时库存三值。

同步范围 = 在册共用类（is_deleted=false AND active AND managed_class=stocked，
与 service.list_stock_rows 缺省口径一致）：direct 类不占库存、不经领料表单，
不进镜像。镜像行锚点 = 「平台ID」列（UUID 文本）；平台行软删/停用后镜像行
由全量对账删除（表单不再可选）。

三值口径 = service.list_stock_rows：库存量=accepted 批次 remaining 合计、
预扣量=RESERVING 单 need_qty 合计、可领量=在手−预扣（复用同两个子查询，
防两处口径漂移）。类别为镜像表单选（7 类），平台值域已核实与选项一致。

触发三路：
- 物资增/改钩子（service.create_material_manual / update_material）→ 即时
  best-effort 单行 upsert（失败只记日志，不阻断管理端操作）；
- 库存变动钩子（入账/预扣/释放/发料/盘点/退库验收）→ mark_stock_dirty 登记，
  由定时任务批量刷三值（防高频入库逐行打 Bitable）；
- 定时全量对账兜底 warehouse.hardware_mirror_reconcile（30 分钟）：先清
  dirty 队列再全量 diff（补建/更正/删孤儿），事件丢失与漂移最终一致。

幂等：平台ID→record_id 映射缓存（进程内，list_all_records 拉全表构建）；
重复 upsert 写同值无副作用。测试全部 mock 本模块导入的平台 bitable 函数，
不打真飞书。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.bitable_cells import unwrap

logger = logging.getLogger(__name__)

# 镜像表列（2026-11-17 list_fields 实测字段名；2026-11-25 清单翻新增「位号」）
F_NAME = "物资名称"
F_PLATFORM_ID = "平台ID"
F_SPEC = "规格型号"
F_UNIT = "计量单位"
F_CATEGORY = "类别"
F_ON_HAND = "库存量"
F_RESERVED = "预扣量"
F_AVAILABLE = "可领量"
F_CODE = "编码"
F_LOCATION_NO = "位号"
# 位号列位（文本类型）；表里缺列时由 ensure_location_no_field 补建
FIELD_TYPE_TEXT = 1

ZERO = Decimal("0")

# 库存变动钩子登记的待刷三值物料（进程内；定时任务批量清空）
_pending_stock_ids: set[str] = set()

# 平台ID → record_id 映射缓存（进程内；None=未加载，出错置失效重拉）
_record_map: dict[str, str] | None = None


def _mirror_target() -> tuple[str, str] | None:
    """镜像表坐标（base, table）；任一未配置返回 None（同步自空转）。"""
    s = get_settings()
    base = str(getattr(s, "HARDWARE_MIRROR_BASE_TOKEN", "") or "").strip()
    table = str(getattr(s, "HARDWARE_MIRROR_TABLE_ID", "") or "").strip()
    return (base, table) if base and table else None


def _credentials() -> tuple[str | None, str | None]:
    """仓储应用凭证（镜像表由仓储应用创建，许康福已授 full_access）。"""
    s = get_settings()
    return s.WAREHOUSE_FEISHU_APP_ID or None, s.WAREHOUSE_FEISHU_APP_SECRET or None


def invalidate_record_map() -> None:
    """失效映射缓存（测试隔离用；下轮同步重拉全表）。"""
    global _record_map
    _record_map = None


def mark_stock_dirty(*material_ids: UUID | str) -> None:
    """库存变动钩子：登记待刷三值的物料（service/stocktake 各动账点调用）。"""
    for mid in material_ids:
        _pending_stock_ids.add(str(mid))


def take_dirty_ids() -> set[str]:
    """取走并清空 dirty 集合（定时任务批量刷新）。"""
    ids = set(_pending_stock_ids)
    _pending_stock_ids.clear()
    return ids


def build_material_fields(
    material: Any, on_hand: Decimal, reserved: Decimal
) -> dict[str, Any]:
    """平台行 → 镜像 fields dict（纯函数，测试直接断言）。

    编码列空值不写键（留空语义与静态快照一致；引用控件「被引用字段空值→
    该记录检索不到」，表单引用字段不勾编码即可兼容无码物资）；
    位号是普通文本列，空值写空串（无引用控件检索问题）。
    """
    available = (on_hand or ZERO) - (reserved or ZERO)
    fields: dict[str, Any] = {
        F_NAME: material.name,
        F_PLATFORM_ID: str(material.id),
        F_SPEC: material.spec or "",
        F_UNIT: material.unit or "",
        F_CATEGORY: material.category or "",
        F_ON_HAND: float(on_hand or ZERO),
        F_RESERVED: float(reserved or ZERO),
        F_AVAILABLE: float(available),
        F_LOCATION_NO: getattr(material, "location_no", None) or "",
    }
    if material.code:
        fields[F_CODE] = material.code
    return fields


async def ensure_location_no_field() -> bool:
    """镜像表缺「位号」列时补建（幂等；列已存在/建成功=True，未配置镜像=False）。

    镜像表由仓储应用创建且许康福已授 full_access，可 API 加列（2026-11-25
    清单翻新配套）。翻新脚本/运维在首次同步前调用一次即可。
    """
    target = _mirror_target()
    if target is None:
        return False
    base, table = target
    app_id, app_secret = _credentials()
    if not (app_id and app_secret):
        return False
    from app.platform.integrations.feishu.bitable import create_field, list_fields

    existing = await list_fields(
        base, table, app_id=app_id, app_secret=app_secret
    )
    if any(f.get("field_name") == F_LOCATION_NO for f in existing):
        return True
    field = await create_field(
        base, table, F_LOCATION_NO, FIELD_TYPE_TEXT,
        app_id=app_id, app_secret=app_secret,
    )
    logger.info("镜像表补建「位号」列: %s", field.get("field_id") or "失败")
    return bool(field)


def build_stock_fields(on_hand: Decimal, reserved: Decimal) -> dict[str, Any]:
    """三值 fields dict（库存变动批量刷新只 PATCH 这三列）。"""
    available = (on_hand or ZERO) - (reserved or ZERO)
    return {
        F_ON_HAND: float(on_hand or ZERO),
        F_RESERVED: float(reserved or ZERO),
        F_AVAILABLE: float(available),
    }


async def _load_record_map(db: AsyncSession | None = None) -> dict[str, str]:
    """平台ID → record_id（缓存；缺省拉全表——全量对账同源数据）。"""
    global _record_map
    if _record_map is not None:
        return _record_map
    from app.platform.integrations.feishu.bitable import list_all_records

    target = _mirror_target()
    if target is None:
        return {}
    base, table = target
    app_id, app_secret = _credentials()
    records = await list_all_records(
        base, table, app_id=app_id, app_secret=app_secret
    )
    mapping: dict[str, str] = {}
    for rec in records:
        pid = str(unwrap((rec.get("fields") or {}).get(F_PLATFORM_ID)) or "").strip()
        if pid:
            mapping[pid] = str(rec.get("record_id") or "")
    _record_map = mapping
    return mapping


async def _stock_values(
    db: AsyncSession, material_ids: list[str]
) -> dict[str, tuple[Decimal, Decimal]]:
    """批量三值（口径=list_stock_rows：复用 service 的 on_hand/reserved 子查询）。

    非 UUID 锚点（镜像缓存混入的孤儿/脏值）跳过——调用方按缺行处理。
    """
    from app.modules.warehouse.hardware.models import HardwareMaterial
    from app.modules.warehouse.hardware.service import (
        _on_hand_subquery,
        _reserved_subquery,
    )

    ids: list[UUID] = []
    for mid in material_ids:
        try:
            ids.append(UUID(mid))
        except (ValueError, AttributeError, TypeError):
            continue
    if not ids:
        return {}
    on_hand = _on_hand_subquery()
    reserved = _reserved_subquery()
    rows = (
        await db.execute(
            select(
                HardwareMaterial.id,
                func.coalesce(on_hand.c.on_hand, ZERO),
                func.coalesce(reserved.c.reserved, ZERO),
            )
            .outerjoin(on_hand, on_hand.c.material_id == HardwareMaterial.id)
            .outerjoin(reserved, reserved.c.material_id == HardwareMaterial.id)
            .where(HardwareMaterial.id.in_(ids))
        )
    ).all()
    return {str(mid): (on or ZERO, res or ZERO) for mid, on, res in rows}


async def _write(
    record_id: str | None, fields: dict[str, Any], *, platform_id: str
) -> str:
    """按锚点 upsert 一行（record_id 空=新建），返回落位 record_id。"""
    from app.platform.integrations.feishu.bitable import (
        batch_create_records,
        update_record,
    )

    target = _mirror_target()
    if target is None:
        return ""
    base, table = target
    app_id, app_secret = _credentials()
    if record_id:
        await update_record(
            base, table, record_id, fields, app_id=app_id, app_secret=app_secret
        )
        return record_id
    created = await batch_create_records(
        base, table, [fields], app_id=app_id, app_secret=app_secret
    )
    if created:
        _cache_upsert(platform_id, created[0])
    return created[0] if created else ""


def _cache_upsert(platform_id: str, record_id: str) -> None:
    """新建行回填映射缓存（缓存未加载时跳过——下轮全量拉表自然对齐）。"""
    if _record_map is not None:
        _record_map[platform_id] = record_id


async def sync_material(db: AsyncSession, material_id: UUID | str) -> str:
    """单行 upsert（物资增/改钩子即时路径；返回 record_id，空=未配置自空转）。"""
    from app.modules.warehouse.hardware.models import HardwareMaterial

    material = await db.get(HardwareMaterial, UUID(str(material_id)))
    if material is None or material.is_deleted:
        return ""
    mapping = await _load_record_map()
    values = await _stock_values(db, [str(material.id)])
    on, res = values.get(str(material.id), (ZERO, ZERO))
    return await _write(
        mapping.get(str(material.id)),
        build_material_fields(material, on, res),
        platform_id=str(material.id),
    )


async def refresh_stock_values(db: AsyncSession, material_ids: list[str]) -> int:
    """批量刷三值（库存变动 dirty 队列路径）；镜像无该行则跳过（对账补建）。"""
    if not material_ids:
        return 0
    mapping = await _load_record_map()
    values = await _stock_values(db, material_ids)
    from app.platform.integrations.feishu.bitable import update_record

    target = _mirror_target()
    if target is None:
        return 0
    base, table = target
    app_id, app_secret = _credentials()
    touched = 0
    for mid in material_ids:
        record_id = mapping.get(mid)
        if not record_id or mid not in values:
            continue
        on, res = values[mid]
        await update_record(
            base,
            table,
            record_id,
            build_stock_fields(on, res),
            app_id=app_id,
            app_secret=app_secret,
        )
        touched += 1
    return touched


async def _platform_rows(db: AsyncSession) -> list[Any]:
    """平台在册共用类全集（镜像范围；测试可 monkeypatch 本函数圈定合成行）。"""
    from app.modules.warehouse.hardware.models import HardwareMaterial

    return list(
        (
            await db.execute(
                select(HardwareMaterial).where(
                    HardwareMaterial.is_deleted.is_(False),
                    HardwareMaterial.active.is_(True),
                    HardwareMaterial.managed_class == "stocked",
                )
            )
        ).scalars().all()
    )


async def reconcile_mirror(db: AsyncSession) -> dict[str, int]:
    """全量对账：补建缺失行 + 更正漂移行 + 删除孤儿行（幂等，30 分钟兜底）。

    孤儿行 = 镜像平台ID不在平台在册集合（软删/停用/direct 的行，表单不可选）。
    """
    from app.platform.integrations.feishu.bitable import (
        BitableAPIError,
        batch_create_records,
        delete_record,
        list_all_records,
        update_record,
    )

    target = _mirror_target()
    stats = {"created": 0, "updated": 0, "deleted": 0, "platform": 0, "mirror": 0}
    if target is None:
        return stats
    app_id, app_secret = _credentials()
    if not app_id or not app_secret:
        logger.warning("镜像同步自空转：仓储应用凭证未配置")
        return stats
    base, table = target

    rows = await _platform_rows(db)
    platform_ids = [str(m.id) for m in rows]
    stats["platform"] = len(rows)

    records = await list_all_records(
        base, table, app_id=app_id, app_secret=app_secret
    )
    stats["mirror"] = len(records)
    mirror_rows: dict[str, tuple[str, dict[str, Any]]] = {}
    for rec in records:
        fields = rec.get("fields") or {}
        pid = str(unwrap(fields.get(F_PLATFORM_ID)) or "").strip()
        if pid:
            mirror_rows[pid] = (str(rec.get("record_id") or ""), fields)

    values = await _stock_values(db, platform_ids)
    to_create: list[dict[str, Any]] = []
    for m in rows:
        pid = str(m.id)
        on, res = values.get(pid, (ZERO, ZERO))
        fields = build_material_fields(m, on, res)
        if pid not in mirror_rows:
            to_create.append(fields)
            continue
        record_id, current = mirror_rows[pid]
        if _fields_diff(current, fields):
            try:
                await update_record(
                    base, table, record_id, fields, app_id=app_id, app_secret=app_secret
                )
                stats["updated"] += 1
            except BitableAPIError as exc:
                if "1254043" not in str(exc):  # RecordIdNotFound
                    raise
                # 并发窗口：对账期间该行被外部删除（如另一实例同时在对账）——
                # 映射已失真，降级为新建（下轮全量对账收敛）
                to_create.append(fields)
                logger.warning("镜像行已被并发删除，转新建: pid=%s", pid)
    if to_create:
        created_ids = await batch_create_records(
            base, table, to_create, app_id=app_id, app_secret=app_secret
        )
        stats["created"] = len(created_ids)

    platform_set = set(platform_ids)
    for pid, (record_id, _fields) in mirror_rows.items():
        if pid not in platform_set:
            await delete_record(
                base, table, record_id, app_id=app_id, app_secret=app_secret
            )
            stats["deleted"] += 1

    invalidate_record_map()  # 下轮重拉（增删后缓存已失真）
    return stats


def _fields_diff(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    """镜像现行 fields vs 期望 fields（文本 unwrap 归一 + 数值 float 归一）。"""
    for key, want in expected.items():
        have = current.get(key)
        if isinstance(want, float):
            try:
                got = float(unwrap(have))
            except (TypeError, ValueError):
                got = None
            if got is None or abs(got - want) > 1e-9:
                return True
        else:
            if str(unwrap(have) or "").strip() != str(want).strip():
                return True
    # 编码列被外部清空的场景（期望无键、镜像有残值）不追删——空值语义留白
    return False


# ── service/stocktake 动账钩子（best-effort，绝不阻断主流程）──


def hook_material_upserted(db: AsyncSession, material_id: UUID | str) -> None:
    """物资增/改后即时同步（fire-and-forget：自管会话，失败只记日志）。

    独立会话避免读到请求事务未提交态——延迟一拍（create_task 调度在当前
    协程让出后），绝大多数场景请求已 commit；抢先场景由 30 分钟对账兜底。
    """
    import asyncio

    async def _run() -> None:
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                await sync_material(session, material_id)
        except Exception:  # noqa: BLE001 — 镜像失败不影响平台主数据操作
            logger.warning(
                "[镜像] 物资同步失败（对账兜底）: material_id=%s", material_id,
                exc_info=True,
            )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.warning("[镜像] 无事件循环，跳过即时同步: %s", material_id)
