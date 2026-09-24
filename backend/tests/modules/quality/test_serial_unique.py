"""流水号唯一索引与冲突检测回归测试。

背景：两人并发生成 COA 会撞流水号；唯一索引兜底 + is_serial_unique_violation
识别冲突让上层重算重试。本测试验证：重复流水号被数据库拒绝，且冲突可被识别。
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.quality.models import ReportRecord
from app.modules.quality.repository import (
    create_report_record,
    is_serial_unique_violation,
)

# 随机流水号，避免与开发库真实数据（按日期编号）撞唯一索引
_SERIAL = f"test-{uuid.uuid4().hex[:12]}"


def _insert_args(batch: str) -> dict:
    return {
        "template_path": "tpl.docx",
        "product_name": "测试产品",
        "batch_number": batch,
        "serial_no": _SERIAL,
    }


async def test_duplicate_serial_rejected_by_db(db_session):
    await create_report_record(db_session, **_insert_args("B-1"))
    with pytest.raises(IntegrityError) as exc_info:
        await create_report_record(db_session, **_insert_args("B-2"))
    assert is_serial_unique_violation(exc_info.value)
    # 恢复 session 可用状态，供后续用例/收尾正常执行
    await db_session.rollback()


async def test_other_integrity_error_not_misdetected(db_session):
    # 非流水号冲突（NOT NULL 违反）不应被识别为撞号
    rec = ReportRecord(
        template_path=None,  # 故意违反 NOT NULL
        product_name="测试产品",
        batch_number="B-3",
    )
    db_session.add(rec)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.flush()
    assert not is_serial_unique_violation(exc_info.value)
    await db_session.rollback()


def test_plain_exception_not_serial_violation():
    assert not is_serial_unique_violation(ValueError("uq_quality_report_record_serial"))
