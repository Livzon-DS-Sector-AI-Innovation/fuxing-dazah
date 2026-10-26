"""QA 正文提取服务：解析/分块运行、重试与处理结果视图。"""

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    AppException,
    NotFoundException,
)
from app.modules.qa import (
    file_service as file_service,  # 显式再导出，供 api 层与测试补丁使用
)
from app.modules.qa.models import (
    DocumentChunkBlock,
    DocumentChunkRun,
    DocumentExtractionArtifact,
    DocumentExtractionRun,
    DocumentFile,
    DocumentTextChunk,
    DocumentTextSegment,
    ExtractionRunStatus,
    ExtractionStatus,
)
from app.modules.qa.repository import (
    get_chunk_run,
    get_extraction_run,
    get_file,
    get_latest_chunk_run_any_status,
    get_latest_extraction_run_any_status,
    list_chunk_block_locations,
    list_current_chunk_previews,
    list_current_raw_block_previews,
)
from app.modules.qa.service._shared import (
    _actor_id,
    _audit,
)
from app.platform.identity.models import User

logger = logging.getLogger(__name__)


# 解析在独立线程中读取对象并执行 XML/PDF 版面处理；租约要覆盖大文件的
# 正常处理时间，同时仍由调度器在明确过期后回收。
EXTRACTION_LEASE_MINUTES = 30


def _retrieval_fields(value: Any, raw_content: str) -> tuple[str, str, int, int]:
    """返回解析器派生的检索文本与哈希，并兼容旧解析契约。

    ``content`` 是 raw 证据，不能为了清洗 HTML 而覆盖。新解析器在
    ``RawBlock``/``DocumentChunk`` 上提供只读 ``retrieval_text`` 和
    ``retrieval_text_hash``；native/legacy 调用方没有这些属性时回退到
    原文，使 service 在迁移期间仍可保存旧格式结果。一次调用同时计算
    字符数和 token 估算，避免大型 HTML 表格被重复解析。
    """

    retrieval_text = getattr(value, "retrieval_text", None)
    if retrieval_text is None:
        retrieval_text = raw_content
    retrieval_text = str(retrieval_text)
    # 不再读取 dataclass 的 ``retrieval_text_hash`` property：它会再次执行
    # HTMLParser。相同文本的哈希在这里直接计算一次即可。
    retrieval_hash = hashlib.sha256(retrieval_text.encode("utf-8")).hexdigest()
    return (
        retrieval_text,
        str(retrieval_hash),
        len(retrieval_text),
        _retrieval_token_count(retrieval_text),
    )


def _retrieval_token_count(value: str) -> int:
    """与文档分块层一致的稳定 token 估算，避免绑定具体 embedding 模型。"""

    if not value:
        return 0
    return max(
        1,
        int(len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\w\s]", value)) * 1.05),
    )


async def process_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    *,
    worker_token: str | None = None,
) -> DocumentFile:
    """处理正文并生成 raw block/chunk。

    解析运行和分块运行都是追加记录，旧数据不被覆盖；``current_*`` 指针
    只在新运行成功（包括明确的 text_not_available/unsupported）后更新。
    文件读取和 CPU 解析在事务锁之外执行，数据库只在写入阶段短暂 flush。
    """
    # 直接调用（例如人工重试/本地脚本）也必须先取得短暂的文件行锁，
    # 否则两个入口都可能在看到 NULL token 后各自创建解析运行。调度器
    # 已领取的 token 不允许被无 token 的调用“加入”，避免并行 worker 共用
    # 一个运行身份。
    claim_result = await db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.id == file_id,
            DocumentFile.is_deleted.is_(False),
        )
        .with_for_update()
    )
    file_row = claim_result.scalar_one_or_none()
    if file_row is None:
        raise NotFoundException("文件", str(file_id))
    if worker_token is None and file_row.extraction_worker_token:
        return file_row
    lease_token = worker_token or uuid.uuid4().hex
    if (
        file_row.extraction_worker_token
        and file_row.extraction_worker_token != lease_token
    ):
        # 旧 worker 的租约已被回收，禁止覆盖新运行结果。
        return file_row
    from app.modules.qa.processing.document import (
        CHUNK_VERSION,
        PARSER_VERSION,
    )
    from app.modules.qa.processing.markdown import RETRIEVAL_TEXT_VERSION

    # 调度器在网络/进程边界可能发生至少一次投递；同一个 lease token
    # 已经有 processing run 时直接复用，避免重复追加 raw block/chunk。
    existing_run_result = await db.execute(
        select(DocumentExtractionRun)
        .where(
            DocumentExtractionRun.file_id == file_id,
            DocumentExtractionRun.worker_token == lease_token,
            DocumentExtractionRun.status == ExtractionRunStatus.PROCESSING.value,
            DocumentExtractionRun.is_deleted.is_(False),
        )
        .with_for_update()
    )
    existing_run = existing_run_result.scalar_one_or_none()
    if existing_run is not None:
        return file_row

    parser_mode = (file_row.parser_mode or "native_text").strip() or "native_text"
    configured_provider = (
        get_settings().QA_MD_EXTRACT_PROVIDER.strip().casefold() or "mineru"
    )
    input_hash = hashlib.sha256(
        # 解析输入哈希只描述原文件和解析器；分块版本单独进入 chunk
        # 运行哈希，便于未来只升级分块算法时复用 raw block。
        f"{file_row.sha256}:{parser_mode}:{PARSER_VERSION}".encode()
    ).hexdigest()
    extraction_run = DocumentExtractionRun(
        file_id=file_id,
        sha256=file_row.sha256,
        input_hash=input_hash,
        parser_mode=parser_mode,
        parser_version=PARSER_VERSION,
        provider=configured_provider,
        status=ExtractionRunStatus.PROCESSING.value,
        started_at=datetime.now(UTC),
        worker_token=lease_token,
        lease_until=datetime.now(UTC) + timedelta(minutes=EXTRACTION_LEASE_MINUTES),
        created_by=file_row.updated_by,
        updated_by=file_row.updated_by,
    )
    # lease_until 仅用于追踪/回收；解析函数本身不持有行锁。
    db.add(extraction_run)
    file_row.extraction_status = ExtractionStatus.PROCESSING.value
    file_row.extraction_error = None
    file_row.extraction_worker_token = lease_token
    file_row.extraction_lease_until = extraction_run.lease_until
    await db.flush()
    # flush 后 ID 已确定；提前保存，异常 rollback 后不依赖已过期 ORM 属性。
    extraction_run_id = extraction_run.id
    # claim/run 元数据先提交；对象读取和解析期间不持有 document_files 行锁。
    await db.commit()
    artifact_rows: list[dict[str, Any]] = []
    try:
        stored = await asyncio.to_thread(
            file_service.read_file,
            file_row.storage_key,
        )
        if stored is None:
            raise FileNotFoundError("私有存储对象不存在")
        data, _ = stored
        provider = configured_provider
        mineru_result = None
        if provider == "mineru":
            # MinerU 接口拆成申请、上传、轮询、下载四步；每次轮询后
            # 将远端状态写入当前解析运行，进程重启或租约回收时不会丢失
            # 批次标识。完整结果下载后统一交给 Markdown/JSON 解析器。
            from app.modules.qa.processing import mineru

            upload_session = await mineru.request_upload(
                data, file_row.original_filename
            )
            extraction_run.provider = "mineru"
            extraction_run.provider_task_id = upload_session.batch_id
            extraction_run.provider_state = "upload_pending"
            extraction_run.provider_context = {
                "batch_id": upload_session.batch_id,
                "file_name": upload_session.file_name,
                "data_id": upload_session.data_id,
            }
            await db.commit()
            await mineru.upload_bytes(upload_session, data)
            extraction_run.provider_state = "pending"
            await db.commit()
            poll_result = None
            # 轮询预算按时间算，不按次数。退避之后每次间隔不同，用次数表达
            # 一定会和真实时长漂移（30 分钟租约按次数推是 900 次，退避到 10s
            # 之后那是两个半小时）。超过租约时长就干净地判失败——外层 wait_for
            # 要租约 + 300s 才取消，那时已经是硬取消，报不出原因。
            poll_deadline = datetime.now(UTC) + timedelta(
                minutes=EXTRACTION_LEASE_MINUTES
            )
            poll_number = 0
            while datetime.now(UTC) < poll_deadline:
                poll_result = await mineru.poll_result(
                    upload_session.batch_id, upload_session.file_name
                )
                poll_number += 1
                extraction_run.provider_state = poll_result.state
                extraction_run.provider_context = {
                    **(extraction_run.provider_context or {}),
                    "progress": poll_result.progress,
                    "poll_count": poll_number,
                    "task_id": poll_result.task_id,
                }
                extraction_run.provider_task_id = (
                    poll_result.task_id or upload_session.batch_id
                )
                extraction_run.next_poll_at = (
                    datetime.now(UTC)
                    + timedelta(seconds=mineru.poll_interval(poll_number))
                    if poll_result.state
                    not in {"done", "failed", "canceled", "cancelled"}
                    else None
                )
                # 轮询期间必须续租。租约只在认领时写一次的话，超过
                # EXTRACTION_LEASE_MINUTES 的任务会被调度器当超时回收，第二个
                # worker 重复上传同一份字节建一个竞争 run，第一个 worker 的
                # 产物随后在 claim 失配时被删（见下面的 token 校验分支），
                # 三次重试用尽——本来能成功的文件被永久判死。文件行和运行行
                # 都要写，调度器两张表都在扫。
                renewed_lease = datetime.now(UTC) + timedelta(
                    minutes=EXTRACTION_LEASE_MINUTES
                )
                extraction_run.lease_until = renewed_lease
                file_row.extraction_lease_until = renewed_lease
                await db.commit()
                if poll_result.state in {"done", "failed", "canceled", "cancelled"}:
                    break
                await asyncio.sleep(mineru.poll_interval(poll_number))
            if poll_result is None or poll_result.state != "done":
                error = (
                    poll_result.error if poll_result else None
                ) or "MinerU 解析未完成"
                raise RuntimeError(error)
            mineru_result = await mineru.download_result(poll_result)
            parsed = mineru_result.document
            artifact_rows = await mineru.persist_artifacts(
                mineru_result, file_id, extraction_run_id, artifact_rows
            )
        elif provider == "native":
            # 仅保留历史/离线兼容；新环境默认 provider=mineru。
            parsed = await asyncio.to_thread(
                file_service.extract_document,
                file_row.extension.lower(),
                data,
                mode=parser_mode,
            )
        else:
            raise RuntimeError(f"不支持的 QA_MD_EXTRACT_PROVIDER: {provider}")
        # 这里不做 refresh 预检租约：紧随其后的 select ... with_for_update 已经
        # 用同一个 worker_token 原子确认归属，重复预检既违反 async 禁 refresh
        # 规则，也会在文件行被并发软删时抛 InvalidRequestError 覆盖掉下面的
        # STALE 分支。
        # 解析完成后再取得文件行锁。这样在开始替换 raw/chunk 前可以原子确认
        # lease token，锁会一直持有到本次结果提交，旧 worker 不会在提交窗口覆盖新结果。
        claim_result = await db.execute(
            select(DocumentFile)
            .where(
                DocumentFile.id == file_id,
                DocumentFile.is_deleted.is_(False),
                DocumentFile.extraction_worker_token == lease_token,
            )
            .with_for_update()
        )
        claimed_file = claim_result.scalar_one_or_none()
        if claimed_file is None:
            await db.rollback()
            for artifact in artifact_rows:
                await asyncio.to_thread(
                    file_service.delete_file, artifact["storage_key"]
                )
            stale_run = await db.get(DocumentExtractionRun, extraction_run_id)
            if stale_run is not None:
                stale_run.status = ExtractionRunStatus.STALE.value
                stale_run.error = "解析租约已被回收，旧 worker 结果已丢弃"
                stale_run.finished_at = datetime.now(UTC)
                stale_run.worker_token = None
                stale_run.lease_until = None
                await db.commit()
            return await get_file(db, file_id) or file_row
        file_row = claimed_file
        extraction_run.status = parsed.status
        extraction_run.parser_version = parsed.parser_version
        extraction_run.provider_state = (
            "done"
            if extraction_run.provider == "mineru"
            and parsed.status == ExtractionRunStatus.READY.value
            else extraction_run.provider_state
        )
        extraction_run.next_poll_at = None
        extraction_run.block_count = len(parsed.blocks)
        extraction_run.char_count = sum(len(block.content) for block in parsed.blocks)
        extraction_run.statistics = {
            **(parsed.statistics or {}),
            "retrieval_text_version": RETRIEVAL_TEXT_VERSION,
        }
        extraction_run.error = parsed.error
        extraction_run.finished_at = datetime.now(UTC)
        extraction_run.lease_until = None
        extraction_run.worker_token = None

        # 远程结果包即使最终归一化失败也要保留引用，便于排查解析器版本
        # 或 MinerU 输出差异；对象已经写入 QA 私有存储，不能留下无主对象。
        for artifact in artifact_rows:
            db.add(
                DocumentExtractionArtifact(
                    **artifact,
                    created_by=file_row.updated_by,
                    updated_by=file_row.updated_by,
                )
            )
        if artifact_rows:
            await db.flush()

        if parsed.status != ExtractionRunStatus.FAILED.value:
            # raw block 是事实/证据层：按 extraction run 追加保存，不因重解析
            # 覆盖或软删除。当前正文由 DocumentFile.current_extraction_run_id
            # 指针选择，历史分析运行仍可稳定引用原始 segment ID。
            block_rows: dict[int, DocumentTextSegment] = {}
            for block in parsed.blocks:
                retrieval_text, retrieval_text_hash, _, _ = _retrieval_fields(
                    block, block.content
                )
                row = DocumentTextSegment(
                    file_id=file_id,
                    extraction_run_id=extraction_run.id,
                    source_order=block.source_order,
                    block_type=block.block_type,
                    locator=block.locator,
                    page_number=block.page_number,
                    paragraph_index=block.paragraph_index,
                    table_index=block.table_index,
                    cell_index=block.cell_index,
                    row_index=block.row_index,
                    column_index=block.column_index,
                    heading_path=list(block.heading_path),
                    source_metadata=block.source_metadata,
                    content=block.content,
                    text_hash=block.text_hash,
                    retrieval_text=retrieval_text,
                    retrieval_text_hash=retrieval_text_hash,
                    created_by=file_row.updated_by,
                    updated_by=file_row.updated_by,
                )
                db.add(row)
                block_rows[block.source_order] = row
            await db.flush()

            # chunk 与运行一一对应，按 chunk_run_id 隔离当前/历史结果；不软删旧
            # chunk，保证历史 AI 运行和未来 embedding 能继续消费原始上下文。
            chunk_input_hash = hashlib.sha256(
                f"{extraction_run.input_hash}:{CHUNK_VERSION}".encode()
            ).hexdigest()
            # 分块是独立的可回收任务，不能复用上面已经清空的解析租约。
            # 在创建运行记录前保存独立 lease，避免 chunk_run 永远以 NULL
            # 租约落库，导致调度器无法识别/回收卡住的分块任务。
            chunk_lease_until = datetime.now(UTC) + timedelta(
                minutes=EXTRACTION_LEASE_MINUTES
            )
            retrieval_chunks = [
                (
                    chunk,
                    *_retrieval_fields(chunk, chunk.content),
                )
                for chunk in parsed.chunks
            ]
            chunk_run = DocumentChunkRun(
                file_id=file_id,
                extraction_run_id=extraction_run.id,
                chunk_version=CHUNK_VERSION,
                input_hash=chunk_input_hash,
                status=parsed.status,
                chunk_count=len(parsed.chunks),
                char_count=sum(chunk.char_count for chunk in parsed.chunks),
                statistics={
                    "parser_version": parsed.parser_version,
                    "provider": extraction_run.provider,
                    "retrieval_text_version": RETRIEVAL_TEXT_VERSION,
                    "retrieval_char_count": sum(item[3] for item in retrieval_chunks),
                    "retrieval_token_count": sum(item[4] for item in retrieval_chunks),
                },
                started_at=extraction_run.started_at,
                finished_at=datetime.now(UTC),
                worker_token=lease_token,
                lease_until=chunk_lease_until,
                created_by=file_row.updated_by,
                updated_by=file_row.updated_by,
            )
            db.add(chunk_run)
            await db.flush()
            for (
                chunk,
                retrieval_text,
                retrieval_text_hash,
                retrieval_char_count,
                retrieval_token_count,
            ) in retrieval_chunks:
                chunk_row = DocumentTextChunk(
                    file_id=file_id,
                    chunk_run_id=chunk_run.id,
                    chunk_order=chunk.chunk_order,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    retrieval_text=retrieval_text,
                    retrieval_text_hash=retrieval_text_hash,
                    retrieval_char_count=retrieval_char_count,
                    retrieval_token_count=retrieval_token_count,
                    char_count=chunk.char_count,
                    token_count=chunk.token_count,
                    heading_path=list(chunk.heading_path),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    source_start=chunk.source_start,
                    source_end=chunk.source_end,
                    chunk_metadata={
                        **(chunk.metadata or {}),
                        "retrieval_text_version": RETRIEVAL_TEXT_VERSION,
                    },
                    created_by=file_row.updated_by,
                    updated_by=file_row.updated_by,
                )
                db.add(chunk_row)
                await db.flush()
                seen_blocks: set[int] = set()
                offsets_by_order: dict[int, tuple[int | None, int | None]] = {}
                for source_order, char_start, char_end in chunk.block_offsets:
                    previous = offsets_by_order.get(source_order)
                    if previous is None:
                        offsets_by_order[source_order] = (char_start, char_end)
                        continue
                    starts = [
                        value
                        for value in (previous[0], char_start)
                        if value is not None
                    ]
                    ends = [
                        value for value in (previous[1], char_end) if value is not None
                    ]
                    offsets_by_order[source_order] = (
                        min(starts) if starts else None,
                        max(ends) if ends else None,
                    )
                for block_order in chunk.raw_block_orders:
                    if block_order in seen_blocks:
                        continue
                    seen_blocks.add(block_order)
                    raw_row = block_rows.get(block_order)
                    if raw_row is None:
                        continue
                    # 变量名与上面 chunk.block_offsets 的 int 解包区分开：这里的
                    # 偏移允许为 None（旧运行没有 offset 映射）。
                    offset_start, offset_end = offsets_by_order.get(
                        block_order, (None, None)
                    )
                    db.add(
                        DocumentChunkBlock(
                            chunk_id=chunk_row.id,
                            segment_id=raw_row.id,
                            block_order=block_order,
                            char_start=offset_start,
                            char_end=offset_end,
                            created_by=file_row.updated_by,
                            updated_by=file_row.updated_by,
                        )
                    )
            chunk_run.lease_until = None
            chunk_run.worker_token = None
            file_row.current_extraction_run_id = extraction_run.id
            file_row.current_chunk_run_id = chunk_run.id
            file_row.parser_version = parsed.parser_version
        file_row.extraction_status = parsed.status
        file_row.extraction_error = parsed.error
        file_row.extraction_worker_token = None
        file_row.extraction_lease_until = None
        if parsed.status == ExtractionRunStatus.FAILED.value:
            file_row.retry_count = int(file_row.retry_count or 0) + 1
            extraction_run.retry_count = file_row.retry_count
        else:
            file_row.retry_count = 0
        await db.flush()
        await _audit(
            db,
            action=(
                "extraction_failed"
                if parsed.status == ExtractionRunStatus.FAILED.value
                else "extraction_complete"
            ),
            user=None,
            resource_type="document_file",
            resource_id=file_row.id,
            new_value={
                "status": parsed.status,
                "block_count": len(parsed.blocks),
                "chunk_count": len(parsed.chunks),
            },
            extra={
                "sha256": file_row.sha256,
                "parser_version": parsed.parser_version,
                "provider": extraction_run.provider,
                "run_id": str(extraction_run.id),
            },
        )
        return file_row
    except asyncio.CancelledError:
        # 调度器超时/停机取消时，回滚本地未提交写入，但故意不清理
        # 已提交的租约 token；由下一轮扫描按 lease_until 回收，避免
        # 旧协程把新 worker 的租约误清掉。
        await db.rollback()
        # 产物不在数据库事务里，回滚带不走它们。键里带本次运行 id，删自己
        # 的对象不可能撞上新 worker 的；不在这里删就成了永久孤儿——没有
        # DB 记录，也就没有任何回收路径。
        for artifact in artifact_rows:
            await asyncio.to_thread(file_service.delete_file, artifact["storage_key"])
        raise
    except Exception as exc:
        # 解析期间租约可能已经被回收并交给新 worker。不能直接修改
        # ``file_row``/``extraction_run``，否则旧 worker 会把新任务覆盖成
        # FAILED 并清掉新租约。回滚旧事务后按 token + 行锁重新 claim，只有
        # 仍持有本 token 的 worker 才能写失败状态；否则只把自己的运行标记
        # 为 STALE。
        error_text = str(exc)[:2000]
        try:
            await db.rollback()
            # 对象存储不参与数据库事务；本次运行尚未成功提交时，清掉
            # 已写入的远程产物，避免失败/租约回收产生无主对象。
            for artifact in artifact_rows:
                await asyncio.to_thread(
                    file_service.delete_file, artifact["storage_key"]
                )
            claim_result = await db.execute(
                select(DocumentFile)
                .where(
                    DocumentFile.id == file_id,
                    DocumentFile.is_deleted.is_(False),
                    DocumentFile.extraction_worker_token == lease_token,
                )
                .with_for_update()
            )
            claimed_file = claim_result.scalar_one_or_none()
            extraction_row = await db.get(DocumentExtractionRun, extraction_run_id)
            if claimed_file is None:
                # 新 worker 已经取得租约；旧运行只保留为可审计的 stale，
                # 不触碰当前文件状态/租约。
                if extraction_row is not None:
                    extraction_row.status = ExtractionRunStatus.STALE.value
                    extraction_row.error = "解析租约已被回收，旧 worker 结果已丢弃"
                    extraction_row.finished_at = datetime.now(UTC)
                    extraction_row.worker_token = None
                    extraction_row.lease_until = None
                    await db.flush()
                    await db.commit()
                return await get_file(db, file_id) or file_row

            next_retry = int(claimed_file.retry_count or 0) + 1
            claimed_file.extraction_status = ExtractionStatus.FAILED.value
            claimed_file.extraction_error = error_text
            claimed_file.extraction_worker_token = None
            claimed_file.extraction_lease_until = None
            claimed_file.retry_count = next_retry
            if extraction_row is not None:
                extraction_row.status = ExtractionRunStatus.FAILED.value
                extraction_row.error = error_text
                extraction_row.finished_at = datetime.now(UTC)
                extraction_row.worker_token = None
                extraction_row.lease_until = None
                extraction_row.retry_count = next_retry
            await db.flush()
            await _audit(
                db,
                action="extraction_failed",
                user=None,
                resource_type="document_file",
                resource_id=claimed_file.id,
                new_value={
                    "status": claimed_file.extraction_status,
                    "error": error_text,
                },
                extra={
                    "retry_count": next_retry,
                    "sha256": claimed_file.sha256,
                    "parser_version": PARSER_VERSION,
                    "run_id": str(extraction_run_id),
                },
            )
            await db.commit()
            return claimed_file
        except Exception:
            # 失败收尾本身不可用时不要再尝试清理未知 worker 的租约；让
            # 调度器依据 lease_until 回收，并尽量返回数据库中的最新状态。
            logger.exception(
                "QA extraction failure finalization failed",
                extra={"file_id": str(file_id), "run_id": str(extraction_run_id)},
            )
            try:
                await db.rollback()
                return await get_file(db, file_id) or file_row
            except Exception:
                return file_row


async def retry_extraction(
    db: AsyncSession, file_id: uuid.UUID, user: User | None = None
) -> DocumentFile:
    # 人工重试与解析 worker 共用文件行锁：先让正在提交的 worker 完成，
    # 再清理其 token/运行，避免重试事务在 worker 之后把 ready 覆盖回 queued
    # 或反过来误清掉新 worker 的租约。
    file_result = await db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.id == file_id,
            DocumentFile.is_deleted.is_(False),
        )
        .with_for_update()
    )
    file_row = file_result.scalar_one_or_none()
    if file_row is None:
        raise NotFoundException("文件", str(file_id))
    active_runs = await db.execute(
        select(DocumentExtractionRun)
        .where(
            DocumentExtractionRun.file_id == file_id,
            DocumentExtractionRun.status == ExtractionRunStatus.PROCESSING.value,
            DocumentExtractionRun.is_deleted.is_(False),
        )
        .with_for_update()
    )
    for run in active_runs.scalars():
        run.status = ExtractionRunStatus.STALE.value
        run.error = "人工重试已替代当前解析运行"
        run.finished_at = datetime.now(UTC)
        run.worker_token = None
        run.lease_until = None
    file_row.extraction_status = ExtractionStatus.QUEUED.value
    file_row.extraction_error = None
    file_row.retry_count = 0
    file_row.extraction_worker_token = None
    file_row.extraction_lease_until = None
    file_row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="extraction_retry",
        user=user,
        resource_type="document_file",
        resource_id=file_id,
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_file(db, file_id) or file_row


# ───────────────────────── 组装输出 ─────────────────────────


def _safe_structure_metadata(value: Any) -> dict[str, Any] | None:
    """保留定位/结构信息，去掉 PDF span 和表格 cell 中的完整正文。"""

    if not isinstance(value, dict):
        return None
    allowed_scalars = {
        "bbox",
        "block_index",
        "line_count",
        "span_count",
        "reading_order",
        "boilerplate_candidate",
        "page_width",
        "page_height",
        "style",
        "numbering",
        "row",
        "row_count",
        "column_count",
        "is_header",
        "is_repeated_header",
    }
    output: dict[str, Any] = {
        key: value[key]
        for key in allowed_scalars
        if key in value
        and isinstance(value[key], (str, int, float, bool, list, dict, type(None)))
    }
    cells = value.get("cells")
    if isinstance(cells, list):
        # cell text 已经由 content_preview 返回；这里仅保留网格和合并信息，
        # 使前端仍能画出表格结构而不绕过正文长度上限。
        safe_cells = [
            {
                key: cell[key]
                for key in ("row", "column", "cell_index", "grid_span", "v_merge")
                if isinstance(cell, dict) and key in cell
            }
            for cell in cells
            if isinstance(cell, dict)
        ]
        output["cells"] = safe_cells[:200]
        if len(safe_cells) > 200:
            output["cells_truncated"] = True
    return output or None


def _safe_chunk_metadata(value: Any) -> dict[str, Any] | None:
    """chunk metadata 仅返回派生统计，不让未来扩展字段绕过正文上限。"""

    if not isinstance(value, dict):
        return None
    allowed = {
        "raw_block_count",
        "contains_table",
        "boilerplate_candidate",
        "boilerplate_block_count",
        "omitted_raw_block_orders",
        "table_header_truncated",
    }
    return {key: value[key] for key in allowed if key in value}


def _run_created_at(row: Any) -> Any:
    # BaseModel.created_at is always present for persisted rows, but keeping this
    # helper tolerant makes the read API compatible with old test doubles.
    return getattr(row, "created_at", None)


def _extraction_run_summary(
    row: Any, current_id: uuid.UUID | None
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "is_current": current_id is not None and row.id == current_id,
        "parser_mode": row.parser_mode,
        "parser_version": row.parser_version,
        "provider": getattr(row, "provider", None),
        "provider_state": getattr(row, "provider_state", None),
        "block_count": int(row.block_count or 0),
        "char_count": int(row.char_count or 0),
        "statistics": row.statistics,
        "error": row.error,
        "retry_count": int(row.retry_count or 0),
        "created_at": _run_created_at(row),
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _chunk_run_summary(row: Any, current_id: uuid.UUID | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "extraction_run_id": row.extraction_run_id,
        "status": row.status,
        "is_current": current_id is not None and row.id == current_id,
        "chunk_version": row.chunk_version,
        "chunk_count": int(row.chunk_count or 0),
        "char_count": int(row.char_count or 0),
        "statistics": row.statistics,
        "error": getattr(row, "error", None),
        "created_at": _run_created_at(row),
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _bounded_preview(
    value: Any, *, content_limit: int, content_length: int | None = None
) -> tuple[str, int, bool]:
    text = str(value or "")
    length = int(content_length if content_length is not None else len(text))
    return (
        text[:content_limit],
        length,
        length > content_limit or len(text) > content_limit,
    )


async def document_processing_results(
    db: AsyncSession,
    file_id: uuid.UUID,
    *,
    view: str,
    page: int,
    page_size: int,
    content_limit: int,
) -> dict[str, Any]:
    """返回文件解析/分块状态和当前结果的分页预览。

    ``latest_*`` 只用于解释 queued/processing/failed 状态；正文明细始终由
    ``current_*`` 指针（或明确的 legacy 空指针兼容规则）限定，避免在用户
    查看时混入历史解析运行或半写入结果。
    """

    file_row = await get_file(db, file_id)
    if file_row is None:
        raise NotFoundException("文件", str(file_id))

    current_extraction = (
        await get_extraction_run(db, file_row.current_extraction_run_id)
        if file_row.current_extraction_run_id is not None
        else None
    )
    latest_extraction = await get_latest_extraction_run_any_status(db, file_id)
    current_chunk = (
        await get_chunk_run(db, file_row.current_chunk_run_id)
        if file_row.current_chunk_run_id is not None
        else None
    )
    latest_chunk = await get_latest_chunk_run_any_status(db, file_id)
    # 只有没有任何新版解析运行的终态旧文件才允许 raw block legacy 回退。
    # 新上传/重试文件即使暂时没有 current 指针，也不能把旧正文混入本次查看。
    legacy = (
        file_row.parser_version is None
        and file_row.current_extraction_run_id is None
        and latest_extraction is None
        and file_row.extraction_status
        not in {ExtractionStatus.QUEUED.value, ExtractionStatus.PROCESSING.value}
    )

    raw_blocks: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    total = 0
    if view == "raw_blocks":
        rows, total = await list_current_raw_block_previews(
            db,
            file_row,
            page=page,
            page_size=page_size,
            content_limit=content_limit,
            allow_legacy=legacy,
        )
        for row in rows:
            preview, length, truncated = _bounded_preview(
                row.get("content_preview"),
                content_limit=content_limit,
                content_length=row.get("content_length"),
            )
            raw_blocks.append(
                {
                    "id": row["id"],
                    "source_order": row.get("source_order"),
                    "block_type": row["block_type"],
                    "locator": row["locator"],
                    "page_number": row.get("page_number"),
                    "paragraph_index": row.get("paragraph_index"),
                    "table_index": row.get("table_index"),
                    "row_index": row.get("row_index"),
                    "column_index": row.get("column_index"),
                    "heading_path": row.get("heading_path"),
                    "content_preview": preview,
                    "content_length": length,
                    "content_truncated": truncated,
                    "text_hash": row["text_hash"],
                    "structure_metadata": _safe_structure_metadata(
                        row.get("source_metadata")
                    ),
                }
            )
    elif view == "chunks":
        rows, total = await list_current_chunk_previews(
            db,
            file_row,
            page=page,
            page_size=page_size,
            content_limit=content_limit,
        )
        locations = await list_chunk_block_locations(db, [row["id"] for row in rows])
        for row in rows:
            retrieval_preview = row.get("retrieval_text_preview")
            retrieval_char_count = row.get("retrieval_char_count")
            if retrieval_preview is None:
                preview = None
                truncated = False
            else:
                preview, _, truncated = _bounded_preview(
                    retrieval_preview,
                    content_limit=content_limit,
                    content_length=retrieval_char_count,
                )
            chunks.append(
                {
                    "id": row["id"],
                    "chunk_order": row["chunk_order"],
                    "char_count": row["char_count"],
                    "token_count": row["token_count"],
                    "heading_path": row.get("heading_path"),
                    "page_start": row.get("page_start"),
                    "page_end": row.get("page_end"),
                    "source_start": row.get("source_start"),
                    "source_end": row.get("source_end"),
                    "retrieval_text_preview": preview,
                    "retrieval_char_count": retrieval_char_count,
                    "retrieval_text_truncated": truncated,
                    "retrieval_text_hash": row.get("retrieval_text_hash"),
                    "content_hash": row["content_hash"],
                    "metadata": _safe_chunk_metadata(row.get("chunk_metadata")),
                    "source_blocks": locations.get(row["id"], []),
                }
            )
    else:
        raise AppException(status_code=422, message="view 只能是 raw_blocks 或 chunks")

    return {
        "file_id": file_row.id,
        "extraction_status": file_row.extraction_status,
        "extraction_error": file_row.extraction_error,
        "retry_count": int(file_row.retry_count or 0),
        "parser_mode": file_row.parser_mode,
        "parser_version": file_row.parser_version,
        "legacy": legacy,
        "current_extraction_run": _extraction_run_summary(
            current_extraction, file_row.current_extraction_run_id
        ),
        "latest_extraction_run": _extraction_run_summary(
            latest_extraction, file_row.current_extraction_run_id
        ),
        "current_chunk_run": _chunk_run_summary(
            current_chunk, file_row.current_chunk_run_id
        ),
        "latest_chunk_run": _chunk_run_summary(
            latest_chunk, file_row.current_chunk_run_id
        ),
        "view": view,
        "page": page,
        "page_size": page_size,
        "total": total,
        "raw_blocks": raw_blocks,
        "chunks": chunks,
    }
