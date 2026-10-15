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
    """空台账 + 判定不可达：预去重放行，AI 判定双路失败 → pending 留痕。"""
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: _FakeWriter([]))
    monkeypatch.setattr(
        ingest_service, "AIExtractor",
        lambda: _FakeExtractor(batch_results=[], fallback_relevant=None),
    )


# ── AI 批量判定（Ticket 02） ────────────────────────────────


class _FakeExtractor:
    """AIExtractor 替身：预设批量判定返回；可断言调用。"""

    def __init__(
        self,
        batch_results: list[dict[str, Any]] | None = None,
        batch_raises: bool = False,
        fallback_relevant: bool | None = None,
    ) -> None:
        self.batch_results = batch_results
        self.batch_raises = batch_raises
        self.fallback_relevant = fallback_relevant
        self.batch_called = False

    async def classify_and_assess_batch(self, items):
        self.batch_called = True
        if self.batch_raises:
            raise RuntimeError("ai down")
        return self.batch_results if self.batch_results is not None else []

    async def check_industry_relevance(self, title: str, summary: str = "") -> bool:
        if self.fallback_relevant is None:
            raise RuntimeError("fallback not configured")
        return bool(self.fallback_relevant)


def _use_extractor(monkeypatch, extractor: _FakeExtractor) -> _FakeExtractor:
    monkeypatch.setattr(ingest_service, "AIExtractor", lambda: extractor)
    return extractor


def _two_items() -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": "cand-rel",
            "source": "npc",
            "url": "https://example.gov.cn/1",
            "title": "危险化学品安全管理条例（修订）",
            "content_digest": "危险化学品安全管理条例修订全文，涉及生产储存使用经营运输安全管理要求。",
        },
        {
            "candidate_id": "cand-irr",
            "source": "npc",
            "url": "https://example.gov.cn/2",
            "title": "某市旅游业发展促进条例",
            "content_digest": "某市旅游业发展促进条例全文，涉及旅游产业发展与市场推广支持措施。",
        },
    ]


async def test_ai_relevant_pending_irrelevant_rejected(client, gate_on, empty_ledger, monkeypatch):
    _use_extractor(monkeypatch, _FakeExtractor(batch_results=[
        {"index": 0, "content_type": "regulation", "relevance_score": 0.92,
         "impact_level": "高", "business_domains": ["危化品管理"], "core_summary": "危化品管理"},
        {"index": 1, "content_type": "regulation", "relevance_score": 0.08,
         "impact_level": "低", "business_domains": [], "core_summary": ""},
    ]))
    resp = await client.post(_ENDPOINT, json=_payload(items=_two_items()))
    results = {r["candidate_id"]: r for r in resp.json()["data"]["results"]}
    assert results["cand-rel"]["action_taken"] == "pending"
    assert "判定相关" in results["cand-rel"]["reason"]
    assert results["cand-irr"]["action_taken"] == "reject"
    assert "score=0.08" in results["cand-irr"]["reason"]


async def test_ai_non_regulation_rejected(client, gate_on, empty_ledger, monkeypatch):
    _use_extractor(monkeypatch, _FakeExtractor(batch_results=[
        {"index": 0, "content_type": "news", "relevance_score": 0.9},
    ]))
    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "reject"
    assert "非法规" in r["reason"]


async def test_ai_budget_exceeded_marks_pending(client, gate_on, empty_ledger, monkeypatch):
    """预算护栏：预估超限 → 全部 pending 且不发起 AI 调用。"""
    monkeypatch.setenv("SAFETY_REGULATION_CRAWLER_MAX_AI_TOKENS_PER_RUN", "1")
    extractor = _use_extractor(monkeypatch, _FakeExtractor(batch_results=[
        {"index": 0, "content_type": "regulation", "relevance_score": 0.9},
    ]))
    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "pending"
    assert "预算超限" in r["reason"]
    assert extractor.batch_called is False


async def test_ai_batch_fail_fallback_per_item(client, gate_on, empty_ledger, monkeypatch):
    """批量失败 → 逐条回退（行业相关性终判）。"""
    _use_extractor(monkeypatch, _FakeExtractor(
        batch_raises=True, fallback_relevant=False,
    ))
    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "reject"
    assert "逐条回退" in r["reason"]


async def test_ai_fallback_relevant_pending(client, gate_on, empty_ledger, monkeypatch):
    _use_extractor(monkeypatch, _FakeExtractor(
        batch_results=[], fallback_relevant=True,
    ))
    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "pending"
    assert "逐条回退" in r["reason"]


async def test_duplicate_skips_ai_entirely(client, gate_on, monkeypatch):
    """去重命中的条目不进入 AI 判定（省 token）。"""
    monkeypatch.setattr(
        ingest_service, "BitableWriter",
        lambda: _FakeWriter([_ledger_item("危险化学品安全管理条例（修订）")]),
    )
    extractor = _use_extractor(monkeypatch, _FakeExtractor(batch_results=[
        {"index": 0, "content_type": "regulation", "relevance_score": 0.9},
    ]))
    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "duplicate"
    assert extractor.batch_called is False


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
    _use_extractor(monkeypatch, _FakeExtractor(
        batch_results=[{"index": 0, "content_type": "regulation", "relevance_score": 0.9}],
    ))
    payload = _payload(items=[{
        "candidate_id": "cand-new-ver",
        "source": "samr",
        "url": "https://example.samr.gov.cn/gb/30871",
        "title": "GB 30871-2026 危险化学品企业特殊作业安全规范",
    }])
    resp = await client.post(_ENDPOINT, json=payload)
    data = resp.json()["data"]
    assert data["results"][0]["action_taken"] == "pending"
