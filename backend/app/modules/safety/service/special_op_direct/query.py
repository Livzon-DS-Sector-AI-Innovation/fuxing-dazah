"""特殊作业明细「直读多维表格」查询（Agent 只读工具用）。

与镜像库查询的差异（Ticket 07）：

- 数据源 = 飞书「全厂特殊作业一览表」直读，**不再读平台库镜像表**
- 精确筛选下推 Bitable：日期区间、作业类型、作业分级、报备类型、部门、风险等级
- 关键词模糊匹配与各下推条件的最终复核在应用侧完成
- 风险等级：列有值则读列（可能陈旧，窗口最长约 9 小时），为空则现场跑
  ``RiskAssessmentEngine`` 并展示，**不回写**

Bitable 过滤能力（2026-09-14 连生产表实测）：

- ``filter`` 只支持**单层** conjunction：嵌套 group 返回 ``field validation failed``，
  因此「部门 = 申请部门 或 发起人部门」「风险列 = X 或 为空」这类 OR 只能拆成
  多条 flat-AND 查询再按 record_id 取并集
- 单选字段只支持 ``is`` / ``isNot`` / ``isEmpty`` / ``isNotEmpty``
  （``contains`` 返回 ``InvalidFilter``）；文本字段（发起人部门）支持 ``contains``
- 无日期窗口时不做分支下推（避免整表被扫多次），退化为单查询 + 应用侧过滤

Ticket 06 收敛：日期窗口、过滤构造与分支并集全部转发公共底座
``bitable_direct.filters``；本模块只保留特殊作业的枚举映射、应用侧复核与返回形状。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import filters as bd_filters
from app.modules.safety.service.bitable_direct.reader import BitableRecordsReader
from app.modules.safety.service.special_op_direct import bitable_repo, contract
from app.modules.safety.service.special_op_direct.bitable_repo import SpecialOpView

logger = logging.getLogger(__name__)

# 多维表格列名
F_TYPE = "作业类型"
F_LEVEL = "作业分级"
F_REPORT_TYPE = "报备类型"
F_DEPT = "申请部门"
F_INITIATOR_DEPT = "发起人部门"

# 单次分页大小（拉取侧）：500 可减少全表扫描的往返次数
_FETCH_PAGE_SIZE = 500
# 返回侧分页上限（与既有工具一致）
MAX_PAGE_SIZE = 100

# 平台 code  Bitable 单选选项（与 map_bitable_fields 的 CNEN 映射互逆）
OP_TYPE_EN2CN_OPTIONS: dict[str, tuple[str, ...]] = {
    "hot_work": ("动火作业", "常规作业"),  # 映射表里「常规作业」也归 hot_work
    "confined_space": ("受限空间",),
    "height_work": ("高处作业",),
    "lifting": ("吊装作业",),
    "temporary_electricity": ("临时用电",),
    "excavation": ("动土作业",),
    "road_breaking": ("断路作业",),
    "blind_plate": ("盲板抽堵",),
}
OP_LEVEL_EN2CN_OPTIONS: dict[str, tuple[str, ...]] = {
    "special": ("特级/Ⅳ级",),
    "grade1": ("一级（Ⅰ级）",),
    "grade2": ("二级（Ⅱ级）", "三级（Ⅲ级）"),  # 两级都映射 grade2 -> 不下推
    "not_applicable": ("不涉及",),
}
REPORT_TYPE_EN2CN: dict[str, str] = {
    "planned": "计划内作业",
    "unplanned": "计划外作业",
}


def date_window(
    date_from: date | None, date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    """ISO 日期 -> [起始, 结束次日) 的北京时间半开区间（与旧工具口径一致）。

    转发公共底座的 ``date_range_window``，保留原函数名与签名。
    """
    return bd_filters.date_range_window(date_from, date_to)


def _stored_risk_level(record: dict[str, Any]) -> str | None:
    """读取「日报风险等级（AI）」列值 -> 平台 code（空/未知返回 None）。"""
    fields = record.get("fields") or {}
    text = bd_fields.select(fields, contract.RISK_FIELD_NAME)
    if not text:
        return None
    return contract.OPTION_TO_RISK_LEVEL.get(text)


def to_query_view(record: dict[str, Any]) -> SpecialOpView:
    """Bitable 记录 -> 查询用视图：列有值读列，为空则现场判定（不回写）。

    撤回票排除在最后兜底：存量风险列有值的撤回票不得因列值而算作有效票。
    """
    view = bitable_repo.to_view(record)
    stored = _stored_risk_level(record)
    if stored:
        view.daily_risk_level = stored
        view.daily_risk_reason = None
        view.is_excluded = False
        view.exclusion_reason = None
        view.inferred_operation_types = None
    else:
        bitable_repo.assess_view(view)
    return bitable_repo.mark_withdrawn(view)


def _matches(
    view: SpecialOpView,
    *,
    department: str | None,
    start: datetime | None,
    end_exclusive: datetime | None,
    operation_type: str | None,
    operation_level: str | None,
    daily_risk_level: str | None,
    report_type: str | None,
    keyword: str | None,
) -> bool:
    """应用侧复核：保证下推条件的最终语义（含模糊匹配）。"""
    if department and department not in (view.department or ""):
        return False
    if start and (view.planned_start_time is None or view.planned_start_time < start):
        return False
    if end_exclusive and (
        view.planned_start_time is None or view.planned_start_time >= end_exclusive
    ):
        return False
    if operation_type and view.operation_type != operation_type:
        return False
    if operation_level and view.operation_level != operation_level:
        return False
    if report_type and view.report_type != report_type:
        return False
    if daily_risk_level and view.daily_risk_level != daily_risk_level:
        return False
    if keyword:
        kw = keyword.lower()
        haystacks = (
            (view.work_description or "").lower(),
            (view.location or "").lower(),
            (view.approval_no or "").lower(),
        )
        if not any(kw in hay for hay in haystacks):
            return False
    return True


def _item(view: SpecialOpView) -> dict[str, Any]:
    """返回条目（字段与既有镜像库工具逐一对应，不增不减）。"""
    return {
        "report_no": view.report_no,
        "department": view.department,
        "initiator_department": view.initiator_department,
        "operation_type": view.operation_type,
        "operation_level": view.operation_level,
        "daily_risk_level": view.daily_risk_level,
        "daily_risk_reason": view.daily_risk_reason,
        "report_type": view.report_type,
        "work_description": view.work_description,
        "location": view.location,
        "planned_start_time": (
            view.planned_start_time.isoformat() if view.planned_start_time else None
        ),
        "planned_end_time": (
            view.planned_end_time.isoformat() if view.planned_end_time else None
        ),
        "work_duration_hours": view.work_duration_hours,
        "personnel_type": view.personnel_type,
        "approval_no": view.approval_no,
        "approver_name": view.approver_name,
        "is_excluded": view.is_excluded,
        "exclusion_reason": view.exclusion_reason,
    }


def _sort_key(view: SpecialOpView) -> tuple[Any, Any, str]:
    return (
        view.planned_start_time or datetime.min.replace(tzinfo=UTC),
        view.created_at,
        view.feishu_record_id or "",
    )


async def query_records(
    *,
    department: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    operation_type: str | None = None,
    operation_level: str | None = None,
    daily_risk_level: str | None = None,
    report_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    client: BitableRecordsReader | None = None,
) -> dict[str, Any]:
    """按条件直读多维表格并返回分页明细。

    Returns:
        ``{"items": [...], "total": int, "page": int, "page_size": int}``
    """
    reader = client or bitable_repo.resolve_client()
    start, end_exclusive = date_window(date_from, date_to)

    #  下推条件：扁平 AND（单选项枚举 + 日期窗口）
    base: list[dict[str, Any]] = []
    if start:
        base.append(
            bd_filters.condition(
                bitable_repo.F_START_TIME,
                "isGreater",
                bd_filters.exact_date_value(start),
            )
        )
    if end_exclusive:
        base.append(
            bd_filters.condition(
                bitable_repo.F_START_TIME,
                "isLess",
                bd_filters.exact_date_value(end_exclusive),
            )
        )
    if operation_type:
        options = OP_TYPE_EN2CN_OPTIONS.get(operation_type, ())
        if len(options) == 1:  # 多选项（hot_work）不下推，改应用侧
            base.append(bd_filters.condition(F_TYPE, "is", [options[0]]))
    if operation_level:
        options = OP_LEVEL_EN2CN_OPTIONS.get(operation_level, ())
        if len(options) == 1:  # grade2 对应两个选项，不下推
            base.append(bd_filters.condition(F_LEVEL, "is", [options[0]]))
    if report_type and report_type in REPORT_TYPE_EN2CN:
        base.append(
            bd_filters.condition(
                F_REPORT_TYPE, "is", [REPORT_TYPE_EN2CN[report_type]]
            )
        )

    #  下推条件：需要 OR 的条件拆成多条 flat-AND 查询取并集
    # 仅在有日期窗口时下推（否则整表会被扫多次，不如单查询 + 应用侧过滤）
    branches: list[list[dict[str, Any]]] = [[]]
    if start or end_exclusive:
        if department:
            branches = [
                leaf + branch
                for leaf in branches
                for branch in (
                    [bd_filters.condition(F_INITIATOR_DEPT, "contains", [department])],
                    [bd_filters.condition(F_DEPT, "is", [department])],
                )
            ]
        risk_option = contract.option_for_risk_level(daily_risk_level)
        if risk_option:
            branches = [
                leaf + branch
                for leaf in branches
                for branch in (
                    [bd_filters.condition(contract.RISK_FIELD_NAME, "is", [risk_option])],
                    [bd_filters.condition(contract.RISK_FIELD_NAME, "isEmpty")],
                )
            ]

    fetched_groups: list[list[dict[str, Any]]] = []
    for branch in branches:
        conditions = base + branch
        fetched = await reader.list_all_records(
            # 无条件时传 None（空 conditions 会被 Bitable 判为非法过滤）
            filter_info=bd_filters.flat_group(conditions),
            page_size=_FETCH_PAGE_SIZE,
            strict=True,
        )
        fetched_groups.append([
            record
            for record in fetched
            if str(record.get("record_id") or "")
        ])
    records = bd_filters.union_by_record_id(fetched_groups)
    logger.info(
        "特殊作业明细直读: 查询分支=%d 拉取记录=%d", len(branches), len(records)
    )

    views = [to_query_view(record) for record in records]
    matched = [
        view
        for view in views
        if _matches(
            view,
            department=department,
            start=start,
            end_exclusive=end_exclusive,
            operation_type=operation_type,
            operation_level=operation_level,
            daily_risk_level=daily_risk_level,
            report_type=report_type,
            keyword=keyword,
        )
    ]
    matched.sort(key=_sort_key, reverse=True)

    effective_page = max(page, 1)
    effective_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (effective_page - 1) * effective_size
    return {
        "items": [_item(view) for view in matched[offset:offset + effective_size]],
        "total": len(matched),
        "page": effective_page,
        "page_size": effective_size,
    }
