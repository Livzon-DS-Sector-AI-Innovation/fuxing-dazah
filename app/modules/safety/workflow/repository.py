"""Workflow repository — 工作流定义与运行记录的数据访问。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.workflow.models import WorkflowDefinition, WorkflowRun


class WorkflowRepository:
    """工作流数据访问层 — 纯读写，不含业务语义。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ═══════════════════════════════════════════════════════════
    # WorkflowDefinition
    # ═══════════════════════════════════════════════════════════

    async def list_definitions(
        self,
        skip: int = 0,
        limit: int = 100,
        module_code: str | None = None,
        is_enabled: bool | None = None,
    ) -> tuple[list[WorkflowDefinition], int]:
        query = select(WorkflowDefinition).where(
            WorkflowDefinition.is_deleted == False
        )
        count_query = select(func.count()).select_from(WorkflowDefinition).where(
            WorkflowDefinition.is_deleted == False
        )

        if module_code:
            query = query.where(WorkflowDefinition.module_code == module_code)
            count_query = count_query.where(
                WorkflowDefinition.module_code == module_code
            )
        if is_enabled is not None:
            query = query.where(WorkflowDefinition.is_enabled == is_enabled)
            count_query = count_query.where(
                WorkflowDefinition.is_enabled == is_enabled
            )

        query = query.order_by(WorkflowDefinition.updated_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        items = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def get_definition(self, id: uuid.UUID) -> WorkflowDefinition | None:
        stmt = select(WorkflowDefinition).where(
            WorkflowDefinition.id == id,
            WorkflowDefinition.is_deleted == False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_definition_by_module_code(
        self, module_code: str,
    ) -> WorkflowDefinition | None:
        stmt = select(WorkflowDefinition).where(
            WorkflowDefinition.module_code == module_code,
            WorkflowDefinition.is_deleted == False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_definition(
        self, data: dict,
    ) -> WorkflowDefinition:
        wf = WorkflowDefinition(**data)
        self.session.add(wf)
        await self.session.flush()
        return wf

    async def update_definition(
        self, id: uuid.UUID, data: dict,
    ) -> WorkflowDefinition | None:
        data["updated_at"] = datetime.utcnow()
        stmt = (
            update(WorkflowDefinition)
            .where(WorkflowDefinition.id == id, WorkflowDefinition.is_deleted == False)
            .values(**data)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        # UPDATE 后必须 re-fetch（SQLAlchemy async 铁律）
        return await self.get_definition(id)

    async def delete_definition(self, id: uuid.UUID) -> bool:
        wf = await self.get_definition(id)
        if wf is None:
            return False
        wf.is_deleted = True
        wf.updated_at = datetime.utcnow()
        await self.session.flush()
        return True

    # ═══════════════════════════════════════════════════════════
    # WorkflowRun
    # ═══════════════════════════════════════════════════════════

    async def list_runs(
        self,
        workflow_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorkflowRun], int]:
        query = select(WorkflowRun).where(WorkflowRun.is_deleted == False)
        count_query = select(func.count()).select_from(WorkflowRun).where(
            WorkflowRun.is_deleted == False
        )

        if workflow_id:
            query = query.where(WorkflowRun.workflow_id == workflow_id)
            count_query = count_query.where(WorkflowRun.workflow_id == workflow_id)

        query = query.order_by(WorkflowRun.created_at.desc())
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        items = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def get_run(self, id: uuid.UUID) -> WorkflowRun | None:
        stmt = select(WorkflowRun).where(
            WorkflowRun.id == id,
            WorkflowRun.is_deleted == False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_run(self, data: dict) -> WorkflowRun:
        run = WorkflowRun(**data)
        self.session.add(run)
        await self.session.flush()
        return run

    async def update_run(self, id: uuid.UUID, data: dict) -> WorkflowRun | None:
        data["updated_at"] = datetime.utcnow()
        stmt = (
            update(WorkflowRun)
            .where(WorkflowRun.id == id, WorkflowRun.is_deleted == False)
            .values(**data)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return await self.get_run(id)
