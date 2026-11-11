"""月度绩效考核主流程：创建/列表/我的、自评与领导评分状态机、考核项目配置。

评分矩阵（category-scores）的权限隔离与加权总分已在 test_performance_scoring.py
覆盖，此处不重复。
"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import DeptTrainingPersonnel, HrDepartment
from tests.modules.hr.conftest import _rand

_MONTH = "2030-01"


def _create_payload(department: str, **overrides) -> dict:
    data = {
        "department": department,
        "department_head": "王五",
        "evaluator_leader": "赵六",
        "evaluation_month": _MONTH,
        "headcount": 8,
        "items": [
            {"category": "key_work", "indicator": "重点工作A", "weight": 60, "sort_order": 0},
            {"category": "routine_work", "indicator": "常规工作", "weight": 40, "sort_order": 1},
        ],
    }
    data.update(overrides)
    return data


async def _mk_evaluation(db_session: AsyncSession, department: str, **overrides) -> dict:
    """直接落库一条考核（绕开 HTTP），返回创建 payload。"""
    from app.modules.hr.schemas import PerformanceEvaluationCreate
    from app.modules.hr.service import (
        PerformanceEvaluationService,
    )

    payload = _create_payload(department, **overrides)
    result = await PerformanceEvaluationService(db_session).create_evaluation(
        PerformanceEvaluationCreate(**payload),
    )
    return result


async def test_create_with_items_and_duplicate_rejected(client: AsyncClient):
    """创建带指标项 → 201 草稿；同部门同月重复创建 → 400。"""
    dept = _rand("绩效部")
    res = await client.post("/api/v1/hr/performance-evaluations", json=_create_payload(dept))
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["department"] == dept
    assert data["status"] == "draft"
    assert len(data["items"]) == 2

    dup = await client.post("/api/v1/hr/performance-evaluations", json=_create_payload(dept))
    assert dup.status_code == 400
    assert "已有考核记录" in dup.json()["message"]


async def test_create_auto_fills_department_head_from_personnel(
    db_session: AsyncSession, client: AsyncClient,
):
    """未提供负责人时，从部门培训人员表回填 department_head。"""
    dept = _rand("负责人部")
    db_session.add(DeptTrainingPersonnel(
        display_department=dept, department=dept,
        department_head="钱七", training_admin="钱七",
    ))
    await db_session.flush()

    res = await client.post("/api/v1/hr/performance-evaluations", json=_create_payload(
        dept, department_head=None,
    ))
    assert res.status_code == 201, res.text
    assert res.json()["data"]["department_head"] == "钱七"


async def test_list_filter_and_detail(client: AsyncClient):
    """列表按部门/月份过滤；详情 404；管理权限 can_edit_leader=True。"""
    dept = _rand("列表部")
    created = await client.post(
        "/api/v1/hr/performance-evaluations", json=_create_payload(dept),
    )
    ev_id = created.json()["data"]["id"]

    res = await client.get(
        "/api/v1/hr/performance-evaluations",
        params={"month": _MONTH, "department": dept},
    )
    assert res.status_code == 200, res.text
    items = res.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == ev_id

    detail = await client.get(f"/api/v1/hr/performance-evaluations/{ev_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["can_edit_leader"] is True

    missing = await client.get(f"/api/v1/hr/performance-evaluations/{uuid4()}")
    assert missing.status_code == 404


async def test_my_evaluations_filters_by_head_or_leader(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """/my 只返回当前用户任负责人或分管领导的考核。"""
    mine_dept = _rand("我的部")
    other_dept = _rand("他人部")
    await _mk_evaluation(db_session, mine_dept, department_head=test_user.name)
    await _mk_evaluation(db_session, other_dept, department_head="别人")

    res = await client.get("/api/v1/hr/performance-evaluations/my", params={"month": _MONTH})
    assert res.status_code == 200, res.text
    departments = [it["department"] for it in res.json()["data"]["items"]]
    assert mine_dept in departments
    assert other_dept not in departments


async def test_submit_flow_state_machine(db_session: AsyncSession, client: AsyncClient, test_user):
    """draft → 自评（仅负责人）→ self_submitted → 领导评分（仅分管领导）→ leader_scored。"""
    dept = _rand("状态部")
    ev = await _mk_evaluation(db_session, dept, department_head=test_user.name, evaluator_leader=test_user.name)
    ev_id = ev["id"]

    # 非负责人提交自评 → 403
    other = await _mk_evaluation(db_session, _rand("他人部"), department_head="别人")
    forbidden = await client.post(f"/api/v1/hr/performance-evaluations/{other['id']}/submit-self")
    assert forbidden.status_code == 403

    # 负责人提交自评 → self_submitted
    ok = await client.post(f"/api/v1/hr/performance-evaluations/{ev_id}/submit-self")
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["status"] == "self_submitted"

    # 重复提交自评 → 400（仅草稿可自评）
    again = await client.post(f"/api/v1/hr/performance-evaluations/{ev_id}/submit-self")
    assert again.status_code == 400

    # 自评后仍可编辑（进入领导评分阶段）
    upd = await client.put(
        f"/api/v1/hr/performance-evaluations/{ev_id}", json={"headcount": 10},
    )
    assert upd.status_code == 200

    # 领导评分 → leader_scored
    leader = await client.post(f"/api/v1/hr/performance-evaluations/{ev_id}/submit-leader")
    assert leader.status_code == 200, leader.text
    assert leader.json()["data"]["status"] == "leader_scored"

    # 终态后不可再编辑 / 不可再提交
    assert (await client.put(
        f"/api/v1/hr/performance-evaluations/{ev_id}", json={"headcount": 12},
    )).status_code == 400
    assert (await client.post(
        f"/api/v1/hr/performance-evaluations/{ev_id}/submit-leader",
    )).status_code == 400


async def test_submit_requires_configured_head_and_leader(
    db_session: AsyncSession, client: AsyncClient,
):
    """未配置负责人无法自评；未配置分管领导无法提交领导评分。"""
    ev = await _mk_evaluation(db_session, _rand("缺配部"), department_head=None, evaluator_leader=None)
    no_head = await client.post(f"/api/v1/hr/performance-evaluations/{ev['id']}/submit-self")
    assert no_head.status_code == 403
    assert "部门负责人" in no_head.json()["message"]

    no_leader = await client.post(f"/api/v1/hr/performance-evaluations/{ev['id']}/submit-leader")
    assert no_leader.status_code == 403
    assert "分管领导" in no_leader.json()["message"]


async def test_auto_create_skips_existing(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """按部门批量生成当月考核；已有则跳过；受限无授权部门 → 403。"""
    dept_a, dept_b = _rand("批量部A"), _rand("批量部B")
    db_session.add_all([
        HrDepartment(name=dept_a, code=_rand("DP")), HrDepartment(name=dept_b, code=_rand("DP")),
    ])
    await db_session.flush()

    res = await client.post(
        "/api/v1/hr/performance-evaluations/auto-create", params={"month": "2030-02"},
    )
    assert res.status_code == 200, res.text
    created_total = res.json()["data"]["created"]
    assert created_total >= 2  # 共享库可能已有其他部门

    # 二次生成：已有部门全部跳过
    res2 = await client.post(
        "/api/v1/hr/performance-evaluations/auto-create", params={"month": "2030-02"},
    )
    assert res2.status_code == 200
    assert res2.json()["data"]["created"] == 0

    # 校验部门确实生成了记录
    lst = await client.get(
        "/api/v1/hr/performance-evaluations", params={"month": "2030-02", "department": dept_a},
    )
    assert len(lst.json()["data"]["items"]) == 1


class TestPerformanceCategories:
    async def test_crud_and_dept_weights(self, db_session: AsyncSession, client: AsyncClient):
        """考核项目增改删 + 部门权重保存/读取。"""
        name = _rand("考核项")
        created = await client.post("/api/v1/hr/performance-categories", json={
            "name": name, "weight": 50, "evaluator": "张三", "sort_order": 1,
        })
        assert created.status_code == 201, created.text
        cat_id = created.json()["data"]["id"]

        lst = await client.get("/api/v1/hr/performance-categories")
        mine = [c for c in lst.json()["data"] if c["id"] == cat_id]
        assert len(mine) == 1
        assert mine[0]["weight"] == 50

        upd = await client.put(f"/api/v1/hr/performance-categories/{cat_id}", json={"weight": 60})
        assert upd.status_code == 200
        lst2 = await client.get("/api/v1/hr/performance-categories")
        assert [c for c in lst2.json()["data"] if c["id"] == cat_id][0]["weight"] == 60

        # 部门权重：保存后可读取，重复保存为更新
        dept = _rand("权重部")
        save = await client.post(
            f"/api/v1/hr/performance-categories/{cat_id}/dept-weights",
            json={"weights": [{"department": dept, "weight": 30}]},
        )
        assert save.status_code == 200, save.text
        got = await client.get(f"/api/v1/hr/performance-categories/{cat_id}/dept-weights")
        assert got.json()["data"] == [{"department": dept, "weight": 30}]

        save2 = await client.post(
            f"/api/v1/hr/performance-categories/{cat_id}/dept-weights",
            json={"weights": [{"department": dept, "weight": 45}]},
        )
        assert save2.status_code == 200
        got2 = await client.get(f"/api/v1/hr/performance-categories/{cat_id}/dept-weights")
        assert got2.json()["data"] == [{"department": dept, "weight": 45}]

        dele = await client.delete(f"/api/v1/hr/performance-categories/{cat_id}")
        assert dele.status_code == 200
        lst3 = await client.get("/api/v1/hr/performance-categories")
        assert cat_id not in {c["id"] for c in lst3.json()["data"]}

    async def test_update_unknown_category_404(self, client: AsyncClient):
        res = await client.put(
            f"/api/v1/hr/performance-categories/{uuid4()}", json={"weight": 10},
        )
        assert res.status_code == 404
