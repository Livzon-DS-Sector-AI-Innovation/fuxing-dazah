"""P2-3 T01 附件缓存 exists 短路 —— download_photos 重复下载消除。

覆盖 ticket 01 验收：
- exists 命中（本地/MinIO 任一形态）→ 零网络下载（策略 1/2/3 均不触发），
  直接返回存量存储标识；
- exists 未命中 → 走原三级回退下载并照常 store_bytes（既有行为回归）；
- 开关 SAFETY_HAZARD_ATTACHMENT_CACHE_ENABLED=false → 不探测 exists，
  行为与现状一致（重新下载）；
- 探测异常容忍：exists 抛错视为 miss 继续下载（缓存故障不影响业务）。

全部 fake：不连真实网络 / DB / Redis / Bitable / 文件系统。
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from app.modules.safety.service.hazard_direct import bitable_repo

CACHE_KEY = "SAFETY_HAZARD_ATTACHMENT_CACHE_ENABLED"


# ═══════════════════════════════════════════════════════════════
# 公共 fake / 辅助
# ═══════════════════════════════════════════════════════════════


class _FakeClient:
    """计数每条下载策略调用的假 Bitable client。"""

    def __init__(self, *, url_bytes: bytes | None = b"IMG", drive_bytes: bytes | None = None):
        self.table_id = "tblFake"
        self.url_calls = 0
        self.drive_calls = 0
        self._url_bytes = url_bytes
        self._drive_bytes = drive_bytes

    async def download_attachment_from_url(self, url: str) -> bytes:
        self.url_calls += 1
        if self._url_bytes is None:
            raise RuntimeError("url download failed")
        return self._url_bytes

    async def download_attachment(self, file_token: str, *, extra: str | None = None) -> bytes:
        self.drive_calls += 1
        if self._drive_bytes is None:
            raise RuntimeError("drive download failed")
        return self._drive_bytes


def _record_with_defect_attachment(*, file_token: str = "tokabcdef1234567890", name: str = "IMG_001.jpg") -> dict[str, Any]:
    return {
        "record_id": "recFAKE01",
        "fields": {
            "缺陷图片": [
                {
                    "file_token": file_token,
                    "name": name,
                    "url": "https://open.feishu.cn/open-apis/drive/v1/medias/fake/download",
                    "tmp_url": "",
                    "type": "image/jpeg",
                }
            ]
        },
    }


@pytest.fixture()
def store_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """劫持 attachment_store.exists/store_bytes 收集调用并可控返回。

    download_photos 在函数体内延迟 import，patch 模块属性即可生效。
    """
    import app.modules.safety.attachment_store as att_store

    state: dict[str, Any] = {
        "exists_calls": [],       # 全部探测过的存储标识
        "stored": [],             # store_bytes 落盘的 (subdir, filename, bytes)
        "exists_result": False,   # 默认 miss
        "exists_raise": False,
    }

    def _exists(path_or_key: str) -> bool:
        state["exists_calls"].append(path_or_key)
        if state["exists_raise"]:
            raise RuntimeError("exists probe broken")
        return bool(state["exists_result"])

    def _store_bytes(subdir: str, filename: str, data: bytes, content_type: str = "") -> str:
        state["stored"].append((subdir, filename, data))
        return f"{subdir}/{filename}"

    monkeypatch.setattr(att_store, "exists", _exists)
    monkeypatch.setattr(att_store, "store_bytes", _store_bytes)
    return state


# ═══════════════════════════════════════════════════════════════
# 行为测试
# ═══════════════════════════════════════════════════════════════


async def test_exists_hit_skips_download(
    store_spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓存命中：零网络下载，返回存量标识。"""
    monkeypatch.setenv(CACHE_KEY, "true")
    store_spy["exists_result"] = True
    client = _FakeClient()
    record = _record_with_defect_attachment()

    saved = await bitable_repo.download_photos(
        cast(Any, client), record["fields"], record_id=record["record_id"],
        include_rectification=False,
    )

    assert client.url_calls == 0 and client.drive_calls == 0, "命中缓存仍发起下载"
    assert len(saved["defect"]) == 1
    # 返回的路径 = 首个探测命中的候选（本地形态优先），键形 direct_<record>_<token12>_<name>
    probed = store_spy["exists_calls"]
    assert probed and saved["defect"][0] == probed[0], (saved["defect"], probed)
    assert "direct_recFAKE01_tokabcdef123_IMG_001.jpg" in saved["defect"][0]
    assert store_spy["stored"] == [], "命中缓存不应重复落盘"


async def test_exists_miss_downloads_and_stores(
    store_spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓存未命中：原三级回退下载 + 照常 store_bytes（既有行为）。"""
    monkeypatch.setenv(CACHE_KEY, "true")
    client = _FakeClient()
    record = _record_with_defect_attachment()

    saved = await bitable_repo.download_photos(
        cast(Any, client), record["fields"], record_id=record["record_id"],
        include_rectification=False,
    )

    assert client.url_calls == 1, "未命中应走 URL 策略下载一次"
    assert len(saved["defect"]) == 1
    assert len(store_spy["stored"]) == 1
    subdir, filename, data = store_spy["stored"][0]
    assert subdir == "hazard" and data == b"IMG"
    assert filename.startswith("direct_recFAKE01_tokabcdef123_")


async def test_cache_disabled_redownloads_even_if_cached(
    store_spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关关：不探测 exists，行为与现状一致（重新下载）。"""
    monkeypatch.setenv(CACHE_KEY, "false")
    store_spy["exists_result"] = True  # 即使存量存在也不许短路
    client = _FakeClient()
    record = _record_with_defect_attachment()

    saved = await bitable_repo.download_photos(
        cast(Any, client), record["fields"], record_id=record["record_id"],
        include_rectification=False,
    )

    assert store_spy["exists_calls"] == [], "开关关闭时不应探测缓存"
    assert client.url_calls == 1, "开关关闭时应照常下载"
    assert len(saved["defect"]) == 1


async def test_exists_probe_error_falls_back_to_download(
    store_spy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """探测异常容忍：视为 miss 继续下载（缓存故障不影响业务）。"""
    monkeypatch.setenv(CACHE_KEY, "true")
    store_spy["exists_raise"] = True
    client = _FakeClient()
    record = _record_with_defect_attachment()

    saved = await bitable_repo.download_photos(
        cast(Any, client), record["fields"], record_id=record["record_id"],
        include_rectification=False,
    )

    assert client.url_calls == 1, "探测异常应回退下载"
    assert len(saved["defect"]) == 1
    assert len(store_spy["stored"]) == 1
