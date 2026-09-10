"""表1: 集团EHS审计缺陷整改跟进报告 2025.10.20"""
from datetime import date

AUDIT_TABLE_CONFIG: dict = {
    "name": "ehs_2025_1020",
    "label": "集团EHS审计 2025.10.20",
    "source": {
        "type": "bitable",
        "app_token": "IXNfb12Ugax6jEstoU5c5mTWnHc",
        "table_id": "tblZjzLCIROj9Q6P",
    },
    "defaults": {
        "discovered_at": date(2025, 10, 20),
        "discovered_by_name": "集团EHS审计组",
        "inspection_category": "集团EHS审计",
        "hazard_type": "unsafe_condition",
        "hazard_level": "general",
        "inspector_department": "",  # 取自隐患部门
    },
    "field_mapping": {
        "description": (
            "缺陷项描述",
            "text",
            "",
        ),
        "department": (
            "隐患部门",
            "single_select",
            "",
        ),
        "rectification_responsible_person_name": (
            "责任人",
            "person_name",
            "",
        ),
        "deadline": (
            "目标完成日期",
            "text_date_dot",  # "2025.04.30" → datetime, "——" → None
            None,
        ),
        "rectification_reply": (
            None,
            "combined_text",
            {
                "parts": ["整改方案", "整改情况"],
                "sep": "\n\n实施情况：",
                "prefix": {"整改方案": "整改方案：", "整改情况": ""},
            },
        ),
        "rectification_status": (
            "关闭状态",
            "enum",
            "pending",
            {"关闭": "closed"},
        ),
        "rectification_photos": (
            "验证材料",
            "attachments",
            None,
        ),
    },
}

# ============================================================
# 表1 特殊说明:
#   - 目标完成日期 是文本型 SingleSelect（非 DateTime），含 "——"、"需根据审批情况实施" 等非日期值
#   - 关闭状态 仅有一个选项 "关闭"，全部 23 条已关闭
#   - 缺少 discovered_at 和 discovered_by_name → 使用默认值
#   - 无 actual_completion_date 字段
# ============================================================
