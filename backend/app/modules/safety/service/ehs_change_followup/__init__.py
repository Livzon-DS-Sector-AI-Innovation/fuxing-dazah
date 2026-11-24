"""EHS 变更周度督办（周五提醒 + 周一总结，DESIGN 2026-11-24）。

- config：三道闸（总闸默认关 / 灰度收件人 / 排除清单）
- records：两表解析 + 关闭判定 + 周一分类（纯函数）
- cards：周五卡三态 + 两个速递格子（纯函数）
- service：编排（唯一测试接缝）
"""

from app.modules.safety.service.ehs_change_followup import cards, config, records
from app.modules.safety.service.ehs_change_followup.service import (
    run_friday_round,
    run_monday_summary,
)

__all__ = ["cards", "config", "records", "run_friday_round", "run_monday_summary"]
