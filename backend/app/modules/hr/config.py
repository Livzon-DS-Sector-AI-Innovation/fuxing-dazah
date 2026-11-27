"""HR 模块内部配置，完全收敛在模块内。

凭证类配置（AI key、飞书应用）走 app.core.config.Settings（与 .env 加载机制一致），
不再使用 os.getenv——避免部署时 .env.production 只被 pydantic-settings
读取而 os.environ 拿不到值导致 AI 功能静默失效。

固定行为/数据型取值直接作为模块常量维护，不进 .env——
它们跨环境无差异，放环境变量只会形成"配了但永远是默认值"的死配置。
"""

from app.core.config import get_settings

_settings = get_settings()

# AI 出题 / 人事问答 / 面试评价 / 胜任度分析
HR_AI_API_KEY: str = _settings.HR_AI_API_KEY
HR_AI_MODEL: str = _settings.HR_AI_MODEL or "deepseek-chat"

# 人事问答系统提示词（固定行为，非环境差异；调整提示词直接改这里）
HR_AI_SYSTEM_PROMPT: str = (
    "你是「小H」，原料药工厂人事管理助手。"
    "只基于查询结果回答人事问题，禁止编造。"
    "回答极其简洁，只陈述事实，不分析、不解释、不推理。"
    "禁止出现'根据规则'、'依据以上信息'等元话语。"
)

# 面试日程同步的飞书日历：primary=应用主日历，改用团队日历时换成对应 calendar_id
HR_FEISHU_CALENDAR_ID: str = "primary"
