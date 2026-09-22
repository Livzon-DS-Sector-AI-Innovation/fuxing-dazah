"""contractor_admission AI 回写 3 列契约（Ticket 02）。

探针（2026-09-22，survey_contractor_admission.py）证实 3 列已在 Bitable
「承包商材料跟进表」（tblVWu4ENcUJWoDT），值域与 ai_contractor_review 插件完全一致；
本契约固化列名/类型/值域，供直读派生（views）与回写白名单（service._writeback_review
直读分支、verify 脚本两态断言）共同引用，禁止散落字面量。
"""

from __future__ import annotations

__all__ = [
    "WRITEBACK_CONCLUSION_FIELD",
    "WRITEBACK_REPORT_FIELD",
    "WRITEBACK_DEFECTS_FIELD",
    "WRITEBACK_FIELD_TYPES",
    "CONCLUSION_VALUES",
    "DEFECT_CATEGORY_VALUES",
    "CREATED_AT_FIELD",
]

# Bitable 中文列名 → 类型（1=text / 3=single_select / 4=multi_select）
WRITEBACK_CONCLUSION_FIELD = "AI审核结论"
WRITEBACK_REPORT_FIELD = "AI审核报告"
WRITEBACK_DEFECTS_FIELD = "AI不符合项"

WRITEBACK_FIELD_TYPES: dict[str, int] = {
    WRITEBACK_CONCLUSION_FIELD: 3,
    WRITEBACK_REPORT_FIELD: 1,
    WRITEBACK_DEFECTS_FIELD: 4,
}

# 结论三标准值（ai_contractor_review.schemas.ReviewConclusion 同值域）
CONCLUSION_VALUES = ("审核通过", "需补充完善", "审核不通过")

# 不符合项 4 类标准值（ai_contractor_review.plugin._CATEGORY_PREFIX_MAP 同值域）
DEFECT_CATEGORY_VALUES = (
    "安全管理协议-A基础信息类",
    "安全管理协议-B有效期类",
    "安全管理协议-C签章类",
    "安全管理协议-D骑缝章类",
)

# 创建时间公式列（type=1001；直读视图 created_at 来源，探针 109 行全有值）
CREATED_AT_FIELD = "创建日期"
