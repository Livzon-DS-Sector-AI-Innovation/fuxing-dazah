"""识别相关纯函数测试（无 DB、无网络）。

报告字段识别统一走 AI 视觉（外部 API），不做单元测试；此处覆盖日期计算。
"""

from datetime import date

from app.modules.meter.ai_service import calc_next_calibration_date

# ── calc_next_calibration_date ──


def test_next_date_with_cycle():
    assert calc_next_calibration_date(date(2026, 4, 13), 12) == date(2027, 4, 12)


def test_next_date_default_cycle():
    assert calc_next_calibration_date(date(2026, 1, 15), None) == date(2027, 1, 14)


def test_next_date_month_end():
    # 2026-01-31 + 1 个月 = 2026-02-28（relativedelta 自动夹取），-1 天 = 02-27
    assert calc_next_calibration_date(date(2026, 1, 31), 1) == date(2026, 2, 27)


# ── call_ai_vision_extract_report_fields 日期归一化 ──


async def test_extract_report_fields_normalizes_chinese_date(monkeypatch):
    """AI 返回中文日期时应归一化为 ISO，避免 Pydantic date 校验 500。"""

    async def fake_chat(api_url, api_key, model, images, prompt, **kwargs):
        return (
            '{"instrument_name": "压力表", "serial_number": "SN-1", '
            '"certificate_no": "C-1", "calibration_date": "2024年3月5日"}'
        )

    monkeypatch.setattr("app.modules.meter.ai_service._call_ai_chat", fake_chat)
    from app.modules.meter.ai_service import call_ai_vision_extract_report_fields

    fields = await call_ai_vision_extract_report_fields("u", "k", "m", ["img"])
    assert fields["calibration_date"] == "2024-03-05"
    assert fields["instrument_name"] == "压力表"


async def test_extract_report_fields_unparsable_date_becomes_none(monkeypatch):
    """AI 返回无法解析的日期时应置空而不是透传导致 500。"""

    async def fake_chat(api_url, api_key, model, images, prompt, **kwargs):
        return '{"calibration_date": "不是日期"}'

    monkeypatch.setattr("app.modules.meter.ai_service._call_ai_chat", fake_chat)
    from app.modules.meter.ai_service import call_ai_vision_extract_report_fields

    fields = await call_ai_vision_extract_report_fields("u", "k", "m", ["img"])
    assert fields["calibration_date"] is None
