"""新员工信息收集（飞书机器人表单卡片）测试。

覆盖：字段校验/清洗、发起（发卡+跳过场景）、卡片提交回调（身份防代填、
格式校验、upsert）、采纳（写源表列自适配 + 员工账号回填 + 本地预更新）、
驳回（状态回滚重发）、平台回调注册。

回调走独立 session factory（async_session_factory），按根 conftest 约定
用 _test_session_factory 真实 commit 并自行清理。
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete

from app.modules.hr.employee_info_collection_service import (
    CARD_ACTION,
    _clean_form,
    _validate_form,
    approve_collection,
    create_collections,
    handle_card_submit,
    register_feishu_callbacks,
    reject_collection,
)
from app.modules.hr.models import Employee, EmployeeInfoCollection
from tests.conftest import _test_session_factory
from tests.modules.hr.conftest import _rand

_GOOD_FORM = {
    "id_card": "110101199003077758",
    "phone": "13800001111",
    "education": "本科",
    "degree_type": "学士",
    "school": "某某大学",
    "major": "化学工程",
    "emergency_contact_name": "张三",
    "emergency_contact_phone": "13900002222",
}


# ─── 纯函数：校验与清洗 ───


def test_validate_form_rejects_bad_id_card():
    errors = _validate_form({**_GOOD_FORM, "id_card": "12345"})
    assert any("身份证" in e for e in errors)


def test_validate_form_requires_mandatory_fields():
    errors = _validate_form({})
    assert len(errors) >= 5  # id_card/phone/education/school/紧急联系人 等


def test_validate_form_accepts_good_form():
    assert _validate_form(_GOOD_FORM) == []


def test_clean_form_filters_whitelist_and_trims():
    cleaned = _clean_form({**_GOOD_FORM, "name": "应被过滤", "school": "  某某大学  "})
    assert "name" not in cleaned
    assert cleaned["school"] == "某某大学"
    assert cleaned["phone"] == "13800001111"


# ─── 发起收集 ───


def _mk_employee(db, *, open_id: str | None = None, record_id: str | None = None) -> Employee:
    e = Employee(
        name=_rand("员工"), employee_number=_rand("EMP"),
        department="技术部", position="工程师",
        hire_date=date.today(), feishu_open_id=open_id,
        feishu_record_id=record_id,
    )
    db.add(e)
    return e


async def _mk_employee_flushed(db, **kwargs) -> Employee:
    """flush 保证 employee.id 已生成后再被外键引用。"""
    e = _mk_employee(db, **kwargs)
    await db.flush()
    return e


async def test_create_collections_sends_card_and_creates_record(db_session):
    emp = await _mk_employee_flushed(db_session, open_id="ou_open_1")

    with patch(
        "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
    ) as mock_send:
        result = await create_collections(db_session, [emp.id], operator="测试HR")

    assert result["created"] == 1
    assert result["skipped"] == []
    card = mock_send.await_args.args[1]
    assert card["header"]["title"]["content"] == "新员工信息登记"
    # 表单里必含身份证/紧急联系人等字段与提交按钮（value 带任务定位）
    form = next(el for el in card["body"]["elements"] if el.get("tag") == "form")
    names = {el.get("name") for el in form["elements"]}
    assert {"id_card", "phone", "emergency_contact_name"} <= names
    btn = next(el for el in form["elements"] if el.get("action_type") == "form_submit")
    assert btn["value"]["action"] == CARD_ACTION


async def test_create_collections_skips_without_open_id(db_session):
    emp = await _mk_employee_flushed(db_session)  # 无 feishu_open_id

    with (
        patch("app.modules.hr.feishu_review_service._lookup_open_id", new=AsyncMock(return_value=None)),
        patch(
            "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
        ) as mock_send,
    ):
        result = await create_collections(db_session, [emp.id], operator="测试HR")

    assert result["created"] == 0
    assert "open_id" in result["skipped"][0]["reason"]
    mock_send.assert_not_awaited()


async def test_create_collections_skips_active_task(db_session):
    emp = await _mk_employee_flushed(db_session, open_id="ou_open_2")
    db_session.add(EmployeeInfoCollection(employee_id=emp.id, open_id="ou_open_2", status="sent"))
    await db_session.flush()

    with patch(
        "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
    ) as mock_send:
        result = await create_collections(db_session, [emp.id], operator="测试HR")

    assert result["created"] == 0
    assert "进行中" in result["skipped"][0]["reason"]
    mock_send.assert_not_awaited()


# ─── 卡片提交回调（独立 factory，真实 commit + 自行清理） ───


async def _setup_with_factory() -> tuple[uuid.UUID, str]:
    async with _test_session_factory() as s:
        e = Employee(
            name=_rand("回调员工"), employee_number=_rand("CB"),
            department="技术部", position="工程师", hire_date=date.today(),
        )
        s.add(e)
        await s.flush()  # 先生成 employee.id 再被外键引用
        c = EmployeeInfoCollection(employee_id=e.id, open_id="ou_cb_1", status="sent")
        s.add(c)
        await s.commit()
        return c.id, "ou_cb_1"


async def _cleanup_collection(collection_id: uuid.UUID) -> None:
    """清理回调测试造的数据：收集任务 + 员工档案一起删。

    历史教训：只删任务不删员工时，测试员工（回调员工XXXX）会真实
    写入共享库并泄漏进员工导出/看板统计——务必成对清理。
    """
    async with _test_session_factory() as s:
        c = await s.get(EmployeeInfoCollection, collection_id)
        if c is not None:
            emp = await s.get(Employee, c.employee_id)
            await s.delete(c)
            await s.flush()  # 先落库删任务解除外键，再删员工
            if emp is not None:
                await s.delete(emp)
        await s.commit()


async def test_card_submit_upserts_submission():
    cid, open_id = await _setup_with_factory()
    try:
        payload = {
            "action": CARD_ACTION, "collection_id": str(cid),
            "_form_value": _GOOD_FORM, "_open_id": open_id,
        }
        with (
            patch("app.core.database.async_session_factory", _test_session_factory),
            patch(
                "app.modules.hr.employee_info_collection_service._send_card",
                new=AsyncMock(return_value=True),
            ),
        ):
            result = await handle_card_submit(payload, "u1")

        assert result == {"toast": {"type": "success", "content": "已提交，等待人事确认"}}
        async with _test_session_factory() as s:
            c = await s.get(EmployeeInfoCollection, cid)
            assert c is not None
            assert c.status == "submitted"
            assert c.form_data["id_card"] == "110101199003077758"
    finally:
        await _cleanup_collection(cid)


async def test_card_submit_rejects_wrong_open_id():
    cid, _ = await _setup_with_factory()
    try:
        payload = {
            "action": CARD_ACTION, "collection_id": str(cid),
            "_form_value": _GOOD_FORM, "_open_id": "ou_someone_else",
        }
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_card_submit(payload, "u2")

        assert result["toast"]["type"] == "error"
        async with _test_session_factory() as s:
            c = await s.get(EmployeeInfoCollection, cid)
            assert c is not None
            assert c.status == "sent"  # 未被篡改
    finally:
        await _cleanup_collection(cid)


async def test_card_submit_rejects_bad_format():
    cid, open_id = await _setup_with_factory()
    try:
        payload = {
            "action": CARD_ACTION, "collection_id": str(cid),
            "_form_value": {**_GOOD_FORM, "id_card": "abc"}, "_open_id": open_id,
        }
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_card_submit(payload, "u3")

        assert result["toast"]["type"] == "error"
        assert "身份证" in result["toast"]["content"]
    finally:
        await _cleanup_collection(cid)


# ─── 审核：采纳与驳回 ───


def _ready_config():
    from app.modules.hr.employee_sync.config import EmployeeSyncConfig

    return EmployeeSyncConfig(enabled=True, app_token="app_x", source_table_id="tbl_y")


async def _mk_submitted(db, *, form_data=None) -> tuple[EmployeeInfoCollection, Employee]:
    e = await _mk_employee_flushed(db, open_id="ou_ap_1", record_id="rec_1")
    c = EmployeeInfoCollection(
        employee_id=e.id, open_id="ou_ap_1", status="submitted",
        form_data=form_data or {"id_card": "110101199003077758", "phone": "13800001111"},
    )
    db.add(c)
    await db.flush()
    return c, e


async def test_approve_writes_source_table_and_updates_employee(db_session):
    c, e = await _mk_submitted(db_session)

    fields = [{"field_name": n} for n in ("身份证号", "联系电话", "员工账号")]
    with (
        patch(
            "app.modules.hr.employee_info_collection_service.load_config",
            new=AsyncMock(return_value=_ready_config()),
        ),
        patch(
            "app.platform.integrations.feishu.bitable.list_fields",
            new=AsyncMock(return_value=fields),
        ) as mock_lf,
        patch(
            "app.platform.integrations.feishu.bitable.update_record", new=AsyncMock(),
        ) as mock_update,
        patch(
            "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
        ),
    ):
        result = await approve_collection(db_session, c.id, reviewer="测试HR")

    assert result["written_fields"] == 3  # 身份证号 + 联系电话 + 员工账号
    # 写入源表的列名自适配（ORM 字段 → 源表实际列名）+ 员工账号回填 open_id
    kwargs = mock_update.await_args.kwargs
    payload = kwargs.get("fields") or mock_update.await_args.args[3]
    assert payload["身份证号"] == "110101199003077758"
    assert payload["联系电话"] == "13800001111"
    assert payload["员工账号"] == {"id": "ou_ap_1"}
    assert mock_update.await_args.args[2] == "rec_1"  # 按员工源表记录定位
    # 本地档案同值预更新 + 任务完结
    assert e.id_card == "110101199003077758"
    assert e.phone == "13800001111"
    assert c.status == "approved"
    assert c.reviewed_by == "测试HR"


async def test_approve_skips_missing_source_column(db_session):
    c, _ = await _mk_submitted(db_session, form_data={"id_card": "110101199003077758", "native_place": "浙江"})

    with (
        patch(
            "app.modules.hr.employee_info_collection_service.load_config",
            new=AsyncMock(return_value=_ready_config()),
        ),
        patch(
            "app.platform.integrations.feishu.bitable.list_fields",
            new=AsyncMock(return_value=[{"field_name": "身份证号"}]),  # 源表无籍贯/员工账号列
        ),
        patch("app.platform.integrations.feishu.bitable.update_record", new=AsyncMock()),
        patch(
            "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
        ),
    ):
        result = await approve_collection(db_session, c.id, reviewer="测试HR")

    assert result["written_fields"] == 1
    assert result["skipped_fields"] == ["籍贯"]


async def test_approve_requires_submitted_status(db_session):
    e = await _mk_employee_flushed(db_session, open_id="ou_ap_2", record_id="rec_2")
    c = EmployeeInfoCollection(employee_id=e.id, open_id="ou_ap_2", status="sent")
    db_session.add(c)
    await db_session.flush()

    with pytest.raises(ValueError, match="已提交待审核"):
        await approve_collection(db_session, c.id, reviewer="测试HR")


async def test_reject_rolls_back_to_sent_and_resends(db_session):
    c, _ = await _mk_submitted(db_session)

    with patch(
        "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
    ) as mock_send:
        await reject_collection(db_session, c.id, reason="身份证号有误", reviewer="测试HR")

    assert c.status == "sent"  # 回滚待重填（同一记录复用，唯一索引不冲突）
    assert c.reject_reason == "身份证号有误"
    card = mock_send.await_args.args[1]
    assert "身份证号有误" in card["body"]["elements"][0]["content"]  # 驳回原因置顶


async def test_reject_send_failure_raises(db_session):
    c, _ = await _mk_submitted(db_session)

    with patch(
        "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=False),
    ):
        with pytest.raises(ValueError, match="发送失败"):
            await reject_collection(db_session, c.id, reason="x", reviewer="测试HR")


# ─── 平台回调注册 ───


def test_register_feishu_callbacks():
    from app.platform.integrations.feishu.event_handler import _CARD_ACTION_HANDLERS

    _CARD_ACTION_HANDLERS.pop(CARD_ACTION, None)  # 允许重复执行（如测试重跑）
    register_feishu_callbacks()
    assert _CARD_ACTION_HANDLERS.get(CARD_ACTION) is handle_card_submit


# ─── API 级：路由挂载 + 权限链路 ───


async def test_api_create_and_list(client, db_session):
    """发起收集走 API（含权限映射），列表返回 diff 结构。"""
    from httpx import AsyncClient

    assert isinstance(client, AsyncClient)  # 类型提示
    emp = await _mk_employee_flushed(db_session, open_id="ou_api_1")
    with patch(
        "app.modules.hr.employee_info_collection_service._send_card", new=AsyncMock(return_value=True),
    ):
        res = await client.post(
            "/api/v1/hr/employee-info-collections", json={"employee_ids": [str(emp.id)]},
        )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["created"] == 1

    lst = await client.get("/api/v1/hr/employee-info-collections?status=sent")
    assert lst.status_code == 200
    rows = lst.json()["data"]
    mine = [r for r in rows if r["employee_name"] == emp.name]
    assert mine and mine[0]["status"] == "sent"
    assert len(mine[0]["diff"]) >= 10  # 15 项字段差异结构齐备


async def test_api_approve_requires_submitted(client, db_session):
    """非 submitted 状态采纳 → 400 业务提示。"""
    emp = await _mk_employee_flushed(db_session, open_id="ou_api_2", record_id="rec_api")
    db_session.add(EmployeeInfoCollection(employee_id=emp.id, open_id="ou_api_2", status="sent"))
    await db_session.flush()

    res = await client.post(f"/api/v1/hr/employee-info-collections/{await _last_collection_id(db_session, emp.id)}/approve")
    assert res.status_code == 400
    assert "已提交待审核" in res.json()["message"]


async def _last_collection_id(db, employee_id) -> uuid.UUID:
    from sqlalchemy import select

    return (await db.execute(
        select(EmployeeInfoCollection.id).where(
            EmployeeInfoCollection.employee_id == employee_id,
            EmployeeInfoCollection.is_deleted.is_(False),
        ).order_by(EmployeeInfoCollection.created_at.desc())
    )).scalars().first()


# ─── onboard 自动发起信息收集（路由级） ───


async def test_onboard_auto_sends_info_collection(client, db_session):
    """一键入职成功后自动给新员工发信息收集表单。"""
    from datetime import date as date_type

    from app.modules.hr.models import Candidate

    c = Candidate(id=uuid.uuid4(), name=_rand("自动收集"), status="待入职审批",
                  department="QC部", position="QC工程师")
    db_session.add(c)
    await db_session.flush()

    with (
        patch("app.modules.hr.feishu_review_service._lookup_open_id",
              new=AsyncMock(return_value="ou_auto_1")),
        patch(
            "app.modules.hr.employee_info_collection_service._send_card",
            new=AsyncMock(return_value=True),
        ) as mock_send,
    ):
        res = await client.post(f"/api/v1/hr/candidates/{c.id}/onboard")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["info_collection_sent"] is True
    assert "信息收集表单已发送" in res.json()["message"]
    # 卡片发给按姓名解析出的 open_id
    assert mock_send.await_args.args[0] == "ou_auto_1"


async def test_onboard_auto_send_degrades_without_open_id(client, db_session):
    """未绑定飞书账号的员工：入职照常成功，收集降级为提示（不失败）。"""
    from app.modules.hr.models import Candidate

    c = Candidate(id=uuid.uuid4(), name=_rand("无账号入职"), status="待入职审批",
                  department="QC部", position="QC工程师")
    db_session.add(c)
    await db_session.flush()

    with patch("app.modules.hr.feishu_review_service._lookup_open_id",
               new=AsyncMock(return_value=None)):
        res = await client.post(f"/api/v1/hr/candidates/{c.id}/onboard")

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["info_collection_sent"] is False
    assert "信息收集未发送" in res.json()["message"]
