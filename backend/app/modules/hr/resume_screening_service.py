"""AI 简历筛选：按岗位要求对 PDF 简历全文打分排名，辅助初筛。

输出结构对齐培训管理的《岗位适配度分析+复试推荐意见》范例：
优势分析 / 核心硬伤（分节论述，客观犀利、基于简历证据）+
按岗位定制的胜任度打分表 + 最终推荐意见（结论 + 支撑理由）。
并按 HR 飞书 AI 直聘筛选表补充：候选人信息卡片（结构化解析）、
核心评价一句话、四维分组打分（专业能力/基础匹配/发展潜力/软实力）、人才分类。
"""

import logging
import re
from io import BytesIO
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import Candidate, JobRequirement, ResumeScreeningResult
from app.modules.hr.service import CandidateService, NotFoundException

logger = logging.getLogger(__name__)

# 简历全文交给 LLM 的长度上限（字符）：控制 token 成本与响应时长
_RESUME_TEXT_LIMIT = 12_000
_PDF_PAGE_LIMIT = 15
_FILE_SIZE_LIMIT = 10 * 1024 * 1024

_RECOMMENDATION_TIERS = ("强烈推荐", "推荐", "待定", "不推荐")
_TALENT_CATEGORIES = ("A", "B", "C")
_SCORE_GROUPS = ("专业能力", "基础匹配", "发展潜力", "软实力")

_SCREENING_SYSTEM_PROMPT = """你是一位要求严格的原料药（API）制药企业招聘官，做简历初筛时以业务负责人的标准做判断：
- 只依据简历原文内容评估，简历没写的不臆测、不给假设性加分；
- 客观犀利、直给结论，不说客套话和"综合来看有一定潜力"式废话；
- 优势写真实有分量的（数量不限，没有就少写）；硬伤直接点透、说清对岗位的具体影响；
- 打分维度分组固定为四组：专业能力（技术栈/项目经验）、基础匹配（学历/专业等硬门槛）、\
发展潜力（成长性/稳定性）、软实力（沟通协作/执行力），组内子维度按岗位实际要求定制（如英语、地域、薪资期望等），不套固定模板；
- 打分稳定性是硬性要求：同一份简历+同一岗位需求重复评估，必须输出相同的分数与档位。\
打分只做「简历事实 ↔ 岗位要求」逐条对照，不做主观浮动；证据不足时给保守分，不凭感觉抬分；
- 打分锚点（各维度分与总分都必须落在对应区间）：90+ 全面超出岗位要求且经验强相关；\
80-89 匹配良好仅有小瑕疵；70-79 基本匹配但有明显短板；60-69 勉强达标需较多培养；<60 不达标或关键硬伤；
- 总分与打分表自洽：total_score ≈ score_table 各项得分的算术平均（四舍五入）；\
仅当存在一票否决硬伤（岗位明确要求的学历/资质/英语等硬门槛不达标）时，总分显著低于平均分并在硬伤中说明；
- recommendation 档位由总分区间唯一决定：≥85 强烈推荐；75-84 推荐；60-74 待定；\
<60 或存在一票否决硬伤 不推荐。"""

_SCREENING_PROMPT_TEMPLATE = """## 岗位需求
岗位名称：{position_name}
部门：{department}
岗位要求：
{requirements}
{duties_section}
## 候选人简历全文
{resume_text}

请输出该候选人的「岗位适配度分析+复试推荐意见」，严格按以下 JSON 结构（分数均为 0-100 整数）：
{{
  "candidate_name": "从简历识别的姓名（识别不出为空字符串）",
  "profile": {{
    "education": "最高学历（如 本科/硕士/大专）",
    "school": "最高学历学校",
    "major": "专业",
    "current_position": "当前职位",
    "current_company": "当前公司",
    "expected_position": "期望职位",
    "intended_city": "意向城市",
    "work_years": "总工作年限（数字，如 5；范围取下限）",
    "age": "年龄（数字或区间文本）",
    "gender": "性别",
    "employment_status": "在职状态（在职/离职/应届）",
    "skills": ["核心技能，3-8 项"],
    "phone": "手机号（简历未写为空字符串）",
    "email": "邮箱（简历未写为空字符串）"
  }},
  "core_evaluation": "核心评价一句话：突出优势+主要顾虑+需面试确认的点，格式如「具备…经验，但…；需确认…」",
  "talent_category": "人才分类：A-关键人才（硬性条件全达标且经验强相关）/ B-潜力人才（大部分达标，个别短板可培养）/ C-普通简历",
  "dimension_assessment": {{
    "专业能力": [
      {{"label": "技术栈", "text": "一句话论述其技术/专业能力与岗位的匹配情况"}},
      {{"label": "项目经验", "text": "一句话论述相关项目/行业经验分量"}}
    ],
    "基础匹配": [
      {{"label": "学历背景", "text": "以 ✅/⚠️/❌ 开头+一句话（是否满足学历要求）"}},
      {{"label": "专业背景", "text": "以 ✅/⚠️/❌ 开头+一句话（专业相关度）"}}
    ],
    "发展潜力": [
      {{"label": "成长性", "text": "一句话（学习轨迹/晋升轨迹）"}},
      {{"label": "稳定性", "text": "一句话（跳槽频率/职业连贯性/空档）"}}
    ],
    "软实力": [
      {{"label": "沟通协作", "text": "一句话（跨部门/团队协作证据）"}},
      {{"label": "执行力", "text": "一句话（交付/落地证据）"}}
    ]
  }},
  "advantages": [
    {{"title": "优势小节标题（一句话概括，如：基础专业门槛达标）", "detail": "该优势的具体论述，2-4 句，引用简历中的事实支撑"}}
  ],
  "flaws": [
    {{"title": "硬伤/短板小节标题（一句话点透，如：英语硬性条件不达标）", "detail": "该硬伤的具体论述，说清对岗位工作的实际影响"}}
  ],
  "score_table": [
    {{"group": "专业能力/基础匹配/发展潜力/软实力 四组之一，四组都必须出现", "dimension": "组内打分子维度（按岗位定制，如 技术栈匹配/项目经验相关性/学历门槛/地域薪资适配）", "score": 0, "comment": "一句话评分依据"}}
  ],
  "total_score": "综合胜任度总分 0-100（与打分表匹配，硬性条件缺失要显著拉低总分）",
  "recommendation": "强烈推荐 / 推荐 / 待定 / 不推荐（对应该候选人是否值得推进面试）",
  "final_verdict": "最终推荐意见结论，一句话，直接明确（如：建议邀约复试 / 不建议推进，直接婉拒）",
  "final_reasons": ["支撑最终结论的核心理由，2-4 条，每条一句话，按重要性排序"]
}}"""


def extract_pdf_full_text(file_bytes: bytes) -> str:
    """提取 PDF 全文（页数与长度有上限）。空文本/畸形文件抛 ValueError。"""
    import pdfplumber

    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            pages = pdf.pages[:_PDF_PAGE_LIMIT]
            text = "\n".join((page.extract_text() or "") for page in pages)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 — pdfplumber 异常类型不稳定，统一转业务错误
        raise ValueError(f"无法读取 PDF 文件：{exc}") from exc
    text = text.strip()
    if not text:
        raise ValueError(
            "未能从 PDF 中提取到文本（可能是扫描件/图片型 PDF，请改用文字版简历）",
        )
    return text


def build_screening_prompt(jd: JobRequirement, resume_text: str) -> str:
    duties_section = f"岗位职责：\n{jd.duties}\n" if jd.duties else ""
    return _SCREENING_PROMPT_TEMPLATE.format(
        position_name=jd.position_name,
        department=jd.department,
        requirements=jd.requirements or "（未填写）",
        duties_section=duties_section,
        resume_text=resume_text[:_RESUME_TEXT_LIMIT],
    )


def _clamp_score(value: object) -> int:
    """AI 返回的分值归一到 0-100 整数（异常值按 0 处理）。"""
    try:
        return max(0, min(100, int(round(float(value)))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _normalize_recommendation(value: object) -> str:
    text = str(value or "").strip()
    if text in _RECOMMENDATION_TIERS:
        return text
    # 子串匹配顺序由包含关系决定：「不推荐」「强烈推荐」都含「推荐」，须先判
    for tier in ("不推荐", "强烈推荐", "推荐", "待定"):
        if tier in text:
            return tier
    return "待定"


def _normalize_talent_category(value: object) -> str | None:
    """归一人才分类到 A/B/C；无法识别时返回 None（不强行兜底）。"""
    text = str(value or "").strip().upper()
    for category in _TALENT_CATEGORIES:
        if text.startswith(category):
            return category
    return None


_PROFILE_TEXT_FIELDS = (
    "education", "school", "major", "current_position", "current_company",
    "expected_position", "intended_city", "age", "gender",
    "employment_status", "phone", "email",
)
_PROFILE_TEXT_LIMITS = {f: 128 for f in _PROFILE_TEXT_FIELDS}
_PROFILE_TEXT_LIMITS.update({"education": 16, "gender": 8})


def _parse_work_years(value: object) -> int | None:
    """从 "5年"/"3-5年"/"应届" 等文本取第一个数字作为年限下限。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _candidate_profile(value: object) -> dict | None:
    """归一 AI 输出的候选人信息卡片；无有效内容时返回 None。"""
    if not isinstance(value, dict):
        return None
    profile: dict[str, object] = {}
    for field in _PROFILE_TEXT_FIELDS:
        text = str(value.get(field) or "").strip()
        if text:
            profile[field] = text[:_PROFILE_TEXT_LIMITS[field]]
    work_years = _parse_work_years(value.get("work_years"))
    if work_years is not None:
        profile["work_years"] = work_years
    raw_skills = value.get("skills")
    if isinstance(raw_skills, list):
        skills = [str(s).strip()[:32] for s in raw_skills if str(s).strip()]
        if skills:
            profile["skills"] = skills[:8]
    return profile or None


# AI 初筛后允许回填修正的候选人档案字段（教育背景/工作背景，AI 提取可靠）
_PROFILE_BACKFILL_TEXT_FIELDS = ("education", "school", "major", "current_company")


def _backfill_profile_fields(candidate: Candidate, profile: dict) -> None:
    """用 AI 提取的 profile 回填/修正候选人档案字段（有值即覆盖，跳过同值免脏写）。"""
    for field in _PROFILE_BACKFILL_TEXT_FIELDS:
        v = profile.get(field)
        if isinstance(v, str) and v.strip() and v.strip() != getattr(candidate, field, None):
            setattr(candidate, field, v.strip())
    wy = profile.get("work_years")
    if isinstance(wy, int) and 0 <= wy <= 50 and wy != candidate.work_years:
        candidate.work_years = wy


def _dimension_assessment(value: object) -> dict[str, list[dict]]:
    """归一能力维度评估：{组: [{label, text}]}，只保留四组白名单、过滤空项。"""
    result: dict[str, list[dict]] = {}
    if not isinstance(value, dict):
        return result
    for group in _SCORE_GROUPS:
        items = value.get(group)
        if not isinstance(items, list):
            continue
        rows = [
            {"label": str(i.get("label") or "").strip()[:24], "text": str(i.get("text") or "").strip()[:200]}
            for i in items if isinstance(i, dict)
        ]
        rows = [r for r in rows if r["text"]]
        if rows:
            result[group] = rows
    return result


def _profile_lines(profile: dict | None, name: str | None) -> list[str]:
    """拼装信息卡片行（对齐 AI 直聘表：姓名/学历|学校|专业/当前职位/期望|城市/核心技能）。"""
    p = profile or {}
    lines: list[str] = []
    if name:
        lines.append(f"👤 姓名：{name}")
    edu = " | ".join(x for x in (p.get("education"), p.get("school"), p.get("major")) if x)
    if edu:
        lines.append(f"🎓 学历：{edu}")
    job = " · ".join(x for x in (p.get("current_position"), p.get("current_company")) if x)
    if job:
        lines.append(f"💼 当前职位：{job}")
    expect = " | ".join(x for x in (p.get("expected_position"), p.get("intended_city")) if x)
    if expect:
        lines.append(f"🔮 期望发展：{expect}")
    if p.get("skills"):
        lines.append(f"📝 核心技能：{'、'.join(p['skills'])}")
    seniority = " · ".join(x for x in (
        f"{p['work_years']} 年" if p.get("work_years") is not None else None,
        p.get("employment_status"),
    ) if x)
    if seniority:
        lines.append(f"⏳ 工作年限：{seniority}")
    return lines


def _build_match_report(
    *,
    jd: JobRequirement,
    candidate_name: str | None,
    profile: dict | None,
    recommendation: str,
    core_evaluation: str | None,
    dimension_assessment: dict[str, list[dict]],
    total_score: int,
    final_verdict: str | None,
) -> str:
    """把结构化筛选结果拼装成一份可直接转发的「候选人匹配度报告」全文。

    结构对齐 AI 直聘筛选表：信息卡片 → 匹配度评估概览 → 能力维度评估 → 综合结论；
    缺失的小节整体跳过，保证拼装结果始终成文。
    """
    sections: list[str] = [f"【候选人匹配度报告】应聘岗位：{jd.position_name}（{jd.department}）", ""]

    card = _profile_lines(profile, candidate_name)
    if card:
        sections += ["一、候选人信息卡片", *card, ""]

    overview: list[str] = [f"📋 推荐等级：{recommendation}"]
    if core_evaluation:
        overview.append(f"💬 核心评价：{core_evaluation}")
    sections += ["二、匹配度评估", *overview, ""]

    if dimension_assessment:
        sections.append("三、能力维度评估")
        for group in _SCORE_GROUPS:
            items = dimension_assessment.get(group) or []
            if not items:
                continue
            sections.append(f"【{group}】")
            sections += [f"- {item['label']}：{item['text']}" for item in items]
        sections.append("")

    sections += [
        "四、综合结论",
        f"综合胜任度：{total_score}/100",
        f"最终意见：{final_verdict or recommendation}",
    ]
    return "\n".join(sections)


def _section_list(value: object) -> list[dict]:
    """归一 AI 输出的小节列表：[{title, detail}]，过滤空项。"""
    result: list[dict] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if title or detail:
            result.append({"title": title, "detail": detail})
    return result


def _score_table(value: object) -> list[dict]:
    """归一打分表：[{group, dimension, score, comment}]，group 归一到四组白名单。"""
    result: list[dict] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension:
            continue
        group = str(item.get("group") or "").strip()
        result.append({
            "group": group if group in _SCORE_GROUPS else None,
            "dimension": dimension,
            "score": _clamp_score(item.get("score")),
            "comment": str(item.get("comment") or "").strip(),
        })
    return result


class ResumeScreeningService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _evaluate(
        self, *, jd: JobRequirement, file_name: str, file_bytes: bytes,
        operator: str | None = None, candidate_id: UUID | None = None,
    ) -> ResumeScreeningResult:
        """公共评估管线：PDF 全文 → AI 打分 → 落库（上传初筛与候选人直接初筛共用）。"""
        import os
        import uuid as _uuid

        if len(file_bytes) > _FILE_SIZE_LIMIT:
            raise ValueError("简历文件过大（上限 10MB）")
        resume_text = extract_pdf_full_text(file_bytes)

        from app.modules.hr.ai_service import AiChatService
        from app.modules.hr.config import HR_AI_MODEL

        prompt = build_screening_prompt(jd, resume_text)
        raw = await AiChatService.call_json(prompt, system_prompt=_SCREENING_SYSTEM_PROMPT)

        jd_snapshot = (
            f"{jd.position_name}（{jd.department}）\n要求：{jd.requirements or '（未填写）'}"
            + (f"\n职责：{jd.duties}" if jd.duties else "")
        )
        profile = _candidate_profile(raw.get("profile"))
        dimension_assessment = _dimension_assessment(raw.get("dimension_assessment"))
        core_evaluation = str(raw.get("core_evaluation") or "").strip()[:512] or None
        recommendation = _normalize_recommendation(raw.get("recommendation"))
        total_score = _clamp_score(raw.get("total_score"))
        final_verdict = str(raw.get("final_verdict") or "").strip() or None
        result = ResumeScreeningResult(
            job_requirement_id=jd.id,
            candidate_id=candidate_id,
            jd_snapshot=jd_snapshot,
            file_name=Path(file_name).name[:256] or "resume.pdf",
            candidate_name=(str(raw.get("candidate_name") or "").strip() or None),
            core_evaluation=core_evaluation,
            talent_category=_normalize_talent_category(raw.get("talent_category")),
            candidate_profile=profile,
            dimension_assessment=dimension_assessment,
            match_report=_build_match_report(
                jd=jd,
                candidate_name=(str(raw.get("candidate_name") or "").strip() or None),
                profile=profile,
                recommendation=recommendation,
                core_evaluation=core_evaluation,
                dimension_assessment=dimension_assessment,
                total_score=total_score,
                final_verdict=final_verdict,
            ),
            total_score=total_score,
            recommendation=recommendation,
            advantages=_section_list(raw.get("advantages")),
            flaws=_section_list(raw.get("flaws")),
            score_table=_score_table(raw.get("score_table")),
            final_verdict=final_verdict,
            final_reasons=[str(r) for r in raw.get("final_reasons") or [] if str(r).strip()],
            resume_excerpt=resume_text[:1500],
            model_version=HR_AI_MODEL,
            created_by_name=operator,
        )

        # 存 PDF 供「转为候选人」挂简历（与 parse-resume 同目录规则）
        safe_name = Path(file_name).name.replace("\\", "_").replace("/", "_") or "resume.pdf"
        if not safe_name or safe_name in (".", ".."):
            safe_name = "resume.pdf"
        from app.core.storage import is_enabled as storage_enabled
        from app.core.storage import upload_object

        object_key = f"resumes/{_uuid.uuid4().hex[:8]}_{safe_name}"
        if storage_enabled():
            upload_object("hr", object_key, file_bytes, len(file_bytes), "application/pdf")
            result.resume_file_path = f"minio://hr/{object_key}"
        else:
            os.makedirs("uploads/resumes", exist_ok=True)
            path = f"uploads/resumes/{_uuid.uuid4().hex[:8]}_{safe_name}"
            with open(path, "wb") as f:
                f.write(file_bytes)
            result.resume_file_path = path

        self.session.add(result)
        await self.session.flush()
        return result

    async def screen_resume(
        self, *, jd_id: UUID, file_name: str, file_bytes: bytes,
        operator: str | None = None,
    ) -> ResumeScreeningResult:
        """解析并 AI 评估一份上传的简历，落库返回结果（PDF 同时存储供转候选人）。"""
        jd = (await self.session.execute(
            select(JobRequirement).where(
                JobRequirement.id == jd_id, JobRequirement.is_deleted == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not jd:
            raise NotFoundException("岗位需求", str(jd_id))
        return await self._evaluate(
            jd=jd, file_name=file_name, file_bytes=file_bytes, operator=operator,
        )

    async def screen_candidate(
        self, candidate_id: UUID, *, operator: str | None = None,
    ) -> ResumeScreeningResult:
        """对已建档候选人的存量简历直接 AI 初筛（免重复上传）。

        读取候选人 resume_url 指向的 PDF（MinIO / 本地），按其关联岗位需求评估，
        结果回链候选人并回写推荐等级与匹配报告全文。
        """
        import os

        candidate = await CandidateService(self.session).get(candidate_id)
        if not candidate.resume_url:
            raise ValueError("该候选人没有简历文件，请先在详情页上传简历")
        if not candidate.job_requirement_id:
            raise ValueError("该候选人未关联岗位需求，无法确定筛选依据")

        # 读简历字节：与简历预览接口同一套规则（minio:// 或 uploads/resumes 白名单）
        resume_url = candidate.resume_url
        if resume_url.startswith("minio://"):
            from app.core.storage import get_object

            obj = get_object("hr", resume_url[len("minio://"):])
            if obj is None:
                raise ValueError("简历文件不存在（可能已被清理），请重新上传")
            file_bytes, _ = obj
        else:
            path = os.path.normpath(resume_url)
            if not path.startswith("uploads/resumes/") or not os.path.exists(path):
                raise ValueError("简历文件不存在（可能已被清理），请重新上传")
            with open(path, "rb") as f:
                file_bytes = f.read()

        jd = (await self.session.execute(
            select(JobRequirement).where(
                JobRequirement.id == candidate.job_requirement_id,
                JobRequirement.is_deleted == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not jd:
            raise NotFoundException("岗位需求", str(candidate.job_requirement_id))

        result = await self._evaluate(
            jd=jd,
            file_name=Path(resume_url).name or "resume.pdf",
            file_bytes=file_bytes,
            operator=operator,
            candidate_id=candidate_id,
        )
        # 初筛结论回写候选人：推荐等级 + 匹配报告全文（详情页与列表直接可见）
        candidate.recommendation_level = result.recommendation
        candidate.match_report = result.match_report
        # 档案字段回填修正：AI 结构化提取（candidate_profile）比上传建档时的
        # 规则解析更准（如校名介词污染），有值即覆盖——仅限档案核心信息字段，
        # 姓名/联系方式等身份字段不覆盖（AI 也可能抄错，保守不动）
        _backfill_profile_fields(candidate, result.candidate_profile or {})
        await self.session.flush()
        return result

    async def list_by_job_requirement(self, jd_id: UUID) -> list[ResumeScreeningResult]:
        """按岗位列出筛选结果，总分降序（排名）。"""
        rows = (await self.session.execute(
            select(ResumeScreeningResult).where(
                ResumeScreeningResult.job_requirement_id == jd_id,
                ResumeScreeningResult.is_deleted == False,  # noqa: E712
            ).order_by(
                ResumeScreeningResult.total_score.desc(),
                ResumeScreeningResult.created_at.desc(),
            )
        )).scalars().all()
        return list(rows)

    async def list_ranking(
        self, jd_id: UUID | None = None,
    ) -> list[tuple[ResumeScreeningResult, JobRequirement | None]]:
        """筛选结果排名总览：jd_id 为空时跨岗位全量，总分降序。

        返回 (结果, 所属岗位) 对——岗位可能已被删除/软删，删除后回 None，
        前端用 jd_snapshot 兜底展示。上传入口已迁移到岗位侧，本页只读。
        """
        stmt = select(ResumeScreeningResult).where(
            ResumeScreeningResult.is_deleted == False,  # noqa: E712
        ).order_by(
            ResumeScreeningResult.total_score.desc(),
            ResumeScreeningResult.created_at.desc(),
        )
        if jd_id is not None:
            stmt = stmt.where(ResumeScreeningResult.job_requirement_id == jd_id)
        rows = list((await self.session.execute(stmt)).scalars().all())
        jd_map: dict[UUID, JobRequirement] = {}
        if rows:
            jd_ids = {r.job_requirement_id for r in rows}
            for j in (await self.session.execute(
                select(JobRequirement).where(JobRequirement.id.in_(jd_ids))
            )).scalars().all():
                jd_map[j.id] = j
        return [(r, jd_map.get(r.job_requirement_id)) for r in rows]

    async def get_resume_bytes(self, result_id: UUID) -> tuple[bytes, str]:
        """读取筛选结果存档的简历原文（排名总览页点击查看）。

        与候选人简历预览同一套读取规则：minio:// 或 uploads/resumes 白名单。
        """
        row = await self.get(result_id)
        path = row.resume_file_path
        if not path:
            raise ValueError("该筛选结果没有存档简历文件")
        if path.startswith("minio://"):
            from app.core.storage import get_object

            obj = get_object("hr", path[len("minio://"):])
            if obj is None:
                raise ValueError("简历文件不存在（可能已被清理）")
            data, _ct = obj
            return data, row.file_name or "resume.pdf"
        import os

        norm = os.path.normpath(path)
        if not norm.startswith("uploads/resumes/") or not os.path.exists(norm):
            raise ValueError("简历文件不存在（可能已被清理）")
        with open(norm, "rb") as f:
            return f.read(), row.file_name or "resume.pdf"

    async def delete(self, result_id: UUID) -> None:
        row = await self.get(result_id)
        row.is_deleted = True
        await self.session.flush()

    async def get(self, result_id: UUID) -> ResumeScreeningResult:
        row = (await self.session.execute(
            select(ResumeScreeningResult).where(
                ResumeScreeningResult.id == result_id,
                ResumeScreeningResult.is_deleted == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not row:
            raise NotFoundException("筛选结果", str(result_id))
        return row

    async def convert_to_candidate(self, result_id: UUID) -> Candidate:
        """把筛选结果转为候选人（进入待筛选流程，挂简历文件并回填解析档案）。"""
        from app.modules.hr.schemas import CandidateCreate
        from app.modules.hr.service import CandidateService

        row = await self.get(result_id)
        name = row.candidate_name or Path(row.file_name).stem or "未命名候选人"
        profile = row.candidate_profile or {}
        candidate = await CandidateService(self.session).create(
            CandidateCreate(
                name=name,
                job_requirement_id=row.job_requirement_id,
                resume_url=row.resume_file_path,
                # AI 解析出的档案信息回填候选人表（CandidateCreate 的可选字段）
                phone=profile.get("phone") or None,
                email=profile.get("email") or None,
                gender=profile.get("gender") or None,
                school=profile.get("school") or None,
                education=profile.get("education") or None,
                major=profile.get("major") or None,
                work_years=profile.get("work_years"),
                current_company=profile.get("current_company") or None,
                recommendation_level=row.recommendation,
                match_report=row.match_report or row.core_evaluation,
                notes=(
                    f"来自 AI 简历筛选（胜任度 {row.total_score}/100，{row.recommendation}）。"
                    f"结论：{row.final_verdict or row.recommendation}"
                ),
            ),
        )
        # 转换后软删筛选记录，避免列表里重复转入
        row.is_deleted = True
        await self.session.flush()
        return candidate
