"""R3 信号纯函数 —— 信号类常量 / trigger external_id / thread_key 构造。

幂等范式对齐 BitablePollSource 指纹（external_id 内嵌状态），单测锚点：
任何构造改动都会被既有断言拦住。日期一律北京时间 ISO（YYYY-MM-DD）。
"""

from __future__ import annotations

import hashlib
from typing import Any

# ── 信号类（payload["signal"]；授权/路由只看它，永不读文本）──
SIGNAL_JOB_FAILED = "job_failed"
SIGNAL_JOB_RECOVERED = "job_recovered"      # job 行 failed→success 翻转（归属 failed 日）
SIGNAL_JOB_MISSED = "job_missed"            # D 日补发窗口耗尽仍 failed（漏审定局信号）
SIGNAL_RAG_DEGRADED = "rag_degraded"
SIGNAL_RAG_RECOVERED = "rag_recovered"
SIGNAL_PARKED = "effects_parked"
SIGNAL_DEADLETTER = "hazard_deadletter"
SIGNAL_DEP_RECOVERED = "dep_recovered"      # 上游依赖端点不可达→可达
SIGNAL_BATCH = "ops_batch"                  # 防风暴聚合

#: 恢复类信号（驱动收口核对分支，不重复诊断）
RECOVERY_SIGNALS = frozenset({
    SIGNAL_JOB_RECOVERED, SIGNAL_JOB_MISSED, SIGNAL_RAG_RECOVERED,
    SIGNAL_DEP_RECOVERED,
})

#: 新故障类信号（驱动诊断管线；防风暴 5 条上限适用）
FAILURE_SIGNALS = frozenset({
    SIGNAL_JOB_FAILED, SIGNAL_RAG_DEGRADED, SIGNAL_PARKED,
    SIGNAL_DEADLETTER, SIGNAL_BATCH,
})


# ── external_id / thread_key 构造（纯函数）──

def job_thread(job_name: str, fired_date: str) -> str:
    """job 信号线程：每任务每天一单（同日抖动反复聚同单）。"""
    return f"ops:job:{job_name}:{fired_date}"


def job_failed_eid(job_name: str, fired_date: str) -> str:
    return f"ops:job:{job_name}:{fired_date}:failed"


def job_recovered_eid(job_name: str, fired_date: str) -> str:
    return f"ops:job:{job_name}:{fired_date}:recovered"


def job_missed_eid(job_name: str, fired_date: str) -> str:
    """D 日漏审定局（窗口耗尽仍 failed；补跑与收口的确定性输入）。"""
    return f"ops:job:{job_name}:{fired_date}:missed"


def rag_thread(fired_date: str) -> str:
    return f"ops:rag:{fired_date}"


def rag_eid(fired_date: str, kind: str, ts: str) -> str:
    """kind ∈ degraded/recovered；同日多次抖动各投各的（ts 区分）。"""
    return f"ops:rag:{fired_date}:{kind}:{ts}"


def parked_eid(component: str, fired_date: str) -> str:
    return f"ops:parked:{component}:{fired_date}"


def deadletter_eid(fired_date: str) -> str:
    return f"ops:deadletter:{fired_date}"


def opsmisc_thread(fired_date: str) -> str:
    """parked/deadletter/batch 共用日常单线程。"""
    return f"ops:opsmisc:{fired_date}"


def batch_eid(fired_date: str, item_eids: list[str]) -> str:
    """防风暴聚合 trigger（清单指纹 → 稳定幂等键）。"""
    digest = hashlib.sha256("|".join(sorted(item_eids)).encode("utf-8")).hexdigest()[:12]
    return f"ops:batch:{fired_date}:{digest}"


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]


def dep_recovered_eid(task_id: str, endpoint: str) -> str:
    return f"ops:dep:{task_id}:{endpoint_hash(endpoint)}:recovered"


# ── R3 工单阶段（stage_facts["r3"]["stage"]；closed 用 task.status=ended 表达）──

R3_STAGE_DETECTED = "detected"
R3_STAGE_DIAGNOSED = "diagnosed"
R3_STAGE_REPAIRING = "repairing"
R3_STAGE_VERIFY_WAIT = "verify_wait"
R3_STAGE_NEEDS_HUMAN = "needs_human"

R3_STAGE_LABELS: dict[str, str] = {
    R3_STAGE_DETECTED: "已检出",
    R3_STAGE_DIAGNOSED: "已诊断",
    R3_STAGE_REPAIRING: "修复中",
    R3_STAGE_VERIFY_WAIT: "待收口",
    R3_STAGE_NEEDS_HUMAN: "需人工",
}

#: LLM 归因七分类（设计 §4.3；unknown=降级兜底）
ROOT_CAUSE_CLASSES = (
    "upstream_outage", "quota_exhausted", "network", "config_error",
    "data_issue", "code_bug", "unknown",
)


def r3_facts(task_stage_facts: dict[str, Any] | None) -> dict[str, Any]:
    """读取 stage_facts["r3"]（缺失返回空 dict；写入侧负责合并回写）。"""
    return dict((task_stage_facts or {}).get("r3") or {})


def r3_stage(task_status: str | None, task_stage_facts: dict[str, Any] | None) -> str:
    """现算 R3 工单阶段（观测口径统一走本函数；closed=task.status ended 表达）。"""
    if task_status == "ended":
        return "closed"
    return r3_facts(task_stage_facts).get("stage") or R3_STAGE_DETECTED
