"""R3 规则声明 —— 两源各一条（RuleEngineAssessor 按 rule.source 匹配源名）。

conditions 为空 = 源内一切 Trigger 皆信号（信号判定已在 Source 翻译层
完成：失败阈值/翻转语义/防风暴都在扫描侧，规则引擎只做路由到执行器）。

⚠️ 会合点：本组规则必须经 ``ensure_guardian_r2_policy()`` 组合播种
（append 进 R1+R2+HW 列表）；单播子集会把其他模块规则挤出现行版本。
"""

from __future__ import annotations

from typing import Any

#: R3 扫描源实例名（迁移播种 agent_sources.name；规则 source 过滤依据）
R3_SCAN_SOURCE_NAME = "safety.ops.selfheal"
#: R3 rag 直投载体行名（enabled 恒 false，仅归属；直投走 ingest_draft 不经轮询）
R3_RAG_SOURCE_NAME = "safety.ops.rag_inject"

#: R3 执行器名（两规则同绑）
R3_EXECUTOR = "r3_ops_heal"


def r3_ops_rules() -> list[dict[str, Any]]:
    """R3 两条规则（扫描源 + rag 直投源；executor=r3_ops_heal）。"""
    return [
        {
            "rule_id": "r3_ops_failure",
            "enabled": True,
            "source": R3_SCAN_SOURCE_NAME,
            "executor": R3_EXECUTOR,
            "conditions": [],
        },
        {
            "rule_id": "r3_ops_rag_signal",
            "enabled": True,
            "source": R3_RAG_SOURCE_NAME,
            "executor": R3_EXECUTOR,
            "conditions": [],
        },
    ]
