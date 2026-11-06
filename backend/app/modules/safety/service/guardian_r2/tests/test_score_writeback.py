"""R2 成绩映射 —— 写回字段构建 + 取证进名单推导 纯函数单测（T05）。

拍板④：辨别结果写回资格表三列（考核成绩/考核日期/考核类型）；换证分支
额外写「已换证日期」（成功延期换证，引擎以 renewed_date 重算下一周期）；
取证分支 create_record 进名单（取证日期=考核日期、三节点 +1/+2/+3 年）。
日期毫秒=UTC 零点（与 scan_source._ms_to_date 读回口径对称）。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.guardian_r2.writeback import (
    build_enroll_fields,
    build_writeback_fields,
    date_to_ms,
)
from app.modules.safety.service.guardian_r2.score_parse import ScoreFacts


def test_date_to_ms_utc_midnight_roundtrip() -> None:
    import datetime as dt

    ms = date_to_ms(date(2026, 12, 1))
    back = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).date()
    assert back == date(2026, 12, 1)


def _facts(passed="合格", exam_date=date(2026, 12, 1)) -> ScoreFacts:
    return ScoreFacts(
        person_name="张三", open_id="ou_wb", department="提炼工程一部",
        cert_category="guardian_a", passed=passed, exam_date=exam_date,
        score_value=88.0,
    )


def test_writeback_review_fields() -> None:
    """复审合格 → 三列写回（考核类型=复审）。"""
    fields = build_writeback_fields(_facts(), discriminated="复审")
    assert fields["考核成绩"] == "合格"
    assert fields["考核日期"] == date_to_ms(date(2026, 12, 1))
    assert fields["考核类型"] == "复审"
    assert "已换证日期" not in fields


def test_writeback_renew_fields() -> None:
    """换证合格 → 三列 + 已换证日期=考核日期（成功延期换证）。"""
    fields = build_writeback_fields(_facts(), discriminated="换证")
    assert fields["考核类型"] == "换证"
    assert fields["已换证日期"] == date_to_ms(date(2026, 12, 1))


def test_writeback_failed_score() -> None:
    """不合格也写回（台账可见失败尝试；节点不消费，取消资格走规则2）。"""
    fields = build_writeback_fields(
        _facts(passed="不合格"), discriminated="复审"
    )
    assert fields["考核成绩"] == "不合格"
    assert fields["考核类型"] == "复审"


def test_enroll_fields_full_cycle() -> None:
    """取证进名单：人员字段（open_id）/部门/取证日期=考核日期/三节点 1-2-3 年。"""
    fields = build_enroll_fields(_facts())
    assert fields["姓名"] == [{"id": "ou_wb"}]
    assert fields["部门"] == "提炼工程一部"
    assert fields["取证日期"] == date_to_ms(date(2026, 12, 1))
    assert fields["第一次复审截止日期"] == date_to_ms(date(2027, 12, 1))
    assert fields["第二次复审截止日期"] == date_to_ms(date(2028, 12, 1))
    assert fields["应换证日期"] == date_to_ms(date(2029, 12, 1))
    assert fields["考核成绩"] == "合格"
    assert fields["考核类型"] == "取证"
    assert fields["考核日期"] == date_to_ms(date(2026, 12, 1))
