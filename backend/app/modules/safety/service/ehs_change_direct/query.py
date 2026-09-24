"""ehs_change 直读侧查询（Ticket 03）——单语义，Agent 工具专用。

忠实复刻 legacy 镜像语义（read_tools.query_ehs_changes:1843-1925，
spec D3）：

- 过滤：department ilike / change_type 精确（strip 后等值，比较对象为
  映射后枚举值 process_tech/equipment_facility/management 或 Bitable
  原样透传值——legacy 对 PG 列等值比较的同款语义）/ change_grade 经
  _norm_choice 归一（重大→major、一般→general，小写 code 兼容，未知值
  原样返回=零命中）/ status 精确 lower / ai_review_status 精确 lower /
  keyword（title/description ilike）。ilike ≈ 大小写不敏感子串匹配
  （全中文场景等价，oh/hazard_id query 同款口径）；
- 排序（受控偏差，spec D3）：legacy created_at desc（镜像首次插入时间）
  → Bitable created_time desc（真实创建时间），created_time 缺失
  防御性放最后；稳定排序保持拉取序兜底同秒行；
- 分页 quirk（legacy 逐字同款）：offset 用 **raw page_size** 步进、
  limit 取 min(page_size, 100)（cap 只作用 limit）；
  total=过滤后全量计数（非页大小，两表合并口径）；
- 输出：13 字段（与 legacy 逐字同款键集）；日期 isoformat；
  actual_start/actual_completion 恒 None（状态机零使用，spec §0.2）。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.ehs_change_direct.views import EhsChangeView

__all__ = ["ehs_changes"]

# 与 legacy 逐字同款拷贝（read_tools._norm_choice；工具模块不反向
# import service，hazard_id_direct/query 同款口径）
_GRADE_MAP: dict[str, str] = {"重大": "major", "一般": "general"}

# legacy 输出键集（read_tools.items 构造逐字对齐，含键序）
_EHS_ITEM_KEYS = (
    "change_no", "title", "change_type", "change_grade", "department",
    "location_unit", "status", "expected_start", "expected_completion",
    "actual_start", "actual_completion", "applicant_name",
    "ai_review_status",
)


def _norm_choice(value: str | None) -> str | None:
    """枚举参数规范化：先查中文→code 映射，再兼容小写 code，未知值原样返回。"""
    if not value:
        return None
    v = value.strip()
    if v in _GRADE_MAP:
        return _GRADE_MAP[v]
    low = v.lower()
    if low in set(_GRADE_MAP.values()):
        return low
    return v


def _contains(needle: str, haystack: str | None) -> bool:
    """ilike(f"%needle%") 等价：大小写不敏感子串（全中文场景等价）。"""
    return needle.lower() in (haystack or "").lower()


def _iso(v: Any) -> str | None:
    return v.isoformat() if v else None


def _item(v: EhsChangeView) -> dict[str, Any]:
    """视图 → legacy 逐字同款输出 dict。"""
    return {
        "change_no": v.change_no,
        "title": v.title,
        "change_type": v.change_type,
        "change_grade": v.change_grade,
        "department": v.department,
        "location_unit": v.location_unit,
        "status": v.status,
        "expected_start": _iso(v.expected_start),
        "expected_completion": _iso(v.expected_completion),
        "actual_start": _iso(v.actual_start),
        "actual_completion": _iso(v.actual_completion),
        "applicant_name": v.applicant_name,
        "ai_review_status": v.ai_review_status,
    }


def ehs_changes(
    views: list[EhsChangeView],
    *,
    department: str | None = None,
    change_type: str | None = None,
    change_grade: str | None = None,
    status: str | None = None,
    ai_review_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """EHS 变更台账（legacy query_ehs_changes 等价内存实现，两表并集）。"""
    grade_norm = _norm_choice(change_grade)
    status_norm = status.strip().lower() if status else None
    ai_norm = ai_review_status.strip().lower() if ai_review_status else None

    def _match(v: EhsChangeView) -> bool:
        if department and not _contains(department, v.department):
            return False
        if change_type and (v.change_type or "") != change_type.strip():
            return False
        if grade_norm and (v.change_grade or "") != grade_norm:
            return False
        if status_norm and (v.status or "") != status_norm:
            return False
        if ai_norm and (v.ai_review_status or "") != ai_norm:
            return False
        if keyword and not (
            _contains(keyword, v.title) or _contains(keyword, v.description)
        ):
            return False
        return True

    filtered = [v for v in views if _match(v)]
    ordered = sorted(
        filtered,
        key=lambda v: v.created_time_ms if v.created_time_ms is not None else 0,
        reverse=True,
    )
    # legacy 分页 quirk：offset 步进用 raw page_size，cap 只作用 limit
    skip = (max(page, 1) - 1) * page_size
    limit = min(page_size, 100)
    window = ordered[skip: skip + max(0, limit)]
    return [_item(v) for v in window], len(filtered)
