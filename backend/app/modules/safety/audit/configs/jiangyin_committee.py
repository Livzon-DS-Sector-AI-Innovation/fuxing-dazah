"""表4: 江阴管委会检查"""
from datetime import date

AUDIT_TABLE_CONFIG: dict = {
    "name": "jiangyin_committee",
    "label": "江阴管委会检查",
    "source": {
        "type": "bitable",
        "app_token": "NTGAbAJLPa1zyfsjYYacy0RHnve",
        "table_id": "tbl3b5BoaESaaYHD",
    },
    "defaults": {
        # 源表无检查日期字段 → 固定为审计检查日期 2026-04-10
        "discovered_at": date(2026, 4, 10),
        "discovered_by_name": "江阴管委会检查组",
        "inspection_category": "政府安全检查",
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
            "multi_select",
            "",
        ),
        "rectification_responsible_person_name": (
            "责任人",
            "person_name",
            "",
        ),
        "deadline": (
            "目标完成日期",
            "datetime_ms",
            None,
        ),
        "actual_completion_date": (
            "完成时间",
            "datetime_ms",
            None,
        ),
        "rectification_reply": (
            "整改方案",
            "text",
            "",
        ),
        "rectification_status": (
            "整改状态",
            "enum",
            "pending",
            {"已关闭": "closed", "未关闭": "pending"},
        ),
        "rectification_photos": (
            "验证材料",
            "attachments",
            None,
        ),
    },
}

# ============================================================
# 表4 特殊说明:
#   - 与表3（福清应急局）字段结构完全相同，共用映射逻辑
#   - 6/18 未关闭（33%）— 比例最高
#   - 未关闭的多涉及"需设计院设计诊断"，整改周期长
#   - 完全缺失检查日期
# ============================================================
