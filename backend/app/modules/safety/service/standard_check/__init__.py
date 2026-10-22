"""S1 目标责任与绩效——体系标准符合性核查引擎。

DESIGN：docs/DESIGN-安全目标责任与绩效模块-体系标准符合性核查引擎-20261021.md
- engine 判定纯函数（四态）
- metrics 指标注册表（metric_key → 取数器）
- page 聚合服务（三态信封）+ 总览健康度采集
- freeze 周期定格（二期：snapshot upsert + 季度速递格）
- history 历史定格聚合（二期：迎检/自评直接取定格结果）
"""

from app.modules.safety.service.standard_check.engine import (
    ST_IN_PROGRESS,
    ST_MISSED,
    ST_NO_DATA,
    ST_OK,
    MetricOutcome,
    MetricSpec,
    PeriodWindow,
    StandardRow,
    Verdict,
    judge,
    window_for,
)
from app.modules.safety.service.standard_check.freeze import (
    FreezeResult,
    FreezeTarget,
    build_compliance_cell,
    freeze_due,
    quarter_targets,
    send_standard_compliance_digest,
)
from app.modules.safety.service.standard_check.history import (
    build_standard_history,
)
from app.modules.safety.service.standard_check.page import (
    build_standard_check_page,
    build_standard_evidence,
    collect_goals_health,
)

__all__ = [
    "ST_IN_PROGRESS", "ST_MISSED", "ST_NO_DATA", "ST_OK",
    "MetricOutcome", "MetricSpec", "PeriodWindow", "StandardRow", "Verdict",
    "judge", "window_for",
    "build_standard_check_page", "build_standard_evidence",
    "collect_goals_health",
    "FreezeResult", "FreezeTarget", "build_compliance_cell", "freeze_due",
    "quarter_targets", "send_standard_compliance_digest",
    "build_standard_history",
]
