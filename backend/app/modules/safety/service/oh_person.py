"""职业健康人员汇总台账 Service — 台账 CRUD / 总表回填联动 / Bitable 同步。

对齐 backend-design.md §5.2：
- sync_from_exam：体检记录 → person.last_exam_* / exam_record_ids / hazard_factors；
- sync_hazard_factors_by_position：按岗位同步接触危害因素；
- Bitable 回写（最后体检结论/类别/时间 + 体检记录 link + 接触危害因素 +「是否已同步汇总表」）
  一律 _set_sync_ignore 防循环，Bitable 配置未配置（store 读取）或失败仅告警不阻塞；
- open_id → user_id 回填（IdentityResolver 本地查询，identity.users 无匹配静默跳过）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import OhHealthExam, OhPerson
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service._helpers import audit_log, json_safe

logger = logging.getLogger(__name__)

# 标准枚举 → Bitable「最后体检类别」单选标签
_EXAM_TYPE_LABELS = {
    "pre_employment": "岗前",
    "periodic": "在岗期间",
    "post_employment": "离岗",
    "transfer": "转岗",
    "emergency": "应急",
}

# Bitable 配置经配置中心 store 读取（DB 活行 → registry 默认）：
# - person_master 人员汇总表（总表回填）
# - exam_registry 体检记录表（「是否已同步汇总表」=是 回写）


class OhPersonService:
    """职业健康人员汇总台账服务"""

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

    # ── 查询 ──

    async def get_persons(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        position: str | None = None,
        hazard_exposure: str | None = None,
        last_exam_conclusion: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhPerson], int]:
        """台账列表（筛选 + keyword + 分页）"""
        return await self.repo.get_oh_persons(
            skip,
            limit,
            department=department,
            position=position,
            hazard_exposure=hazard_exposure,
            last_exam_conclusion=last_exam_conclusion,
            keyword=keyword,
        )

    async def get_person(self, person_id: uuid.UUID) -> OhPerson | None:
        """人员详情"""
        return await self.repo.get_oh_person_by_id(person_id)

    async def get_exams_by_person(self, person_id: uuid.UUID) -> list[OhHealthExam]:
        """该人员的体检记录链"""
        return await self.repo.get_oh_exams_by_person(person_id)

    async def get_followups_by_person(self, person_id: uuid.UUID) -> list:
        """该人员的异常随访（供详情展开）"""
        return await self.repo.get_oh_followups_by_person(person_id)

    async def get_stats(self) -> dict[str, Any]:
        """台账统计：按部门/岗位/在岗状态/最后体检结论/接害分布"""
        base = select(OhPerson).where(OhPerson.is_deleted == False)  # noqa: E712
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        hazard_exposed = await self.session.scalar(
            select(func.count())
            .select_from(OhPerson)
            .where(
                OhPerson.is_deleted == False,  # noqa: E712
                (OhPerson.hazard_exposure_years > 0) | (OhPerson.hazard_factors.is_not(None)),
            )
        )

        async def _group_counts(column) -> dict[str, int]:
            rows = await self.session.execute(
                select(column, func.count())
                .where(OhPerson.is_deleted == False)  # noqa: E712
                .group_by(column)
            )
            return {k: int(v) for k, v in rows.all()}

        return {
            "total": int(total or 0),
            "hazard_exposed": int(hazard_exposed or 0),
            "by_department": await _group_counts(OhPerson.department),
            "by_position": await _group_counts(OhPerson.position),
            "by_work_status": await _group_counts(OhPerson.work_status),
            "by_last_exam_conclusion": await _group_counts(OhPerson.last_exam_conclusion),
        }

    # ── 总表回填（核心联动）──

    async def sync_from_exam(self, exam_id: uuid.UUID) -> OhPerson | None:
        """体检记录 → 人员汇总表回填（核心联动）。

        last_exam_at/type/conclusion/summary + exam_record_ids 去重追加
        + hazard_factors 覆盖（非空时）+ open_id → user_id 回填（IdentityResolver 本地查询）
        + 体检记录标记 synced_to_summary=True
        + 回写 Bitable 人员汇总表（最后体检结论/类别/时间 + 体检记录 link + 接触危害因素）
          与体检记录表「是否已同步汇总表」=是（_set_sync_ignore 防循环；env 未配置静默跳过）。
        """
        exam = await self.session.get(OhHealthExam, exam_id)
        if not exam or exam.is_deleted:
            return None
        person = await self.repo.get_oh_person_by_name_idcard(
            exam.employee_name, exam.id_card_no
        )
        if not person:
            return None

        changed = False
        if exam.exam_date:
            person.last_exam_at = exam.exam_date
            changed = True
        if exam.exam_type:
            person.last_exam_type = exam.exam_type
            changed = True
        if exam.ai_conclusion:
            person.last_exam_conclusion = exam.ai_conclusion
            changed = True
        if exam.ai_interpretation:
            person.last_exam_summary = exam.ai_interpretation
            changed = True
        record_ids = list(person.exam_record_ids or [])
        if str(exam.id) not in record_ids:
            record_ids.append(str(exam.id))
            person.exam_record_ids = record_ids
            changed = True
        if exam.hazard_factors:
            person.hazard_factors = exam.hazard_factors
            changed = True

        # open_id → user_id 回填（Bitable 姓名人员字段的 open_id → identity.users.id）
        if person.open_id and not person.user_id:
            resolved_user_id = await self._resolve_user_id_by_open_id(person.open_id)
            if resolved_user_id:
                person.user_id = resolved_user_id
                changed = True

        if changed:
            await self.session.flush()

        # 平台侧同步标记（防重复触发；Bitable「是否已同步汇总表」由平台回写）
        if not exam.synced_to_summary:
            exam.synced_to_summary = True
            await self.session.flush()
        # flush 后 onupdate 列（updated_at）过期：select re-fetch 恢复 loaded
        # （async 铁律，防止调用方在响应序列化阶段访问 exam.updated_at 触发 MissingGreenlet）
        await self.session.scalar(
            select(OhHealthExam).where(OhHealthExam.id == exam.id)
        )

        await self._sync_bitable_person_master(person)
        await self._sync_bitable_exam_summary_flag(exam)
        return person

    async def _resolve_user_id_by_open_id(self, open_id: str) -> uuid.UUID | None:
        """open_id → identity.users.id（IdentityResolver 本地查询；失败返回 None 不阻塞）。"""
        try:
            from app.modules.safety.feishu.identity_resolver import IdentityResolver

            resolved = await IdentityResolver(self.session).resolve_by_user_id(open_id)
            if resolved and resolved.id:
                return uuid.UUID(str(resolved.id))
        except Exception:
            logger.exception("人员 user_id 回填失败（不阻塞）: open_id=%s", open_id)
        return None

    async def sync_hazard_factors_by_position(self, person_id: uuid.UUID) -> OhPerson | None:
        """按 person.position 从 oh_positions 同步危害因素（覆盖 person.hazard_factors）"""
        person = await self.repo.get_oh_person_by_id(person_id)
        if not person or not person.department or not person.position:
            return person
        row = await self.repo.get_oh_position_by_dept_position(
            person.department, person.position
        )
        if row is None or row.hazard_factors is None:
            return person  # 岗位未登记危害因素，不覆盖
        person.hazard_factors = row.hazard_factors
        await self.session.flush()
        await self._sync_bitable_person_master(person)
        return person

    async def manual_sync(self, person_id: uuid.UUID) -> OhPerson | None:
        """手动触发总表回填：取该人员最近一次体检 → sync_from_exam"""
        person = await self.repo.get_oh_person_by_id(person_id)
        if not person:
            return None
        latest = await self.repo.get_latest_health_exam_by_person(
            person.name, person.id_card_no, person_id=person.id
        )
        if latest is None:
            # 未关联 person_id 的体检（手工建单）按 姓名+身份证 兜底（与 sync_from_exam 同关联键）
            latest = await self.repo.get_latest_health_exam_by_person(
                person.name, person.id_card_no
            )
        if latest:
            await self.sync_from_exam(latest.id)
        return await self.repo.get_oh_person_by_id(person_id)

    # ── Bitable 回写（防循环）──

    async def _sync_bitable_person_master(self, person: OhPerson) -> None:
        """回写 Bitable 人员汇总表（最后体检时间/类别/结论 + 体检记录 link + 接触危害因素）。

        写回前 _set_sync_ignore(record_id, ttl=30) 防平台回写循环；
        Bitable 配置未配置或调用失败仅告警，不阻塞主流程。
        「体检记录」link 字段需要 Bitable record_id（feishu_record_id）而非平台 UUID，
        故按 exam_record_ids 逐条反查后回写。
        """
        if not person.feishu_record_id:
            return
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("oh", "person_master")
        if conn is None or conn.status == "disabled":
            return
        try:
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient
            from app.modules.safety.feishu.bitable_handler import _set_sync_ignore

            fields: dict[str, Any] = {}
            if person.last_exam_at:
                fields["最后一次体检时间"] = int(person.last_exam_at.timestamp() * 1000)
            if person.last_exam_type:
                label = _EXAM_TYPE_LABELS.get(person.last_exam_type)
                if label:
                    fields["最后体检类别"] = label
            if person.last_exam_conclusion:
                fields["最后体检结论"] = person.last_exam_conclusion
            if person.hazard_factors:
                fields["接触危害因素"] = list(person.hazard_factors)
            if person.exam_record_ids:
                link_records: list[dict[str, str]] = []
                for rid in person.exam_record_ids:
                    try:
                        exam_uuid = uuid.UUID(str(rid))
                    except (ValueError, TypeError):
                        continue
                    feishu_id = await self.session.scalar(
                        select(OhHealthExam.feishu_record_id).where(
                            OhHealthExam.id == exam_uuid,
                            OhHealthExam.is_deleted == False,  # noqa: E712
                        )
                    )
                    if feishu_id:
                        link_records.append({"record_id": feishu_id})
                if link_records:
                    fields["体检记录"] = link_records
            if not fields:
                return
            await _set_sync_ignore(person.feishu_record_id, ttl=30)
            client = SafetyBitableClient(
                app_token=conn.app_token, table_id=conn.table_id
            )
            await client.update_record(record_id=person.feishu_record_id, fields=fields)
        except Exception:
            logger.exception("Bitable 人员汇总表回写失败: person=%s", person.id)

    async def _sync_bitable_exam_summary_flag(self, exam: OhHealthExam) -> None:
        """回写体检记录表 Bitable「是否已同步汇总表」=是。

        写回前 _set_sync_ignore(record_id, ttl=30) 防平台回写循环；
        Bitable 配置未配置或调用失败仅告警，不阻塞主流程。
        """
        if not exam.feishu_record_id:
            return
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("oh", "exam_registry")
        if conn is None or conn.status == "disabled":
            return
        try:
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient
            from app.modules.safety.feishu.bitable_handler import _set_sync_ignore

            await _set_sync_ignore(exam.feishu_record_id, ttl=30)
            client = SafetyBitableClient(
                app_token=conn.app_token, table_id=conn.table_id
            )
            await client.update_record(
                record_id=exam.feishu_record_id,
                fields={"是否已同步汇总表": "是"},
            )
            logger.info(
                "体检记录「是否已同步汇总表」已回写: exam=%s record=%s",
                exam.id, exam.feishu_record_id,
            )
        except Exception:
            logger.exception("体检记录「是否已同步汇总表」回写失败: exam=%s", exam.id)

    # ── Bitable 同步（ticket 03 handler 复用）──

    async def upsert_from_bitable(self, data: dict[str, Any], feishu_record_id: str) -> OhPerson:
        existing = await self.repo.get_oh_person_by_feishu_id(feishu_record_id)
        if existing:
            data.pop("feishu_record_id", None)
            updated = await self.repo.update_oh_person(existing.id, data)
            if updated:
                return updated
            return existing
        return await self.repo.create_oh_person(
            {**data, "feishu_record_id": feishu_record_id}
        )

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        existing = await self.repo.get_oh_person_by_feishu_id(feishu_record_id)
        if not existing:
            return False
        result = await self.repo.delete_oh_person(existing.id)
        if result:
            await self._audit("delete", "oh_person", resource_id=existing.id)
        return result
