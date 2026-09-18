"""归档编排：筛缺档 -> 渲染 PDF -> 上传回填 -> 汇总结局。

幂等口径：仅「巡检记录」为空的记录生成回填；已有附件一律跳过，绝不改动。
文件名序号 = 全表已有归档最大序号 + 1（任务内串行递增）。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.modules.safety.fire_inspection import bitable
from app.modules.safety.fire_inspection.models import (
    Attachment,
    InspectionRecord,
    parse_record,
)
from app.modules.safety.fire_inspection.pdf import render

logger = logging.getLogger(__name__)

_SEQ_PATTERN = re.compile(r"^(\d+)_")
_UNKNOWN_EQUIPMENT = "未编号"
_UNKNOWN_TIME = "未知时间"
_TRUE = {"1", "true", "yes", "on", "y"}


def backfill_enabled() -> bool:
    """归档总开关（默认关闭；SAFETY_FIRE_INSPECTION_PDF_ENABLED 置真启用）。"""
    raw = (os.getenv("SAFETY_FIRE_INSPECTION_PDF_ENABLED") or "").strip().lower()
    return raw in _TRUE


@dataclass
class BackfillResult:
    """一次归档任务的结局。"""

    generated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (record_id, 原因)


class RepoPort(Protocol):
    """数据端口：service 只依赖此接口，测试注入内存桩。"""

    async def list_records(self) -> list[dict[str, object]]: ...

    async def download(self, file_token: str, extra: str | None = None) -> bytes: ...

    async def attachment_extra_map(
        self, record_ids: list[str]
    ) -> dict[str, dict[str, str]]: ...

    async def upload(self, file_name: str, content: bytes) -> str: ...

    async def append(self, record_id: str, file_tokens: list[str]) -> None: ...

    async def aclose(self) -> None: ...


class BitableRepo:
    """端口默认实现：直连点检表 Bitable。"""

    def __init__(self, app_token: str, table_id: str) -> None:
        self._app_token = app_token
        self._table_id = table_id
        self._http = httpx.AsyncClient(timeout=60)

    async def _token(self) -> str:
        return await bitable.load_tenant_token()

    async def list_records(self) -> list[dict[str, Any]]:
        return await bitable.search_records(
            await self._token(), self._app_token, self._table_id, http=self._http
        )

    async def download(self, file_token: str, extra: str | None = None) -> bytes:
        return await bitable.download_media(
            await self._token(), file_token, extra=extra, http=self._http
        )

    async def attachment_extra_map(
        self, record_ids: list[str]
    ) -> dict[str, dict[str, str]]:
        return await bitable.get_attachment_extras(
            await self._token(), self._app_token, self._table_id, record_ids, http=self._http
        )

    async def upload(self, file_name: str, content: bytes) -> str:
        return await bitable.upload_attachment(
            await self._token(), self._app_token, file_name, content, http=self._http
        )

    async def append(self, record_id: str, file_tokens: list[str]) -> None:
        await bitable.append_attachments(
            await self._token(),
            self._app_token,
            self._table_id,
            record_id,
            bitable.FIELD_REPORT_ID,
            file_tokens,
            http=self._http,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def default_repo() -> BitableRepo:
    return BitableRepo(bitable.FIRE_INSPECTION_APP_TOKEN, bitable.FIRE_INSPECTION_TABLE_ID)


def _max_archive_seq(records: list[InspectionRecord]) -> int:
    """全表已有归档附件名的最大序号；无归档为 0。"""
    max_seq = 0
    for record in records:
        for att in record.reports:
            match = _SEQ_PATTERN.match(att.name)
            if match:
                max_seq = max(max_seq, int(match.group(1)))
    return max_seq


def _archive_filename(record: InspectionRecord, seq: int) -> str:
    at = record.inspect_at or record.created_at
    time_part = at.strftime("%Y-%m-%d_%H-%M") if at else _UNKNOWN_TIME
    equipment = record.equipment_no or _UNKNOWN_EQUIPMENT
    return f"{seq:02d}_{equipment}_{time_part}_消防设施点检记录.pdf"


async def _collect_images(
    repo: RepoPort,
    record: InspectionRecord,
    extras: dict[str, str],
) -> dict[str, bytes]:
    """下载照片/签字字节；失败向上抛（整条计入失败清单，次日重试）。

    「记录本身没有照片」仍由渲染层留空框（与下载失败区分）。
    """
    images: dict[str, bytes] = {}
    attachments: list[Attachment] = [
        *record.overall_photos,
        *record.key_photos,
        *record.signatures,
    ]
    for att in attachments:
        if att.file_token in images:
            continue
        images[att.file_token] = await repo.download(att.file_token, extras.get(att.file_token))
    return images


async def generate_and_backfill(
    record_ids: list[str] | None = None,
    *,
    repo: RepoPort | None = None,
) -> BackfillResult:
    """扫描点检表，为缺档记录生成标准 PDF 并回填附件。

    record_ids 给定时只在该范围内补档（仍只补空档）。
    """
    own_repo = repo is None
    repo = repo or default_repo()
    result = BackfillResult()
    try:
        raw_records = await repo.list_records()
        records = [parse_record(raw) for raw in raw_records]
        by_id = {r.record_id: r for r in records}
        if record_ids:
            targets = [by_id[rid] for rid in record_ids if rid in by_id]
        else:
            targets = records

        next_seq = _max_archive_seq(records) + 1
        missing = [r for r in targets if not r.reports]
        result.skipped = [r.record_id for r in targets if r.reports]
        extras_by_record = await repo.attachment_extra_map([r.record_id for r in missing])
        for record in missing:
            try:
                images = await _collect_images(repo, record, extras_by_record.get(record.record_id, {}))
                file_name = _archive_filename(record, next_seq)
                content = render(record, images)
                token = await repo.upload(file_name, content)
                await repo.append(record.record_id, [token])
                result.generated.append(record.record_id)
                next_seq += 1
            except Exception as exc:
                logger.warning("点检归档失败 record=%s: %s", record.record_id, exc)
                result.failed.append((record.record_id, str(exc)))
        return result
    finally:
        if own_repo:
            await repo.aclose()


__all__ = [
    "BackfillResult",
    "BitableRepo",
    "RepoPort",
    "backfill_enabled",
    "default_repo",
    "generate_and_backfill",
]
