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
        from app.modules.safety.regulation_ingest.extractors import AIExtractor

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


async def test_replay_idempotent_no_duplicate_side_effects(
    client, gate_on, empty_ledger, monkeypatch, push_off,
):
    """同批重放：命中留痕直接返回既有结果，不重复写台账/回执/推送。"""
    writer = _use_write(monkeypatch, _FakeWriter(
        [], write_result={"record_id": "rec-1", "shared_url": "u", "action": "created"},
    ), _rel_verdict())
    receipts = _use_receipts(monkeypatch, _FakeLifecycleClient())

    first = (await client.post(_ENDPOINT, json=_payload())).json()["data"]
    second = (await client.post(_ENDPOINT, json=_payload())).json()["data"]
    assert second["accepted"] is True
    assert second["run_log_id"] == first["run_log_id"]
    assert second["results"] == first["results"]
    assert len(writer.write_calls) == 1      # 台账只写一次
    assert len(receipts.calls) == 1          # 回执只发一次
    assert len(push_off) == 1                # 推送只发一次


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


# ── 监控聚合端点（Ticket 04） ───────────────────────────────

from app.core.database import get_db as _get_db  # noqa: E402
from app.main import app as _app  # noqa: E402
from app.modules.safety.models import RegulationIngestRun  # noqa: E402
from app.modules.safety.regulation_ingest import monitor as ingest_monitor  # noqa: E402
from app.modules.safety.regulation_ingest.ragplus_crawler_client import (  # noqa: E402
    RagplusCrawlerError,
    RagplusCrawlerNotConnectedError,
)


class _StatusClient:
    """契约③替身：预设 sources/runs 或异常。"""

    def __init__(
        self,
        sources: list[dict[str, Any]] | None = None,
        runs: list[dict[str, Any]] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._sources = sources or []
        self._runs = runs or []
        self._raises = raises

    async def get_crawler_status(self) -> dict[str, Any]:
        if self._raises:
            raise self._raises
        return {"sources": self._sources, "runs": self._runs}


def _use_status(monkeypatch, client: _StatusClient) -> None:
    monkeypatch.setattr(ingest_monitor, "get_ragplus_crawler_client", lambda: client)


@pytest.fixture
async def monitor_client(db_session):
    """端点走 db_session 同一事务：直插留痕行对端点可见，回滚零残留。"""
    from httpx import ASGITransport, AsyncClient

    async def _override():
        yield db_session

    _app.dependency_overrides[_get_db] = _override
    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    _app.dependency_overrides.clear()


def _mk_run_row(source_run_id: str, **kw) -> RegulationIngestRun:
    defaults = dict(
        source_run_id=source_run_id,
        source="push",
        status="completed",
        received_count=3,
        duplicate_count=1,
        pending_count=0,
        promoted_count=1,
        rejected_count=1,
        failed_count=0,
        ai_tokens_used=800,
        items_result=[{
            "candidate_id": "c1", "action_taken": "promote",
            "reason": "判定相关（score=0.9），修订替代《旧法》",
            "bitable_record_id": "rec-1", "title": "新法（修订）",
            "url": "https://example.gov.cn/new", "attachment_missing": False,
        }],
    )
    defaults.update(kw)
    return RegulationIngestRun(**defaults)


async def test_monitor_live(monitor_client, db_session, monkeypatch):
    _use_status(monkeypatch, _StatusClient(
        sources=[
            {"name": "应急管理部", "layer": "api", "last_success_at": "2026-10-15T06:00:00Z",
             "consecutive_failures": 0, "items_7d": 5, "status": "ok"},
            {"name": "国家标准委", "layer": "http_parse", "last_success_at": None,
             "consecutive_failures": 2, "items_7d": 0, "status": "warn"},
        ],
        runs=[{"run_id": "rag-1", "status": "success", "found_count": 30, "parsed_count": 28}],
    ))
    db_session.add(_mk_run_row("run-live"))
    await db_session.flush()

    resp = await monitor_client.get("/api/v1/safety/regulation-monitor")
    data = resp.json()["data"]
    assert data["status"] == "live"
    assert data["errors"] == []
    assert data["stats"]["sources_total"] == 2
    assert data["stats"]["sources_healthy"] == 1
    assert data["stats"]["items_7d"] == 1
    assert data["stats"]["pending_review"] == 0
    assert data["feed"][0]["title"] == "新法（修订）"
    assert data["feed"][0]["is_revision"] is True
    assert data["funnel"]["discovered"] == 30
    assert data["funnel"]["promoted"] == 1
    assert data["runs"]["meta"]["total"] == 1


async def test_monitor_degraded_unreachable_not_silent(monitor_client, db_session, monkeypatch):
    """ragplus 不可达 → degraded + errors 标注 + 本仓留痕照常返回。"""
    _use_status(monkeypatch, _StatusClient(raises=RagplusCrawlerError("connect timeout")))
    db_session.add(_mk_run_row("run-deg"))
    await db_session.flush()

    resp = await monitor_client.get("/api/v1/safety/regulation-monitor")
    data = resp.json()["data"]
    assert data["status"] == "degraded"
    assert any("不可达" in e or "失败" in e for e in data["errors"])
    assert data["sources"] == []
    assert data["runs"]["meta"]["total"] == 1  # 本仓留痕不静默清空


async def test_monitor_not_connected(monitor_client, monkeypatch):
    _use_status(monkeypatch, _StatusClient(
        raises=RagplusCrawlerNotConnectedError("404"),
    ))
    resp = await monitor_client.get("/api/v1/safety/regulation-monitor")
    data = resp.json()["data"]
    assert data["status"] == "not_connected"


async def test_monitor_degraded_on_down_source(monitor_client, monkeypatch):
    _use_status(monkeypatch, _StatusClient(sources=[
        {"name": "药监局", "layer": "api", "status": "down"},
    ]))
    resp = await monitor_client.get("/api/v1/safety/regulation-monitor")
    data = resp.json()["data"]
    assert data["status"] == "degraded"
    assert "药监局" in data["errors"][0]


async def test_monitor_run_detail_two_segments(monitor_client, db_session, monkeypatch):
    _use_status(monkeypatch, _StatusClient(
        runs=[{"run_id": "run-d1", "status": "success", "found_count": 12,
               "started_at": "2026-10-15T06:00:00Z"}],
    ))
    db_session.add(_mk_run_row("run-d1"))
    await db_session.flush()

    resp = await monitor_client.get("/api/v1/safety/regulation-monitor/runs/run-d1")
    data = resp.json()["data"]
    assert data["ingest"]["source_run_id"] == "run-d1"
    assert data["ingest"]["items_result"][0]["candidate_id"] == "c1"
    assert data["ragplus_run"]["found_count"] == 12


async def test_monitor_run_detail_ragplus_fail_tolerated(monitor_client, db_session, monkeypatch):
    _use_status(monkeypatch, _StatusClient(raises=RagplusCrawlerError("down")))
    db_session.add(_mk_run_row("run-d2"))
    await db_session.flush()

    resp = await monitor_client.get("/api/v1/safety/regulation-monitor/runs/run-d2")
    data = resp.json()["data"]
    assert data["ingest"]["source_run_id"] == "run-d2"
    assert data["ragplus_run"] is None
    assert data["errors"]


async def test_monitor_run_detail_404(monitor_client, monkeypatch):
    _use_status(monkeypatch, _StatusClient())
    resp = await monitor_client.get("/api/v1/safety/regulation-monitor/runs/nope")
    assert resp.status_code == 404


# ── S2 卡轻量指标（Ticket 07） ──────────────────────────────


@pytest.fixture(autouse=False)
def s2_cache_reset():
    ingest_monitor._s2_cache["value"] = None
    ingest_monitor._s2_cache["expires_at"] = 0.0
    yield
    ingest_monitor._s2_cache["value"] = None
    ingest_monitor._s2_cache["expires_at"] = 0.0


async def test_s2_metric_live(db_session, monkeypatch, s2_cache_reset):
    _use_status(monkeypatch, _StatusClient(sources=[{"name": "应急管理部", "status": "ok"}]))
    db_session.add(_mk_run_row("run-s2", promoted_count=2))
    await db_session.flush()

    result = await ingest_monitor.build_s2_metric(db_session)
    assert result["status"] == "ok"
    assert result["metric"] == "采集正常 · 近7日+2"


async def test_s2_metric_unreachable_warns(db_session, monkeypatch, s2_cache_reset):
    _use_status(monkeypatch, _StatusClient(raises=RagplusCrawlerError("timeout")))
    result = await ingest_monitor.build_s2_metric(db_session)
    assert result["status"] == "warn"
    assert "采集降级" in result["metric"]


async def test_s2_metric_not_connected_keeps_running(db_session, monkeypatch, s2_cache_reset):
    _use_status(monkeypatch, _StatusClient(raises=RagplusCrawlerNotConnectedError("404")))
    result = await ingest_monitor.build_s2_metric(db_session)
    assert result["status"] == "ok"
    assert result["metric"] == "知识库运行中"


async def test_s2_metric_down_source_warns(db_session, monkeypatch, s2_cache_reset):
    _use_status(monkeypatch, _StatusClient(sources=[
        {"name": "a", "status": "ok"}, {"name": "b", "status": "down"},
    ]))
    result = await ingest_monitor.build_s2_metric(db_session)
    assert result["status"] == "warn"
    assert "1 源停摆" in result["metric"]


async def test_s2_metric_ttl_cache(db_session, monkeypatch, s2_cache_reset):
    client = _StatusClient(sources=[{"name": "a", "status": "ok"}])
    _use_status(monkeypatch, client)

    first = await ingest_monitor.build_s2_metric(db_session)
    second = await ingest_monitor.build_s2_metric(db_session)
    assert first == second


# ── 对账兜底巡检（Ticket 08） ───────────────────────────────

from app.modules.safety.regulation_ingest import (  # noqa: E402
    reconcile as ingest_reconcile,
)


class _PatrolStatusClient:
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self._runs = runs

    async def get_crawler_status(self) -> dict[str, Any]:
        return {"sources": [], "runs": self._runs}


def _rag_run(run_id: str, items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {"run_id": run_id, "status": "success", "items": items}


async def test_reconcile_recovers_missed_run(db_session, monkeypatch):
    """人为漏推一批候选 → 巡检补处理成功（走完整链，source=reconcile 留痕）。"""
    monkeypatch.setenv(_ENABLED_KEY, "1")
    monkeypatch.setattr(
        ingest_reconcile, "get_ragplus_crawler_client",
        lambda: _PatrolStatusClient([_rag_run("missed-1", [
            {"candidate_id": "c1", "source": "npc", "url": "https://a/1",
             "title": "漏推的法规", "content_digest": "内容摘要"},
        ])]),
    )
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: _FakeWriter(
        [], write_result={"record_id": "rec-m1", "shared_url": "u", "action": "created"},
    ))
    monkeypatch.setattr(ingest_service, "AIExtractor", lambda: _rel_verdict())
    monkeypatch.setattr(
        ingest_service, "get_ragplus_crawler_client",
        lambda: _FakeLifecycleClient(),
    )

    result = await ingest_reconcile.run_reconcile_patrol(db_session)

    assert result["recovered_runs"] == ["missed-1"]
    row = (await db_session.execute(
        select(RegulationIngestRun).where(
            RegulationIngestRun.source_run_id == "missed-1")
    )).scalar_one()
    assert row.source == "reconcile"
    assert row.status == "completed"
    assert row.promoted_count == 1
    assert row.items_result[0]["action_taken"] == "promote"


async def test_reconcile_skips_known_runs(db_session, monkeypatch):
    """已收录的 run 不重复处理。"""
    monkeypatch.setenv(_ENABLED_KEY, "1")
    db_session.add(_mk_run_row("known-1", status="completed"))
    await db_session.flush()
    monkeypatch.setattr(
        ingest_reconcile, "get_ragplus_crawler_client",
        lambda: _PatrolStatusClient([_rag_run("known-1", [
            {"candidate_id": "c1", "source": "npc", "url": "u", "title": "t"},
        ])]),
    )

    result = await ingest_reconcile.run_reconcile_patrol(db_session)

    assert result["recovered_runs"] == []
    assert result["missing_no_items"] == []
    rows = (await db_session.execute(
        select(RegulationIngestRun).where(
            RegulationIngestRun.source_run_id == "known-1")
    )).scalars().all()
    assert len(rows) == 1  # 无新增留痕行


async def test_reconcile_missing_no_items_tolerated(db_session, monkeypatch):
    """契约③ run 无候选明细 → 留痕告警（missing_no_items）不炸。"""
    monkeypatch.setenv(_ENABLED_KEY, "1")
    monkeypatch.setattr(
        ingest_reconcile, "get_ragplus_crawler_client",
        lambda: _PatrolStatusClient([_rag_run("bare-1", None)]),
    )

    result = await ingest_reconcile.run_reconcile_patrol(db_session)

    assert result["missing_no_items"] == ["bare-1"]
    assert result["recovered_runs"] == []


async def test_reconcile_unreachable_raises(db_session, monkeypatch):
    """ragplus 不可达 → 异常传播（scheduler guarded 层留痕 failed，不静默）。"""
    class _Broken:
        async def get_crawler_status(self):
            raise RagplusCrawlerError("connect timeout")

    monkeypatch.setattr(
        ingest_reconcile, "get_ragplus_crawler_client", lambda: _Broken(),
    )
    with pytest.raises(RagplusCrawlerError):
        await ingest_reconcile.run_reconcile_patrol(db_session)


# ── 事件信封 + MCP 工具（Ticket 09） ─────────────────────────


async def test_event_envelope_recorded_on_promote(db_session, monkeypatch, push_off):
    """收录成功路径 emit regulation.updated：信封字段完整落留痕 event_envelope。"""
    from app.modules.safety.regulation_ingest.schemas import IngestCandidatesRequest

    monkeypatch.setenv(_ENABLED_KEY, "1")
    monkeypatch.setattr(ingest_service, "BitableWriter", lambda: _FakeWriter(
        [], write_result={"record_id": "rec-ev-1", "shared_url": "u", "action": "created"},
    ))
    monkeypatch.setattr(ingest_service, "AIExtractor", lambda: _rel_verdict())
    _use_receipts(monkeypatch, _FakeLifecycleClient())

    service = ingest_service.RegulationIngestService(db_session)
    resp = await service.ingest_candidates(IngestCandidatesRequest(**_payload()))
    assert resp.results[0].action_taken == "promote"

    row = (await db_session.execute(
        select(RegulationIngestRun).where(
            RegulationIngestRun.source_run_id == "run-001")
    )).scalar_one()
    envelopes = row.event_envelope or []
    assert len(envelopes) == 1
    env = envelopes[0]
    assert env["event_type"] == "regulation.updated"
    assert env["source"] == "platform"
    assert env["actor"] == "platform"
    assert env["op"] == "created"
    assert env["record_id"] == "rec-ev-1"
    assert env["event_id"]
    assert env["occurred_at"]


class _FakeDeps:
    def __init__(self, db) -> None:
        self.db = db


class _FakeCtx:
    def __init__(self, db) -> None:
        self.deps = _FakeDeps(db)


async def test_mcp_query_regulation_crawl_status(db_session, monkeypatch):
    from app.modules.safety.business_agent.tools.read_tools import (
        query_regulation_crawl_status,
    )

    _use_status(monkeypatch, _StatusClient(
        sources=[{"name": "应急管理部", "status": "ok"}],
        runs=[{"run_id": "r1", "status": "success"}],
    ))
    result = await query_regulation_crawl_status(_FakeCtx(db_session))
    assert result["success"] is True
    assert result["status"] == "live"
    assert result["sources"][0]["name"] == "应急管理部"
    assert result["source"] == "regulation-monitor"


async def test_mcp_query_regulation_latest(db_session, monkeypatch):
    from app.modules.safety.business_agent.tools.read_tools import (
        query_regulation_latest,
    )

    _use_status(monkeypatch, _StatusClient())
    db_session.add(_mk_run_row("run-mcp"))
    await db_session.flush()

    result = await query_regulation_latest(_FakeCtx(db_session), limit=3)
    assert result["success"] is True
    assert result["items"][0]["title"] == "新法（修订）"
    assert result["items"][0]["is_revision"] is True
