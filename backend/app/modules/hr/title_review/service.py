"""职称评审业务编排（v3：审批前置 + 内网投票）。

流程：员工飞书审批申报（部门负责人→HR 两道，飞书原生）→ 审批通过自动写入
申报表 → 系统同步落库 → 评委登录内网系统投票（匿名）→ 票数判定
(同意÷(同意+不同意)≥2/3) → 飞书卡片通知申报人。
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import Employee
from app.modules.hr.title_review import models as m
from app.modules.hr.title_review.repository import (
    TitleReviewActivityRepository,
    TitleReviewApplicationRepository,
    TitleReviewDeptCommitteeRepository,
    TitleReviewDimensionRepository,
    TitleReviewJudgeRepository,
    TitleReviewLevelRepository,
    TitleReviewScoreRepository,
)
from app.modules.hr.title_review.schemas import (
    TitleReviewActivityCreate,
    TitleReviewActivityUpdate,
    TitleReviewDeptCommitteeIn,
    TitleReviewJudgeAssignIn,
    TitleReviewLevelIn,
)
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

# ─── 申报表字段映射（与原型一致） ───
APPLY_SELF_EVAL_FIELDS = [
    "岗位任务自我评价",
    "工作思想表现自我评价",
    "组织项目自我评价",
    "科技成果自我评价",
    "专利论文自我评价",
    "合理化建议自我评价",
    "培养指导自我评价",
]
APPLY_WORK_FIELDS = [
    "岗位规定的职责任务完成情况",
    "组织处理技术项目及效果",
    "专业工作合理化建议及采纳情况",
    "任现职以来主要专业技术/职业技能工作业绩",
    "专利/论文/著作/总结/报告及发表情况",
    "科技/技改/管理/研究成果及奖励情况",
    "培养指导专业技术人员学习工作情况",
    "工作思想表现及执行政策水平",
]
APPLY_ATTACHMENT_FIELDS = [
    "职称评审申报表",
    "业绩成果证明材料",
    "论文论著专利",
    "外部职称证书",
]


def _as_str(value: Any) -> str | None:
    """飞书字段值转字符串（select/lookup 可能返回 list）。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(v) for v in value]
        return "".join(parts) if parts else None
    return str(value)


def _as_bool_text(value: Any) -> bool:
    return _as_str(value) == "是"


def _as_ts(value: Any) -> datetime | None:
    """datetime 字段（毫秒时间戳 int）→ datetime。"""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def _parse_attachments(raw: Any) -> list[dict[str, Any]] | None:
    """附件字段 → 元数据列表 [{file_token,name,size}]。"""
    if not isinstance(raw, list):
        return None
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(
                {
                    "file_token": item.get("file_token", ""),
                    "name": item.get("name", ""),
                    "size": item.get("size", 0),
                }
            )
    return result or None


def decide_by_votes(agree: int, oppose: int, pass_ratio: float) -> bool:
    """票数判定：同意÷(同意+不同意) ≥ pass_ratio（弃权不计分母；有同意且无反对即通过）。"""
    voted = agree + oppose
    if voted == 0:
        return False
    return agree / voted >= pass_ratio


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    user: Any = None,
    resource_type: str,
    resource_id: UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """审计落库（容错包装：审计失败不阻断业务）。"""
    try:
        await record_audit_log(
            db,
            action=action,
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )
    except Exception:
        logger.exception("审计日志记录失败: action=%s", action)


def _apply_fields_to_dict(fields: dict[str, Any]) -> dict[str, Any]:
    """原型申报表字段 → 内网结构化数据。"""
    self_evaluations: dict[str, str] = {}
    for k in APPLY_SELF_EVAL_FIELDS:
        val = _as_str(fields.get(k))
        if val is not None:
            self_evaluations[k] = val
    work_statements: dict[str, str] = {}
    for k in APPLY_WORK_FIELDS:
        text_val = _as_str(fields.get(k))
        if text_val is not None:
            work_statements[k] = text_val
    perf = _as_str(fields.get("近五年年终绩效考核结果"))
    if perf:
        work_statements["近五年年终绩效考核结果"] = perf
    attachments: dict[str, list[dict[str, Any]]] = {}
    for k in APPLY_ATTACHMENT_FIELDS:
        attach_val = _parse_attachments(fields.get(k))
        if attach_val is not None:
            attachments[k] = attach_val
    return {
        "employee_no": str(fields.get("工号") or "").strip(),
        "name": str(fields.get("姓名") or "").strip(),
        "sequence": _as_str(fields.get("申报序列")),
        "apply_level": _as_str(fields.get("申报职级")),
        "current_level": _as_str(fields.get("现任职级")),
        "is_exception": _as_bool_text(fields.get("是否破格申报")),
        "exception_reason": _as_str(fields.get("破格申报理由")),
        "tenure_start": _as_ts(fields.get("任现职开始时间")),
        "tenure_end": _as_ts(fields.get("任现职结束时间")),
        "self_evaluations": self_evaluations or None,
        "work_statements": work_statements or None,
        "attachments": attachments or None,
        "approval_instance_code": _as_str(fields.get("审批实例编号")),
    }


class TitleReviewService:
    """职称评审编排（活动/职级组/部门评审组/申报/投票/流程）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.activity_repo = TitleReviewActivityRepository(session)
        self.level_repo = TitleReviewLevelRepository(session)
        self.dimension_repo = TitleReviewDimensionRepository(session)
        self.application_repo = TitleReviewApplicationRepository(session)
        self.judge_repo = TitleReviewJudgeRepository(session)
        self.score_repo = TitleReviewScoreRepository(session)
        self.committee_repo = TitleReviewDeptCommitteeRepository(session)

    # ═══ 活动 CRUD ═══

    async def create_activity(
        self, data: TitleReviewActivityCreate, user: Any = None
    ) -> m.TitleReviewActivity:
        activity = m.TitleReviewActivity(
            name=data.name,
            status=m.ACTIVITY_DRAFT,
            apply_deadline=data.apply_deadline,
            review_deadline=data.review_deadline,
            pass_ratio=data.pass_ratio,
            feishu_app_token=data.feishu_app_token,
            apply_table_id=data.apply_table_id,
            vote_table_id=data.vote_table_id,
        )
        await self.activity_repo.create(activity)
        levels = data.levels or [
            TitleReviewLevelIn(**tpl) for tpl in m.DEFAULT_LEVEL_TEMPLATE
        ]
        for i, lv in enumerate(levels, start=1):
            await self.level_repo.create(
                m.TitleReviewLevel(
                    activity_id=activity.id,
                    sequence=lv.sequence,
                    level_name=lv.level_name,
                    basic_conditions=lv.basic_conditions,
                    ability_requirements=lv.ability_requirements,
                    achievement_requirements=lv.achievement_requirements,
                    review_points=lv.review_points,
                    remark=lv.remark,
                    need_final_review=lv.need_final_review,
                    sort_order=i,
                )
            )
        # 固定 7 个评价项（投票表列名与评价项同名）
        for i, name in enumerate(m.DEFAULT_DIMENSION_NAMES, start=1):
            await self.dimension_repo.create(
                m.TitleReviewDimension(
                    activity_id=activity.id,
                    name=name,
                    feishu_field_name=name,
                    sort_order=i,
                )
            )
        await _audit(
            self.session,
            action="hr.title.activity_create",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            new_value={"name": activity.name, "pass_ratio": activity.pass_ratio},
        )
        return activity

    async def get_activity(self, activity_id: UUID) -> m.TitleReviewActivity:
        activity = await self.activity_repo.get_by_id(activity_id)
        if not activity:
            raise HTTPException(404, "评定活动不存在")
        return activity

    async def list_activities_with_progress(
        self, *, status: str | None, keyword: str | None, page: int, page_size: int
    ) -> tuple[list[m.TitleReviewActivity], int, dict[UUID, int], dict[UUID, int], dict[UUID, int]]:
        """活动分页 + 申报数/评委总数/已投票评委数（分组查询避免 N+1）。"""
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        activities, total = await self.activity_repo.list_all(
            status=status, keyword=keyword, page=page, page_size=page_size
        )
        ids = [a.id for a in activities]
        app_counts: dict[UUID, int] = {}
        voted_counts: dict[UUID, int] = {}
        total_judge_counts: dict[UUID, int] = {}
        if ids:
            app_rows = (
                await self.session.execute(
                    sa_select(m.TitleReviewApplication.activity_id, func.count())
                    .where(
                        m.TitleReviewApplication.activity_id.in_(ids),
                        m.TitleReviewApplication.is_deleted == False,  # noqa: E712
                    )
                    .group_by(m.TitleReviewApplication.activity_id)
                )
            ).all()
            app_counts = {row[0]: row[1] for row in app_rows}
            judge_rows = (
                await self.session.execute(
                    sa_select(
                        m.TitleReviewJudge.activity_id,
                        func.count(),
                        func.count().filter(m.TitleReviewJudge.vote_result.isnot(None)),
                    )
                    .where(
                        m.TitleReviewJudge.activity_id.in_(ids),
                        m.TitleReviewJudge.is_deleted == False,  # noqa: E712
                    )
                    .group_by(m.TitleReviewJudge.activity_id)
                )
            ).all()
            total_judge_counts = {row[0]: row[1] for row in judge_rows}
            voted_counts = {row[0]: row[2] for row in judge_rows}
        return activities, total, app_counts, voted_counts, total_judge_counts

    async def update_activity(
        self, activity_id: UUID, data: TitleReviewActivityUpdate, user: Any = None
    ) -> m.TitleReviewActivity:
        activity = await self.get_activity(activity_id)
        old = {"name": activity.name, "pass_ratio": activity.pass_ratio}

        if data.name is not None and data.name != activity.name:
            self._ensure_draft(activity, "活动名称")
            activity.name = data.name
        if activity.status == m.ACTIVITY_CLOSED:
            raise HTTPException(400, "活动已结束，不可修改")
        if "apply_deadline" in data.model_fields_set:
            activity.apply_deadline = data.apply_deadline
        if "review_deadline" in data.model_fields_set:
            activity.review_deadline = data.review_deadline
        if "pass_ratio" in data.model_fields_set and data.pass_ratio is not None:
            activity.pass_ratio = data.pass_ratio
        for field_name, value in (
            ("feishu_app_token", data.feishu_app_token),
            ("apply_table_id", data.apply_table_id),
            ("vote_table_id", data.vote_table_id),
        ):
            if value is not None and getattr(activity, field_name) != value:
                self._ensure_draft(activity, "飞书表格绑定")
                setattr(activity, field_name, value)

        if data.levels is not None:
            self._ensure_draft(activity, "职级组")
            existing = await self.level_repo.list_by_activity(activity.id)
            for old_lv in existing:
                old_lv.is_deleted = True
            for i, lv in enumerate(data.levels, start=1):
                await self.level_repo.create(
                    m.TitleReviewLevel(
                        activity_id=activity.id,
                        sequence=lv.sequence,
                        level_name=lv.level_name,
                        basic_conditions=lv.basic_conditions,
                        ability_requirements=lv.ability_requirements,
                        achievement_requirements=lv.achievement_requirements,
                        review_points=lv.review_points,
                        remark=lv.remark,
                        need_final_review=lv.need_final_review,
                        sort_order=i,
                    )
                )

        activity = await self.activity_repo.update(activity)
        await _audit(
            self.session,
            action="hr.title.activity_update",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            old_value=old,
            new_value={"name": activity.name, "pass_ratio": activity.pass_ratio},
        )
        return activity

    async def delete_activity(self, activity_id: UUID, user: Any = None) -> None:
        activity = await self.get_activity(activity_id)
        if activity.status != m.ACTIVITY_DRAFT:
            raise HTTPException(400, "仅配置中（draft）的活动可删除")
        count = await self.application_repo.count_by_activity(activity.id)
        if count > 0:
            raise HTTPException(400, f"活动已有 {count} 条申报记录，不可删除")
        for lv in await self.level_repo.list_by_activity(activity.id):
            lv.is_deleted = True
        for dim in await self.dimension_repo.list_by_activity(activity.id):
            dim.is_deleted = True
        activity.is_deleted = True
        await self.activity_repo.update(activity)
        await _audit(
            self.session,
            action="hr.title.activity_delete",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            old_value={"name": activity.name},
        )

    async def bind_tables(self, activity_id: UUID, user: Any = None) -> m.TitleReviewActivity:
        """校验绑定表格可访问 + 订阅事件 + 回写投票表评价项 field_id。"""
        from app.modules.hr.title_review import bitable_client as bc

        activity = await self.get_activity(activity_id)
        if not (activity.feishu_app_token and activity.apply_table_id and activity.vote_table_id):
            raise HTTPException(400, "请先在活动编辑中粘贴 app_token、申报表 table_id、投票表 table_id")
        try:
            apply_fields = await bc.list_fields(
                activity.feishu_app_token, activity.apply_table_id
            )
            vote_fields = await bc.list_fields(
                activity.feishu_app_token, activity.vote_table_id
            )
            await bc.subscribe_bitable(activity.feishu_app_token)
        except bc.TitleReviewBitableError as exc:
            raise HTTPException(502, f"绑定飞书表格失败：{exc}") from exc
        apply_names = {f.get("field_name") for f in apply_fields}
        missing_apply = {"姓名", "工号", "附件4评审结果", "同意票数", "不同意票数", "弃权票数"} - apply_names
        if missing_apply:
            raise HTTPException(400, f"申报表缺少必需列：{'、'.join(sorted(missing_apply))}")
        vote_name_to_id = {f.get("field_name"): f.get("field_id") for f in vote_fields}
        missing_vote = set(m.DEFAULT_DIMENSION_NAMES) | {"评审人编号", "评审人角色", "综合等级", "投票结果", "投票状态", "评审意见"} - set(vote_name_to_id)
        if missing_vote:
            raise HTTPException(400, f"投票表缺少必需列：{'、'.join(sorted(missing_vote))}")
        dims = await self.dimension_repo.list_by_activity(activity.id)
        for dim in dims:
            fid = vote_name_to_id.get(dim.feishu_field_name)
            if fid:
                dim.feishu_field_id = fid
        await self.session.flush()
        await _audit(
            self.session,
            action="hr.title.activity_bind_tables",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            new_value={
                "feishu_app_token": activity.feishu_app_token,
                "apply_table_id": activity.apply_table_id,
                "vote_table_id": activity.vote_table_id,
            },
        )
        return activity

    # ─── 状态流转 ───

    async def open_activity(self, activity_id: UUID, user: Any = None) -> m.TitleReviewActivity:
        activity = await self.get_activity(activity_id)
        if activity.status != m.ACTIVITY_DRAFT:
            raise HTTPException(400, f"仅配置中（draft）的活动可开启，当前：{activity.status}")
        if not (activity.feishu_app_token and activity.apply_table_id and activity.vote_table_id):
            raise HTTPException(400, "请先绑定飞书表格（app_token/申报表/投票表）")
        levels = await self.level_repo.list_by_activity(activity.id)
        if not levels:
            raise HTTPException(400, "请先配置职级组")
        activity.status = m.ACTIVITY_OPEN
        activity = await self.activity_repo.update(activity)
        await _audit(
            self.session,
            action="hr.title.activity_status",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            old_value={"status": m.ACTIVITY_DRAFT},
            new_value={"status": m.ACTIVITY_OPEN},
        )
        return activity

    async def start_review(self, activity_id: UUID, user: Any = None) -> m.TitleReviewActivity:
        activity = await self.get_activity(activity_id)
        if activity.status != m.ACTIVITY_OPEN:
            raise HTTPException(400, f"仅申报中（open）的活动可开启评审，当前：{activity.status}")
        activity.status = m.ACTIVITY_REVIEWING
        activity = await self.activity_repo.update(activity)
        # 批量流转：submitted → voting，并按部门自动分配评委
        assigned = 0
        applications = await self.application_repo.list_all_by_activity(activity.id)
        for application in applications:
            if application.status == m.APPLICATION_SUBMITTED:
                application.status = m.APPLICATION_VOTING
                await self.application_repo.update(application)
                assigned += await self._auto_assign_for_application(activity, application)
        if assigned:
            logger.info("开始评审批量分配评委: activity=%s assigned=%s", activity.id, assigned)
        await _audit(
            self.session,
            action="hr.title.activity_status",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            old_value={"status": m.ACTIVITY_OPEN},
            new_value={"status": m.ACTIVITY_REVIEWING},
        )
        return activity

    async def close_activity(self, activity_id: UUID, user: Any = None) -> m.TitleReviewActivity:
        activity = await self.get_activity(activity_id)
        if activity.status not in (m.ACTIVITY_OPEN, m.ACTIVITY_REVIEWING):
            raise HTTPException(400, f"当前状态不可关闭：{activity.status}")
        old_status = activity.status
        activity.status = m.ACTIVITY_CLOSED
        activity = await self.activity_repo.update(activity)
        await _audit(
            self.session,
            action="hr.title.activity_status",
            user=user,
            resource_type="title_review_activity",
            resource_id=activity.id,
            old_value={"status": old_status},
            new_value={"status": m.ACTIVITY_CLOSED},
        )
        return activity

    async def get_levels(self, activity_id: UUID) -> list[m.TitleReviewLevel]:
        await self.get_activity(activity_id)
        return await self.level_repo.list_by_activity(activity_id)

    async def get_dimensions(self, activity_id: UUID) -> list[m.TitleReviewDimension]:
        await self.get_activity(activity_id)
        return await self.dimension_repo.list_by_activity(activity_id)

    # ═══ 部门评审组 ═══

    async def list_departments(self) -> list[str]:
        """员工档案中去重的体现部门（部门评审组配置下拉用，与自动分配口径一致）。"""
        from sqlalchemy import select as sa_select

        result = await self.session.execute(
            sa_select(Employee.department)
            .where(Employee.is_deleted == False, Employee.department.isnot(None))  # noqa: E712
            .distinct()
            .order_by(Employee.department)
        )
        return [str(row[0]) for row in result.all() if row[0]]



    async def list_committees(self) -> list[m.TitleReviewDeptCommittee]:
        return await self.committee_repo.list_all()

    async def upsert_committee(
        self, data: TitleReviewDeptCommitteeIn, user: Any = None
    ) -> m.TitleReviewDeptCommittee:
        committee = await self.committee_repo.get_by_department(data.department)
        members = [item.model_dump(mode="json") for item in data.committee_members]
        if committee:
            committee.manager_employee_id = data.manager_employee_id
            committee.manager_name = data.manager_name
            committee.leader_employee_id = data.leader_employee_id
            committee.leader_name = data.leader_name
            committee.committee_members = members or None
            committee = await self.committee_repo.update(committee)
        else:
            committee = await self.committee_repo.create(
                m.TitleReviewDeptCommittee(
                    department=data.department,
                    manager_employee_id=data.manager_employee_id,
                    manager_name=data.manager_name,
                    leader_employee_id=data.leader_employee_id,
                    leader_name=data.leader_name,
                    committee_members=members or None,
                )
            )
        await _audit(
            self.session,
            action="hr.title.committee_upsert",
            user=user,
            resource_type="title_review_dept_committee",
            resource_id=committee.id,
            new_value={"department": committee.department},
        )
        return committee

    async def delete_committee(self, committee_id: UUID, user: Any = None) -> None:
        committee = await self.committee_repo.get_by_id(committee_id)
        if not committee:
            raise HTTPException(404, "部门评审组不存在")
        committee.is_deleted = True
        await self.committee_repo.update(committee)
        await _audit(
            self.session,
            action="hr.title.committee_delete",
            user=user,
            resource_type="title_review_dept_committee",
            resource_id=committee.id,
            old_value={"department": committee.department},
        )

    # ═══ 申报同步（飞书申报表事件 → 落库） ═══

    async def sync_apply_record_added(
        self, activity_id: UUID, record_id: str, fields: dict[str, Any]
    ) -> m.TitleReviewApplication | None:
        activity = await self.get_activity(activity_id)
        existing = await self.application_repo.get_by_feishu_record(activity.id, record_id)
        if existing:
            return None
        parsed = _apply_fields_to_dict(fields)
        employee = await self._match_employee(parsed["employee_no"], parsed["name"])
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=employee.id if employee else None,
            employee_no=parsed["employee_no"],
            name=parsed["name"],
            department=employee.department if employee else None,
            sequence=parsed["sequence"],
            apply_level=parsed["apply_level"],
            current_level=parsed["current_level"],
            is_exception=parsed["is_exception"],
            exception_reason=parsed["exception_reason"],
            tenure_start=parsed["tenure_start"],
            tenure_end=parsed["tenure_end"],
            self_evaluations=parsed["self_evaluations"],
            work_statements=parsed["work_statements"],
            attachments=parsed["attachments"],
            feishu_record_id=record_id,
            approval_instance_code=parsed["approval_instance_code"],
            status=m.APPLICATION_SUBMITTED if employee else m.APPLICATION_INVALID,
        )
        await self.application_repo.create(application)
        # 活动已进入评审期 → 自动流转到投票并按部门分配评委
        if application.status == m.APPLICATION_SUBMITTED and activity.status == m.ACTIVITY_REVIEWING:
            application.status = m.APPLICATION_VOTING
            await self.application_repo.update(application)
            await self._auto_assign_for_application(activity, application)
        await _audit(
            self.session,
            action="hr.title.application_sync",
            resource_type="title_review_application",
            resource_id=application.id,
            extra={"record_id": record_id, "valid": employee is not None},
        )
        return application

    async def sync_apply_record_edited(
        self, activity_id: UUID, record_id: str, fields: dict[str, Any]
    ) -> m.TitleReviewApplication | None:
        activity = await self.get_activity(activity_id)
        application = await self.application_repo.get_by_feishu_record(activity.id, record_id)
        if not application:
            return await self.sync_apply_record_added(activity.id, record_id, fields)
        if application.status in (
            m.APPLICATION_PASSED, m.APPLICATION_FAILED,
            m.APPLICATION_FINAL_PASSED, m.APPLICATION_FINAL_FAILED,
        ):
            return application  # 已判定不再改
        parsed = _apply_fields_to_dict(fields)
        application.employee_no = parsed["employee_no"] or application.employee_no
        application.name = parsed["name"] or application.name
        application.sequence = parsed["sequence"] or application.sequence
        application.apply_level = parsed["apply_level"] or application.apply_level
        application.current_level = parsed["current_level"] or application.current_level
        application.is_exception = parsed["is_exception"]
        application.exception_reason = parsed["exception_reason"]
        application.tenure_start = parsed["tenure_start"] or application.tenure_start
        application.tenure_end = parsed["tenure_end"] or application.tenure_end
        application.self_evaluations = parsed["self_evaluations"] or application.self_evaluations
        application.work_statements = parsed["work_statements"] or application.work_statements
        application.attachments = parsed["attachments"] or application.attachments
        employee = await self._match_employee(parsed["employee_no"], parsed["name"])
        application.employee_id = employee.id if employee else application.employee_id
        if application.status == m.APPLICATION_INVALID and employee:
            application.status = m.APPLICATION_SUBMITTED
            await self.application_repo.update(application)
            if activity.status == m.ACTIVITY_REVIEWING:
                application.status = m.APPLICATION_VOTING
                await self.application_repo.update(application)
                await self._auto_assign_for_application(activity, application)
            return application
        await self.application_repo.update(application)
        return application

    async def sync_apply_record_deleted(self, activity_id: UUID, record_id: str) -> None:
        activity = await self.get_activity(activity_id)
        application = await self.application_repo.get_by_feishu_record(activity.id, record_id)
        if not application:
            return
        if application.status in (
            m.APPLICATION_PASSED, m.APPLICATION_FAILED,
            m.APPLICATION_FINAL_PASSED, m.APPLICATION_FINAL_FAILED,
        ):
            logger.warning("已判定申报不可撤回: record_id=%s", record_id)
            return
        application.is_deleted = True
        await self.application_repo.update(application)

    async def _match_employee(
        self, employee_no: str, name: str
    ) -> Employee | None:
        """姓名+工号匹配在职员工（排除离职）。"""
        from app.modules.hr.repository import EmployeeRepository

        if not employee_no or not name:
            return None
        employee = await EmployeeRepository(self.session).get_by_employee_number(employee_no)
        if not employee or employee.status == "离职":
            return None
        if employee.name != name:
            return None
        return employee

    async def default_committee_members(
        self, application_id: UUID
    ) -> list[dict[str, Any]]:
        """申报人部门评审组的默认评委（评定小组成员）。"""
        application = await self.application_repo.get_by_id(application_id)
        if not application or not application.department:
            return []
        committee = await self.committee_repo.get_by_department(application.department)
        if not committee or not committee.committee_members:
            return []
        return list(committee.committee_members)

    async def _auto_assign_for_application(
        self, activity: m.TitleReviewActivity, application: m.TitleReviewApplication
    ) -> int:
        """按申报人部门自动分配评委（部门评审组评定小组）；无配置返回 0。"""
        if not application.department:
            return 0
        committee = await self.committee_repo.get_by_department(application.department)
        if not committee or not committee.committee_members:
            logger.info("部门 %s 未配置评审组，跳过自动分配", application.department)
            return 0
        from app.modules.hr.repository import EmployeeRepository

        emp_repo = EmployeeRepository(self.session)
        existing = await self.judge_repo.list_by_application(application.id)
        existing_ids = {j.judge_employee_id for j in existing}
        used_codes = {j.judge_code for j in existing}
        next_index = len(used_codes) + 1
        added = 0
        new_judges: list[m.TitleReviewJudge] = []
        for member in committee.committee_members:
            member_id = member.get("employee_id")
            if not member_id:
                continue
            try:
                emp_id = UUID(str(member_id))
            except (TypeError, ValueError):
                continue
            if emp_id in existing_ids:
                continue
            emp = await emp_repo.get_by_id(emp_id)
            if not emp or emp.status == "离职":
                continue
            while f"P{next_index}" in used_codes:
                next_index += 1
            judge = await self.judge_repo.create(
                m.TitleReviewJudge(
                    activity_id=activity.id,
                    application_id=application.id,
                    judge_employee_id=emp.id,
                    judge_name=emp.name,
                    judge_employee_no=emp.employee_number,
                    judge_code=f"P{next_index}",
                    judge_role="技术专家",
                )
            )
            used_codes.add(judge.judge_code)
            next_index += 1
            new_judges.append(judge)
            added += 1
        if new_judges:
            await _audit(
                self.session,
                action="hr.title.judge_auto_assign",
                resource_type="title_review_application",
                resource_id=application.id,
                new_value={
                    "department": application.department,
                    "judges": [j.judge_code for j in new_judges],
                },
            )
            from app.modules.hr.title_review.notify import send_judge_reminder

            for j in new_judges:
                try:
                    await send_judge_reminder(
                        judge_name=j.judge_name,
                        activity_name=activity.name,
                        applicant_name=application.name,
                        judge_code=j.judge_code,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("评委提醒发送失败: %s", j.judge_name)
        return added

    async def assign_judges(
        self, application_id: UUID, data: TitleReviewJudgeAssignIn, user: Any = None
    ) -> list[m.TitleReviewJudge]:
        """指定/调整评委（幂等 upsert，匿名编号）→ 提醒评委登录内网投票。"""
        application = await self.application_repo.get_by_id(application_id)
        if not application:
            raise HTTPException(404, "申报记录不存在")
        activity = await self.get_activity(application.activity_id)
        if activity.status not in (m.ACTIVITY_OPEN, m.ACTIVITY_REVIEWING):
            raise HTTPException(400, f"活动状态不可指定评委：{activity.status}")
        if application.status == m.APPLICATION_INVALID:
            raise HTTPException(400, "申报信息有误，请先联系申报人更正")
        if application.status not in (m.APPLICATION_VOTING,):
            raise HTTPException(400, f"当前状态不可指定评委：{application.status}")

        from app.modules.hr.repository import EmployeeRepository

        emp_repo = EmployeeRepository(self.session)
        employees = []
        for item in data.judges:
            emp = await emp_repo.get_by_id(item.employee_id)
            if not emp or emp.status == "离职":
                raise HTTPException(400, f"评委不存在或已离职: {item.employee_id}")
            employees.append((emp, item.role))

        existing_judges = await self.judge_repo.list_by_application(application.id)
        existing_map = {j.judge_employee_id: j for j in existing_judges}
        target_ids = {item.employee_id for item in data.judges}

        for j in existing_judges:
            if j.judge_employee_id not in target_ids:
                if j.vote_result is not None:
                    raise HTTPException(400, f"评委 {j.judge_name} 已投票，不可撤换")
                j.is_deleted = True
                await self.judge_repo.update(j)

        # 编号延续现有最大编号
        used_codes = {j.judge_code for j in existing_judges}
        next_index = len(used_codes) + 1
        new_judges: list[m.TitleReviewJudge] = []
        for emp, role in employees:
            if emp.id in existing_map and not existing_map[emp.id].is_deleted:
                continue
            while f"P{next_index}" in used_codes:
                next_index += 1
            judge = await self.judge_repo.create(
                m.TitleReviewJudge(
                    activity_id=activity.id,
                    application_id=application.id,
                    judge_employee_id=emp.id,
                    judge_name=emp.name,
                    judge_employee_no=emp.employee_number,
                    judge_code=f"P{next_index}",
                    judge_role=role,
                )
            )
            used_codes.add(judge.judge_code)
            next_index += 1
            new_judges.append(judge)

        await self.session.flush()

        all_judges = await self.judge_repo.list_by_application(application.id)
        await _audit(
            self.session,
            action="hr.title.judge_assign",
            user=user,
            resource_type="title_review_application",
            resource_id=application.id,
            new_value={
                "judges": [{"code": j.judge_code, "name": j.judge_name, "role": j.judge_role} for j in all_judges],
            },
        )
        # 提醒新评委登录内网系统投票
        if new_judges:
            from app.modules.hr.title_review.notify import send_judge_reminder

            for j in new_judges:
                try:
                    await send_judge_reminder(
                        judge_name=j.judge_name,
                        activity_name=activity.name,
                        applicant_name=application.name,
                        judge_code=j.judge_code,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("评委提醒发送失败: %s", j.judge_name)
        return all_judges

    async def sync_vote_record(
        self, activity_id: UUID, record_id: str, fields: dict[str, Any]
    ) -> None:
        """投票表记录变更：投票结果/综合等级/7 维评价落库，全投完自动判定。"""
        activity = await self.get_activity(activity_id)
        judge = None
        if record_id:
            judge = await self.judge_repo.get_by_feishu_record(record_id)
        if not judge:
            judge_code = _as_str(fields.get("评审人编号"))
            if judge_code:
                from sqlalchemy import select as sa_select

                result = await self.session.execute(
                    sa_select(m.TitleReviewJudge).where(
                        m.TitleReviewJudge.activity_id == activity_id,
                        m.TitleReviewJudge.judge_code == judge_code,
                        m.TitleReviewJudge.is_deleted == False,  # noqa: E712
                    )
                )
                judge = result.scalar_one_or_none()
        if not judge:
            logger.warning("无法匹配投票表行: record_id=%s", record_id)
            return
        application = await self.application_repo.get_by_id(judge.application_id)
        if not application:
            return

        vote_result = _as_str(fields.get("投票结果"))
        judge.vote_result = vote_result
        judge.comprehensive_grade = _as_str(fields.get("综合等级"))
        judge.review_comment = _as_str(fields.get("评审意见"))
        if vote_result:
            judge.voted_at = _as_ts(fields.get("投票时间")) or datetime.now().astimezone()
        elif _as_str(fields.get("投票状态")) == "已作废":
            judge.vote_result = None
            judge.voted_at = None
        judge = await self.judge_repo.update(judge)

        dims = await self.dimension_repo.list_by_activity(activity.id)
        for dim in dims:
            raw = _as_str(fields.get(dim.feishu_field_name))
            if raw is None:
                continue
            existing = await self.score_repo.get_by_judge_and_dimension(judge.id, dim.id)
            if existing:
                existing.grade = raw
                existing.voted_at = judge.voted_at
                await self.score_repo.update(existing)
            else:
                await self.score_repo.create(
                    m.TitleReviewScore(
                        activity_id=activity.id,
                        application_id=application.id,
                        judge_id=judge.id,
                        dimension_id=dim.id,
                        dimension_name=dim.name,
                        grade=raw,
                        voted_at=judge.voted_at,
                    )
                )
        await _audit(
            self.session,
            action="hr.title.vote_sync",
            resource_type="title_review_judge",
            resource_id=judge.id,
            extra={"judge_code": judge.judge_code, "vote_result": vote_result},
        )
        # 回写投票表“投票状态”列
        if activity.feishu_app_token and activity.vote_table_id:
            from app.modules.hr.title_review import bitable_client as bc

            try:
                await bc.update_record(
                    activity.feishu_app_token,
                    activity.vote_table_id,
                    record_id,
                    {"投票状态": "已投票" if vote_result else "未投票"},
                )
            except bc.TitleReviewBitableError as exc:
                logger.warning("回写投票状态失败: record_id=%s error=%s", record_id, exc)
        # 全部评委已投票 → 自动判定
        judges = await self.judge_repo.list_by_application(application.id)
        if judges and all(j.vote_result is not None for j in judges):
            if application.status in (m.APPLICATION_VOTING, m.APPLICATION_PASSED, m.APPLICATION_FAILED):
                await self.finalize_by_votes(application.id)

    async def finalize_by_votes(
        self, application_id: UUID, user: Any = None, force: bool = False
    ) -> m.TitleReviewApplication:
        """票数判定：统计票数 → 回写申报表 → 终审卡或结果通知。"""
        application = await self.application_repo.get_by_id(application_id)
        if not application:
            raise HTTPException(404, "申报记录不存在")
        if application.status not in (m.APPLICATION_VOTING, m.APPLICATION_PASSED, m.APPLICATION_FAILED):
            raise HTTPException(400, f"当前状态不可判定：{application.status}")
        judges = await self.judge_repo.list_by_application(application.id)
        if not judges:
            raise HTTPException(400, "尚未指定评委，无法判定")
        if not force and not all(j.vote_result is not None for j in judges):
            raise HTTPException(400, "仍有评委未投票，如需提前判定请确认")

        agree = sum(1 for j in judges if j.vote_result == m.VOTE_AGREE)
        oppose = sum(1 for j in judges if j.vote_result == m.VOTE_OPPOSE)
        abstain = sum(1 for j in judges if j.vote_result == m.VOTE_ABSTAIN)
        activity = await self.get_activity(application.activity_id)
        passed = decide_by_votes(agree, oppose, activity.pass_ratio)

        old = {
            "status": application.status,
            "agree_votes": application.agree_votes,
            "oppose_votes": application.oppose_votes,
            "abstain_votes": application.abstain_votes,
            "final_result": application.final_result,
        }
        application.agree_votes = agree
        application.oppose_votes = oppose
        application.abstain_votes = abstain
        application.final_result = m.APPLICATION_PASSED if passed else m.APPLICATION_FAILED
        application.status = m.APPLICATION_PASSED if passed else m.APPLICATION_FAILED
        application = await self.application_repo.update(application)

        # 回写申报表：票数 3 列 + 附件4评审结果
        await self._writeback_votes(application, passed)
        await _audit(
            self.session,
            action="hr.title.vote_finalize",
            user=user,
            resource_type="title_review_application",
            resource_id=application.id,
            old_value=old,
            new_value={
                "status": application.status,
                "agree_votes": agree,
                "oppose_votes": oppose,
                "abstain_votes": abstain,
            },
        )

        # 判定完成 → 直接通知申报人（终审已由飞书审批承担，v3 简化）
        await self._notify_result(application)
        return application

    async def _writeback_votes(
        self, application: m.TitleReviewApplication, passed: bool
    ) -> None:
        """回写申报表：同意/不同意/弃权票数 + 附件4评审结果。"""
        from app.modules.hr.title_review import bitable_client as bc

        activity = await self.get_activity(application.activity_id)
        if not (activity.feishu_app_token and activity.apply_table_id and application.feishu_record_id):
            return
        try:
            await bc.update_record(
                activity.feishu_app_token,
                activity.apply_table_id,
                application.feishu_record_id,
                {
                    "同意票数": application.agree_votes,
                    "不同意票数": application.oppose_votes,
                    "弃权票数": application.abstain_votes,
                    "附件4评审结果": "通过(三分之二以上同意)" if passed else "不通过",
                },
            )
        except bc.TitleReviewBitableError as exc:
            logger.warning("回写申报表票数失败: record_id=%s error=%s", application.feishu_record_id, exc)

    async def _notify_result(self, application: m.TitleReviewApplication) -> None:
        """通知申报人结果（只含总分/结果，不透露评委）。"""
        from app.modules.hr.title_review.notify import send_result_card

        if application.result_notified_at is not None:
            return
        activity = await self.get_activity(application.activity_id)
        passed = application.status in (m.APPLICATION_PASSED, m.APPLICATION_FINAL_PASSED)
        ok = await send_result_card(
            applicant_name=application.name,
            activity_name=activity.name,
            level_name=application.apply_level or "",
            passed=passed,
        )
        if ok:
            application.result_notified_at = datetime.now().astimezone()
            await self.application_repo.update(application)

    async def invalidate_application(
        self, application_id: UUID, user: Any = None
    ) -> m.TitleReviewApplication:
        """HR 标记申报信息有误。"""
        application = await self.application_repo.get_by_id(application_id)
        if not application:
            raise HTTPException(404, "申报记录不存在")
        if application.status == m.APPLICATION_INVALID:
            return application
        old = application.status
        application.status = m.APPLICATION_INVALID
        application = await self.application_repo.update(application)
        await _audit(
            self.session,
            action="hr.title.application_invalidate",
            user=user,
            resource_type="title_review_application",
            resource_id=application.id,
            old_value={"status": old},
            new_value={"status": m.APPLICATION_INVALID},
        )
        return application

    # ═══ 查询 ═══

    async def list_applications(
        self,
        activity_id: UUID,
        *,
        status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[m.TitleReviewApplication], int]:
        await self.get_activity(activity_id)
        return await self.application_repo.list_by_activity(
            activity_id, status=status, keyword=keyword, page=page, page_size=page_size
        )

    async def get_application_detail(
        self, application_id: UUID
    ) -> tuple[m.TitleReviewApplication, list[m.TitleReviewJudge]]:
        application = await self.application_repo.get_by_id(application_id)
        if not application:
            raise HTTPException(404, "申报记录不存在")
        judges = await self.judge_repo.list_by_application(application.id)
        return application, judges

    async def get_results(self, activity_id: UUID) -> list[dict[str, Any]]:
        """活动评审结果（票数、各评委投票明细）——hr:title:scores:read 数据。"""
        activity = await self.get_activity(activity_id)
        applications = await self.application_repo.list_all_by_activity(activity_id)
        results: list[dict[str, Any]] = []
        for application in applications:
            judges = await self.judge_repo.list_by_application(application.id)
            scores = await self.score_repo.list_by_application(application.id)
            scores_by_judge: dict[UUID, list[dict[str, Any]]] = {}
            for s in scores:
                scores_by_judge.setdefault(s.judge_id, []).append(
                    {
                        "id": s.id,
                        "judge_id": s.judge_id,
                        "dimension_id": s.dimension_id,
                        "dimension_name": s.dimension_name,
                        "grade": s.grade,
                        "voted_at": s.voted_at,
                    }
                )
            judge_out = []
            for j in judges:
                item = {
                    "id": j.id,
                    "application_id": j.application_id,
                    "judge_employee_id": j.judge_employee_id,
                    "judge_name": j.judge_name,
                    "judge_employee_no": j.judge_employee_no,
                    "judge_code": j.judge_code,
                    "judge_role": j.judge_role,
                    "feishu_record_id": j.feishu_record_id,
                    "vote_result": j.vote_result,
                    "comprehensive_grade": j.comprehensive_grade,
                    "review_comment": j.review_comment,
                    "voted_at": j.voted_at,
                    "scores": scores_by_judge.get(j.id, []),
                }
                judge_out.append(item)
            voted = application.agree_votes + application.oppose_votes
            level = None
            if application.sequence and application.apply_level:
                level = await self.level_repo.get_by_sequence_level(
                    activity.id, application.sequence, application.apply_level
                )
            results.append(
                {
                    "application": {
                        "id": application.id,
                        "activity_id": application.activity_id,
                        "employee_id": application.employee_id,
                        "employee_no": application.employee_no,
                        "name": application.name,
                        "department": application.department,
                        "sequence": application.sequence,
                        "apply_level": application.apply_level,
                        "current_level": application.current_level,
                        "is_exception": application.is_exception,
                        "exception_reason": application.exception_reason,
                        "tenure_start": application.tenure_start,
                        "tenure_end": application.tenure_end,
                        "self_evaluations": application.self_evaluations,
                        "work_statements": application.work_statements,
                        "attachments": application.attachments,
                        "feishu_record_id": application.feishu_record_id,
                        "status": application.status,
                        "agree_votes": application.agree_votes,
                        "oppose_votes": application.oppose_votes,
                        "abstain_votes": application.abstain_votes,
                        "final_result": application.final_result,
                        "final_opinion": application.final_opinion,
                        "result_notified_at": application.result_notified_at,
                        "created_at": application.created_at,
                    },
                    "judges": judge_out,
                    "vote_ratio": round(application.agree_votes / voted, 4) if voted else None,
                    "need_final_review": bool(level and level.need_final_review),
                }
            )
        return results

    # ═══ 评委内网投票（v3：投票在内网系统完成） ═══

    async def _resolve_judge_for_user(
        self, judge_id: UUID, employee_no: str | None
    ) -> tuple[m.TitleReviewJudge, m.TitleReviewApplication]:
        """校验评委任务归属：仅本人（工号匹配）可操作自己的投票任务。"""
        from app.modules.hr.repository import EmployeeRepository

        judge = await self.judge_repo.get_by_id(judge_id)
        if not judge:
            raise HTTPException(404, "投票任务不存在")
        if not employee_no:
            raise HTTPException(403, "无法识别您的员工身份，请联系管理员")
        employee = await EmployeeRepository(self.session).get_by_employee_number(employee_no)
        if not employee or employee.id != judge.judge_employee_id:
            raise HTTPException(403, "该投票任务不属于您")
        application = await self.application_repo.get_by_id(judge.application_id)
        if not application:
            raise HTTPException(404, "申报记录不存在")
        return judge, application

    async def list_my_judge_tasks(
        self, employee_no: str | None
    ) -> list[dict[str, Any]]:
        """评委视角：我的投票任务列表（不含其他评委信息）。"""
        if not employee_no:
            return []
        from app.modules.hr.repository import EmployeeRepository

        employee = await EmployeeRepository(self.session).get_by_employee_number(employee_no)
        if not employee:
            return []
        from sqlalchemy import select as sa_select

        result = await self.session.execute(
            sa_select(m.TitleReviewJudge)
            .where(
                m.TitleReviewJudge.judge_employee_id == employee.id,
                m.TitleReviewJudge.is_deleted == False,  # noqa: E712
            )
            .order_by(m.TitleReviewJudge.vote_result.is_(None).desc(), m.TitleReviewJudge.created_at)
        )
        tasks: list[dict[str, Any]] = []
        for judge in result.scalars().all():
            application = await self.application_repo.get_by_id(judge.application_id)
            if not application:
                continue
            activity = await self.activity_repo.get_by_id(application.activity_id)
            if not activity or activity.status == m.ACTIVITY_CLOSED:
                continue
            scores = await self.score_repo.list_by_judge(judge.id)
            tasks.append(
                {
                    "judge_id": judge.id,
                    "judge_code": judge.judge_code,
                    "status": "voted" if judge.vote_result else "pending",
                    "vote_result": judge.vote_result,
                    "comprehensive_grade": judge.comprehensive_grade,
                    "review_comment": judge.review_comment,
                    "voted_at": judge.voted_at,
                    "dimension_grades": {s.dimension_name: s.grade for s in scores},
                    "activity_name": activity.name,
                    "application": {
                        "id": application.id,
                        "activity_id": application.activity_id,
                        "employee_id": application.employee_id,
                        "employee_no": application.employee_no,
                        "name": application.name,
                        "department": application.department,
                        "sequence": application.sequence,
                        "apply_level": application.apply_level,
                        "current_level": application.current_level,
                        "is_exception": application.is_exception,
                        "exception_reason": application.exception_reason,
                        "tenure_start": application.tenure_start,
                        "tenure_end": application.tenure_end,
                        "self_evaluations": application.self_evaluations,
                        "work_statements": application.work_statements,
                        "attachments": application.attachments,
                        "feishu_record_id": application.feishu_record_id,
                        "approval_instance_code": application.approval_instance_code,
                        "status": application.status,
                        "agree_votes": application.agree_votes,
                        "oppose_votes": application.oppose_votes,
                        "abstain_votes": application.abstain_votes,
                        "final_result": application.final_result,
                        "final_opinion": application.final_opinion,
                        "result_notified_at": application.result_notified_at,
                        "created_at": application.created_at,
                    },
                }
            )
        return tasks

    async def submit_vote(
        self,
        judge_id: UUID,
        employee_no: str | None,
        data: Any,
    ) -> m.TitleReviewJudge:
        """评委提交投票：投票结果 + 综合等级 + 7 维评价 + 意见；全投完自动判定。"""
        judge, application = await self._resolve_judge_for_user(judge_id, employee_no)
        if application.status not in (m.APPLICATION_VOTING, m.APPLICATION_PASSED, m.APPLICATION_FAILED):
            raise HTTPException(400, f"当前状态不可投票：{application.status}")
        if data.vote_result not in (m.VOTE_AGREE, m.VOTE_OPPOSE, m.VOTE_ABSTAIN):
            raise HTTPException(400, "投票结果必须为：同意/不同意/弃权")

        judge.vote_result = data.vote_result
        judge.comprehensive_grade = data.comprehensive_grade
        judge.review_comment = data.review_comment
        judge.voted_at = datetime.now().astimezone()
        judge = await self.judge_repo.update(judge)

        dims = await self.dimension_repo.list_by_activity(application.activity_id)
        for dim in dims:
            grade = (data.dimension_grades or {}).get(dim.name)
            if grade is None:
                continue
            existing = await self.score_repo.get_by_judge_and_dimension(judge.id, dim.id)
            if existing:
                existing.grade = grade
                existing.voted_at = judge.voted_at
                await self.score_repo.update(existing)
            else:
                await self.score_repo.create(
                    m.TitleReviewScore(
                        activity_id=application.activity_id,
                        application_id=application.id,
                        judge_id=judge.id,
                        dimension_id=dim.id,
                        dimension_name=dim.name,
                        grade=grade,
                        voted_at=judge.voted_at,
                    )
                )
        await _audit(
            self.session,
            action="hr.title.judge_vote",
            resource_type="title_review_judge",
            resource_id=judge.id,
            extra={"judge_code": judge.judge_code, "vote_result": data.vote_result},
        )
        # 全部评委已投票 → 自动判定
        judges = await self.judge_repo.list_by_application(application.id)
        if judges and all(j.vote_result is not None for j in judges):
            await self.finalize_by_votes(application.id)
        return judge

    # ═══ 审批先行同步（飞书审批通过 → 写申报表） ═══

    async def sync_approval_instances(self, activity_id: UUID) -> dict[str, Any]:
        """拉取近 30 天已通过且未同步的审批实例，写入申报表（事件自然落库）。"""
        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        activity = await self.get_activity(activity_id)
        stats: dict[str, Any] = {
            "approval_instances_fetched": 0,
            "approval_synced": 0,
            "approval_skipped": 0,
        }
        if not activity.approval_code:
            return stats
        if not (activity.feishu_app_token and activity.apply_table_id):
            return stats

        now = datetime.now().astimezone()
        end_ms = int(now.timestamp() * 1000)
        start_ms = end_ms - 30 * 24 * 3600 * 1000
        try:
            codes = await ac.list_instance_codes(
                activity.approval_code, start_ms, end_ms
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉取审批实例失败: activity=%s error=%s", activity.id, exc)
            return stats

        # 申报表已有的审批实例编号 → 防重复写行
        existing_map: dict[str, str] = {}
        try:
            records = await bc.list_all_records(
                activity.feishu_app_token, activity.apply_table_id
            )
        except bc.TitleReviewBitableError as exc:
            logger.warning("拉取申报表失败: %s", exc)
            return stats
        for item in records:
            code = _as_str((item.get("fields") or {}).get("审批实例编号"))
            if code:
                existing_map[code] = str(item.get("record_id") or "")

        rows_to_write: list[dict[str, Any]] = []
        for code in codes:
            if code in existing_map:
                stats["approval_skipped"] += 1
                continue
            stats["approval_instances_fetched"] += 1
            try:
                instance = await ac.get_instance(code)
            except ac.TitleReviewBitableError as exc:
                logger.warning("拉取审批实例详情失败: %s error=%s", code, exc)
                continue
            if instance.get("status") != "APPROVED":
                continue
            fields = ac.form_widgets_to_fields(instance.get("form") or [])
            if not _as_str(fields.get("姓名")) or not _as_str(fields.get("工号")):
                logger.warning("审批实例缺少姓名/工号，跳过: %s", code)
                continue
            row = dict(fields)
            row["审批实例编号"] = code
            # 审批附件：有 file_token 才写申报表附件列，否则元数据并入申报说明
            for attach_key in APPLY_ATTACHMENT_FIELDS:
                raw = row.get(attach_key)
                if not isinstance(raw, list):
                    continue
                valid = [a for a in raw if isinstance(a, dict) and a.get("file_token")]
                if valid:
                    row[attach_key] = [{"file_token": a["file_token"]} for a in valid]
                else:
                    row.pop(attach_key, None)
                    meta = "、".join(
                        str(a.get("title") or a.get("name") or a.get("url") or "")
                        for a in raw
                        if isinstance(a, dict)
                    )
                    if meta:
                        note = _as_str(row.get("申报说明")) or ""
                        row["申报说明"] = f"{note}\n【{attach_key}】{meta}".strip()
            rows_to_write.append(row)

        if rows_to_write:
            try:
                await bc.batch_create_records(
                    activity.feishu_app_token, activity.apply_table_id, rows_to_write
                )
                stats["approval_synced"] = len(rows_to_write)
            except bc.TitleReviewBitableError as exc:
                logger.warning("写入申报表失败: %s", exc)
                stats["approval_synced"] = 0
        await _audit(
            self.session,
            action="hr.title.approval_sync",
            resource_type="title_review_activity",
            resource_id=activity.id,
            extra=stats,
        )
        return stats

    # ═══ 兜底对账 ═══

    async def reconcile_activity(self, activity_id: UUID) -> dict[str, Any]:
        """拉飞书全量记录与本地双向对账（幂等）。"""
        from app.modules.hr.title_review import bitable_client as bc

        activity = await self.get_activity(activity_id)
        stats: dict[str, Any] = {
            "applications_created": 0,
            "applications_removed": 0,
            "votes_updated": 0,
            "errors": [],
        }
        # 审批先行：先同步审批通过的实例 → 写入申报表（随后本对账立即拉取落库）
        if activity.approval_code:
            approval_stats = await self.sync_approval_instances(activity.id)
            stats.update(approval_stats)
        if not (activity.feishu_app_token and activity.apply_table_id):
            return stats

        try:
            feishu_records = await bc.list_all_records(
                activity.feishu_app_token, activity.apply_table_id
            )
        except bc.TitleReviewBitableError as exc:
            stats["errors"].append(f"拉取申报表失败: {exc}")
            return stats
        feishu_ids = {item.get("record_id") for item in feishu_records}
        for item in feishu_records:
            record_id = str(item.get("record_id") or "")
            fields = item.get("fields") or {}
            existing = await self.application_repo.get_by_feishu_record(activity.id, record_id)
            if existing:
                if existing.status not in (
                    m.APPLICATION_PASSED, m.APPLICATION_FAILED,
                    m.APPLICATION_FINAL_PASSED, m.APPLICATION_FINAL_FAILED,
                ):
                    parsed = _apply_fields_to_dict(fields)
                    existing.employee_no = parsed["employee_no"] or existing.employee_no
                    existing.name = parsed["name"] or existing.name
                    existing.sequence = parsed["sequence"] or existing.sequence
                    existing.apply_level = parsed["apply_level"] or existing.apply_level
                    existing.self_evaluations = parsed["self_evaluations"] or existing.self_evaluations
                    existing.work_statements = parsed["work_statements"] or existing.work_statements
                    existing.attachments = parsed["attachments"] or existing.attachments
                    await self.application_repo.update(existing)
            else:
                await self.sync_apply_record_added(activity.id, record_id, fields)
                stats["applications_created"] += 1
        for application in await self.application_repo.list_all_by_activity(activity.id):
            if (
                application.feishu_record_id
                and application.feishu_record_id not in feishu_ids
                and application.status not in (
                    m.APPLICATION_PASSED, m.APPLICATION_FAILED,
                    m.APPLICATION_FINAL_PASSED, m.APPLICATION_FINAL_FAILED,
                )
            ):
                application.is_deleted = True
                await self.application_repo.update(application)
                stats["applications_removed"] += 1

        if activity.vote_table_id:
            try:
                vote_records = await bc.list_all_records(
                    activity.feishu_app_token, activity.vote_table_id
                )
            except bc.TitleReviewBitableError as exc:
                stats["errors"].append(f"拉取投票表失败: {exc}")
            else:
                for item in vote_records:
                    record_id = str(item.get("record_id") or "")
                    fields = item.get("fields") or {}
                    if not fields:
                        continue
                    try:
                        await self.sync_vote_record(activity.id, record_id, fields)
                        stats["votes_updated"] += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("对账同步投票行失败: record_id=%s error=%s", record_id, exc)
        await _audit(
            self.session,
            action="hr.title.reconcile",
            resource_type="title_review_activity",
            resource_id=activity.id,
            extra=stats,
        )
        return stats

    # ─── 校验辅助 ───

    @staticmethod
    def _ensure_draft(activity: m.TitleReviewActivity, field: str) -> None:
        if activity.status != m.ACTIVITY_DRAFT:
            raise HTTPException(400, f"{field}仅配置中（draft）可修改，当前：{activity.status}")
