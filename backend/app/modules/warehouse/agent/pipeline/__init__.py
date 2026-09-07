"""识别 Pipeline（S2）：recognizer → aligner → draft_flow → submit（S2 ticket 04 完整链）。

对外 re-export 稳定接口，内部模块经 ``warehouse.agent.pipeline`` 引入。
draft_flow 导入即注册 scene=receipt 确认回调（submit_receipt 真身，
draft_flow 注册处薄包装延迟 import 解 cards↔submit 模块环）。
"""

from app.modules.warehouse.agent.pipeline.aligner import (
    FUZZY_MIN_RATIO,
    MASTER_CACHE_TTL,
    AlignedReceipt,
    MaterialMasterEntry,
    align_batch,
    align_receipt,
    get_master_entries,
    match_material,
    normalize_name,
)
from app.modules.warehouse.agent.pipeline.draft_flow import (
    ACTIVE_STATUSES,
    DRAFT_NO_RETRIES,
    DRAFT_TTL_SECONDS,
    RECEIPT_SCENE,
    DraftFlowError,
    cancel_draft,
    create_receipt_draft,
    expire_stale,
    mark_aligned,
    send_confirm_card,
)
from app.modules.warehouse.agent.pipeline.recognizer import (
    OPTIONAL_FIELDS,
    RECOGNIZE_MAX_TOKENS,
    RECOGNIZE_PROMPT,
    RECOGNIZE_TEMPERATURE,
    REQUIRED_FIELDS,
    RecognizedField,
    RecognizedReceipt,
    build_receipt,
    build_vision_message,
    parse_receipt_payload,
    recognize_receipt,
    required_all_missing,
)
from app.modules.warehouse.agent.pipeline.submit import (
    ARRIVAL_STATUS_VALUE,
    ATTACHMENT_FIELD,
    CHECK_FIELDS,
    RECEIPT_TABLE,
    SUBMIT_MATERIAL_NAME_ENABLED,
    build_receipt_fields,
    submit_receipt,
)

__all__ = [
    "ACTIVE_STATUSES",
    "ARRIVAL_STATUS_VALUE",
    "ATTACHMENT_FIELD",
    "AlignedReceipt",
    "CHECK_FIELDS",
    "DRAFT_NO_RETRIES",
    "DRAFT_TTL_SECONDS",
    "DraftFlowError",
    "FUZZY_MIN_RATIO",
    "MASTER_CACHE_TTL",
    "MaterialMasterEntry",
    "OPTIONAL_FIELDS",
    "RECEIPT_SCENE",
    "RECEIPT_TABLE",
    "RECOGNIZE_MAX_TOKENS",
    "RECOGNIZE_PROMPT",
    "RECOGNIZE_TEMPERATURE",
    "REQUIRED_FIELDS",
    "SUBMIT_MATERIAL_NAME_ENABLED",
    "RecognizedField",
    "RecognizedReceipt",
    "align_batch",
    "align_receipt",
    "build_receipt",
    "build_receipt_fields",
    "build_vision_message",
    "cancel_draft",
    "create_receipt_draft",
    "expire_stale",
    "get_master_entries",
    "mark_aligned",
    "match_material",
    "normalize_name",
    "parse_receipt_payload",
    "recognize_receipt",
    "required_all_missing",
    "send_confirm_card",
    "submit_receipt",
]
