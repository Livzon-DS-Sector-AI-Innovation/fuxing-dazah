"""SOP AI 层 — 智能补全（逐章生成）与 AI 审核。

包结构（拆自原 sop_ai.py，外部 import 路径保持不变）：
- _prompts.py   静态 system prompt（前缀缓存友好）
- _validate.py  Schema 校验 / 结构规范化 / 质量自检
- _chapters.py  逐章 AI 主生成（ch7 优先落地，ch3/5/6/8/9 后续扩展）
- _knowledge.py 知识参考包构建（法规 RAG + MSDS 台账，为逐章生成补知识层）
- _complete.py  生成补全（单次调用版，逐步被逐章管线取代）
- _review.py    对照源文档的 AI 审核 + 章节重组

范式遵循 MSDS 提取模板（msds.py）：
    ai_audit_scope → create_ai_service("text") → chat_parsed
    system 提示词完全静态（前缀缓存友好），变量数据放 user 消息尾部。

re-export 采用「普通 import + __all__」形态：__all__ 声明了公开名称，
ruff F401 视为已使用，无需逐条 `X as X` 冗余别名。
"""

from __future__ import annotations

# ── 逐章生成（ch7 优先落地，ch3/5/6/8/9 已扩展）──
from ._chapters import (
    CH7_COVERAGE_THRESHOLD,
    CH7_MAX_RETRIES,
    baseline_stages,
    generate_ch3_risk,
    generate_ch5_params,
    generate_ch6_safety,
    generate_ch7_flow,
    generate_ch8_abnormal,
    generate_ch9_selection,
)
from ._complete import (
    MAX_RAW_TEXT_CHARS,
    sop_complete_document,
)
from ._knowledge import (
    RAG_TARGET_CHUNKS,
    build_knowledge_package,
)
from ._prompts import (
    SOP_CH3_SYSTEM_PROMPT,
    SOP_CH5_SYSTEM_PROMPT,
    SOP_CH6_SYSTEM_PROMPT,
    SOP_CH7_SYSTEM_PROMPT,
    SOP_CH8_SYSTEM_PROMPT,
    SOP_CH9_SYSTEM_PROMPT,
    SOP_COMPLETE_SYSTEM_PROMPT,
    SOP_REVIEW_SYSTEM_PROMPT,
    SOP_VISION_REVIEW_SYSTEM_PROMPT,
)
from ._review import (
    _CHAPTER_HEADING_RE,
    MAX_REVIEW_SOURCE_CHARS,
    VISION_REVIEW_BATCH_SIZE,
    _split_chapters,
    merge_reviews,
    reassemble_sop,
    sop_review_document,
    sop_review_document_vision,
)
from ._validate import (
    EMERGENCY_TYPES,
    MAX_ABNORMALS,
    MAX_CH7_STAGES,
    MAX_FLOW_STAGES,
    MAX_LAYOUT_ISSUES,
    MAX_PARAMS,
    MAX_RISK_ROWS,
    MAX_SAFETY_REQS,
    MAX_VISION_DIMENSIONS,
    PLACEHOLDER_MARKERS,
    REVIEW_DIMENSIONS,
    _validate_review,
    _validate_supplement,
    _validate_vision_review,
    assess_generation_quality,
    ch5_traceability,
    ch7_coverage,
    validate_ch3,
    validate_ch5,
    validate_ch6,
    validate_ch7,
    validate_ch8,
    validate_ch9,
)

__all__ = [
    "CH7_COVERAGE_THRESHOLD",
    "CH7_MAX_RETRIES",
    "baseline_stages",
    "generate_ch3_risk",
    "generate_ch5_params",
    "generate_ch6_safety",
    "generate_ch7_flow",
    "generate_ch8_abnormal",
    "generate_ch9_selection",
    "MAX_RAW_TEXT_CHARS",
    "sop_complete_document",
    "RAG_TARGET_CHUNKS",
    "build_knowledge_package",
    "SOP_CH3_SYSTEM_PROMPT",
    "SOP_CH5_SYSTEM_PROMPT",
    "SOP_CH6_SYSTEM_PROMPT",
    "SOP_CH7_SYSTEM_PROMPT",
    "SOP_CH8_SYSTEM_PROMPT",
    "SOP_CH9_SYSTEM_PROMPT",
    "SOP_COMPLETE_SYSTEM_PROMPT",
    "SOP_REVIEW_SYSTEM_PROMPT",
    "SOP_VISION_REVIEW_SYSTEM_PROMPT",
    "MAX_REVIEW_SOURCE_CHARS",
    "VISION_REVIEW_BATCH_SIZE",
    "_CHAPTER_HEADING_RE",
    "_split_chapters",
    "merge_reviews",
    "reassemble_sop",
    "sop_review_document",
    "sop_review_document_vision",
    "EMERGENCY_TYPES",
    "MAX_ABNORMALS",
    "MAX_CH7_STAGES",
    "MAX_FLOW_STAGES",
    "MAX_LAYOUT_ISSUES",
    "MAX_PARAMS",
    "MAX_RISK_ROWS",
    "MAX_SAFETY_REQS",
    "MAX_VISION_DIMENSIONS",
    "PLACEHOLDER_MARKERS",
    "REVIEW_DIMENSIONS",
    "_validate_review",
    "_validate_supplement",
    "_validate_vision_review",
    "assess_generation_quality",
    "ch5_traceability",
    "ch7_coverage",
    "validate_ch3",
    "validate_ch5",
    "validate_ch6",
    "validate_ch7",
    "validate_ch8",
    "validate_ch9",
]
