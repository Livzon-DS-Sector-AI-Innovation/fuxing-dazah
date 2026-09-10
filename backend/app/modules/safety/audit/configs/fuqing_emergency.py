"""表3: 福清应急局检查"""
from datetime import date

AUDIT_TABLE_CONFIG: dict = {
    "name": "fuqing_emergency",
    "label": "福清应急局检查",
    "source": {
        "type": "bitable",
        "app_token": "F9kWb0B6IaeVGHswTvVclylPnhf",
        "table_id": "tblZc5jXkZbe8kIs",
    },
    "defaults": {
        # 源表无检查日期字段 → 固定为审计检查日期 2025-11-27
        "discovered_at": date(2025, 11, 27),
        "discovered_by_name": "福清应急局检查组",
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
            "完成时间",  # 表3独有：实际完成时间
            "datetime_ms",
            None,
        ),
        "rectification_reply": (
            "整改方案",
            "text",  # 仅有整改方案，无整改情况
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
# 表3 特殊说明:
#   - 与表4（江阴管委会）字段结构完全相同
#   - 有 完成时间 (actual_completion_date) DateTime 字段 ✅
#   - 无 整改情况 字段 → rectification_reply 仅含整改方案
#   - 整改状态 有"已关闭"和"未关闭"两个选项
#   - 序号全部为 null（不影响映射）
#   - 完全缺失检查日期 → discovered_at = None
#   - 3/40 未关闭
# ============================================================
