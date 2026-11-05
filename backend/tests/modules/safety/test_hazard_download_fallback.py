"""T10 F10：附件下载三级回退 + field_id 缓存键修复（spec B7-4 / S9）— TDD 测试。

接缝：``bitable_repo.download_photos`` 只依赖注入的假 Bitable client
（预签名 url / tmp_url / Drive API 三个下载边界），``store_bytes`` 用假件替代
落盘；不访问真实网络/真实文件存储。``_field_id_cache`` 是进程级模块变量，
用例间必须清空隔离。

覆盖：
1. 预签名 url 失败 → tmp_url 成功；
2. url + tmp_url 均失败 → file_token + extra（Drive API）成功，extra 含
   tableId / record_id / field_id / file_token 鉴权参数；
3. 三级全失败 → 返回空且不抛；
4. field_id 获取失败不缓存空串（下次调用可重试）；
5. ``_field_id_cache`` 按 (table_id, field_name) 分键：多表互不串用，成功值缓存。
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from typing import Any, cast

import pytest

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.service.hazard_direct import bitable_repo

_URL = "https://example.test/defect.jpg"
_TMP_URL = "https://example.test/defect-tmp.jpg"


class _FakeAttachmentClient:
    """假 Bitable 附件客户端：三级下载策略的每个外部边界都可注入行为。"""

    def __init__(
        self,
        *,
        table_id: str = "tbl_test",
        fail_urls: frozenset[str] = frozenset(),
        ok_urls: dict[str, bytes] | None = None,
        field_ids: list[str | None] | None = None,
        drive_result: bytes | None = None,
    ) -> None:
        self.table_id = table_id
        self.fail_urls = fail_urls
        self.ok_urls = dict(ok_urls or {})
        self.field_ids = list(field_ids) if field_ids is not None else ["fld_defect"]
        self.drive_result = drive_result
        self.url_calls: list[str] = []
        self.drive_calls: list[tuple[str, str | None]] = []
        self.field_id_calls: list[str] = []

    async def download_attachment_from_url(self, url: str) -> bytes | None:
        self.url_calls.append(url)
        if url in self.fail_urls:
            raise RuntimeError("预签名 url 过期")
        return self.ok_urls.get(url)

    async def get_field_id_by_name(self, field_name: str) -> str | None:
        self.field_id_calls.append(field_name)
        index = min(len(self.field_id_calls) - 1, len(self.field_ids) - 1)
        return self.field_ids[index]

    async def download_attachment(
        self, file_token: str, extra: str | None = None
    ) -> bytes | None:
        self.drive_calls.append((file_token, extra))
        return self.drive_result


def _as_client(fake: _FakeAttachmentClient) -> SafetyBitableClient:
    """假客户端只实现下载协议；类型上转到真实签名以复用严格 mypy 检查。"""
    return cast(SafetyBitableClient, fake)


def _attachment_fields() -> dict[str, Any]:
    """缺陷图附件元数据（search 返回的形态：url + tmp_url + file_token）。"""
    return {
        "缺陷图片": [
            {
                "file_token": "tok_defect",
                "name": "defect.jpg",
                "url": _URL,
                "tmp_url": _TMP_URL,
                "type": "image/jpeg",
            }
        ]
    }


def _decode_extra(extra: str) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(urllib.parse.unquote(extra))
    return decoded


@pytest.fixture(autouse=True)
def clear_field_id_cache() -> Iterator[None]:
    """field_id 缓存是进程级模块变量，用例间隔离。"""
    bitable_repo._field_id_cache.clear()
    yield
    bitable_repo._field_id_cache.clear()


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bytes]]:
    """替代同步落盘（store_bytes 延迟 import 自 attachment_store）。"""
    import app.modules.safety.attachment_store as attachment_store

    stored: list[tuple[str, bytes]] = []

    def _fake_store_bytes(
        bucket: str, name: str, data: bytes, **kwargs: Any
    ) -> str:
        stored.append((name, data))
        return f"/stored/{name}"

    monkeypatch.setattr(attachment_store, "store_bytes", _fake_store_bytes)
    return stored


# ═══════════════════════════════════════════════════════════════
# 1/2/3. 三级下载回退
# ═══════════════════════════════════════════════════════════════


async def test_falls_back_to_tmp_url_when_presigned_url_fails(
    fake_store: list[tuple[str, bytes]],
) -> None:
    client = _FakeAttachmentClient(
        fail_urls=frozenset({_URL}), ok_urls={_TMP_URL: b"tmp-bytes"}
    )

    saved = await bitable_repo.download_photos(
        _as_client(client),
        _attachment_fields(),
        record_id="rec-1",
        include_rectification=False,
    )

    assert client.url_calls == [_URL, _TMP_URL]  # 策略 1 失败后尝试策略 2
    assert client.drive_calls == []  # 未降级到 Drive API
    assert len(saved["defect"]) == 1
    assert saved["rectification"] == []
    assert fake_store and fake_store[0][1] == b"tmp-bytes"


async def test_falls_back_to_file_token_extra_when_both_urls_fail(
    fake_store: list[tuple[str, bytes]],
) -> None:
    client = _FakeAttachmentClient(
        fail_urls=frozenset({_URL, _TMP_URL}),
        field_ids=["fld_defect"],
        drive_result=b"drive-bytes",
    )

    saved = await bitable_repo.download_photos(
        _as_client(client),
        _attachment_fields(),
        record_id="rec-1",
        include_rectification=False,
    )

    assert client.field_id_calls == ["缺陷图片"]
    assert len(client.drive_calls) == 1
    file_token, extra = client.drive_calls[0]
    assert file_token == "tok_defect"
    assert extra is not None
    permission = _decode_extra(extra)["bitablePerm"]
    assert permission["tableId"] == "tbl_test"
    assert permission["attachments"]["fld_defect"]["rec-1"] == ["tok_defect"]
    assert len(saved["defect"]) == 1
    assert fake_store and fake_store[0][1] == b"drive-bytes"


async def test_all_three_strategies_fail_returns_empty_without_raising(
    fake_store: list[tuple[str, bytes]],
) -> None:
    client = _FakeAttachmentClient(
        fail_urls=frozenset({_URL, _TMP_URL}),
        field_ids=["fld_defect"],
        drive_result=None,
    )

    saved = await bitable_repo.download_photos(
        _as_client(client),
        _attachment_fields(),
        record_id="rec-1",
        include_rectification=False,
    )

    assert saved == {"defect": [], "rectification": []}
    assert fake_store == []
    assert len(client.drive_calls) == 1  # 三级都试过，最终放弃


# ═══════════════════════════════════════════════════════════════
# 4/5. field_id 缓存：失败不缓存空串 + 按 (table_id, field_name) 分键
# ═══════════════════════════════════════════════════════════════


async def test_field_id_failure_not_cached_and_retryable(
    fake_store: list[tuple[str, bytes]],
) -> None:
    """首次 field_id 取不到 → 不带 extra 下载；下次调用重新取（空串不入缓存）。"""
    client = _FakeAttachmentClient(
        fail_urls=frozenset({_URL, _TMP_URL}),
        field_ids=[None, "fld_ok"],
        drive_result=b"drive-bytes",
    )

    first = await bitable_repo.download_photos(
        _as_client(client),
        _attachment_fields(),
        record_id="rec-1",
        include_rectification=False,
    )
    assert len(first["defect"]) == 1
    assert client.field_id_calls == ["缺陷图片"]
    assert client.drive_calls[0] == ("tok_defect", None)  # 失败 → 回退不带 extra

    second = await bitable_repo.download_photos(
        _as_client(client),
        _attachment_fields(),
        record_id="rec-1",
        include_rectification=False,
    )
    assert len(second["defect"]) == 1
    assert client.field_id_calls == ["缺陷图片", "缺陷图片"]  # 失败值未被缓存，重试
    second_extra = client.drive_calls[1][1]
    assert second_extra is not None
    assert _decode_extra(second_extra)["bitablePerm"]["attachments"]["fld_ok"]


async def test_field_id_cache_keyed_by_table_and_success_cached(
    fake_store: list[tuple[str, bytes]],
) -> None:
    """不同 table_id 各自缓存；同表同字段成功后命中缓存不再请求。"""
    client_a = _FakeAttachmentClient(
        table_id="tbl_a",
        fail_urls=frozenset({_URL, _TMP_URL}),
        field_ids=["fld_a"],
        drive_result=b"a-bytes",
    )
    client_b = _FakeAttachmentClient(
        table_id="tbl_b",
        fail_urls=frozenset({_URL, _TMP_URL}),
        field_ids=["fld_b"],
        drive_result=b"b-bytes",
    )

    await bitable_repo.download_photos(
        _as_client(client_a),
        _attachment_fields(),
        record_id="rec_1",
        include_rectification=False,
    )
    await bitable_repo.download_photos(
        _as_client(client_a),
        _attachment_fields(),
        record_id="rec_2",
        include_rectification=False,
    )
    await bitable_repo.download_photos(
        _as_client(client_b),
        _attachment_fields(),
        record_id="rec_3",
        include_rectification=False,
    )

    # 同表第二次命中缓存（成功值缓存）；不同表独立取一次
    assert client_a.field_id_calls == ["缺陷图片"]
    assert client_b.field_id_calls == ["缺陷图片"]

    extras_a = [
        _decode_extra(extra)["bitablePerm"]
        for _, extra in client_a.drive_calls
        if extra is not None
    ]
    assert [perm["tableId"] for perm in extras_a] == ["tbl_a", "tbl_a"]
    assert all("fld_a" in perm["attachments"] for perm in extras_a)

    extras_b = [
        _decode_extra(extra)["bitablePerm"]
        for _, extra in client_b.drive_calls
        if extra is not None
    ]
    assert [perm["tableId"] for perm in extras_b] == ["tbl_b"]
    assert "fld_b" in extras_b[0]["attachments"]
