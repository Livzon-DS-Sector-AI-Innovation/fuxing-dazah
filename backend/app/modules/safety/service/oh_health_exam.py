"""职业健康体检 Service — CRUD / AI 解析入口 / 人工覆盖结论留痕 / 随访联动。

对齐 backend-design.md §5.1：
- 所有 create/update/delete/override 走 _audit；
- UPDATE/DELETE 后 select re-fetch（async 铁律）；
- INSERT 后 flush 即可返回；
- 覆盖结论留痕（ai_override_notes + notes 追加「人工覆盖 by xxx」）；
- 联动 person.last_exam_*（调 OhPersonService.sync_from_exam）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    OhExamApplication,
    OhFollowup,
    OhHealthExam,
    OhPerson,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas.oh_health_exams import (
    OhAiConclusion,
    OhHealthExamCreate,
    OhHealthExamUpdate,
)
from app.modules.safety.service._helpers import audit_log, json_safe

logger = logging.getLogger(__name__)

# 异常结论集（统计 abnormal 用，含人工覆盖结论）
_ABNORMAL_CONCLUSIONS = {
    OhAiConclusion.ABNORMAL_OTHER.value,
    OhAiConclusion.CONTRAINDICATED.value,
    OhAiConclusion.SUSPECTED_OD.value,
    OhAiConclusion.OD_DIAGNOSED.value,
    OhAiConclusion.RE_EXAMINATION.value,
}

# 申请体检类型（中文原文）→ 体检记录标准枚举
# Q1 用户决策：申请表「转岗体检」本质是岗位体检 → periodic（在岗期间）；「离岗体检」→ post_employment
_EXAM_TYPE_FROM_APPLICATION = {
    "转岗体检": "periodic",
    "离岗体检": "post_employment",
}

# 体检记录标准枚举 → Bitable 体检记录表「体检类型」选项标签（回写用）
_EXAM_TYPE_LABEL = {
    "pre_employment": "岗前",
    "periodic": "在岗期间",
    "post_employment": "离岗",
    "transfer": "转岗",
    "emergency": "应急",
}


class OhHealthExamService:
    """职业健康体检服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    async def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await audit_log(
            self.session,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            old_value=json_safe(old_value),
            new_value=json_safe(new_value),
            extra=json_safe(extra),
        )

    # ── CRUD ──

    async def get_exams(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        exam_type: str | None = None,
        department: str | None = None,
        ai_conclusion: str | None = None,
        ai_parse_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhHealthExam], int]:
        """获取体检列表（筛选 + keyword + 分页）"""
        return await self.repo.get_health_exams(
            skip,
            limit,
            status,
            exam_type,
            department,
            keyword,
            ai_conclusion,
            ai_parse_status,
        )

    async def get_exam(self, exam_id: uuid.UUID) -> OhHealthExam | None:
        """获取体检详情"""
        return await self.repo.get_health_exam_by_id(exam_id)

    async def create_exam(
        self,
        data: OhHealthExamCreate,
        *,
        user_id: uuid.UUID | None = None,
    ) -> OhHealthExam:
        """创建体检记录（联动人员汇总表 last_exam_*）"""
        create_data = data.model_dump(mode="python")
        item = await self.repo.create_health_exam(create_data)
        await self._audit(
            "create", "oh_health_exam", resource_id=item.id,
            user_id=user_id, new_value=create_data,
        )
        await self._sync_person(item)
        return item

    async def update_exam(
        self,
        exam_id: uuid.UUID,
        data: OhHealthExamUpdate,
        *,
        user_id: uuid.UUID | None = None,
    ) -> OhHealthExam | None:
        """更新体检记录（联动人员汇总表 last_exam_*）"""
        update_data = {
            k: v for k, v in data.model_dump(exclude_unset=True, mode="python").items()
            if v is not None
        }
        if not update_data:
            return await self.get_exam(exam_id)
        item = await self.repo.update_health_exam(exam_id, update_data)
        if not item:
            return None
        await self._audit(
            "update", "oh_health_exam", resource_id=exam_id,
            user_id=user_id, new_value=update_data,
        )
        await self._sync_person(item)
        return item

    async def delete_exam(
        self,
        exam_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> bool:
        """删除体检记录（软删除，清 exam_no/feishu_record_id 唯一键）"""
        result = await self.repo.delete_health_exam(exam_id)
        if result:
            await self._audit("delete", "oh_health_exam", resource_id=exam_id, user_id=user_id)
        return result

    async def _sync_person(self, exam: OhHealthExam) -> None:
        """体检记录变更 → 联动 person.last_exam_*（调 oh_person service，失败不阻塞）"""
        if not exam.exam_date:
            return
        try:
            from app.modules.safety.service.oh_person import OhPersonService

            await OhPersonService(self.session).sync_from_exam(exam.id)
        except Exception:
            logger.exception("体检记录联动人员汇总表失败: exam=%s", exam.id)

    # ── AI 工作流①（委托 OhAIService，主体 ticket 04 实现）──

    async def run_ai_parse(
        self,
        exam_id: uuid.UUID,
        *,
        channel: str = "system",
    ) -> OhHealthExam | None:
        """手动触发/重试体检报告 AI 解析。

        委托 OhAIService.parse_exam_report（scenario=oh_exam_report_parsing，
        channel=system/web 由调用方传入）。
        """
        exam = await self.get_exam(exam_id)
        if not exam:
            return None
        await self._audit(
            "parse", "oh_health_exam", resource_id=exam_id, extra={"channel": channel},
        )
        from app.modules.safety.service.oh_ai import OhAIService

        return await OhAIService(self.session).parse_exam_report(exam_id, channel=channel)

    # ── 覆盖结论（留痕）──

    async def override_conclusion(
        self,
        exam_id: uuid.UUID,
        *,
        override_conclusion: OhAiConclusion | str,
        notes: str | None = None,
        user_id: uuid.UUID | None = None,
        user_name: str | None = None,
    ) -> OhHealthExam | None:
        """人工覆盖 AI 结论（留痕）。

        覆盖值同时写入 ai_conclusion（生效结论）与 override_conclusion（覆盖标记）；
        原 AI 结论 + 覆盖说明写入 ai_override_notes；notes 追加「人工覆盖 by xxx」。
        """
        exam = await self.get_exam(exam_id)
        if not exam:
            return None
        value = (
            override_conclusion.value
            if isinstance(override_conclusion, OhAiConclusion)
            else str(override_conclusion)
        )
        original = exam.ai_conclusion
        who = user_name or (str(user_id) if user_id else "unknown")
        trail = f"【人工覆盖 by {who}】原AI结论={original or '无'}"
        if notes:
            trail += f"；说明：{notes}"
        update_data: dict[str, Any] = {
            "ai_conclusion": value,
            "override_conclusion": value,
            "override_by": user_id,
            "override_at": datetime.now(UTC),
            "ai_override_notes": trail,
            "notes": f"{exam.notes}\n{trail}" if exam.notes else trail,
        }
        item = await self.repo.update_health_exam(exam_id, update_data)
        if item:
            await self._audit(
                "override", "oh_health_exam", resource_id=exam_id, user_id=user_id,
                old_value={"ai_conclusion": original},
                new_value={"override_conclusion": value, "notes": notes},
            )
            # 覆盖结论生效 → 联动人员汇总表「最后体检结论」（失败不阻塞）
            await self._sync_person(item)
        return item

    # ── 统计 ──

    async def get_stats(self) -> dict[str, Any]:
        """体检统计：total/abnormal/contraindicated/pending_parse + by_category"""
        base = select(OhHealthExam).where(OhHealthExam.is_deleted == False)  # noqa: E712
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        pending_parse = await self.session.scalar(
            select(func.count())
            .select_from(OhHealthExam)
            .where(
                OhHealthExam.is_deleted == False,  # noqa: E712
                OhHealthExam.ai_parse_status == "pending",
            )
        )
        abnormal = await self.session.scalar(
            select(func.count())
            .select_from(OhHealthExam)
            .where(
                OhHealthExam.is_deleted == False,  # noqa: E712
                or_(
                    OhHealthExam.ai_conclusion.in_(_ABNORMAL_CONCLUSIONS),
                    OhHealthExam.override_conclusion.in_(_ABNORMAL_CONCLUSIONS),
                ),
            )
        )
        contraindicated = await self.session.scalar(
            select(func.count())
            .select_from(OhHealthExam)
            .where(
                OhHealthExam.is_deleted == False,  # noqa: E712
                or_(
                    OhHealthExam.ai_conclusion == OhAiConclusion.CONTRAINDICATED.value,
                    OhHealthExam.override_conclusion == OhAiConclusion.CONTRAINDICATED.value,
                ),
            )
        )
        category_rows = (
            await self.session.execute(
                select(OhHealthExam.exam_type, func.count())
                .where(OhHealthExam.is_deleted == False)  # noqa: E712
                .group_by(OhHealthExam.exam_type)
            )
        ).all()
        by_category = {k: int(v) for k, v in category_rows}
        return {
            "total": int(total or 0),
            "abnormal": int(abnormal or 0),
            "contraindicated": int(contraindicated or 0),
            "pending_parse": int(pending_parse or 0),
            "by_category": by_category,
        }

    # ── 随访联动 ──

    async def get_followups(self, exam_id: uuid.UUID) -> list[OhFollowup]:
        """该体检的异常随访列表"""
        return await self.repo.get_oh_followups_by_exam(exam_id)

    # ── 转岗联动（被 OhTransferService 调用）──

    async def create_draft_from_application(
        self, application_id: uuid.UUID
    ) -> OhHealthExam:
        """从转岗/离岗申请自动创建体检登记（工作流②联动）。

        体检类型=转岗体检→periodic（Q1：岗位体检）/离岗体检→post_employment（映射标准枚举），
        流程状态=pending，person_id 按姓名+身份证匹配 oh_persons。
        """
        application = await self.session.get(OhExamApplication, application_id)
        if not application or application.is_deleted:
            raise ValueError("体检申请不存在")
        exam_type = _EXAM_TYPE_FROM_APPLICATION.get(
            application.exam_type or "", application.exam_type or "periodic"
        )
        person = await self.repo.get_oh_person_by_name_idcard(
            application.employee_name or "", application.id_card_no
        )
        item = OhHealthExam(
            source="manual",
            employee_name=application.employee_name or "未填写",
            id_card_no=application.id_card_no,
            person_id=person.id if person else None,
            department=application.department,
            position=application.position,
            exam_type=exam_type,
            status="pending",
            ai_parse_status="pending",
        )
        self.session.add(item)
        await self.session.flush()
        application.created_exam_id = item.id
        await self._audit(
            "create", "oh_health_exam", resource_id=item.id,
            extra={"from_application": str(application_id)},
        )
        return item

    # ── 来源表联动（D7：新员工登记 / 转岗离岗申请 created → 自动建体检登记）──

    async def get_exam_by_source(
        self, source_table: str, source_record_id: str
    ) -> OhHealthExam | None:
        """按来源表 + 来源记录 ID 查体检记录（活行，走 uq_oh_exams_source 索引）"""
        return await self.repo.get_health_exam_by_source(source_table, source_record_id)

    async def create_from_source(
        self,
        source_table: str,
        source_record_id: str,
        *,
        name: str,
        id_card_no: str | None = None,
        department: str | None = None,
        job_position: str | None = None,
        exam_type: str,
        registered_at: datetime | None = None,
        raw_conclusion_advice: str | None = None,
        transfer_date: datetime | None = None,
        leave_date: datetime | None = None,
        source_payload: dict[str, Any] | None = None,
        sync_bitable: bool = True,
    ) -> OhHealthExam:
        """来源表 created → 自动建体检登记（D7，幂等）。

        新员工登记表（new_employee → exam_type=pre_employment）与转岗离岗申请
        （exam_application → periodic/post_employment）created 事件调用；
        - 流程状态=未体检（status=pending），姓名/身份证/部门/岗位/登记时间/检查结论+处理意见带入；
        - 写 source_table/source_record_id 溯源（uq_oh_exams_source 唯一索引幂等）；
        - 新员工登记查无此人 → 自动建档（Q3：oh_persons work_status=岗前 + Bitable 人员汇总表
          回写新记录，record_id 回填 feishu_record_id），体检记录 person_id 关联新档案；
        - 创建后回写 Bitable 体检记录表（Source Table/Source Record ID/流程状态=未体检，
          _set_sync_ignore 防循环），并把新 record_id 回填 feishu_record_id；
        - 同一来源记录重复调用直接返回现有记录（不重复建）。
        """
        # 1. 幂等：先按 source 键查活行（唯一索引兜底并发）
        existing = await self.repo.get_health_exam_by_source(source_table, source_record_id)
        if existing is not None:
            logger.info(
                "来源联动幂等命中，跳过创建: source_table=%s source_record_id=%s exam=%s",
                source_table, source_record_id, existing.id,
            )
            return existing

        payload = source_payload or {}
        person = await self.repo.get_oh_person_by_name_idcard(name, id_card_no)
        # Q3 用户决策：新员工登记 created 查无此人 → 自动建档（岗前），体检记录关联新档案；
        # 幂等由「先查 person 表 + source 键唯一索引 + Bitable 侧查重」三重保护
        if person is None and source_table == "new_employee":
            person = await self._create_person_from_new_employee(
                name, id_card_no, department, job_position, payload
            )

        # 检查结论+处理意见：分离字段优先（与镜像/AI①输入列一致），合并文本兜底
        exam_conclusion = payload.get("exam_conclusion")
        treatment_advice_raw = payload.get("treatment_advice_raw")
        if not exam_conclusion and raw_conclusion_advice:
            exam_conclusion = raw_conclusion_advice

        item = OhHealthExam(
            source="bitable",
            employee_name=name,
            id_card_no=id_card_no or payload.get("id_card_no"),
            person_id=person.id if person else None,
            department=department or payload.get("department"),
            position=job_position or payload.get("position"),
            gender=payload.get("gender"),
            marital_status=payload.get("marital_status"),
            phone=payload.get("phone"),
            exam_type=exam_type,
            status="pending",  # 流程状态=未体检
            ai_parse_status="pending",
            scheduled_date=registered_at or payload.get("scheduled_date"),
            exam_date=payload.get("exam_date"),
            exam_conclusion=exam_conclusion,
            treatment_advice_raw=treatment_advice_raw,
            notes=payload.get("notes"),
            source_table=source_table,
            source_record_id=source_record_id,
        )
        self.session.add(item)
        await self.session.flush()
        await self._audit(
            "create", "oh_health_exam", resource_id=item.id,
            extra={
                "source_table": source_table,
                "source_record_id": source_record_id,
                "transfer_date": transfer_date.isoformat() if transfer_date else None,
                "leave_date": leave_date.isoformat() if leave_date else None,
            },
        )
        if sync_bitable:
            await self._sync_exam_to_bitable_registry(item)
        logger.info(
            "来源联动创建体检登记: source_table=%s source_record_id=%s exam=%s exam_type=%s",
            source_table, source_record_id, item.id, exam_type,
        )
        return item

    # ── 来源表人员建档（Q3：新员工登记 → oh_persons 档案 + Bitable 人员汇总表回写）──

    async def _create_person_from_new_employee(
        self,
        name: str,
        id_card_no: str | None,
        department: str | None,
        job_position: str | None,
        payload: dict[str, Any],
    ) -> OhPerson | None:
        """新员工登记 → 人员档案建档（Q3）。

        - 创建 oh_persons：name/id_card_no/department/position/phone/gender/marital_status/
          total_work_years（新员工表「总工龄」公式 "X年Y月" 折算），work_status=pre_employment（岗前）；
        - 「入职时间」/「工作年限（第一份工作入职时间）」为日期字段，OhPerson 无对应列 → 忽略
          （仅作 changed 事件触发条件，见 handler）；
        - 建档后回写 Bitable 人员汇总表新建记录（_set_sync_ignore 防循环），record_id 回填
          feishu_record_id；
        - 幂等：并发建档唯一键冲突 → 回查复用既有档案；Bitable 侧已建记录 → 复用不重复建。
        """
        from sqlalchemy.exc import IntegrityError

        data: dict[str, Any] = {"name": name, "work_status": "pre_employment"}
        if id_card_no:
            data["id_card_no"] = id_card_no
        if department:
            data["department"] = department
        if job_position:
            data["position"] = job_position
        if payload.get("phone"):
            data["phone"] = str(payload["phone"]).strip()
        if payload.get("gender"):
            data["gender"] = str(payload["gender"]).strip()
        if payload.get("marital_status"):
            data["marital_status"] = str(payload["marital_status"]).strip()
        total_work_years = payload.get("total_work_years")
        if total_work_years is not None:
            try:
                data["total_work_years"] = float(total_work_years)
            except (TypeError, ValueError):
                logger.warning("新员工总工龄解析失败，忽略: name=%s value=%r", name, total_work_years)
        try:
            person = await self.repo.create_oh_person(data)
        except IntegrityError:
            # 并发建档（不同 source 同人）→ 回查复用，不重复建
            await self.session.rollback()
            person = await self.repo.get_oh_person_by_name_idcard(name, id_card_no)
            if person is None:
                logger.warning("新员工建档唯一键冲突且回查失败: name=%s", name)
                return None
            logger.info("新员工建档唯一键冲突，复用既有档案: person=%s", person.id)
        if person is not None:
            await self._sync_new_person_to_bitable(person)
            logger.info(
                "新员工建档完成: person=%s work_status=%s total_work_years=%s",
                person.id, person.work_status, person.total_work_years,
            )
        return person

    async def _search_person_master_record(
        self, client: Any, person: OhPerson
    ) -> str | None:
        """Bitable 人员汇总表查重：按身份证号码精确查，无身份证 → 姓名（文本）兜底。

        查询异常返回 None（调用方降级为直接创建 + source 幂等保护 + 日志告警）。
        """
        try:
            if person.id_card_no:
                result = await client.search_records(
                    filter_info={
                        "conjunction": "and",
                        "conditions": [{
                            "field_name": "身份证号码",
                            "operator": "is",
                            "value": [person.id_card_no],
                        }],
                    },
                    page_size=10,
                )
            else:
                result = await client.search_records(
                    filter_info={
                        "conjunction": "and",
                        "conditions": [{
                            "field_name": "姓名（文本）",
                            "operator": "is",
                            "value": [person.name],
                        }],
                    },
                    page_size=10,
                )
        except Exception:
            logger.exception(
                "Bitable 人员汇总表按身份证/姓名查重失败（降级为直接创建）: person=%s", person.id
            )
            return None
        items = result.get("items") or []
        if not items:
            return None
        if len(items) > 1:
            logger.warning(
                "Bitable 人员汇总表查重命中多条，取首条: person=%s count=%d", person.id, len(items)
            )
        return items[0].get("record_id") or None

    async def _sync_new_person_to_bitable(self, person: OhPerson) -> None:
        """新员工建档 → 回写 Bitable 人员汇总表新建记录（Q3）。

        - 字段：姓名（文本）/身份证号码/岗位/性别/手机号码/婚姻状况/在岗状态=岗前；
          人员汇总表无独立「部门」字段（部门经姓名人员字段联动）→ 不写入，仅日志；
        - 幂等：先按身份证/姓名查已建记录，命中则复用 record_id 不重复建；
        - 创建后 _set_sync_ignore(record_id, ttl=30) 防 created/changed 事件循环，
          record_id 回填 person.feishu_record_id；
        - env 未配置静默跳过；调用失败仅告警，不阻塞平台建档。
        """
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("oh", "person_master")
        if conn is None or conn.status == "disabled":
            return
        app_token, table_id = conn.app_token, conn.table_id
        try:
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient
            from app.modules.safety.feishu.bitable_handler import _set_sync_ignore

            client = SafetyBitableClient(app_token=app_token, table_id=table_id)
            existing_record_id = await self._search_person_master_record(client, person)
            if existing_record_id:
                # Bitable 侧已建过（如并发/补跑）→ 复用，不重复建
                person.feishu_record_id = existing_record_id
                await self.session.flush()
                logger.warning(
                    "新员工建档 Bitable 人员汇总表已存在记录，复用（未新建）: person=%s record_id=%s",
                    person.id, existing_record_id,
                )
                return
            fields: dict[str, Any] = {
                "姓名（文本）": person.name,
                "在岗状态": "岗前",
            }
            if person.id_card_no:
                fields["身份证号码"] = person.id_card_no
            if person.position:
                fields["岗位"] = person.position
            if person.gender:
                fields["性别"] = person.gender
            if person.phone:
                fields["手机号码"] = person.phone
            if person.marital_status:
                fields["婚姻状况"] = person.marital_status
            if person.department:
                logger.info(
                    "新员工建档：人员汇总表无独立部门字段（姓名.部门经人员字段联动），部门不随建档写入: "
                    "person=%s department=%s",
                    person.id, person.department,
                )
            created = await client.create_record(fields=fields)
            record_id = (created or {}).get("record_id")
            if not record_id:
                logger.warning("Bitable 人员汇总表创建返回空 record_id: person=%s", person.id)
                return
            await _set_sync_ignore(record_id, ttl=30)
            person.feishu_record_id = record_id
            await self.session.flush()
            logger.info(
                "新员工建档已回写 Bitable 人员汇总表: person=%s record_id=%s",
                person.id, record_id,
            )
        except Exception:
            logger.exception("Bitable 人员汇总表建档回写失败（不阻塞）: person=%s", person.id)

    async def _sync_exam_to_bitable_registry(self, exam: OhHealthExam) -> None:
        """回写 Bitable 体检记录表：来源联动创建的新登记（D7）。

        - 创建记录时带入 Source Table / Source Record ID / 流程状态=未体检 / 体检类型
          与姓名/身份证/部门/岗位/登记时间/检查结论/处理意见；
        - 创建后立刻 _set_sync_ignore(record_id, ttl=30) 防 created/changed 事件循环；
        - env 未配置或调用失败仅告警，不阻塞平台记录创建。
        """
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("oh", "exam_registry")
        if conn is None or conn.status == "disabled":
            return
        app_token, table_id = conn.app_token, conn.table_id
        try:
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient
            from app.modules.safety.feishu.bitable_handler import (
                _datetime_to_ms,
                _set_sync_ignore,
            )

            fields: dict[str, Any] = {
                "姓名": exam.employee_name,
                "流程状态": "未体检",
                "Source Table": exam.source_table or "",
                "Source Record ID": exam.source_record_id or "",
                "体检类型": _EXAM_TYPE_LABEL.get(exam.exam_type, exam.exam_type),
            }
            if exam.id_card_no:
                fields["身份证号码"] = exam.id_card_no
            if exam.department:
                fields["部门"] = exam.department
            if exam.position:
                fields["岗位"] = exam.position
            if exam.scheduled_date:
                fields["登记时间"] = _datetime_to_ms(exam.scheduled_date)
            if exam.exam_date:
                fields["体检时间"] = _datetime_to_ms(exam.exam_date)
            if exam.exam_conclusion:
                fields["检查结论"] = exam.exam_conclusion
            if exam.treatment_advice_raw:
                fields["处理意见"] = exam.treatment_advice_raw
            client = SafetyBitableClient(app_token=app_token, table_id=table_id)
            created = await client.create_record(fields=fields)
            record_id = (created or {}).get("record_id")
            if not record_id:
                logger.warning("Bitable 体检记录表创建返回空 record_id: exam=%s", exam.id)
                return
            await _set_sync_ignore(record_id, ttl=30)
            exam.feishu_record_id = record_id
            await self.session.flush()
            logger.info(
                "来源联动已回写 Bitable 体检记录表: exam=%s record_id=%s",
                exam.id, record_id,
            )
        except Exception:
            logger.exception("Bitable 体检记录表回写失败（不阻塞）: exam=%s", exam.id)

    async def soft_delete_exam_by_source(
        self, source_table: str, source_record_id: str
    ) -> bool:
        """按来源键软删体检记录（审批拒绝/取消/终止/撤回联动）。

        软删同时清空 source_table/source_record_id 唯一键（软删铁律：
        防「删→重建同来源」触发 uq_oh_exams_source 冲突）。
        """
        existing = await self.repo.get_health_exam_by_source(source_table, source_record_id)
        if existing is None:
            return False
        result = await self.session.execute(
            update(OhHealthExam)
            .where(
                OhHealthExam.id == existing.id,
                OhHealthExam.is_deleted == False,  # noqa: E712
            )
            .values(
                is_deleted=True,
                exam_no=None,
                feishu_record_id=None,
                source_table=None,
                source_record_id=None,
            )
        )
        if result.rowcount:
            await self._audit(
                "delete", "oh_health_exam", resource_id=existing.id,
                extra={"source_table": source_table, "source_record_id": source_record_id},
            )
            logger.info(
                "来源联动软删体检登记: source_table=%s source_record_id=%s exam=%s",
                source_table, source_record_id, existing.id,
            )
        return result.rowcount > 0

    async def ensure_exam_for_application(
        self, application_id: uuid.UUID
    ) -> OhHealthExam | None:
        """工作流②联动（D7）：needs_exam=True 时确保体检登记存在——更新已建登记，不重复新建。

        申请表 created 时已由 create_from_source 建体检记录（source_table=exam_application，
        source_record_id=feishu_record_id）；此处命中则仅更新体检类型/流程状态标记并返回；
        未命中（手工申请或并发竞态兜底）才新建。
        """
        application = await self.session.get(OhExamApplication, application_id)
        if not application or application.is_deleted:
            return None
        exam_type = _EXAM_TYPE_FROM_APPLICATION.get(
            application.exam_type or "", application.exam_type or "periodic"
        )
        if application.feishu_record_id:
            existing = await self.repo.get_health_exam_by_source(
                "exam_application", application.feishu_record_id
            )
            if existing is not None:
                # 差异分析更新已建登记（needs_exam 标记：流程状态=未体检 + 体检类型对齐），不新建
                if existing.exam_type != exam_type:
                    existing.exam_type = exam_type
                existing.status = "pending"
                await self.session.flush()
                logger.info(
                    "转岗差异分析复用已建体检登记（不新建）: application=%s exam=%s",
                    application_id, existing.id,
                )
                return existing
            return await self.create_from_source(
                "exam_application", application.feishu_record_id,
                name=application.employee_name or "未填写",
                id_card_no=application.id_card_no,
                department=application.department,
                job_position=application.position,
                exam_type=exam_type,
                registered_at=application.submitted_at,
                transfer_date=application.transfer_date,
                leave_date=application.leave_date,
            )
        return await self.create_draft_from_application(application_id)

    # ── Bitable 同步（ticket 03 handler 复用）──

    async def upsert_from_bitable(
        self, data: dict[str, Any], feishu_record_id: str
    ) -> OhHealthExam:
        """按 Bitable 记录 ID upsert（活行查重）"""
        existing = await self.repo.get_health_exam_by_feishu_id(feishu_record_id)
        if existing:
            data.pop("feishu_record_id", None)
            updated = await self.repo.update_health_exam(existing.id, data)
            if updated:
                return updated
            return existing
        return await self.repo.create_health_exam(
            {**data, "feishu_record_id": feishu_record_id}
        )

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        """Bitable 删除事件 → 软删除（清唯一键）"""
        existing = await self.repo.get_health_exam_by_feishu_id(feishu_record_id)
        if not existing:
            return False
        return await self.delete_exam(existing.id)

    async def get_latest_by_person(
        self, name: str, id_card_no: str | None
    ) -> OhHealthExam | None:
        """按姓名+身份证取最近一次体检（供工作流②）"""
        return await self.repo.get_latest_health_exam_by_person(name, id_card_no)
