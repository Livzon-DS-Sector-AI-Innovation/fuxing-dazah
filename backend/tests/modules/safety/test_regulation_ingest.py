"""法规收录契约①接收端点测试 — 接缝：HTTP 端点级（AsyncClient+ASGITransport）。

外部依赖全 mock：Bitable（预去重读台账）走 monkeypatch 替换 service 命名空间
的 BitableWriter；app_config 走 setenv（autouse stub 已隔离 DB 层）。
留痕验证通过响应行为（幂等重放返回同一 run_log_id）间接断言。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

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
    """BitableWriter 替身：双表返回预设记录；write_regulation 可预设返回。"""

    def __init__(
        self,
        safety_records: list[dict[str, Any]],
        env_records: list[dict[str, Any]] | None = None,
        write_result: dict[str, Any] | None = None,
        write_raises: Exception | None = None,
    ) -> None:
        self.safety_bitable = _FakeBitableClient(safety_records)
        self.env_bitable = _FakeBitableClient(env_records or [])
        self.write_result = write_result
        self.write_raises = write_raises
        self.write_calls: list[str] = []

    async def write_regulation(self, item) -> dict[str, Any] | None:
        self.write_calls.append(item.title)
        if self.write_raises:
            raise self.write_raises
        return self.write_result


class _FakeLifecycleClient:
    """契约②回执客户端替身：记录调用；可预设失败。"""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raises = raises

    async def send_lifecycle(self, candidate_id, action, reason="", replace_candidate_id=None):
        if self.raises:
            raise self.raises
        self.calls.append({
            "candidate_id": candidate_id, "action": action, "reason": reason,
            "replace_candidate_id": replace_candidate_id,
        })
        return {"ok": True}

    async def get_crawler_status(self):
        return {"sources": [], "runs": []}


def _use_receipts(monkeypatch, client: _FakeLifecycleClient) -> _FakeLifecycleClient:
    monkeypatch.setattr(
        ingest_service, "get_ragplus_crawler_client", lambda: client,
    )
    return client


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
    """空台账 + 判定不可达 + 回执替身：预去重放行，AI 判定双路失败 → pending。"""
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: _FakeWriter([]))
    monkeypatch.setattr(
        ingest_service, "AIExtractor",
        lambda: _FakeExtractor(batch_results=[], fallback_relevant=None),
    )
    _use_receipts(monkeypatch, _FakeLifecycleClient())


@pytest.fixture
def push_off(monkeypatch: pytest.MonkeyPatch):
    """PushNotifier 替身：记录调用不真推。"""
    sent: list[Any] = []

    class _FakeNotifier:
        async def send_crawl_result_notification(self, result) -> None:
            sent.append(result)

    monkeypatch.setattr(ingest_service, "PushNotifier", _FakeNotifier)
    return sent


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

    @staticmethod
    def has_revision_indicator(title: str) -> bool:
        from app.modules.safety.regulation_crawler.engine.extractors import AIExtractor

        return AIExtractor.has_revision_indicator(title)


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
    # 相关条目进入执行链（03）：写入层去重兜底下 promote；不相关 reject
    assert results["cand-rel"]["action_taken"] == "promote"
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
    assert r["action_taken"] == "promote"
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
    _use_receipts(monkeypatch, _FakeLifecycleClient())
    payload = _payload(items=[{
        "candidate_id": "cand-new-ver",
        "source": "samr",
        "url": "https://example.samr.gov.cn/gb/30871",
        "title": "GB 30871-2026 危险化学品企业特殊作业安全规范",
    }])
    resp = await client.post(_ENDPOINT, json=payload)
    data = resp.json()["data"]
    # 放行后判定相关 → 执行链（写入 None=去重兜底 → promote 转正）
    assert data["results"][0]["action_taken"] == "promote"


# ── 收录执行链（Ticket 03） ─────────────────────────────────


def _rel_verdict(idx: int = 0, score: float = 0.9) -> _FakeExtractor:
    return _FakeExtractor(batch_results=[
        {"index": idx, "content_type": "regulation", "relevance_score": score,
         "impact_level": "高", "business_domains": ["安全生产"], "core_summary": "相关法规"},
    ])


def _use_write(
    monkeypatch, writer: _FakeWriter, extractor: _FakeExtractor | None = None,
) -> _FakeWriter:
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: writer)
    if extractor is not None:
        monkeypatch.setattr(ingest_service, "AIExtractor", lambda: extractor)
    return writer


async def test_promote_full_chain(client, gate_on, empty_ledger, monkeypatch, push_off):
    """判定相关 → 写台账 → promote 回执 → 结果带 record_id。"""
    writer = _use_write(monkeypatch, _FakeWriter(
        [], write_result={"record_id": "rec-1", "shared_url": "https://feishu/rec-1",
                          "action": "created"},
    ), _rel_verdict())
    receipts = _use_receipts(monkeypatch, _FakeLifecycleClient())

    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "promote"
    assert r["bitable_record_id"] == "rec-1"
    assert writer.write_calls  # 台账确实被写
    assert receipts.calls[0]["action"] == "promote"
    assert receipts.calls[0]["candidate_id"] == "cand-rel"


async def test_reject_sends_receipt_not_write(client, gate_on, empty_ledger, monkeypatch, push_off):
    """判定不相关 → reject 回执，不写台账。"""
    writer = _use_write(monkeypatch, _FakeWriter(
        [], write_result={"record_id": "rec-x", "action": "created"},
    ), _FakeExtractor(batch_results=[
        {"index": 0, "content_type": "regulation", "relevance_score": 0.1},
    ]))
    receipts = _use_receipts(monkeypatch, _FakeLifecycleClient())

    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "reject"
    assert writer.write_calls == []
    assert receipts.calls[0]["action"] == "reject"


async def test_revision_orchestration(client, gate_on, empty_ledger, monkeypatch, push_off):
    """修订场景：台账旧版存在 → 写入（updated）+ promote 回执 reason 注明替代。"""
    old_record = {"fields": {
        "法律法规及标准名称": "危险化学品安全管理条例",
        "颁布修订日期": 1600000000000,
    }}
    writer = _use_write(monkeypatch, _FakeWriter(
        [old_record],
        write_result={"record_id": "rec-new", "shared_url": "u", "action": "updated"},
    ), _rel_verdict())
    receipts = _use_receipts(monkeypatch, _FakeLifecycleClient())

    item = _two_items()[0]  # 标题含「（修订）」→ 修订指示
    resp = await client.post(_ENDPOINT, json=_payload(items=[item]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "promote"
    assert "修订替代《危险化学品安全管理条例》" in r["reason"]
    assert writer.write_calls  # 删旧写新由 writer 执行（此处 mock 验证调用发生）
    assert receipts.calls[0]["action"] == "promote"
    assert "修订替代" in receipts.calls[0]["reason"]


async def test_receipt_failure_tolerated(client, gate_on, empty_ledger, monkeypatch, push_off):
    """回执失败不阻断：收录仍 promote，reason 注记失败，本批其余候选不受影响。"""
    _use_write(monkeypatch, _FakeWriter(
        [], write_result={"record_id": "rec-1", "shared_url": "u", "action": "created"},
    ), _FakeExtractor(batch_results=[
        {"index": 0, "content_type": "regulation", "relevance_score": 0.9},
        {"index": 1, "content_type": "regulation", "relevance_score": 0.1},
    ]))
    _use_receipts(monkeypatch, _FakeLifecycleClient(raises=RuntimeError("ragplus down")))

    resp = await client.post(_ENDPOINT, json=_payload(items=_two_items()))
    results = {r["candidate_id"]: r for r in resp.json()["data"]["results"]}
    assert results["cand-rel"]["action_taken"] == "promote"
    assert "回执失败" in results["cand-rel"]["reason"]
    assert results["cand-irr"]["action_taken"] == "reject"
    assert "回执失败" in results["cand-irr"]["reason"]


async def test_write_failure_marks_error(client, gate_on, empty_ledger, monkeypatch, push_off):
    """台账写入抛错 → error 留痕，不发回执（留待对账补处理）。"""
    _use_write(monkeypatch, _FakeWriter(
        [], write_raises=RuntimeError("bitable quota"),
    ), _rel_verdict())
    receipts = _use_receipts(monkeypatch, _FakeLifecycleClient())

    resp = await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    r = resp.json()["data"]["results"][0]
    assert r["action_taken"] == "error"
    assert "台账写入失败" in r["reason"]
    assert receipts.calls == []


async def test_push_notification_sent_on_promote(client, gate_on, empty_ledger, monkeypatch, push_off):
    """有收录成功 → 批次飞书推送发生（推送失败不阻断）。"""
    _use_write(monkeypatch, _FakeWriter(
        [], write_result={"record_id": "rec-1", "shared_url": "u", "action": "created"},
    ), _rel_verdict())
    _use_receipts(monkeypatch, _FakeLifecycleClient())

    await client.post(_ENDPOINT, json=_payload(items=[_two_items()[0]]))
    assert len(push_off) == 1
    assert push_off[0].new_count == 1


async def test_promote_doc_map_registered(db_session, monkeypatch, push_off):
    """doc_map 登记：promote 写台账成功后 upsert regulation 域映射（直调接缝）。"""
    from app.modules.safety.models import RagplusDocMap
    from app.modules.safety.regulation_ingest.schemas import IngestCandidatesRequest

    monkeypatch.setenv(_ENABLED_KEY, "1")
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: _FakeWriter(
        [], write_result={"record_id": "rec-map-1", "shared_url": "u", "action": "created"},
    ))
    monkeypatch.setattr(ingest_service, "AIExtractor", lambda: _rel_verdict())
    _use_receipts(monkeypatch, _FakeLifecycleClient())

    service = ingest_service.RegulationIngestService(db_session)
    resp = await service.ingest_candidates(IngestCandidatesRequest(**_payload()))
    assert resp.results[0].action_taken == "promote"

    row = (await db_session.execute(
        select(RagplusDocMap).where(
            RagplusDocMap.domain == "regulation",
            RagplusDocMap.biz_key == "rec-map-1",
        )
    )).scalar_one_or_none()
    assert row is not None
    assert row.status == "active"
    assert row.dataset_name == "安全法规标准"
