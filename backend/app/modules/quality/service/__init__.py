"""Quality 业务逻辑编排包（service.py 拆分：原文件 1582 行，按 300 行规范拆为同名目录）。

对外导入路径保持不变：`from app.modules.quality.service import TestTaskService` 等。
"""

from app.modules.quality.service.helpers import (
    PARSER_REGISTRY,
    ParserEntry,
    _norm_date_str,
    spawn_background,
)
from app.modules.quality.service.lc_service import LcReportService, lc_report_service
from app.modules.quality.service.task_lifecycle import _TaskLifecycle
from app.modules.quality.service.task_parse import _TaskParse
from app.modules.quality.service.task_reports import _TaskReports


class TestTaskService(_TaskLifecycle, _TaskParse, _TaskReports):
    """检验任务编排：建任务快照、批量填报判定、状态流转。

    按职责拆分：核心助手（task_core）/ 生命周期（task_lifecycle）/
    液相解析（task_parse）/ 报表查询（task_reports）。
    """


test_task_service = TestTaskService()

__all__ = [
    "LcReportService",
    "PARSER_REGISTRY",
    "ParserEntry",
    "TestTaskService",
    "_norm_date_str",
    "lc_report_service",
    "spawn_background",
    "test_task_service",
]
