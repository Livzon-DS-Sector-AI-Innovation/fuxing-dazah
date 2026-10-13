"""oh 直读 — Web 台账页面查询（直读看板批次 3，2026-10-13）。

职业健康是双向域（平台联动回写 Bitable：体检→汇总表回填/在岗状态等，见
``oh_person.sync_from_exam``），本模块只服务**读侧台账视图**：

- 人员汇总台账列表/统计（kind=person_master，映射复用事件 handler 同款 mapper）
- 体检记录列表（kind=exam_registry）
- 危害因素 PPE 台账列表（复用既有 fetch_factors 视图）

详情/写入流/岗位表维持镜像（平台 join 与双源承重，见 oh_direct/config 模块头）。
与镜像路径的已知差异：排序按 Bitable record 创建顺序倒序（镜像按平台
created_at 倒序，二者对同一批业务行通常一致）；响应 id=recXXX。
"""

from __future__ import annotations

import time
from typing import Any, cast

from app.modules.safety.feishu import oh_bitable_handler as oh_handler
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.oh_direct import config


class OhRowView:
    """person_master / exam_registry 行的通用视图（mapped 为 ORM 形状 dict）。"""

    def __init__(self, record_id: str, mapped: dict[str, Any]) -> None:
        self.record_id = record_id
        self.mapped = mapped

    @property
    def id(self) -> str:
        return self.record_id

    def __getattr__(self, name: str) -> Any:
        # 只暴露 mapped 里真实存在的键；缺失键抛 AttributeError，
        # 让 Pydantic from_attributes 回退到 schema 字段默认值
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self.mapped:
            return self.mapped[name]
        raise AttributeError(name)


_cached: dict[str, Any] = {
    "person_master": [],
    "exam_registry": [],
    "ts": {"person_master": 0.0, "exam_registry": 0.0},
}

# 人员汇总表实际列名带「 2」后缀（表格改版后重建的引用列），事件 handler
# 仍按原名读取——此处做键名归一垫片，两套名字都能映射上
_PERSON_FIELD_ALIASES: tuple[tuple[str, str], ...] = (
    ("姓名.部门 2", "姓名.部门"),
    ("姓名.工号 2", "姓名.工号"),
    ("姓名.职务 2", "姓名.职务"),
)


def _normalize_person_fields(fields: dict[str, Any]) -> dict[str, Any]:
    for suffixed, canonical in _PERSON_FIELD_ALIASES:
        if suffixed in fields and canonical not in fields:
            fields[canonical] = fields[suffixed]
    return fields


async def _fetch_kind(kind: str, mapper: Any) -> list[OhRowView]:
    ttl = config.cache_ttl_seconds()
    now = time.monotonic()
    if ttl > 0 and _cached[kind] and now - _cached["ts"][kind] < ttl:
        return cast("list[OhRowView]", _cached[kind])

    client = bd_reader.resolve_client("oh", kind)
    # automatic_fields=True：人员字段子键（如 姓名.部门）需要服务端展开
    records = await client.list_all_records(
        automatic_fields=True, page_size=500, strict=True,
    )
    views: list[OhRowView] = []
    for rec in records:
        record_id = str(rec.get("record_id") or "")
        if not record_id:
            continue
        fields = rec.get("fields") or {}
        if kind == "person_master":
            fields = _normalize_person_fields(fields)
        mapped = mapper(fields)
        if mapped is None:
            continue  # 脏数据（mapper 自身判定，如无姓名行）
        views.append(OhRowView(record_id, mapped))
    if ttl > 0:
        _cached[kind] = views
        _cached["ts"][kind] = now
    return views


async def fetch_persons() -> list[OhRowView]:
    """人员汇总台账全量视图（TTL 缓存）。"""
    return await _fetch_kind("person_master", oh_handler.map_person_master_fields)


async def fetch_exams() -> list[OhRowView]:
    """体检记录全量视图（TTL 缓存）。"""
    return await _fetch_kind("exam_registry", oh_handler.map_exam_registry_fields)


# ── 人员列表（过滤口径对齐 repository/core.get_oh_persons）──


def list_persons(
    persons: list[OhRowView],
    *,
    skip: int = 0,
    limit: int = 20,
    department: str | None = None,
    position: str | None = None,
    hazard_exposure: str | None = None,
    last_exam_conclusion: str | None = None,
    keyword: str | None = None,
) -> tuple[list[OhRowView], int]:
    filtered = [
        p for p in persons
        if _person_matches(
            p, department, position, hazard_exposure, last_exam_conclusion, keyword,
        )
    ]
    total = len(filtered)
    return filtered[skip : skip + limit], total


def person_stats(persons: list[OhRowView]) -> dict[str, Any]:
    """键与 ``OhPersonService.get_stats`` 一致。"""
    by_department: dict[str, int] = {}
    by_position: dict[str, int] = {}
    by_work_status: dict[str, int] = {}
    by_conclusion: dict[str, int] = {}
    hazard_exposed = 0

    def _bump(bucket: dict[str, int], key: Any) -> None:
        if key in (None, ""):
            return
        bucket[str(key)] = bucket.get(str(key), 0) + 1

    for p in persons:
        _bump(by_department, p.mapped.get("department"))
        _bump(by_position, p.mapped.get("position"))
        _bump(by_work_status, p.mapped.get("work_status"))
        _bump(by_conclusion, p.mapped.get("last_exam_conclusion"))
        years = p.mapped.get("hazard_exposure_years") or 0
        factors = p.mapped.get("hazard_factors")
        if (isinstance(years, (int, float)) and years > 0) or factors:
            hazard_exposed += 1
    return {
        "total": len(persons),
        "hazard_exposed": hazard_exposed,
        "by_department": by_department,
        "by_position": by_position,
        "by_work_status": by_work_status,
        "by_last_exam_conclusion": by_conclusion,
    }


def _person_matches(
    p: OhRowView,
    department: str | None,
    position: str | None,
    hazard_exposure: str | None,
    last_exam_conclusion: str | None,
    keyword: str | None,
) -> bool:
    m = p.mapped
    if department and m.get("department") != department:
        return False
    if position and m.get("position") != position:
        return False
    if last_exam_conclusion and m.get("last_exam_conclusion") != last_exam_conclusion:
        return False
    if hazard_exposure in ("yes", "true", "1"):
        years = m.get("hazard_exposure_years") or 0
        if not ((isinstance(years, (int, float)) and years > 0) or m.get("hazard_factors")):
            return False
    if keyword:
        kw = keyword.lower()
        if not any(
            kw in str(m.get(f) or "").lower()
            for f in ("name", "id_card_no", "employee_no", "department", "phone")
        ):
            return False
    return True


# ── 体检列表（过滤口径对齐 repository/core.get_health_exams）──


def list_exams(
    exams: list[OhRowView],
    *,
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
    exam_type: str | None = None,
    department: str | None = None,
    ai_conclusion: str | None = None,
    ai_parse_status: str | None = None,
    keyword: str | None = None,
) -> tuple[list[OhRowView], int]:
    filtered = [
        e for e in exams
        if _exam_matches(
            e, status, exam_type, department, ai_conclusion, ai_parse_status, keyword,
        )
    ]
    total = len(filtered)
    return filtered[skip : skip + limit], total


def _exam_matches(
    e: OhRowView,
    status: str | None,
    exam_type: str | None,
    department: str | None,
    ai_conclusion: str | None,
    ai_parse_status: str | None,
    keyword: str | None,
) -> bool:
    m = e.mapped
    if status and m.get("status") != status:
        return False
    if exam_type and m.get("exam_type") != exam_type:
        return False
    if department and m.get("department") != department:
        return False
    if ai_conclusion and ai_conclusion not in (
        m.get("ai_conclusion"), m.get("override_conclusion"),
    ):
        return False
    if ai_parse_status and m.get("ai_parse_status") != ai_parse_status:
        return False
    if keyword:
        kw = keyword.lower()
        if not any(
            kw in str(m.get(f) or "").lower()
            for f in ("exam_no", "employee_name", "department", "id_card_no")
        ):
            return False
    return True


# ── 危害因素列表（复用既有 fetch_factors 视图，无过滤仅分页）──


async def list_hazard_factors(
    *, skip: int = 0, limit: int = 50,
) -> tuple[list[Any], int]:
    from app.modules.safety.service.oh_direct.reader import open_reader

    views = await open_reader().fetch_factors()
    return views[skip : skip + limit], len(views)


__all__ = [
    "OhRowView",
    "fetch_persons",
    "fetch_exams",
    "list_persons",
    "person_stats",
    "list_exams",
    "list_hazard_factors",
]
