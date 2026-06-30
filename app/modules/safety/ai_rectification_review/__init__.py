"""AI 整改初审插件 — 安全模块 AI 工作流扩展。

基于《AI隐患识别工作流设计方案》的架构模式，提供：
- AIRectificationReviewer: 整改回复初审引擎（独立可测试）
- RuleEngine: 输出规则验证器
- 完整的 Prompt 模板体系 + 数据库配置种子
- 输入/输出数据模型（Pydantic v2）

用法:
    from app.modules.safety.ai_rectification_review import (
        AIRectificationReviewer,
        RectificationReviewInput,
        PluginConfig,
    )
"""

from app.modules.safety.ai_rectification_review.plugin import (
    AIRectificationReviewer,
    ReviewError,
)
from app.modules.safety.ai_rectification_review.prompts import (
    build_context_text,
    build_full_prompt,
    get_db_seed_config,
    get_expected_keys,
)
from app.modules.safety.ai_rectification_review.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_rectification_review.schemas import (
    ComplianceLevel,
    MeasureQualityLevel,
    PhotoMatchLevel,
    PluginConfig,
    RectificationReviewInput,
    RectificationReviewOutput,
    ReviewConclusion,
    ValidationResult,
)

__all__ = [
    # 核心引擎
    "AIRectificationReviewer",
    "ReviewError",
    # 规则
    "RuleEngine",
    "auto_correct",
    # 数据模型
    "RectificationReviewInput",
    "RectificationReviewOutput",
    "ValidationResult",
    "PluginConfig",
    # 枚举
    "PhotoMatchLevel",
    "MeasureQualityLevel",
    "ComplianceLevel",
    "ReviewConclusion",
    # 工具
    "get_db_seed_config",
    "get_expected_keys",
    "build_full_prompt",
    "build_context_text",
]
