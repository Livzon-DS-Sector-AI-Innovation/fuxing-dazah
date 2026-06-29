"""AI隐患识别 + 危险源辨识插件 — 安全模块 AI 工作流核心。

本包提供两套 AI 工作流引擎：

1. AI 隐患识别（已有）
   - AIHazardIdentifier: 核心识别引擎（独立可测试）
   - RuleEngine: 输出规则验证器
   - 完整的 Prompt 模板体系 + 数据库配置种子
   - 输入/输出数据模型（Pydantic v2）

2. AI 危险源辨识（新增 — 方案B Plugin 架构）
   - 7 个独立 Plugin（脚本1-7），对标 AIHazardIdentifier 的 4-phase pipeline
   - BasePlugin: 共享 pipeline 基类
   - HazardIdentificationOrchestrator: 编排器（状态机 + DB 映射）
   - 每步独立可测试、独立可配置、独立可演进

用法:
    # AI 隐患识别
    from app.modules.safety.ai_hazard_identification import (
        AIHazardIdentifier,
        HazardIdentificationInput,
        PluginConfig,
    )

    # AI 危险源辨识
    from app.modules.safety.ai_hazard_identification import (
        HazardIdentificationOrchestrator,
        AttachmentParser,
        HazardIdentifier,
        InherentRiskAssessor,
    )
"""

# ── 现有 AI 隐患识别（保持不变）──
# ── 危险源辨识 方案B Plugin 架构（新增）──
from app.modules.safety.ai_hazard_identification._base import (
    BasePlugin,
    PluginError,
    UnknownValueError,
)
from app.modules.safety.ai_hazard_identification.orchestrator import (
    HazardIdentificationOrchestrator,
    OrchestratorError,
)
from app.modules.safety.ai_hazard_identification.plugin import (
    AIHazardIdentifier,
    IdentificationError,
)
from app.modules.safety.ai_hazard_identification.prompts import (
    build_context_text,
    build_full_prompt,
    get_db_seed_config,
    get_expected_keys,
)
from app.modules.safety.ai_hazard_identification.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.schemas import (
    HazardCategoryEnum,
    HazardIdentificationInput,
    HazardIdentificationOutput,
    HazardLevelEnum,
    HazardTypeEnum,
    PluginConfig,
    RectificationSuggestion,
    ValidationResult,
)

# 脚本1: 附件解析
from app.modules.safety.ai_hazard_identification.script1_attachment import (
    AttachmentInput,
    AttachmentOutput,
    AttachmentParser,
    AttachmentRuleEngine,
)

# 脚本2: AI 危险源辨识
from app.modules.safety.ai_hazard_identification.script2_hazard_id import (
    VALID_HAZARD_TYPES_6441,
    HazardIdentifier,
    HazardIdInput,
    HazardIdOutput,
    HazardIdRuleEngine,
)

# 脚本3: LEC 固有风险评价
from app.modules.safety.ai_hazard_identification.script3_inherent_risk import (
    LEC_SCORING_GUIDE,
    RISK_LEVEL_TABLE,
    VALID_C_VALUES,
    VALID_E_VALUES,
    VALID_L_VALUES,
    InherentRiskAssessor,
    InherentRiskInput,
    InherentRiskOutput,
    InherentRiskRuleEngine,
    LECOutput,
)

# 脚本4: 现有控制措施识别
from app.modules.safety.ai_hazard_identification.script4_controls import (
    ControlMeasureExtractor,
    ControlsInput,
    ControlsOutput,
    ControlsRuleEngine,
)

# 脚本5: 残余风险 LEC 评价
from app.modules.safety.ai_hazard_identification.script5_residual_risk import (
    ResidualRiskAssessor,
    ResidualRiskInput,
    ResidualRiskOutput,
    ResidualRiskRuleEngine,
)

# 脚本6: 建议措施生成
from app.modules.safety.ai_hazard_identification.script6_recommendations import (
    RecommendationGenerator,
    RecommendationInput,
    RecommendationOutput,
    RecommendationRuleEngine,
)

# 脚本7: 措施后风险 LEC 评价
from app.modules.safety.ai_hazard_identification.script7_post_risk import (
    PostMeasureAssessor,
    PostRiskInput,
    PostRiskOutput,
    PostRiskRuleEngine,
)

__all__ = [
    # ── 核心引擎（隐患识别）──
    "AIHazardIdentifier",
    "IdentificationError",
    # ── 规则（隐患识别）──
    "RuleEngine",
    "auto_correct",
    # ── 数据模型（隐患识别）──
    "HazardIdentificationInput",
    "HazardIdentificationOutput",
    "RectificationSuggestion",
    "ValidationResult",
    "PluginConfig",
    # ── 枚举（隐患识别）──
    "HazardTypeEnum",
    "HazardCategoryEnum",
    "HazardLevelEnum",
    # ── 工具（隐患识别）──
    "get_db_seed_config",
    "get_expected_keys",
    "build_full_prompt",
    "build_context_text",
    # ── 危险源辨识 基类 + 编排器 ──
    "BasePlugin",
    "PluginError",
    "UnknownValueError",
    "HazardIdentificationOrchestrator",
    "OrchestratorError",
    # ── 脚本1: 附件解析 ──
    "AttachmentParser",
    "AttachmentInput",
    "AttachmentOutput",
    "AttachmentRuleEngine",
    # ── 脚本2: 危险源辨识 ──
    "HazardIdentifier",
    "HazardIdInput",
    "HazardIdOutput",
    "HazardIdRuleEngine",
    "VALID_HAZARD_TYPES_6441",
    # ── 脚本3: LEC 固有风险 ──
    "InherentRiskAssessor",
    "LECOutput",
    "InherentRiskInput",
    "InherentRiskOutput",
    "InherentRiskRuleEngine",
    "LEC_SCORING_GUIDE",
    "RISK_LEVEL_TABLE",
    "VALID_L_VALUES",
    "VALID_E_VALUES",
    "VALID_C_VALUES",
    # ── 脚本4: 控制措施 ──
    "ControlMeasureExtractor",
    "ControlsInput",
    "ControlsOutput",
    "ControlsRuleEngine",
    # ── 脚本5: 残余风险 ──
    "ResidualRiskAssessor",
    "ResidualRiskInput",
    "ResidualRiskOutput",
    "ResidualRiskRuleEngine",
    # ── 脚本6: 建议措施 ──
    "RecommendationGenerator",
    "RecommendationInput",
    "RecommendationOutput",
    "RecommendationRuleEngine",
    # ── 脚本7: 措施后风险 ──
    "PostMeasureAssessor",
    "PostRiskInput",
    "PostRiskOutput",
    "PostRiskRuleEngine",
]
