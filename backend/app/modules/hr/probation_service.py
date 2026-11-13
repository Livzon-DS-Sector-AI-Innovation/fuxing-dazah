"""试用期转正评估（部门负责人飞书评 → HR 确认生效）。

流程：HR 发起（选部门负责人为评估人）→ 机器人私发评估表单卡片 →
负责人提交（WS 回调，防代填）→ HR 确认生效：写飞书源表「员工性质」=正式
（每日对账派生 status=在职，本地同值预更新，绕开同步只读），并通知评估人。
延长 = 写 probation_end_date 后重走一轮；不通过 = 不改状态，提示走离职。

复用 employee_info_collection_service 验证过的全部模式：
平台 send_user_card / register_card_action_handler / bitable.update_record
+ COLUMN_MAP 列名自适配 + _lookup_open_id 姓名→open_id。
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import Employee, ProbationReview

logger = logging.getLogger(__name__)

CARD_ACTION = "probation_review_submit"

_CONCLUSIONS = ("通过", "延长", "不通过")


def _label(text: str) -> dict:
    return {"tag": "plain_text", "content": text}


def _build_review_card(review: ProbationReview, employee: Employee) -> dict:
    """构造转正评估表单卡片（结论/评语/延长新日期 + 提交按钮）。"""
    end = employee.computed_probation_end
    end_text = end.strftime("%Y-%m-%d") if end else "未知"
    days = employee.computed_probation_days_left
    days_text = f"（已过期 {abs(days)} 天）" if days is not None and days < 0 else f"（剩 {days} 天）"
    return {
        "schema": "2.0",
        "header": {"title": _label("试用期转正评估"), "template": "blue"},
        "body": {"elements": [
            {"tag": "markdown", "content": (
                f"**{employee.name}**（{employee.department} · {employee.position}）\n"
                f"入职日期：{employee.hire_date} ｜ 转正到期：**{end_text}**{days_text}\n\n"
                f"请作为部门负责人给出转正评估结论（评估人：{review.reviewer_name}）。"
            )},
            {"tag": "form", "name": "probation_review_form", "elements": [
                {
                    "tag": "input", "name": "conclusion", "label": _label("评估结论 *"),
                    "required": True,
                    "placeholder": _label("填：通过 / 延长 / 不通过"),
                    "max_length": 8,
                },
                {
                    "tag": "textarea", "name": "comment", "label": _label("评语（工作表现/出勤/协作等）"),
                    "required": True, "max_length": 300,
                },
                {
                    "tag": "input", "name": "proposed_probation_end", "label": _label("新转正到期日（仅结论=延长时填）"),
                    "required": False,
                    "placeholder": _label("格式 2027-03-15"),
                    "max_length": 32,
                },
                {
                    "tag": "button", "action_type": "form_submit", "name": "submit",
                    "text": {"tag": "lark_md", "content": "**提交评估**"}, "type": "primary",
                    "value": {"action": CARD_ACTION, "review_id": str(review.id)},
                },
            ]},
        ]},
    }


def _build_result_notice(review: ProbationReview, employee: Employee, *, extended_to: date | None) -> dict:
    """生效后通知评估人的结果卡片。"""
    if review.conclusion == "通过":
        body = f"**{employee.name}** 已转正生效（员工性质→正式）。感谢你的评估。"
    elif review.conclusion == "延长":
        body = f"**{employee.name}** 试用期延长至 {extended_to}，届时将重新发起评估。"
    else:
        body = f"**{employee.name}** 的转正评估结论为「不通过」，已移交人事处理。"
    return {
        "schema": "2.0",
        "header": {"title": _label("转正评估已确认"), "template": "green"},
        "body": {"elements": [{"tag": "markdown", "content": body}]},
    }


async def _send_card(open_id: str, card: dict) -> bool:
    from app.platform.integrations.feishu.notification import send_user_card

    try:
        return await send_user_card(open_id, card=card)
    except Exception as e:  # noqa: BLE001
        logger.warning("发送转正评估卡片失败 open_id=%s: %s", open_id, e)
        return False


# ═══════════════════════════════════════════════════════════════
# 发起评估
# ═══════════════════════════════════════════════════════════════

async def _resolve_open_id_by_name(name: str) -> str | None:
    from app.modules.hr.feishu_review_service import _lookup_open_id

    return await _lookup_open_id(name)


async def create_review(
    session: AsyncSession, employee_id: UUID, reviewer_name: str, operator: str,
) -> ProbationReview:
    """发起转正评估：校验试用期状态 → 解析评估人 open_id → 私发评估卡。"""
    employee = (await session.execute(
        select(Employee).where(Employee.id == employee_id, Employee.is_deleted.is_(False))
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工不存在")
    if employee.status != "试用期":
        raise ValueError(f"{employee.name} 当前状态为「{employee.status}」，仅试用期员工可发起转正评估")
    active = (await session.execute(
        select(ProbationReview).where(
            ProbationReview.employee_id == employee_id,
            ProbationReview.status.in_(("pending_reviewer", "pending_hr")),
            ProbationReview.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if active is not None:
        raise ValueError(f"{employee.name} 已有进行中的转正评估")

    reviewer_name = reviewer_name.strip()
    open_id = await _resolve_open_id_by_name(reviewer_name)
    if not open_id:
        raise ValueError(f"未找到评估人「{reviewer_name}」的飞书账号（需其登录过系统或在源表有员工账号）")

    review = ProbationReview(
        id=uuid.uuid4(), employee_id=employee_id,
        reviewer_name=reviewer_name, reviewer_open_id=open_id,
    )
    if not await _send_card(open_id, _build_review_card(review, employee)):
        raise ValueError("评估卡片发送失败（网络或机器人权限），请稍后重试")
    session.add(review)
    await session.commit()
    return review


# ═══════════════════════════════════════════════════════════════
# 评估卡片提交回调（平台注册制）
# ═══════════════════════════════════════════════════════════════

async def handle_review_submit(payload: dict[str, Any], user_id: str) -> dict | None:
    """负责人提交评估：防代填 + 结论校验 → 待 HR 确认。"""
    from app.core.database import async_session_factory

    def toast(kind: str, content: str) -> dict:
        return {"toast": {"type": kind, "content": content}}

    form_value = payload.get("_form_value") or {}
    open_id = payload.get("_open_id") or ""
    review_id = payload.get("review_id") or ""
    if not review_id:
        return toast("error", "卡片数据缺失，请联系人事重新发起")

    async with async_session_factory() as session:
        review = (await session.execute(
            select(ProbationReview).where(
                ProbationReview.id == UUID(review_id),
                ProbationReview.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if review is None or review.status != "pending_reviewer":
            return toast("error", "该评估任务不存在或已结束")
        if open_id and open_id != review.reviewer_open_id:
            return toast("error", "请使用收到评估卡片的飞书账号提交")

        conclusion = str(form_value.get("conclusion") or "").strip()
        comment = str(form_value.get("comment") or "").strip()
        if conclusion not in _CONCLUSIONS:
            return toast("error", "评估结论需为：通过 / 延长 / 不通过")
        if not comment:
            return toast("error", "请填写评语")

        employee = (await session.execute(
            select(Employee).where(Employee.id == review.employee_id)
        )).scalar_one_or_none()
        if employee is None:
            return toast("error", "员工档案不存在，请联系人事")

        proposed: date | None = None
        if conclusion == "延长":
            raw = str(form_value.get("proposed_probation_end") or "").strip()[:10]
            try:
                proposed = date.fromisoformat(raw)
            except ValueError:
                return toast("error", "延长时需填写新到期日（格式 2027-03-15）")
            current_end = employee.computed_probation_end
            if current_end and proposed <= current_end:
                return toast("error", f"新到期日需晚于当前到期日 {current_end}")

        review.conclusion = conclusion
        review.comment = comment
        review.proposed_probation_end = proposed
        review.status = "pending_hr"
        review.submitted_at = datetime.now(timezone.utc)
        await session.commit()

    return toast("success", "评估已提交，等待人事确认")


def register_feishu_callbacks() -> None:
    from app.platform.integrations.feishu.event_handler import register_card_action_handler

    register_card_action_handler(CARD_ACTION, handle_review_submit)


# ═══════════════════════════════════════════════════════════════
# 列表 / HR 确认生效 / 取消
# ═══════════════════════════════════════════════════════════════

async def list_reviews(session: AsyncSession, status: str | None = None) -> list[dict]:
    stmt = (
        select(ProbationReview, Employee)
        .join(Employee, Employee.id == ProbationReview.employee_id)
        .where(ProbationReview.is_deleted.is_(False))
        .order_by(ProbationReview.updated_at.desc())
    )
    if status:
        stmt = stmt.where(ProbationReview.status == status)
    rows = (await session.execute(stmt)).all()
    return [{
        "id": str(r.id),
        "employee_id": str(e.id),
        "employee_name": e.name,
        "employee_number": e.employee_number,
        "department": e.department,
        "position": e.position,
        "hire_date": e.hire_date.isoformat() if e.hire_date else None,
        "probation_end": e.computed_probation_end.isoformat() if e.computed_probation_end else None,
        "days_left": e.computed_probation_days_left,
        "reviewer_name": r.reviewer_name,
        "status": r.status,
        "conclusion": r.conclusion,
        "comment": r.comment,
        "proposed_probation_end": r.proposed_probation_end.isoformat() if r.proposed_probation_end else None,
        "hr_note": r.hr_note,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "reviewed_by": r.reviewed_by,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r, e in rows]


def _sync_creds() -> tuple[str | None, str | None]:
    from app.core.config import get_settings

    s = get_settings()
    return (
        s.HR_EMPLOYEE_SYNC_FEISHU_APP_ID or None,
        s.HR_EMPLOYEE_SYNC_FEISHU_APP_SECRET or None,
    )


async def finalize_review(session: AsyncSession, review_id: UUID, hr_note: str | None, reviewer: str) -> dict:
    """HR 确认生效。

    通过：源表「员工性质」=正式 + 本地 status_category=正式 / status=在职，
    probation_end_date 定格（保留转正依据）。
    延长：写新 probation_end_date（不改状态），评估记录完结，到期后再发起。
    不通过：不改任何状态，仅完结记录（后续走离职流程）。
    """
    review = (await session.execute(
        select(ProbationReview).where(
            ProbationReview.id == review_id, ProbationReview.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if review is None:
        raise ValueError("评估记录不存在")
    if review.status != "pending_hr":
        raise ValueError("仅「待HR确认」的评估可确认生效")
    employee = (await session.execute(
        select(Employee).where(Employee.id == review.employee_id)
    )).scalar_one()

    extended_to: date | None = None
    if review.conclusion == "通过":
        await _write_source_category(session, employee, "正式")
        # 先取到期日（status_category 改正式后 computed 将返回 None）
        end = employee.computed_probation_end
        employee.status_category = "正式"
        employee.status = "在职"
        # 到期日定格（空则写入当天），保留转正依据
        employee.probation_end_date = end or date.today()
    elif review.conclusion == "延长":
        extended_to = review.proposed_probation_end or employee.computed_probation_end
        employee.probation_end_date = extended_to
    # 不通过：不改状态，提示走离职流程

    review.status = "effective"
    review.hr_note = hr_note
    review.reviewed_by = reviewer
    review.reviewed_at = datetime.now(timezone.utc)
    await session.commit()

    await _send_card(review.reviewer_open_id, _build_result_notice(review, employee, extended_to=extended_to))
    return {"conclusion": review.conclusion, "extended_to": extended_to.isoformat() if extended_to else None}


async def _write_source_category(session: AsyncSession, employee: Employee, value: str) -> None:
    """回写源表「员工性质」列（列名 COLUMN_MAP 候选×源表实际列自适配）。

    转正不同步只读限制：源表是唯一权威源，写回后每日对账派生 status=在职，
    本地预更新只是让 HR 免手动同步。
    """
    from app.platform.integrations.feishu import bitable as pb

    from app.modules.hr.employee_sync.config import load_config
    from app.modules.hr.employee_sync.mapping import COLUMN_MAP

    if not employee.feishu_record_id:
        raise ValueError(f"{employee.name} 无源表记录ID（feishu_record_id），请先执行一次员工同步再转正")
    cfg = await load_config(session)
    if not cfg.is_ready:
        raise ValueError("员工档案同步未启用或未配置源表，无法回写员工性质")

    app_id, app_secret = _sync_creds()
    fields_meta = await pb.list_fields(cfg.app_token, cfg.source_table_id, app_id=app_id, app_secret=app_secret)
    available = {f["field_name"] for f in fields_meta}
    col = next(
        (c for c, f in COLUMN_MAP.items() if f == "status_category" and c in available), None,
    )
    if col is None:
        raise ValueError("源表中未找到「员工性质/用工性质」列，无法回写，请联系管理员核对源表")

    await pb.update_record(
        cfg.app_token, cfg.source_table_id, employee.feishu_record_id,
        {col: value}, app_id=app_id, app_secret=app_secret,
    )


async def cancel_review(session: AsyncSession, review_id: UUID, operator: str) -> None:
    """取消进行中的评估（发错人/重复发起等场景）。"""
    review = (await session.execute(
        select(ProbationReview).where(
            ProbationReview.id == review_id, ProbationReview.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if review is None:
        raise ValueError("评估记录不存在")
    if review.status not in ("pending_reviewer", "pending_hr"):
        raise ValueError("仅进行中的评估可取消")
    review.status = "cancelled"
    review.reviewed_by = operator
    review.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
