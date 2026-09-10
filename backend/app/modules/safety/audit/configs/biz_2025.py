"""表5: 2025事业部EHS审计"""

AUDIT_TABLE_CONFIG: dict = {
    "name": "biz_2025",
    "label": "2025事业部EHS审计",
    "source": {
        "type": "bitable",
        "app_token": "EXuywsDQBio1MTko2zJckeHLnSe",
        "table_id": "tbl3HyVrsaxuYWhb",
    },
    "defaults": {
        # 审计时间字段存在但全部为 null → 用默认 None
        "discovered_at": None,
        "discovered_by_name": "事业部EHS审计组",
        "inspection_category": "事业部EHS审计",
        "hazard_type": "unsafe_condition",
        "hazard_level": "general",
        "inspector_department": "",
    },
    "field_mapping": {
        "description": (
            "缺陷项",  # 字段名与表1-4不同
            "text",
            "",
        ),
        "department": (
            "责任部门",  # 字段名不同
            "multi_select",
            "",
        ),
        "rectification_responsible_person_name": (
            "整改责任人",  # 字段名不同
            "person_name",
            "",
        ),
        "deadline": (
            "计划完成时间",  # 字段名不同
            "datetime_ms",
            None,
        ),
        # 无 actual_completion_date 字段，仅有计划完成时间
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
            "关闭状态",  # 字段名不同
            "enum",
            "pending",
            {"已关闭": "closed", "未关闭": "pending"},
        ),
        "rectification_photos": (
            "整改证据",  # 字段名不同
            "attachments",
            None,
        ),
        # 额外字段（优先用源表值，否则用默认值）
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
# 表5 特殊说明:
#   - 与表6（2026上半年事业部）字段结构完全相同
#   - 字段名体系与表1-4完全不同（缺陷项/责任部门/整改责任人/整改证据...）
#   - 有专用 纠正预防措施 字段 ← 最佳匹配
#   - 审计时间/审计人员 字段存在但全部为 null
#   - 无 actual_completion_date，仅计划完成时间
#   - 部门体系是子公司名（提炼一部/半合成中心...）非集团部门名
#   - 1/17 未关闭
# ============================================================
