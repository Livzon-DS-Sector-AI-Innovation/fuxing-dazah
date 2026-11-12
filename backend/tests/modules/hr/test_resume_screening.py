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

# 模拟 AI 输出：结构对齐《岗位适配度分析+复试推荐意见》范例 + AI 直聘筛选表扩展
_FAKE_AI_RESULT = {
    "candidate_name": "张三",
    "profile": {
        "education": "本科",
        "school": "福建医科大学",
        "major": "临床药学",
        "current_position": "临床药师",
        "current_company": "福州市第一医院",
        "expected_position": "QA 专员",
        "intended_city": "福州",
        "work_years": "5-8年",
        "employment_status": "在职",
        "skills": ["药品调剂", "用药指导", "GMP 基础"],
        "phone": "13800000000",
        "email": "zhangsan@example.com",
    },
    "core_evaluation": "具备医院药学服务经验，但无工业药企 QA 经历；需确认英语读写与 GMP 认知",
    "talent_category": "B类-潜力人才",
    "dimension_assessment": {
        "专业能力": [
            {"label": "技术栈", "text": "临床药学技能扎实，但 QC 检验技术栈缺失"},
            {"label": "项目经验", "text": "仅医院药房实习，无工业药企项目经验"},
        ],
        "基础匹配": [
            {"label": "学历背景", "text": "✅ 本科符合要求"},
            {"label": "专业背景", "text": "❌ 临床药学偏离原料药 QA"},
        ],
        "发展潜力": [
            {"label": "成长性", "text": "有持续学习意愿"},
            {"label": "稳定性", "text": "工作经历连贯，无空档"},
        ],
        "软实力": [
            {"label": "沟通协作", "text": "病房会诊经验，沟通顺畅"},
            {"label": "执行力", "text": "处方审核严谨细致"},
        ],
    },
    "advantages": [
        {"title": "专业门槛达标", "detail": "药学本科，掌握药品基础逻辑，满足 QA 最低专业门槛。"},
        {"title": "地域与薪资适配", "detail": "人在福州，通勤方便，薪资预期低。"},
    ],
    "flaws": [
        {"title": "英语硬性条件不达标", "detail": "无四级证书，无法独立阅读英文药典与申报文件。"},
        {"title": "无工业药企经验", "detail": "实习全部在医院药房，GMP 仅字面概念，培训成本高。"},
    ],
    "score_table": [
        {"group": "专业能力", "dimension": "专业匹配", "score": 30, "comment": "临床药学不匹配原料药工业 QA"},
        {"group": "基础匹配", "dimension": "语言能力", "score": 10, "comment": "无四级，依赖翻译软件"},
        {"group": "软实力", "dimension": "地域&薪资适配", "score": 85, "comment": "本地、预期低"},
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
    # AI 直聘表扩展：核心评价 / 人才分类 / 信息卡片 / 打分组 / 维度评估 / 报告全文
    assert data["core_evaluation"].startswith("具备医院药学服务经验")
    assert data["talent_category"] == "B"
    assert data["candidate_profile"]["school"] == "福建医科大学"
    assert data["candidate_profile"]["work_years"] == 5  # "5-8年" 取下限
    assert data["candidate_profile"]["skills"] == ["药品调剂", "用药指导", "GMP 基础"]
    assert data["dimension_assessment"]["专业能力"][0] == {
        "label": "技术栈", "text": "临床药学技能扎实，但 QC 检验技术栈缺失",
    }
    report = data["match_report"]
    assert report.startswith("【候选人匹配度报告】应聘岗位：")
    assert "👤 姓名：张三" in report
    assert "🎓 学历：本科 | 福建医科大学 | 临床药学" in report
    assert "📋 推荐等级：不推荐" in report
    assert "💬 核心评价：" in report
    assert "- 技术栈：临床药学技能扎实" in report
    assert "综合胜任度：42/100" in report
    assert [a["title"] for a in data["advantages"]] == ["专业门槛达标", "地域与薪资适配"]
    assert "英语" in data["flaws"][0]["title"]
    assert data["score_table"][0]["group"] == "专业能力"
    assert data["score_table"][0]["dimension"] == "专业匹配"
    assert data["score_table"][0]["score"] == 30
    assert data["final_reasons"] == ["英语硬性条件不满足", "岗位认知偏差大，入职后易离职"]
    assert "要求：药学相关专业" in data["jd_snapshot"]

    # 第二份高分简历 → 排名在其前（强烈推荐档位同时候选人侧 recommendation_level 对齐）
    high = {
        **_FAKE_AI_RESULT, "candidate_name": "李四", "total_score": 81,
        "recommendation": "强烈推荐", "talent_category": "A类-关键人才",
    }
    await _screen(client, jd.id, pdf, high, filename="李四简历.pdf")

    lst = await client.get(
        "/api/v1/hr/resume-screening", params={"job_requirement_id": str(jd.id)},
    )
    assert lst.status_code == 200, lst.text
    rows = lst.json()["data"]
    assert [r["candidate_name"] for r in rows] == ["李四", "张三"]
    assert rows[0]["total_score"] >= rows[1]["total_score"]
    assert rows[0]["recommendation"] == "强烈推荐"
    assert rows[0]["talent_category"] == "A"


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
    """AI 返回越界分值/异常档位/非法分组时归一：分数截到 0-100，档位回落待定，组外置空。"""
    jd = await _mk_jd(db_session)
    weird = {
        **_FAKE_AI_RESULT,
        "total_score": 150,
        "score_table": [{"group": "综合评估", "dimension": "专业匹配", "score": -20, "comment": "x"}],
        "recommendation": "非常强烈推荐",  # 含「强烈推荐」子串 → 归一强烈推荐（先于「推荐」）
        "talent_category": "核心人才",  # 无法识别 → None，不强行兜底
        "profile": {"work_years": "应届", "school": "某大学"},  # 年限无数字 → 不写入
        "dimension_assessment": {"综合评估": [{"label": "x", "text": "y"}]},  # 组名不在白名单 → 丢弃
        "advantages": "不是列表",  # 非法结构安全降级为空
    }
    res = await _screen(client, jd.id, _make_pdf(["resume content"]), weird)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["total_score"] == 100
    assert data["score_table"][0]["score"] == 0
    assert data["score_table"][0]["group"] is None
    assert data["recommendation"] == "强烈推荐"
    assert data["talent_category"] is None
    assert data["candidate_profile"] == {"school": "某大学"}  # work_years 未写入
    assert data["dimension_assessment"] == {}
    # 维度评估缺失时报告仍成文：有概览与结论、无「三、能力维度评估」
    assert "📋 推荐等级：强烈推荐" in data["match_report"]
    assert "三、能力维度评估" not in data["match_report"]
    assert "综合胜任度：100/100" in data["match_report"]
    assert data["advantages"] == []

    # 完全无法识别的档位文本 → 回落「待定」
    fallback = await _screen(client, jd.id, _make_pdf(["another"]), {**_FAKE_AI_RESULT, "recommendation": "无法判断"})
    assert fallback.json()["data"]["recommendation"] == "待定"


async def test_screen_candidate(db_session: AsyncSession, client: AsyncClient):
    """岗位侧候选人存量简历直接初筛：免重复上传，结果回链候选人并回写推荐等级/匹配报告。"""
    import uuid as _uuid

    jd = await _mk_jd(db_session)
    # 造一份已建档候选人：简历落本地 uploads/resumes（与本地开发存储规则一致）
    import os

    os.makedirs("uploads/resumes", exist_ok=True)
    resume_path = f"uploads/resumes/{_uuid.uuid4().hex[:8]}_王五简历.pdf"
    with open(resume_path, "wb") as f:
        f.write(_make_pdf(["Wang Wu - QC Engineer, 6 years API plant experience."]))

    from app.modules.hr.schemas import CandidateCreate
    from app.modules.hr.service import CandidateService

    candidate = await CandidateService(db_session).create(CandidateCreate(
        name="王五", job_requirement_id=jd.id, resume_url=resume_path, status="待筛选",
    ))

    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value=_FAKE_AI_RESULT),
    ):
        res = await client.post(f"/api/v1/hr/resume-screening/candidate/{candidate.id}")
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["candidate_id"] == str(candidate.id)
    assert data["job_requirement_id"] == str(jd.id)

    # 回写候选人档案：推荐等级 + 匹配报告全文
    refreshed = await CandidateService(db_session).get(candidate.id)
    assert refreshed.recommendation_level == "不推荐"
    assert refreshed.match_report and refreshed.match_report.startswith("【候选人匹配度报告】")

    # 结果出现在该岗位的筛选列表里（与上传初筛同一池，可排名对比）
    lst = await client.get(
        "/api/v1/hr/resume-screening", params={"job_requirement_id": str(jd.id)},
    )
    assert data["id"] in {r["id"] for r in lst.json()["data"]}


async def test_screen_candidate_validations(db_session: AsyncSession, client: AsyncClient):
    """无简历 / 未关联岗位 → 400 可读引导；候选人不存在 → 404。"""
    from app.modules.hr.schemas import CandidateCreate
    from app.modules.hr.service import CandidateService

    no_resume = await CandidateService(db_session).create(CandidateCreate(name="赵六"))
    res = await client.post(f"/api/v1/hr/resume-screening/candidate/{no_resume.id}")
    assert res.status_code == 400
    assert "简历" in res.json()["message"]

    jd = await _mk_jd(db_session)
    no_jd = await CandidateService(db_session).create(CandidateCreate(name="钱七", resume_url="uploads/resumes/x.pdf"))
    res = await client.post(f"/api/v1/hr/resume-screening/candidate/{no_jd.id}")
    assert res.status_code == 400
    assert "岗位" in res.json()["message"]

    missing = await client.post(f"/api/v1/hr/resume-screening/candidate/{uuid4()}")
    assert missing.status_code == 404


async def test_convert_to_candidate(db_session: AsyncSession, client: AsyncClient):
    """转候选人：档案/推荐等级/核心评价回填；筛选记录软删防重复转入。"""
    jd = await _mk_jd(db_session)
    created = await _screen(client, jd.id, _make_pdf(["John Smith QC"]), _FAKE_AI_RESULT)
    result_id = created.json()["data"]["id"]

    converted = await client.post(f"/api/v1/hr/resume-screening/{result_id}/convert")
    assert converted.status_code == 201, converted.text
    candidate = converted.json()["data"]
    assert candidate["name"] == "张三"
    assert candidate["status"] == "待筛选"
    assert candidate["resume_url"]
    # AI 解析档案回填候选人表
    assert candidate["school"] == "福建医科大学"
    assert candidate["education"] == "本科"
    assert candidate["major"] == "临床药学"
    assert candidate["work_years"] == 5
    assert candidate["phone"] == "13800000000"
    assert candidate["recommendation_level"] == "不推荐"
    # 匹配度报告全文随候选人流转（候选人详情 match_report 可直接看）
    assert candidate["match_report"].startswith("【候选人匹配度报告】应聘岗位：")
    assert "💬 核心评价：" in candidate["match_report"]
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
