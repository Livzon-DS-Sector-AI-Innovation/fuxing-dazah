"""报表用职级公式 + 培训人员名单计算列 + 名单导出测试。

规则（2026-11 与培训管理确认，含 M 序列修正）：
参与分级 = 岗位类别「管理」（M 序列管理岗 M1-M8）或 S 序列 ≥ S13（含 S13）；
在此范围内按职务关键词分级（总监优先于经理）；其余 → 其他人员。
"""

from io import BytesIO

from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.employee_sync.report_level import compute_report_level
from app.modules.hr.models import TrainingRosterProfile
from tests.modules.hr.conftest import _rand

# ─── 公式（纯函数） ───


def test_general_manager():
    assert compute_report_level("S13", "总经理", "管理") == "总经理级及以上"
    assert compute_report_level("S15", "总经理", "管理") == "总经理级及以上"
    # M8 = 总经理（库内真实：M 序列最高层）
    assert compute_report_level("M8", "总经理", "管理") == "总经理级及以上"


def test_director_level_keywords_win_over_manager():
    """总监关键词优先：副总经理/总监/工程师 → 总监级（含总监兼经理的兼任职务）。"""
    assert compute_report_level("S13", "副总经理", "管理") == "总监级"
    assert compute_report_level("M7", "副总经理", "管理") == "总监级"
    assert compute_report_level("M6", "人力资源总监", "管理") == "总监级"  # 陈小娟
    assert compute_report_level("M6", "生产总监兼六部经理", "管理") == "总监级"
    assert compute_report_level("S13", "质量副总监", "管理") == "总监级"
    assert compute_report_level("S13", "工程师") == "总监级"
    assert compute_report_level("M4", "财务总监", "管理") == "总监级"


def test_manager_level():
    """含「经理」且不含「总经理」→ 经理级。"""
    assert compute_report_level("M3", "经理", "管理") == "经理级"
    assert compute_report_level("M1", "副经理", "管理") == "经理级"
    assert compute_report_level("M2", "菌种副经理", "管理") == "经理级"
    assert compute_report_level("S13", "高级经理", "管理") == "经理级"
    assert compute_report_level("S13", "六部经理", "管理") == "经理级"


def test_s13_threshold_inclusive():
    """S13 含在本数内；S12 及以下（非管理类别）即使职务匹配也是其他人员。"""
    assert compute_report_level("S13", "经理") == "经理级"
    assert compute_report_level("S12", "经理") == "其他人员"
    assert compute_report_level("S12", "总经理", "技术") == "其他人员"


def test_management_category_qualifies_regardless_of_level():
    """岗位类别=管理即参与分级（M 序列管理岗的主通道）。"""
    assert compute_report_level("M1", "副经理", "管理") == "经理级"
    assert compute_report_level(None, "经理", "管理") == "经理级"
    assert compute_report_level("M5", "常务副总经理", "管理") == "总监级"


def test_non_management_track_is_other():
    """非管理序列且职级不够：实习生/S12 以下/空值 → 其他人员。"""
    assert compute_report_level("实习转试用S7", "经理", "技术") == "其他人员"
    assert compute_report_level("S11", "主管", "操作") == "其他人员"
    assert compute_report_level(None, "经理") == "其他人员"
    assert compute_report_level("S13", None, "管理") == "其他人员"
    assert compute_report_level("S13", "", "管理") == "其他人员"
    assert compute_report_level("S13", "主管", "管理") == "其他人员"


def test_m_track_floors_at_manager_level():
    """M 序列保底经理级：职务未命中关键词（高级工程师/总经理助理/无职务）也至少经理级。"""
    # 库内真实案例：M1 设备高级工程师（岗位类别为技术支持组，仍按 M 序列判）
    assert compute_report_level("M1", "设备高级工程师", "技术支持组") == "经理级"
    # 「总经理助理」含「总经理」不落入经理级档、也不等于总经理 → M 序列保底
    assert compute_report_level("M5", "总经理助理", "管理") == "经理级"
    # M 序列无职务：保底经理级
    assert compute_report_level("M3", None, "管理") == "经理级"
    assert compute_report_level("M2", "") == "经理级"


def test_engineer_director_keyword_only_for_s13():
    """「工程师 → 总监级」仅适用 S13 及以上；M 序列普通工程师按序列保底经理级。

    「总工程师」是总监级头衔，任何序列都判总监级（库内真实：M6 总工程师）。
    """
    assert compute_report_level("S13", "工程师") == "总监级"
    assert compute_report_level("S14", "研发高级工程师", "技术") == "总监级"
    assert compute_report_level("M6", "总工程师", "管理") == "总监级"
    assert compute_report_level("M1", "设备高级工程师", "技术支持组") == "经理级"



def test_gm_assistant_not_gm_or_director_level():
    """「总经理助理」含「总经理」→ 不判总经理级/总监级；M 序列保底经理级。"""
    assert compute_report_level("M5", "总经理助理", "管理") == "经理级"
    assert compute_report_level("M5", "总经理助理", "管理") != "总经理级及以上"


# ─── 名单接口：计算列 ───


async def _add_roster(db_session: AsyncSession, **overrides) -> TrainingRosterProfile:
    defaults = dict(
        employee_number=_rand("RLV"), name="分级员工",
        department=_rand("分级部"), position="操作工",
    )
    defaults.update(overrides)
    profile = TrainingRosterProfile(**defaults)
    db_session.add(profile)
    await db_session.flush()
    return profile


async def test_roster_rows_include_report_level(db_session: AsyncSession, client: AsyncClient):
    """名单行带 report_level 计算列；原始「级别」仍不出现在白名单输出里。"""
    gm = await _add_roster(db_session, level="M8", duty="总经理", job_category="管理", name="总经理甲")
    director = await _add_roster(db_session, level="M6", duty="人力资源总监", job_category="管理", name="总监乙")
    mgr = await _add_roster(db_session, level="M3", duty="经理", job_category="管理", name="经理丙")
    staff = await _add_roster(db_session, level="S11", duty="主管", job_category="操作", name="主管丁")

    res = await client.get(
        "/api/v1/hr/employee-sync/training-roster",
        params={"page_size": 500, "keyword": ""},
    )
    assert res.status_code == 200, res.text
    rows = {r["employee_number"]: r for r in res.json()["data"]}
    assert rows[gm.employee_number]["report_level"] == "总经理级及以上"
    assert rows[director.employee_number]["report_level"] == "总监级"
    assert rows[mgr.employee_number]["report_level"] == "经理级"
    assert rows[staff.employee_number]["report_level"] == "其他人员"
    # 原始级别字段不外显（脱敏白名单）
    assert "level" not in rows[gm.employee_number]


# ─── 名单导出 ───


async def test_export_training_roster_xlsx(db_session: AsyncSession, client: AsyncClient):
    """导出 xlsx：含「报表用职级」列（紧跟「职务」），行数据与计算值正确。"""
    dept = _rand("导出部")
    a = await _add_roster(db_session, level="M6", duty="总监", job_category="管理", department=dept, name="总监导出")
    b = await _add_roster(db_session, level="S10", duty="班长", job_category="操作", department=dept, name="班长导出")

    res = await client.get(
        "/api/v1/hr/employee-sync/training-roster/export",
        params={"department": dept},
    )
    assert res.status_code == 200, res.text
    assert "spreadsheetml" in res.headers["content-type"]
    assert "attachment" in res.headers.get("content-disposition", "")

    wb = load_workbook(BytesIO(res.content))
    ws = wb.active
    header = [c.value for c in next(ws.iter_rows(max_row=1))]
    assert "报表用职级" in header
    assert header.index("报表用职级") == header.index("职务") + 1

    body = {r[0]: dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)}
    assert body[a.employee_number]["报表用职级"] == "总监级"
    assert body[b.employee_number]["报表用职级"] == "其他人员"


async def test_export_respects_keyword_filter(db_session: AsyncSession, client: AsyncClient):
    """导出沿用列表的筛选参数与数据范围。"""
    dept = _rand("筛选部")
    target = await _add_roster(db_session, level="S13", duty="经理", department=dept, name="唯一命中")
    await _add_roster(db_session, level="S13", duty="经理", department=dept, name="不该出现")

    res = await client.get(
        "/api/v1/hr/employee-sync/training-roster/export",
        params={"department": dept, "keyword": "唯一命中"},
    )
    assert res.status_code == 200, res.text
    wb = load_workbook(BytesIO(res.content))
    ws = wb.active
    numbers = [r[0] for r in ws.iter_rows(min_row=2, values_only=True)]
    assert numbers == [target.employee_number]
