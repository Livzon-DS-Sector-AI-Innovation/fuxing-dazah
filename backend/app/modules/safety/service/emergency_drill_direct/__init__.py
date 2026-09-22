"""emergency_drill 应急演练直读包（批次二-3）。

仅切查询面（API 列表/统计/详情 + Agent 查询工具）；事件链路（采集归集 +
评估 AI 触发 + 镜像维护）承载业务流转，整体保留不设闸门（spec §0 盘点结论）。
"""

from app.modules.safety.service.emergency_drill_direct import (  # noqa: F401
    config,
    query,
    reader,
    views,
)
