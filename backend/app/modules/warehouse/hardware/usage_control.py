"""五金库月度用量管控表回填（部门×月份×物资，需求基线 vs 实际领用）。

Bitable「月度用量管控」表由 HARDWARE_USAGE_TABLE_ID 指定（Base 复用镜像
HARDWARE_MIRROR_BASE_TOKEN，凭证复用仓储应用）；表上三列公式（用量差值/
超出比例/比对结论）自动算，处置状态/备注是人工列——刷新永不触碰。

行生成规则（2026-11-18 拍板）：
- 月需求量 = 物资清单 monthly_demands 基线（五部门键域，material 侧权威）
- 实际用量 = 领用出库流水聚合：direction=outbound AND business_type IN
  (req_issue, urgent_issue)，退库不冲减（与全仓 USAGE_BIZ_TYPES 口径一致）
- 活跃行 = 需求>0 或 用量>0；行键 = 平台ID+统计月份+需求部门（幂等 upsert，
  行是事实记录不做删孤儿——区别于镜像表）
- movement.dept_name 是自由文本，按 _match_demand_dept 语义归一五部门桶；
  归不进落「其他部门」（计划外部门领用在表上可见而非丢弃）
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_cells import cell_number, unwrap

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

USAGE_BIZ_TYPES = ("req_issue", "urgent_issue")

# 用量管控表十列（2026-11-18 建列实测字段名；公式/人工列不在此列）
F_MONTH = "统计月份"
F_DEPT = "需求部门"
F_NAME = "物资名称"
F_SPEC = "规格型号"
F_UNIT = "计量单位"
F_CATEGORY = "类别"
F_LINK = "关联物资"
F_PLATFORM_ID = "平台ID"
F_DEMAND = "月需求量"
F_ACTUAL = "实际用量"

OTHER_DEPT = "其他部门"


def _usage_target() -> tuple[str, str] | None:
    """管控表坐标（base, table）；表未配置返回 None（同步自空转，默认关）。"""
    from app.core.config import get_settings

    s = get_settings()
    base = str(getattr(s, "HARDWARE_MIRROR_BASE_TOKEN", "") or "").strip()
    table = str(getattr(s, "HARDWARE_USAGE_TABLE_ID", "") or "").strip()
    return (base, table) if base and table else None


def month_key(month_start: datetime) -> str:
    """月初 → 统计月份选项值（YYYY-MM）。"""
    return f"{month_start.year:04d}-{month_start.month:02d}"


def month_starts(now: datetime, months_back: int) -> list[datetime]:
    """当月往前 months_back 个月的月初序列（含当月；CN_TZ 口径）。"""
    total = now.year * 12 + (now.month - 1)
    starts = []
    for k in range(months_back, -1, -1):
        y, m = divmod(total - k, 12)
        starts.append(datetime(y, m + 1, 1, tzinfo=CN_TZ))
    return starts


def next_month_start(month_start: datetime) -> datetime:
    total = month_start.year * 12 + month_start.month
    y, m = divmod(total, 12)
    return datetime(y, m + 1, 1, tzinfo=CN_TZ)


def normalize_dept(dept_name: str | None) -> str:
    """自由文本部门 → 五部门桶（完全匹配优先、互相包含兜底），归不进落其他部门。"""
    from app.modules.warehouse.hardware.models import DEMAND_DEPARTMENTS
    from app.modules.warehouse.hardware.service import _match_demand_dept

    dept = (dept_name or "").strip()
    if not dept:
        return OTHER_DEPT
    matched = _match_demand_dept(dict.fromkeys(DEMAND_DEPARTMENTS), dept)
    return matched if matched in DEMAND_DEPARTMENTS else OTHER_DEPT


async def aggregate_monthly_usage(
    db: AsyncSession, month_start: datetime
) -> dict[tuple[str, str], float]:
    """某月领用出库聚合 → {(material_id, 归一部门桶): 量}。

    口径 = USAGE_BIZ_TYPES（req_issue+urgent_issue）；退库 return_in 是
    inbound 不在此口径（现行用量不冲减）。dept_name 原值分组后 Python 归一
    合桶（自由文本 → 五桶+其他部门）。
    """
    from app.modules.warehouse.hardware.models import HardwareMovement

    end = next_month_start(month_start)
    rows = (
        await db.execute(
            select(
                HardwareMovement.material_id,
                HardwareMovement.dept_name,
                func.sum(HardwareMovement.quantity),
            ).where(
                HardwareMovement.direction == "outbound",
                HardwareMovement.business_type.in_(USAGE_BIZ_TYPES),
                HardwareMovement.is_deleted.is_(False),
                HardwareMovement.material_id.isnot(None),
                HardwareMovement.occurred_at >= month_start,
                HardwareMovement.occurred_at < end,
            )
            .group_by(HardwareMovement.material_id, HardwareMovement.dept_name)
        )
    ).all()
    usage: dict[tuple[str, str], float] = {}
    for material_id, dept_name, qty in rows:
        key = (str(material_id), normalize_dept(dept_name))
        usage[key] = usage.get(key, 0.0) + float(qty or ZERO)
    return usage


def build_usage_rows(
    materials: list, usage: dict[tuple[str, str], float], month_start: datetime,
    record_map: dict[str, str],
) -> list[dict[str, Any]]:
    """基线+用量 → 行 fields 列表（纯函数，测试直接断言）。

    - 需求侧行只取在册物资（active）；用量侧物资可能已停用/删除，历史用量
      照常成行（material 对象缺位时快照列留空）
    - 关联物资列按镜像平台ID映射带出；未映射（镜像未配置/新物资）不写键
    """
    by_id = {str(m.id): m for m in materials}
    demand: dict[tuple[str, str], float] = {}
    for m in materials:
        if not getattr(m, "active", True):
            continue  # 停用物资不再生成纯基线行
        for dept, qty in (m.monthly_demands or {}).items():
            value = cell_number(qty) or 0
            if value > 0:
                demand[(str(m.id), str(dept))] = value

    rows: list[dict[str, Any]] = []
    for key in sorted(set(demand) | set(usage)):
        mid, dept = key
        material = by_id.get(mid)
        fields: dict[str, Any] = {
            F_PLATFORM_ID: mid,
            F_MONTH: month_key(month_start),
            F_DEPT: dept,
            F_NAME: material.name if material else "",
            F_SPEC: (material.spec if material else "") or "",
            F_UNIT: (material.unit if material else "") or "",
            F_CATEGORY: material.category if material else "",
            F_DEMAND: float(demand.get(key, 0.0)),
            F_ACTUAL: float(usage.get(key, 0.0)),
        }
        link_id = record_map.get(mid)
        if link_id:
            fields[F_LINK] = [link_id]
        rows.append(fields)
    return rows


async def _ensure_month_options(
    base: str, table: str, months: list[str], kw: dict
) -> None:
    """统计月份单选缺项补选项（不依赖飞书记录写入自动加选项的未验行为）。"""
    from app.platform.integrations.feishu.bitable import (
        BITABLE_BASE,
        _request,
        list_fields,
    )

    fields = await list_fields(base, table, **kw)
    field = next((f for f in fields if f.get("field_name") == F_MONTH), None)
    if field is None:
        return
    options = [
        o.get("name") for o in ((field.get("property") or {}).get("options") or [])
        if isinstance(o, dict)
    ]
    missing = [m for m in months if m not in options]
    if not missing:
        return
    await _request(
        "PUT",
        f"{BITABLE_BASE}/apps/{base}/tables/{table}/fields/{field['field_id']}",
        json_body={
            "field_name": F_MONTH,
            "type": 3,
            "property": {
                "options": [{"name": o} for o in (options + missing)]
            },
        },
        **kw,
    )


def _link_ids(value: Any) -> list[str]:
    """关联列单元格 → record_id 列表（写入 [id] / 读回形态三样兼容）。

    真机读回实测（2026-11-18）：[{"record_ids": [...], "table_id", "text"}]
    ——复数 record_ids 嵌在分段 dict 里；另兼容裸 dict 与裸 id 列表。
    """
    if value is None:
        return []

    def _from_dict(obj: dict) -> list[str]:
        for key in ("link_record_ids", "record_ids"):
            ids = obj.get(key)
            if isinstance(ids, list):
                return [str(x) for x in ids if x]
        rid = obj.get("record_id") or obj.get("id")
        return [str(rid)] if rid else []

    if isinstance(value, dict):
        return _from_dict(value)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                out.extend(_from_dict(item))
            elif item:
                out.append(str(item))
        return out
    return []


def _usage_rows_diff(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    """行漂移判定：镜像 _fields_diff 语义 + 关联列按 record_id 集合比。

    读回形态（link_record_ids dict，unwrap 会取到显示文本）与写入形态
    （[record_id]）不可直接 str() 比——镜像表无关联列，此为其扩展。
    """
    from app.modules.warehouse.hardware import mirror_sync

    link_expected = expected.get(F_LINK)
    rest = {k: v for k, v in expected.items() if k != F_LINK}
    if mirror_sync._fields_diff(current, rest):
        return True
    if link_expected is None:
        return False  # 未映射不写键——现状不追删（同镜像编码列语义）
    return sorted(_link_ids(current.get(F_LINK))) != sorted(link_expected)


async def _load_materials(db: AsyncSession, involved: set[UUID]) -> list:
    """基线物资全集：在册（active）∪ 用量涉及的（含停用，历史用量照常成行）。"""
    from app.modules.warehouse.hardware.models import HardwareMaterial

    return list(
        (
            await db.execute(
                select(HardwareMaterial).where(
                    (HardwareMaterial.active.is_(True))
                    | (HardwareMaterial.id.in_(involved))
                )
            )
        )
        .scalars()
        .all()
    )


async def sync_usage_rows(
    db: AsyncSession, *, months_back: int = 1, now: datetime | None = None
) -> dict[str, Any]:
    """当月往前 months_back 个月的管控行 upsert（默认上月+当月）。

    未配置 HARDWARE_USAGE_TABLE_ID 自空转返回 enabled=False。只写维度/
    快照/两数值列，处置状态/备注人工列永不触碰；无漂移行跳过。
    """
    from app.modules.warehouse.hardware import mirror_sync
    from app.platform.integrations.feishu.bitable import (
        batch_create_records,
        list_all_records,
        update_record,
    )

    target = _usage_target()
    if target is None:
        return {"enabled": False}
    base, table = target
    app_id, app_secret = mirror_sync._credentials()
    kw = {"app_id": app_id, "app_secret": app_secret}
    now = now or datetime.now(CN_TZ)
    starts = month_starts(now, months_back)

    await _ensure_month_options(
        base, table, [month_key(s) for s in starts], kw
    )

    # 关联物资列的平台ID映射与镜像共用（同 Base 同目录表）
    record_map = await mirror_sync._load_record_map(db)

    created = updated = 0
    for month_start in starts:
        usage = await aggregate_monthly_usage(db, month_start)
        involved = {UUID(mid) for mid, _ in usage}
        materials = await _load_materials(db, involved)
        expected_rows = build_usage_rows(materials, usage, month_start, record_map)

        existing: dict[tuple[str, str, str], str] = {}
        current: dict[str, dict] = {}
        for rec in await list_all_records(base, table, **kw):
            fields = rec.get("fields") or {}
            anchor = (
                str(unwrap(fields.get(F_PLATFORM_ID)) or "").strip(),
                str(unwrap(fields.get(F_MONTH)) or "").strip(),
                str(unwrap(fields.get(F_DEPT)) or "").strip(),
            )
            if all(anchor):
                existing[anchor] = str(rec.get("record_id") or "")
                current[anchor] = fields

        month_created = month_updated = 0
        to_create: list[dict] = []
        for fields in expected_rows:
            anchor = (fields[F_PLATFORM_ID], fields[F_MONTH], fields[F_DEPT])
            record_id = existing.get(anchor)
            if record_id is None:
                to_create.append(fields)
                continue
            if _usage_rows_diff(current.get(anchor) or {}, fields):
                await update_record(base, table, record_id, fields, **kw)
                month_updated += 1
        if to_create:
            await batch_create_records(base, table, to_create, **kw)
            month_created = len(to_create)
        created += month_created
        updated += month_updated
        logger.info(
            "[用量管控] %s 行=%d 建=%d 改=%d",
            month_key(month_start), len(expected_rows), month_created, month_updated,
        )
    return {"enabled": True, "months": len(starts), "rows": created + updated,
            "created": created, "updated": updated}


async def run_usage_sync() -> None:
    """定时包装：独立会话（每日 06:00 刷当月+上月，月初自然定格上月）。"""
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        stats = await sync_usage_rows(session)
        await session.commit()
    if stats.get("enabled") and (stats.get("created") or stats.get("updated")):
        logger.info("五金月度用量管控回填: %s", stats)
