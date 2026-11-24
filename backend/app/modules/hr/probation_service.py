"""试用期转正评估（三级审批链）。

流程：发起（HR 面板或 30 天提醒卡上部门负责人）→ 解析三级审批人
（直属上级←员工档案 direct_manager_name；部门经理/分管领导←hr.departments
部门配置）→ 直属上级填评估卡（通过/延长/不通过）→ 部门经理审（同意/退回）
→ 分管领导审（同意/退回）→ 三级同意自动生效（回写源表「员工性质」=正式，
同步派生将产出在职，绕开每日对账只读限制）。

- 直属上级「不通过」或后级「退回」→ 直接完结（rejected）
- 源表回写失败 → 提交事务回滚停在当前步骤，HR 面板可兜底确认生效
- 重点岗位须有安全考试合格记录（hr.probation_safety_exams）方可发起
- 延长 = 写 probation_end_date 后重走一轮；不通过 = 不改状态，提示走离职

复用 employee_info_collection_service 验证过的全部模式：
平台 send_user_card / register_card_action_handler / bitable.update_record
+ COLUMN_MAP 列名自适配 + _lookup_open_id 姓名→open_id。
"""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import (
    Employee,
    HrDepartment,
    ProbationReview,
    ProbationSafetyExam,
)

logger = logging.getLogger(__name__)

CARD_ACTION_SUBMIT = "probation_review_submit"
CARD_ACTION_START = "probation_review_start"

_CONCLUSIONS = ("通过", "延长", "不通过")
_DECISIONS = ("同意", "退回")

STATUS_STEP1 = "pending_step1"
STATUS_STEP2 = "pending_step2"
STATUS_STEP3 = "pending_step3"
STATUS_EFFECTIVE = "effective"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
ACTIVE_STATUSES = (STATUS_STEP1, STATUS_STEP2, STATUS_STEP3)

STATUS_LABELS = {
    STATUS_STEP1: "直属上级待评",
    STATUS_STEP2: "部门经理待审",
    STATUS_STEP3: "分管领导待审",
    STATUS_EFFECTIVE: "已生效",
    STATUS_REJECTED: "未通过/退回",
    STATUS_CANCELLED: "已取消",
}


def _label(text: str) -> dict[str, Any]:
    return {"tag": "plain_text", "content": text}


def _employee_brief(employee: Employee) -> str:
    end = employee.computed_probation_end
    end_text = end.strftime("%Y-%m-%d") if end else "未知"
    days = employee.computed_probation_days_left
    days_text = f"（已过期 {abs(days)} 天）" if days is not None and days < 0 else f"（剩 {days} 天）"
    return (
        f"**{employee.name}**（{employee.department} · {employee.position}）\n"
        f"入职日期：{employee.hire_date} ｜ 转正到期：**{end_text}**{days_text}"
    )


def _build_review_card(review: ProbationReview, employee: Employee) -> dict[str, Any]:
    """第一级卡片：直属上级评估表单（结论/评语/延长新日期 + 提交按钮）。"""
    return {
        "schema": "2.0",
        "header": {"title": _label("试用期转正评估"), "template": "blue"},
        "body": {"elements": [
            {"tag": "markdown", "content": (
                f"{_employee_brief(employee)}\n\n"
                f"请作为**直属上级**给出转正评估结论（评估人：{review.direct_manager_name}）；"
                f"提交后将依次经部门经理、分管领导审批。"
            )},
            {"tag": "form", "name": "probation_review_form", "elements": [
                {
                    "tag": "input", "name": "conclusion", "label": _label("评估结论 *"),
                    "required": True,
                    "placeholder": _label("填：通过 / 延长 / 不通过"),
                    "max_length": 8,
                },
                {
                    # 飞书卡片 2.0 不支持 textarea 标签（ErrCode 200621 整卡拒），统一用 input
                    "tag": "input", "name": "comment", "label": _label("评语（工作表现/出勤/协作等）"),
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
                    "value": {"action": CARD_ACTION_SUBMIT, "review_id": str(review.id), "step": 1},
                },
            ]},
        ]},
    }


def _build_approval_card(review: ProbationReview, employee: Employee, step: int) -> dict[str, Any]:
    """第二/三级卡片：展示直属上级评估摘要 + 审批表单（同意/退回）。"""
    role = "部门经理" if step == 2 else "分管领导"
    approver = review.dept_manager_name if step == 2 else review.leader_name
    step1_block = (
        f"直属上级 **{review.direct_manager_name}** 评估结论：**{review.conclusion}**\n"
        f"评语：{review.comment or '—'}"
    )
    if review.conclusion == "延长" and review.proposed_probation_end:
        step1_block += f"\n建议新到期日：{review.proposed_probation_end}"
    elements = [
        {"tag": "markdown", "content": (
            f"{_employee_brief(employee)}\n\n{step1_block}\n\n"
            f"请作为**{role}** 审批（审批人：{approver}）。"
        )},
        {"tag": "form", "name": "probation_approval_form", "elements": [
            {
                "tag": "input", "name": "decision", "label": _label("审批意见 *"),
                "required": True,
                "placeholder": _label("填：同意 / 退回"),
                "max_length": 8,
            },
            {
                "tag": "input", "name": "comment", "label": _label("批示说明"),
                "required": False, "max_length": 300,
            },
            {
                "tag": "button", "action_type": "form_submit", "name": "submit",
                "text": {"tag": "lark_md", "content": "**提交审批**"}, "type": "primary",
                "value": {"action": CARD_ACTION_SUBMIT, "review_id": str(review.id), "step": step},
            },
        ]},
    ]
    return {
        "schema": "2.0",
        "header": {"title": _label(f"试用期转正审批——{role}"), "template": "blue"},
        "body": {"elements": elements},
    }


def _build_result_notice(review: ProbationReview, employee: Employee, *, extended_to: date | None) -> dict[str, Any]:
    """生效后通知直属上级的结果卡片。"""
    if review.conclusion == "通过":
        body = f"**{employee.name}** 转正已生效（三级审批通过，员工性质→正式）。感谢你的评估。"
    elif review.conclusion == "延长":
        body = f"**{employee.name}** 试用期延长至 {extended_to}，届时将重新发起评估。"
    else:
        body = f"**{employee.name}** 的转正评估结论为「不通过」，已移交人事处理。"
    return {
        "schema": "2.0",
        "header": {"title": _label("转正评估已完成"), "template": "green"},
        "body": {"elements": [{"tag": "markdown", "content": body}]},
    }


async def _send_card(open_id: str, card: dict[str, Any]) -> bool:
    from app.platform.integrations.feishu.notification import send_user_card

    try:
        return await send_user_card(open_id, card=card)
    except Exception as e:  # noqa: BLE001
        logger.warning("发送转正评估卡片失败 open_id=%s: %s", open_id, e)
        return False


# ═══════════════════════════════════════════════════════════════
# 审批人解析与发起
# ═══════════════════════════════════════════════════════════════

async def _resolve_open_id_by_name(name: str) -> str | None:
    from app.modules.hr.feishu_review_service import _lookup_open_id

    return await _lookup_open_id(name)


async def _resolve_department_approvers(
    session: AsyncSession, employee: Employee,
) -> tuple[str | None, str | None]:
    """部门经理/分管领导：hr.departments 按员工体现部门名查配置。"""
    dept = (await session.execute(
        select(HrDepartment).where(
            HrDepartment.name == employee.department,
            HrDepartment.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if dept is None:
        return None, None
    return dept.department_manager_name, dept.supervising_leader_name


async def has_passed_safety_exam(session: AsyncSession, employee_id: UUID) -> bool:
    """重点岗位卡点：是否已有合格的安全考试记录。"""
    row = (await session.execute(
        select(ProbationSafetyExam.id).where(
            ProbationSafetyExam.employee_id == employee_id,
            ProbationSafetyExam.passed.is_(True),
            ProbationSafetyExam.is_deleted.is_(False),
        ).limit(1)
    )).scalar_one_or_none()
    return row is not None


async def create_review(session: AsyncSession, employee_id: UUID, operator: str) -> ProbationReview:
    """发起转正评估：校验 → 解析三级审批人 → 私发直属上级评估卡。

    审批人来源：直属上级←员工档案 direct_manager_name（飞书源表同步或 HR 维护）；
    部门经理/分管领导←hr.departments 部门配置（部门管理界面维护）。
    """
    from app.modules.hr.probation_config import reload_probation_config

    await reload_probation_config(session)

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
            ProbationReview.status.in_(ACTIVE_STATUSES),
            ProbationReview.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if active is not None:
        raise ValueError(f"{employee.name} 已有进行中的转正评估")
    if employee.is_key_position and not await has_passed_safety_exam(session, employee_id):
        raise ValueError(
            f"{employee.name} 为重点岗位，须先通过安全办组织的安全考试（合格记录由安全办录入）方可发起转正"
        )

    direct_name = (employee.direct_manager_name or "").strip()
    if not direct_name:
        raise ValueError(f"{employee.name} 档案未登记「直属上级」，请先在员工档案/飞书源表补录后再发起")
    dept_manager_name, leader_name = await _resolve_department_approvers(session, employee)
    if not dept_manager_name:
        raise ValueError(f"部门「{employee.department}」未配置部门负责人，请先在部门管理中维护")
    if not leader_name:
        raise ValueError(f"部门「{employee.department}」未配置分管领导，请先在部门管理中维护")

    direct_open_id = await _resolve_open_id_by_name(direct_name)
    if not direct_open_id:
        raise ValueError(f"未找到直属上级「{direct_name}」的飞书账号（需其登录过系统或在源表有员工账号）")
    dept_manager_open_id = await _resolve_open_id_by_name(dept_manager_name)
    leader_open_id = await _resolve_open_id_by_name(leader_name)

    review = ProbationReview(
        id=uuid.uuid4(), employee_id=employee_id,
        current_step=1,
        direct_manager_name=direct_name, direct_manager_open_id=direct_open_id,
        dept_manager_name=dept_manager_name, dept_manager_open_id=dept_manager_open_id,
        leader_name=leader_name, leader_open_id=leader_open_id,
        hr_note=f"发起人：{operator}" if operator else None,
    )
    if not await _send_card(direct_open_id, _build_review_card(review, employee)):
        raise ValueError("评估卡片发送失败（网络或机器人权限），请稍后重试")
    session.add(review)
    await session.commit()
    return review


# ═══════════════════════════════════════════════════════════════
# 卡片回调（平台注册制）：三级评估提交 + 提醒卡发起
# ═══════════════════════════════════════════════════════════════

def _current_approver(review: ProbationReview) -> tuple[str | None, str | None]:
    """(姓名, open_id)：当前步骤应处理的审批人。"""
    if review.current_step == 1:
        return review.direct_manager_name, review.direct_manager_open_id
    if review.current_step == 2:
        return review.dept_manager_name, review.dept_manager_open_id
    return review.leader_name, review.leader_open_id


async def _advance_step(session: AsyncSession, review: ProbationReview, employee: Employee) -> None:
    """推进到下一级并发卡（调用方负责 commit；步内仅内存变更 + flush）。"""
    review.current_step += 1
    review.status = {2: STATUS_STEP2, 3: STATUS_STEP3}[review.current_step]
    await session.flush()
    approver_name, approver_open_id = _current_approver(review)
    if approver_open_id:
        await _send_card(approver_open_id, _build_approval_card(review, employee, review.current_step))
    else:
        logger.warning(
            "转正评估 %s 第 %d 级审批人 %s 无 open_id，跳过发卡（HR 可在面板兜底处理）",
            review.id, review.current_step, approver_name,
        )


async def _try_effectuate(session: AsyncSession, review: ProbationReview, employee: Employee) -> bool:
    """第三级同意后自动生效；源表回写失败回滚并返回 False（决策已另行落库，
    评估停留 pending_step3，HR 可在面板兜底确认生效）。

    回写链路的失败形态包括配置类 ValueError 与飞书网络/SDK 异常，都回落
    到「HR 兜底生效」而非让卡片回调 500（回调失败会引发飞书重试）。"""
    review_pk = review.id
    try:
        review.status = STATUS_EFFECTIVE
        review.reviewed_at = datetime.now(UTC)
        review.reviewed_by = "系统自动（三级审批通过）"
        await _effectuate_employee(session, review, employee)
        await session.commit()
        return True
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        # rollback 后对象 expire，此处不得再访问 review 属性（会触发懒加载）
        logger.warning("转正评估 %s 自动生效失败（源表回写）：%s", review_pk, e)
        return False


async def _effectuate_employee(session: AsyncSession, review: ProbationReview, employee: Employee) -> date | None:
    """按直属上级结论落员工状态（通过/延长/不通过），返回延长后到期日。"""
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
    return extended_to


async def handle_review_submit(payload: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    """三级审批卡提交回调：防代填（按当前步骤 open_id）→ 推进/完结。"""
    from app.core.database import async_session_factory

    def toast(kind: str, content: str) -> dict[str, Any]:
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
        if review is None or review.status not in ACTIVE_STATUSES:
            return toast("error", "该评估任务不存在或已结束")
        _, expected_open_id = _current_approver(review)
        if open_id and expected_open_id and open_id != expected_open_id:
            return toast("error", "请使用收到本环节卡片的飞书账号提交")

        employee = (await session.execute(
            select(Employee).where(Employee.id == review.employee_id)
        )).scalar_one_or_none()
        if employee is None:
            return toast("error", "员工档案不存在，请联系人事")

        now = datetime.now(UTC)

        if review.current_step == 1:
            conclusion = str(form_value.get("conclusion") or "").strip()
            comment = str(form_value.get("comment") or "").strip()
            if conclusion not in _CONCLUSIONS:
                return toast("error", "评估结论需为：通过 / 延长 / 不通过")
            if not comment:
                return toast("error", "请填写评语")

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
            review.direct_manager_decided_at = now

            if conclusion == "不通过":
                # 直属上级不通过：无需后续审批，直接完结
                review.status = STATUS_REJECTED
                review.reviewed_at = now
                review.reviewed_by = "直属上级结论：不通过"
                await session.commit()
                return toast("success", "评估已提交（结论：不通过），已移交人事处理")

            await _advance_step(session, review, employee)
            await session.commit()
            return toast("success", "评估已提交，已流转至部门经理审批")

        # step 2/3：审批（同意/退回）——决策先落库，生效失败不吞决策
        decision = str(form_value.get("decision") or "").strip()
        comment = str(form_value.get("comment") or "").strip()
        if decision not in _DECISIONS:
            return toast("error", "审批意见需为：同意 / 退回")
        if review.current_step == 2:
            review.dept_manager_decision = decision
            review.dept_manager_comment = comment or None
            review.dept_manager_decided_at = now
        else:
            review.leader_decision = decision
            review.leader_comment = comment or None
            review.leader_decided_at = now

        if decision == "退回":
            review.status = STATUS_REJECTED
            review.reviewed_at = now
            review.reviewed_by = "审批退回"
            await session.commit()
            return toast("success", "已退回，评估流转终止（人事可重新发起）")

        if review.current_step == 2:
            await _advance_step(session, review, employee)
            await session.commit()
            return toast("success", "审批已提交，已流转至分管领导审批")

        # 第三级同意：先保决策，再尝试自动生效（失败停在 pending_step3）
        await session.commit()
        if await _try_effectuate(session, review, employee):
            await _send_card(
                review.direct_manager_open_id,
                _build_result_notice(review, employee, extended_to=employee.probation_end_date),
            )
            return toast("success", "三级审批全部通过，已自动转正生效")
        return toast("error", "审批已记录，但生效回写源表失败：请联系人事在转正面板确认生效")


async def handle_review_start(payload: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    """30 天提醒卡上的「发起转正评估」按钮：校验点击人身份后发起。

    允许：该员工部门的部门负责人（收卡人）或拥有 hr:profile:update 的 HR。
    """
    from app.core.database import async_session_factory

    def toast(kind: str, content: str) -> dict[str, Any]:
        return {"toast": {"type": kind, "content": content}}

    open_id = payload.get("_open_id") or ""
    employee_id = payload.get("employee_id") or ""
    if not employee_id:
        return toast("error", "卡片数据缺失")

    async with async_session_factory() as session:
        employee = (await session.execute(
            select(Employee).where(Employee.id == UUID(employee_id), Employee.is_deleted.is_(False))
        )).scalar_one_or_none()
        if employee is None:
            return toast("error", "员工不存在")

        # 身份校验：点击人是本部门负责人，或有档案编辑权限的 HR
        allowed = False
        operator = "部门负责人"
        if open_id:
            dept_manager_name, _ = await _resolve_department_approvers(session, employee)
            if dept_manager_name:
                manager_open_id = await _resolve_open_id_by_name(dept_manager_name)
                if manager_open_id and manager_open_id == open_id:
                    allowed = True
                    operator = f"部门负责人 {dept_manager_name}"
        if not allowed and open_id:
            from app.platform.identity.models import User
            from app.platform.permission.deps import get_user_permissions

            user = (await session.execute(
                select(User).where(User.feishu_open_id == open_id)
            )).scalar_one_or_none()
            if user is not None:
                perms = await get_user_permissions(str(user.id), session)
                if "hr:profile:update" in perms:
                    allowed = True
                    operator = f"HR {user.name}"
        if not allowed:
            return toast("error", "仅本部门负责人或人事可发起转正评估")

        try:
            review = await create_review(session, UUID(employee_id), operator=operator)
        except ValueError as e:
            return toast("error", str(e))
        return toast("success", f"已发起（评估卡已发送给直属上级 {review.direct_manager_name}）")


def register_feishu_callbacks() -> None:
    from app.platform.integrations.feishu.event_handler import (
        register_card_action_handler,
    )

    register_card_action_handler(CARD_ACTION_SUBMIT, handle_review_submit)
    register_card_action_handler(CARD_ACTION_START, handle_review_start)


# ═══════════════════════════════════════════════════════════════
# 列表 / HR 兜底生效 / 取消 / 安全考试
# ═══════════════════════════════════════════════════════════════

async def list_reviews(session: AsyncSession, status: str | None = None) -> list[dict[str, Any]]:
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
        "current_step": r.current_step,
        "status": r.status,
        "status_label": STATUS_LABELS.get(r.status, r.status),
        "direct_manager_name": r.direct_manager_name,
        "dept_manager_name": r.dept_manager_name,
        "leader_name": r.leader_name,
        "conclusion": r.conclusion,
        "comment": r.comment,
        "proposed_probation_end": r.proposed_probation_end.isoformat() if r.proposed_probation_end else None,
        "dept_manager_decision": r.dept_manager_decision,
        "dept_manager_comment": r.dept_manager_comment,
        "leader_decision": r.leader_decision,
        "leader_comment": r.leader_comment,
        "hr_note": r.hr_note,
        "direct_manager_decided_at": r.direct_manager_decided_at.isoformat() if r.direct_manager_decided_at else None,
        "dept_manager_decided_at": r.dept_manager_decided_at.isoformat() if r.dept_manager_decided_at else None,
        "leader_decided_at": r.leader_decided_at.isoformat() if r.leader_decided_at else None,
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


async def finalize_review(session: AsyncSession, review_id: UUID, hr_note: str | None, reviewer: str) -> dict[str, Any]:
    """HR 兜底确认生效（三级审批通过但源表回写失败的重试入口；也可对
    进行中记录直接生效——HR 判断场景，如线下已沟通完毕）。"""
    review = (await session.execute(
        select(ProbationReview).where(
            ProbationReview.id == review_id, ProbationReview.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if review is None:
        raise ValueError("评估记录不存在")
    if review.status not in ACTIVE_STATUSES:
        raise ValueError("仅进行中的评估可确认生效")
    if review.current_step == 1 and not review.conclusion:
        raise ValueError("直属上级尚未提交评估结论，无法确认生效")
    employee = (await session.execute(
        select(Employee).where(Employee.id == review.employee_id)
    )).scalar_one()

    extended_to = await _effectuate_employee(session, review, employee)
    review.status = STATUS_EFFECTIVE
    review.hr_note = hr_note or review.hr_note
    review.reviewed_by = reviewer
    review.reviewed_at = datetime.now(UTC)
    await session.commit()

    await _send_card(review.direct_manager_open_id, _build_result_notice(review, employee, extended_to=extended_to))
    return {"conclusion": review.conclusion, "extended_to": extended_to.isoformat() if extended_to else None}


async def _write_source_category(session: AsyncSession, employee: Employee, value: str) -> None:
    """回写源表「员工性质」列（列名 COLUMN_MAP 候选×源表实际列自适配）。

    转正不同步只读限制：源表是唯一权威源，写回后每日对账派生 status=在职，
    本地预更新只是让 HR 免手动同步。
    """
    from app.modules.hr.employee_sync.config import load_config
    from app.modules.hr.employee_sync.mapping import COLUMN_MAP
    from app.platform.integrations.feishu import bitable as pb

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
    if review.status not in ACTIVE_STATUSES:
        raise ValueError("仅进行中的评估可取消")
    review.status = STATUS_CANCELLED
    review.reviewed_by = operator
    review.reviewed_at = datetime.now(UTC)
    await session.commit()


# ═══════════════════════════════════════════════════════════════
# 安全考试结果（安全办录入）
# ═══════════════════════════════════════════════════════════════

async def list_safety_exams(
    session: AsyncSession, employee_id: UUID | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(ProbationSafetyExam, Employee)
        .join(Employee, Employee.id == ProbationSafetyExam.employee_id)
        .where(ProbationSafetyExam.is_deleted.is_(False))
        .order_by(ProbationSafetyExam.exam_date.desc())
    )
    if employee_id:
        stmt = stmt.where(ProbationSafetyExam.employee_id == employee_id)
    rows = (await session.execute(stmt)).all()
    return [{
        "id": str(x.id),
        "employee_id": str(e.id),
        "employee_name": e.name,
        "employee_number": e.employee_number,
        "department": e.department,
        "exam_date": x.exam_date.isoformat(),
        "passed": x.passed,
        "score": x.score,
        "entered_by": x.entered_by,
        "remark": x.remark,
    } for x, e in rows]


async def add_safety_exam(
    session: AsyncSession, *, employee_id: UUID, exam_date: date,
    passed: bool, score: float | None, entered_by: str, remark: str | None,
) -> dict[str, Any]:
    employee = (await session.execute(
        select(Employee).where(Employee.id == employee_id, Employee.is_deleted.is_(False))
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工不存在")
    exam = ProbationSafetyExam(
        id=uuid.uuid4(),
        employee_id=employee_id, exam_date=exam_date, passed=passed,
        score=score, entered_by=entered_by or None, remark=remark or None,
    )
    session.add(exam)
    await session.commit()
    return {
        "id": str(exam.id), "employee_id": str(employee_id),
        "employee_name": employee.name,
        "exam_date": exam_date.isoformat(), "passed": passed, "score": score,
    }


async def delete_safety_exam(session: AsyncSession, exam_id: UUID) -> None:
    exam = (await session.execute(
        select(ProbationSafetyExam).where(
            ProbationSafetyExam.id == exam_id,
            ProbationSafetyExam.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if exam is None:
        raise ValueError("考试记录不存在")
    exam.is_deleted = True
    await session.commit()
