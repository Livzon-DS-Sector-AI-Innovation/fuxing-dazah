"""T09 离线回归脚本 —— 纯函数单测（不连 DB / 不调 AI / 无网络）。

脚本位于 ``backend/scripts/hazard_ai_quality_replay.py``（只读交付物）；
本文件用 importlib 按路径加载，只测其外部可观察统计契约：
    - 单条 output_text 的 A1 修复指标与 A3 闸门分类；
    - 行集合汇总（视觉/文本拆分、按天、重跑窗口按 record 聚合）；
    - 197 条 ground truth 一致性对照（用临时文件，不依赖 /tmp 真实样本）；
    - Markdown 渲染包含关键结论行。

T1⑤ 数据口径（fix2）：197 条 ground truth（其中 140 条 success 样本用于 A4 规则回归）
属于生产台账派生数据，**不入库**；
`/tmp/rerun_results.jsonl` 只是本地/CI 都可选的可复现输入，缺失时
`compare_ground_truth` / `rule_regression_from_ground_truth` 返回 None（跳过对照），
本文件全部用 `tmp_path` 合成样本，不依赖 /tmp。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "hazard_ai_quality_replay.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hazard_ai_quality_replay", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = _load_script()

FIELD = '"major_hazard_basis"'


def _row(
    *,
    output: str,
    vision: bool = True,
    record_id: str = "rec1",
    day: str = "2026-11-05",
    degradation: str | None = "ragplus",
) -> dict[str, Any]:
    return {
        "created_at": f"{day} 00:00:00",
        "input_text": "请识别" + ("\n\n[附图 1 张]" if vision else ""),
        "output_text": output,
        "status": "success",
        "degradation_level": degradation,
        "extra": json.dumps({"bitable_record_id": record_id}, ensure_ascii=False),
    }


GOOD = (
    '{"key_defect": "管道标识缺失", '
    + FIELD
    + ': "《安全生产法》第41条：生产经营单位必须..."}'
)
TRAILING = (
    '{"key_defect": "管道标识缺失", '
    + FIELD
    + ': "《安全生产法》第41条：生产经营单位必须...",}'
)
PLACEHOLDER = '{"key_defect": "x", ' + FIELD + ': "知识库中无相应条文，待人工补充"}'
NO_CITATION = '{"key_defect": "x", ' + FIELD + ': "现场管理不到位，需要加强管理"}'
BAD_JSON = "完全不是 JSON"


# ═══════════════════════════════════════════════════════════════
# 单条指标
# ═══════════════════════════════════════════════════════════════


def test_good_output_valid_and_gate_pass() -> None:
    metrics = replay.analyze_output(GOOD)
    assert metrics["json_valid_before"] is True
    assert metrics["json_valid_after"] is True
    assert metrics["repaired"] is False
    assert metrics["gate_pass"] is True
    assert metrics["gate_category"] is None
    assert metrics["placeholder"] is False


def test_trailing_comma_repaired_before_gate() -> None:
    metrics = replay.analyze_output(TRAILING)
    assert metrics["json_valid_before"] is False
    assert metrics["json_valid_after"] is True
    assert metrics["repaired"] is True
    assert "trailing_comma" in metrics["repair_stages"]
    assert metrics["gate_pass"] is True


def test_placeholder_rejected_with_category() -> None:
    metrics = replay.analyze_output(PLACEHOLDER)
    assert metrics["json_valid_after"] is True
    assert metrics["gate_pass"] is False
    assert metrics["gate_category"] == "placeholder_basis"
    assert metrics["placeholder"] is True


def test_no_citation_rejected_with_category() -> None:
    metrics = replay.analyze_output(NO_CITATION)
    assert metrics["gate_pass"] is False
    assert metrics["gate_category"] == "no_citation"


def test_unparseable_marked_json_invalid() -> None:
    metrics = replay.analyze_output(BAD_JSON)
    assert metrics["json_valid_after"] is False
    assert metrics["gate_pass"] is None
    assert metrics["gate_category"] == "json_invalid"


# ═══════════════════════════════════════════════════════════════
# 行集合汇总
# ═══════════════════════════════════════════════════════════════


def test_analyze_rows_rates_chain_split_and_rerun_records() -> None:
    rows = [
        _row(output=GOOD, record_id="rec_ok"),
        _row(output=TRAILING, record_id="rec_ok"),  # 同记录重试：一次通过即记录通过
        _row(output=PLACEHOLDER, record_id="rec_ph"),
        _row(output=NO_CITATION, vision=False, record_id="rec_nc"),
        _row(output=BAD_JSON, vision=False, record_id="rec_bad"),
    ]
    stats = replay.analyze_rows(rows)
    totals = stats["totals"]
    assert totals["calls"] == 5
    assert totals["vision_calls"] == 3
    assert totals["text_calls"] == 2
    assert totals["json_valid_before"] == 3  # GOOD + PLACEHOLDER + NO_CITATION（严格可解析）
    assert totals["json_valid_after"] == 4  # 尾逗号被修复
    assert totals["repaired_recovered"] == 1
    assert total_rate(stats, "json_valid_after_rate") == 80.0
    assert totals["gate_pass_calls"] == 2  # GOOD + TRAILING
    assert totals["gate_fail_calls"] == 2
    assert totals["gate_unparseable_calls"] == 1
    assert stats["gate_categories"] == {"placeholder_basis": 1, "no_citation": 1}
    assert stats["rerun_day"] == "2026-11-05"
    assert stats["rerun_records"]["records"] == 4
    assert stats["rerun_records"]["gate_pass_records"] == 1  # rec_ok
    assert stats["rerun_records"]["gate_fail_records"] == 3
    assert stats["repair_stages"] == {"trailing_comma": 1}


def total_rate(stats: dict[str, Any], key: str) -> float:
    return float(stats["totals"][key])


def test_analyze_rows_marks_degraded_calls() -> None:
    rows = [
        _row(output=GOOD, degradation="ragplus"),
        _row(output=GOOD, degradation="ragplus_unavailable"),
        _row(output=GOOD, degradation=None),
    ]
    stats = replay.analyze_rows(rows)
    assert stats["totals"]["degraded_calls"] == 1


def test_ground_truth_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth_file = tmp_path / "rerun_results.jsonl"
    truth_file.write_text(
        "\n".join(
            [
                json.dumps({"record_id": "rec_ok", "status": "success"}),
                json.dumps({"record_id": "rec_ph", "status": "failed"}),
                json.dumps({"record_id": "rec_cit", "status": "failed"}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    rows = [
        _row(output=GOOD, record_id="rec_ok"),
        _row(output=PLACEHOLDER, record_id="rec_ph"),
        # ground truth 说失败，但闸门会通过 → 误收（口径与重跑脚本不一致时暴露）
        _row(output=GOOD, record_id="rec_cit"),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["ground_truth_records"] == 3
    assert result["replayed_records"] == 3
    assert result["wrong_reject"] == 0
    assert result["wrong_accept"] == 1


def test_ground_truth_missing_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", tmp_path / "nope.jsonl")
    assert replay.compare_ground_truth([_row(output=GOOD)]) is None


def test_rule_regression_missing_ground_truth_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T1⑤：ground truth 不入库、缺失时规则回归对照跳过（不报错、不依赖 /tmp）。"""
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", tmp_path / "nope.jsonl")
    assert replay.rule_regression_from_ground_truth() is None


# ═══════════════════════════════════════════════════════════════
# 渲染
# ═══════════════════════════════════════════════════════════════


def test_render_markdown_contains_key_conclusions() -> None:
    stats = replay.analyze_rows([_row(output=GOOD), _row(output=TRAILING, record_id="rec2")])
    markdown = replay.render_markdown(stats, days=30)
    assert "JSON 合法率" in markdown
    assert "质量闸门" in markdown
    assert "重跑窗口" in markdown
    assert "2026-11-05" in markdown


@pytest.mark.parametrize("days", [1, 30])
def test_render_markdown_accepts_any_window(days: int) -> None:
    stats = replay.analyze_rows([])
    markdown = replay.render_markdown(stats, days=days)
    assert f"近 {days} 天" in markdown


def test_rule_regression_from_ground_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth_file = tmp_path / "rerun_results.jsonl"
    truth_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "record_id": "rec_good",
                        "status": "success",
                        "basis_new": "《安全生产法》第41条：生产经营单位必须建立安全管理制度",
                        "hazard_type": "unsafe_condition",
                        "hazard_category": "equipment",
                        "hazard_level": "general",
                    }
                ),
                json.dumps(
                    {
                        "record_id": "rec_bad_basis",
                        "status": "success",
                        "basis_new": "现场管理不到位，需要加强管理。",
                        "hazard_type": "unsafe_condition",
                        "hazard_category": "equipment",
                        "hazard_level": "general",
                    }
                ),
                json.dumps(
                    {
                        "record_id": "rec_failed",
                        "status": "failed",
                        "basis_new": "知识库中无相应条文，待人工补充",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    result = replay.rule_regression_from_ground_truth()
    assert result is not None
    assert result["checked_records"] == 2
    assert result["rule_errors"] == 1
