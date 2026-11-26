"""COA 模板标注：AI 判定「哪个字段写进哪个数据位」+ 确定性校验 + 人工确认。

原 ``template_bind.py`` 按职责拆成同名包，对外导入路径保持不变：

- fields：可回填的字段清单（批次信息字段 + 标准检测项目）
- formats：格式规则（小数位/单位/日期/补英文）与配置偏差
- review：确定性校验、提案组装、已保存标注的还原
- annotate：AI 标注（只产提案，不落库）
- store：模板文件与人工确认标注的存取
"""

from app.modules.qa.service.coa.template_bind.annotate import (
    _parse_annotation,
    _prompt_fields,
    annotate_template,
)
from app.modules.qa.service.coa.template_bind.fields import (
    TEMPLATE_EXCLUDED_BATCH_FIELDS,
    FieldDef,
    build_fields,
    field_defs,
    field_dict,
)
from app.modules.qa.service.coa.template_bind.formats import (
    _DRIFT_LINE_LIMIT,
    BUILTIN_VERDICTS,
    DEFAULTS,
    bilingual_pair,
    binding_drift,
    field_config,
    infer_format,
    match_date_pattern,
    normalize_fmt,
)
from app.modules.qa.service.coa.template_bind.review import (
    FLAG_LABELS,
    assemble,
    derive_slot,
    describe_binding,
    name_matches,
    plan_slot,
    result_residue,
)
from app.modules.qa.service.coa.template_bind.store import (
    BIND_PROMPT_VERSION,
    BINDING_VERSION,
    drift_by_standard,
    get_template,
    load_template_data,
    parse_template,
    save_template_binding,
    template_status,
    template_summary,
    upload_template,
)

__all__ = [
    "BINDING_VERSION",
    "BIND_PROMPT_VERSION",
    "BUILTIN_VERDICTS",
    "DEFAULTS",
    "FLAG_LABELS",
    "FieldDef",
    "TEMPLATE_EXCLUDED_BATCH_FIELDS",
    "_DRIFT_LINE_LIMIT",
    "_parse_annotation",
    "_prompt_fields",
    "annotate_template",
    "assemble",
    "binding_drift",
    "bilingual_pair",
    "build_fields",
    "describe_binding",
    "derive_slot",
    "drift_by_standard",
    "field_config",
    "field_defs",
    "field_dict",
    "get_template",
    "infer_format",
    "load_template_data",
    "match_date_pattern",
    "name_matches",
    "normalize_fmt",
    "parse_template",
    "plan_slot",
    "result_residue",
    "save_template_binding",
    "template_status",
    "template_summary",
    "upload_template",
]
