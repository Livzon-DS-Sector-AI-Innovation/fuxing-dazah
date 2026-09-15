"""汇总统计口径测试 + 权限门禁 401 冒烟（回滚式 db_session / client）。"""

import uuid

from app.modules.quality.repository import (
    create_test_results,
    create_test_task,
    get_summary_by_product,
)


def _rand_batch() -> str:
    return f"HAS{uuid.uuid4().hex[:6].upper()}"


async def _make_task(db, product: str, batch: str, status: str, filled: bool):
    task = await create_test_task(
        db,
        product_name=product,
        batch_number=batch,
        production_date="2026-09-01",
        expiry_date="2028-08-31",
        specification=None,
        form_id=None,
        standard_document_id=None,
    )
    task.status = status
    await db.flush()
    rows = await create_test_results(db, task.id, [{
        "item_name": "水分", "sop_no": "SOP.03.1111", "standard_text": "≤3.0%",
        "operator": "≤", "limit_max": 3.0, "judge_mode": "auto", "source": "manual",
    }])
    if filled:
        for r in rows:
            r.is_pass = True
            r.result_value = 1.0
        await db.flush()
    return task


async def test_summary_counts_completed_and_in_progress(db_session):
    product = f"汇总测试{uuid.uuid4().hex[:4]}"
    await _make_task(db_session, product, _rand_batch(), "completed", filled=True)
    await _make_task(db_session, product, _rand_batch(), "pending_review", filled=False)
    await _make_task(db_session, product, _rand_batch(), "in_progress", filled=False)

    s = await get_summary_by_product(db_session, product_name=product)
    assert s["total"] == 1
    assert s["pass_count"] == 1
    assert s["fail_count"] == 0
    assert s["in_progress"] == 2
    assert s["pass_rate"] == 100.0
    assert len(s["products"]) == 1
    assert s["products"][0]["in_progress"] == 2


async def test_task_create_requires_auth(client):
    res = await client.post("/api/v1/quality/tasks", json={
        "product_name": "X", "batch_number": "Y",
    })
    assert res.status_code == 401


async def test_unqualified_handle_requires_auth(client):
    res = await client.put(
        "/api/v1/quality/unqualified-events/00000000-0000-0000-0000-000000000000/handle?handled=true"
    )
    assert res.status_code == 401
