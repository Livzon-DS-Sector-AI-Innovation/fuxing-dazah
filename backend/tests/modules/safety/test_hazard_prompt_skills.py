"""P1-3 T4 —— skills 化 prompt：①主链零漂移迁移 + 复核员 prompt md 化。

零漂移锁：迁移前固化的 golden 字节快照（tests/fixtures/hazard_prompt_golden）
与迁移后组装结果逐字节比对；SYSTEM_ROLE sha256 不变（prompt_version 口径
连续）。硬护栏（CRITICAL_CONSTRAINTS/OUTPUT_FORMAT）留代码，md 不可覆盖。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.modules.safety.ai_hazard_identification import prompts
from app.modules.safety.ai_hazard_identification.prompt_loader import (
    block_version,
    load_text_block,
)

GOLDEN = Path(__file__).parents[2] / "fixtures" / "hazard_prompt_golden"

CTX_TEXT = (
    "隐患编号：HZ-20261109-001\n责任部门：生产一部\n地点/部位：三车间平台\n"
    "检查人员：张三\n检查时间：2026-11-09\n隐患描述：平台边缘无防护栏杆，距地 3 米"
)
CTX_VISION = (
    "## 隐患文本描述（仅供参考，以图片分析为准）\n隐患编号：HZ-20261109-002\n"
    "隐患描述：防爆电箱引入口未封堵"
)
KNOWLEDGE = (
    "## 相关法规条款\n\n[1] 《消防法》 第十条\n应设置防护栏杆。\n\n---\n\n"
    "[2] GB 30871-2022 第5.2条\n高处作业应正确佩戴安全带。"
)


def _golden(name: str) -> str:
    return (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")


# ── 零漂移：组装结果与迁移前 golden 逐字节一致 ──────────────────────────────


@pytest.mark.parametrize(
    ("name", "built"),
    [
        ("text_full", lambda: prompts.build_full_prompt(CTX_TEXT, vision_mode=False)),
        (
            "text_nofewshot",
            lambda: prompts.build_full_prompt(
                CTX_TEXT, vision_mode=False, include_fewshot=False
            ),
        ),
        (
            "text_knowledge",
            lambda: prompts.build_full_prompt(
                CTX_TEXT, vision_mode=False, knowledge_context=KNOWLEDGE
            ),
        ),
        ("vision_full", lambda: prompts.build_full_prompt(CTX_VISION, vision_mode=True)),
        (
            "vision_knowledge",
            lambda: prompts.build_full_prompt(
                CTX_VISION, vision_mode=True, knowledge_context=KNOWLEDGE
            ),
        ),
        ("system_role", lambda: prompts.system_role()),
        ("work_rules", lambda: prompts.work_rules()),
        ("defect_substance_rules", lambda: prompts.defect_substance_rules()),
    ],
)
def test_golden_zero_drift(name: str, built) -> None:
    assert built() == _golden(name), f"{name} 与迁移前 golden 漂移"


def test_golden_fewshot_serialization_identical() -> None:
    """few-shot md 化后重序列化逐字节一致（键序/缩进/ensure_ascii 不变）。"""
    dumped = json.dumps(
        prompts.fewshot_examples(), ensure_ascii=False, indent=2
    )
    assert dumped == (GOLDEN / "fewshot_examples.json").read_text(encoding="utf-8")


def test_system_role_sha256_unchanged() -> None:
    """SYSTEM_ROLE sha256 不变（ai_call_audits.prompt_version 口径连续）。"""
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    current = hashlib.sha256(prompts.system_role().encode("utf-8")).hexdigest()
    assert current == manifest["system_role"]


# ── 硬护栏留代码：md 不含且不可覆盖输出格式段 ────────────────────────────────


def test_hard_guardrails_stay_in_code() -> None:
    """CRITICAL_CONSTRAINTS / OUTPUT_FORMAT 不在 md 目录（md 改不动硬护栏）。"""
    skills_dir = (
        prompts.__file__.rsplit("/", 1)[0] + "/prompt_skills"
    )
    md_text = "".join(
        p.read_text(encoding="utf-8") for p in Path(skills_dir).glob("*.md")
    )
    assert "CRITICAL_CONSTRAINTS" not in md_text
    # 硬护栏文本本体也不进 md（输出 JSON schema 段）
    assert prompts.OUTPUT_FORMAT not in md_text
    # 组装时硬护栏恒以代码常量为准
    built = prompts.build_full_prompt(CTX_TEXT, vision_mode=False, include_fewshot=False)
    assert prompts.CRITICAL_CONSTRAINTS in built
    assert prompts.OUTPUT_FORMAT in built


# ── loader 行为 ──────────────────────────────────────────────────────────────


def test_loader_reads_md_and_version() -> None:
    text = load_text_block("work-rules", fallback="FALLBACK")
    assert text == _golden("work_rules")
    version = block_version("work-rules")
    assert version and version != "fallback"


def test_loader_missing_file_falls_back() -> None:
    assert load_text_block("不存在的块", fallback="FB") == "FB"
    assert block_version("不存在的块") == "fallback"


def test_loader_corrupt_frontmatter_falls_back(tmp_path: Path) -> None:
    from app.modules.safety.ai_hazard_identification import prompt_loader

    bad = tmp_path / "bad.md"
    bad.write_text("---\nversion: [broken\n---\n正文", encoding="utf-8")
    parsed = prompt_loader._parse_md(bad.read_text(encoding="utf-8"))
    # 非法 frontmatter 视为无 frontmatter，正文照常返回
    assert parsed == ("", "---\nversion: [broken\n---\n正文") or parsed[1].endswith("正文")


def test_loader_fewshot_pair() -> None:
    """成对加载：单 md 文件拆出 marker 与 3 个示例（分隔标记缺失回落）。"""
    from app.modules.safety.ai_hazard_identification.prompt_loader import load_fewshot

    marker, examples = load_fewshot(
        fallback_marker="FB_MARKER", fallback_examples=[]
    )
    assert marker == _golden("fewshot_marker")
    # P2-3 T03：fewshot 5→3 例（保 1/4/5，用户拍板有意压缩）
    assert isinstance(examples, list) and len(examples) == 3
    # 分隔标记缺失 → 整体回落
    degraded = load_fewshot(fallback_marker="FB_MARKER", fallback_examples=[1])
    assert degraded == ("FB_MARKER", [1]) or degraded[0] == _golden("fewshot_marker")


def test_fewshot_kept_examples_p23() -> None:
    """P2-3 有意压缩：保留例 1/4/5（例内文本零改动），删例 2/3。

    - 例 4/5 是 defect_substance 字段仅有的两个展示（v2 核心），必须保留；
    - 保留例的输出 dict 与压缩前逐字节一致（例内文本零改动）；
    - md 兜底常量与 md 文件同步（删 md 即回滚到同一 3 例集合）。
    """
    kept_inputs = [ex["input"] for ex in prompts.fewshot_examples()]
    assert kept_inputs == [
        "防爆电箱接线口未使用防爆堵头封堵，箱体内部积尘严重",
        "一级动火作业票（编号DH-2026-0612）中，现场监护人、动火负责人签章栏空白，审批时间与实际作业时间不一致",
        "车间操作规程现场放置的为打印版本，非正式签发版本，未加盖签发章",
    ]
    # 例内文本零改动：兜底常量与 md 读出完全一致
    assert prompts.fewshot_pair()[1] == prompts.FEWSHOT_EXAMPLES
    # defect_substance 展示仍在（例 4 substantive / 例 5 procedural；例 1 旧格式无该字段）
    substances = [ex["output"].get("defect_substance") for ex in prompts.fewshot_examples()]
    assert substances == [None, "substantive", "procedural"]


def test_loader_mtime_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """mtime 未变走缓存；mtime 变更后重读（热更新）。"""
    from app.modules.safety.ai_hazard_identification import prompt_loader

    prompt_loader._cache.clear()
    first = load_text_block("work-rules", fallback="FB")
    # 缓存命中（无第二次 IO 也可断言 cache 里有条目）
    assert "work-rules" in prompt_loader._cache
    second = load_text_block("work-rules", fallback="FB")
    assert first == second


# ── 复核员 prompt md 化 ──────────────────────────────────────────────────────


def test_reviewer_prompt_from_md_matches_fallback_semantics() -> None:
    """复核员 prompt：md 存在时与代码兜底常量同义（observe 铁律均在）。"""
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        REVIEWER_PROMPT,
        reviewer_prompt,
    )

    text = reviewer_prompt()
    assert "observe" in text and "不写回" in text and "人工" in text
    # md 化后版本号可读
    assert block_version("exception-reviewer") != "fallback"
    # 兜底常量保留（md 缺失时离线可用）
    assert "observe" in REVIEWER_PROMPT


def test_reviewer_prompt_bytes_md_equals_fallback() -> None:
    """md 内容与代码兜底逐字节一致（迁移即搬家，不改语义）。"""
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        REVIEWER_PROMPT,
        reviewer_prompt,
    )

    assert reviewer_prompt() == REVIEWER_PROMPT
