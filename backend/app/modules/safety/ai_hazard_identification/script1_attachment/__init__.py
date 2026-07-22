"""脚本1 AttachmentParser — 附件解析模块。"""

from app.modules.safety.ai_hazard_identification.script1_attachment.plugin import (
    AttachmentParser,
)
from app.modules.safety.ai_hazard_identification.script1_attachment.prompts import (
    get_db_seed_config,
)
from app.modules.safety.ai_hazard_identification.script1_attachment.rules import (
    AttachmentRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script1_attachment.schemas import (
    AttachmentInput,
    AttachmentOutput,
)

__all__ = [
    "AttachmentParser",
    "AttachmentInput",
    "AttachmentOutput",
    "AttachmentRuleEngine",
    "auto_correct",
    "get_db_seed_config",
]
