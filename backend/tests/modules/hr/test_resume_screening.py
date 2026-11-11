"""AI 简历筛选：PDF 全文提取 → 适配度分析报告 → 落库排名 → 转候选人。

DeepSeek 调用全程 mock；PDF 用 fpdf2 生成文字版（中文需嵌入字体，
测试内容用英文即可——只验证提取与流转，AI 结果是 mock 的）。
报告结构对齐《岗位适配度分析+复试推荐意见》范例。
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fpdf import FPDF
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import JobRequirement
from tests.modules.hr.conftest import _rand

# 模拟 AI 输出：结构与《岗位适配度分析+复试推荐意见》范例一致
_FAKE_AI_RESULT = {
    "candidate_name": "张三",
    "advantages": [
        {"title": "专业门槛达标", "detail": "药学本科，掌握药品基础逻辑，满足 QA 最低专业门槛。"},
        {"title": "地域与薪资适配", "detail": "人在福州，通勤方便，薪资预期低。"},
    ],
    "flaws": [
        {"title": "英语硬性条件不达标", "detail": "无四级证书，无法独立阅读英文药典与申报文件。"},
        {"title": "无工业药企经验", "detail": "实习全部在医院药房，GMP 仅字面概念，培训成本高。"},
    ],
    "score_table": [
        {"dimension": "专业匹配", "score": 30, "comment": "临床药学不匹配原料药工业 QA"},
        {"dimension": "语言能力", "score": 10, "comment": "无四级，依赖翻译软件"},
        {"dimension": "地域&薪资适配", "score": 85, "comment": "本地、预期低"},
    ],
    "total_score": 42,
    "recommendation": "不推荐",
    "final_verdict": "不建议邀约复试，直接婉拒候选人",
    "final_reasons": ["英语硬性条件不满足", "岗位认知偏差大，入职后易离职"],
}


def _make_pdf(lines: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in lines:
        pdf.multi_cell(w=180, h=6, text=line)
    return bytes(pdf.output())


async def _mk_jd(db_session: AsyncSession) -> JobRequirement:
    jd = JobRequirement(
        id=uuid4(), position_name=_rand("筛岗"), department=_rand("筛部门"),
        headcount=1, requirements="药学相关专业，3 年以上 QC 经验",
        duties="负责原辅料检验与稳定性考察",
    )
    db_session.add(jd)
    await db_session.flush()
    return jd


async def _screen(
    client: AsyncClient, jd_id, pdf: bytes, ai_result: dict, filename: str = "张三简历.pdf",
):
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value=ai_result),
    ):
        return await client.post(
            f"/api/v1/hr/resume-screening/{jd_id}",
            files={"file": (filename, pdf, "application/pdf")},
        )


async def test_screen_resume_and_ranking(db_session: AsyncSession, client: AsyncClient):
    """筛选落库：优势/硬伤/打分表/最终意见齐全；列表按总分降序（即排名）。"""
    jd = await _mk_jd(db_session)
    pdf = _make_pdf([
        "John Smith - QC Engineer",
        "Bachelor of Pharmacy, 5 years QC experience in API plant.",
    ])

    res = await _screen(client, jd.id, pdf, _FAKE_AI_RESULT)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["candidate_name"] == "张三"
    assert data["total_score"] == 42
    assert data["recommendation"] == "不推荐"
    assert data["final_verdict"] == "不建议邀约复试，直接婉拒候选人"
    assert [a["title"] for a in data["advantages"]] == ["专业门槛达标", "地域与薪资适配"]
    assert "英语" in data["flaws"][0]["title"]
    assert data["score_table"][0]["dimension"] == "专业匹配"
    assert data["score_table"][0]["score"] == 30
    assert data["final_reasons"] == ["英语硬性条件不满足", "岗位认知偏差大，入职后易离职"]
    assert "要求：药学相关专业" in data["jd_snapshot"]

    # 第二份高分简历 → 排名在其前
    high = {**_FAKE_AI_RESULT, "candidate_name": "李四", "total_score": 81, "recommendation": "推荐"}
    await _screen(client, jd.id, pdf, high, filename="李四简历.pdf")

    lst = await client.get(
        "/api/v1/hr/resume-screening", params={"job_requirement_id": str(jd.id)},
    )
    assert lst.status_code == 200, lst.text
    rows = lst.json()["data"]
    assert [r["candidate_name"] for r in rows] == ["李四", "张三"]
    assert rows[0]["total_score"] >= rows[1]["total_score"]


async def test_screen_rejects_unreadable_pdf(db_session: AsyncSession, client: AsyncClient):
    """非 PDF / 提取不到文本的文件 → 400 引导，不落库不调 AI。"""
    jd = await _mk_jd(db_session)
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value=_FAKE_AI_RESULT),
    ) as mock_ai:
        res = await client.post(
            f"/api/v1/hr/resume-screening/{jd.id}",
            files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
        )
    assert res.status_code == 400, res.text
    mock_ai.assert_not_called()


async def test_screen_clamps_bad_ai_values(db_session: AsyncSession, client: AsyncClient):
    """AI 返回越界分值/异常推荐档位时归一：分数截到 0-100，档位回落待定。"""
    jd = await _mk_jd(db_session)
    weird = {
        **_FAKE_AI_RESULT,
        "total_score": 150,
        "score_table": [{"dimension": "专业匹配", "score": -20, "comment": "x"}],
        "recommendation": "无法判断",
        "advantages": "不是列表",  # 非法结构安全降级为空
    }
    res = await _screen(client, jd.id, _make_pdf(["resume content"]), weird)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["total_score"] == 100
    assert data["score_table"][0]["score"] == 0
    assert data["recommendation"] == "待定"
    assert data["advantages"] == []


async def test_convert_to_candidate(db_session: AsyncSession, client: AsyncClient):
    """转候选人：姓名/岗位/简历文件/最终结论带过去；筛选记录软删防重复转入。"""
    jd = await _mk_jd(db_session)
    created = await _screen(client, jd.id, _make_pdf(["John Smith QC"]), _FAKE_AI_RESULT)
    result_id = created.json()["data"]["id"]

    converted = await client.post(f"/api/v1/hr/resume-screening/{result_id}/convert")
    assert converted.status_code == 201, converted.text
    candidate = converted.json()["data"]
    assert candidate["name"] == "张三"
    assert candidate["status"] == "待筛选"
    assert candidate["resume_url"]
    notes = candidate["notes"] or ""
    assert "AI 简历筛选" in notes
    assert "婉拒" in notes  # 最终结论摘要带入备注

    # 转换后记录从列表消失；重复转 404
    lst = await client.get(
        "/api/v1/hr/resume-screening", params={"job_requirement_id": str(jd.id)},
    )
    assert result_id not in {r["id"] for r in lst.json()["data"]}
    again = await client.post(f"/api/v1/hr/resume-screening/{result_id}/convert")
    assert again.status_code == 404


async def test_screen_unknown_jd_404(client: AsyncClient):
    res = await client.post(
        f"/api/v1/hr/resume-screening/{uuid4()}",
        files={"file": ("简历.pdf", _make_pdf(["x"]), "application/pdf")},
    )
    assert res.status_code == 404
