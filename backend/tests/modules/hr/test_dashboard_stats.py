"""人事仪表盘统计（GET /dashboard/stats）：KPI 口径 + 数据范围过滤。

部门名用随机后缀隔离共享库数据；受限范围断言用精确值，
不限权范围只断言结构（共享库已有数据无法穷举）。
"""

from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import Employee
from tests.modules.hr.conftest import _rand


def _mk_employee(
    *, department: str, education: str | None = "本科", status: str = "在职",
    hire_date: date | None = None, departure_date: date | None = None,
    is_deleted: bool = False, birth_year: int | None = None,
    status_category: str | None = None,
) -> Employee:
    return Employee(
        employee_number=_rand("DASH"),
        name="仪表盘员工",
        department=department,
        position="操作工",
        hire_date=hire_date or date(2020, 1, 1),
        education=education,
        status=status,
        departure_date=departure_date,
        is_deleted=is_deleted,
        birth_year=birth_year,
        status_category=status_category,
    )


def _scoped_override(test_user, departments: frozenset[str]):
    async def _scoped() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department=next(iter(departments)) if departments else None,
            employee_number=test_user.employee_no,
            scoped_departments=departments,
        )
    return _scoped


async def test_kpi_counts_within_scoped_department(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """受限部门范围内：在职/本月入职/本月离职口径互不串数。"""
    dept = _rand("看板部")
    today = date.today()
    db_session.add_all([
        # 3 年前入职 · 在职 · 本科
        _mk_employee(department=dept, education="本科", hire_date=date(today.year - 3, 3, 1)),
        # 本月入职 · 在职 · 硕士
        _mk_employee(department=dept, education="硕士", hire_date=today),
        # 去年入职 · 本月离职
        _mk_employee(
            department=dept, status="离职",
            hire_date=date(today.year - 1, 6, 1), departure_date=today,
        ),
        # 软删员工不计入任何统计
        _mk_employee(department=dept, is_deleted=True, hire_date=today),
    ])
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped_override(test_user, frozenset({dept}))
    try:
        res = await client.get("/api/v1/hr/dashboard/stats")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        summary = data["summary"]

        assert summary["total_employees"] == 2
        assert summary["new_hires_this_month"] == 1
        assert summary["departures_this_month"] == 1
        # 今日入职/离职（软删员工不计入）
        assert summary["today_hires"] == 1
        assert summary["today_departures"] == 1
        # 本月净增 = 入 - 离
        assert summary["net_growth_this_month"] == 0

        edu = {d["name"]: d["value"] for d in data["education_distribution"]}
        assert edu == {"本科": 1, "硕士": 1}
        # 离职/软删员工不进部门在职分布
        dept_dist = {d["name"]: d["value"] for d in data["department_distribution"]}
        assert dept_dist == {dept: 2}
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_unclassified_employee_counts_by_actual_department(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """「未分类」员工按实际部门归属授权范围（与 apply_list_scope 语义一致）。"""
    dept = _rand("归属部")
    db_session.add(_mk_employee(department="未分类"))
    emp = _mk_employee(department="未分类")
    emp.actual_department = dept
    db_session.add(emp)
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped_override(test_user, frozenset({dept}))
    try:
        res = await client.get("/api/v1/hr/dashboard/stats")
        assert res.status_code == 200, res.text
        assert res.json()["data"]["summary"]["total_employees"] == 1
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_self_only_scope_filters_by_own_number(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """self_only 只统计本人工号对应的员工。"""
    dept = _rand("本人部")
    mine = _mk_employee(department=dept)
    db_session.add_all([mine, _mk_employee(department=dept)])
    await db_session.flush()

    async def _self_only() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope="self_only",
            department=dept,
            employee_number=mine.employee_number,
        )

    app.dependency_overrides[get_hr_scope] = _self_only
    try:
        res = await client.get("/api/v1/hr/dashboard/stats")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["summary"]["total_employees"] == 1
        assert data["department_distribution"] == [{"name": dept, "value": 1}]
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_department_scope_without_departments_fails_closed(
    client: AsyncClient, test_user,
):
    """部门范围但授权部门为空 → fail-closed 403，而不是放开成全公司数据。"""
    app.dependency_overrides[get_hr_scope] = _scoped_override(test_user, frozenset())
    try:
        res = await client.get("/api/v1/hr/dashboard/stats")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_response_shape_unrestricted(client: AsyncClient):
    """不限权范围：完整结构（summary + 分布组）+ 离职对比逐月 12 条 + 年龄 4 段。"""
    res = await client.get("/api/v1/hr/dashboard/stats")
    assert res.status_code == 200, res.text
    data = res.json()["data"]

    for key in (
        "summary", "education_distribution", "department_distribution",
        "monthly_hires_by_dept", "monthly_hires", "monthly_departures",
        "monthly_departure_comparison", "departures_by_dept",
        "monthly_hires_by_category", "monthly_departures_by_category",
        "hires_by_dept_year",
        "distributions", "position_departure_top", "contract_expiry",
    ):
        assert key in data, f"缺少字段 {key}"

    for key in ("total_employees", "new_hires_this_month", "departures_this_month",
                "today_hires", "today_departures", "net_growth_this_month", "avg_tenure"):
        assert key in data["summary"], f"summary 缺少字段 {key}"

    for key in ("gender", "age", "tenure", "departure_reason", "retention"):
        assert key in data["distributions"], f"distributions 缺少字段 {key}"

    comparison = data["monthly_departure_comparison"]
    assert len(comparison) == 12
    assert {m["month"] for m in comparison} == {f"{m:02d}月" for m in range(1, 13)}
    for m in comparison:
        assert isinstance(m["last_year"], int)
        assert isinstance(m["current_year"], int)

    # 年龄分布固定 4 段（与看板设计稿对齐）
    assert [d["name"] for d in data["distributions"]["age"]] == [
        "18-25岁", "26-35岁", "36-45岁", "46岁以上",
    ]

    # 按员工性质分组的月度统计：条目含 month/category/value
    for key in ("monthly_hires_by_category", "monthly_departures_by_category"):
        for item in data[key]:
            assert set(item.keys()) >= {"month", "category", "value"}, f"{key} 条目字段不完整: {item}"

    # 年度入职各部门总量：条目含 name/value
    for item in data["hires_by_dept_year"]:
        assert set(item.keys()) >= {"name", "value"}, f"hires_by_dept_year 条目字段不完整: {item}"


async def test_monthly_by_category_grouping(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """按员工性质分组的月度入职/离职：同月不同性质分组计数，空性质归「未填写」。"""
    dept = _rand("性质分组部")
    today = date.today()
    db_session.add_all([
        # 本月入职 · 实习生 / 转正员工
        _mk_employee(department=dept, status_category="实习生", hire_date=today),
        _mk_employee(department=dept, status_category="转正员工", hire_date=today),
        # 本月入职 · 性质为空 → 「未填写」
        _mk_employee(department=dept, status_category=None, hire_date=today),
        # 本月离职 · 试用期
        _mk_employee(
            department=dept, status="离职", status_category="试用期",
            hire_date=date(today.year - 1, 1, 1), departure_date=today,
        ),
    ])
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped_override(test_user, frozenset({dept}))
    try:
        res = await client.get("/api/v1/hr/dashboard/stats")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        month_key = today.strftime("%Y-%m")

        hires = {(i["month"], i["category"]): i["value"] for i in data["monthly_hires_by_category"]}
        assert hires.get((month_key, "实习生")) == 1
        assert hires.get((month_key, "转正员工")) == 1
        assert hires.get((month_key, "未填写")) == 1

        departures = {(i["month"], i["category"]): i["value"] for i in data["monthly_departures_by_category"]}
        assert departures.get((month_key, "试用期")) == 1

        # 年度入职各部门总量：只统计本年度 hire_date，3 名今日入职计入、去年入职的离职员工不计
        by_dept = {i["name"]: i["value"] for i in data["hires_by_dept_year"]}
        assert by_dept.get(dept) == 3
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)
