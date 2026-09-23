"""hazard_id 直读侧查询（Ticket 04）——单语义，Agent 工具专用。

忠实复刻 legacy 镜像语义（read_tools.query_hazard_identifications，
spec D3/D5）：

- 过滤：department ilike（identity 现算部门，见 resolve_departments）/
  position ilike / risk_stage+risk_level（label ilike × 关键词组，须同时
  给出且均可识别才生效——legacy 同款静默不过滤）/ overall_status 等值
  （实值域 draft/completed）/ keyword（specific_activity/hazard_type/
  possible_accident 三列 ilike）。ilike ≈ 大小写不敏感子串匹配（全中文
  场景等价，oh query 同款口径）；
- 排序（受控偏差，spec D5）：legacy created_at desc（镜像首次插入时间）→
  Bitable created_time desc（真实创建时间，秒粒度），created_time 缺失
  防御性放最后；稳定排序保持拉取序兜底同秒行；
- 分页 quirk：offset 用 **raw page_size** 步进、limit 取 min(page_size, 100)
  （cap 只作用 limit——legacy 逐字同款）；total=过滤后全量计数（非页大小）；
- 输出：15 字段（与 legacy 逐字同款键集）；feishu_url 恒 None（镜像自始
  无写入方，spec D6 quirk）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select

from app.modules.safety.service.hazard_id_direct.views import (
    HazardIdentificationView,
)

__all__ = ["hazard_identifications", "resolve_departments"]

# 与 legacy 工具体逐字同款拷贝（read_tools._HI_LEVEL_KEYWORDS；工具模块不
# 反向 import service，oh_direct/query 同款口径）
_HI_LEVEL_KEYWORDS: dict[str, list[str]] = {
    "1": ["一级", "重大"], "2": ["二级", "较大"],
    "3": ["三级", "一般"], "4": ["四级", "低风险"],
    "一级": ["一级"], "二级": ["二级"], "三级": ["三级"], "四级": ["四级"],
    "重大": ["重大"], "较大": ["较大"], "一般": ["一般"], "低": ["低风险"],
}

_STAGE_LABEL_ATTRS = {
    "inherent": "inherent_risk_label",
    "residual": "residual_risk_label",
    "post": "post_risk_label",
}

# legacy 输出键集（read_tools.items 构造逐字对齐）
_HI_ITEM_KEYS = (
    "hazard_id_no", "department", "position", "production_step",
    "specific_activity", "hazard_type", "possible_accident",
    "inherent_risk_label", "residual_risk_label", "post_risk_label",
    "control_level", "recommendation_content", "overall_status",
    "submitter_name", "feishu_url",
)


def _contains(needle: str, haystack: str | None) -> bool:
    """ilike(f"%needle%") 等价：大小写不敏感子串（全中文场景等价）。"""
    return needle.lower() in (haystack or "").lower()


def _item(v: HazardIdentificationView, department: str | None) -> dict[str, Any]:
    """视图 → legacy 逐字同款输出 dict（feishu_url 恒 None 属 quirk 复刻）。"""
    return {
        "hazard_id_no": v.hazard_id_no,
        "department": department,
        "position": v.position,
        "production_step": v.production_step,
        "specific_activity": v.specific_activity,
        "hazard_type": v.hazard_type,
        "possible_accident": v.possible_accident,
        "inherent_risk_label": v.inherent_risk_label,
        "residual_risk_label": v.residual_risk_label,
        "post_risk_label": v.post_risk_label,
        "control_level": v.control_level,
        "recommendation_content": v.recommendation_content,
        "overall_status": v.overall_status,
        "submitter_name": v.submitter_name,
        "feishu_url": None,
    }


def hazard_identifications(
    views: list[HazardIdentificationView],
    *,
    departments: dict[str, str | None] | None = None,
    department: str | None = None,
    position: str | None = None,
    risk_stage: str | None = None,
    risk_level: str | None = None,
    overall_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """危险源辨识明细（legacy query_hazard_identifications 等价内存实现）。"""
    dept_map = departments or {}

    # legacy：stage/level 须同时给出且均可识别才过滤；任一不可识别=静默不加条件
    stage_attr = (
        _STAGE_LABEL_ATTRS.get((risk_stage or "").strip().lower())
        if risk_stage else None
    )
    kws = _HI_LEVEL_KEYWORDS.get(risk_level.strip()) if risk_level else None
    stage_filter_on = bool(stage_attr and kws)
    status_norm = overall_status.strip().lower() if overall_status else None

    def _match(v: HazardIdentificationView) -> bool:
        if department and not _contains(
            department, dept_map.get(v.submitter_name or ""),
        ):
            return False
        if position and not _contains(position, v.position):
            return False
        if stage_filter_on:
            label = getattr(v, stage_attr or "")
            if not any(kw in (label or "") for kw in kws or []):
                return False
        if status_norm and (v.overall_status or "") != status_norm:
            return False
        if keyword and not any(
            _contains(keyword, getattr(v, f))
            for f in ("specific_activity", "hazard_type", "possible_accident")
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
    items = [
        _item(v, dept_map.get(v.submitter_name or "")) for v in window
    ]
    return items, len(filtered)


async def resolve_departments(
    db: Any, names: Iterable[str | None],
) -> dict[str, str | None]:
    """identity.users 按提交人姓名批量派生部门（handler 同语义，spec D6）。

    精确姓名匹配、is_deleted=false、每名取首条——与 handler
    `_resolve_department_for_submitter` 的 ``.first()`` 同为任意序（同名多人
    取序不保证逐字一致，时效差异归因见 verify）；派不到的名字不落键
    （查询层 ``.get`` → None=置空，与镜像置空语义一致）。
    """
    unique = sorted({n.strip() for n in names if n and n.strip()})
    if not unique:
        return {}
    from app.platform.identity.models import User as IdentityUser

    stmt = select(IdentityUser.name, IdentityUser.department).where(
        IdentityUser.name.in_(unique),
        IdentityUser.is_deleted == False,  # noqa: E712
    )
    rows = (await db.execute(stmt)).all()
    out: dict[str, str | None] = {}
    for name, dept in rows:
        out.setdefault(name, dept)
    return out
