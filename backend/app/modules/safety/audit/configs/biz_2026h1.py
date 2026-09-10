"""表6: 2026上半年事业部EHS审计"""
from datetime import date

AUDIT_TABLE_CONFIG: dict = {
    "name": "biz_2026h1",
    "label": "2026上半年事业部EHS审计",
    "source": {
        "type": "bitable",
        "app_token": "SKaxbB3ijarqCIs5ciDcAyfgnfb",
        "table_id": "tbl9CyXyVroK1OJg",
    },
    "defaults": {
        # 源表无检查日期字段 → 固定为审计检查日期 2026-03-25
        "discovered_at": date(2026, 3, 25),
        "discovered_by_name": "事业部EHS审计组",
        "inspection_category": "事业部EHS审计",
        "hazard_type": "unsafe_condition",
        "hazard_level": "general",
        "inspector_department": "",
    },
    "field_mapping": {
        "description": (
            "缺陷项",
            "text",
            "",
        ),
        "department": (
            "责任部门",
            "multi_select",
            "",
        ),
        "rectification_responsible_person_name": (
            "整改责任人",
            "person_name",
            "",
        ),
        "deadline": (
            "计划完成时间",
            "datetime_ms",
            None,
        ),
        "rectification_reply": (
            None,
            "combined_text",
            {
                "parts": ["纠正预防措施", "最新整改情况描述"],
                "sep": "\n\n最新进展：",
                "prefix": {"纠正预防措施": "纠正预防措施：", "最新整改情况描述": ""},
            },
        ),
        "rectification_status": (
            "关闭状态",
            "enum",
            "pending",
            {"已关闭": "closed", "未关闭": "pending"},
        ),
        "rectification_photos": (
            "整改证据",
            "attachments",
            None,
        ),
        "discovered_at": (
            "审计时间",
            "text_date_dot",
            None,
        ),
        "discovered_by_name": (
            "审计人员",
            "text",
            "",
        ),
    },
}

# ============================================================
# 表6 特殊说明:
#   - 与表5（2025事业部）字段结构完全相同，仅多"备注"Url字段
#   - 侧重安全管理体系审计（法规库/应急演练/ESG）非现场排查
#   - 2/13 未关闭
# ============================================================
