"""日期归一化与效期计算纯函数测试。"""

from app.modules.quality.service import TestTaskService, _norm_date_str


def test_dot_format_normalized():
    assert _norm_date_str("2026.01.01") == "2026-01-01"


def test_slash_format_normalized():
    assert _norm_date_str("2026/01/01") == "2026-01-01"


def test_hyphen_unchanged():
    assert _norm_date_str("2026-01-01") == "2026-01-01"


def test_empty_returns_none():
    assert _norm_date_str("") is None
    assert _norm_date_str(None) is None


def test_expiry_years_minus_one_day():
    assert TestTaskService._calc_expiry("2026-09-01", "2年") == "2028-08-31"


def test_expiry_months():
    assert TestTaskService._calc_expiry("2026-09-01", "24个月") == "2028-08-31"


def test_expiry_leap_day():
    # 2/29 + 1 年 → 先钳到次年 2/28，再 -1 天 → 2/27（与前端 calcExpiry 同规则）
    assert TestTaskService._calc_expiry("2024-02-29", "1年") == "2025-02-27"


def test_expiry_unparseable_returns_none():
    assert TestTaskService._calc_expiry("2026-09-01", "未知") is None
    assert TestTaskService._calc_expiry("bad-date", "2年") is None
