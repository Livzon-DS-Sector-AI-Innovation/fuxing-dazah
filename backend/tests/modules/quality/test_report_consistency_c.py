"""报告单确定性机审 C 类检查测试：图谱计算链路复算（C1）+ 峰面积一致性（C2）。

场景：B-1 预填链路（calc_form 留痕 inputs+peaks）→ 检验员提交后人工改动 → 审核机审应报出。
"""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.api._reports import report_consistency_endpoint
from tests.modules.quality.test_task_flow import _make_doc, _rand_batch


def _calc_cfg() -> dict:
    """归一化法最小可用配置：主成分 90% / 杂质A 5% / 总杂质 5%（面积 1000/900/50）。"""
    return {
        "mode": "normalization",
        "rrf": 1.0,
        "samples": 1,
        "main_item": {"std_name": "万古霉素B", "label": "万古霉素B"},
        "impurities": [{"key": "imp_a", "std_name": "杂质A", "label": "杂质A"}],
        "total_std_name": "总杂质",
    }


_INPUTS = {"total_peak_1": 1000.0, "main_peak_1": 900.0, "imp_a_1": 50.0}


@pytest.mark.asyncio
async def test_consistency_c2_total_peak_is_synthetic_no_false_alarm(
    db_session: AsyncSession,
) -> None:
    """total_peak 是映射引擎求和的合成值：峰表找不到不报（真实样本验收踩过：24 峰求和必不在峰表）。"""
    from app.modules.quality.repository import (
        create_report_record,
    )
    from app.modules.quality.service import test_task_service

    task, table_no = await _prepare_task_with_calc(db_session)
    # total=1250（900+50+300 求和，峰表无此值）；main/impurity 为单峰直取
    await test_task_service.submit_calc_form(
        db_session, task, table_no, "2026-09-05", [],
        inputs={"total_peak_1": 1250.0, "main_peak_1": 900.0, "imp_a_1": 50.0},
        peaks=[{"name": "总峰", "area": 900.0}, {"name": "主峰", "area": 50.0},
               {"name": "杂质A", "area": 300.0}],
    )
    report = await create_report_record(
        db_session, template_path="t.docx", product_name=task.product_name,
        batch_number=task.batch_number, test_task_id=task.id,
        file_path="/tmp/x.docx", file_size=10, serial_no=f"26{uuid.uuid4().hex[:6]}",
    )
    d = await _consistency(db_session, report.id)
    # total_peak_1=1250 不在峰表（900/50/300）但不报；无任何面积被改 → C2 全绿
    assert d["peak_area_mismatches"] == []


async def _prepare_task_with_calc(db: AsyncSession) -> tuple:
    from app.modules.quality.repository import (
        create_lc_template_config,
        create_test_results,
        create_test_task,
    )

    doc = await _make_doc(db, "HAF")
    task = await create_test_task(db,
        product_name=doc.product_name, batch_number=_rand_batch("HAF"),
        production_date="2026-09-01", expiry_date="2029-08-31",
        specification=None, form_id=None, standard_document_id=doc.id)
    task.status = "in_progress"
    await db.flush()
    await create_test_results(db, task.id, [
        {"item_name": "万古霉素B", "sop_no": "SOP.03.7777", "standard_text": "≥80%",
         "operator": "≥", "limit_min": 80.0, "judge_mode": "auto", "source": "manual"},
        {"item_name": "杂质A", "sop_no": "SOP.03.7778", "standard_text": "≤10%",
         "operator": "≤", "limit_max": 10.0, "judge_mode": "auto", "source": "manual"},
        {"item_name": "总杂质", "sop_no": "SOP.03.7779", "standard_text": "≤10%",
         "operator": "≤", "limit_max": 10.0, "judge_mode": "auto", "source": "manual"},
    ])
    table_no = f"EX-C1-{uuid.uuid4().hex[:4].upper()}-001"
    await create_lc_template_config(db, table_no, doc.product_name, None, None,
        {"calc": _calc_cfg(), "merge": [], "blocks": [], "batch_label": "批号"})
    return task, table_no


async def _consistency(db: AsyncSession, report_id) -> dict:
    resp = await report_consistency_endpoint(report_id, db, None)
    return json.loads(resp.body)["data"]


@pytest.mark.asyncio
async def test_consistency_c1_recalc_mismatch(db_session: AsyncSession) -> None:
    from app.modules.quality.repository import (
        create_report_record,
        list_test_results,
    )
    from app.modules.quality.service import test_task_service

    task, table_no = await _prepare_task_with_calc(db_session)
    filled, _unmatched = await test_task_service.submit_calc_form(
        db_session, task, table_no, "2026-09-05", [],
        inputs=dict(_INPUTS), section=0,
        peaks=[{"name": "总峰", "area": 1000.0}, {"name": "主峰", "area": 900.0},
               {"name": "杂质A", "area": 55.0}],  # 面积 55，检验员改成 50 提交（C2 应报）
    )
    assert set(filled) == {"万古霉素B", "杂质A", "总杂质"}

    # 检验员在提交后人工修改主成分结果（C1 复算应报 91 ≠ 90）
    rows = await list_test_results(db_session, task.id)
    for r in rows:
        if r.item_name == "万古霉素B":
            r.result_value = 91.0
    await db_session.flush()

    report = await create_report_record(
        db_session, template_path="t.docx", product_name=task.product_name,
        batch_number=task.batch_number, test_task_id=task.id,
        file_path="/tmp/x.docx", file_size=10, serial_no=f"26{uuid.uuid4().hex[:6]}",
    )
    d = await _consistency(db_session, report.id)
    by_name = {m["item_name"]: m for m in d["calc_mismatches"]}
    assert "万古霉素B" in by_name
    assert by_name["万古霉素B"]["report_value"] == 91.0
    assert abs(by_name["万古霉素B"]["recomputed_value"] - 90.0) < 1e-9
    # 其余两项未被改动：不报
    assert "杂质A" not in by_name and "总杂质" not in by_name
    # C2：计算表输入 imp_a_1=50 与峰表面积（1000/900/55）对不上
    assert {"input_key": "imp_a_1", "input_value": 50.0} in d["peak_area_mismatches"]


@pytest.mark.asyncio
async def test_consistency_c1_skip_when_config_gone(db_session: AsyncSession) -> None:
    """表号配置被删除后复算跳过（不报错、不误报），峰面积比对仍可用。"""
    from app.modules.quality.repository import (
        create_report_record,
        delete_lc_template_config,
        get_lc_template_by_table_no,
    )
    from app.modules.quality.service import test_task_service

    task, table_no = await _prepare_task_with_calc(db_session)
    await test_task_service.submit_calc_form(
        db_session, task, table_no, "2026-09-05", [],
        inputs=dict(_INPUTS),
        peaks=[{"name": "总峰", "area": 1000.0}, {"name": "主峰", "area": 900.0},
               {"name": "杂质A", "area": 50.0}],
    )
    cfg = await get_lc_template_by_table_no(db_session, table_no)
    await delete_lc_template_config(db_session, cfg.id)

    report = await create_report_record(
        db_session, template_path="t.docx", product_name=task.product_name,
        batch_number=task.batch_number, test_task_id=task.id,
        file_path="/tmp/x.docx", file_size=10, serial_no=f"26{uuid.uuid4().hex[:6]}",
    )
    d = await _consistency(db_session, report.id)
    assert d["calc_mismatches"] == []  # 配置已删：复算跳过，不误报
    assert d["peak_area_mismatches"] == []  # 峰面积全部吻合
