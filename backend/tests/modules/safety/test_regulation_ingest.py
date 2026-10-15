"""法规收录契约①接收端点测试 — 接缝：HTTP 端点级（AsyncClient+ASGITransport）。

外部依赖全 mock：Bitable（预去重读台账）走 monkeypatch 替换 service 命名空间
的 BitableWriter；app_config 走 setenv（autouse stub 已隔离 DB 层）。
留痕验证通过响应行为（幂等重放返回同一 run_log_id）间接断言。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.regulation_ingest import service as ingest_service

_ENABLED_KEY = "SAFETY_REGULATION_CRAWLER_ENABLED"
_SECRET_KEY = "SAFETY_REGULATION_INGEST_SECRET"

_ENDPOINT = "/api/v1/safety/regulation-ingest/candidates"


# ── 测试基建 ────────────────────────────────────────────────


class _FakeBitableClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    async def list_all_records(self, page_size: int = 500) -> list[dict[str, Any]]:
        return self._records


class _FakeWriter:
    """BitableWriter 替身：safety/env 双表返回预设记录。"""

    def __init__(self, safety_records: list[dict[str, Any]], env_records=None) -> None:
        self.safety_bitable = _FakeBitableClient(safety_records)
        self.env_bitable = _FakeBitableClient(env_records or [])


def _payload(run_id: str = "run-001", items: list[dict[str, Any]] | None = None) -> dict:
    items = items if items is not None else [
        {
            "candidate_id": "cand-1",
            "source": "npc",
            "url": "https://example.gov.cn/law/1",
            "title": "中华人民共和国安全生产法（2021 修正）",
            "metadata": {"doc_no": "主席令第八十八号", "issued_at": "2021-06-10",
                         "puborg": "全国人大常委会", "effective_at": "2021-09-01"},
            "attachment": {"file_id": "file-1", "filename": "aqlaw.pdf"},
            "content_digest": "安全生产法修正全文摘要",
            "old_version_hint": None,
            "discovered_at": "2026-10-15T06:00:00+00:00",
        },
    ]
    return {"run_id": run_id, "items": items}


@pytest.fixture
def gate_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_ENABLED_KEY, "1")
    monkeypatch.delenv(_SECRET_KEY, raising=False)


@pytest.fixture
def empty_ledger(monkeypatch: pytest.MonkeyPatch):
    """空台账：预去重全部放行。"""
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: _FakeWriter([]))


# ── 鉴权 ────────────────────────────────────────────────────


async def test_secret_mismatch_rejected_401(client, gate_on, empty_ledger, monkeypatch):
    monkeypatch.setenv(_SECRET_KEY, "s3cret")
    resp = await client.post(_ENDPOINT, json=_payload(),
                             headers={"X-Ingest-Secret": "wrong"})
    assert resp.status_code == 401


async def test_secret_match_accepted(client, gate_on, empty_ledger, monkeypatch):
    monkeypatch.setenv(_SECRET_KEY, "s3cret")
    resp = await client.post(_ENDPOINT, json=_payload(),
                             headers={"X-Ingest-Secret": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["data"]["accepted"] is True


async def test_empty_secret_no_header_passes(client, gate_on, empty_ledger):
    """secret 未配置时不校验（沿用 webhook 先例），无 Header 也放行。"""
    resp = await client.post(_ENDPOINT, json=_payload())
    assert resp.status_code == 200
    assert resp.json()["data"]["accepted"] is True


# ── 总闸 ────────────────────────────────────────────────────


async def test_gate_disabled_skips_and_records(client, monkeypatch, empty_ledger):
    monkeypatch.delenv(_ENABLED_KEY, raising=False)
    resp = await client.post(_ENDPOINT, json=_payload())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["accepted"] is False
    assert data["reason"] == "disabled"
    assert data["run_log_id"]  # 留痕仍发生


async def test_gate_reenabled_reprocesses_same_run(client, gate_on, empty_ledger, monkeypatch):
    """总闸关闭的留痕不锚定幂等：开闸后重推同 run_id 应正常处理。"""
    monkeypatch.delenv(_ENABLED_KEY, raising=False)
    skipped = (await client.post(_ENDPOINT, json=_payload())).json()["data"]
    assert skipped["accepted"] is False

    monkeypatch.setenv(_ENABLED_KEY, "1")
    processed = (await client.post(_ENDPOINT, json=_payload())).json()["data"]
    assert processed["accepted"] is True
    assert processed["run_log_id"] != skipped["run_log_id"]


# ── 收录与幂等 ──────────────────────────────────────────────


async def test_new_batch_returns_pending(client, gate_on, empty_ledger):
    resp = await client.post(_ENDPOINT, json=_payload())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["accepted"] is True
    assert data["run_log_id"]
    assert len(data["results"]) == 1
    assert data["results"][0]["candidate_id"] == "cand-1"
    assert data["results"][0]["action_taken"] == "pending"


async def test_replay_idempotent(client, gate_on, empty_ledger):
    first = (await client.post(_ENDPOINT, json=_payload())).json()["data"]
    second = (await client.post(_ENDPOINT, json=_payload())).json()["data"]
    assert second["accepted"] is True
    assert second["run_log_id"] == first["run_log_id"]
    assert second["results"] == first["results"]


async def test_empty_items_batch(client, gate_on, empty_ledger):
    resp = await client.post(_ENDPOINT, json=_payload(items=[]))
    assert resp.status_code == 200
    assert resp.json()["data"]["results"] == []


# ── 预去重（vs Bitable 台账） ───────────────────────────────


def _ledger_item(title: str) -> dict[str, Any]:
    return {"fields": {"法律法规及标准名称": title}}


async def test_duplicate_exact_title(client, gate_on, monkeypatch):
    monkeypatch.setattr(
        ingest_service, "BitableWriter",
        lambda: _FakeWriter([_ledger_item("中华人民共和国安全生产法（2021 修正）")]),
    )
    resp = await client.post(_ENDPOINT, json=_payload())
    data = resp.json()["data"]
    assert data["results"][0]["action_taken"] == "duplicate"


async def test_duplicate_doc_no_from_metadata(client, gate_on, monkeypatch):
    """候选自带 metadata.doc_no 命中台账文号 → duplicate。

    文号提取口径=「国务院令/部委令」格式（XX令第N号）。
    """
    monkeypatch.setattr(
        ingest_service, "BitableWriter",
        lambda: _FakeWriter([_ledger_item("应急管理部令第5号 某安全管理办法")]),
    )
    payload = _payload(items=[{
        "candidate_id": "cand-doc",
        "source": "gov_cn",
        "url": "https://example.gov.cn/law/2",
        "title": "全新标题从未见过",
        "metadata": {"doc_no": "应急管理部令第5号"},
    }])
    resp = await client.post(_ENDPOINT, json=payload)
    data = resp.json()["data"]
    assert data["results"][0]["action_taken"] == "duplicate"


async def test_new_standard_edition_passes(client, gate_on, monkeypatch):
    """同标准号不同年份=新版，放行（待判定/修订编排）。"""
    monkeypatch.setattr(
        ingest_service, "BitableWriter",
        lambda: _FakeWriter([_ledger_item("GB 30871-2022 危险化学品企业特殊作业安全规范")]),
    )
    payload = _payload(items=[{
        "candidate_id": "cand-new-ver",
        "source": "samr",
        "url": "https://example.samr.gov.cn/gb/30871",
        "title": "GB 30871-2026 危险化学品企业特殊作业安全规范",
    }])
    resp = await client.post(_ENDPOINT, json=payload)
    data = resp.json()["data"]
    assert data["results"][0]["action_taken"] == "pending"
