"""危险源辨识（hazard_id）**Web 台账**直读 — 直读看板批次 4，2026-10-13。

与既有 ``hazard_id_direct`` 包（Agent 查询，批次四-2）分工：本模块服务
REST 台账页面（列表/工作流统计/台账统计，字段=镜像模型全量），映射复用
``map_bitable_to_model``（与事件镜像同一纯函数）；Agent 工具维持其包不动。
**AI 脚本工作流保持镜像事件驱动不动**（advance/writeback 链路）。

- 部门按提交人批量反查 identity.users（每次缓存刷新一次查询；同名不消歧
  置空，与镜像策略一致）；
- created_at 用 Bitable 系统字段「创建时间」（镜像为平台落库时间，排序
  口径受控偏差：同一业务行的相对顺序通常一致）；
- 过滤/统计口径逐字对齐 ``repository/core.py`` 的镜像查询。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast

from app.modules.safety.service.bitable_direct import gates
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.hazard_identification_bitable import (
    _person_name,
    map_bitable_to_model,
)

_cached: dict[str, Any] = {"views": [], "ts": 0.0}

_REVIEW_STATUS_KEYS = tuple(f"script{i}_review_status" for i in range(1, 8))


def direct_enabled() -> bool:
    """台账查询面直读开关（SAFETY_HAZARD_ID_DIRECT_ENABLED，默认关）。"""
    return gates.direct_enabled(gates.DOMAIN_HAZARD_ID)


class HazardIdRowView:
    """辨识表行的内存视图（mapped 为镜像字段 dict）。"""

    def __init__(
        self, record_id: str, created_at: datetime | None, mapped: dict[str, Any]
    ) -> None:
        self.record_id = record_id
        self.created_at = created_at
        self.mapped = mapped

    @property
    def id(self) -> str:
        return self.record_id

    def __getattr__(self, name: str) -> Any:
        # 只暴露 mapped 真实存在的键；缺失键抛 AttributeError 让 schema 默认值生效
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self.mapped:
            return self.mapped[name]
        raise AttributeError(name)


async def _resolve_departments(
    session: Any, records: list[dict[str, Any]]
) -> dict[str, str]:
    """提交人姓名 → 部门（一次批量查询；同名多人不消歧，剔除）。"""
    names: set[str] = set()
    for rec in records:
        submitter = _person_name((rec.get("fields") or {}).get("提交人员"))
        if submitter:
            names.add(submitter)
    if not names or session is None:
        return {}
    from sqlalchemy import select

    from app.platform.identity.models import User as IdentityUser

    rows = (
        await session.execute(
            select(IdentityUser.name, IdentityUser.department).where(
                IdentityUser.name.in_(names),
                IdentityUser.is_deleted == False,  # noqa: E712
            )
        )
    ).all()
    dept_map: dict[str, str] = {}
    name_counts: dict[str, int] = {}
    for name, dept in rows:
        name_counts[name] = name_counts.get(name, 0) + 1
        if dept:
            dept_map[name] = dept
    # 同名多人 → 无法消歧，剔除（镜像同策略）
    return {n: d for n, d in dept_map.items() if name_counts.get(n) == 1}


async def fetch_all(session: Any = None, *, strict: bool = False) -> list[HazardIdRowView]:
    """辨识表全量视图（TTL 缓存；部门批量反查每次刷新一次）。"""
    ttl = gates.int_env("SAFETY_HAZARD_ID_DIRECT_CACHE_TTL_SECONDS", 60, minimum=0)
    now = time.monotonic()
    if not strict and ttl > 0 and _cached["views"] and now - _cached["ts"] < ttl:
        return cast("list[HazardIdRowView]", _cached["views"])

    client = bd_reader.resolve_client("hazard_id", "identification")
    records = await client.list_all_records(
        automatic_fields=True, page_size=500, strict=True,
    )
    dept_map = await _resolve_departments(session, records)
    views: list[HazardIdRowView] = []
    for rec in records:
        record_id = str(rec.get("record_id") or "")
        if not record_id:
            continue
        fields = _unwrap_formula_fields(rec.get("fields") or {})
        submitter = _person_name(fields.get("提交人员"))
        mapped = map_bitable_to_model(
            fields,
            feishu_record_id=record_id,
            resolve_department=(lambda n: dept_map.get(n)) if submitter else None,
        )
        created_ms = rec.get("created_time")
        created_at = (
            datetime.fromtimestamp(int(created_ms) / 1000, tz=UTC)
            if isinstance(created_ms, (int, float))
            else None
        )
        views.append(HazardIdRowView(record_id, created_at, mapped))
    if ttl > 0:
        _cached["views"] = views
        _cached["ts"] = now
    return views


def _unwrap_formula_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """search 返回的公式列是 ``{"type": N, "value": [...]}`` 包装形态
    （事件负载为裸值，mapper 只认裸值）——统一解包为普通列值。
    """
    out: dict[str, Any] = {}
    for key, val in fields.items():
        if isinstance(val, dict) and "value" in val and "type" in val:
            inner = val.get("value")
            if isinstance(inner, list):
                val = inner[0] if inner else None
            elif not isinstance(inner, (str, int, float, bool)):
                val = None
        out[key] = val
    return out


def _matches(
    v: HazardIdRowView,
    department: str | None,
    overall_status: str | None,
    ai_node_progress: str | None,
    keyword: str | None,
    position: str | None,
    risk_level: str | None,
    date_from: str | None,
    date_to: str | None,
    review_status: str | None,
) -> bool:
    m = v.mapped
    if department and m.get("department") != department:
        return False
    if overall_status and m.get("overall_status") != overall_status:
        return False
    if ai_node_progress and m.get("ai_node_progress") != ai_node_progress:
        return False
    if position and m.get("position") != position:
        return False
    if risk_level and m.get("inherent_risk_level") != risk_level:
        return False
    if review_status and not any(m.get(k) == review_status for k in _REVIEW_STATUS_KEYS):
        return False
    if date_from or date_to:
        ca = v.created_at
        try:
            if date_from:
                lo = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=UTC)
                if ca is None or ca < lo:
                    return False
            if date_to:
                hi = datetime.strptime(
                    date_to + " 23:59:59", "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=UTC)
                if ca is None or ca > hi:
                    return False
        except ValueError:
            pass
    if keyword:
        kw = keyword.lower()
        if not any(
            kw in str(m.get(f) or "").lower()
            for f in ("hazard_id_no", "department", "position", "production_step")
        ):
            return False
    return True


def list_identifications(
    views: list[HazardIdRowView],
    *,
    skip: int = 0,
    limit: int = 20,
    department: str | None = None,
    overall_status: str | None = None,
    ai_node_progress: str | None = None,
    keyword: str | None = None,
    position: str | None = None,
    risk_level: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    review_status: str | None = None,
) -> tuple[list[HazardIdRowView], int]:
    """台账列表（过滤口径对齐镜像 ``get_hazard_identifications``）。"""
    filtered = [
        v for v in views
        if _matches(
            v, department, overall_status, ai_node_progress, keyword,
            position, risk_level, date_from, date_to, review_status,
        )
    ]
    filtered.sort(
        key=lambda v: v.created_at or datetime.min.replace(tzinfo=UTC), reverse=True,
    )
    return filtered[skip : skip + limit], len(filtered)


def workflow_stats(views: list[HazardIdRowView]) -> dict[str, int]:
    """工作流统计（键对齐镜像 ``get_hazard_identification_stats``）。"""
    stats = {
        "total_draft": 0,
        "total_in_progress": 0,
        "total_pending_review": 0,
        "total_completed": 0,
    }
    for v in views:
        status = v.mapped.get("overall_status")
        if status == "draft":
            stats["total_draft"] += 1
        elif status == "in_progress":
            stats["total_in_progress"] += 1
            if any(v.mapped.get(k) == "pending" for k in _REVIEW_STATUS_KEYS):
                stats["total_pending_review"] += 1
        elif status == "completed":
            stats["total_completed"] += 1
    return stats


def ledger_stats(
    views: list[HazardIdRowView],
    *,
    department: str | None = None,
    position: str | None = None,
    risk_level: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    """台账统计：仅 completed 行，按固有风险等级分组（键对齐镜像）。"""
    levels = {"level_1": 0, "level_2": 0, "level_3": 0, "level_4": 0}
    total = 0
    for v in views:
        if v.mapped.get("overall_status") != "completed":
            continue
        if not _matches(
            v, department, None, None, None, position, risk_level,
            date_from, date_to, None,
        ):
            continue
        total += 1
        level = v.mapped.get("inherent_risk_level")
        if level in levels:
            levels[level] += 1
    return {"total": total, **levels}
