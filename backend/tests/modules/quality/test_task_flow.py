"""建任务与填报保存流程测试（回滚式 db_session，随机 file_no/批号避免唯一索引冲突）。

此前 create_task/update_results 零覆盖——它们是网页与机器人两条填报链路的主干。
"""

import uuid

import pytest

from app.core.exceptions import AppException
from app.modules.quality.models import QualityStandardDocument
from app.modules.quality.repository import (
    create_standard_item,
    create_test_results,
    get_test_task,
    list_test_results,
)
from app.modules.quality.schemas import (
    TestResultFill,
    TestResultsUpdate,
    TestTaskCreate,
)
from app.modules.quality.service import TestTaskService


def _rand_file_no() -> str:
    return f"SOP.02.{uuid.uuid4().hex[:4].upper()}.{uuid.uuid4().hex[:3].upper()}"


def _rand_batch(code: str) -> str:
    return f"{code}{uuid.uuid4().hex[:8].upper()}"


async def _make_doc(db, code: str, valid_years: str = "3年") -> QualityStandardDocument:
    doc = QualityStandardDocument(
        file_no=_rand_file_no(),
        product_name=f"测试产品{uuid.uuid4().hex[:6]}",
        product_code=code,
        valid_years=valid_years,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _make_task_with_rows(db, doc: QualityStandardDocument) -> object:
    """直接建一个 in_progress 任务 + 一条 auto 行 + 一条 manual 行。"""
    from app.modules.quality.repository import create_test_task

    task = await create_test_task(
        db,
        product_name=doc.product_name,
        batch_number=_rand_batch(doc.product_code or "HAF"),
        production_date="2026-09-01",
        expiry_date="2028-08-31",
        specification=None,
        form_id=None,
        standard_document_id=doc.id,
    )
    task.status = "in_progress"
    await db.flush()
    rows = await create_test_results(db, task.id, [
        {"item_name": "水分", "sop_no": "SOP.03.1111", "standard_text": "≤3.0%",
         "operator": "≤", "limit_max": 3.0, "judge_mode": "auto", "source": "manual"},
        {"item_name": "外观", "sop_no": "SOP.03.2222", "standard_text": "应为白色粉末",
         "operator": None, "limit_max": None, "judge_mode": "manual", "source": "manual"},
    ])
    return task, rows


# ── create_task：批号收敛 + 快照 + 重复拦截 ──


async def test_create_task_snapshots_items_and_computes_expiry(db_session):
    doc = await _make_doc(db_session, "HAF", valid_years="3年")
    await create_standard_item(db_session, doc.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    payload = TestTaskCreate(
        product_name=doc.product_name,
        batch_number=_rand_batch("HAF"),
        production_date="2026.09.01",  # 日期分隔符归一化
        standard_document_id=doc.id,
    )
    detail = await TestTaskService.create_task(db_session, payload)
    assert detail.id is not None
    assert detail.status == "in_progress"
    assert len(detail.results) == 1
    assert detail.results[0].item_name == "水分"
    assert detail.results[0].judge_mode == "auto"
    # 效期 = 生产日期 + 3 年 - 1 天
    assert detail.expiry_date == "2029-08-31"


async def test_create_task_rejects_batch_without_known_code(db_session):
    doc = await _make_doc(db_session, "HAF")
    payload = TestTaskCreate(
        product_name=doc.product_name,
        batch_number="UNKNOWN123",  # 开头不含任何标准库代号
    )
    with pytest.raises(AppException) as exc_info:
        await TestTaskService.create_task(db_session, payload)
    assert exc_info.value.status_code == 400
    assert "产品代号" in exc_info.value.detail


async def test_create_task_duplicate_batch_409(db_session):
    doc = await _make_doc(db_session, "HAF")
    await create_standard_item(db_session, doc.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    batch = _rand_batch("HAF")
    payload = TestTaskCreate(product_name=doc.product_name, batch_number=batch,
                             standard_document_id=doc.id)
    await TestTaskService.create_task(db_session, payload)
    with pytest.raises(AppException) as exc_info:
        await TestTaskService.create_task(db_session, payload)
    assert exc_info.value.status_code == 409


async def test_create_task_selected_item_subset(db_session):
    doc = await _make_doc(db_session, "HAF")
    item_a = await create_standard_item(db_session, doc.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    await create_standard_item(db_session, doc.id, {
        "seq": 2, "item_name": "炽灼残渣", "sop_no": "SOP.03.3333",
        "standard_text": "≤0.1%", "operator": "≤", "limit_max": 0.1,
    })
    payload = TestTaskCreate(
        product_name=doc.product_name,
        batch_number=_rand_batch("HAF"),
        standard_document_id=doc.id,
        standard_item_ids=[item_a.id],
    )
    detail = await TestTaskService.create_task(db_session, payload)
    assert [r.item_name for r in detail.results] == ["水分"]


# ── update_results：auto/manual 分支 + 错误场景 + 自动流转 ──


async def test_update_auto_row_judges_and_records_filler(db_session):
    doc = await _make_doc(db_session, "HAF")
    task, rows = await _make_task_with_rows(db_session, doc)
    auto_row = next(r for r in rows if r.judge_mode == "auto")
    filler = uuid.uuid4()
    payload = TestResultsUpdate(results=[
        TestResultFill(result_id=auto_row.id, result_value=3.5)  # 超限 → 不合格
    ])
    detail = await TestTaskService.update_results(db_session, task.id, payload, filled_by=filler)
    saved = next(r for r in detail.results if r.id == auto_row.id)
    assert saved.is_pass is False
    # GMP 可追溯：填报人/时间落库（响应 schema 未暴露 filled_by，直接查模型）
    db_row = next(r for r in await list_test_results(db_session, task.id) if r.id == auto_row.id)
    assert db_row.filled_by == filler
    assert db_row.filled_at is not None


async def test_update_manual_row_requires_is_pass(db_session):
    doc = await _make_doc(db_session, "HAF")
    task, rows = await _make_task_with_rows(db_session, doc)
    manual_row = next(r for r in rows if r.judge_mode == "manual")
    payload = TestResultsUpdate(results=[
        TestResultFill(result_id=manual_row.id, result_text="白色粉末")  # 无 is_pass
    ])
    with pytest.raises(AppException) as exc_info:
        await TestTaskService.update_results(db_session, task.id, payload)
    assert exc_info.value.status_code == 400
    assert "人工判定" in exc_info.value.detail


async def test_update_unknown_result_id_400(db_session):
    doc = await _make_doc(db_session, "HAF")
    task, _rows = await _make_task_with_rows(db_session, doc)
    payload = TestResultsUpdate(results=[
        TestResultFill(result_id=uuid.uuid4(), result_value=1.0)
    ])
    with pytest.raises(AppException) as exc_info:
        await TestTaskService.update_results(db_session, task.id, payload)
    assert exc_info.value.status_code == 400


async def test_update_auto_row_missing_limit_requires_manual_verdict(db_session):
    doc = await _make_doc(db_session, "HAF")
    task, rows = await _make_task_with_rows(db_session, doc)
    auto_row = next(r for r in rows if r.judge_mode == "auto")
    auto_row.operator = None  # 限度结构破坏 → 无法自动判定
    await db_session.flush()
    payload = TestResultsUpdate(results=[
        TestResultFill(result_id=auto_row.id, result_value=1.0)  # 无 is_pass
    ])
    with pytest.raises(AppException) as exc_info:
        await TestTaskService.update_results(db_session, task.id, payload)
    assert "人工判定" in exc_info.value.detail


async def test_update_all_judged_auto_advances_to_review(db_session):
    doc = await _make_doc(db_session, "HAF")
    task, rows = await _make_task_with_rows(db_session, doc)
    payload = TestResultsUpdate(results=[
        TestResultFill(result_id=rows[0].id, result_value=1.5),  # 合格
        TestResultFill(result_id=rows[1].id, is_pass=True, result_text="白色粉末"),
    ])
    await TestTaskService.update_results(db_session, task.id, payload)
    refreshed = await get_test_task(db_session, task.id)
    assert refreshed.status == "pending_review"
    all_rows = await list_test_results(db_session, task.id)
    assert all(r.is_pass is not None for r in all_rows)


async def test_update_rejects_non_in_progress_task(db_session):
    doc = await _make_doc(db_session, "HAF")
    task, rows = await _make_task_with_rows(db_session, doc)
    task.status = "completed"
    await db_session.flush()
    payload = TestResultsUpdate(results=[
        TestResultFill(result_id=rows[0].id, result_value=1.5)
    ])
    with pytest.raises(AppException) as exc_info:
        await TestTaskService.update_results(db_session, task.id, payload)
    assert exc_info.value.status_code == 400


async def test_item_update_keeps_doc_mapping_for_history_tasks(db_session):
    """覆盖导入复用旧行 ID 的不变量：历史任务 standard_item_id → 文档映射不因更新行内容断裂。"""
    from app.modules.quality.repository import (
        get_standard_item_doc_map,
        update_standard_item,
    )

    doc = await _make_doc(db_session, "HAF")
    item = await create_standard_item(db_session, doc.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    task = await TestTaskService.create_task(db_session, TestTaskCreate(
        product_name=doc.product_name,
        batch_number=_rand_batch("HAF"),
        standard_document_id=doc.id,
    ))
    # 覆盖导入路径：同 (sop_no, item_name) 复用行 ID，仅更新内容
    await update_standard_item(db_session, item.id, limit_max=5.0, standard_text="≤5.0%")
    # 历史任务行的归属映射必须仍然有效
    task_rows = await list_test_results(db_session, task.id)
    item_ids = {r.standard_item_id for r in task_rows if r.standard_item_id}
    mapping = await get_standard_item_doc_map(db_session, item_ids)
    assert mapping == {item.id: doc.id}
