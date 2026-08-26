"""HR 模块内部配置，完全收敛在模块内。

AI 相关配置统一走 app.core.config.Settings（与 .env 加载机制一致），
不再使用 os.getenv——避免部署时 .env.production 只被 pydantic-settings
读取而 os.environ 拿不到值导致 AI 功能静默失效。
"""

from app.core.config import get_settings

_settings = get_settings()

# AI 出题 / 人事问答 / 面试评价 / 胜任度分析
HR_AI_API_KEY: str = _settings.HR_AI_API_KEY
HR_AI_MODEL: str = _settings.HR_AI_MODEL or "deepseek-chat"
HR_AI_SYSTEM_PROMPT: str = _settings.HR_AI_SYSTEM_PROMPT or (
    "你是「小H」，原料药工厂人事管理助手。"
    "只基于查询结果回答人事问题，禁止编造。"
    "回答极其简洁，只陈述事实，不分析、不解释、不推理。"
    "禁止出现'根据规则'、'依据以上信息'等元话语。"
)
