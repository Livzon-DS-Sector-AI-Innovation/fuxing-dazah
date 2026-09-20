"""按日查询报告单的日期边界回归测试：必须按北京时间计日。

背景 bug：流水号/按日归档曾用 UTC 计日，北京 00:00–07:59 生成的报告
会被归到前一天。本测试构造跨「北京午夜」的记录，断言按北京日归属。
"""

from datetime import datetime

from app.core.time import APP_TZ
from app.modules.quality.models import ReportRecord
from app.modules.quality.repository import list_report_records_by_date


def _rec(batch: str, created_at: datetime) -> ReportRecord:
    return ReportRecord(
        template_path="tpl.docx",
        product_name="测试产品",
        batch_number=batch,
        serial_no=batch,  # 流水号唯一索引要求测试数据各不相同
        created_at=created_at,
    )


async def test_day_boundary_is_beijing_time(db_session):
    # 北京 9-20 00:30 = UTC 9-19 16:30：必须归到 9-20（按 UTC 计日会归到 9-19）
    early_beijing = _rec("B-EARLY", datetime(2026, 9, 20, 0, 30, tzinfo=APP_TZ))
    # 北京 9-19 17:00 = UTC 9-19 09:00：必须归到 9-19
    late_beijing = _rec("B-LATE", datetime(2026, 9, 19, 17, 0, tzinfo=APP_TZ))
    db_session.add_all([early_beijing, late_beijing])
    await db_session.flush()

    day19 = await list_report_records_by_date(db_session, "2026-09-19")
    day20 = await list_report_records_by_date(db_session, "2026-09-20")
    assert [r.batch_number for r in day19] == ["B-LATE"]
    assert [r.batch_number for r in day20] == ["B-EARLY"]
