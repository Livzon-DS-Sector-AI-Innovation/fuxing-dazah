"""五金库 superagent 规则声明 —— 三规则按 payload.event_type 分流到三执行器。

事件判定全部在 Source 翻译层完成（payload 全结构化）；规则引擎只判
event_type（零 AI、零文本操作符）。规则进全局 Policy 须经 safety 桥
组合播种（R1+R2+HW 三组合——单播会把其他模块规则从现行版本挤掉，
safety/superagent_bridge.ensure_guardian_r2_policy 是唯一会合点）。
"""

from __future__ import annotations

from typing import Any

from app.modules.warehouse.hardware.superagent.scan_source import (
    HARDWARE_ALERT_SOURCE_NAME,
)

#: 催办类事件（→ hardware_urge 执行器）
URGE_EVENT_TYPES = ("low_stock", "urgent_unpatched", "draft_backlog", "issue_timeout", "stale")


def hardware_alert_rules() -> list[dict[str, Any]]:
    """三规则声明（rule_id 稳定；内容升版走 Policy 版本化）。"""
    return [
        {
            "rule_id": "hardware_alert_urge",
            "enabled": True,
            "source": HARDWARE_ALERT_SOURCE_NAME,
            "executor": "hardware_urge",
            "conditions": [
                {"field": "payload.event_type", "op": "in", "values": list(URGE_EVENT_TYPES)},
            ],
        },
        {
            "rule_id": "hardware_digest_push",
            "enabled": True,
            "source": HARDWARE_ALERT_SOURCE_NAME,
            "executor": "hardware_digest_push",
            "conditions": [
                {"field": "payload.event_type", "op": "in", "values": ["daily_digest"]},
            ],
        },
        {
            "rule_id": "hardware_plan_draft",
            "enabled": True,
            "source": HARDWARE_ALERT_SOURCE_NAME,
            "executor": "hardware_plan_draft",
            "conditions": [
                {"field": "payload.event_type", "op": "in", "values": ["plan_draft"]},
            ],
        },
    ]
