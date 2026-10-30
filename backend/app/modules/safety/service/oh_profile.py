"""职业健康个人完整档案聚合 Service — 单人五源聚合（供档案页）。

双模式（与人员/体检台账同一开关 SAFETY_OH_DIRECT_ENABLED，DB 配置中心）：
- 直读模式（当前线上形态，镜像表已清空）：人员/体检走 oh_direct.ledger
  Bitable 直读行（id=recXXX），参训/申请走 PG（姓名关联），违章走
  Bitable 直读；随访为平台侧 PG 表、无直读源，恒空展示；
- 镜像模式（回退）：人员按 UUID/feishu_record_id 解析，体检/随访走
  repo person_id 强键。

区块与身份匹配口径（无新外键，全部运行时匹配）：
- 体检：直读=姓名等值+身份证兜底排除；镜像=person_id；
- 转岗离岗申请：employee_name 等值 + 身份证明确不相等才排除（空不算失配）；
- 培训参训：person_name（签到表 OCR 转录，姓名级即上限）；
- 违章：person_open_id == person.open_id 强匹配优先；双方都有 open_id 而
  不同 = 同名不同人直接排除；缺任一方 open_id 才姓名兜底（逐行标注）。

降级：违章源（Bitable 直读）失败/未接入置 None + errors[] 标注，不阻塞
其余区块（overview 采集器同口径）。共用 AsyncSession 的 DB 查询串行，
与违章网络拉取并行。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import OhExamApplication, OhPerson, TrainingAttendee
from app.modules.safety.repository import SafetyRepository

logger = logging.getLogger(__name__)


class OhProfileService:
    """职业健康个人完整档案聚合服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    # ── 人员解析（镜像模式）──

    async def _resolve_person(self, person_ref: str) -> OhPerson | None:
        """UUID 优先，feishu_record_id 兜底（直读行 id=recXXX 防呆）。"""
        base = select(OhPerson).where(OhPerson.is_deleted == False)  # noqa: E712
        try:
            person_id = uuid.UUID(person_ref)
        except ValueError:
            person_id = None
        if person_id is not None:
            person = (
                await self.session.execute(base.where(OhPerson.id == person_id))
            ).scalar_one_or_none()
            if person is not None:
                return person
        return (
            await self.session.execute(
                base.where(OhPerson.feishu_record_id == person_ref)
            )
        ).scalar_one_or_none()

    # ── 各源采集 ──

    async def _get_direct_exams(self, person: Any) -> list[Any]:
        """直读模式体检行：姓名等值 + 身份证明确不相等才排除。"""
        from app.modules.safety.service.oh_direct import ledger

        name = str(person.mapped.get("name") or "")
        id_card = person.mapped.get("id_card_no") or None
        hits: list[Any] = []
        for e in await ledger.fetch_exams():
            m = e.mapped
            if not name or m.get("employee_name") != name:
                continue
            exam_id_card = m.get("id_card_no")
            if id_card and exam_id_card and exam_id_card != id_card:
                continue
            hits.append(e)
        # exam_date 缺失行排最后（None 与 datetime 混排会 TypeError，垫哨兵）
        zero = datetime.min.replace(tzinfo=UTC)
        hits.sort(key=lambda e: e.mapped.get("exam_date") or zero, reverse=True)
        return hits

    async def _get_applications(self, person: OhPerson) -> list[OhExamApplication]:
        """转岗/离岗申请（姓名等值；身份证明确不相等才排除）。"""
        conds = [
            OhExamApplication.is_deleted == False,  # noqa: E712
            OhExamApplication.employee_name == person.name,
        ]
        if person.id_card_no:
            conds.append(
                or_(
                    OhExamApplication.id_card_no.is_(None),
                    OhExamApplication.id_card_no == "",
                    OhExamApplication.id_card_no == person.id_card_no,
                )
            )
        res = await self.session.execute(
            select(OhExamApplication)
            .where(*conds)
            .order_by(
                OhExamApplication.submitted_at.desc().nulls_last(),
                OhExamApplication.created_at.desc(),
            )
        )
        return list(res.scalars().all())

    async def _get_trainings(self, person: OhPerson) -> list[TrainingAttendee]:
        """参训人明细（OCR 姓名等值，held_at 倒序）。"""
        res = await self.session.execute(
            select(TrainingAttendee)
            .where(
                TrainingAttendee.is_deleted == False,  # noqa: E712
                TrainingAttendee.person_name == person.name,
            )
            .order_by(TrainingAttendee.held_at.desc().nulls_last())
        )
        return list(res.scalars().all())

    async def _get_violations(
        self, person: OhPerson
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        """违章行（Bitable 直读）→ (命中行, 匹配口径)。

        返回 (None, None) = 域未接入（调用方标注降级，与空列表区分）。
        """
        from app.modules.safety.service import domain_pages

        rows = await domain_pages.fetch_kind_rows("training-behavior", "violation")
        if rows is None:
            return None, None
        hits: list[dict[str, Any]] = []
        bases: set[str] = set()
        for row in rows:
            name = str(row.get("person_name") or "")
            row_oid = row.get("person_open_id")
            if person.open_id and row_oid:
                # 双方都有 open_id：选人控件是真实飞书用户，不同 open_id =
                # 确定不同人（同名不误配），不走姓名兜底。
                if row_oid == person.open_id:
                    hits.append({**row, "match_basis": "open_id"})
                    bases.add("open_id")
                continue
            if name and name == person.name:
                hits.append({**row, "match_basis": "name"})
                bases.add("name")
        basis: str | None = None
        if len(bases) == 1:
            basis = next(iter(bases))
        elif bases:
            basis = "mixed"
        return hits, basis

    async def _get_db_sources(
        self, person: Any, *, direct: bool
    ) -> tuple[list[Any], list[Any], list[OhExamApplication], list[TrainingAttendee]]:
        """共用 session 的查询串行；直读模式体检走 ledger、随访无直读源。"""
        if direct:
            exams: list[Any] = await self._get_direct_exams(person)
            followups: list[Any] = []
        else:
            exams = await self.repo.get_oh_exams_by_person(person.id)
            followups = await self.repo.get_oh_followups_by_person(person.id)
        applications = await self._get_applications(person)
        trainings = await self._get_trainings(person)
        return exams, followups, applications, trainings

    # ── 聚合入口 ──

    async def build_profile(self, person_ref: str) -> dict[str, Any] | None:
        """五源聚合；人员不存在返回 None，单源失败降级进 errors。

        直读模式：person_ref=Bitable record_id，人员/体检走 ledger 直读行；
        镜像模式：UUID/feishu_record_id 解析，体检/随访走 repo person_id。
        """
        from app.modules.safety.service.oh_direct import config as od_config

        direct = od_config.direct_enabled()
        person: Any = None
        if direct:
            from app.modules.safety.service.oh_direct import ledger

            persons = await ledger.fetch_persons()
            person = next((p for p in persons if p.id == person_ref), None)
        else:
            person = await self._resolve_person(person_ref)
        if person is None:
            return None
        db_task = self._get_db_sources(person, direct=direct)
        violation_task = self._get_violations(person)
        (db_result, violation_result) = await asyncio.gather(
            db_task, violation_task, return_exceptions=True
        )

        errors: list[str] = []
        if isinstance(db_result, Exception):
            logger.warning(
                "档案DB区块采集失败 person=%s", person.id, exc_info=db_result
            )
            errors.append(f"db_sources: {db_result.__class__.__name__}")
            exams: list[Any] = []
            followups: list[Any] = []
            applications: list[OhExamApplication] = []
            trainings: list[TrainingAttendee] = []
        else:
            exams, followups, applications, trainings = db_result

        if isinstance(violation_result, Exception):
            logger.warning(
                "档案违章源采集失败 person=%s", person.id, exc_info=violation_result
            )
            errors.append(f"violations: {violation_result.__class__.__name__}")
            violations = None
            violation_basis = None
        else:
            violations, violation_basis = violation_result

        return {
            "person": person,
            "exams": exams,
            "followups": followups,
            "applications": applications,
            "trainings": trainings,
            "violations": violations,
            "match_notes": {
                "trainings": "name",
                "violations": violation_basis,
            },
            "errors": errors,
        }
