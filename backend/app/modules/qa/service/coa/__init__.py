"""QA COA 域业务编排：客户标准配置 / docx 导入 / 出具登记 / 矩阵透视。

子模块：ai_parse（DeepSeek 文档解析+提取，版式无关）/ docx_parse（域模型
与确定性文本工具）/ common（序列化与 404）/ standards（产品与标准 CRUD）/
import_standard（docx→标准草稿）/ issuance（报告登记、导入匹配、矩阵）。
对外整包 re-export——api 层以 ``service.coa.X`` 调用。
"""

from app.modules.qa.service.coa.ai_parse import (
    COA_AI_PROMPT_VERSION_STRUCTURE,
    COA_AI_PROMPT_VERSION_VALUES,
    parse_docx_ai,
)
from app.modules.qa.service.coa.docx_parse import (
    CoaDocxParse,
    CoaParsedField,
    CoaParsedItem,
    item_code,
    normalize,
    parse_date_text,
    parse_number,
    parse_spec,
    split_bilingual,
)
from app.modules.qa.service.coa.import_standard import import_standard_preview
from app.modules.qa.service.coa.issuance import (
    create_report,
    delete_report,
    get_report_detail,
    import_report_preview,
    list_reports,
    matrix,
    update_report,
)
from app.modules.qa.service.coa.standards import (
    create_product,
    create_standard,
    delete_standard,
    get_standard_detail,
    list_product_fields,
    list_products,
    list_standards,
    replace_items,
    replace_product_fields,
    replace_standard_fields,
    resolve_standard_fields,
    restore_standard_fields,
    update_product,
    update_standard,
)

__all__ = [
    "COA_AI_PROMPT_VERSION_STRUCTURE",
    "COA_AI_PROMPT_VERSION_VALUES",
    "CoaDocxParse",
    "CoaParsedField",
    "CoaParsedItem",
    "item_code",
    "normalize",
    "parse_date_text",
    "parse_docx_ai",
    "parse_number",
    "parse_spec",
    "split_bilingual",
    "import_standard_preview",
    "create_report",
    "delete_report",
    "get_report_detail",
    "import_report_preview",
    "list_reports",
    "matrix",
    "update_report",
    "create_product",
    "create_standard",
    "delete_standard",
    "get_standard_detail",
    "list_product_fields",
    "list_products",
    "list_standards",
    "replace_items",
    "replace_product_fields",
    "replace_standard_fields",
    "resolve_standard_fields",
    "restore_standard_fields",
    "update_product",
    "update_standard",
]
