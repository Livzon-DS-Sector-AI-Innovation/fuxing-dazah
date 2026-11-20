"""面试官评分卡（机器人私发表单卡 → 面试官提交 → 回写人工面试评价 + 通知 HR）。

复用 probation_service 验证过的模式：平台 send_user_card /
register_card_action_handler；卡片 value 服务端下发不可篡改，
hr_name 随卡携带用于回调后反查 open_id 通知发起人。

与候选人详情的 HR 代填评价（InterviewFeedbackService.upsert）共用同一张
interview_feedbacks 表：面试官本人提交覆盖 HR 代填（以最新提交为准）。
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import Candidate, CandidateAnalysisReport, Interview
from app.modules.hr.schemas import InterviewFeedbackDimension, InterviewFeedbackIn
from app.modules.hr.service import InterviewFeedbackService

logger = logging.getLogger(__name__)

CARD_ACTION = "interview_score_submit"

# 与前端 FEEDBACK_DIMENSIONS 对齐（name→卡片表单字段名）
_DIMENSION_FIELDS: list[tuple[str, str]] = [
    ("专业能力", "score_professional"),
    ("沟通表达", "score_communication"),
    ("岗位匹配", "score_match"),
    ("发展潜力", "score_potential"),
]

_RESULTS = ("通过", "待定", "不通过")


def _label(text: str) -> dict:
    return {"tag": "plain_text", "content": text}


def _fmt_interview_brief(interview: Interview, candidate: Candidate | None) -> str:
    date_text = interview.interview_date.strftime("%Y-%m-%d") if interview.interview_date else "时间待定"
    time_text = ""
    if interview.start_time:
        time_text = f" {interview.start_time.strftime('%H:%M')}"
        if interview.end_time:
            time_text += f"-{interview.end_time.strftime('%H:%M')}"
    name = candidate.name if candidate else "候选人"
    position = candidate.position if candidate else ""
    return f"**{name}**（{position}）· {interview.interview_type} · {date_text}{time_text}"


def _build_score_card(
    interview: Interview, candidate: Candidate | None,
    report: CandidateAnalysisReport | None, interviewer_name: str, hr_name: str,
) -> dict:
    """构造面试官评分表单卡（四维打分 + 结论 + 总评，input 模式与转正评估卡一致）。

    hr_name 随提交按钮 value 下发（服务端注入不可篡改），回调后反查 open_id 通知发起 HR。
    """
    brief = _fmt_interview_brief(interview, candidate)
    ai_text = ""
    if report is not None and report.total_score is not None:
        ai_text = f"\nAI 胜任度初评：**{report.total_score:.0f} 分**（{report.recommend_level or '未定级'}），供参考。"
    form_elements = [
        {
            "tag": "input", "name": field, "label": _label(f"{label}（1-5 分，选填）"),
            "required": False, "placeholder": _label("填 1-5 整数分"), "max_length": 2,
        }
        for label, field in _DIMENSION_FIELDS
    ]
    form_elements += [
        {
            "tag": "input", "name": "result", "label": _label("面试结论 *"),
            "required": True, "placeholder": _label("填：通过 / 待定 / 不通过"), "max_length": 8,
        },
        {
            # 飞书卡片 2.0 不支持 textarea（ErrCode 200621 整卡拒），统一 input
            "tag": "input", "name": "comment", "label": _label("总体评价（选填）"),
            "required": False, "max_length": 300,
        },
        {
            "tag": "button", "action_type": "form_submit", "name": "submit",
            "text": {"tag": "lark_md", "content": "**提交评分**"}, "type": "primary",
            "value": {"action": CARD_ACTION, "interview_id": str(interview.id), "hr_name": hr_name},
        },
    ]
    return {
        "schema": "2.0",
        "header": {"title": _label("面试官评分"), "template": "blue"},
        "body": {"elements": [
            {"tag": "markdown", "content": (
                f"{brief}\n"
                f"面试官：{interviewer_name}，请在面试结束后提交评分，结果将同步人事。{ai_text}"
            )},
            {"tag": "form", "name": "interview_score_form", "elements": form_elements},
        ]},
    }


def _build_hr_notice(
    interview: Interview, candidate: Candidate | None, interviewer_name: str,
    result: str, dims: list[dict], comment: str | None,
) -> dict:
    """面试官提交后通知发起 HR 的结果卡。"""
    brief = _fmt_interview_brief(interview, candidate)
    emoji = "✅" if result == "通过" else "❌" if result == "不通过" else "🤔"
    dim_text = " ｜ ".join(f"{d['name']} {d['score']}分" for d in dims if d.get("score"))
    md = f"{brief}\n\n面试官 **{interviewer_name}** 提交评分：{emoji} **{result}**"
    if dim_text:
        md += f"\n\n{dim_text}"
    if comment:
        md += f"\n\n总体评价：{comment}"
    return {
        "schema": "2.0",
        "header": {"title": _label("面试评分已提交"), "template": "green" if result == "通过" else "orange"},
        "body": {"elements": [{"tag": "markdown", "content": md}]},
    }


async def _send_card(open_id: str, card: dict) -> bool:
    from app.platform.integrations.feishu.notification import send_user_card

    try:
        return await send_user_card(open_id, card=card)
    except Exception as e:  # noqa: BLE001
        logger.warning("发送面试评分卡片失败 open_id=%s: %s", open_id, e)
        return False


async def _resolve_open_id_by_name(name: str) -> str | None:
    from app.modules.hr.feishu_review_service import _lookup_open_id

    return await _lookup_open_id(name)


# ═══════════════════════════════════════════════════════════════
# HR 发起推送评分卡
# ═══════════════════════════════════════════════════════════════

async def push_score_card(
    session: AsyncSession, interview_id: UUID,
    operator_name: str, operator: UUID | None,
) -> Interview:
    """把评分表单卡私发给面试官本人；推送记录写面试行（重复推送覆盖）。"""
    interview = (await session.execute(
        select(Interview).where(Interview.id == interview_id, Interview.is_deleted.is_(False))
    )).scalar_one_or_none()
    if interview is None:
        raise ValueError("面试记录不存在")
    if not (interview.interviewer or "").strip():
        raise ValueError("该面试未指定面试官，请先在「编辑」中填写面试官")
    if interview.status == "已取消":
        raise ValueError("该面试已取消，无需推送评分")

    interviewer_name = interview.interviewer.strip()
    open_id = await _resolve_open_id_by_name(interviewer_name)
    if not open_id:
        raise ValueError(f"未找到面试官「{interviewer_name}」的飞书账号（需其登录过系统或在源表有员工账号）")

    candidate = (await session.execute(
        select(Candidate).where(Candidate.id == interview.candidate_id)
    )).scalar_one_or_none()
    report = (await session.execute(
        select(CandidateAnalysisReport)
        .where(CandidateAnalysisReport.interview_id == interview_id,
               CandidateAnalysisReport.is_deleted.is_(False))
    )).scalar_one_or_none()

    card = _build_score_card(interview, candidate, report, interviewer_name, operator_name)
    if not await _send_card(open_id, card):
        raise ValueError("评分卡片发送失败（网络或机器人权限），请稍后重试")

    interview.score_push_open_id = open_id
    interview.score_pushed_at = datetime.now(timezone.utc)
    interview.updated_by = operator
    await session.commit()
    return interview


# ═══════════════════════════════════════════════════════════════
# 面试官提交回调（平台注册制）
# ═══════════════════════════════════════════════════════════════

async def handle_score_submit(payload: dict[str, Any], user_id: str) -> dict | None:
    """面试官提交评分：防代填 + 分值校验 → upsert 人工评价 → 通知发起 HR。"""
    from app.core.database import async_session_factory

    def toast(kind: str, content: str) -> dict:
        return {"toast": {"type": kind, "content": content}}

    form_value = payload.get("_form_value") or {}
    open_id = payload.get("_open_id") or ""
    interview_id = payload.get("interview_id") or ""
    if not interview_id:
        return toast("error", "卡片数据缺失，请联系人事重新发起")

    async with async_session_factory() as session:
        interview = (await session.execute(
            select(Interview).where(Interview.id == UUID(interview_id), Interview.is_deleted.is_(False))
        )).scalar_one_or_none()
        if interview is None or interview.status == "已取消":
            return toast("error", "该面试不存在或已取消")
        if not interview.score_push_open_id:
            return toast("error", "该面试未推送过评分卡，请联系人事")
        if open_id and open_id != interview.score_push_open_id:
            return toast("error", "请使用收到评分卡片的飞书账号提交")

        result = str(form_value.get("result") or "").strip()
        if result not in _RESULTS:
            return toast("error", "面试结论需为：通过 / 待定 / 不通过")

        dimensions = []
        for label, field in _DIMENSION_FIELDS:
            raw = str(form_value.get(field) or "").strip()
            if not raw:
                continue
            if not raw.isdigit() or not (1 <= int(raw) <= 5):
                return toast("error", f"{label}分需为 1-5 的整数")
            dimensions.append(InterviewFeedbackDimension(name=label, score=int(raw)))

        comment = str(form_value.get("comment") or "").strip() or None
        await InterviewFeedbackService(session).upsert(
            interview_id,
            InterviewFeedbackIn(
                evaluator=interview.interviewer or "面试官",
                dimensions=dimensions,
                overall_comment=comment,
                result=result,
            ),
        )
        await session.commit()

        # 通知发起 HR（hr_name 随卡片 value 下发）
        hr_name = str(payload.get("hr_name") or "").strip()
        if hr_name:
            hr_open_id = await _resolve_open_id_by_name(hr_name)
            if hr_open_id:
                candidate = (await session.execute(
                    select(Candidate).where(Candidate.id == interview.candidate_id)
                )).scalar_one_or_none()
                await _send_card(hr_open_id, _build_hr_notice(
                    interview, candidate, interview.interviewer or "面试官",
                    result, [d.model_dump() for d in dimensions], comment,
                ))

    return toast("success", "评分已提交，已同步人事")


def register_feishu_callbacks() -> None:
    from app.platform.integrations.feishu.event_handler import register_card_action_handler

    register_card_action_handler(CARD_ACTION, handle_score_submit)
