"""相关方准入 Bitable 字段映射。

将飞书多维表格「相关方准入」表的中文字段映射为 ``ContractorAdmission`` 模型字段。
纯数据映射，无副作用（不触发 AI / 通知 / 状态流转）。

- 相关方准入表: contractor_admission/admission（准入条件表）
- 连接配置从配置中心 store 读取（延迟读取 + 同步缓存）
- 复用 bitable_handler 的纯函数: _extract_rich_text / _extract_person_info / _extract_select_values / _ms_to_datetime
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_handler import (
    _extract_person_info,
    _extract_rich_text,
    _extract_select_values,
    _ms_to_datetime,
)

logger = logging.getLogger(__name__)


def admission_tables() -> dict[str, str]:
    """kind → table_id（单表恒为 admission），仅启用连接（事件过滤/同步分派用）。"""
    return {
        v.kind: v.table_id
        for v in store.get_connections("contractor_admission")
        if v.table_id
    }


def admission_app_token() -> str:
    """相关方准入 Base app_token；未启用/缺失返回空串。"""
    conn = store.get_connection("contractor_admission", "admission")
    return conn.app_token if conn and conn.enabled else ""


# ── 表匹配 ──


def _match_table(app_token: str, table_id: str) -> str | None:
    """返回 table_id 对应的表类型 key（admission），不匹配返回 None。"""
    if not app_token or app_token != admission_app_token():
        return None
    return table_kind_by_id(table_id)


def table_kind_by_id(table_id: str) -> str | None:
    """仅按 table_id 匹配表类型（用于 bitable.record.* 事件，事件里通常不含 app token）。"""
    for kind, tid in admission_tables().items():
        if table_id and table_id == tid:
            return kind
    return None


# ── 值提取辅助 ──

# Bitable 协议附件字段名 → 相关方类型（related_party_type 为空时 fallback 承包商）
_AGREEMENT_FIELD_BY_TYPE: dict[str, str] = {
    "承包商": "承包商安全管理协议",
    "合作类相关方": "合作类安全管理协议",
    "劳务派遣": "劳务派遣安全管理协议",
}


def _extract_attachments(value: Any) -> list[dict] | None:
    """从 Bitable attachment 字段提取附件，保留原始 Bitable 结构 [{file_token, name, size, ...}]。

    service 层 upsert 时再决定是否下载存本地路径；本 ticket 只同步原始结构。
    """
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    result: list[dict] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("file_token"):
            continue
        result.append(it)
    return result or None


def _extract_date(value: Any) -> date | None:
    """DateTime ms → date（Bitable datetime 字段平台只存日期部分）。"""
    dt = _ms_to_datetime(value)
    return dt.date() if dt else None


# ── 主映射函数 ──


def map_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """将 Bitable「相关方准入」表记录映射为 ContractorAdmission dict。

    公式字段（补交截止日期/是否延期/材料完整度/创建日期）不映射。

    Returns:
        dict — 可直接用于创建/更新 ContractorAdmission；
        None — 软删除信号（本表暂无 STATUS_DELETED 机制，保留扩展入口）。
    """
    party_type = _extract_select_values(fields.get("相关方类型")) or None
    liaison = _extract_person_info(fields.get("对接人员"))

    # 按 related_party_type 取对应协议附件（type 为空 fallback 承包商）
    agreement_field = _AGREEMENT_FIELD_BY_TYPE.get(party_type or "", "承包商安全管理协议")
    agreement_files = _extract_attachments(fields.get(agreement_field))
    # 兜底：类型字段未填/类型与所挂协议不一致时，按实际存在的协议字段三选一
    # （实测 2026-08-31：相关方类型未填时合作类协议被漏取，导致不触发审核）
    if not agreement_files:
        for fallback_name in ("承包商安全管理协议", "合作类安全管理协议", "劳务派遣安全管理协议"):
            files = _extract_attachments(fields.get(fallback_name))
            if files:
                agreement_files = files
                break

    return {
        "company_name": _extract_rich_text(fields.get("作业单位名称")) or None,
        "related_party_type": party_type,
        "contact_person": _extract_rich_text(fields.get("承包商负责人")) or None,
        "contact_phone": _extract_rich_text(fields.get("承包商负责人联系电话")) or None,
        "liaison_user_id": liaison["id"] or None,
        "liaison_user_name": liaison["name"] or None,
        "entry_date": _extract_date(fields.get("入厂日期")),
        "start_date": _extract_date(fields.get("开始日期")),
        "end_date": _extract_date(fields.get("结束日期")),
        "material_expiry_date": _extract_date(fields.get("材料失效日期")),
        "actual_submit_date": _extract_date(fields.get("实际提交日期")),
        "actual_complete_date": _extract_date(fields.get("实际完成日期")),
        "submit_status": _extract_select_values(fields.get("提交状态")) or None,
        "training_status": _extract_select_values(fields.get("培训状态")) or None,
        "notes": _extract_rich_text(fields.get("备注")) or None,
        "safety_agreement_files": agreement_files,
        "business_license_files": _extract_attachments(fields.get("企业营业执照")),
        "insurance_files": _extract_attachments(fields.get("现场作业保险凭证")),
        "assessment_rules_files": _extract_attachments(fields.get("承包商考核细则")),
        "employee_cert_files": _extract_attachments(fields.get("员工证明盖章文件")),
        "on_site_leader_stamp_files": _extract_attachments(fields.get("现场负责人盖章文件")),
        # 公式字段（补交截止日期/是否延期/材料完整度/创建日期）不映射
    }
