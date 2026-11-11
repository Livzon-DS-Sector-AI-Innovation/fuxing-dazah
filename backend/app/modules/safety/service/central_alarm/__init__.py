"""中控报警分析 Service 包 — re-export 公开对象（import 路径稳定）。"""

from app.modules.safety.service.central_alarm.aggregator import (
    CentralAlarmDailyAgg,
    CentralAlarmPeriodAgg,
    aggregate_daily,
    aggregate_period,
    get_natural_month_range,
    get_natural_week_range,
    prev_natural_month_range,
    prev_natural_week_range,
)
from app.modules.safety.service.central_alarm.analyst import CentralAlarmAnalyst
from app.modules.safety.service.central_alarm.bitable_mapper import (
    derive_workshop_line,
    map_bitable_fields,
)
from app.modules.safety.service.central_alarm.renderer import (
    render_daily_report,
    render_period_report,
)
from app.modules.safety.service.central_alarm.service import (
    CentralAlarmService,
    central_alarm_app_token,
    central_alarm_table_ids,
    run_daily_central_alarm_analysis,
    run_monthly_central_alarm_analysis,
    run_weekly_central_alarm_analysis,
)

__all__ = [
    "central_alarm_app_token",
    "central_alarm_table_ids",
    "CentralAlarmService",
    "CentralAlarmAnalyst",
    "CentralAlarmDailyAgg",
    "CentralAlarmPeriodAgg",
    "aggregate_daily",
    "aggregate_period",
    "get_natural_month_range",
    "get_natural_week_range",
    "prev_natural_month_range",
    "prev_natural_week_range",
    "run_daily_central_alarm_analysis",
    "run_monthly_central_alarm_analysis",
    "run_weekly_central_alarm_analysis",
    "derive_workshop_line",
    "map_bitable_fields",
    "render_daily_report",
    "render_period_report",
]
