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

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_label": self.job_label,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "deferred": self.deferred,
            "failures": self.failures,
        }
