"""离职台账增强（筛选 / 导出 / 保存视图 / 导出留痕）— 业务规则测试。

覆盖需求「筛选与导出」：十类筛选条件可单独 / 任意组合使用、列表带出办理流程信息
（审批状态 / 证明开具签收 / 四部门清退结算）、导出字段可勾选且身份证脱敏、
导出行为留痕、常用条件保存为视图。真实 DB 回滚；飞书 / 邮件 / 对象存储打桩。
"""

import io
from datetime import date, timedelta
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

import tests.modules.hr.test_offboarding_case as case_tests
from app.core.exceptions import AppException, NotFoundException
from app.modules.hr.models import DepartureRecord
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import service
from app.modules.hr.offboarding.ledger import export as ledger_export
from app.modules.hr.offboarding.ledger import query as ledger_query
from app.modules.hr.offboarding.ledger import views as ledger_views
from app.modules.hr.schemas import EmployeeCreate
from app.modules.hr.service import EmployeeService
from tests.modules.hr.conftest import _rand
from tests.modules.hr.test_offboarding_case import (  # noqa: F401 — 夹具随导入在本模块生效
    _no_real_feishu_approval,
    _set_settings,
    no_mail,
    object_store,
)

TODAY = date.today()


# ── 测试数据 ──

async def _make_employee(db: AsyncSession, *, department: str):
    suffix = _rand()
    employee = await EmployeeService(db).create_employee(EmployeeCreate(
        employee_number=f"LG{suffix}", name=f"流程甲{suffix}", department=department,
        position="操作工", hire_date=date(2019, 6, 1),
    ))
    employee.gender, employee.education = "女", "本科"
    employee.id_card = "350102199001011234"
    await db.flush()
    return employee


async def _seed_ledger(db: AsyncSession) -> dict[str, str]:
    """三行互相可区分的台账数据，返回 {A/B/C: 姓名, dept: 部门}。

    A：平台走完流程的办结单（建单即落台账并带出档案信息；有清退明细、证明已开已签）；
    B / C：飞书同步来的线下台账行（没有办结单）。部门名随机，与共享库其它数据隔离。
    """
    dept = _rand("台账部")

    employee_a = await _make_employee(db, department=dept)
    case = await service.create_case(
        db, employee_id=employee_a.id, offboarding_date=TODAY + timedelta(days=20), reason="个人发展",
    )
    case = (await service.submit_approval(db, case))[0]
    case = await service.manual_stage_done(db, case, stage="approving")
    await service.replace_clearance_items(db, case, [
        {"category": "admin", "item_name": "宿舍钥匙", "status": "confirmed"},
        {"category": "admin", "item_name": "餐卡", "status": "deducted",
         "deduction_amount": "30", "supplement_amount": "5.5"},
        {"category": "admin", "item_name": "车辆通行证", "status": "pending"},
        {"category": "finance", "item_name": "电脑", "status": "confirmed"},
    ])
    case = await service.manual_stage_done(db, case, stage="clearing")
    case, _note = await service.issue_certificate(db, case, issued_by="HR乙")
    await service.register_signature(db, case, signature=case_tests.PNG_SIGNATURE)

    name_b, name_c = f"线下乙{_rand()}", f"线下丙{_rand()}"
    db.add_all([
        DepartureRecord(
            name=name_b, employee_number=f"LG{_rand()}", department=dept, position="操作工",
            offboarding_type="辞退", offboarding_reason=["部门劝退", "家庭原因"],
            employee_category="退休返聘", gender="男", education="大专",
            offboarding_date=TODAY - timedelta(days=10),
        ),
        DepartureRecord(
            name=name_c, employee_number=f"LG{_rand()}", department=dept, position="质检员",
            offboarding_type="辞职", gender="女", education="本科",
            offboarding_date=TODAY + timedelta(days=5), cert_sign_status="signed",
        ),
    ])
    await db.flush()
    return {"A": employee_a.name, "B": name_b, "C": name_c, "dept": dept}


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, str]:
    """台账测试数据（见 _seed_ledger）。

    造数据会开证：邮件 / 对象存储 / 飞书审批的打桩是从 test_offboarding_case 导入的
    autouse 夹具，对本文件自动生效，不需要（也不能）在这里用 usefixtures 标记。
    """
    return await _seed_ledger(db_session)


async def _names(db: AsyncSession, seeded: dict[str, str], **filters) -> set[str]:
    rows, _total = await ledger_query.query(
        db, {"department": seeded["dept"], **filters}, scoped=None, page_size=200,
    )
    return {row["name"] for row in rows}


def _pick(seeded: dict[str, str], keys: str) -> set[str]:
    return {seeded[key] for key in keys}


# ═══════════════════════════════════════════════════════════════
# 列表：办理流程信息装配
# ═══════════════════════════════════════════════════════════════

async def test_query_carries_process_info(db_session: AsyncSession, seeded: dict[str, str]):
    rows, total = await ledger_query.query(
        db_session, {"department": seeded["dept"]}, scoped=None, page_size=200,
    )
    assert total == 3
    by_name = {row["name"]: row for row in rows}

    row_a = by_name[seeded["A"]]
    assert "cert_sign_image" not in row_a and row_a["has_sign_image"] is True  # 签名图不进列表
    assert row_a["approval_status"] == "signed" and row_a["approval_status_label"] == "已签字确认"
    assert row_a["case_no"] and row_a["case_id"]
    assert row_a["cert_issued"] is True and row_a["cert_signed"] is True and row_a["cert_issued_at"]
    assert row_a["gender"] == "女" and row_a["education"] == "本科"  # 建单时从档案带出
    # 清退结算：行政后勤 3 项（2 项已确认，扣 30 补 5.5），财务 1 项已确认，其余部门无明细
    assert row_a["clearance"]["admin"] == {"total": 3, "done": 2, "deduction": 30.0, "supplement": 5.5}
    assert row_a["clearance"]["finance"] == {"total": 1, "done": 1, "deduction": 0.0, "supplement": 0.0}
    assert row_a["clearance"]["work"] == {"total": 0, "done": 0, "deduction": 0.0, "supplement": 0.0}

    row_b = by_name[seeded["B"]]
    assert row_b["approval_status"] is None and row_b["approval_status_label"] == "未发起"
    assert row_b["case_id"] is None and row_b["cert_issued"] is False and row_b["cert_signed"] is False
    assert row_b["offboarding_reason"] == ["部门劝退", "家庭原因"]

    row_c = by_name[seeded["C"]]
    assert row_c["cert_signed"] is True and row_c["cert_issued"] is False  # 存量：线下签收、平台未开证


# ═══════════════════════════════════════════════════════════════
# 十类筛选：可单独使用
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(("filters", "expected"), [
    ({"gender": "女"}, "AC"),
    ({"gender": "男"}, "B"),
    ({"education": "本科"}, "AC"),
    ({"education": "大专"}, "B"),
    ({"position": "质检员"}, "C"),
    ({"offboarding_type": "辞退"}, "B"),
    ({"offboarding_reason": "家庭原因"}, "B"),  # JSON 多选值包含
    ({"employee_category": "退休返聘"}, "B"),
    ({"approval_status": ledger_query.APPROVAL_NONE}, "BC"),  # 未发起办理
    ({"approval_status": "signed"}, "A"),
    ({"cert_issued": True}, "A"),
    ({"cert_issued": False}, "BC"),
    ({"cert_signed": True}, "AC"),
    ({"cert_signed": False}, "B"),
])
async def test_single_filters(db_session: AsyncSession, seeded: dict[str, str], filters: dict, expected: str):
    assert await _names(db_session, seeded, **filters) == _pick(seeded, expected)


async def test_date_range_keyword_and_combination(db_session: AsyncSession, seeded: dict[str, str]):
    assert await _names(db_session, seeded, offboarding_date_from=TODAY - timedelta(days=1)) == _pick(seeded, "AC")
    assert await _names(db_session, seeded, offboarding_date_to=TODAY) == _pick(seeded, "B")
    assert await _names(
        db_session, seeded,
        offboarding_date_from=TODAY - timedelta(days=15), offboarding_date_to=TODAY + timedelta(days=21),
    ) == _pick(seeded, "ABC")
    # 关键词：职位 / 部门
    assert await _names(db_session, seeded, keyword="质检") == _pick(seeded, "C")
    assert await _names(db_session, seeded, keyword=seeded["dept"][3:]) == _pick(seeded, "ABC")
    # 任意组合
    assert await _names(db_session, seeded, gender="女", education="本科") == _pick(seeded, "AC")
    assert await _names(db_session, seeded, gender="女", education="本科", cert_issued=True) == _pick(seeded, "A")
    assert await _names(db_session, seeded, approval_status="none", cert_signed=True) == _pick(seeded, "C")
    assert await _names(db_session, seeded, gender="女", offboarding_type="辞退") == set()
    # 「%」是普通字符，不能匹配整表
    assert await _names(db_session, seeded, keyword="%") == set()


async def test_query_rejects_inverted_date_range(db_session: AsyncSession):
    with pytest.raises(AppException, match="起始日期不能晚于截止日期"):
        await ledger_query.query(
            db_session,
            {"offboarding_date_from": TODAY, "offboarding_date_to": TODAY - timedelta(days=1)},
            scoped=None,
        )


async def test_scoped_departments_follow_hr_scope(db_session: AsyncSession, seeded: dict[str, str]):
    async def names_in(scoped: set[str] | None) -> set[str]:
        rows, _total = await ledger_query.query(
            db_session, {"position": "质检员"}, scoped=scoped, page_size=500,
        )
        return {row["name"] for row in rows}

    assert await names_in({seeded["dept"]}) == {seeded["C"]}
    assert await names_in(set()) == set()  # 无可见部门
    assert await names_in({_rand("别的部")}) == set()


# ═══════════════════════════════════════════════════════════════
# 筛选选项 / 导出字段
# ═══════════════════════════════════════════════════════════════

async def test_filter_options_aggregate_existing_values(db_session: AsyncSession, seeded: dict[str, str]):
    options = await ledger_query.filter_options(db_session, {seeded["dept"]})
    assert seeded["dept"] in options["departments"]
    assert {"质检员", "操作工"} <= set(options["positions"])
    assert {"辞职", "辞退"} <= set(options["offboarding_types"])
    assert {"家庭原因", "部门劝退"} <= set(options["offboarding_reasons"])
    assert "退休返聘" in options["employee_categories"]
    assert options["approval_statuses"][0] == {"value": "none", "label": "未发起"}
    assert {item["value"] for item in options["approval_statuses"]} >= {"draft", "closed", "none"}


async def test_filter_options_drop_date_like_education(db_session: AsyncSession):
    dept = _rand("脏数据部")
    db_session.add(DepartureRecord(
        name="学历脏数据", department=dept, position="操作工", offboarding_type="辞职",
        education="1983/09/18", offboarding_reason="个人原因",  # 存量：学历列错位、离职原因为标量
    ))
    await db_session.flush()
    options = await ledger_query.filter_options(db_session, {dept})
    assert options["educations"] == [] and options["offboarding_reasons"] == []


def test_export_column_registry_is_consistent():
    keys = [column.key for column in ledger_export.EXPORT_COLUMNS]
    assert len(keys) == len(set(keys))
    assert set(ledger_export.DEFAULT_EXPORT_KEYS) <= set(keys)
    assert {column.group for column in ledger_export.EXPORT_COLUMNS} == {
        "人员信息", "离职信息", "证明信息", "清退与结算", "流程信息",
    }
    with pytest.raises(AppException, match="未知的导出字段"):
        ledger_export.resolve_columns(["name", "password"])
    resolved = ledger_export.resolve_columns(["offboarding_date", "name"])
    assert [column.label for column in resolved] == ["离职日期", "姓名"]  # 按传入顺序出列


def test_export_clearance_cells_blank_when_no_data():
    """没有明细 / 金额为 0 的格子留空；非零金额输出数值，Excel 里可直接求和。"""
    amount = ledger_export.COLUMN_BY_KEY["finance_supplement"].getter
    progress = ledger_export.COLUMN_BY_KEY["finance_progress"].getter
    filled = {"clearance": {"finance": {"total": 1, "done": 1, "deduction": 0, "supplement": 12.5}}}
    empty = {"clearance": {"hr": {"total": 0, "done": 0, "deduction": 0, "supplement": 0}}}
    assert amount(filled, {}) == 12.5 and progress(filled, {}) == "1/1"
    assert ledger_export.COLUMN_BY_KEY["finance_deduction"].getter(filled, {}) == ""
    assert amount(empty, {}) == "" and progress(empty, {}) == ""


# ═══════════════════════════════════════════════════════════════
# 导出：字段勾选 / 脱敏 / 留痕
# ═══════════════════════════════════════════════════════════════

EXPORT_KEYS = [
    "name", "id_card", "offboarding_reason", "approval_node", "cert_issued_by",
    "admin_progress", "admin_deduction", "finance_progress", "current_handler", "entry_date",
]


async def test_export_selected_columns_and_audit_log(db_session: AsyncSession, seeded: dict[str, str]):
    operator_id = uuid4()
    workbook, count, headers = await ledger_export.export_ledger(
        db_session, {"department": seeded["dept"], "approval_status": "signed"}, EXPORT_KEYS,
        scoped=None, operator_id=operator_id, operator_name="HR乙",
    )
    assert count == 1  # 只导出「已签字确认」那一行，与列表同筛选口径

    grid = list(workbook.active.iter_rows(values_only=True))
    assert list(grid[0]) == headers == [
        "姓名", "身份证号", "离职原因", "审批节点", "HR 负责人",
        "行政后勤部清退进度", "行政后勤部扣款", "财务部清退进度", "当前处理人", "入职日期",
    ]
    body = grid[1]
    assert body[0] == seeded["A"]
    assert set(body[1]) == {"*"} and len(body[1]) == 18  # 身份证全部屏蔽
    assert body[2:5] == ("个人发展", "已签字确认", "HR乙")
    assert body[5:8] == ("2/3", 30, "1/1")
    assert body[8] == "HR乙"  # 已签字待办结：当前处理人是 HR 经办人
    assert str(body[9]).startswith("20")

    log = (await repo.list_export_logs(db_session, module="departure", limit=1))[0]
    assert log.row_count == 1 and log.operator_name == "HR乙" and log.operator_id == operator_id
    assert log.filters == {"department": seeded["dept"], "approval_status": "signed"}
    assert log.columns == EXPORT_KEYS
    shown = ledger_export.export_log_dict(log)
    assert shown["filters"] == {"部门": seeded["dept"], "办理状态": "已签字确认"}  # 状态码转成文案
    assert "身份证号" in shown["columns"] and "name" not in shown["columns"]


# ═══════════════════════════════════════════════════════════════
# 保存视图
# ═══════════════════════════════════════════════════════════════

async def test_saved_view_crud_and_ownership(db_session: AsyncSession):
    owner, stranger = uuid4(), uuid4()
    view = await ledger_views.create_view(
        db_session, owner, name="本月辞职",
        filters={"offboarding_type": "辞职", "cert_issued": True},
        columns=["name", "department", "不存在的字段"], is_default=True,
    )
    assert view.is_default is True
    assert view.columns == ["name", "department"]  # 注册表外的 key 不落库

    with pytest.raises(AppException, match="已有名为"):
        await ledger_views.create_view(db_session, owner, name="本月辞职", filters={}, columns=[])
    second = await ledger_views.create_view(
        db_session, owner, name="待办结", filters={}, columns=[], is_default=True,
    )
    defaults = [v for v in await ledger_views.list_views(db_session, owner) if v.is_default]
    assert [v.id for v in defaults] == [second.id]  # 同一人只保留一个默认视图

    updated = await ledger_views.update_view(
        db_session, owner, view.id, name="本月已开证", is_default=True, filters={"cert_issued": True},
    )
    assert updated.name == "本月已开证" and updated.filters == {"cert_issued": True}
    assert updated.is_default is True and second.is_default is False

    # 视图只属于创建人：别人看不到、改不了、删不了
    assert await ledger_views.list_views(db_session, stranger) == []
    with pytest.raises(NotFoundException):
        await ledger_views.update_view(db_session, stranger, view.id, name="越权改名")
    with pytest.raises(NotFoundException):
        await ledger_views.delete_view(db_session, stranger, view.id)

    await ledger_views.delete_view(db_session, owner, view.id)
    assert [v.id for v in await ledger_views.list_views(db_session, owner)] == [second.id]


async def test_update_view_keeps_fields_not_passed(db_session: AsyncSession):
    owner = uuid4()
    view = await ledger_views.create_view(
        db_session, owner, name="原视图", filters={"gender": "女"}, columns=["name"],
    )
    updated = await ledger_views.update_view(db_session, owner, view.id, name="新名字")
    assert updated.filters == {"gender": "女"} and updated.columns == ["name"]


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

async def test_api_ledger_end_to_end(client, db_session: AsyncSession, seeded: dict[str, str]):
    queried = await client.post("/api/v1/hr/departure-ledger/query", json={
        "department": seeded["dept"], "gender": "女", "page_size": 50,
    })
    assert queried.status_code == 200, queried.text
    body = queried.json()
    assert body["meta"]["total"] == 2
    assert {row["name"] for row in body["data"]} == _pick(seeded, "AC")
    assert all("cert_sign_image" not in row for row in body["data"])
    a_row = next(row for row in body["data"] if row["name"] == seeded["A"])
    assert set(a_row["id_card"]) == {"*"}  # 测试用户无敏感权限：身份证屏蔽

    bad = await client.post("/api/v1/hr/departure-ledger/query", json={"sort_by": "id_card"})
    assert bad.status_code == 422  # 排序字段白名单

    options = (await client.get("/api/v1/hr/departure-ledger/filter-options")).json()["data"]
    assert seeded["dept"] in options["departments"] and "approval_statuses" in options

    columns = (await client.get("/api/v1/hr/departure-ledger/export-columns")).json()["data"]
    assert len(columns["columns"]) == len(ledger_export.EXPORT_COLUMNS)
    assert set(columns["default_keys"]) == set(ledger_export.DEFAULT_EXPORT_KEYS)

    exported = await client.post("/api/v1/hr/departure-ledger/export", json={
        "department": seeded["dept"], "gender": "女",
        "columns": ["name", "id_card", "approval_node", "admin_deduction"],
    })
    assert exported.status_code == 200, exported.text
    grid = list(load_workbook(io.BytesIO(exported.content)).active.iter_rows(values_only=True))
    assert list(grid[0]) == ["姓名", "身份证号", "审批节点", "行政后勤部扣款"]
    assert {row[0] for row in grid[1:]} == _pick(seeded, "AC")
    # 身份证有值的一律屏蔽，没值的留空
    assert all(set(row[1]) == {"*"} for row in grid[1:] if row[1])
    assert any(not row[1] for row in grid[1:])  # 线下行 C 没有身份证号：留空（openpyxl 读回是 None）

    unknown = await client.post("/api/v1/hr/departure-ledger/export", json={"columns": ["nope"]})
    assert unknown.status_code == 422

    logs = (await client.get("/api/v1/hr/departure-ledger/export-logs")).json()["data"]
    assert logs[0]["row_count"] == 2 and logs[0]["operator_name"] == "HR测试员"
    assert logs[0]["filters"] == {"部门": seeded["dept"], "性别": "女"}

    # 保存视图：存 → 列 → 改 → 删
    created = await client.post("/api/v1/hr/departure-ledger/saved-views", json={
        "name": "女员工未开证", "filters": {"gender": "女", "cert_issued": False},
        "columns": ["name", "approval_node"], "is_default": True,
    })
    assert created.status_code == 200, created.text
    view = created.json()["data"]
    assert view["filters"] == {"gender": "女", "cert_issued": False} and view["is_default"] is True

    listed = (await client.get("/api/v1/hr/departure-ledger/saved-views")).json()["data"]
    assert [v["id"] for v in listed] == [view["id"]]

    renamed = await client.put(f"/api/v1/hr/departure-ledger/saved-views/{view['id']}", json={
        "name": "未开证", "filters": {"cert_issued": False}, "columns": ["name"],
    })
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["name"] == "未开证"
    assert renamed.json()["data"]["is_default"] is False

    assert (await client.delete(f"/api/v1/hr/departure-ledger/saved-views/{view['id']}")).status_code == 200
    assert (await client.delete(f"/api/v1/hr/departure-ledger/saved-views/{view['id']}")).status_code == 404
    assert (await client.get("/api/v1/hr/departure-ledger/saved-views")).json()["data"] == []
