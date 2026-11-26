"""Excel 导入读取入口 —— 旧版 .xls 与读不了的文件。

年度培训计划 / 内训师 / SOP 目录三个导入入口前端都放行 .xls，此前直接交给 openpyxl
（只认 zip 容器），旧版 .xls 一传就是 500；现统一走 xlsx_utils.read_first_sheet_rows。
仓库没有 .xls 写入库（xlwt 非依赖），夹具由 _xls_bytes 手工构造。
"""

import struct
from datetime import date, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.xlsx_utils import read_first_sheet_rows
from tests.modules.hr.conftest import _rand

# CFB（OLE 容器）里的特殊扇区号
_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_NOSTREAM = 0xFFFFFFFF


# ═══════════════════════════════════════════════════════════════
# 夹具：手工构造 .xlsx / .xls
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


def _xls_bytes(rows: list[list[Any]]) -> bytes:
    """手工构造最小可用的旧版 .xls：OLE 容器里放一个 BIFF8「Workbook」流，首个工作表写入 rows。

    文本用 LABEL、数字用 NUMBER 记录，None 留空；date/datetime 转成 Excel 序列号并挂上
    内置日期格式（ifmt=14）的 XF，xlrd 才会把它读成日期格而不是普通数字。
    """
    def rec(code: int, payload: bytes) -> bytes:
        return struct.pack("<HH", code, len(payload)) + payload

    def bof(kind: int) -> bytes:
        return rec(0x0809, struct.pack("<HHHHIHH", 0x0600, kind, 0x0DBB, 0x07CC, 0, 0x0006, 0))

    cells = b""
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if isinstance(value, (date, datetime)):
                serial = (value - date(1899, 12, 30)).days
                cells += rec(0x0203, struct.pack("<HHHd", r, c, 1, float(serial)))
            elif isinstance(value, (int, float)):
                cells += rec(0x0203, struct.pack("<HHHd", r, c, 0, float(value)))
            elif value is not None:
                text = str(value).encode("utf-16-le")
                cells += rec(0x0204, struct.pack("<HHHHB", r, c, 0, len(text) // 2, 1) + text)

    nrows, ncols = len(rows), max(map(len, rows))
    sheet = (
        bof(0x0010)
        + rec(0x0200, struct.pack("<HHHHHH", 0, nrows, 0, 0, ncols, 0))  # DIMENSIONS
        + cells
        + rec(0x000A, b"")
    )

    # 全局子流：BOF + 两个 XF（0=常规，1=日期格式）+ BOUNDSHEET（指向工作表 BOF 的流内偏移）+ EOF
    def boundsheet(sheet_pos: int) -> bytes:
        return rec(0x0085, struct.pack("<IBBBB", sheet_pos, 0, 0, 1, 0) + b"S")

    globals_ = bof(0x0005) + rec(0x00E0, bytes(20)) + rec(0x00E0, bytes(2) + bytes([14]) + bytes(17))
    sheet_pos = len(globals_) + len(boundsheet(0)) + 4  # 末尾还有 EOF 记录
    stream = globals_ + boundsheet(sheet_pos) + rec(0x000A, b"") + sheet
    return _ole_container(stream)


def _ole_container(stream: bytes) -> bytes:
    """最小 CFB（512 字节扇区）：数据扇区 → 1 个 FAT 扇区 → 1 个目录扇区，不含 mini 流。

    流不足 4096 字节会被要求放进 mini 流，所以补零到 4096（EOF 记录之后的填充读不到）。
    """
    total = max(4096, -(-len(stream) // 512) * 512)
    stream = stream.ljust(total, b"\0")
    n = total // 512
    fat = [_FREESECT] * 128
    fat[:n - 1] = range(1, n)  # 数据扇区串成链
    fat[n - 1] = _ENDOFCHAIN
    fat[n] = _FATSECT
    fat[n + 1] = _ENDOFCHAIN
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII",
        bytes.fromhex("D0CF11E0A1B11AE1"), bytes(16), 0x003E, 3, 0xFFFE, 9, 6, bytes(6),
        0, 1, n + 1, 0, 4096, _ENDOFCHAIN, 0, _ENDOFCHAIN, 0,
    ) + struct.pack("<109I", n, *([_FREESECT] * 108))

    def entry(label: bytes, kind: int, child: int, start: int, size: int) -> bytes:
        label += b"\0\0"
        return struct.pack(
            "<64sHBBIII16sIQQIQ", label, len(label), kind, 1, _NOSTREAM, _NOSTREAM, child,
            bytes(16), 0, 0, 0, start, size,
        )

    directory = (
        entry("Root Entry".encode("utf-16-le"), 5, 1, _ENDOFCHAIN, 0)
        + entry("Workbook".encode("utf-16-le"), 2, _NOSTREAM, 0, total)
        + bytes(256)  # 目录扇区固定 4 个条目，后两个留空
    )
    return header + stream + struct.pack("<128I", *fat) + directory


_HEADERS = ["年度", "部门", "月份", "课时", "培训内容及使用教材", "确认日期"]
_TABLE: list[list[Any]] = [
    _HEADERS,
    [2026, "一车间", "3月", 8, "GMP基础培训", date(2026, 3, 15)],
    [None] * 6,  # 空行：xlrd 读出来是一行 ''，必须照样被当成空行
    [2026, "厂级", "4月", 4.5, "安全培训", None],
]


# ═══════════════════════════════════════════════════════════════
# read_first_sheet_rows
# ═══════════════════════════════════════════════════════════════


def test_reader_reads_legacy_xls_like_xlsx():
    """同一张表存成 .xls 与 .xlsx，读出的行值一致（空格 None / 整数不带小数 / 日期 datetime）。"""
    expected = read_first_sheet_rows(_xlsx_bytes(_TABLE))
    assert expected[1] == (2026, "一车间", "3月", 8, "GMP基础培训", datetime(2026, 3, 15))
    assert expected[2] == (None,) * 6
    assert read_first_sheet_rows(_xls_bytes(_TABLE)) == expected


@pytest.mark.parametrize(
    "content",
    [
        b"\xd0\xcf\x11\xe0" + bytes(600),  # 只剩 OLE 头的残缺 .xls
        b"PK\x03\x04" + bytes(600),  # zip 容器但不是 xlsx（改了扩展名）
        "年度,部门\n2026,甲\n".encode(),  # CSV 改扩展名
    ],
    ids=["truncated-ole", "zip-not-xlsx", "csv"],
)
def test_reader_unreadable_file_raises_value_error(content: bytes):
    """读不了的文件抛带中文提示的 ValueError（端点转 400），而不是 openpyxl/xlrd 的原始异常（500）。"""
    with pytest.raises(ValueError, match="无法读取该文件"):
        read_first_sheet_rows(content)


def test_reader_empty_file_returns_no_rows():
    """空文件交由调用方按「文件为空」处理。"""
    assert read_first_sheet_rows(b"") == []


# ═══════════════════════════════════════════════════════════════
# 三个导入入口：旧版 .xls
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_annual_plan_supports_legacy_xls(db_session: AsyncSession):
    """标题行 + 表头 + 数据的 .xls 能导入；空行不报错；日期格落库为日期。"""
    from app.modules.hr.models import AnnualTrainingPlan, AnnualTrainingPlanItem
    from app.modules.hr.service import EmployeeService

    dept_a, dept_b = _rand("计划甲"), _rand("计划乙")
    table = [list(row) for row in _TABLE]
    table[1][1], table[3][1] = dept_a, dept_b
    result = await EmployeeService(db_session).upload_annual_plan(_xls_bytes([["2026 年培训计划"]] + table))

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


@pytest.mark.asyncio
async def test_upload_trainers_supports_legacy_xls(db_session: AsyncSession):
    from app.modules.hr.models import HrTrainer
    from app.modules.hr.service import EmployeeService

    name, dept = _rand("内训师"), _rand("部门")
    result = await EmployeeService(db_session).upload_trainers(_xls_bytes([
        ["姓名", "部门", "认证日期"],
        [name, dept, date(2026, 1, 15)],
        [None] * 3,
    ]))

    assert (result["created"], result["errors"]) == (1, [])
    trainer = (await db_session.execute(
        select(HrTrainer).where(HrTrainer.name == name)
    )).scalar_one()
    assert (trainer.department, trainer.certification_date) == (dept, date(2026, 1, 15))


@pytest.mark.asyncio
async def test_upload_sop_catalog_supports_legacy_xls(db_session: AsyncSession):
    from app.modules.hr.models import SopCatalog
    from app.modules.hr.service import EmployeeService

    dept, sop = _rand("部门"), _rand("SOP")
    result = await EmployeeService(db_session).upload_sop_catalog(_xls_bytes([
        ["SOP编号", "文件名称", "部门", "岗位"],
        [sop, "文件A,文件B", dept, "操作工"],
        [None] * 4,
    ]))

    assert (result["created"], result["errors"]) == (2, [])
    names = (await db_session.execute(
        select(SopCatalog.file_name).where(SopCatalog.department == dept)
    )).scalars().all()
    assert sorted(names) == ["文件A", "文件B"]


# ═══════════════════════════════════════════════════════════════
# HTTP 层：前端只展示后端 message
# ═══════════════════════════════════════════════════════════════

_UPLOAD_URL = "/api/v1/hr/annual-training-plans/upload"
_XLS_MEDIA_TYPE = "application/vnd.ms-excel"


@pytest.mark.asyncio
async def test_api_upload_annual_plan_unreadable_file_returns_400(client: AsyncClient):
    """读不了的文件是 400 + 中文提示，而不是 500「服务内部错误」。"""
    resp = await client.post(
        _UPLOAD_URL,
        files={"file": ("计划.xls", b"\xd0\xcf\x11\xe0" + bytes(600), _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "无法读取该文件" in resp.json()["message"]


@pytest.mark.asyncio
async def test_api_upload_annual_plan_accepts_legacy_xls(client: AsyncClient):
    dept = _rand("计划")
    content = _xls_bytes([
        _HEADERS,
        [2026, dept, "3月", 8, "GMP基础培训", date(2026, 3, 15)],
    ])
    resp = await client.post(
        _UPLOAD_URL, files={"file": ("计划.xls", content, _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "新增 1 条，更新 0 条"


_DEPT_PERSONNEL_URL = "/api/v1/hr/dept-training-personnel/upload"


@pytest.mark.asyncio
async def test_api_upload_dept_training_personnel_accepts_legacy_xls(
    client: AsyncClient, db_session: AsyncSession
):
    """部门培训人员表在路由里按固定列位取值（跳过表头），.xls 同样可导入。"""
    from app.modules.hr.models import DeptTrainingPersonnel

    dept, variety = _rand("车间"), _rand("品种")
    content = _xls_bytes([
        ["序号", "体现部门", "品种", "部门", "培训管理员", "部门负责人", "一级培训师"],
        [1, dept, variety, dept, "张三", "李四", "王五"],
    ])
    resp = await client.post(
        _DEPT_PERSONNEL_URL, files={"file": ("人员表.xls", content, _XLS_MEDIA_TYPE)},
    )

    assert resp.status_code == 200
    assert resp.json()["message"] == "新增 1，更新 0"
    person = (await db_session.execute(
        select(DeptTrainingPersonnel).where(DeptTrainingPersonnel.display_department == dept)
    )).scalar_one()
    assert (person.variety, person.training_admin, person.department_head, person.level1_trainer) == (
        variety, "张三", "李四", "王五",
    )


@pytest.mark.asyncio
async def test_api_upload_dept_training_personnel_unreadable_file_returns_400(client: AsyncClient):
    resp = await client.post(
        _DEPT_PERSONNEL_URL,
        files={"file": ("人员表.xls", b"\xd0\xcf\x11\xe0" + bytes(600), _XLS_MEDIA_TYPE)},
    )
    assert resp.status_code == 400
    assert "无法读取该文件" in resp.json()["message"]
