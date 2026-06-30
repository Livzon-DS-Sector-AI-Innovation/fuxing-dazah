"""Safety business workflows."""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    EhsChange,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    EhsChangeCreate,
    EhsChangeUpdate,
)
from app.modules.safety.service._helpers import audit_log

logger = logging.getLogger(__name__)


class EhsChangeService:
    """EHS变更管理业务服务（基于 T/CCSAS 007-2020）"""

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

    # ── CRUD ──

    async def get_ehs_changes(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        change_type: str | None = None,
        change_grade: str | None = None,
        change_duration: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[EhsChange], int]:
        """获取EHS变更列表"""
        return await self.repo.get_ehs_changes(
            skip, limit, status, change_type, change_grade, change_duration, department, keyword
        )

    async def get_ehs_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """获取EHS变更详情"""
        return await self.repo.get_ehs_change_by_id(change_id)

    async def create_ehs_change(self, data: EhsChangeCreate) -> EhsChange:
        """创建EHS变更"""
        create_data = data.model_dump()
        item = await self.repo.create_ehs_change(create_data)
        await self._audit("create", "ehs_change", resource_id=item.id)
        return item

    async def update_ehs_change(
        self, change_id: uuid.UUID, data: EhsChangeUpdate
    ) -> EhsChange | None:
        """更新EHS变更"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_ehs_change(change_id, update_data)
        if item:
            await self._audit("update", "ehs_change", resource_id=change_id)
        return item

    async def delete_ehs_change(self, change_id: uuid.UUID) -> bool:
        """删除EHS变更（软删除）"""
        result = await self.repo.delete_ehs_change(change_id)
        if result:
            await self._audit("delete", "ehs_change", resource_id=change_id)
        return result

    # ── 工作流状态机 ──

    async def submit_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """提交变更（草稿→审核中；紧急变更自动批准）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "draft":
            return None

        # 紧急变更：自动批准，保留审批链追溯
        if change.change_duration == "emergency":
            approval_chain = list(change.approval_chain or [])
            approval_chain.append({
                "level": 1,
                "approver_role": "系统自动批准（紧急变更）",
                "approver": "系统",
                "decision": "approved",
                "comments": "紧急变更，自动批准。需在48小时内补办审批手续。",
                "decided_at": datetime.now().isoformat(),
            })
            return await self.repo.update_ehs_change(
                change_id,
                {"status": "approved", "approval_chain": approval_chain},
            )

        return await self.repo.update_ehs_change(
            change_id, {"status": "under_review"}
        )

    async def approve_change(
        self, change_id: uuid.UUID, decision: str, comments: str | None = None
    ) -> EhsChange | None:
        """审批变更（审核中→已批准/已驳回）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "under_review":
            return None

        if decision == "approved":
            return await self.repo.update_ehs_change(
                change_id, {"status": "approved"}
            )
        elif decision == "rejected":
            return await self.repo.update_ehs_change(
                change_id, {"status": "rejected"}
            )
        return None

    async def reject_change(
        self, change_id: uuid.UUID, comments: str | None = None
    ) -> EhsChange | None:
        """驳回变更（审核中→已驳回）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "under_review":
            return None
        return await self.repo.update_ehs_change(
            change_id, {"status": "rejected"}
        )

    async def start_implementation(self, change_id: uuid.UUID) -> EhsChange | None:
        """开始实施（已批准→实施中）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "approved":
            return None
        return await self.repo.update_ehs_change(
            change_id,
            {"status": "in_progress", "actual_start": datetime.now()},
        )

    async def commission_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """投用（实施中→已投用）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "in_progress":
            return None
        return await self.repo.update_ehs_change(
            change_id,
            {"status": "commissioned", "actual_completion": datetime.now()},
        )

    async def close_change(
        self,
        change_id: uuid.UUID,
        closed_by: str | None = None,
        temp_expiry_date: str | None = None,
        restored_date: str | None = None,
    ) -> EhsChange | None:
        """关闭变更（已投用→已关闭）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "commissioned":
            return None

        closure_data = {
            "closed_by": closed_by,
            "closed_date": datetime.now().isoformat(),
        }
        if temp_expiry_date:
            closure_data["temp_expiry_date"] = temp_expiry_date
        if restored_date:
            closure_data["restored_date"] = restored_date

        return await self.repo.update_ehs_change(
            change_id,
            {"status": "closed", "closure": closure_data},
        )

    async def cancel_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """取消变更（草稿→已关闭）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "draft":
            return None
        closure_data = {
            "closed_by": None,
            "closed_date": datetime.now().isoformat(),
        }
        return await self.repo.update_ehs_change(
            change_id,
            {"status": "closed", "closure": closure_data},
        )

    # ── JSON 子记录操作 ──

    async def add_risk_assessment(
        self, change_id: uuid.UUID, item: dict
    ) -> EhsChange | None:
        """追加风险评估记录"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        assessments = list(change.risk_assessments or [])
        assessments.append(item)
        return await self.repo.update_ehs_change(
            change_id, {"risk_assessments": assessments}
        )

    async def update_action_item(
        self, change_id: uuid.UUID, index: int, status: str
    ) -> EhsChange | None:
        """更新行动项状态"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        items = list(change.action_items or [])
        if index < 0 or index >= len(items):
            return None
        items[index] = {**items[index], "status": status}
        if status == "completed":
            items[index]["completed_at"] = datetime.now().isoformat()
        return await self.repo.update_ehs_change(
            change_id, {"action_items": items}
        )

    async def update_pssr_checklist(
        self, change_id: uuid.UUID, items: list[dict]
    ) -> EhsChange | None:
        """更新PSSR检查清单"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        return await self.repo.update_ehs_change(
            change_id, {"pssr_checklist": items}
        )

    async def submit_verification(
        self, change_id: uuid.UUID, data: dict
    ) -> EhsChange | None:
        """提交变更验证数据"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        return await self.repo.update_ehs_change(
            change_id, {"verification": data}
        )


# ==================== 职业危害因素监测 Service ====================


