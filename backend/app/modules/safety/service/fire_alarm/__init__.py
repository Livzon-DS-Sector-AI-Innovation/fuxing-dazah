"""消防报警分析服务包。

保持 import 路径 from app.modules.safety.service.fire_alarm import FireAlarmService
稳定（参照 ai_hazard_analysis 包模式）。
"""

from app.modules.safety.service.fire_alarm.service import FireAlarmService

__all__ = ["FireAlarmService"]
