"""外部审计缺陷接入模块。

提供从外部 Bitable/Sheets 读取、解析、upsert 到平台隐患台账的完整管线。
不触发 AI 工作流、不发送通知、不回写源表。

用法:
    # 导入全部 7 张表
    from app.modules.safety.audit.service import import_all_audit_tables
    results = await import_all_audit_tables()

    # 导入单表
    from app.modules.safety.audit.service import import_audit_table
    result = await import_audit_table("ehs_2025_1020")
"""

from app.modules.safety.audit.configs import ALL_AUDIT_TABLES, AUDIT_TABLES_BY_NAME
from app.modules.safety.audit.parser import parse_record
from app.modules.safety.audit.reader import read_table
from app.modules.safety.audit.service import import_all_audit_tables, import_audit_table

__all__ = [
    "ALL_AUDIT_TABLES",
    "AUDIT_TABLES_BY_NAME",
    "read_table",
    "parse_record",
    "import_all_audit_tables",
    "import_audit_table",
]
