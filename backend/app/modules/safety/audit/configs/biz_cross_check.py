"""表7: 事业部交叉检查缺陷项汇总表 2026.07 (Feishu Sheets)"""
from datetime import date

# Feishu Sheets 列索引 → 中文表头映射（行 2 = 表头行）
SHEETS_COLUMNS = [
    "序号",           # A → idx 0
    "分类/模块",       # B → idx 1
    "缺陷项",          # C → idx 2
    "纠正预防措施",     # D → idx 3
    "整改责任人",       # E → idx 4
    "计划完成时间",     # F → idx 5
    "关闭状态",        # G → idx 6
]

AUDIT_TABLE_CONFIG: dict = {
    "name": "biz_cross_check",
    "label": "事业部交叉检查 2026.07",
    "source": {
        "type": "sheets",
        "spreadsheet_token": "DtHHwuAiNibmxZkcnm1cNuKdnDb",
        "sheet_id": "0fThEJ",
        "range": "A3:G14",  # 行3=第1条数据，行14=第12条数据
        "header_row_index": 0,  # 从 range 第0行取表头
        "columns": SHEETS_COLUMNS,
    },
    "defaults": {
        "discovered_at": date(2026, 7, 1),  # 标题推断 2026.07 → 默认为月初
        "discovered_by_name": "事业部交叉检查组",
        "inspection_category": "事业部交叉检查",
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
            "分类/模块",  # "车间四"/"罐区"/"中控室" — 非标准部门名
            "text",
            "",
        ),
        "rectification_responsible_person_name": (
            "整改责任人",
            "text",  # Sheets 中是纯文本姓名，非 User 对象
            "",
        ),
        "deadline": (
            "计划完成时间",
            "text_date_any",  # "2026.08.10" / "立即整改" / "2026.10.30"
            None,
        ),
        "rectification_reply": (
            "纠正预防措施",
            "text",
            "",
        ),
        "rectification_status": (
            "关闭状态",
            "enum",
            "pending",  # 全部为空 → pending
            {"已关闭": "closed", "未关闭": "pending"},
        ),
        # 无附件字段
    },
}

# ============================================================
# 表7 特殊说明:
#   - 唯一一个 Feishu Sheets（Excel）类型的表，非 Bitable
#   - 关闭状态全部为空 → 12条全部 pending（2026.07 最新检查）
#   - 计划完成时间 是文本格式，含 "立即整改" 等非日期值
#   - 整改责任人 是纯文本（非飞书 User 对象）→ 无法解析 open_id
#   - 分类/模块 替代部门（"车间四"/"罐区"/"中控室" 非标准名）
#   - 无附件/整改证据
#   - feishu_record_id: "{spreadsheet_token}:row{N}" (N=数据行号)
# ============================================================
