"""AI+安全日报配置读取——app_config 注册表 + bitable_config 连接。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.safety.app_config.store import store
from app.modules.safety.bitable_config.store import ConnectionView

#: bitable_config 域 key（registry 已登记 daily_report 域）
DOMAIN = "daily_report"

#: 四张表的 kind（与 bitable_config/registry.py KindInfo.kind 一致）
KIND_REPORTS = "reports"
KIND_SUMMARY = "summary"
KIND_ROSTER = "roster"
KIND_HISTORY = "history"

def enabled() -> bool:
    """功能总闸（SAFETY_DAILY_REPORT_ENABLED，默认关）。"""
    return bool(store.get_bool("SAFETY_DAILY_REPORT_ENABLED", False))


def chat_id() -> str:
    """日报目标群 chat_id（默认值唯一事实源=app_config registry）。"""
    return store.get_str("SAFETY_DAILY_REPORT_CHAT_ID") or ""


def connection(kind: str) -> ConnectionView | None:
    """读 daily_report 域内指定 kind 的连接（missing/disabled → None）。"""
    from app.modules.safety.bitable_config.store import store as bitable_store

    view = bitable_store.get_connection(DOMAIN, kind)
    if view is None or not view.enabled:
        return None
    return view


def bj_now() -> datetime:
    """北京时间当前时刻（日期口径统一 Asia/Shanghai）。"""
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def today_key(now: datetime | None = None) -> str:
    """日期键 YYYY-MM-DD（查重与拉取键）。"""
    dt = now or bj_now()
    return dt.strftime("%Y-%m-%d")


def normalize_date_key(date_key: str | None) -> str:
    """外部传入日期归一：None/空/格式非法 → 当天；截断带时间的输入。

    非 YYYY-MM-DD 的脏键若放行会生成查重永远命不中的孤儿记录。
    """
    import re

    text = (date_key or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return today_key()
    return text
