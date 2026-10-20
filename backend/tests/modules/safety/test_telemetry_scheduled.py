"""facilities-p2 票 03：采集 interval 任务注册与留痕节流语义。

不真起调度循环：直测 TaskDefinition 参数（照 test_safety_scheduled_bridge
风格）与 RunLogGate 节流（同状态不重写、状态变化写、换日写）。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.scheduled import TELEMETRY_COLLECT_TASK
from app.modules.safety.telemetry.collector import RunLogGate


def test_task_registered_with_interval_config():
    assert TELEMETRY_COLLECT_TASK.name == "safety.telemetry_collect"
    assert TELEMETRY_COLLECT_TASK.schedule.interval_seconds == 300  # 默认 5 分钟
    assert TELEMETRY_COLLECT_TASK.module == "safety"


def test_gate_throttles_same_outcome():
    gate = RunLogGate()
    d1, d2 = date(2026, 10, 20), date(2026, 10, 20)
    assert gate.should_log("telemetry_collect", "success", d1) is True   # 首行
    assert gate.should_log("telemetry_collect", "success", d2) is False  # 同状态不重写
    assert gate.should_log("telemetry_collect", "no_source", d2) is True  # 状态变化
    assert gate.should_log("telemetry_collect", "no_source", d2) is False


def test_gate_logs_again_next_day():
    gate = RunLogGate()
    assert gate.should_log("telemetry_collect", "success", date(2026, 10, 20))
    assert not gate.should_log("telemetry_collect", "success", date(2026, 10, 20))
    assert gate.should_log("telemetry_collect", "success", date(2026, 10, 21))  # 换日心跳


def test_gate_failure_always_logged_once_per_state():
    gate = RunLogGate()
    assert gate.should_log("telemetry_collect", "failed", date(2026, 10, 20))
    assert not gate.should_log("telemetry_collect", "failed", date(2026, 10, 20))
    assert gate.should_log("telemetry_collect", "success", date(2026, 10, 20))  # 恢复也写
