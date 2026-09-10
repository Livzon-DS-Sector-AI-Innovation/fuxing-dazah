"""表2: 集团下半年EHS审计 2025.11.13"""
from datetime import date

AUDIT_TABLE_CONFIG: dict = {
    "name": "ehs_2025_1113",
    "label": "集团下半年EHS审计 2025.11.13",
    "source": {
        "type": "bitable",
        "app_token": "FDCObQ3c6aEwkIsLRAvcXPo7nZb",
        "table_id": "tblkDClIyE9ARhjx",
    },
    "defaults": {
        "discovered_at": date(2025, 11, 13),
        "discovered_by_name": "集团EHS审计组",
        "inspection_category": "集团EHS审计",
        "hazard_type": "unsafe_condition",
        "hazard_level": "general",
        "inspector_department": "",
    },
    "field_mapping": {
        "description": (
            "缺陷项描述",
            "text",
            "",
        ),
        "department": (
            "隐患部门",
            "multi_select",  # 表1是 single_select，这里是 multi_select
            "",
        ),
        "rectification_responsible_person_name": (
            "责任人",
            "person_name",  # User 多选 → join names
            "",
        ),
        "deadline": (
            "目标完成日期",
            "datetime_ms",  # 真正的 DateTime 字段
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
        # 额外字段: discovered_at 优先用源表值（仅 1/15 有）
        "discovered_at": (
            "检查时间",
            "text_date_dot",
            None,  # 解析失败用 defaults
        ),
        "discovered_by_name": (
            "集团检查人员",
            "person_name",
            "",  # 仅 1/15 有
        ),
    },
}

# ============================================================
# 表2 特殊说明:
#   - 隐患部门 是 MultiSelect（与表1不同）
#   - 目标完成日期 是真正的 DateTime (Unix ms)
#   - 责任人 是多选 User
#   - 有 集团检查人员 和 检查时间 字段（仅1/15有值）
#   - 无 actual_completion_date 和 inspector_department 字段
#   - 3/15 未关闭 → 需督办
# ============================================================
