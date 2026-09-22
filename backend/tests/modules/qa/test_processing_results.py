"""文件解析/raw block/chunk 只读预览契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.qa import service


def _file(*, file_id, extraction_id=None, chunk_id=None, status="ready"):
    return SimpleNamespace(
        id=file_id,
        extraction_status=status,
        extraction_error=None,
        retry_count=0,
        parser_mode="native_text",
        parser_version="qa-native-text-v2" if extraction_id else None,
        current_extraction_run_id=extraction_id,
        current_chunk_run_id=chunk_id,
    )


def _extraction(run_id, *, status="ready"):
    return SimpleNamespace(
        id=run_id,
        status=status,
        parser_mode="native_text",
        parser_version="qa-native-text-v2",
        block_count=1,
        char_count=2000,
        statistics={"block_count": 1},
        error=None,
        retry_count=0,
        created_at=datetime.now(UTC),
        started_at=None,
        finished_at=None,
    )


def _chunk_run(run_id, extraction_id, *, status="ready"):
    return SimpleNamespace(
        id=run_id,
        extraction_run_id=extraction_id,
        status=status,
        chunk_version="qa-chunk-v2",
        chunk_count=1,
        char_count=2000,
        statistics={"chunk_count": 1},
        error=None,
        created_at=datetime.now(UTC),
        started_at=None,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_processing_results_truncate_content_and_hide_nested_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = uuid4()
    extraction_id = uuid4()
    chunk_id = uuid4()
    file_row = _file(file_id=file_id, extraction_id=extraction_id, chunk_id=chunk_id)
    current = _extraction(extraction_id)
    latest_chunk = _chunk_run(chunk_id, extraction_id)

    monkeypatch.setattr(service, "get_file", AsyncMock(return_value=file_row))
    monkeypatch.setattr(service, "get_extraction_run", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "get_latest_extraction_run_any_status", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "get_chunk_run", AsyncMock(return_value=latest_chunk))
    monkeypatch.setattr(service, "get_latest_chunk_run_any_status", AsyncMock(return_value=latest_chunk))
    list_blocks = AsyncMock(
        return_value=(
            [
                {
                    "id": uuid4(),
                    "source_order": 1,
                    "block_type": "pdf_block",
                    "locator": "page:1/block:1",
                    "page_number": 1,
                    "paragraph_index": None,
                    "table_index": None,
                    "row_index": None,
                    "column_index": None,
                    "heading_path": [],
                    "content_preview": "ABCDEFGHIJK",
                    "content_length": 11,
                    "text_hash": "a" * 64,
                    "source_metadata": {
                        "bbox": [0, 0, 10, 10],
                        "lines": [{"text": "DO NOT RETURN"}],
                        "cells": [{"row": 0, "column": 0, "text": "hidden"}],
                    },
                }
            ],
            1,
        )
    )
    monkeypatch.setattr(service, "list_current_raw_block_previews", list_blocks)

    result = await service.document_processing_results(
        db=None,  # type: ignore[arg-type]
        file_id=file_id,
        view="raw_blocks",
        page=1,
        page_size=20,
        content_limit=5,
    )

    item = result["raw_blocks"][0]
    assert item["content_preview"] == "ABCDE"
    assert item["content_length"] == 11
    assert item["content_truncated"] is True
    assert "lines" not in item["structure_metadata"]
    assert item["structure_metadata"]["cells"] == [
        {"row": 0, "column": 0}
    ]
    assert result["current_extraction_run"]["is_current"] is True
    assert result["latest_extraction_run"]["is_current"] is True
    list_blocks.assert_awaited_once()


@pytest.mark.asyncio
async def test_processing_results_chunk_preview_includes_only_current_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = uuid4()
    extraction_id = uuid4()
    chunk_id = uuid4()
    segment_id = uuid4()
    file_row = _file(file_id=file_id, extraction_id=extraction_id, chunk_id=chunk_id)
    current = _extraction(extraction_id)
    current_chunk = _chunk_run(chunk_id, extraction_id)

    monkeypatch.setattr(service, "get_file", AsyncMock(return_value=file_row))
    monkeypatch.setattr(service, "get_extraction_run", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "get_latest_extraction_run_any_status", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "get_chunk_run", AsyncMock(return_value=current_chunk))
    monkeypatch.setattr(service, "get_latest_chunk_run_any_status", AsyncMock(return_value=current_chunk))
    monkeypatch.setattr(
        service,
        "list_current_chunk_previews",
        AsyncMock(
            return_value=(
                [
                    {
                        "id": chunk_id,
                        "chunk_order": 0,
                        "char_count": 1001,
                        "token_count": 300,
                        "heading_path": ["SOP"],
                        "page_start": 1,
                        "page_end": 2,
                        "source_start": 1,
                        "source_end": 2,
                        "content_preview": "X" * 101,
                        "content_hash": "b" * 64,
                        "chunk_metadata": {"raw_block_count": 2},
                    }
                ],
                1,
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "list_chunk_block_locations",
        AsyncMock(
            return_value={
                chunk_id: [
                    {
                        "segment_id": segment_id,
                        "block_order": 1,
                        "char_start": 0,
                        "char_end": 50,
                        "locator": "paragraph:1",
                        "block_type": "paragraph",
                    }
                ]
            }
        ),
    )

    result = await service.document_processing_results(
        db=None,  # type: ignore[arg-type]
        file_id=file_id,
        view="chunks",
        page=1,
        page_size=20,
        content_limit=100,
    )

    item = result["chunks"][0]
    assert item["content_preview"] == "X" * 100
    assert item["content_truncated"] is True
    assert item["source_blocks"][0]["segment_id"] == segment_id
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_processing_results_does_not_fallback_to_legacy_while_new_run_is_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = uuid4()
    extraction_id = uuid4()
    file_row = _file(file_id=file_id, status="queued")
    queued_run = _extraction(extraction_id, status="queued")

    monkeypatch.setattr(service, "get_file", AsyncMock(return_value=file_row))
    monkeypatch.setattr(service, "get_extraction_run", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service,
        "get_latest_extraction_run_any_status",
        AsyncMock(return_value=queued_run),
    )
    monkeypatch.setattr(service, "get_chunk_run", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service,
        "get_latest_chunk_run_any_status",
        AsyncMock(return_value=None),
    )
    list_blocks = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(service, "list_current_raw_block_previews", list_blocks)

    result = await service.document_processing_results(
        db=None,  # type: ignore[arg-type]
        file_id=file_id,
        view="raw_blocks",
        page=1,
        page_size=20,
        content_limit=100,
    )

    assert result["legacy"] is False
    assert result["raw_blocks"] == []
    list_blocks.assert_awaited_once()
    assert list_blocks.await_args.kwargs["allow_legacy"] is False
