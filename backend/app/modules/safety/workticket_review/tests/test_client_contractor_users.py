"""WorkTicketPlatformClient.list_contractor_users 单测。

沿用 test_client_range.FakeClient 模式：覆写 _request_json 返回内存分页响应，
覆盖：多页聚合停页条件、name 过滤参数、非成功 code 抛错、分页防御上限。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.workticket_review.client import WorkTicketPlatformClient


def _page(total: int, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"code": 200, "data": {"total": total, "records": records}}


class FakeContractorClient(WorkTicketPlatformClient):
    """内存客户端：记录请求并按序返回预设分页响应（耗尽后重复最后一页）。"""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._platform_token = "fake-platform-token"
        self._lcp_token = "fake-lcp-token"
        self._client = None
        self._owns_client = False
        self._pages = pages
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

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
        self.calls.append((method, url, json_body))
        idx = min(len(self.calls) - 1, len(self._pages) - 1)
        return self._pages[idx]


@pytest.mark.asyncio
async def test_multi_page_aggregation() -> None:
    pages = [
        _page(3, [{"id": "1", "name": "甲"}, {"id": "2", "name": "乙"}]),
        _page(3, [{"id": "3", "name": "丙"}]),
    ]
    client = FakeContractorClient(pages)
    users = await client.list_contractor_users()

    assert [u["id"] for u in users] == ["1", "2", "3"]
    assert len(client.calls) == 2
    method, url, body = client.calls[0]
    assert method == "POST"
    assert url.endswith("/api/tiji-master-data/client/contractor-user/all-page")
    assert body == {"current": 1, "size": 100}
    assert client.calls[1][2] == {"current": 2, "size": 100}


@pytest.mark.asyncio
async def test_single_page_stops_early() -> None:
    client = FakeContractorClient([_page(1, [{"id": "1"}])])
    users = await client.list_contractor_users()
    assert len(users) == 1
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_name_filter_forwarded() -> None:
    client = FakeContractorClient([_page(1, [{"id": "9", "name": "何胜"}])])
    users = await client.list_contractor_users(name="何胜")
    assert users[0]["name"] == "何胜"
    assert client.calls[0][2] == {"current": 1, "size": 100, "name": "何胜"}


@pytest.mark.asyncio
async def test_error_code_raises() -> None:
    client = FakeContractorClient([{"code": 400, "msg": "缺少必要的请求参数"}])
    with pytest.raises(RuntimeError, match="承包商人员台账接口返回失败"):
        await client.list_contractor_users()


@pytest.mark.asyncio
async def test_max_pages_defense() -> None:
    # total 恒大于已取数（异常场景），触发防御上限
    client = FakeContractorClient(
        [_page(10_000, [{"id": str(i)} for i in range(100)])]
    )
    client._CONTRACTOR_USER_MAX_PAGES = 2
    with pytest.raises(RuntimeError, match="防御上限"):
        await client.list_contractor_users()
    assert len(client.calls) == 2
