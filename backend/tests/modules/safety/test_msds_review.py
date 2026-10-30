"""MSDS 错别字审核 + 修订同步机制测试（2026-10-30）。

纯单测（零 DB/零真机）：hash 判定矩阵、entry 反查（外观列新旧名兼容、
富文本段兜底）、_map_fields 新旧列共存不覆盖、AI 校对输出过滤与格式化、
修订记录裁剪。接缝：create_ai_service 替身（chat_parsed 假返回）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.feishu.msds_bitable_handler import _map_fields
from app.modules.safety.service.msds_review import (
    FIELD_TYPO_DETAIL,
    FIELD_TYPO_STATUS,
    REVISION_LOG_MAX_LINES,
    TYPO_STATUS_CLEAN,
    TYPO_STATUS_SUSPECT,
    append_revision_log,
    decide_pdf_sync,
    entry_from_bitable_fields,
    format_typo_detail,
    msds_content_hash,
    proofread_entry,
    typo_review_fields,
    _validate_issues,
)


# ── 内容 hash ──


def test_content_hash_stable_and_whitespace_normalized():
    a = {"name": "乙醇", "appearance": "无色液体"}
    b = {"name": "乙醇", "appearance": "无色 液体\n"}  # 仅空白差异
    c = {"name": "乙醇", "appearance": "无色液体，有酒香"}  # 实质修改
    assert msds_content_hash(a) == msds_content_hash(b)
    assert msds_content_hash(a) != msds_content_hash(c)


def test_content_hash_independent_of_extra_keys():
    a = {"name": "乙醇"}
    b = {"name": "乙醇", "label_elements": "GHS02", "msds_attachment": [{"x": 1}]}
    # label_elements 不在内容比对面（台账表无该列），附件/日期不参与
    assert msds_content_hash(a) == msds_content_hash(b)


# ── 同步判定矩阵 ──


@pytest.mark.parametrize(
    "current,pdf,marker,force,expected",
    [
        ("h1", "h1", None, False, "skip_up_to_date"),
        ("h1", "h1", "h1", False, "skip_up_to_date"),  # up_to_date 优先
        ("h1", "h0", "h1", False, "skip_self_write"),
        ("h1", None, None, False, "regenerate"),  # 存量行无 hash
        ("h1", "h0", None, False, "regenerate"),  # 人工修改
        ("h1", "h0", "h2", False, "regenerate"),  # 标记过期不匹配
        ("h1", "h1", None, True, "regenerate"),  # force 恒重建
    ],
)
def test_decide_pdf_sync(current, pdf, marker, force, expected):
    assert decide_pdf_sync(current, pdf, marker, force=force) == expected


# ── Bitable fields → entry ──


def test_entry_from_bitable_fields_new_and_legacy_appearance():
    base = {"物质名称": "乙醇", "CAS号": "64-17-5"}
    assert entry_from_bitable_fields({**base, "外观与性状": "无色液体"})["appearance"] == "无色液体"
    # 旧列名环境（未改名）回落
    assert entry_from_bitable_fields({**base, "外观与现状": "无色液体"})["appearance"] == "无色液体"
    # 新列优先，旧列空值不覆盖
    both = entry_from_bitable_fields(
        {**base, "外观与性状": "无色液体", "外观与现状": ""}
    )
    assert both["appearance"] == "无色液体"


def test_entry_from_bitable_fields_rich_text_segments():
    fields = {"物质名称": [{"text": "乙", "type": "text"}, {"text": "醇", "type": "text"}]}
    assert entry_from_bitable_fields(fields)["name"] == "乙醇"


def test_entry_from_bitable_fields_excludes_non_content_columns():
    entry = entry_from_bitable_fields({
        "物质名称": "乙醇",
        "日期": 1785945600000,
        "MSDS附件": [{"file_token": "x"}],
        "错别字审核": "疑似错别字",
        "修订记录": "2026-10-30 …",
    })
    assert set(entry) == {"name"}
    assert "typo_review_status" not in entry and "source_date" not in entry


# ── 镜像映射（新旧列共存 + 审核字段）──


def test_map_fields_appearance_fallback_no_overwrite():
    legacy = _map_fields({"外观与现状": "无色液体"})
    modern = _map_fields({"外观与性状": "无色液体"})
    both = _map_fields({"外观与性状": "无色液体", "外观与现状": None})
    assert legacy["appearance"] == modern["appearance"] == both["appearance"] == "无色液体"


def test_map_fields_includes_review_and_revision_columns():
    mapped = _map_fields({
        "物质名称": "乙醇",
        "错别字审核": "疑似错别字",
        "错别字明细": "「急救措施」：『迅术』→『迅速』（形近字）",
        "修订记录": "2026-10-30 15:04 内容字段已修改，标准 PDF 已同步重新生成",
    })
    assert mapped["typo_review_status"] == "疑似错别字"
    assert "迅术" in mapped["typo_review_detail"]
    assert "PDF" in mapped["revision_log"]


# ── 校对输出 ──


def test_validate_issues_filters_unknown_field_and_dups():
    raw = [
        {"field": "急救措施", "original": "迅术脱离", "suggestion": "迅速脱离", "reason": "形近字"},
        {"field": "不存在的字段", "original": "x", "suggestion": "y"},  # 字段名不在清单 → 丢
        {"field": "急救措施", "original": "同样", "suggestion": "同样"},  # 原文=建议 → 丢
        {"field": "健康危害", "original": "", "suggestion": "y"},  # 空片段 → 丢
        "garbage-string",  # 非 dict → 丢
    ]
    valid = _validate_issues(raw)
    assert len(valid) == 1
    assert valid[0]["field"] == "急救措施"


def test_validate_issues_accepts_english_field_key():
    # AI 偶尔回传英文 key 也认（known_fields 含 key 面）
    valid = _validate_issues([
        {"field": "first_aid", "original": "迅术脱离", "suggestion": "迅速脱离"},
    ])
    assert valid and valid[0]["field"] == "first_aid"


def test_typo_review_fields_status_and_detail():
    issues = [{
        "field": "急救措施", "original": "迅术脱离现场",
        "suggestion": "迅速脱离现场", "reason": "形近字",
    }]
    fields = typo_review_fields(issues)
    assert fields[FIELD_TYPO_STATUS] == TYPO_STATUS_SUSPECT
    assert "『迅术脱离现场』→『迅速脱离现场』" in fields[FIELD_TYPO_DETAIL]
    assert typo_review_fields([]) == {
        FIELD_TYPO_STATUS: TYPO_STATUS_CLEAN, FIELD_TYPO_DETAIL: "",
    }


def test_format_typo_detail_empty():
    assert format_typo_detail([]) == ""


# ── 修订记录裁剪 ──


def test_append_revision_log_caps_lines():
    existing = "\n".join(f"2026-01-01 00:0{i} 第{i}行" for i in range(REVISION_LOG_MAX_LINES))
    appended = append_revision_log(existing, "新一行")
    lines = appended.splitlines()
    assert len(lines) == REVISION_LOG_MAX_LINES
    assert lines[-1].endswith("新一行")
    assert "第0行" not in appended  # 最旧行被裁


def test_append_revision_log_rich_text_segments():
    appended = append_revision_log([{"text": "2026-10-30 旧记录"}], "第二条")
    assert "旧记录" in appended and "第二条" in appended


# ── AI 校对接缝（create_ai_service 替身）──


class _FakeAI:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload
        self.calls: list[dict] = []

    async def chat_parsed(self, messages, expected_keys=None, temperature=None):
        self.calls.append({"messages": messages, "expected_keys": expected_keys})
        return self._payload

    async def close(self):
        return None


@pytest.fixture()
def fake_ai_factory(monkeypatch):
    holder: dict[str, _FakeAI] = {}

    def _install(payload: dict[str, Any]) -> _FakeAI:
        ai = _FakeAI(payload)
        holder["ai"] = ai

        import app.modules.safety.service.config as cfg

        monkeypatch.setattr(cfg, "create_ai_service", lambda *a, **k: ai)
        return ai

    yield _install


async def test_proofread_entry_returns_validated_issues(fake_ai_factory):
    ai = fake_ai_factory({"issues": [
        {"field": "急救措施", "original": "迅术脱离", "suggestion": "迅速脱离", "reason": "形近字"},
        {"field": "未知字段", "original": "a", "suggestion": "b"},
    ]})
    issues = await proofread_entry({"name": "乙醇", "first_aid": "吸入：迅术脱离现场。"})
    assert len(issues) == 1
    assert issues[0]["suggestion"] == "迅速脱离"
    # 只传非空字段给 AI
    sent = ai.calls[0]["messages"][1]["content"]
    assert "乙醇" in sent and "急救措施" in sent


async def test_proofread_entry_skips_empty_entry(fake_ai_factory):
    fake_ai_factory({"issues": []})
    assert await proofread_entry({}) == []


async def test_proofread_entry_none_issues_tolerated(fake_ai_factory):
    fake_ai_factory({"issues": None})
    assert await proofread_entry({"name": "乙醇"}) == []


# ── 标准 PDF 单页契约（打印需求，2026-10-30）──


def test_standard_pdf_single_page(tmp_path):
    """常规与超长内容都必须输出单页（自适应缩放 + 极端截断安全阀）。"""
    pypdf = pytest.importorskip("pypdf")
    from app.modules.safety.feishu.msds_pdf import build_standard_msds_pdf

    base = {
        "name": "乙醇；酒精", "cas_no": "64-17-5", "molecular_formula": "C2H6O",
        "un_no": "1170", "hazard_statement": "高度易燃液体和蒸气，其蒸气与空气混合,能形成爆炸性混合物。",
        "appearance": "无色液体,有酒香。", "solubility": "与水混溶。",
        "melting_point": "-114.1℃", "boiling_point": "78.3℃", "flash_point": "13℃（CC）",
        "relative_density": "1.59", "explosion_upper_limit": "19.0", "explosion_lower_limit": "3.3",
        "autoignition_temperature": "363℃", "decomposition_temperature": "无资料",
        "pc_twa": "1000ppm", "pc_stel": "/", "mac": "/",
        "health_hazard": "本品为中枢神经系统抑制剂。" * 20,
        "first_aid": "皮肤接触：立即脱去污染的衣着,用流动清水彻底冲洗。就医。" * 10,
        "fire_fighting": "灭火剂:用抗溶性泡沫、干粉、二氧化碳、砂土灭火。" * 8,
        "leakage_response": "消除所有点火源。根据液体流动和蒸气扩散的影响区域划定警戒区。" * 8,
        "waste_disposal": "废弃化学品：建议用焚烧法处置。" * 6,
        "exposure_controls": "工程控制：生产过程密闭,加强通风。" * 8,
        "handling_storage": "操作注意事项：密闭操作,全面通风。" * 10,
        "stability_reactivity": "稳定性稳定 禁配物强氧化剂、酸类、酸酐、碱金属、胺类。" * 6,
        "environmental_hazard": "对水生环境有害。" * 6,
    }
    out1 = tmp_path / "normal.pdf"
    build_standard_msds_pdf(base, str(out1))
    assert len(pypdf.PdfReader(str(out1)).pages) == 1

    extreme = {k: (v * 30 if isinstance(v, str) else v) for k, v in base.items()}
    out2 = tmp_path / "extreme.pdf"
    build_standard_msds_pdf(extreme, str(out2))
    assert len(pypdf.PdfReader(str(out2)).pages) == 1
