"""QA COA 域业务编排：客户标准配置 / docx 导入 / 出具登记 / 矩阵透视 / 模板回填。

子模块：ai_parse（DeepSeek 文档解析+提取，版式无关）/ docx_parse（域模型
与确定性文本工具）/ common（序列化与 404）/ standards（产品与标准 CRUD）/
import_standard（docx→标准草稿）/ issuance（报告登记、导入匹配、矩阵）/
report_log（出具登记操作日志：逐格前后快照）/ template_address（模板编址与
写入）/ template_bind（AI 标注+确定性校验+人工确认）/ template_render（按
标注回填登记数据）/ template_pdf（回填结果转 PDF 供快速打印，带缓存）/
render_archive（生成留档与验证）。
对外整包 re-export——api 层以 ``service.coa.X`` 调用。
"""

from app.modules.qa.service.coa.ai_parse import (
    COA_AI_PROMPT_VERSION_STRUCTURE,
    COA_AI_PROMPT_VERSION_VALUES,
    parse_docx_ai,
)
from app.modules.qa.service.coa.common import resolve_standard_fields
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
from app.modules.qa.service.coa.render_archive import (
    get_render_record_or_404,
    list_renders,
    read_render_file,
    verify_docx,
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
    restore_standard_fields,
    update_product,
    update_standard,
)
from app.modules.qa.service.coa.template_bind import (
    annotate_template,
    get_template,
    save_template_binding,
    upload_template,
)
from app.modules.qa.service.coa.template_pdf import (
    COA_PDF_MIME,
    print_failure_lines,
    render_report_pdf,
)
from app.modules.qa.service.coa.template_render import (
    COA_DOCX_MIME,
    build_report_docx,
    check_report_render,
    render_report_docx,
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
    "get_render_record_or_404",
    "get_report_detail",
    "import_report_preview",
    "list_renders",
    "list_reports",
    "matrix",
    "read_render_file",
    "update_report",
    "verify_docx",
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
    # 模板回填
    "COA_DOCX_MIME",
    "COA_PDF_MIME",
    "annotate_template",
    "build_report_docx",
    "check_report_render",
    "get_template",
    "print_failure_lines",
    "render_report_docx",
    "render_report_pdf",
    "save_template_binding",
    "upload_template",
]
