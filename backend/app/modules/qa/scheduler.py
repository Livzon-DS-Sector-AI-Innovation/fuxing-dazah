"""QA 正文提取的持久化调度器生成器。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import async_session_factory
from app.modules.qa.ai_analysis import (
    AI_LEASE_MINUTES,
    AI_MAX_RETRY_COUNT,
    process_analysis_run,
)
from app.modules.qa.models import (
    AIAnalysisStatus,
    DocumentAIAnalysisRun,
    DocumentExtractionRun,
    DocumentFile,
    ExtractionRunStatus,
    ExtractionStatus,
)
from app.modules.qa.service import EXTRACTION_LEASE_MINUTES, process_file
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskGenerator

logger = logging.getLogger(__name__)

# 自动重试上限；超过后停在 failed，只由人工在界面触发重试。
MAX_RETRY_COUNT = 3


class QaTextExtractionGenerator(TaskGenerator):
    name = "qa_text_extraction"
    schedule = ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=10)
    # 50 MiB 文件的对象读取、DOCX XML/PDF 版面解析可能明显超过单次
    # HTTP 请求时限；调度器超时必须高于解析租约回收阈值，避免正常大文件
    # 被外层 wait_for 取消后只能等下一轮回收。真正约束单次解析时长的是
    # 租约本身，这里只留出回收扫描的余量，因此直接由租约常量推导，
    # 避免两处数字漂移后再次出现「超时早于租约」把大文件反复掐死的问题。
    timeout_seconds = EXTRACTION_LEASE_MINUTES * 60 + 300
    enabled = True

    async def find_due(self, session: Any) -> list[DocumentFile]:
        now = datetime.now(UTC)
        try:
            # processing 超时回收为 queued；failed 最多自动重试三次。
            # 回收必须同时累加 retry_count：否则一个每次都卡死的文件会被每 10s
            # 重新拾起，既永远到不了 failed 上限，也永远解析不完。
            # 先关闭过期的运行台账，再清理文件 claim；否则被 wait_for 取消的
            # worker 会留下永久 processing 的历史运行。
            await session.execute(
                update(DocumentExtractionRun)
                .where(
                    DocumentExtractionRun.is_deleted.is_(False),
                    DocumentExtractionRun.status
                    == ExtractionRunStatus.PROCESSING.value,
                    or_(
                        DocumentExtractionRun.lease_until.is_(None),
                        DocumentExtractionRun.lease_until < now,
                    ),
                )
                .values(
                    status=ExtractionRunStatus.STALE.value,
                    error="解析租约超时，运行已回收",
                    finished_at=now,
                    worker_token=None,
                    lease_until=None,
                    retry_count=DocumentExtractionRun.retry_count + 1,
                )
            )
            await session.execute(
                update(DocumentFile)
                .where(
                    DocumentFile.is_deleted.is_(False),
                    DocumentFile.extraction_status == ExtractionStatus.PROCESSING.value,
                    or_(
                        DocumentFile.extraction_lease_until.is_(None),
                        DocumentFile.extraction_lease_until < now,
                    ),
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
                    extraction_worker_token=None,
                    extraction_lease_until=None,
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
                # 一次 tick 只认领一个：engine 是串行 await 每个 item 的
                # （platform/scheduler/engine.py:161-169），多认领不会提高
                # 吞吐（本来就串行），只会把调度器主循环的阻塞窗口按倍数放大。
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            items = list(result.scalars())
            for item in items:
                # 保留轻量 fake session/旧 worker 测试适配；真实 ORM 行都
                # 带有这些字段并走原子 claim。
                if hasattr(item, "extraction_status"):
                    item.extraction_status = ExtractionStatus.PROCESSING.value
                    item.extraction_worker_token = uuid.uuid4().hex
                    item.extraction_lease_until = now + timedelta(minutes=EXTRACTION_LEASE_MINUTES)
            # claim 先提交，实际读取/解析不持有数据库锁。
            if hasattr(session, "commit"):
                await session.commit()
            return items
        except SQLAlchemyError:
            # 应用可能先启动、后执行 Alembic。迁移尚未创建 qa 表时，调度器
            # 不应让每个 tick 打出未捕获异常或阻断同一 session 的后续工作。
            await session.rollback()
            logger.warning("QA 正文解析表不可用，跳过本轮扫描；请先执行数据库迁移")
            return []

    async def execute_one(self, session: Any, item: DocumentFile) -> None:
        # 解析任务使用独立 session，claim 事务已经提交；文件读取/解析期间
        # 不占用调度器扫描事务或数据库行锁。
        async with async_session_factory() as worker_session:
            await process_file(
                worker_session, item.id, worker_token=item.extraction_worker_token
            )
            await worker_session.commit()


GENERATOR = QaTextExtractionGenerator()


class QaAIAnalysisGenerator(TaskGenerator):
    """基于数据库 claim/lease 的 QA AI 分析 worker。"""

    name = "qa_ai_analysis"
    schedule = ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=5)
    # 整篇文档必须在一次 execute_one 内跑完：重跑分支会清空派生行并从第 0 块
    # 重来，所以超时低于整篇耗时的文档永远分析不完——每轮都被外层 wait_for
    # 取消、每轮都在重跑。块间续租只防「被当成失联任务回收」，防不住这个超时。
    # ponytail: 1 小时 = 「约 600 块 × 6s」的经验估计；分块数没有上限，更大的
    # 文档要么调大这里，要么把重跑分支改成增量续跑（ai_analysis 的清空分支）。
    # 由于 engine 串行执行 generator，这个值同时是单个 AI 任务阻塞调度器
    # tick 的上限。
    timeout_seconds = AI_LEASE_MINUTES * 60 * 4
    enabled = True

    async def find_due(self, session: Any) -> list[DocumentAIAnalysisRun]:
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=AI_LEASE_MINUTES)
        try:
            # 先回收过期租约；旧 worker 即使稍后返回也会因 token 不一致而
            # 不得覆盖新结果。
            await session.execute(
                update(DocumentAIAnalysisRun)
                .where(
                    DocumentAIAnalysisRun.is_deleted.is_(False),
                    DocumentAIAnalysisRun.status == AIAnalysisStatus.PROCESSING.value,
                    or_(
                        DocumentAIAnalysisRun.lease_until.is_(None),
                        DocumentAIAnalysisRun.lease_until < now,
                    ),
                )
                .values(
                    status=case(
                        (
                            DocumentAIAnalysisRun.retry_count + 1 >= AI_MAX_RETRY_COUNT,
                            AIAnalysisStatus.FAILED.value,
                        ),
                        else_=AIAnalysisStatus.QUEUED.value,
                    ),
                    worker_token=None,
                    lease_until=None,
                    retry_count=DocumentAIAnalysisRun.retry_count + 1,
                    finished_at=now,
                    error="AI 分析租约超时，已自动回收",
                )
            )
            result = await session.execute(
                select(DocumentAIAnalysisRun)
                .where(
                    DocumentAIAnalysisRun.is_deleted.is_(False),
                    or_(
                        (
                            (DocumentAIAnalysisRun.status == AIAnalysisStatus.QUEUED.value)
                            & (DocumentAIAnalysisRun.retry_count < AI_MAX_RETRY_COUNT)
                        ),
                        (
                            (DocumentAIAnalysisRun.status == AIAnalysisStatus.PROCESSING.value)
                            & (
                                DocumentAIAnalysisRun.lease_until.is_(None)
                                | (DocumentAIAnalysisRun.lease_until < stale_before)
                            )
                            & (DocumentAIAnalysisRun.retry_count < AI_MAX_RETRY_COUNT)
                        ),
                        (
                            (DocumentAIAnalysisRun.status == AIAnalysisStatus.FAILED.value)
                            & (DocumentAIAnalysisRun.retry_count < AI_MAX_RETRY_COUNT)
                        ),
                    ),
                )
                .order_by(DocumentAIAnalysisRun.created_at)
                # 同 QaTextExtractionGenerator：串行执行，只认领一个。
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            items = list(result.scalars())
            # claim 在单独事务提交，模型调用不持有数据库行锁。
            for item in items:
                item.status = AIAnalysisStatus.PROCESSING.value
                item.worker_token = uuid.uuid4().hex
                item.lease_until = now + timedelta(minutes=AI_LEASE_MINUTES)
                item.started_at = item.started_at or now
                item.finished_at = None
            if hasattr(session, "commit"):
                await session.commit()
            return items
        except SQLAlchemyError:
            await session.rollback()
            logger.warning("QA AI 分析表不可用，跳过本轮扫描；请先执行数据库迁移")
            return []

    async def execute_one(self, session: Any, item: DocumentAIAnalysisRun) -> None:
        async with async_session_factory() as worker_session:
            await process_analysis_run(
                worker_session, item.id, worker_token=item.worker_token
            )
            await worker_session.commit()


AI_GENERATOR = QaAIAnalysisGenerator()
