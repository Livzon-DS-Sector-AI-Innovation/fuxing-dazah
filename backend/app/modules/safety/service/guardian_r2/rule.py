"""R2 四规则声明 —— 全结构化（扫描源翻译层已算好 _derived，零文本操作符）。

- 规则1 复审提醒（observe 起步 → 回放验收后切 auto）：低风险、月度键防重
- 规则2 取消资格（**恒 observe**，promote=「经审核确认」，拍板需求原文）
- 规则3 资格恢复（**恒 observe**，promote 确认人留痕）
- 规则4 成绩映射（observe 起步 → auto）：合格/不合格才进决策（缺考零噪音）
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.guardian_r2.scan_source import R2_CERT_SOURCE_NAME

#: R2 成绩源实例名（迁移播种）
R2_SCORE_SOURCE_NAME = "safety.guardian.score"


def guardian_remind_rule() -> dict[str, Any]:
    """规则1：复审/换证提醒（_derived.trigger_type == remind）。"""
    return {
        "rule_id": "guardian_review_remind",
        "enabled": True,
        "source": R2_CERT_SOURCE_NAME,
        "executor": "guardian_remind_dm",
        "conditions": [
            {"field": "_derived.trigger_type", "op": "equals", "values": ["remind"]},
        ],
    }


def guardian_revoke_rule() -> dict[str, Any]:
    """规则2：取消资格（考核不合格；恒 observe 人工确认）。

    2026-11-06 拍板④：逾期对象不产 Trigger 不催办（大量为放弃考证/资格
    的存量）——取消资格只由「考核不合格」触发；_revoke_reason 同步收窄。
    """
    return {
        "rule_id": "guardian_qualification_revoke",
        "enabled": True,
        "source": R2_CERT_SOURCE_NAME,
        "executor": "guardian_qualify_revoke",
        "conditions": [
            {"field": "_derived.trigger_type", "op": "equals",
             "values": ["failed"]},
        ],
    }


def guardian_restore_rule() -> dict[str, Any]:
    """规则3：资格恢复（revoked 后新合格成绩；恒 observe 人工确认）。"""
    return {
        "rule_id": "guardian_qualification_restore",
        "enabled": True,
        "source": R2_CERT_SOURCE_NAME,
        "executor": "guardian_qualify_restore",
        "conditions": [
            {"field": "_derived.trigger_type", "op": "equals", "values": ["restore"]},
        ],
    }


def guardian_score_map_rule() -> dict[str, Any]:
    """规则4：成绩映射（成绩源；是否合格非空才进决策，缺考零噪音）。"""
    return {
        "rule_id": "guardian_score_map",
        "enabled": True,
        "source": R2_SCORE_SOURCE_NAME,
        "executor": "guardian_score_map",
        "conditions": [
            {"field": "_derived.passed", "op": "in", "values": ["合格", "不合格"]},
        ],
    }
