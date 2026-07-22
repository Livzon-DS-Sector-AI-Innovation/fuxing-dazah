"""Safety business workflows."""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    OhHealthExam,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service._helpers import audit_log

logger = logging.getLogger(__name__)


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
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )

    # ── CRUD ──

    async def get_exams(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        exam_type: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhHealthExam], int]:
        """获取体检列表"""
        return await self.repo.get_health_exams(
            skip, limit, status, exam_type, department, keyword
        )

    async def get_exam(self, exam_id: uuid.UUID) -> OhHealthExam | None:
        """获取体检详情"""
        return await self.repo.get_health_exam_by_id(exam_id)

    async def create_exam(self, data: Any) -> OhHealthExam:
        """创建体检记录"""
        create_data = data.model_dump()
        item = await self.repo.create_health_exam(create_data)
        await self._audit("create", "oh_health_exam", resource_id=item.id)
        return item

    async def update_exam(self, exam_id: uuid.UUID, data: Any) -> OhHealthExam | None:
        """更新体检记录"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_health_exam(exam_id, update_data)
        if item:
            await self._audit("update", "oh_health_exam", resource_id=exam_id)
        return item

    async def delete_exam(self, exam_id: uuid.UUID) -> bool:
        """删除体检记录（软删除）"""
        result = await self.repo.delete_health_exam(exam_id)
        if result:
            await self._audit("delete", "oh_health_exam", resource_id=exam_id)
        return result

    # ── 工作流 ──

    async def start_exam(self, exam_id: uuid.UUID) -> OhHealthExam | None:
        """开始体检（已安排→体检中）"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam or exam.status != "scheduled":
            return None
        return await self.repo.update_health_exam(
            exam_id, {"status": "in_progress"}
        )

    async def complete_exam(self, exam_id: uuid.UUID) -> OhHealthExam | None:
        """完成体检（体检中→已完成）"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam or exam.status != "in_progress":
            return None
        return await self.repo.update_health_exam(
            exam_id, {"status": "completed"}
        )

    async def archive_exam(self, exam_id: uuid.UUID) -> OhHealthExam | None:
        """归档体检（已完成→已归档）"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam or exam.status != "completed":
            return None
        return await self.repo.update_health_exam(
            exam_id, {"status": "archived"}
        )

    # ── JSON 子记录操作 ──

    async def add_exam_item(
        self, exam_id: uuid.UUID, item: dict
    ) -> OhHealthExam | None:
        """追加体检项目"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None
        items = list(exam.exam_items or [])
        items.append(item)
        return await self.repo.update_health_exam(
            exam_id, {"exam_items": items}
        )

    async def update_exam_item(
        self, exam_id: uuid.UUID, index: int, data: dict
    ) -> OhHealthExam | None:
        """更新体检项目"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None
        items = list(exam.exam_items or [])
        if index < 0 or index >= len(items):
            return None
        items[index] = {**items[index], **data}
        return await self.repo.update_health_exam(
            exam_id, {"exam_items": items}
        )

    async def remove_exam_item(
        self, exam_id: uuid.UUID, index: int
    ) -> OhHealthExam | None:
        """删除体检项目"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None
        items = list(exam.exam_items or [])
        if index < 0 or index >= len(items):
            return None
        items.pop(index)
        return await self.repo.update_health_exam(
            exam_id, {"exam_items": items}
        )

    async def set_conclusion(
        self, exam_id: uuid.UUID, conclusion: str, remarks: str | None = None
    ) -> OhHealthExam | None:
        """设置体检结论（若为异常结论则自动创建异常记录）"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None

        update_data: dict[str, Any] = {"overall_conclusion": conclusion}

        # 异常结论自动创建处置记录
        alarming_conclusions = {"suspected_od", "od_diagnosed", "contraindicated"}
        if conclusion in alarming_conclusions:
            conclusion_labels = {
                "suspected_od": "疑似职业病",
                "od_diagnosed": "职业病确诊",
                "contraindicated": "职业禁忌证",
            }
            label = conclusion_labels.get(conclusion, conclusion)
            records = list(exam.abnormality_records or [])
            records.append({
                "abnormality_desc": (
                    f"员工 {exam.employee_name} 体检结论为「{label}」"
                    + (f"，备注: {remarks}" if remarks else "")
                ),
                "corrective_action": "",
                "responsible_person": "",
                "deadline": "",
                "status": "open",
                "completed_at": "",
                "remarks": remarks or "",
            })
            update_data["abnormality_records"] = records

        return await self.repo.update_health_exam(exam_id, update_data)

    async def add_abnormality_record(
        self, exam_id: uuid.UUID, item: dict
    ) -> OhHealthExam | None:
        """追加异常处置记录"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None
        records = list(exam.abnormality_records or [])
        records.append(item)
        return await self.repo.update_health_exam(
            exam_id, {"abnormality_records": records}
        )

    async def update_abnormality_record_status(
        self, exam_id: uuid.UUID, index: int, status: str
    ) -> OhHealthExam | None:
        """更新异常处置状态"""
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None
        records = list(exam.abnormality_records or [])
        if index < 0 or index >= len(records):
            return None
        records[index] = {**records[index], "status": status}
        if status == "closed":
            records[index]["completed_at"] = datetime.now().isoformat()
        return await self.repo.update_health_exam(
            exam_id, {"abnormality_records": records}
        )


# ==================== 定时任务 Service ====================


