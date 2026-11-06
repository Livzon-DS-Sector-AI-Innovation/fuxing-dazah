"""P1-4 D2 质量看板后端测试（service 层 + 端点）。

接缝（spec §5 S2）：
- service：fake AsyncSession 喂合成审计行 → 输出与
  ``quality_metrics.analyze_rows`` **同数据集逐字段一致**（同源锁定）；
- 窗口查询口径与 replay SQL 同构（scenario + output_text 非空 + created_at 窗口）；
- 死信水位：注入 fake redis（``failure_ledger.RedisLike`` 协议）；ledger 自身
  fail-open（hgetall 异常→[]），service 外层再兜一层（ledger 抛错→count=None）；
- 端点：monkeypatch ``api.hazard_quality.build_quality_dashboard``（subsidy 前例），
  ``days`` 仅 7/30 合法。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.safety.api import hazard_quality as hq_api
from app.modules.safety.service.hazard_direct import quality_dashboard as qd
from app.modules.safety.service.hazard_direct.quality_metrics import (
    SCENARIO,
    analyze_rows,
    baseline_comparison,
)

FIELD = '"major_hazard_basis"'

GOOD = (
    '{"key_defect": "管道标识缺失", '
    + FIELD
    + ': "《安全生产法》第四十一条：\'生产经营单位必须建立、健全安全生产'
    '责任制。\'"}'
)
PLACEHOLDER_VARIANT = (
    '{"key_defect": "x", '
    + FIELD
    + ': "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充"}'
)
NO_CITATION = '{"key_defect": "x", ' + FIELD + ': "现场管理不到位，需要加强管理"}'
BAD_JSON = "完全不是 JSON"

KNOWLEDGE = (
    "## 相关法规条款\n\n"
    "[1] 《安全生产法》 第四十一条\n"
    "生产经营单位必须建立、健全安全生产责任制，改善安全生产条件。\n\n"
    "---\n\n"
    "[2] GB 30871-2022 第5.1条\n"
    "动火作业前应办理动火作业票，落实监护人和安全措施。"
)


def _audit_input(vision: bool = False) -> str:
    prompt = "现场隐患：受限空间作业未办票" + ("\n\n[附图 1 张]" if vision else "")
    content = (
        f"{prompt}\n\n---\n\n{KNOWLEDGE}\n\n---\n\n## 工作规则\n\n（省略）"
    )
    return json.dumps(
        [
            {"role": "system", "content": "你是安全专家"},
            {"role": "user", "content": content},
        ],
        ensure_ascii=False,
    )


def _row(
    *,
    output: str,
    day: str = "2026-11-05",
    record_id: str = "rec1",
    vision: bool = False,
    degradation: str | None = "ragplus",
    retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {"bitable_record_id": record_id}
    if retrieval is not None:
        extra.update(retrieval)
    return {
        "created_at": f"{day} 08:00:00+08:00",
        "degradation_level": degradation,
        "input_text": _audit_input(vision=vision),
        "output_text": output,
        "extra": json.dumps(extra, ensure_ascii=False),
    }


def _rows() -> list[dict[str, Any]]:
    return [
        _row(
            output=GOOD,
            record_id="rec_ok",
            retrieval={
                "multi_query_count": 2,
                "rewrite_hit": True,
                "retrieval_docs": ["受限空间作业安全管理制度", "GB 30871-2022"],
            },
        ),
        _row(
            output=PLACEHOLDER_VARIANT,
            day="2026-11-04",
            record_id="rec_ph",
            degradation=None,
            retrieval={"multi_query_count": 1, "retrieval_docs": []},
        ),
        _row(output=NO_CITATION, record_id="rec_nc", vision=True),
        _row(output=BAD_JSON, day="2026-11-04", record_id="rec_bad"),
    ]


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class FakeDB:
    """最小 AsyncSession 假件：只实现 execute，捕获语句供口径断言。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.stmt: Any = None

    async def execute(self, stmt: Any) -> _FakeResult:
        self.stmt = stmt
        return _FakeResult(self.rows)


class FakeRedis:
    """failure_ledger.RedisLike 协议最小假件（只用到 hgetall）。"""

    def __init__(
        self,
        hash_data: dict[str, str] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._hash = hash_data or {}
        self._exc = exc

    async def hgetall(self, key: str) -> dict[str, str]:
        if self._exc is not None:
            raise self._exc
        return self._hash


def _dead_payload(record_id: str, attempts: int, dead_at: float) -> str:
    return json.dumps(
        {
            "record_id": record_id,
            "attempts": attempts,
            "category": "no_chunks",
            "last_reason": "检索零召回",
            "dead_at": dead_at,
        },
        ensure_ascii=False,
    )


# ── service：同源锁定（与 analyze_rows 同数据集逐字段一致） ──────────


async def test_dashboard_matches_analyze_rows_same_dataset() -> None:
    rows = _rows()
    data = await qd.build_quality_dashboard(
        FakeDB(rows), days=30, redis=FakeRedis()
    )
    expected = analyze_rows(rows)
    for key in (
        "totals",
        "citation",
        "retrieval",
        "gate_categories",
        "repair_stages",
        "by_day",
        "rerun_records",
    ):
        assert data[key] == expected[key], key
    assert data["baseline"] == baseline_comparison(expected)
    assert data["window"]["days"] == 30
    # 指标不是全零（合成行确实走到了检索/引用/占位路径）
    assert data["totals"]["calls"] == 4
    assert data["retrieval"]["calls_with_meta"] == 2
    assert data["citation"]["calls_with_evidence"] == 4


async def test_dashboard_window_query_matches_replay_semantics() -> None:
    db = FakeDB([])
    before = datetime.now(UTC)
    data = await qd.build_quality_dashboard(db, days=7, redis=FakeRedis())
    after = datetime.now(UTC)
    assert data["window"]["days"] == 7
    assert data["totals"]["calls"] == 0
    # 查询口径与 replay SQL 同构：scenario + output_text 非空 + created_at 窗口
    sql = str(db.stmt)
    assert "scenario" in sql and "output_text" in sql and "created_at" in sql
    params = db.stmt.compile().params

    def _param(prefix: str) -> Any:
        matched = [v for k, v in params.items() if k.startswith(prefix)]
        assert matched, f"param {prefix}* not in {list(params)}"
        return matched[0]

    assert _param("scenario") == SCENARIO
    cutoff = _param("created_at")
    assert isinstance(cutoff, datetime)
    assert (
        before - timedelta(days=7)
        <= cutoff
        <= after - timedelta(days=7) + timedelta(seconds=1)
    )


async def test_dashboard_dead_letters_from_redis() -> None:
    redis = FakeRedis(
        {
            "recA": _dead_payload("recA", 5, 2000000000.0),
            "recB": _dead_payload("recB", 5, 1000000000.0),
        }
    )
    data = await qd.build_quality_dashboard(FakeDB(_rows()), days=30, redis=redis)
    dead = data["dead_letters"]
    assert dead["count"] == 2
    assert [item["record_id"] for item in dead["items"]] == ["recA", "recB"]
    assert dead["items"][0]["attempts"] == 5
    assert dead["items"][0]["category"] == "no_chunks"


async def test_dashboard_dead_letter_ledger_fail_open_counts_zero() -> None:
    """Redis 挂：failure_ledger fail-open（hgetall 异常→[]）→ count=0，不阻塞。"""
    data = await qd.build_quality_dashboard(
        FakeDB(_rows()), days=30, redis=FakeRedis(exc=RuntimeError("redis down"))
    )
    assert data["dead_letters"] == {"count": 0, "items": []}
    assert data["totals"]["calls"] == 4


async def test_dashboard_dead_letter_unexpected_error_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ledger 本身抛错（非 hgetall 异常）：count=None（水位未知），主指标不炸。"""

    async def boom(**kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("ledger broken")

    monkeypatch.setattr(qd, "list_dead_letters", boom)
    data = await qd.build_quality_dashboard(FakeDB(_rows()), days=30, redis=FakeRedis())
    assert data["dead_letters"] == {"count": None, "items": []}
    assert data["totals"]["calls"] == 4


# ── 端点：days 校验 + 透传 ─────────────────────────────────────────


def _patch_service(
    monkeypatch: pytest.MonkeyPatch, sentinel: dict[str, Any]
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_dashboard(db: Any, *, days: int = 30, redis: Any = None) -> dict[str, Any]:
        captured["days"] = days
        return sentinel

    monkeypatch.setattr(hq_api, "build_quality_dashboard", fake_dashboard)
    return captured


async def test_endpoint_default_30d_and_pass_through(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = {"window": {"days": 30}, "totals": {"calls": 1}}
    captured = _patch_service(monkeypatch, sentinel)
    resp = await client.get("/api/v1/safety/hazard-quality/dashboard")
    assert resp.status_code == 200
    assert resp.json()["data"] == sentinel
    assert captured["days"] == 30


async def test_endpoint_accepts_7d(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_service(monkeypatch, {"window": {"days": 7}})
    resp = await client.get(
        "/api/v1/safety/hazard-quality/dashboard", params={"days": 7}
    )
    assert resp.status_code == 200
    assert captured["days"] == 7


@pytest.mark.parametrize("bad", [8, 1, 90, 0])
async def test_endpoint_rejects_other_days(
    client: Any, monkeypatch: pytest.MonkeyPatch, bad: int
) -> None:
    _patch_service(monkeypatch, {})
    resp = await client.get(
        "/api/v1/safety/hazard-quality/dashboard", params={"days": bad}
    )
    assert resp.status_code == 422
