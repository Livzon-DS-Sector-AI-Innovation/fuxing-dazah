"""QA 正文提取的持久化调度器生成器。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.modules.qa.models import DocumentFile, ExtractionStatus
from app.modules.qa.service import process_file
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskGenerator

logger = logging.getLogger(__name__)

# 自动重试上限；超过后停在 failed，只由人工在界面触发重试。
MAX_RETRY_COUNT = 3


class QaTextExtractionGenerator(TaskGenerator):
    name = "qa_text_extraction"
    schedule = ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=10)
    timeout_seconds = 120
    enabled = True

    async def find_due(self, session: Any) -> list[DocumentFile]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=10)
        try:
            # processing 超时回收为 queued；failed 最多自动重试三次。
            # 回收必须同时累加 retry_count：否则一个每次都卡死的文件会被每 10s
            # 重新拾起，既永远到不了 failed 上限，也永远解析不完。
            await session.execute(
                update(DocumentFile)
                .where(
                    DocumentFile.is_deleted.is_(False),
                    DocumentFile.extraction_status == ExtractionStatus.PROCESSING.value,
                    DocumentFile.updated_at < stale_before,
                )
                .values(
                    extraction_status=case(
                        (
                            DocumentFile.retry_count + 1 >= MAX_RETRY_COUNT,
                            ExtractionStatus.FAILED.value,
                        ),
                        else_=ExtractionStatus.QUEUED.value,
                    ),
                    retry_count=DocumentFile.retry_count + 1,
                    extraction_error="处理超时，已自动回收",
                )
            )
            result = await session.execute(
                select(DocumentFile)
                .where(
                    DocumentFile.is_deleted.is_(False),
                    or_(
                        DocumentFile.extraction_status == ExtractionStatus.QUEUED.value,
                        (
                            (DocumentFile.extraction_status == ExtractionStatus.FAILED.value)
                            & (DocumentFile.retry_count < MAX_RETRY_COUNT)
                        ),
                    ),
                )
                .order_by(DocumentFile.updated_at)
                .limit(20)
            )
            return list(result.scalars())
        except SQLAlchemyError:
            # 应用可能先启动、后执行 Alembic。迁移尚未创建 qa 表时，调度器
            # 不应让每个 tick 打出未捕获异常或阻断同一 session 的后续工作。
            await session.rollback()
            logger.warning("QA 正文解析表不可用，跳过本轮扫描；请先执行数据库迁移")
            return []

    async def execute_one(self, session: Any, item: DocumentFile) -> None:
        await process_file(session, item.id)


GENERATOR = QaTextExtractionGenerator()
