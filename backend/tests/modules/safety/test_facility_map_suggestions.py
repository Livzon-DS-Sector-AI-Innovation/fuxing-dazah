"""#2 地点→分区 AI 建议映射：插件解析 + 批扫描 + 确认流测试。

接缝：pins_service 替身（get_pins 返回固定 unmapped）与 ai_service 替身
（chat_parsed 假返回）构造注入；PG 走 db_session（dev 库），测试行用
「ZZ-T-」前缀隔离并在用例内显式清行（服务内 commit，回滚不生效）。
规格：docs/DESIGN-3x平台关联-…-20261026.md §12。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import delete

from app.modules.safety.ai_facility_map import (
    FacilityMapSuggestError,
    FacilityMapSuggestPlugin,
)
from app.modules.safety.models.location_district_map import LocationDistrictMap
from app.modules.safety.models.location_district_suggestion import (
    LocationDistrictSuggestion,
)
from app.modules.safety.service.facility_map import suggestions

_PREFIX = "ZZ-T-"


class _FakePins:
    """逐日返回固定 unmapped（count/kinds 按日拆开验证跨日聚合）。"""

    def __init__(self, unmapped_by_day: dict[date, list[dict[str, Any]]]):
        self._by_day = unmapped_by_day
        self.calls: list[date] = []

    async def get_pins(self, target: date) -> dict[str, Any]:
        self.calls.append(target)
        return {
            "pins": [],
            "unmapped": self._by_day.get(target, []),
            "errors": [],
        }


class _FakeAI:
    """chat_parsed 假返回（可注入多次调用序列）。"""

    def __init__(self, outputs: list[dict[str, Any]]):
        self._outputs = list(outputs)
        self.calls: list[list[tuple[str, int]]] = []

    async def chat_parsed(self, messages, expected_keys, temperature=0.1):
        assert expected_keys == ["suggestions"]
        self.calls.append(messages[1]["content"])
        return self._outputs.pop(0)


async def _cleanup(db) -> None:
    await db.execute(
        delete(LocationDistrictSuggestion).where(
            LocationDistrictSuggestion.location_text.like(f"{_PREFIX}%")
        )
    )
    await db.execute(
        delete(LocationDistrictMap).where(
            LocationDistrictMap.location_text.like(f"{_PREFIX}%")
        )
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _isolation(db_session):
    await _cleanup(db_session)
    yield
    await _cleanup(db_session)


def _day_pins() -> _FakePins:
    """两天各含一条同文本（跨日 count 累计、kinds 并集）+ 一条独有文本。"""
    day1, day2 = date(2026, 10, 26), date(2026, 10, 27)
    return _FakePins({
        day1: [
            {"text": f"{_PREFIX}212罐", "count": 3, "kinds": ["job"]},
            {"text": f"{_PREFIX}新罐区", "count": 5, "kinds": ["central"]},
        ],
        day2: [
            {"text": f"{_PREFIX}212罐", "count": 2, "kinds": ["fire"]},
        ],
    })


# ═══════════════════════════ 插件解析 ═══════════════════════════


class TestPluginParse:
    async def test_parse_normalizes_and_drops_hallucination(self):
        plugin = FacilityMapSuggestPlugin(_FakeAI([{"suggestions": [
            {"text": "212罐", "dist_id": "27", "confidence": "high",
             "reason": "212罐位于新罐区"},
            {"text": "不存在文本", "dist_id": "27", "confidence": "high", "reason": "幻觉"},
            {"text": "某文本", "dist_id": "99999", "confidence": "mid", "reason": "distId 幻觉"},
            {"text": "另一文本", "dist_id": None, "confidence": "medium", "reason": "无法判断"},
        ]}]))
        out = await plugin.suggest([("212罐", 8), ("某文本", 1), ("另一文本", 1)])
        assert [(s.text, s.dist_id, s.confidence) for s in out] == [
            ("212罐", "27", "high"),
            ("某文本", None, "mid"),      # distId 幻觉置空但保留建议行
            ("另一文本", None, "mid"),    # medium 归一 mid
        ]

    async def test_ai_failure_raises(self):
        class _Boom:
            async def chat_parsed(self, **kw):
                raise RuntimeError("upstream down")

        with pytest.raises(FacilityMapSuggestError):
            await FacilityMapSuggestPlugin(_Boom()).suggest([("x", 1)])


# ═══════════════════════════ 收集与扫描 ═══════════════════════════


class TestCollectAndScan:
    async def test_collect_aggregates_across_days(self):
        pins = _day_pins()
        agg = await suggestions.collect_unmapped_texts(days=2, pins_service=pins)
        assert agg[f"{_PREFIX}212罐"] == {"count": 5, "kinds": {"job", "fire"}}
        assert agg[f"{_PREFIX}新罐区"] == {"count": 5, "kinds": {"central"}}
        assert len(pins.calls) == 2

    async def test_scan_inserts_pending_and_is_idempotent(self, db_session):
        pins = _day_pins()
        ai = _FakeAI([{"suggestions": [
            {"text": f"{_PREFIX}212罐", "dist_id": "27", "confidence": "high",
             "reason": "位于新罐区"},
            {"text": f"{_PREFIX}新罐区", "dist_id": None, "confidence": "low",
             "reason": "未在分区清单"},
        ]}])
        result = await suggestions.run_suggestion_scan(
            db_session, days=2, ai_service=ai, pins_service=pins
        )
        assert result["candidates"] == 2
        assert result["suggested"] == 2
        assert result["no_judgement"] == 1

        # 只看本用例前缀行（表内有真实验收数据，勿全表断言）
        rows = [
            r for r in await suggestions.list_suggestions(db_session)
            if r["location_text"].startswith(_PREFIX)
        ]
        by_text = {r["location_text"]: r for r in rows}
        assert set(by_text) == {f"{_PREFIX}212罐", f"{_PREFIX}新罐区"}
        row = by_text[f"{_PREFIX}212罐"]
        assert (row["status"], row["dist_id"], row["confidence"]) == ("pending", "27", "high")
        assert row["kinds"] == ["fire", "job"]  # kinds 排序稳定
        assert row["dist_name"]  # dist_id 反解分区名

        # 重跑（无 AI 可调——同文本已有建议行，不应触发 AI）
        result2 = await suggestions.run_suggestion_scan(
            db_session, days=2, ai_service=_FakeAI([]), pins_service=pins
        )
        assert result2["candidates"] == 0
        assert result2["suggested"] == 0

    async def test_scan_skips_mapped_text(self, db_session):
        db_session.add(LocationDistrictMap(
            location_text=f"{_PREFIX}新罐区", dist_id="27", source="manual",
        ))
        await db_session.commit()
        result = await suggestions.run_suggestion_scan(
            db_session, days=2,
            ai_service=_FakeAI([{"suggestions": [
                {"text": f"{_PREFIX}212罐", "dist_id": "27", "confidence": "high",
                 "reason": "位于新罐区"},
            ]}]),
            pins_service=_day_pins(),
        )
        assert result["candidates"] == 1  # 已映射文本不进候选


# ═══════════════════════════ 确认流 ═══════════════════════════


async def _seed_pending(db, **overrides) -> LocationDistrictSuggestion:
    base = dict(
        location_text=f"{_PREFIX}212罐",
        count=5,
        kinds=["job", "fire"],
        dist_id="27",
        confidence="high",
        reason="位于新罐区",
        batch_id="test-batch",
        status="pending",
    )
    base.update(overrides)
    row = LocationDistrictSuggestion(**base)
    db.add(row)
    await db.commit()
    return row


class TestConfirmFlow:
    async def test_confirm_writes_map_ai_confirmed(self, db_session):
        row = await _seed_pending(db_session)
        data = await suggestions.confirm_suggestion(db_session, str(row.id))
        assert data["map_created"] is True
        assert data["dist_name"]
        map_row = (
            await db_session.execute(
                LocationDistrictMap.__table__.select().where(
                    LocationDistrictMap.location_text == f"{_PREFIX}212罐"
                )
            )
        ).mappings().one()
        assert map_row["dist_id"] == "27"
        assert map_row["source"] == "ai_confirmed"

    async def test_confirm_keeps_existing_manual_map(self, db_session):
        db_session.add(LocationDistrictMap(
            location_text=f"{_PREFIX}212罐", dist_id="58", source="manual",
        ))
        await db_session.commit()
        row = await _seed_pending(db_session)
        data = await suggestions.confirm_suggestion(db_session, str(row.id))
        assert data["map_created"] is False
        map_rows = (
            await db_session.execute(
                LocationDistrictMap.__table__.select().where(
                    LocationDistrictMap.location_text == f"{_PREFIX}212罐"
                )
            )
        ).mappings().all()
        assert len(map_rows) == 1
        assert map_rows[0]["dist_id"] == "58"  # 人工行保留不覆盖

    async def test_confirm_rejects_non_pending_and_null_dist(self, db_session):
        row = await _seed_pending(db_session, dist_id=None, confidence="low")
        with pytest.raises(suggestions.SuggestionStateError):
            await suggestions.confirm_suggestion(db_session, str(row.id))
        await suggestions.ignore_suggestion(db_session, str(row.id))
        with pytest.raises(suggestions.SuggestionStateError):
            await suggestions.confirm_suggestion(db_session, str(row.id))

    async def test_ignore_excludes_from_list(self, db_session):
        row = await _seed_pending(db_session, location_text=f"{_PREFIX}忽略项")
        await suggestions.ignore_suggestion(db_session, str(row.id))
        pending = await suggestions.list_suggestions(db_session, status="pending")
        assert all(r["location_text"] != f"{_PREFIX}忽略项" for r in pending)
        ignored = await suggestions.list_suggestions(db_session, status="ignored")
        assert any(r["location_text"] == f"{_PREFIX}忽略项" for r in ignored)

    async def test_confirm_high_only_takes_high_with_dist(self, db_session):
        await _seed_pending(db_session, location_text=f"{_PREFIX}高1",
                            dist_id="27", confidence="high")
        await _seed_pending(db_session, location_text=f"{_PREFIX}高无判断",
                            dist_id=None, confidence="high")
        await _seed_pending(db_session, location_text=f"{_PREFIX}中1",
                            dist_id="27", confidence="mid")
        data = await suggestions.confirm_high_confidence(db_session)
        assert data == {"confirmed": 1, "map_created": 1}
        rows = {r["location_text"]: r["status"]
                for r in await suggestions.list_suggestions(db_session, status=None)}
        assert rows[f"{_PREFIX}高1"] == "confirmed"
        assert rows[f"{_PREFIX}高无判断"] == "pending"
        assert rows[f"{_PREFIX}中1"] == "pending"
