"""Workflow service — 工作流业务编排（CRUD + 执行触发）。"""

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.workflow.models import WorkflowDefinition, WorkflowRun
from app.modules.safety.workflow.repository import WorkflowRepository
from app.modules.safety.workflow.schemas import (
    WorkflowDefCreate,
    WorkflowDefUpdate,
)

logger = logging.getLogger(__name__)


class WorkflowService:
    """工作流定义 CRUD + 执行协调。"""

    def __init__(self, session: AsyncSession):
        self.repo = WorkflowRepository(session)
        self.session = session

    # ═══════════════════════════════════════════════════════════
    # 定义管理
    # ═══════════════════════════════════════════════════════════

    async def list_definitions(
        self,
        skip: int = 0,
        limit: int = 100,
        module_code: str | None = None,
        is_enabled: bool | None = None,
    ) -> tuple[list[WorkflowDefinition], int]:
        return await self.repo.list_definitions(
            skip=skip, limit=limit, module_code=module_code, is_enabled=is_enabled,
        )

    async def get_definition(self, id: uuid.UUID) -> WorkflowDefinition | None:
        return await self.repo.get_definition(id)

    async def get_definition_by_module_code(
        self, module_code: str,
    ) -> WorkflowDefinition | None:
        return await self.repo.get_definition_by_module_code(module_code)

    async def create_definition(
        self, data: WorkflowDefCreate,
    ) -> WorkflowDefinition:
        # 检查 module_code 唯一性（软删除感知）
        existing = await self.repo.get_definition_by_module_code(data.module_code)
        if existing:
            raise ValueError(
                f"module_code '{data.module_code}' 已被使用（ID: {existing.id}）"
            )
        return await self.repo.create_definition(data.model_dump())

    async def update_definition(
        self, id: uuid.UUID, data: WorkflowDefUpdate,
    ) -> WorkflowDefinition | None:
        wf = await self.repo.get_definition(id)
        if wf is None:
            return None

        update_data = data.model_dump(exclude_none=True)

        # 检查 module_code 唯一性
        if "module_code" in update_data:
            existing = await self.repo.get_definition_by_module_code(
                update_data["module_code"]
            )
            if existing and existing.id != id:
                raise ValueError(
                    f"module_code '{update_data['module_code']}' 已被使用"
                )

        # 更新时版本递增
        update_data["version"] = wf.version + 1

        return await self.repo.update_definition(id, update_data)

    async def delete_definition(self, id: uuid.UUID) -> bool:
        return await self.repo.delete_definition(id)

    # ═══════════════════════════════════════════════════════════
    # 执行
    # ═══════════════════════════════════════════════════════════

    async def run_workflow(
        self,
        workflow_id: uuid.UUID,
        inputs: dict,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> WorkflowRun:
        """执行工作流：创建 run 记录 → 执行 → 更新结果。

        当前版本为同步 blocking 执行。
        后续可改为 SSE streaming。
        """
        wf = await self.repo.get_definition(workflow_id)
        if wf is None:
            raise ValueError(f"工作流定义不存在: {workflow_id}")

        if not wf.is_enabled:
            raise ValueError(f"工作流已禁用: {wf.name}")

        # 创建 run 记录
        run = await self.repo.create_run({
            "workflow_id": workflow_id,
            "inputs": inputs,
            "status": "running",
            "started_at": datetime.utcnow(),
            "entity_type": entity_type,
            "entity_id": entity_id,
        })

        try:
            # 执行工作流（同步 blocking）
            from app.modules.safety.workflow.entry import WorkflowEntry
            from app.modules.safety.service.config import create_ai_service

            ai_service = create_ai_service("text")
            entry = WorkflowEntry(self.session, ai_service)

            start = time.monotonic()
            result = entry.run(wf, inputs)
            elapsed = time.monotonic() - start

            # 更新 run 记录为成功
            await self.repo.update_run(run.id, {
                "status": "succeeded",
                "outputs": result.get("outputs", {}),
                "node_results": result.get("node_results", {}),
                "total_tokens": result.get("total_tokens", 0),
                "total_steps": result.get("total_steps", 0),
                "elapsed_time": round(elapsed, 3),
                "finished_at": datetime.utcnow(),
            })

            # 关闭 AI service 连接
            await ai_service.close()

            return await self.repo.get_run(run.id)

        except Exception as e:
            logger.exception("工作流执行失败: %s", e)
            await self.repo.update_run(run.id, {
                "status": "failed",
                "error_message": str(e),
                "elapsed_time": time.monotonic() - start,
                "finished_at": datetime.utcnow(),
            })
            try:
                await ai_service.close()
            except Exception:
                pass
            raise

    # ═══════════════════════════════════════════════════════════
    # 运行记录
    # ═══════════════════════════════════════════════════════════

    async def list_runs(
        self,
        workflow_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorkflowRun], int]:
        return await self.repo.list_runs(
            workflow_id=workflow_id, skip=skip, limit=limit,
        )

    async def get_run(self, id: uuid.UUID) -> WorkflowRun | None:
        return await self.repo.get_run(id)
