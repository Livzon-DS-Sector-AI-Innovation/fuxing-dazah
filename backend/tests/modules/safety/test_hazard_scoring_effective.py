"""T03 ⑤评分 + ④通报读口径（B2 评分/通报）单测（RED 先行）。

覆盖 spec S4/S5 / B2-2 / B2-4：
- ``_score_one`` 传给 AI 的 HazardScoringInput.level/type/category = effective_*
  （human≠AI 时取人工值）；
- ``_build_note`` 追加等级口径段（人工 → 基于人工等级；AI fallback →
  基于AI等级（人工等级缺失）），首段仍为 band（前端契约不破坏）；
- ``run_scoring_round`` 把 effective_level_source 传入评分说明，写回仍 2 列；
- ``build_bulletin`` 渲染等级 = effective_level（human≠AI 时显示人工值）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.ai_hazard_scoring.schemas import (
    ConsequenceTier,
    DifficultyTier,
    ExposureTier,
    HazardScoringOutput,
    LikelihoodTier,
    RiskBandEnum,
)
from app.modules.safety.service.hazard_direct import (
    bitable_repo,
    bulletin,
    hazard_scoring,
)

_CHECK_MS = int(datetime(2026, 10, 27, 1, 30, tzinfo=UTC).timestamp() * 1000)


def make_output(*, band: RiskBandEnum = RiskBandEnum.HIGH) -> HazardScoringOutput:
    return HazardScoringOutput(
        likelihood=LikelihoodTier.LIKELY,
        likelihood_reason="作业频繁且点火源现实存在",
        exposure=ExposureTier.DAILY,
        exposure_reason="巡检路线必经",
        consequence=ConsequenceTier.SEVERE,
        consequence_reason="泄漏遇火源可致火灾",
        difficulty=DifficultyTier.NORMAL,
        difficulty_reason="目视可见",
        band=band,
        band_basis="附件五·安全操作·静电控制M",
        major_hazard={"hit": False, "clauses": []},
        summary="静电跨接断裂，建议立即整改。",
    )


def _record(
    no: str = "HZ-20261105-001",
    *,
    manual_level: object = None,
    ai_level: object = None,
    manual_type: object = None,
    ai_type: object = None,
    manual_category: object = None,
    ai_category: object = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        bitable_repo.F_NO: no,
        bitable_repo.F_DESC: "3号罐区静电跨接断裂",
        bitable_repo.F_DATE: _CHECK_MS,
        bitable_repo.F_RECTIFY_STATUS: "未关闭",
    }
    if manual_level is not None:
        fields[bitable_repo.F_LEVEL_MANUAL] = manual_level
    if ai_level is not None:
        fields[bitable_repo.F_LEVEL_AI] = ai_level
    if manual_type is not None:
        fields[bitable_repo.F_TYPE_MANUAL] = manual_type
    if ai_type is not None:
        fields[bitable_repo.F_TYPE_AI] = ai_type
    if manual_category is not None:
        fields[bitable_repo.F_CATEGORY_MANUAL] = manual_category
    if ai_category is not None:
        fields[bitable_repo.F_CATEGORY_AI] = ai_category
    return {"record_id": f"rec_{no}", "fields": fields}


# ═══════════════════════════════════════════════════════════════
# S4a：_score_one 输入 = effective_*（human≠AI 取人工）
# ═══════════════════════════════════════════════════════════════


async def test_score_one_input_uses_effective_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []

    import app.modules.safety.ai_hazard_scoring as scoring_pkg
    from app.modules.safety.service import config as service_config

    class _FakeScorer:
        def __init__(self, ai_service: Any) -> None:
            pass

        async def score(self, input_data: Any) -> HazardScoringOutput:
            captured.append(input_data)
            return make_output()

    class _FakeAIService:
        async def close(self) -> None:
            return None

    monkeypatch.setattr(scoring_pkg, "AIHazardScorer", _FakeScorer)
    monkeypatch.setattr(
        service_config, "create_ai_service", lambda kind: _FakeAIService()
    )

    view = bitable_repo.to_view(
        _record(
            manual_level="较大隐患",
            ai_level="一般隐患",
            manual_type="物的不安全状态",
            ai_type="人的不安全行为",
            manual_category="设备设施",
            ai_category="应急管理",
        )
    )
    out = await hazard_scoring._score_one(SimpleNamespace(), view)

    assert out is not None
    assert len(captured) == 1
    input_data = captured[0]
    assert input_data.hazard_level == "serious"
    assert input_data.hazard_type == "unsafe_condition"
    assert input_data.hazard_category == "equipment"


async def test_score_one_input_ai_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []

    import app.modules.safety.ai_hazard_scoring as scoring_pkg
    from app.modules.safety.service import config as service_config

    class _FakeScorer:
        def __init__(self, ai_service: Any) -> None:
            pass

        async def score(self, input_data: Any) -> HazardScoringOutput:
            captured.append(input_data)
            return make_output()

    class _FakeAIService:
        async def close(self) -> None:
            return None

    monkeypatch.setattr(scoring_pkg, "AIHazardScorer", _FakeScorer)
    monkeypatch.setattr(
        service_config, "create_ai_service", lambda kind: _FakeAIService()
    )

    view = bitable_repo.to_view(
        _record(ai_level="重大隐患", ai_type="管理的缺陷", ai_category="应急管理")
    )
    await hazard_scoring._score_one(SimpleNamespace(), view)

    input_data = captured[0]
    assert input_data.hazard_level == "major"
    assert input_data.hazard_type == "management_defect"
    assert input_data.hazard_category == "emergency_mgmt"


# ═══════════════════════════════════════════════════════════════
# S4b：_build_note 等级口径段（band 首段契约不变）
# ═══════════════════════════════════════════════════════════════


class TestBuildNoteLevelSource:
    def test_human_source_segment_appended_at_end(self) -> None:
        note = hazard_scoring._build_note(make_output(), 52.9, "human")
        assert note.split("｜")[0] == "H"  # 前端色点契约：首段=band
        assert "基于人工等级" in note
        assert note.endswith("基于人工等级")

    def test_ai_source_segment_marks_missing_manual(self) -> None:
        note = hazard_scoring._build_note(make_output(), 52.9, "ai")
        assert note.split("｜")[0] == "H"
        assert "基于AI等级（人工等级缺失）" in note

    def test_none_source_no_level_segment(self) -> None:
        note = hazard_scoring._build_note(make_output(), 52.9, None)
        assert "基于人工等级" not in note
        assert "基于AI等级" not in note

    def test_default_keeps_backward_compatible_two_arg_call(self) -> None:
        note = hazard_scoring._build_note(make_output(), 52.9)
        assert note.split("｜")[0] == "H"
        assert "基于" not in note


# ═══════════════════════════════════════════════════════════════
# S4c：run_scoring_round 把等级来源写进评分说明
# ═══════════════════════════════════════════════════════════════


class TestRunScoringRoundLevelSource:
    async def _run(self, monkeypatch: pytest.MonkeyPatch, record: dict[str, Any]) -> str:
        written: list[dict[str, Any]] = []

        async def fake_write(
            client: Any,
            record_id: str,
            *,
            total: float,
            note: str,
            snapshot_fields: dict[str, Any] | None = None,
        ) -> bool:
            written.append({"record_id": record_id, "total": total, "note": note})
            return True

        async def _return_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return records

        async def _return_output(view: Any) -> HazardScoringOutput:
            return make_output()

        monkeypatch.setattr(
            bitable_repo, "search_pending_scoring",
            lambda client, *, limit=None: _return_records([record]),
        )
        monkeypatch.setattr(
            hazard_scoring, "_score_one",
            lambda client, view: _return_output(view),
        )
        monkeypatch.setattr(bitable_repo, "write_scoring", fake_write)

        result = await hazard_scoring.run_scoring_round(notify=False)
        assert result.succeeded == 1
        assert len(written) == 1
        return str(written[0]["note"])

    async def test_note_marks_human_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        note = await self._run(
            monkeypatch,
            _record(
                manual_level="较大隐患",
                ai_level="一般隐患",
                ai_type="人的不安全行为",
                ai_category="应急管理",
            ),
        )
        assert note.split("｜")[0] == "H"
        assert "基于人工等级" in note
        assert "基于AI等级" not in note

    async def test_note_marks_ai_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        note = await self._run(
            monkeypatch,
            _record(
                ai_level="一般隐患",
                ai_type="人的不安全行为",
                ai_category="应急管理",
            ),
        )
        assert "基于AI等级（人工等级缺失）" in note
        assert "基于人工等级" not in note


# ═══════════════════════════════════════════════════════════════
# S5：④通报等级显示 effective_level（human≠AI 显示人工值）
# ═══════════════════════════════════════════════════════════════


def _bulletin_record(
    no: str,
    *,
    manual_level: object = None,
    ai_level: object = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        bitable_repo.F_NO: no,
        bitable_repo.F_DESC: f"{no} 隐患描述",
        bitable_repo.F_RESPONSIBLE: [{"id": f"ou_{no}", "name": "张三"}],
        bitable_repo.F_DEPT: ["设备工程部"],
        bitable_repo.F_SUPERVISION: "红色预警",
        bitable_repo.F_RECTIFY_STATUS: "未关闭",
    }
    if manual_level is not None:
        fields[bitable_repo.F_LEVEL_MANUAL] = manual_level
    if ai_level is not None:
        fields[bitable_repo.F_LEVEL_AI] = ai_level
    return {"record_id": f"rec_{no}", "fields": fields}


def _patch_bulletin_deps(
    monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]
) -> None:
    from app.modules.safety.bitable_config.store import store as bitable_store
    from app.modules.safety.service import responsible_mapping
    from app.modules.safety.service.hazard_direct import progress_track

    async def fake_fetch(client: Any) -> list[dict[str, Any]]:
        return records

    async def fake_marks(views: Any) -> dict[str, str]:
        return {}

    async def fake_fallback(names: list[str]) -> dict[str, str]:
        return {n: f"ou_fb_{n}" for n in names}

    monkeypatch.setattr(bulletin, "_fetch_targets", fake_fetch)
    monkeypatch.setattr(progress_track, "compute_marks", fake_marks)
    monkeypatch.setattr(bulletin, "_load_person_open_ids", fake_fallback)
    monkeypatch.setattr(responsible_mapping, "DEPARTMENT_RESPONSIBLE_OVERRIDE", {})
    monkeypatch.setattr(
        bitable_store, "get_connection",
        lambda *a: SimpleNamespace(
            app_token="app", table_id="tbl", status="active",
        ),
    )


async def test_bulletin_shows_human_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_bulletin_deps(
        monkeypatch,
        [_bulletin_record("HZ-B1", manual_level="较大隐患", ai_level="一般隐患")],
    )
    content, stats = await bulletin.build_bulletin()
    assert stats["total"] == 1
    assert "等级：较大隐患" in content
    # AI 候选值不得作为权威展示
    assert "一般隐患" not in content


async def test_bulletin_shows_ai_fallback_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_bulletin_deps(
        monkeypatch,
        [_bulletin_record("HZ-B2", ai_level="重大隐患")],
    )
    content, stats = await bulletin.build_bulletin()
    assert stats["total"] == 1
    assert "等级：重大隐患" in content


async def test_bulletin_normalizes_multi_select_human_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """人工级别多选 → effective 按最高严重度归一（R1-7），通报只显示一个权威值。"""
    _patch_bulletin_deps(
        monkeypatch,
        [_bulletin_record("HZ-B3", manual_level=["较大隐患", "一般隐患"])],
    )
    content, stats = await bulletin.build_bulletin()
    assert stats["total"] == 1
    assert "等级：较大隐患" in content
    assert "一般隐患" not in content
