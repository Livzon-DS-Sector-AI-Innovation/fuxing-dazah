"""AI 简历筛选：按岗位要求对 PDF 简历全文打分排名，辅助初筛。

输出结构对齐培训管理的《岗位适配度分析+复试推荐意见》范例：
优势分析 / 核心硬伤（分节论述，客观犀利、基于简历证据）+
按岗位定制的胜任度打分表 + 最终推荐意见（结论 + 支撑理由）。
"""

import logging
from io import BytesIO
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import Candidate, JobRequirement, ResumeScreeningResult
from app.modules.hr.service import NotFoundException

logger = logging.getLogger(__name__)

# 简历全文交给 LLM 的长度上限（字符）：控制 token 成本与响应时长
_RESUME_TEXT_LIMIT = 12_000
_PDF_PAGE_LIMIT = 15
_FILE_SIZE_LIMIT = 10 * 1024 * 1024

_RECOMMENDATION_TIERS = ("推荐", "待定", "不推荐")

_SCREENING_SYSTEM_PROMPT = """你是一位要求严格的原料药（API）制药企业招聘官，做简历初筛时以业务负责人的标准做判断：
- 只依据简历原文内容评估，简历没写的不臆测、不给假设性加分；
- 客观犀利、直给结论，不说客套话和"综合来看有一定潜力"式废话；
- 优势写真实有分量的（数量不限，没有就少写）；硬伤直接点透、说清对岗位的具体影响；
- 打分维度根据该岗位的实际要求定制（如英语、经验、地域、薪资期望等），不套固定模板。"""

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
  "advantages": [
    {{"title": "优势小节标题（一句话概括，如：基础专业门槛达标）", "detail": "该优势的具体论述，2-4 句，引用简历中的事实支撑"}}
  ],
  "flaws": [
    {{"title": "硬伤/短板小节标题（一句话点透，如：英语硬性条件不达标）", "detail": "该硬伤的具体论述，说清对岗位工作的实际影响"}}
  ],
  "score_table": [
    {{"dimension": "打分维度（按岗位定制，4-6 个，如 专业匹配/岗位认知/语言能力/经验相关/软实力/地域薪资适配）", "score": 0, "comment": "一句话评分依据"}}
  ],
  "total_score": "综合胜任度总分 0-100（与打分表匹配，硬性条件缺失要显著拉低总分）",
  "recommendation": "推荐 / 待定 / 不推荐（对应该候选人是否值得推进面试）",
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
    # 包含匹配时「不推荐」必须先于「推荐」（后者是前者子串）
    for tier in ("不推荐", "待定", "推荐"):
        if tier in text:
            return tier
    return "待定"


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
    """归一打分表：[{dimension, score, comment}]。"""
    result: list[dict] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension:
            continue
        result.append({
            "dimension": dimension,
            "score": _clamp_score(item.get("score")),
            "comment": str(item.get("comment") or "").strip(),
        })
    return result


class ResumeScreeningService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def screen_resume(
        self, *, jd_id: UUID, file_name: str, file_bytes: bytes,
        operator: str | None = None,
    ) -> ResumeScreeningResult:
        """解析并 AI 评估一份简历，落库返回结果（PDF 同时存储供转候选人）。"""
        import uuid as _uuid

        jd = (await self.session.execute(
            select(JobRequirement).where(
                JobRequirement.id == jd_id, JobRequirement.is_deleted == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not jd:
            raise NotFoundException("岗位需求", str(jd_id))

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
        result = ResumeScreeningResult(
            job_requirement_id=jd_id,
            jd_snapshot=jd_snapshot,
            file_name=Path(file_name).name[:256] or "resume.pdf",
            candidate_name=(str(raw.get("candidate_name") or "").strip() or None),
            total_score=_clamp_score(raw.get("total_score")),
            recommendation=_normalize_recommendation(raw.get("recommendation")),
            advantages=_section_list(raw.get("advantages")),
            flaws=_section_list(raw.get("flaws")),
            score_table=_score_table(raw.get("score_table")),
            final_verdict=str(raw.get("final_verdict") or "").strip() or None,
            final_reasons=[str(r) for r in raw.get("final_reasons") or [] if str(r).strip()],
            resume_excerpt=resume_text[:1500],
            model_version=HR_AI_MODEL,
            created_by_name=operator,
        )

        # 存 PDF 供「转为候选人」挂简历（与 parse-resume 同目录规则）
        import os

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
        """把筛选结果转为候选人（进入待筛选流程，挂上简历文件）。"""
        from app.modules.hr.schemas import CandidateCreate
        from app.modules.hr.service import CandidateService

        row = await self.get(result_id)
        name = row.candidate_name or Path(row.file_name).stem or "未命名候选人"
        service = CandidateService(self.session)
        candidate = await service.create(
            CandidateCreate(
                name=name,
                job_requirement_id=row.job_requirement_id,
                resume_url=row.resume_file_path,
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
