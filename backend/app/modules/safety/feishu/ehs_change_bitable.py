"""EHS 变更管理 Bitable 字段映射。

将飞书多维表格「变更审批 / 变更验收」两个表的中文字段映射为
``EhsChange`` 模型字段。纯数据映射，无副作用（不触发 AI / 通知 / 状态流转）。

- 变更审批表: ehs_change/approval（变更审批表）
- 变更验收表: ehs_change/acceptance（变更验收表）
- 连接配置从配置中心 store 读取（延迟读取 + 同步缓存）
- 复用 bitable_handler 的纯函数: _extract_rich_text / _extract_person_info / _extract_select_values / _ms_to_datetime
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_handler import (
    _extract_person_info,
    _extract_rich_text,
    _extract_select_values,
    _ms_to_datetime,
)

logger = logging.getLogger(__name__)


def ehs_tables() -> dict[str, str]:
    """kind → table_id（approval/acceptance），仅启用连接（事件过滤/同步分派用）。"""
    return {
        v.kind: v.table_id
        for v in store.get_connections("ehs_change")
        if v.table_id
    }


def ehs_app_token() -> str:
    """EHS 变更 Base app_token（审批/验收两表共用，取任一启用连接）。"""
    for v in store.get_connections("ehs_change"):
        if v.app_token:
            return v.app_token
    return ""

# 伪状态：Bitable 申请状态为「已删除」时表示该记录应被软删除/跳过
STATUS_DELETED = "deleted"


# ── 表匹配 ──


def _match_table(app_token: str, table_id: str) -> str | None:
    """返回 table_id 对应的表类型 key（approval/acceptance），不匹配返回 None。"""
    if not app_token or app_token != ehs_app_token():
        return None
    return table_kind_by_id(table_id)


def table_kind_by_id(table_id: str) -> str | None:
    """仅按 table_id 匹配表类型（用于 bitable.record.* 事件，事件里通常不含 app token）。"""
    for kind, tid in ehs_tables().items():
        if table_id and table_id == tid:
            return kind
    return None


# ── 值提取辅助 ──


def _extract_url_text(value: Any) -> str:
    """从 Bitable Url 字段提取纯文本（如申请编号）。"""
    if isinstance(value, dict):
        return (value.get("text") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_url_link(value: Any) -> str:
    """从 Bitable Url 字段提取链接（原始记录跳转用）。"""
    if isinstance(value, dict):
        return (value.get("link") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_multi_select_first(value: Any) -> str:
    """多选字段取首个值。"""
    return _extract_select_values(value).split(",")[0].strip()


def _extract_datetime_ms(value: Any) -> datetime | None:
    """DateTime 字段转 datetime（自动处理 dict 包装）。"""
    if isinstance(value, dict):
        # 某些场景 value 可能是 {"value": ts} 包装
        value = value.get("value")
    return _ms_to_datetime(value)


# ── 枚举映射 ──

_APPROVAL_STATUS_MAP: dict[str, str] = {
    "已通过": "approved",
    "审批中": "under_review",
    "已拒绝": "rejected",
    "已撤回": "withdrawn",
    "已取消": "cancelled",
    "已终止": "terminated",
    "已删除": STATUS_DELETED,
}

_GRADE_MAP: dict[str, str] = {
    "重大": "major",
    "重大变更": "major",
    "一般": "general",
    "一般（需总经理审批）": "general",
    "一般变更": "general",
}

_TYPE_MAP: dict[str, str] = {
    "工艺技术变更": "process_tech",
    "设备设施变更": "equipment_facility",
    "管理变更": "management",
}

_DURATION_MAP: dict[str, str] = {
    "临时变更": "temporary",
    "永久性变更": "permanent",
    "紧急变更": "emergency",
}

# AI 审核结论列的有效取值（任一命中即视为该维度已审核）
_AI_CONCLUSION_VALUES = {"审核通过", "需补充完善", "审核不通过"}


def _extract_ai_dimension(
    fields: dict[str, Any], *, dim_label: str, dim_key: str
) -> tuple[str | None, str | None]:
    """从 Bitable 提取单维度 AI 审核结论/报告。

    dim_label: Bitable 列前缀（如 "申请变更原因"）
    dim_key: 写入 ai_review_result 的 key（如 "reason"）
    Returns:
        (conclusion | None, report | None)
    """
    conclusion_raw = fields.get(f"{dim_label}-AI审核结论")
    report_raw = fields.get(f"{dim_label}-AI审核报告")
    conclusion = _extract_select_values(conclusion_raw) or None
    report = _extract_rich_text(report_raw) or None
    return conclusion, report


# ── 主映射函数 ──


def map_approval_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """将 Bitable「变更审批」表记录映射为 EhsChange dict。

    Returns:
        dict — 可直接用于创建/更新 EhsChange；
        None — 申请状态为「已删除」，调用方应软删除/跳过该记录。
    """
    status_raw = _extract_select_values(fields.get("申请状态"))
    status = _APPROVAL_STATUS_MAP.get(status_raw)
    if status is None and status_raw:
        logger.warning("Bitable 变更审批申请状态未知值: %s，默认 draft", status_raw)
        status = "draft"
    if status == STATUS_DELETED:
        return None

    person = _extract_person_info(fields.get("变更发起人"))
    current_handler = _extract_person_info(fields.get("当前处理人"))

    change_no = _extract_url_text(fields.get("申请编号"))
    if not change_no:
        change_no = _extract_rich_text(fields.get("变更申请编号"))

    # ── AI 审核四维度 ──
    ai_result: dict[str, Any] = {}
    for dim_label, dim_key in (
        ("申请变更原因", "reason"),
        ("变更计划内容", "plan"),
        ("预计效果", "effect"),
        ("变更风险评估及建议措施", "risk"),
    ):
        conclusion, report = _extract_ai_dimension(fields, dim_label=dim_label, dim_key=dim_key)
        if conclusion or report:
            ai_result[dim_key] = {"conclusion": conclusion, "report": report}

    pre_review = _extract_rich_text(fields.get("AI预审意见"))
    if pre_review:
        ai_result["pre_review"] = pre_review

    ai_review_status = "completed" if ai_result else "none"

    # ── 需更新的文件资料 → documents_to_update [{name}] ──
    docs_raw = _extract_rich_text(fields.get("需更新的文件资料"))
    documents_to_update = None
    if docs_raw:
        documents_to_update = [{"name": docs_raw}]

    # ── bt_extra ──
    bt_extra: dict[str, Any] = {}
    can_reflect = _extract_select_values(fields.get("是否可以体现"))
    if can_reflect:
        bt_extra["can_reflect"] = can_reflect
    gmp_no = _extract_rich_text(fields.get("GMP变更编号"))
    if gmp_no:
        bt_extra["gmp_change_no"] = gmp_no
    if current_handler["name"]:
        bt_extra["current_handler"] = current_handler["name"]
    approval_node = _extract_rich_text(fields.get("审批节点"))
    if approval_node:
        bt_extra["approval_node"] = approval_node
    source_id = _extract_rich_text(fields.get("SourceID"))
    if source_id:
        bt_extra["source_id"] = source_id
    feishu_url = _extract_url_link(fields.get("申请编号"))
    if feishu_url:
        bt_extra["feishu_url"] = feishu_url

    return {
        "change_no": change_no or None,
        "title": _extract_rich_text(fields.get("变更名称")) or "",
        "bt_change_no": _extract_rich_text(fields.get("变更申请编号")) or None,
        "change_type": _TYPE_MAP.get(
            _extract_multi_select_first(fields.get("变更分类"))
        ) or _extract_multi_select_first(fields.get("变更分类")) or None,
        "change_grade": _GRADE_MAP.get(
            _extract_select_values(fields.get("变更级别"))
        ) or _extract_select_values(fields.get("变更级别")) or "general",
        "change_duration": _DURATION_MAP.get(
            _extract_multi_select_first(fields.get("变更时效"))
        ) or _extract_multi_select_first(fields.get("变更时效")) or "permanent",
        "department": _extract_multi_select_first(fields.get("变更申请部门")) or None,
        "location_unit": None,
        "description": _extract_rich_text(fields.get("申请变更原因")) or None,
        "technical_basis": None,
        "expected_start": _extract_datetime_ms(fields.get("预计实施日期")),
        "expected_completion": None,
        "expected_effect": _extract_rich_text(fields.get("预计效果")) or None,
        "applicant_name": person["name"] or None,
        "documents_to_update": documents_to_update,
        "bt_change_status": _extract_rich_text(fields.get("变更状态")) or None,
        "bt_plan_content": _extract_rich_text(fields.get("变更计划内容")) or None,
        "bt_risk_measures": _extract_rich_text(fields.get("变更风险评估及建议措施")) or None,
        "bt_extra": bt_extra or None,
        "ai_review_status": ai_review_status,
        "ai_review_result": ai_result or None,
        "status": status or "draft",
    }


def map_acceptance_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """将 Bitable「变更验收」表记录映射为 EhsChange dict。

    Returns:
        dict — 可直接用于创建/更新 EhsChange；
        None — 申请状态为「已删除」，调用方应软删除/跳过该记录。
    """
    status_raw = _extract_select_values(fields.get("申请状态"))
    status = _APPROVAL_STATUS_MAP.get(status_raw)
    if status is None and status_raw:
        logger.warning("Bitable 变更验收申请状态未知值: %s，默认 draft", status_raw)
        status = "draft"
    if status == STATUS_DELETED:
        return None

    person = _extract_person_info(fields.get("发起人"))
    current_handler = _extract_person_info(fields.get("当前处理人"))

    change_no = _extract_url_text(fields.get("申请编号"))
    if not change_no:
        change_no = _extract_rich_text(fields.get("变更编号"))

    # ── bt_extra ──
    bt_extra: dict[str, Any] = {}
    approval_flow = _extract_select_values(fields.get("审批流程"))
    if approval_flow:
        bt_extra["approval_flow"] = approval_flow
    if current_handler["name"]:
        bt_extra["current_handler"] = current_handler["name"]
    approval_node = _extract_rich_text(fields.get("审批节点"))
    if approval_node:
        bt_extra["approval_node"] = approval_node
    related_approval = _extract_rich_text(fields.get("关联审批"))
    if related_approval:
        bt_extra["related_approval"] = related_approval
    source_id = _extract_rich_text(fields.get("SourceID"))
    if source_id:
        bt_extra["source_id"] = source_id
    feishu_url = _extract_url_link(fields.get("申请编号"))
    if feishu_url:
        bt_extra["feishu_url"] = feishu_url
    acceptance_date = _extract_datetime_ms(fields.get("验收日期"))
    if acceptance_date:
        bt_extra["acceptance_date"] = acceptance_date.isoformat()

    return {
        "change_no": change_no or None,
        "title": _extract_rich_text(fields.get("变更名称")) or "",
        "bt_change_no": _extract_rich_text(fields.get("变更编号")) or None,
        "change_type": None,
        "change_grade": _GRADE_MAP.get(
            _extract_select_values(fields.get("变更级别"))
        ) or _extract_select_values(fields.get("变更级别")) or "general",
        "change_duration": None,
        "department": _extract_rich_text(fields.get("发起人部门")) or None,
        "location_unit": None,
        "description": None,
        "technical_basis": None,
        "expected_start": None,
        "expected_completion": None,
        "expected_effect": None,
        "applicant_name": person["name"] or None,
        "documents_to_update": None,
        "bt_change_status": None,
        "bt_plan_content": None,
        "bt_risk_measures": None,
        "bt_acceptance_comment": _extract_rich_text(fields.get("验收意见（可另附验收报告）")) or None,
        "bt_extra": bt_extra or None,
        "ai_review_status": "none",
        "ai_review_result": None,
        "status": status or "draft",
    }


_MAPPERS: dict[str, Any] = {
    "approval": map_approval_fields,
    "acceptance": map_acceptance_fields,
}


def get_mapper(table_kind: str | None):
    """按表类型返回映射函数。"""
    return _MAPPERS.get(table_kind)
