"""Safety business workflows."""

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.models import (
    SpecialOperationPermit,
    SpecialOperationPersonnel,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    SpecialOperationPermitCreate,
    SpecialOperationPermitUpdate,
    SpecialOperationPersonnelCreate,
    SpecialOperationPersonnelUpdate,
)
from app.modules.safety.service._helpers import audit_log

logger = logging.getLogger(__name__)


class SpecialOperationService:
    """特殊作业管理业务服务

    两大核心能力：
    1. 特殊作业人员资质管理
    2. 特殊作业票管理（含工作流状态机）
    """

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
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )

    @staticmethod
    def _cleanup_file(file_path: str | None) -> None:
        """Delete a single file from MinIO or local disk."""
        if not file_path:
            return
        try:
            if minio_enabled():
                try:
                    delete_object("safety", file_path)
                except Exception:
                    pass
            else:
                abs_path = os.path.abspath(file_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
        except OSError:
            pass

    # ==================== 人员资质 CRUD ====================

    async def get_personnel(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        certificate_type: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SpecialOperationPersonnel], int]:
        """获取特殊作业人员资质列表"""
        return await self.repo.get_special_operation_personnel(
            skip, limit, status, certificate_type, department, keyword
        )

    async def get_personnel_by_id(
        self, personnel_id: uuid.UUID
    ) -> SpecialOperationPersonnel | None:
        """获取人员资质详情"""
        return await self.repo.get_special_operation_personnel_by_id(personnel_id)

    async def create_personnel(
        self, data: SpecialOperationPersonnelCreate
    ) -> SpecialOperationPersonnel:
        """创建人员资质"""
        create_data = data.model_dump()
        item = await self.repo.create_special_operation_personnel(create_data)
        await self._audit("create", "special_operation_personnel", resource_id=item.id)
        return item

    async def update_personnel(
        self, personnel_id: uuid.UUID, data: SpecialOperationPersonnelUpdate
    ) -> SpecialOperationPersonnel | None:
        """更新人员资质"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_special_operation_personnel(
            personnel_id, update_data
        )
        if item:
            await self._audit("update", "special_operation_personnel", resource_id=personnel_id)
        return item

    async def delete_personnel(self, personnel_id: uuid.UUID) -> bool:
        """删除人员资质"""
        personnel = await self.repo.get_special_operation_personnel_by_id(personnel_id)
        result = await self.repo.delete_special_operation_personnel(personnel_id)
        if result:
            if personnel:
                self._cleanup_file(personnel.certificate_file_path)
            await self._audit("delete", "special_operation_personnel", resource_id=personnel_id)
        return result

    # ==================== 作业票 CRUD ====================

    async def get_permits(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        operation_type: str | None = None,
        operation_level: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SpecialOperationPermit], int]:
        """获取特殊作业票列表"""
        return await self.repo.get_special_operation_permits(
            skip, limit, status, operation_type, operation_level, keyword
        )

    async def get_permit(
        self, permit_id: uuid.UUID
    ) -> SpecialOperationPermit | None:
        """获取作业票详情"""
        return await self.repo.get_special_operation_permit_by_id(permit_id)

    async def create_permit(
        self, data: SpecialOperationPermitCreate
    ) -> SpecialOperationPermit:
        """创建作业票"""
        create_data = data.model_dump()
        item = await self.repo.create_special_operation_permit(create_data)
        await self._audit("create", "special_operation_permit", resource_id=item.id)
        return item

    async def update_permit(
        self, permit_id: uuid.UUID, data: SpecialOperationPermitUpdate
    ) -> SpecialOperationPermit | None:
        """更新作业票"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_special_operation_permit(permit_id, update_data)
        if item:
            await self._audit("update", "special_operation_permit", resource_id=permit_id)
        return item

    async def delete_permit(self, permit_id: uuid.UUID) -> bool:
        """删除作业票"""
        result = await self.repo.delete_special_operation_permit(permit_id)
        if result:
            await self._audit("delete", "special_operation_permit", resource_id=permit_id)
        return result

    # ==================== 作业票工作流 ====================

    async def submit_permit(self, permit_id: uuid.UUID) -> SpecialOperationPermit | None:
        """提交作业票（草稿→已提交）"""
        permit = await self.repo.get_special_operation_permit_by_id(permit_id)
        if not permit or permit.status != "draft":
            return None
        return await self.repo.update_special_operation_permit(
            permit_id, {"status": "submitted"}
        )

    async def approve_permit(
        self, permit_id: uuid.UUID
    ) -> SpecialOperationPermit | None:
        """审批作业票（已提交→已审批）"""
        permit = await self.repo.get_special_operation_permit_by_id(permit_id)
        if not permit or permit.status != "submitted":
            return None
        return await self.repo.update_special_operation_permit(
            permit_id, {"status": "approved"}
        )

    async def reject_permit(
        self, permit_id: uuid.UUID, reason: str
    ) -> SpecialOperationPermit | None:
        """驳回作业票（已提交→已驳回）"""
        permit = await self.repo.get_special_operation_permit_by_id(permit_id)
        if not permit or permit.status != "submitted":
            return None
        return await self.repo.update_special_operation_permit(
            permit_id, {"status": "rejected", "rejection_reason": reason}
        )

    async def start_permit(
        self, permit_id: uuid.UUID
    ) -> SpecialOperationPermit | None:
        """开始作业（已审批→作业中）"""
        permit = await self.repo.get_special_operation_permit_by_id(permit_id)
        if not permit or permit.status != "approved":
            return None
        return await self.repo.update_special_operation_permit(
            permit_id,
            {"status": "in_progress", "actual_start_time": datetime.now()},
        )

    async def complete_permit(
        self, permit_id: uuid.UUID, method: str
    ) -> SpecialOperationPermit | None:
        """完工（作业中→已完工）"""
        permit = await self.repo.get_special_operation_permit_by_id(permit_id)
        if not permit or permit.status != "in_progress":
            return None
        return await self.repo.update_special_operation_permit(
            permit_id,
            {
                "status": "completed",
                "actual_end_time": datetime.now(),
                "completion_method": method,
            },
        )

    async def archive_permit(
        self, permit_id: uuid.UUID
    ) -> SpecialOperationPermit | None:
        """归档作业票（已完工→已归档）"""
        permit = await self.repo.get_special_operation_permit_by_id(permit_id)
        if not permit or permit.status != "completed":
            return None
        return await self.repo.update_special_operation_permit(
            permit_id, {"status": "archived"}
        )


# ==================== 安全知识库 Service ====================


