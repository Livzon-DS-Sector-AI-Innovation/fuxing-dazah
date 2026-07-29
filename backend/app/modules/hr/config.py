"""HR 模块内部配置，完全收敛在模块内。"""

import os

# AI 出题 / 面试评估（优先环境变量，兜底模块默认值）
HR_AI_API_KEY: str = os.getenv("HR_AI_API_KEY", "")
HR_AI_MODEL: str = os.getenv("HR_AI_MODEL", "deepseek-chat")
HR_AI_SYSTEM_PROMPT: str = os.getenv(
    "HR_AI_SYSTEM_PROMPT",
    "你是「小H」，原料药工厂人事管理助手。"
    "只基于查询结果回答人事问题，禁止编造。"
    "回答极其简洁，只陈述事实，不分析、不解释、不推理。"
    "禁止出现'根据规则'、'依据以上信息'等元话语。"
)
