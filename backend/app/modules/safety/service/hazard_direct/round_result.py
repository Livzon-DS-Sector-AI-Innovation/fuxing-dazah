"""hazard_direct 单轮执行结果（①~⑤ 轮共享 dataclass）。

自 ai_analysis.py 提取（2026-11-05，⑤评分轮复用，无行为变化）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoundResult:
    """单轮执行结果。"""

    # 默认空串保持旧调用兼容（原 ai_analysis 内默认「隐患AI分析轮询」；
    # 各轮现都显式传标签，仅测试桩可省）
    job_label: str = ""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    # 失败治理退避：本轮「未到重试点 / 已死信」而跳过、不调 AI 的条数（A5）
    deferred: int = 0
    # 失败明细：{"record_id", "category", "reason"}（category 见 spec 失败分类）
    failures: list[dict[str, str]] = field(default_factory=list)
    # 基础设施失败（RAG 不可用 / AI 端点欠费/鉴权/超时/配置等）：不计 attempts、
    # 不进死信；failed 维持全量（= infra_failed + non_infra_failed）。
    infra_failed: int = 0
    # 基础设施失败明细：{"record_id", "category", "reason"}，供调度/告警按类聚合
    infra_failures: list[dict[str, str]] = field(default_factory=list)
    # C5(F9) RAG 全局降级短路熔断：本轮连续 retrieval_degraded 达阈值后跳过剩余
    # 记录（仅影响本轮，下一轮重新计数）；调度/告警可据此观察本轮降级范围。
    breaker_tripped: bool = False

    @property
    def non_infra_failed(self) -> int:
        """记录级失败数（用于调度器「连续失败轮数」累计，infra-only 轮不计）。"""
        return max(0, self.failed - self.infra_failed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_label": self.job_label,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "deferred": self.deferred,
            "failures": self.failures,
            "infra_failed": self.infra_failed,
            "non_infra_failed": self.non_infra_failed,
            "breaker_tripped": self.breaker_tripped,
        }
