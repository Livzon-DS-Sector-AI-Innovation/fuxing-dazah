"""AI 场景配置异常（叶子模块，零业务 import）。

``ScenarioDisabledError``：场景被停用（熔断主动拦截，非真实故障）。
只继承 ``Exception``（而非任何业务异常基类），保证调用点现有
``except Exception`` 均能捕获；``CancelledError`` 是 ``BaseException``
不会被 ``except Exception`` 吞掉——特意不用它。
"""

from __future__ import annotations


class ScenarioDisabledError(Exception):
    """场景被停用（熔断主动拦截，非真实故障）。"""

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        super().__init__(f"AI 场景已停用: {scenario}")


__all__ = ["ScenarioDisabledError"]
