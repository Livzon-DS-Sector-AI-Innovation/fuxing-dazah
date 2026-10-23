"""AI 签到/成绩单解析插件（链3，vision）。

对外：TrainingRecordParsingPlugin / TrainingRecordParseInput /
TrainingRecordParseOutput / TrainingRecordParsingError / 单据类型与
confidence 常量。
"""

from app.modules.safety.ai_training_record_parsing.plugin import (
    TrainingRecordParsingError,
    TrainingRecordParsingPlugin,
)
from app.modules.safety.ai_training_record_parsing.schemas import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LEVELS,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DOC_SCORE,
    DOC_SIGN_IN,
    DOC_TYPES,
    DOC_UNKNOWN,
    TrainingRecordParseInput,
    TrainingRecordParseOutput,
)

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LEVELS",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "DOC_SCORE",
    "DOC_SIGN_IN",
    "DOC_TYPES",
    "DOC_UNKNOWN",
    "TrainingRecordParseInput",
    "TrainingRecordParseOutput",
    "TrainingRecordParsingError",
    "TrainingRecordParsingPlugin",
]
