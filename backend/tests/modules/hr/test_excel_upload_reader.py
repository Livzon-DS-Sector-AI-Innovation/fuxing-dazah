"""Excel 导入读取入口 —— .xlsx 读取与旧格式拒绝。

入平台数据统一用新格式：上传入口只放行 .xlsx（SOP 目录另放行 .docx），
旧版 .xls / .doc 在扩展名校验就被拒（400 + 另存提示），读不了的
（加密/损坏/伪扩展名）由 xlsx_utils.read_first_sheet_rows 抛中文 ValueError
转 400，不再出现 500。
"""

from datetime import date, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.xlsx_utils import read_first_sheet_rows
from tests.modules.hr.conftest import _rand

# ═══════════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════════


def _xlsx_bytes(rows: list[list[Any]]) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


_TABLE: list[list[Any]] = [
    ["年度", "部门", "月份", "课时", "培训内容及使用教材", "确认日期"],
    [2026, "一车间", "3月", 8, "GMP基础培训", date(2026, 3, 15)],
    [None] * 6,  # 空行必须被当成空行
    [2026, "厂级", "4月", 4.5, "安全培训", None],
]


# ═══════════════════════════════════════════════════════════════
# read_first_sheet_rows
# ═══════════════════════════════════════════════════════════════


def test_reader_reads_xlsx_rows():
    """行值口径：整数不带小数 / 日期 datetime / 空行 None 元组。"""
    rows = read_first_sheet_rows(_xlsx_bytes(_TABLE))
    assert rows[1] == (2026, "一车间", "3月", 8, "GMP基础培训", datetime(2026, 3, 15))
    assert rows[2] == (None,) * 6
    assert rows[3][3] == 4.5


@pytest.mark.parametrize(
    "content",
    [
        b"\xd0\xcf\x11\xe0" + bytes(600),  # OLE 容器（旧 .xls 的格式，入口虽拦、兜底也要 400 可读）
        b"PK\x03\x04" + bytes(600),  # zip 容器但不是 xlsx（改了扩展名）
        "年度,部门\n2026,甲\n".encode(),  # CSV 改扩展名
    ],
    ids=["ole-not-xlsx", "zip-not-xlsx", "csv"],
)
def test_reader_unreadable_file_raises_value_error(content: bytes):
    """读不了的文件抛带中文提示的 ValueError（端点转 400），而不是 openpyxl 的原始异常（500）。"""
    with pytest.raises(ValueError, match="无法读取该文件"):
        read_first_sheet_rows(content)


def test_reader_empty_file_returns_no_rows():
    """空文件交由调用方按「文件为空」处理。"""
    assert read_first_sheet_rows(b"") == []


# ═══════════════════════════════════════════════════════════════
# 导入入口：.xlsx 正常导入
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_annual_plan_reads_xlsx(db_session: AsyncSession):
    """标题行 + 表头 + 数据的 .xlsx 能导入；空行不报错；日期格落库为日期。"""
    from app.modules.hr.models import AnnualTrainingPlan, AnnualTrainingPlanItem
    from app.modules.hr.service import EmployeeService

    dept_a, dept_b = _rand("计划甲"), _rand("计划乙")
    table = [list(row) for row in _TABLE]
    table[1][1], table[3][1] = dept_a, dept_b
    result = await EmployeeService(db_session).upload_annual_plan(_xlsx_bytes([["2026 年培训计划"]] + table))

    assert (result["created"], result["errors"]) == (2, [])
    plan = (await db_session.execute(
        select(AnnualTrainingPlan).where(AnnualTrainingPlan.department == dept_a)
    )).scalar_one()
    item = (await db_session.execute(
        select(AnnualTrainingPlanItem).where(AnnualTrainingPlanItem.plan_id == plan.id)
    )).scalar_one()
    assert (plan.year, item.month, item.duration_hours, item.confirm_date) == (
        2026, "3月", 8.0, date(2026, 3, 15),
    )


@pytest.mark.asyncio
async def test_upload_annual_plan_unreadable_file_raises_value_error(db_session: AsyncSession):
    from app.modules.hr.service import EmployeeService

    with pytest.raises(ValueError, match="无法读取该文件"):
        await EmployeeService(db_session).upload_annual_plan(b"\xd0\xcf\x11\xe0" + bytes(600))


# ═══════════════════════════════════════════════════════════════
# HTTP 层：旧格式 400 + 明确提示另存；读不了的文件 400 而非 500
# ═══════════════════════════════════════════════════════════════

_UPLOAD_URL = "/api/v1/hr/annual-training-plans/upload"
_XLS_MEDIA_TYPE = "application/vnd.ms-excel"


@pytest.mark.asyncio
async def test_api_upload_annual_plan_rejects_legacy_xls(client: AsyncClient):
    """入平台数据统一 .xlsx：.xls 在扩展名校验被拒，提示另存。"""
    resp = await client.post(
        _UPLOAD_URL, files={"file": ("计划.xls", b"OLE", _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "另存为 .xlsx" in resp.json()["message"]


@pytest.mark.asyncio
async def test_api_upload_annual_plan_unreadable_file_returns_400(client: AsyncClient):
    """读不了的文件是 400 + 中文提示，而不是 500「服务内部错误」。"""
    resp = await client.post(
        _UPLOAD_URL,
        files={"file": ("计划.xlsx", b"\xd0\xcf\x11\xe0" + bytes(600), _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "无法读取该文件" in resp.json()["message"]


_TRAINERS_URL = "/api/v1/hr/trainers/upload"


@pytest.mark.asyncio
async def test_api_upload_trainers_rejects_legacy_xls(client: AsyncClient):
    resp = await client.post(
        _TRAINERS_URL, files={"file": ("内训师.xls", b"OLE", _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "另存为 .xlsx" in resp.json()["message"]


_DEPT_PERSONNEL_URL = "/api/v1/hr/dept-training-personnel/upload"


@pytest.mark.asyncio
async def test_api_upload_dept_training_personnel_rejects_legacy_xls(client: AsyncClient):
    resp = await client.post(
        _DEPT_PERSONNEL_URL, files={"file": ("人员表.xls", b"OLE", _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "另存为 .xlsx" in resp.json()["message"]


@pytest.mark.asyncio
async def test_api_upload_dept_training_personnel_unreadable_file_returns_400(client: AsyncClient):
    resp = await client.post(
        _DEPT_PERSONNEL_URL,
        files={"file": ("人员表.xlsx", b"\xd0\xcf\x11\xe0" + bytes(600), _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "无法读取该文件" in resp.json()["message"]
