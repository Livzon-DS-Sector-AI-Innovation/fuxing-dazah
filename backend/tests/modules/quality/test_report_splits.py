"""COA 逐份拆分测试：行归属标准文件 + 模板解析 + 流水号递增（回滚式 db_session）。

注意：本地开发库存在真实标准文档，file_no/批号必须用随机值避免唯一索引冲突。
"""

import uuid

from app.modules.quality.models import QualityStandardDocument
from app.modules.quality.repository import (
    create_standard_item,
    create_test_results,
    create_test_task,
)
from app.modules.quality.service import TestTaskService


def _rand_file_no() -> str:
    return f"SOP.02.{uuid.uuid4().hex[:4].upper()}.{uuid.uuid4().hex[:3].upper()}"


def _rand_batch() -> str:
    return f"HAF{uuid.uuid4().hex[:8].upper()}"


async def _make_doc(db, code: str, template: str) -> QualityStandardDocument:
    doc = QualityStandardDocument(
        file_no=_rand_file_no(),
        product_name=f"测试产品{uuid.uuid4().hex[:6]}",
        product_code=code,
        template_path=template,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _make_task(db, doc: QualityStandardDocument, batch: str | None = None) -> object:
    task = await create_test_task(
        db,
        product_name=doc.product_name,
        batch_number=batch or _rand_batch(),
        production_date="2026-09-01",
        expiry_date="2028-08-31",
        specification=None,
        form_id=None,
        standard_document_id=doc.id,
    )
    task.status = "completed"
    await db.flush()
    return task


async def test_splits_assign_rows_to_their_docs(db_session):
    doc_a = await _make_doc(db_session, "HAF", "tpl-a.docx")
    doc_b = await _make_doc(db_session, "HAF", "tpl-b.docx")
    item_a = await create_standard_item(db_session, doc_a.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    item_b = await create_standard_item(db_session, doc_b.id, {
        "seq": 1, "item_name": "酸度", "sop_no": "SOP.03.2222",
        "standard_text": "3.5~4.5", "operator": "范围", "limit_min": 3.5, "limit_max": 4.5,
    })
    batch = _rand_batch()
    task = await _make_task(db_session, doc_a, batch=batch)
    rows = await create_test_results(db_session, task.id, [
        {  # 归属 doc A
            "standard_item_id": item_a.id, "item_name": "水分", "sop_no": "SOP.03.1111",
            "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
            "judge_mode": "auto", "source": "manual",
        },
        {  # 归属 doc B
            "standard_item_id": item_b.id, "item_name": "酸度", "sop_no": "SOP.03.2222",
            "standard_text": "3.5~4.5", "operator": "范围", "limit_min": 3.5, "limit_max": 4.5,
            "judge_mode": "auto", "source": "manual",
        },
        {  # 无归属（液相解析追加行）→ 归主文档 A
            "standard_item_id": None, "item_name": "RS1", "sop_no": "",
            "standard_text": "≤0.5%", "operator": "≤", "limit_max": 0.5,
            "judge_mode": "auto", "source": "parse",
        },
    ])
    for r in rows:
        r.is_pass = True
        r.result_value = 1.0
    await db_session.flush()

    splits = await TestTaskService.build_task_report_splits(db_session, task.id)
    assert len(splits) == 2
    by_file_no = {s["doc"].file_no: s for s in splits}
    split_a = by_file_no[doc_a.file_no]
    split_b = by_file_no[doc_b.file_no]
    # 行序按 seq/created_at 排序，归属断言用集合
    assert {r.item_name for r in split_a["rows"]} == {"水分", "RS1"}
    assert {r.item_name for r in split_b["rows"]} == {"酸度"}
    assert split_a["template"] == "tpl-a.docx"
    assert split_b["template"] == "tpl-b.docx"
    assert split_a["fill_data"]["批号"] == batch
    # 流水号逐份递增（file_no 随机，不假定文档顺序，只断言两号连续）
    serials = sorted(int(s["fill_data"]["流水号"][-2:]) for s in splits)
    assert serials == [serials[0], serials[0] + 1]


async def test_splits_reject_unfilled(db_session):
    import pytest

    from app.core.exceptions import AppException

    doc = await _make_doc(db_session, "HAF", "tpl-a.docx")
    task = await _make_task(db_session, doc)
    await create_test_results(db_session, task.id, [{
        "item_name": "水分", "sop_no": "SOP.03.1111", "standard_text": "≤3.0%",
        "operator": "≤", "limit_max": 3.0, "judge_mode": "auto", "source": "manual",
    }])
    with pytest.raises(AppException):
        await TestTaskService.build_task_report_splits(db_session, task.id)


async def test_splits_require_template(db_session):
    import pytest

    from app.core.exceptions import AppException

    doc = await _make_doc(db_session, "HAF", "")
    task = await _make_task(db_session, doc)
    rows = await create_test_results(db_session, task.id, [{
        "item_name": "水分", "sop_no": "SOP.03.1111", "standard_text": "≤3.0%",
        "operator": "≤", "limit_max": 3.0, "judge_mode": "auto", "source": "manual",
    }])
    for r in rows:
        r.is_pass = True
        r.result_value = 1.0
    await db_session.flush()

    with pytest.raises(AppException):
        await TestTaskService.build_task_report_splits(db_session, task.id)
