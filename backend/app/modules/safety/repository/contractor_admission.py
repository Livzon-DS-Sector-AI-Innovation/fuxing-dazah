"""Safety database queries."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select

from app.modules.safety.models import (
    ContractorAdmission,
)
from app.modules.safety.repository.core import SafetyRepository


class ContractorAdmissionRepository(SafetyRepository):
    """相关方准入 repository。

    继承 SafetyRepository（本表专用方法 get_contractor_admission_by_feishu_id /
    create_contractor_admission / update_contractor_admission /
    soft_delete_contractor_admission_by_feishu_id 见上方 ContractorAdmission Operations 段）。
    """

    async def get_contractor_admission_by_id(
        self, admission_id: uuid.UUID
    ) -> ContractorAdmission | None:
        """按主键查询未删除记录（详情/AI 审核入口）。"""
        query = select(ContractorAdmission).where(
            ContractorAdmission.id == admission_id,
            ContractorAdmission.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_contractor_admission_list(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        related_party_type: str | None = None,
        submit_status: str | None = None,
        ai_review_status: str | None = None,
        ai_conclusion: str | None = None,
        keyword: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[ContractorAdmission], int]:
        """相关方准入列表（筛选 + 分页 + 排序），返回 (items, total)。

        - ai_conclusion 匹配 ai_review_result.overall_conclusion（审核通过/需补充完善/审核不通过）
        - keyword 模糊匹配 company_name / contact_person
        - sort_by 白名单: entry_date / actual_complete_date / created_at / company_name
        """
        base = ContractorAdmission.is_deleted.is_(False)
        query = select(ContractorAdmission).where(base)
        count_query = select(func.count(ContractorAdmission.id)).where(base)

        conditions = []
        if related_party_type:
            conditions.append(
                ContractorAdmission.related_party_type == related_party_type
            )
        if submit_status:
            conditions.append(ContractorAdmission.submit_status == submit_status)
        if ai_review_status:
            conditions.append(ContractorAdmission.ai_review_status == ai_review_status)
        if ai_conclusion:
            conditions.append(
                ContractorAdmission.ai_review_result["overall_conclusion"].astext
                == ai_conclusion
            )
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(
                    ContractorAdmission.company_name.ilike(like),
                    ContractorAdmission.contact_person.ilike(like),
                )
            )
        for cond in conditions:
            query = query.where(cond)
            count_query = count_query.where(cond)

        sort_cols = {
            "entry_date": ContractorAdmission.entry_date,
            "actual_complete_date": ContractorAdmission.actual_complete_date,
            "created_at": ContractorAdmission.created_at,
            "company_name": ContractorAdmission.company_name,
        }
        col = sort_cols.get(sort_by or "", ContractorAdmission.created_at)
        query = query.order_by(
            col.asc() if sort_order == "asc" else col.desc()
        )

        total = await self.session.scalar(count_query) or 0
        result = await self.session.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all()), total

    async def get_contractor_admission_stats(self) -> dict[str, Any]:
        """相关方准入统计（精确计数，不做全表拉取估算）。"""
        base = ContractorAdmission.is_deleted.is_(False)

        async def _group_counts(column: Any) -> dict[str, int]:
            rows = (
                await self.session.execute(
                    select(column, func.count(ContractorAdmission.id))
                    .where(base)
                    .group_by(column)
                )
            ).all()
            return {
                str(k) if k is not None else "未知": int(v) for k, v in rows
            }

        total = (
            await self.session.scalar(
                select(func.count(ContractorAdmission.id)).where(base)
            )
        ) or 0
        return {
            "total": total,
            "by_ai_review_status": await _group_counts(
                ContractorAdmission.ai_review_status
            ),
            "by_related_party_type": await _group_counts(
                ContractorAdmission.related_party_type
            ),
            "by_submit_status": await _group_counts(
                ContractorAdmission.submit_status
            ),
        }


