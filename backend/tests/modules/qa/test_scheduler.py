"""QA 正文提取调度器的容错和扫描行为测试。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.modules.qa.scheduler import QaTextExtractionGenerator


class _Result:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []

    def scalars(self) -> Iterator[Any]:
        return iter(self.rows)


class _Session:
    def __init__(self, results: list[_Result] | None = None, error: Exception | None = None) -> None:
        self.results = list(results or [])
        self.error = error
        self.rollback_count = 0
        self.execute_count = 0

    async def execute(self, _statement: Any) -> _Result:
        self.execute_count += 1
        if self.error is not None:
            raise self.error
        return self.results.pop(0)

    async def rollback(self) -> None:
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_find_due_skips_unmigrated_qa_table_without_bubbling_error() -> None:
    """QA 表尚未迁移时调度器回滚当前事务并安静跳过本轮扫描。"""
    session = _Session(error=SQLAlchemyError("qa.document_files does not exist"))

    result = await QaTextExtractionGenerator().find_due(session)

    assert result == []
    assert session.execute_count == 1
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_find_due_runs_timeout_recovery_and_returns_queued_files() -> None:
    """正常扫描时先回收超时任务，再返回排队和可重试文件。"""
    queued = object()
    session = _Session(results=[_Result(), _Result([queued])])

    result = await QaTextExtractionGenerator().find_due(session)

    assert result == [queued]
    assert session.execute_count == 2
    assert session.rollback_count == 0
