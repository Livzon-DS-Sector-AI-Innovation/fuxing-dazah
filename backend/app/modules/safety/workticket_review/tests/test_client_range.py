"""WorkTicketPlatformClient.list_tickets_for_date_range 单测。

夹具沿用 workticket_review/tests 既有风格（《作业票字段映射.md》实测样例），
以 FakeClient 注入内存响应，覆盖：落窗判定（createTime 边界 / serialNumber 含窗口日期）、
按 processInstanceId 去重、8 类票覆盖、空窗口、detail 富化仅一次、返回结构与单日方法一致。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.safety.workticket_review.client import (
    STANDARD_TICKET_TYPES,
    WorkTicketPlatformClient,
)


def _record(
    pid: str,
    serial: str,
    create_time: str,
    *,
    ticket_type: str = "hot_work",
    status: str = "已完成",
    end_time: str | None = "2026-08-26 18:00:00",
) -> dict[str, Any]:
    """构造一条 all-list 原始记录（字段名与平台实测返回一致）。"""
    return {
        "type": ticket_type,
        "processInstanceId": pid,
        "serialNumber": serial,
        "createTime": create_time,
        "endTime": end_time,
        "status": status,
        "variables": {},
        "raw": {},
    }


class FakeClient(WorkTicketPlatformClient):
    """内存版客户端：all-list 按 processDefinitionKey 返回预设 body，detail 返回预设 variables。"""

    def __init__(
        self,
        list_payloads: dict[str, dict[str, Any]],
        detail_variables: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        # 直接注入缓存 token，避免触发真实鉴权（_ensure_tokens 命中缓存即返回）
        self._platform_token = "fake-platform-token"
        self._lcp_token = "fake-lcp-token"
        self._list_payloads = list_payloads
        self._detail_variables = detail_variables or {}
        self.requested_keys: list[str] = []
        self.detail_pids: list[str] = []

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        assert headers, "必须携带工作流请求头"
        params = params or {}
        if url.endswith("/all-list"):
            key = params.get("processDefinitionKey")
            assert isinstance(key, str), "all-list 必须携带 processDefinitionKey"
            self.requested_keys.append(key)
            return self._list_payloads.get(key, {"data": {"records": []}})
        if url.endswith("/detail"):
            pid = str(params.get("processInstanceId") or "")
            self.detail_pids.append(pid)
            return {"data": {"process": {"variables": self._detail_variables.get(pid, {})}}}
        raise AssertionError(f"unexpected url: {url}")


RESULT_KEYS = {
    "type",
    "processInstanceId",
    "serialNumber",
    "createTime",
    "endTime",
    "status",
    "variables",
    "raw",
}

WINDOW = (date(2026, 8, 1), date(2026, 9, 30))


@pytest.fixture
def window() -> tuple[date, date]:
    return WINDOW


async def test_range_fetches_all_8_standard_ticket_types(window: tuple[date, date]) -> None:
    payloads: dict[str, dict[str, Any]] = {}
    for ticket_type, process_key in STANDARD_TICKET_TYPES:
        payloads[process_key] = {
            "data": {
                "records": [
                    _record(
                        f"pi-{ticket_type}-001",
                        f"SN-{ticket_type}-001",
                        "2026-08-15 10:00:00",
                        ticket_type=ticket_type,
                    )
                ]
            }
        }
    client = FakeClient(payloads)

    results = await client.list_tickets_for_date_range(*window)

    assert len(client.requested_keys) == len(STANDARD_TICKET_TYPES)
    assert set(client.requested_keys) == {key for _, key in STANDARD_TICKET_TYPES}
    assert {r["type"] for r in results} == {t for t, _ in STANDARD_TICKET_TYPES}
    assert len(results) == len(STANDARD_TICKET_TYPES)


async def test_range_result_keys_match_single_date_method(window: tuple[date, date]) -> None:
    payloads: dict[str, dict[str, Any]] = {}
    for ticket_type, process_key in STANDARD_TICKET_TYPES:
        payloads[process_key] = {
            "data": {
                "records": [
                    _record(
                        f"pi-{ticket_type}-001",
                        f"SN-{ticket_type}-001",
                        "2026-08-15 10:00:00",
                    )
                ]
            }
        }
    client = FakeClient(payloads)

    results = await client.list_tickets_for_date_range(*window)

    assert results
    for entry in results:
        assert set(entry) == RESULT_KEYS
        assert entry["raw"] is not None
        assert "serialNumber" in entry["variables"] or entry["variables"] == {}


async def test_range_includes_create_time_boundaries(window: tuple[date, date]) -> None:
    key = STANDARD_TICKET_TYPES[0][1]
    payloads = {
        key: {
            "data": {
                "records": [
                    _record("pi-start", "SN-1", "2026-08-01 00:00:00"),
                    _record("pi-end", "SN-2", "2026-09-30 23:59:59"),
                    _record("pi-before", "SN-3", "2026-07-31 23:59:59"),
                    _record("pi-after", "SN-4", "2026-10-01 00:00:00"),
                ]
            }
        }
    }
    client = FakeClient(payloads)

    results = await client.list_tickets_for_date_range(*window)

    assert {r["processInstanceId"] for r in results} == {"pi-start", "pi-end"}


async def test_range_includes_record_by_serial_number_date(window: tuple[date, date]) -> None:
    key = STANDARD_TICKET_TYPES[0][1]
    payloads = {
        key: {
            "data": {
                "records": [
                    # createTime 在窗口外，但票号「DH-20260826-009」含窗口内日期 2026-08-26
                    _record("pi-serial-hit", "DH-20260826-009", "2026-10-01 10:00:00"),
                    # 票号日期与 createTime 均在窗口外
                    _record("pi-serial-miss", "DH-20261005-001", "2026-10-01 10:00:00"),
                    # createTime 命中（票号反而在窗口外）
                    _record("pi-create-hit", "DH-20261001-001", "2026-08-26 10:00:00"),
                ]
            }
        }
    }
    client = FakeClient(payloads)

    results = await client.list_tickets_for_date_range(*window)

    assert {r["processInstanceId"] for r in results} == {"pi-serial-hit", "pi-create-hit"}


async def test_range_dedup_by_process_instance_id(window: tuple[date, date]) -> None:
    """同一 processInstanceId 出现在多个票类列表时只保留一条。"""
    payloads: dict[str, dict[str, Any]] = {}
    for index, (_, process_key) in enumerate(STANDARD_TICKET_TYPES):
        payloads[process_key] = {
            "data": {"records": [_record("pi-shared", f"SN-{index}", "2026-08-26 10:00:00")]}
        }
    client = FakeClient(payloads)

    results = await client.list_tickets_for_date_range(*window)

    assert len(results) == 1
    assert results[0]["processInstanceId"] == "pi-shared"
    assert client.detail_pids.count("pi-shared") == 1


async def test_range_inverted_window_returns_empty() -> None:
    client = FakeClient({})

    results = await client.list_tickets_for_date_range(date(2026, 8, 31), date(2026, 8, 1))

    assert results == []
    assert client.requested_keys == []


async def test_range_no_match_in_window_returns_empty(window: tuple[date, date]) -> None:
    payloads: dict[str, dict[str, Any]] = {}
    for _, process_key in STANDARD_TICKET_TYPES:
        payloads[process_key] = {
            "data": {"records": [_record("pi-x", "SN-X", "2026-10-01 10:00:00")]}
        }
    client = FakeClient(payloads)

    results = await client.list_tickets_for_date_range(*window)

    assert results == []


async def test_range_enrich_detail_once_per_unique_pid(window: tuple[date, date]) -> None:
    first_key = STANDARD_TICKET_TYPES[0][1]
    second_key = STANDARD_TICKET_TYPES[1][1]
    payloads = {
        first_key: {
            "data": {
                "records": [
                    _record("pi-e1", "SN-E1", "2026-08-26 10:00:00"),
                    _record("pi-e2", "SN-E2", "2026-08-26 11:00:00"),
                ]
            }
        },
        second_key: {
            "data": {
                "records": [
                    # 与 first 列表中的 pi-e1 重复，应被去重且不再触发 detail
                    _record("pi-e1", "SN-E1-dup", "2026-08-26 12:00:00"),
                ]
            }
        },
    }
    client = FakeClient(
        payloads,
        detail_variables={"pi-e1": {"guardian": "张三"}, "pi-e2": {"guardian": "李四"}},
    )

    results = await client.list_tickets_for_date_range(*window)

    assert {r["processInstanceId"] for r in results} == {"pi-e1", "pi-e2"}
    assert client.detail_pids.count("pi-e1") == 1
    assert client.detail_pids.count("pi-e2") == 1
    by_pid = {r["processInstanceId"]: r for r in results}
    assert by_pid["pi-e1"]["variables"]["guardian"] == "张三"
    assert by_pid["pi-e2"]["variables"]["guardian"] == "李四"
