"""职业健康岗位危害台账 Service — 查询 / 岗位危害因素反查 / Bitable 同步。

对齐 backend-design.md §5.5：
- get_hazards_by_position 供工作流②（OhTransferService）取岗位危害因素。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import OhPosition
from app.modules.safety.repository import SafetyRepository


class OhPositionService:
    """岗位危害因素台账服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    async def get_positions(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        hazard_factors_status: str | None = None,
    ) -> tuple[list[OhPosition], int]:
        """岗位危害台账列表（筛选 + 分页）"""
        return await self.repo.get_oh_positions(
            skip, limit, department=department, hazard_factors_status=hazard_factors_status
        )

    async def get_position(self, position_id: uuid.UUID) -> OhPosition | None:
        """岗位详情"""
        return await self.repo.get_oh_position_by_id(position_id)

    async def get_hazards_by_position(
        self, department: str | None, position: str | None
    ) -> list[str]:
        """按部门+岗位反查危害因素标准名列表（供工作流②，无匹配返回 []）"""
        if not department or not position:
            return []
        row = await self.repo.get_oh_position_by_dept_position(department, position)
        if row is None or not row.hazard_factors:
            return []
        return list(row.hazard_factors)

    # ── Bitable 同步（ticket 03 handler 复用）──

    async def upsert_from_bitable(self, data: dict[str, Any], feishu_record_id: str) -> OhPosition:
        existing = await self.repo.get_oh_position_by_feishu_id(feishu_record_id)
        if existing:
            data.pop("feishu_record_id", None)
            updated = await self.repo.update_oh_position(existing.id, data)
            if updated:
                return updated
            return existing
        return await self.repo.create_oh_position(
            {**data, "feishu_record_id": feishu_record_id}
        )

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        existing = await self.repo.get_oh_position_by_feishu_id(feishu_record_id)
        if not existing:
            return False
        return await self.repo.delete_oh_position(existing.id)
