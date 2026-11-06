"""T09 离线回归脚本 —— 纯函数单测（不连 DB / 不调 AI / 无网络）。

脚本位于 ``backend/scripts/hazard_ai_quality_replay.py``（只读交付物）；
本文件用 importlib 按路径加载，只测其外部可观察统计契约：
    - 单条 output_text 的 A1 修复指标与 A3 闸门分类（含 C2 invalid_citation）；
    - 审计 ``input_text``（messages JSON）→ 本轮知识库 markdown → 引用证据；
    - 行集合汇总（视觉/文本拆分、按天、重跑窗口按 record 聚合、citation 段）；
    - 197 条 ground truth 一致性对照（误拒拆标签修正/真误拒，用临时文件，
      不依赖 /tmp 真实样本）；
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
    input_text: str | None = None,
    round_id: str | None = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {"bitable_record_id": record_id}
    if round_id is not None:
        extra["round_id"] = round_id
    return {
        "created_at": f"{day} 00:00:00",
        "input_text": (
            input_text
            if input_text is not None
            else ("请识别" + ("\n\n[附图 1 张]" if vision else ""))
        ),
        "output_text": output,
        "status": "success",
        "degradation_level": degradation,
        "extra": json.dumps(extra, ensure_ascii=False),
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
# C2/C3：审计 input_text → 本轮知识库 markdown → 引用证据
# ═══════════════════════════════════════════════════════════════

KNOWLEDGE = (
    "## 相关法规条款\n\n"
    "[1] 《安全生产法》 第四十一条\n"
    "生产经营单位必须建立、健全安全生产责任制，改善安全生产条件。\n\n"
    "---\n\n"
    "[2] GB 30871-2022 第5.1条\n"
    "动火作业前应办理动火作业票，落实监护人和安全措施。"
)

CITATION_GOOD = (
    '{"key_defect": "管道标识缺失", '
    + FIELD
    + ': "《安全生产法》第四十一条：\'生产经营单位必须建立、健全安全生产责任制，'
    '改善安全生产条件。\'"}'
)
FABRICATED_CITATION = (
    '{"key_defect": "x", '
    + FIELD
    + ': "《消防法》第二十八条：\'任何单位、个人不得损坏、挪用或者擅自拆除、'
    '停用消防设施、器材\'"}'
)
PLACEHOLDER_VARIANT = (
    '{"key_defect": "x", '
    + FIELD
    + ': "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充"}'
)
EMPTY_BASIS = '{"key_defect": "x", ' + FIELD + ': ""}'


def _audit_input(
    prompt: str = "现场隐患：管道标识缺失",
    *,
    knowledge: str | None = KNOWLEDGE,
) -> str:
    """构造审计 ``input_text``（messages JSON 序列化；与 audited_client 同格式）。"""
    content = prompt
    if knowledge is not None:
        content = (
            f"{prompt}\n\n---\n\n{knowledge}\n\n---\n\n"
            "## 工作规则\n\n（此处省略工作规则正文）"
        )
    messages = [
        {"role": "system", "content": "你是安全专家"},
        {"role": "user", "content": content},
    ]
    return json.dumps(messages, ensure_ascii=False)


def _write_truth(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    truth_file = tmp_path / "rerun_results.jsonl"
    truth_file.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items),
        encoding="utf-8",
    )
    return truth_file



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


# ═══════════════════════════════════════════════════════════════
# C3：审计 input_text → 知识库 markdown → 引用证据（纯函数）
# ═══════════════════════════════════════════════════════════════


def test_extract_prompt_text_joins_user_messages_only() -> None:
    """审计 input_text 是 messages JSON：只拼接 user content（system 不计入）。"""
    prompt_text = replay.extract_prompt_text(_audit_input())
    assert "现场隐患：管道标识缺失" in prompt_text
    assert "## 相关法规条款" in prompt_text
    assert "你是安全专家" not in prompt_text


def test_extract_prompt_text_handles_multimodal_content_blocks() -> None:
    """视觉调用的 content 可能是 block 列表：拼接其中的文本块。"""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图识别隐患"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            ],
        }
    ]
    prompt_text = replay.extract_prompt_text(json.dumps(messages, ensure_ascii=False))
    assert "看图识别隐患" in prompt_text


def test_extract_prompt_text_bad_json_returns_empty() -> None:
    assert replay.extract_prompt_text("完全不是 JSON") == ""
    assert replay.extract_prompt_text("") == ""


def test_extract_knowledge_markdown_block() -> None:
    prompt_text = replay.extract_prompt_text(_audit_input())
    markdown = replay.extract_knowledge_markdown(prompt_text)
    assert markdown is not None
    assert markdown.startswith("## 相关法规条款")
    assert "《安全生产法》 第四十一条" in markdown
    assert "GB 30871-2022 第5.1条" in markdown
    assert "## 工作规则" not in markdown


def test_extract_knowledge_markdown_missing_returns_none() -> None:
    assert replay.extract_knowledge_markdown("") is None
    assert replay.extract_knowledge_markdown("没有知识库块的普通 prompt") is None
    # 有工作规则但没有知识库块（RAG 降级/旧 prompt）
    no_knowledge = replay.extract_prompt_text(_audit_input(knowledge=None))
    assert replay.extract_knowledge_markdown(no_knowledge) is None


def test_citation_evidence_from_input() -> None:
    evidence = replay.citation_evidence_from_input(_audit_input())
    assert evidence is not None
    assert len(evidence.entries) == 2
    assert evidence.entries[0].doc_name == "安全生产法"
    assert "第四十一条" in evidence.entries[0].source_article
    # 与本地引用校验同源：真实命中可验证
    report = replay.verify_citations(CITATION_GOOD_BASIS, evidence)
    assert report.has_verified is True


def test_citation_evidence_from_input_bad_or_missing_returns_none() -> None:
    assert replay.citation_evidence_from_input("完全不是 JSON") is None
    assert replay.citation_evidence_from_input("") is None
    assert replay.citation_evidence_from_input(_audit_input(knowledge=None)) is None


CITATION_GOOD_BASIS = (
    "《安全生产法》第四十一条：'生产经营单位必须建立、健全安全生产责任制，改善安全生产条件。'"
)


# ═══════════════════════════════════════════════════════════════
# analyze_output：向后兼容 + 有证据时输出引用报告/gate 新分类
# ═══════════════════════════════════════════════════════════════


def test_analyze_output_backward_compatible_without_evidence() -> None:
    metrics = replay.analyze_output(GOOD)
    assert metrics["gate_pass"] is True
    assert metrics.get("citation_report") is None
    assert metrics["placeholder_variant"] is False


def test_analyze_output_with_evidence_reports_verified_citations() -> None:
    evidence = replay.citation_evidence_from_input(_audit_input())
    metrics = replay.analyze_output(CITATION_GOOD, evidence=evidence)
    report = metrics["citation_report"]
    assert report is not None
    assert report.total_units >= 1
    assert report.has_verified is True
    assert metrics["citation_zero_verified"] is False
    assert metrics["placeholder_variant"] is False
    assert metrics["gate_pass"] is True


def test_analyze_output_with_evidence_flags_invalid_citation() -> None:
    evidence = replay.citation_evidence_from_input(_audit_input())
    metrics = replay.analyze_output(FABRICATED_CITATION, evidence=evidence)
    assert metrics["gate_pass"] is False
    assert metrics["gate_category"] == "invalid_citation"
    assert metrics["citation_report"].has_verified is False
    assert metrics["citation_zero_verified"] is True


def test_analyze_output_placeholder_variant_flagged() -> None:
    # 无证据行（历史异常调用）按「开关关=P0-A 旧闸门」判定：精确占位不命中 →
    # 闸门放行（legacy rollback 语义），但占位变体指标照常标记供质量分析。
    metrics = replay.analyze_output(PLACEHOLDER_VARIANT)
    assert metrics["placeholder"] is False  # 旧精确口径漏判（P0-A 遗留）
    assert metrics["placeholder_variant"] is True
    assert metrics["gate_category"] is None


def test_analyze_output_placeholder_variant_with_evidence_rejected() -> None:
    # 有证据 + 变体零可验证 → 新闸门 placeholder_basis（C2 主路径）
    metrics = replay.analyze_output(PLACEHOLDER_VARIANT, evidence=replay.citation_evidence_from_input(_audit_input()))
    assert metrics["placeholder_variant"] is True
    assert metrics["gate_category"] == "placeholder_basis"


# ═══════════════════════════════════════════════════════════════
# analyze_rows：citation 段 + by_day 新字段
# ═══════════════════════════════════════════════════════════════


def test_analyze_rows_citation_section() -> None:
    audit = _audit_input()
    rows = [
        _row(output=CITATION_GOOD, record_id="rec_ok", input_text=audit),
        _row(output=FABRICATED_CITATION, record_id="rec_bad", input_text=audit),
        _row(output=GOOD, record_id="rec_no_ev"),  # 无知识库块 → 无证据
    ]
    stats = replay.analyze_rows(rows)
    citation = stats["citation"]
    assert citation["calls_with_evidence"] == 2
    assert citation["calls_has_verified"] == 1
    assert citation["calls_zero_verified"] == 1
    assert citation["call_verified_rate"] == 50.0
    assert citation["units_total"] >= 2
    assert citation["units_verified"] >= 1
    assert 0.0 < citation["unit_verified_rate"] <= 100.0
    # gate 新分类可见
    assert stats["gate_categories"].get("invalid_citation") == 1
    # by_day 新字段
    slot = stats["by_day"]["2026-11-05"]
    assert slot["citation_ok"] == 1
    assert slot["placeholder_variant"] == 0


def test_analyze_rows_placeholder_variant_counts() -> None:
    audit = _audit_input()
    rows = [
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_ph", input_text=audit),
    ]
    stats = replay.analyze_rows(rows)
    assert stats["citation"]["placeholder_variant_calls"] == 1
    assert stats["by_day"]["2026-11-05"]["placeholder_variant"] == 1
    assert stats["gate_categories"].get("placeholder_basis") == 1


def test_analyze_rows_stats_json_serializable() -> None:
    """--json 输出契约：新字段可 JSON 序列化（不含 dataclass 对象）。"""
    stats = replay.analyze_rows(
        [_row(output=CITATION_GOOD, input_text=_audit_input())]
    )
    payload = json.dumps(stats, ensure_ascii=False)
    decoded = json.loads(payload)
    for key in (
        "calls_with_evidence",
        "calls_has_verified",
        "calls_zero_verified",
        "units_total",
        "units_verified",
        "call_verified_rate",
        "unit_verified_rate",
        "placeholder_variant_calls",
    ):
        assert key in decoded["citation"]


# ═══════════════════════════════════════════════════════════════
# compare_ground_truth：重跑窗口筛选 + 误拒拆标签修正/真误拒
# ═══════════════════════════════════════════════════════════════


def test_ground_truth_splits_label_correction_and_genuine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth_file = _write_truth(
        tmp_path,
        [
            {"record_id": "rec_label", "status": "success"},
            {"record_id": "rec_genuine", "status": "success"},
            {"record_id": "rec_ok", "status": "success"},
        ],
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        # 已知标签缺陷：truth=success 但依据是「知识库无…」占位变体（零可验证）
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_label", input_text=audit),
        # 真误拒：空依据（与引用来源无关的失败）
        _row(output=EMPTY_BASIS, record_id="rec_genuine", input_text=audit),
        _row(output=CITATION_GOOD, record_id="rec_ok", input_text=audit),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["replayed_records"] == 3
    assert result["wrong_reject"] == 2
    assert result["wrong_reject_label_correction"] == 1
    assert result["wrong_reject_genuine"] == 1
    assert result["wrong_reject_label_correction_ids"] == ["rec_label"]


def test_ground_truth_prefers_rerun_window_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产轮调用（extra.round_id 存在）不参与 GT 对照：只看重跑窗口行。"""
    truth_file = _write_truth(
        tmp_path, [{"record_id": "rec_x", "status": "success"}]
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        # 生产轮：该记录当时通过
        _row(
            output=CITATION_GOOD,
            record_id="rec_x",
            input_text=audit,
            round_id="round-0001",
        ),
        # 重跑窗口：本轮被引用校验拒绝 → 标签修正
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_x", input_text=audit),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["window"] == "rerun"
    assert result["replayed_records"] == 1
    assert result["wrong_reject_label_correction"] == 1
    assert result["ground_truth_records"] == 1


def test_ground_truth_falls_back_to_busiest_day_without_rerun_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """extra.round_id 全有时（无重跑窗口标记）退回调用数最多的一天。"""
    truth_file = _write_truth(
        tmp_path,
        [
            {"record_id": "rec_a", "status": "success"},
            {"record_id": "rec_b", "status": "failed"},
        ],
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        # 调用数最多的一天（2 行）：rec_a 通过、rec_b 被拒（truth=failed 不算误拒）
        _row(output=CITATION_GOOD, record_id="rec_a", input_text=audit, day="2026-11-05", round_id="r1"),
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_b", input_text=audit, day="2026-11-05", round_id="r2"),
        # 其它天：rec_a 若被纳入会变成误拒，用于验证 fallback 只取最多调用日
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_a", input_text=audit, day="2026-11-04", round_id="r3"),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["window"] == "busiest_day"
    assert result["replayed_records"] == 2
    assert result["wrong_reject"] == 0


# ═══════════════════════════════════════════════════════════════
# 渲染：引用可验证性 + ground truth（含标签修正）两节
# ═══════════════════════════════════════════════════════════════


def test_render_markdown_has_citation_and_ground_truth_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth_file = _write_truth(
        tmp_path, [{"record_id": "rec_label", "status": "success"}]
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    rows = [
        _row(output=CITATION_GOOD, record_id="rec_ok", input_text=_audit_input()),
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_label", input_text=_audit_input()),
    ]
    stats = replay.analyze_rows(rows)
    truth = replay.compare_ground_truth(rows)
    assert truth is not None
    stats["ground_truth"] = truth
    markdown = replay.render_markdown(stats, days=30)
    assert "引用可验证性" in markdown
    assert "ground truth（含标签修正" in markdown
    assert "标签修正" in markdown
    assert "invalid_citation" in markdown
    assert "引用OK" in markdown


def test_ground_truth_ignores_historical_no_round_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """历史生产调用也可能缺 extra.round_id：不能全量当作重跑窗口污染对照。

    重跑窗口 = 缺 round_id 调用数最多的一天；更早日期的历史行（同缺该标记）不参与，
    否则历史 output 会把 truth=failed 记录误判成误收。
    """
    truth_file = _write_truth(
        tmp_path,
        [
            {"record_id": "rec_ok", "status": "success"},
            {"record_id": "rec_old_failed", "status": "failed"},
        ],
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        # 历史生产调用（缺 round_id，调用量少）：若纳入会误收 rec_old_failed
        _row(output=CITATION_GOOD, record_id="rec_old_failed", input_text=audit, day="2026-10-20"),
        # 重跑窗口日（缺 round_id 调用数最多）：2 行
        _row(output=CITATION_GOOD, record_id="rec_ok", input_text=audit, day="2026-11-05"),
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_old_failed", input_text=audit, day="2026-11-05"),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["window"] == "rerun"
    assert result["wrong_accept"] == 0
    assert result["wrong_accept_genuine"] == 0


def test_ground_truth_attribution_for_placeholder_note_gate_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """占位注记 + 可验证引用：新闸门放行，但旧重跑脚本 GT 标 failed → 单列归因。"""
    truth_file = _write_truth(
        tmp_path, [{"record_id": "rec_ph_cited", "status": "failed"}]
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    basis = (
        "知识库中无相应条文，待人工补充；《安全生产法》第四十一条："
        "'生产经营单位必须建立、健全安全生产责任制，改善安全生产条件。'"
    )
    output = json.dumps(
        {"key_defect": "x", "major_hazard_basis": basis}, ensure_ascii=False
    )
    rows = [_row(output=output, record_id="rec_ph_cited", input_text=_audit_input())]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["wrong_accept"] == 1
    assert result["wrong_accept_placeholder_note"] == 1
    assert result["wrong_accept_genuine"] == 0
    assert result["wrong_accept_repaired_rescue"] == 0


def test_ground_truth_success_sample_citation_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """140 条历史成功样本引用回归：GT basis_new × 审计证据 → 记录级/单元级 + 占位双口径。"""
    good_basis = (
        "《安全生产法》第四十一条：'生产经营单位必须建立、健全安全生产责任制，"
        "改善安全生产条件。'"
    )
    truth_file = _write_truth(
        tmp_path,
        [
            {"record_id": "rec_ok", "status": "success", "basis_new": good_basis},
            {
                "record_id": "rec_ph",
                "status": "success",
                "basis_new": "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充",
            },
        ],
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        _row(output=CITATION_GOOD, record_id="rec_ok", input_text=audit),
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_ph", input_text=audit),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["success_records"] == 2
    assert result["success_citation_verified"] == 1
    assert result["success_citation_units_verified"] == 1
    assert result["success_citation_units_total"] == 2
    assert result["success_placeholder_note"] == 1
    assert result["success_placeholder_pure"] == 1


# ═══════════════════════════════════════════════════════════════
# T5-fix（C3 指标补全）：变体占位率 / 视觉文本拆分 / legacy 可复现
# ═══════════════════════════════════════════════════════════════

PLACEHOLDER_WITH_CITATION_OUTPUT = json.dumps(
    {
        "key_defect": "x",
        "major_hazard_basis": (
            "知识库中无相应条文，待人工补充；《安全生产法》第四十一条："
            "'生产经营单位必须建立、健全安全生产责任制，改善安全生产条件。'"
        ),
    },
    ensure_ascii=False,
)


def test_citation_placeholder_variant_rate_uses_evidence_denominator() -> None:
    """含变体占位率分母 = 有证据调用（spec 口径），旧 placeholder_rate 为全 calls 口径。"""
    audit = _audit_input()
    rows = [
        _row(output=PLACEHOLDER_VARIANT, record_id="r_ph", input_text=audit),
        _row(output=CITATION_GOOD, record_id="r_ok", input_text=audit),
        # 无证据的精确占位调用：计入旧口径 placeholder_rate，不计入变体占位率分母
        _row(output=PLACEHOLDER, record_id="r_noev"),
    ]
    stats = replay.analyze_rows(rows)
    citation = stats["citation"]
    assert citation["calls_with_evidence"] == 2
    assert citation["placeholder_variant_calls"] == 1
    assert citation["placeholder_variant_rate"] == 50.0
    # 旧 P0-A 口径保留：精确占位标记 / 全量 calls
    assert stats["totals"]["placeholder_calls"] == 1
    assert stats["totals"]["placeholder_rate"] == 33.3
    assert citation["placeholder_variant_rate"] != stats["totals"]["placeholder_rate"]


def test_chain_summary_includes_citation_metrics() -> None:
    """citation 指标进视觉/文本拆分；无证据调用不计入可验证率分母。"""
    audit = _audit_input()
    rows = [
        _row(
            output=CITATION_GOOD,
            record_id="v1",
            # 视觉调用：input_text（messages JSON）内含 vision 标记
            input_text=_audit_input(prompt="现场隐患：管道标识缺失\n\n[附图 1 张]"),
        ),
        _row(output=FABRICATED_CITATION, record_id="t1", vision=False, input_text=audit),
        _row(output=CITATION_GOOD, record_id="t2", vision=False),  # 无证据 → 不计分母
    ]
    stats = replay.analyze_rows(rows)
    vision = stats["vision"]
    assert vision["calls"] == 1
    assert vision["calls_with_evidence"] == 1
    assert vision["calls_has_verified"] == 1
    assert vision["call_verified_rate"] == 100.0
    assert vision["units_total"] >= 1
    assert vision["units_verified"] >= 1
    text = stats["text"]
    assert text["calls"] == 2
    assert text["calls_with_evidence"] == 1  # 无证据调用不计入
    assert text["calls_has_verified"] == 0
    assert text["call_verified_rate"] == 0.0
    assert text["units_total"] >= 1
    assert text["unit_verified_rate"] == 0.0


def test_analyze_rows_legacy_gate_forces_no_evidence() -> None:
    """--legacy-gate：analyze 链强制 evidence=None → P0-A 旧闸门语义、citation 为空。"""
    audit = _audit_input()
    rows = [
        _row(
            output=PLACEHOLDER_WITH_CITATION_OUTPUT,
            record_id="r1",
            input_text=audit,
        )
    ]
    # 新口径（默认）：占位注记 + 可验证引用 → 放行
    strict = replay.analyze_rows(rows)
    assert strict["legacy_gate"] is False
    assert strict["citation"]["calls_with_evidence"] == 1
    assert strict["gate_categories"] == {}
    # legacy 旧口径：精确占位标记 → 拒绝；citation 指标为空
    legacy = replay.analyze_rows(rows, legacy_gate=True)
    assert legacy["legacy_gate"] is True
    assert legacy["citation"]["calls_with_evidence"] == 0
    assert legacy["gate_categories"].get("placeholder_basis") == 1
    assert legacy["totals"]["placeholder_calls"] == 1


def test_compare_ground_truth_outputs_legacy_caliber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GT 对照同时输出新口径与 legacy 旧口径（含 A1 救援归因），可并列对照。"""
    truth_file = _write_truth(
        tmp_path,
        [
            # 变体占位：新口径正确拒绝（标签修正）；legacy 精确占位漏判 → 放行
            {"record_id": "rec_label", "status": "success"},
            # 占位+真实引用：新口径放行；legacy 无条件拒绝
            {"record_id": "rec_ph_cited", "status": "failed"},
        ],
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        _row(output=PLACEHOLDER_VARIANT, record_id="rec_label", input_text=audit),
        _row(
            output=PLACEHOLDER_WITH_CITATION_OUTPUT,
            record_id="rec_ph_cited",
            input_text=audit,
        ),
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    # 新口径
    assert result["wrong_reject"] == 1
    assert result["wrong_reject_label_correction"] == 1
    assert result["wrong_reject_genuine"] == 0
    assert result["wrong_accept"] == 1
    assert result["wrong_accept_placeholder_note"] == 1
    # legacy 旧口径
    legacy = result["legacy"]
    assert legacy["window"] == result["window"]
    assert legacy["replayed_records"] == 2
    assert legacy["wrong_reject"] == 0
    assert legacy["wrong_accept"] == 0
    assert legacy["wrong_accept_repaired_rescue"] == 0
    assert legacy["wrong_accept_genuine"] == 0


def test_render_markdown_citation_calibers_and_vision_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    truth_file = _write_truth(
        tmp_path, [{"record_id": "rec_ok", "status": "success"}]
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    audit = _audit_input()
    rows = [
        _row(output=CITATION_GOOD, record_id="rec_ok", input_text=audit),
        _row(output=FABRICATED_CITATION, record_id="rec_bad", input_text=audit, vision=False),
    ]
    stats = replay.analyze_rows(rows)
    truth = replay.compare_ground_truth(rows)
    assert truth is not None
    stats["ground_truth"] = truth
    markdown = replay.render_markdown(stats, days=30)
    # 变体占位率 + 两口径说明
    assert "含变体占位率" in markdown
    assert "P0-A 旧口径" in markdown
    # 视觉/文本 两行
    assert "| 视觉 |" in markdown
    assert "| 文本 |" in markdown
    # legacy 口径并列
    assert "legacy 旧口径" in markdown
    assert "A1 修复救援" in markdown


def test_cli_legacy_gate_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI --legacy-gate 默认关；开启后主链走旧闸门语义（citation 为空）。"""
    rows = [
        _row(
            output=PLACEHOLDER_WITH_CITATION_OUTPUT,
            record_id="r1",
            input_text=_audit_input(),
        )
    ]

    async def fake_fetch(
        dsn: str, *, days: int, scenario: str, limit: int
    ) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(replay, "fetch_rows", fake_fetch)
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", Path("/nonexistent/nope.jsonl"))

    rc = replay.main(["--dsn", "postgresql://fake", "--json", "--legacy-gate"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["legacy_gate"] is True
    assert payload["citation"]["calls_with_evidence"] == 0
    assert payload["gate_categories"].get("placeholder_basis") == 1

    # 默认（不加 flag）= 新口径
    rc = replay.main(["--dsn", "postgresql://fake", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["legacy_gate"] is False
    assert payload["citation"]["calls_with_evidence"] == 1


def test_label_correction_only_for_placeholder_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3：非占位的『非空依据+零可验证』拒绝必须计真误拒，不能自证为标签修正。"""
    truth_file = _write_truth(
        tmp_path, [{"record_id": "rec_unverified", "status": "success"}]
    )
    monkeypatch.setattr(replay, "GROUND_TRUTH_FILE", truth_file)
    rows = [
        _row(
            output=FABRICATED_CITATION,
            record_id="rec_unverified",
            input_text=_audit_input(),
        )
    ]
    result = replay.compare_ground_truth(rows)
    assert result is not None
    assert result["wrong_reject"] == 1
    assert result["wrong_reject_label_correction"] == 0
    assert result["wrong_reject_genuine"] == 1
    assert result["wrong_reject_label_correction_ids"] == []
