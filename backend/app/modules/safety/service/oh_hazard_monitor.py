"""Safety business workflows."""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    OhHazardMonitor,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service._helpers import audit_log

logger = logging.getLogger(__name__)


class OhHazardMonitorService:
    """职业危害因素监测服务"""

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

    async def get_monitors(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        detection_type: str | None = None,
        workplace: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhHazardMonitor], int]:
        """获取监测列表"""
        return await self.repo.get_hazard_monitors(
            skip, limit, status, detection_type, workplace, keyword
        )

    async def get_monitor(self, monitor_id: uuid.UUID) -> OhHazardMonitor | None:
        """获取监测详情"""
        return await self.repo.get_hazard_monitor_by_id(monitor_id)

    async def create_monitor(self, data: Any) -> OhHazardMonitor:
        """创建监测记录"""
        create_data = data.model_dump()
        item = await self.repo.create_hazard_monitor(create_data)
        await self._audit("create", "oh_hazard_monitor", resource_id=item.id)
        return item

    async def update_monitor(self, monitor_id: uuid.UUID, data: Any) -> OhHazardMonitor | None:
        """更新监测记录"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_hazard_monitor(monitor_id, update_data)
        if item:
            await self._audit("update", "oh_hazard_monitor", resource_id=monitor_id)
        return item

    async def delete_monitor(self, monitor_id: uuid.UUID) -> bool:
        """删除监测记录（软删除）"""
        result = await self.repo.delete_hazard_monitor(monitor_id)
        if result:
            await self._audit("delete", "oh_hazard_monitor", resource_id=monitor_id)
        return result

    # ── 工作流 ──

    async def start_monitoring(self, monitor_id: uuid.UUID) -> OhHazardMonitor | None:
        """开始监测（草稿→检测中）"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor or monitor.status != "draft":
            return None
        return await self.repo.update_hazard_monitor(
            monitor_id, {"status": "in_progress"}
        )

    async def complete_monitoring(self, monitor_id: uuid.UUID) -> OhHazardMonitor | None:
        """完成监测（检测中→已完成），自动计算OEL合规状态并生成异常记录"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor or monitor.status != "in_progress":
            return None

        # 自动计算合规状态
        results = list(monitor.detection_results or [])
        abnormality_records = list(monitor.abnormality_records or [])
        has_exceeding = False

        for i, item in enumerate(results):
            value = item.get("detection_value")
            limit_val = item.get("oel_limit")
            if value is not None and limit_val is not None and limit_val > 0:
                ratio = value / limit_val
                if ratio > 1.0:
                    results[i]["compliance_status"] = "exceeding"
                    has_exceeding = True
                    # 自动创建异常记录
                    abnormality_records.append({
                        "abnormality_desc": (
                            f"{item.get('factor_name', '未知因素')} 检测值 {value} {item.get('unit', '')} "
                            f"超过OEL限值 {limit_val} {item.get('unit', '')}"
                        ),
                        "corrective_action": "",
                        "responsible_person": "",
                        "deadline": "",
                        "status": "open",
                        "completed_at": "",
                        "remarks": f"标准参考: {item.get('standard_ref', '')}",
                    })
                elif ratio >= 0.8:
                    results[i]["compliance_status"] = "marginal"
                else:
                    results[i]["compliance_status"] = "compliant"
            else:
                results[i]["compliance_status"] = "compliant"

        return await self.repo.update_hazard_monitor(
            monitor_id,
            {
                "status": "completed",
                "detection_results": results,
                "abnormality_records": abnormality_records,
            },
        )

    async def verify_monitoring(
        self, monitor_id: uuid.UUID, verified_by: str | None, comments: str | None
    ) -> OhHazardMonitor | None:
        """验证监测（已完成→已验证）"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor or monitor.status != "completed":
            return None
        update_data: dict[str, Any] = {"status": "verified"}
        if verified_by:
            update_data["verifier_name"] = verified_by
        if comments:
            update_data["notes"] = (
                f"{(monitor.notes or '')}\n验证意见: {comments}".strip()
            )
        return await self.repo.update_hazard_monitor(monitor_id, update_data)

    # ── JSON 子记录操作 ──

    async def add_detection_result(
        self, monitor_id: uuid.UUID, item: dict
    ) -> OhHazardMonitor | None:
        """追加检测结果"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor:
            return None
        results = list(monitor.detection_results or [])
        results.append(item)
        return await self.repo.update_hazard_monitor(
            monitor_id, {"detection_results": results}
        )

    async def update_detection_result(
        self, monitor_id: uuid.UUID, index: int, data: dict
    ) -> OhHazardMonitor | None:
        """更新检测结果"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor:
            return None
        results = list(monitor.detection_results or [])
        if index < 0 or index >= len(results):
            return None
        results[index] = {**results[index], **data}
        return await self.repo.update_hazard_monitor(
            monitor_id, {"detection_results": results}
        )

    async def remove_detection_result(
        self, monitor_id: uuid.UUID, index: int
    ) -> OhHazardMonitor | None:
        """删除检测结果"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor:
            return None
        results = list(monitor.detection_results or [])
        if index < 0 or index >= len(results):
            return None
        results.pop(index)
        return await self.repo.update_hazard_monitor(
            monitor_id, {"detection_results": results}
        )

    async def add_abnormality_record(
        self, monitor_id: uuid.UUID, item: dict
    ) -> OhHazardMonitor | None:
        """追加异常处置记录"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor:
            return None
        records = list(monitor.abnormality_records or [])
        records.append(item)
        return await self.repo.update_hazard_monitor(
            monitor_id, {"abnormality_records": records}
        )

    async def update_abnormality_record_status(
        self, monitor_id: uuid.UUID, index: int, status: str
    ) -> OhHazardMonitor | None:
        """更新异常处置状态"""
        monitor = await self.repo.get_hazard_monitor_by_id(monitor_id)
        if not monitor:
            return None
        records = list(monitor.abnormality_records or [])
        if index < 0 or index >= len(records):
            return None
        records[index] = {**records[index], "status": status}
        if status == "closed":
            records[index]["completed_at"] = datetime.now().isoformat()
        return await self.repo.update_hazard_monitor(
            monitor_id, {"abnormality_records": records}
        )


# ==================== 职业健康体检 Service ====================


