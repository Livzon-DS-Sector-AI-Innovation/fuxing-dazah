"""笔试试卷（/exam-papers）：保存、列表（部门数据范围）、Word 下载。"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import ExamPaper
from tests.modules.hr.conftest import _rand

_QUESTIONS = {
    "choice_questions": [
        {"question": "进入洁净区前应做什么？", "options": ["A. 洗手", "B. 更衣", "C. 二者都要"], "answer": "C", "score": 5},
    ],
    "true_false_questions": [
        {"question": "SOP 文件可以随意修改。", "answer": "错", "score": 5},
    ],
}


def _paper_payload(department: str) -> dict:
    return {
        "subject": _rand("试卷主题"),
        "department": department,
        "training_date": "2026-06-15",
        "training_method": "线下",
        "questions": _QUESTIONS,
        "full_score": 100,
        "pass_line": 80,
        "choice_count": 1,
        "true_false_count": 1,
    }


async def test_save_list_and_download(client: AsyncClient):
    """保存 → 列表可见（含题型计数）→ 下载为非空 docx；未知 ID 下载 404。"""
    dept = _rand("试卷部")
    saved = await client.post("/api/v1/hr/exam-papers", json=_paper_payload(dept))
    assert saved.status_code == 201, saved.text
    paper_id = saved.json()["data"]["id"]

    lst = await client.get("/api/v1/hr/exam-papers", params={"page_size": 200})
    assert lst.status_code == 200, lst.text
    mine = [p for p in lst.json()["data"] if p["id"] == paper_id]
    assert len(mine) == 1
    assert mine[0]["department"] == dept
    assert mine[0]["choice_count"] == 1
    assert mine[0]["true_false_count"] == 1
    assert mine[0]["training_date"] == "2026-06-15"

    dl = await client.get(f"/api/v1/hr/exam-papers/{paper_id}/download")
    assert dl.status_code == 200, dl.text
    assert "wordprocessingml" in dl.headers["content-type"]
    assert len(dl.content) > 5000  # 模板生成的完整试卷

    missing = await client.get(f"/api/v1/hr/exam-papers/{paper_id}x/download")
    assert missing.status_code in (404, 422)  # 非法 UUID 为 422


def _scoped(test_user, departments: frozenset[str]):
    async def _override() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department=next(iter(departments)) if departments else None,
            employee_number=test_user.employee_no,
            scoped_departments=departments,
        )
    return _override


async def test_list_restricted_to_scoped_departments(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """受限用户只看授权部门的试卷；无授权部门 → 403。"""
    dept_a, dept_b = _rand("授权部"), _rand("外部部")
    db_session.add_all([
        ExamPaper(subject=_rand("A卷"), department=dept_a, full_score=100, pass_line=80),
        ExamPaper(subject=_rand("B卷"), department=dept_b, full_score=100, pass_line=80),
    ])
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({dept_a}))
    try:
        res = await client.get("/api/v1/hr/exam-papers", params={"page_size": 200})
        assert res.status_code == 200, res.text
        assert {p["department"] for p in res.json()["data"]} == {dept_a}
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)

    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset())
    try:
        empty_scope = await client.get("/api/v1/hr/exam-papers")
        assert empty_scope.status_code == 403
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_download_unknown_paper_404(client: AsyncClient):
    from uuid import uuid4

    res = await client.get(f"/api/v1/hr/exam-papers/{uuid4()}/download")
    assert res.status_code == 404
