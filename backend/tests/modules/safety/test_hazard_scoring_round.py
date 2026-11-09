"""⑤ 隐患AI评分轮询 — 纯内存桩测试（不打飞书/AI 网络）。

覆盖：判据查询组装（回填窗口）、写回 payload（2 列 + note 模板条件段）、
失败不写回下轮重试语义、to_view 新字段解析。
"""

from __future__ import annotations

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
from app.modules.safety.service.hazard_direct import bitable_repo, hazard_scoring


def make_output(
    *,
    band: RiskBandEnum = RiskBandEnum.HIGH,
    hit: bool = False,
    clauses: list[str] | None = None,
) -> HazardScoringOutput:
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
        major_hazard={"hit": hit, "clauses": clauses or []},
        summary="静电跨接断裂，建议立即整改。",
    )


def _pending_record(no: str = "HZ-20261105-001") -> dict[str, Any]:
    return {
        "record_id": f"rec_{no}",
        "fields": {
            "隐患编号": no,
            "隐患描述": "3号罐区静电跨接断裂",
            "隐患分类（AI）": "物的不安全状态",
            "隐患类别（AI）": "防雷防静电",
            "隐患级别（AI）": "一般隐患",
            "隐患判定依据（AI）": "GB 12158",
            "整改责任人.部门": ["储运部"],
            "检查日期": 1762300800000,  # 2025-11-05 (ms)
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# note 模板（_build_note：band 首段 / 四维=D / 条件段）
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildNote:
    def test_plain_note_format(self):
        note = hazard_scoring._build_note(make_output(), 52.9)
        # band 首段；四维乘式含分值与等号总分；评语；依据
        assert note.startswith("H｜")
        assert "可能1.5×每天几次接触1.8×严重20×一般0.98=52.9" in note
        assert "静电跨接断裂，建议立即整改。" in note
        assert "依据:附件五·安全操作·静电控制M" in note
        # 无命中无警示：不含附加段
        assert "重大判定" not in note
        assert "⚠" not in note

    def test_note_with_major_hit(self):
        note = hazard_scoring._build_note(
            make_output(hit=True, clauses=["附件一·十二", "AQ 3067·设备设施"]), 52.9,
        )
        assert "重大判定:附件一·十二;AQ 3067·设备设施" in note
        assert "⚠" not in note

    def test_note_with_consistency_warning(self):
        note = hazard_scoring._build_note(make_output(band=RiskBandEnum.LOW), 52.9)
        assert "⚠" in note
        assert note.startswith("L｜")

    def test_note_with_both_segments(self):
        note = hazard_scoring._build_note(
            make_output(band=RiskBandEnum.LOW, hit=True, clauses=["附件一·十二"]), 52.9,
        )
        assert "重大判定:附件一·十二" in note
        assert "⚠" in note
        # 重大判定段在 ⚠ 段之前
        assert note.index("重大判定") < note.index("⚠")


# ═══════════════════════════════════════════════════════════════════════════
# 判据查询组装（search_pending_scoring：filter + 回填窗口）
# ═══════════════════════════════════════════════════════════════════════════


class _CaptureClient:
    """捕获 list_all_records 调用参数的桩 client。"""

    def __init__(self, records: list[dict[str, Any]] | None = None):
        self.records = records or []
        self.filters: list[Any] = []

    async def list_all_records(self, *, filter_info=None, page_size=None, strict=None):
        self.filters.append(filter_info)
        return list(self.records)


def _flat_conditions(filter_info: Any) -> list[dict[str, Any]]:
    assert filter_info is not None
    conds = filter_info.get("conditions", [])
    assert filter_info.get("conjunction") == "and"
    return conds


class TestSearchPendingScoring:
    async def test_filter_has_three_conditions(self):
        client = _CaptureClient()
        await bitable_repo.search_pending_scoring(client)
        conds = _flat_conditions(client.filters[0])
        names = [c.get("field_name") for c in conds]
        assert "隐患分类（AI）" in names
        assert "评分结果" in names
        assert "检查日期" in names  # 回填窗口默认 120 天

    async def test_backfill_zero_omits_date(self, monkeypatch):
        monkeypatch.setattr(bitable_repo.config, "scoring_backfill_days", lambda: 0)
        client = _CaptureClient()
        await bitable_repo.search_pending_scoring(client)
        conds = _flat_conditions(client.filters[0])
        assert all(c.get("field_name") != "检查日期" for c in conds)


# ═══════════════════════════════════════════════════════════════════════════
# 轮次执行（run_scoring_round：成功写回 / 失败不写）
# ═══════════════════════════════════════════════════════════════════════════


class TestRunScoringRound:
    async def test_success_writes_two_columns(self, monkeypatch):
        written: list[tuple[str, dict[str, Any]]] = []

        async def fake_write(
            client, record_id, *, total, note, snapshot_fields=None
        ):
            written.append((record_id, {"total": total, "note": note}))
            return True

        record = _pending_record()
        monkeypatch.setattr(
            bitable_repo, "search_pending_scoring",
            lambda client, *, limit=None: _return_records([record]),
        )
        monkeypatch.setattr(
            hazard_scoring, "_score_one",
            lambda client, view: _return_output(make_output()),
        )
        monkeypatch.setattr(bitable_repo, "write_scoring", fake_write)

        result = await hazard_scoring.run_scoring_round(notify=False)

        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert written[0][0] == "rec_HZ-20261105-001"
        assert written[0][1]["total"] == 52.9
        assert written[0][1]["note"].startswith("H｜")

    async def test_failure_writes_nothing_and_records_reason(self, monkeypatch):
        written: list[tuple[str, dict[str, Any]]] = []

        async def fake_write(
            client, record_id, *, total, note, snapshot_fields=None
        ):
            written.append((record_id, {"total": total, "note": note}))
            return True

        async def boom(client, view):
            raise RuntimeError("AI 接口超时")

        monkeypatch.setattr(
            bitable_repo, "search_pending_scoring",
            lambda client, *, limit=None: _return_records([_pending_record()]),
        )
        monkeypatch.setattr(hazard_scoring, "_score_one", boom)
        monkeypatch.setattr(bitable_repo, "write_scoring", fake_write)

        result = await hazard_scoring.run_scoring_round(notify=False)

        assert result.failed == 1
        assert result.succeeded == 0
        assert written == []  # 失败语义：不写任何列
        assert "RuntimeError" in result.failures[0]["reason"]

    async def test_empty_pending_short_circuits(self, monkeypatch):
        monkeypatch.setattr(
            bitable_repo, "search_pending_scoring",
            lambda client, *, limit=None: _return_records([]),
        )
        result = await hazard_scoring.run_scoring_round(notify=False)
        assert result.total == 0


# ═══════════════════════════════════════════════════════════════════════════
# to_view 新字段解析
# ═══════════════════════════════════════════════════════════════════════════


class TestViewScoreFields:
    def test_to_view_parses_score_and_note(self):
        record = _pending_record()
        record["fields"]["评分结果"] = 52.9
        record["fields"]["评分说明"] = "H｜可能1.5×…=52.9｜评语｜依据:附件五"
        view = bitable_repo.to_view(record)
        assert view.score == pytest.approx(52.9)
        assert view.score_note is not None
        assert view.score_note.startswith("H｜")

    def test_to_view_defaults_none_when_absent(self):
        view = bitable_repo.to_view(_pending_record())
        assert view.score is None
        assert view.score_note is None


class TestResponseSchemaPassthrough:
    def test_hazard_response_carries_score_fields(self):
        from app.modules.safety.schemas import HazardReportResponse

        record = _pending_record()
        record["fields"]["评分结果"] = 52.9
        record["fields"]["评分说明"] = "H｜可能1.5×每天几次接触1.8×严重20×一般0.98=52.9｜评语｜依据:附件五"
        view = bitable_repo.to_view(record)
        resp = HazardReportResponse.model_validate(view)
        assert resp.score == pytest.approx(52.9)
        assert resp.score_note is not None
        assert resp.score_note.startswith("H｜")

    def test_hazard_response_score_defaults_none(self):
        from app.modules.safety.schemas import HazardReportResponse

        view = bitable_repo.to_view(_pending_record())
        resp = HazardReportResponse.model_validate(view)
        assert resp.score is None
        assert resp.score_note is None


class TestWriteScoringPayload:
    async def test_write_scoring_two_columns_and_rounding(self, monkeypatch):
        """write_scoring 真实 payload：仅 2 列、total 四舍五入 1 位。"""
        from app.modules.safety.service.bitable_direct import writer as bd_writer

        captured: list[bd_writer.RecordUpdate] = []

        class _CaptureWriter:
            async def write_serial(self, client, updates, *, interval_seconds=0.0):
                captured.extend(updates)
                from app.modules.safety.service.bitable_direct.writer import (
                    WritebackResult,
                )

                return WritebackResult(attempted=len(updates), written=len(updates))

        monkeypatch.setattr(bitable_repo.bd_writer, "write_serial", _CaptureWriter().write_serial)
        ok = await bitable_repo.write_scoring(
            object(), "rec_x", total=52.920000001, note="H｜…=52.9"
        )
        assert ok is True
        assert len(captured) == 1
        fields = captured[0].fields
        assert set(fields) == {"评分结果", "评分说明"}
        assert fields["评分结果"] == pytest.approx(52.9)
        assert fields["评分说明"] == "H｜…=52.9"


# ── async 桩工具 ───────────────────────────────────────────────


async def _return_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return records


async def _return_output(output: HazardScoringOutput) -> HazardScoringOutput:
    return output
