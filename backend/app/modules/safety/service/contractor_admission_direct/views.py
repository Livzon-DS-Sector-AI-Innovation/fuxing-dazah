"""contractor_admission 直读视图对象与派生 AI 态（Ticket 01）。

照 key_risk_op_direct/views.py 模式：

1. ContractorAdmissionView：字段名与 ContractorAdmission ORM 完全同名（审计列
   created_by/updated_by/is_deleted 除外，契约单测固化）；id = 飞书记录 ID（recXXX，
   镜像按 feishu_record_id 对齐，两路径 id 空间一致）；source/feishu_table_id 恒
   bitable/admission；admission_no/feishu_url 恒 None（Bitable 无此列，镜像亦从未填充）；
   updated_at 恒 None；created_at = 「创建日期」公式列（探针 109 行全有值）——与镜像
   created_at（首次同步 insert 时刻）天然不同，比对按受控偏差归因（spec §4.6）。
2. view_from_record_id：复用镜像同一映射纯函数
   ``feishu/contractor_admission_bitable.map_fields``（静态、零 IO，22 字段；协议附件
   按相关方类型三选一 + fallback 保留原始 Bitable 结构）。
3. 派生 AI 态（spec §4.1 D2 拍板：仅从 Bitable 3 列推导）——completed ⇔ AI审核结论
   非空；ai_review_result 重建总体三字段，agreement/license/insurance 置 None、
   regulations 置空；processing/failed 不可表达（过滤器恒空，用户已接受）。
4. mapped_diff_key：触发器变更检测用稳定键——附件字段只比 file_token 序列
   （预签名 url/tmp_url 每次拉取都变，比原始 dict 会恒 diff 导致每查必触发）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.modules.safety.feishu.bitable_handler import (
    _extract_rich_text,
    _extract_select_values,
    _ms_to_datetime,
)
from app.modules.safety.feishu.contractor_admission_bitable import map_fields
from app.modules.safety.service.contractor_admission_direct.contract import (
    CREATED_AT_FIELD,
    WRITEBACK_CONCLUSION_FIELD,
    WRITEBACK_DEFECTS_FIELD,
    WRITEBACK_REPORT_FIELD,
)

__all__ = [
    "AI_REVIEW_STATUS_COMPLETED",
    "AI_REVIEW_STATUS_NONE",
    "ContractorAdmissionView",
    "derive_ai_state",
    "mapped_diff_key",
    "mapped_field_keys",
    "view_from_record_id",
]

AI_REVIEW_STATUS_NONE = "none"
AI_REVIEW_STATUS_COMPLETED = "completed"

# 附件映射字段（map_fields 键；diff 时只比 file_token 序列）
_ATTACHMENT_DIFF_FIELDS = frozenset({
    "safety_agreement_files",
    "business_license_files",
    "insurance_files",
    "assessment_rules_files",
    "employee_cert_files",
    "on_site_leader_stamp_files",
})


@dataclass
class ContractorAdmissionView:
    """相关方准入行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX）
    id: str = ""
    admission_no: str | None = None  # 平台生成编号，Bitable 无此列，直读恒 None
    feishu_record_id: str | None = None
    feishu_table_id: str | None = None
    feishu_url: str | None = None  # 镜像亦从未填充，恒 None（对齐）
    source: str = "bitable"
    created_at: datetime | None = None  # = Bitable 创建日期公式列
    updated_at: datetime | None = None  # 直读恒 None

    # 业务字段（map_fields 映射，与 ORM 同名）
    company_name: str | None = None
    related_party_type: str | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    liaison_user_id: str | None = None
    liaison_user_name: str | None = None
    entry_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    material_expiry_date: date | None = None
    actual_submit_date: date | None = None
    actual_complete_date: date | None = None
    submit_status: str | None = None
    training_status: str | None = None
    notes: str | None = None
    safety_agreement_files: list[Any] | None = None
    business_license_files: list[Any] | None = None
    insurance_files: list[Any] | None = None
    assessment_rules_files: list[Any] | None = None
    employee_cert_files: list[Any] | None = None
    on_site_leader_stamp_files: list[Any] | None = None

    # AI 审核态（D2：从 Bitable 3 列派生，非平台库状态）
    ai_review_status: str = AI_REVIEW_STATUS_NONE
    ai_review_result: dict[str, Any] | None = None
    ai_error_message: str | None = None  # 直读派生恒 None
    ai_reviewed_at: datetime | None = None  # 直读派生恒 None


def view_from_record_id(record_id: str, fields: dict[str, Any]) -> ContractorAdmissionView:
    """Bitable 原始 fields dict → 视图对象（映射复用镜像同一纯函数 map_fields）。"""
    mapped = map_fields(fields) or {}
    view = ContractorAdmissionView(id=record_id)
    for key, value in mapped.items():
        setattr(view, key, value)
    view.feishu_record_id = record_id
    view.feishu_table_id = "admission"
    view.source = "bitable"
    view.created_at = _ms_to_datetime(fields.get(CREATED_AT_FIELD))
    view.ai_review_status, view.ai_review_result = derive_ai_state(fields)
    return view


def derive_ai_state(fields: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """从 Bitable 3 列派生 AI 审核态（spec §4.1 D2）。

    completed ⇔ AI审核结论 非空；重建结果只含总体三字段
    （overall_conclusion/overall_report/defect_categories），维度与 regulations 置空。
    """
    conclusion = (_extract_select_values(fields.get(WRITEBACK_CONCLUSION_FIELD)) or "").strip()
    if not conclusion:
        return AI_REVIEW_STATUS_NONE, None
    report = (_extract_rich_text(fields.get(WRITEBACK_REPORT_FIELD)) or "").strip()
    raw_defects = fields.get(WRITEBACK_DEFECTS_FIELD)
    raw_list = raw_defects if isinstance(raw_defects, list) else [raw_defects]
    defects: list[str] = []
    for item in raw_list:
        text = (item if isinstance(item, str) else _extract_select_values(item)).strip()
        if text and text not in defects:
            defects.append(text)
    result: dict[str, Any] = {
        "agreement": None,
        "license": None,
        "insurance": None,
        "overall_conclusion": conclusion,
        "overall_report": report,
        "defect_categories": defects,
        "regulations": [],
    }
    return AI_REVIEW_STATUS_COMPLETED, result


def mapped_field_keys() -> tuple[str, ...]:
    """map_fields 产物键全集（懒求值：map_fields 纯函数，空输入即得键集）。"""
    return tuple((map_fields({}) or {}).keys())


def mapped_diff_key(values: Mapping[str, Any]) -> tuple:
    """映射字段值集 → 稳定 diff 键（触发器变更检测用，两侧同构）。

    附件字段只比 file_token 序列（预签名 url 每拉必变）；其余复合值 repr 归一；
    键排序保证「映射 dict」与「ORM 行取值 dict」同序可比。
    """
    items: list[tuple[str, Any]] = []
    for key in sorted(values):
        value = values[key]
        if key in _ATTACHMENT_DIFF_FIELDS:
            tokens = tuple(
                str(a.get("file_token") or "")
                for a in (value or [])
                if isinstance(a, dict)
            )
            items.append((key, tokens))
        elif isinstance(value, (list, dict)):
            items.append((key, repr(value)))
        else:
            items.append((key, value))
    return tuple(items)
