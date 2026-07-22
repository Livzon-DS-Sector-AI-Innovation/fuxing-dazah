"""统一的应用时区与"当前时间/今天"工具。

全项目获取当前时间/今天都应通过本模块，避免：
- 各模块重复定义 ``CST = timezone(timedelta(hours=8))``；
- 误用裸 ``datetime.now()``（naive）写入 ``DateTime(timezone=True)`` 列，
  导致按数据库会话时区解释而偏移 8 小时。

约定：
- 业务日期计算、日志/显示、写入 timestamptz 列 → 一律用 :func:`now` / :func:`today`。
- :func:`now` 返回带 ``Asia/Shanghai`` 时区的 aware datetime；写入 timestamptz
  存的是等价 UTC 瞬时值，与直接用 UTC 完全一致，只是语义上以本地时区呈现。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# ponytail: 单厂在国内，时区值不变，固定常量即可；未来多区域再接入 Settings
APP_TZ = ZoneInfo("Asia/Shanghai")


def now() -> datetime:
    """当前时间（带 ``Asia/Shanghai`` 时区的 aware datetime）。"""
    return datetime.now(APP_TZ)


def today() -> date:
    """当前日期（按 ``Asia/Shanghai``）。"""
    return datetime.now(APP_TZ).date()


if __name__ == "__main__":
    # 自检：now() 必须带时区，today() 与 now().date() 一致
    n = now()
    assert n.tzinfo is not None, "now() 必须是 aware datetime"
    utc_offset = n.utcoffset()
    assert utc_offset is not None
    assert utc_offset.total_seconds() == 8 * 3600, "偏移必须为 +08:00"
    assert today() == n.date()
    print("ok", n.isoformat(), today().isoformat())
