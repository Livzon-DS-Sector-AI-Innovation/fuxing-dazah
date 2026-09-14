"""AI 配置相关异常。"""

from __future__ import annotations


class ScenarioDisabledError(RuntimeError):
    """场景被熔断（ai_scenario_configs.enabled=false）时由统一入口抛出。

    业务侧应捕获并返回友好提示，不写 failed 审计、不触发失败通知。
    """
