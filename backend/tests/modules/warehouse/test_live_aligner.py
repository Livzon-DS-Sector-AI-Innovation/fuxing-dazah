"""S2 ticket 02 验收：主数据对齐器（单测 + live 主数据拉取 + live 对齐评估）。

单测（纯函数零网络，假缓存/假 fetch 注入）：
- normalize_name：全角转半角（含全角空格/逗号/括号）、大小写、内部空白；
- match_material：exact / prefix（双向，识别名与主数据名互为前缀）/
  fuzzy（difflib ratio ≥0.6）/ none（空名、低 ratio）；多候选时
  生产商/供应商 tie-break；
- 主数据缓存 TTL：注入 `_now` 时钟，TTL 内复用不重拉、过期后刷新。

live（真实测试版 Base material_master 表，依赖仓储飞书凭证）：
- test_live_master_fetch：全量分页拉取并载入缓存，断言 ≥500 条；
- test_live_align_batch_hit_rate：truth.jsonl 真值物料名批量对齐，
  命中率 =（exact + prefix + 0.5×fuzzy）/ total ≥95% 验收线；
  未命中/模糊明细全部打印（如实报告，不造假）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_aligner.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.modules.warehouse.agent.pipeline.aligner as aligner_module
from app.modules.warehouse.agent.pipeline.aligner import (
    MASTER_CACHE_TTL,
    AlignedReceipt,
    MaterialMasterEntry,
    align_batch,
    align_receipt,
    get_master_entries,
    match_material,
    normalize_name,
)
from app.modules.warehouse.agent.pipeline.recognizer import (
    RecognizedField,
    RecognizedReceipt,
)

# 仓库根 = tests/modules/warehouse/test_x.py 往上 4 级
REPO_ROOT = Path(__file__).resolve().parents[4]
DATASET_DIR = REPO_ROOT / ".scratch" / "s2-recognition" / "dataset"
TRUTH_PATH = DATASET_DIR / "truth.jsonl"


# ── 测试数据工厂 ──


def _entry(
    name: str,
    *,
    code: str = "C000",
    level: str = "工业级",
    spec: str = "25Kg/包",
    category: str = "原辅料",
    sub_category: str = "固体（原料库）",
    unit: str = "吨",
    manufacturer: str = "甲生产商",
    supplier: str = "乙供应商",
    erp_code: str = "E000",
) -> MaterialMasterEntry:
    return MaterialMasterEntry(
        name=name,
        code=code,
        level=level,
        spec=spec,
        category=category,
        sub_category=sub_category,
        unit=unit,
        manufacturer=manufacturer,
        supplier=supplier,
        erp_code=erp_code,
    )


def _fake_entries() -> list[MaterialMasterEntry]:
    """形态参照 material_master 实测（同名多记录/带编号包材名）。"""
    return [
        _entry("硫酸铵", code="10107", manufacturer="OXOID", supplier="安徽天地生命科技有限公司"),
        _entry("硫酸", code="10212", manufacturer="广西华御吸附材料科技有限公司"),
        _entry("酵母浸粉", code="10304", manufacturer="河北久鹏制药有限公司"),
        _entry("纸箱(19#)", code="20819", category="包材", manufacturer="良和包装（浙江）有限公司"),
        _entry("纸箱(18#)", code="20818", category="包材", manufacturer="良和包装（浙江）有限公司"),
        _entry("氯化铵", code="10101", manufacturer="湖北双环科技股份有限公司"),
    ]


def _receipt(
    name: str | None,
    *,
    manufacturer: str | None = None,
    supplier: str | None = None,
) -> RecognizedReceipt:
    return RecognizedReceipt(
        material_name=RecognizedField(value=name, confidence=0.9),
        vendor_batch_no=RecognizedField(),
        quantity=RecognizedField(),
        unit=RecognizedField(),
        supplier=RecognizedField(value=supplier),
        manufacturer=RecognizedField(value=manufacturer),
        plate_no=RecognizedField(),
        contract_no=RecognizedField(),
    )


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[float, list[MaterialMasterEntry]]]:
    """替换模块级缓存并预填假主数据（TTL 内，get_master_entries 不会真拉）。"""
    cache: dict[str, tuple[float, list[MaterialMasterEntry]]] = {}
    monkeypatch.setattr(aligner_module, "_master_cache", cache)
    cache[aligner_module.MASTER_CACHE_KEY] = (aligner_module._now(), _fake_entries())
    return cache


# ── 单测：归一化 ──


def test_normalize_fullwidth_space_and_case() -> None:
    """全角空格/内部空格/大小写/全半角标点归一后一致。"""
    assert normalize_name("硫　酸") == normalize_name("硫酸")  # 全角空格
    assert normalize_name("硫 酸") == normalize_name("硫酸")  # 内部半角空格
    assert normalize_name("Kg") == "kg"  # 大小写统一
    assert normalize_name(" AR级 ") == "ar级"  # 首尾空白
    assert normalize_name("2，4，5-三氨基") == normalize_name("2,4,5-三氨基")  # 全角逗号
    assert normalize_name("酵母浸粉（食品级）") == normalize_name("酵母浸粉(食品级)")  # 全角括号


# ── 单测：四级匹配 ──


def test_match_exact() -> None:
    """归一化精确相等 → exact；归一化容错（全角空格）同样 exact。"""
    entry, confidence, detail = match_material("硫酸铵", _fake_entries())
    assert confidence == "exact"
    assert entry is not None and entry.code == "10107"
    assert detail["matched_by"] == "exact"
    assert detail["candidate"] == "硫酸铵"

    entry2, confidence2, _ = match_material("硫　酸", _fake_entries())
    assert confidence2 == "exact"
    assert entry2 is not None and entry2.name == "硫酸"


def test_match_prefix_forward() -> None:
    """识别名是主数据名前缀（识别'硫酸'，主数据仅'硫酸铵'）→ prefix。"""
    entries = [e for e in _fake_entries() if e.name != "硫酸"]
    entry, confidence, detail = match_material("硫酸", entries)
    assert confidence == "prefix"
    assert entry is not None and entry.name == "硫酸铵"  # 多候选取最短（最接近）
    assert detail["matched_by"] == "prefix"
    assert detail["direction"] == "forward"


def test_match_prefix_reverse() -> None:
    """主数据名是识别名前缀（识别'酵母浸粉（食品级）'）→ prefix（反向）。"""
    entry, confidence, detail = match_material("酵母浸粉（食品级）", _fake_entries())
    assert confidence == "prefix"
    assert entry is not None and entry.name == "酵母浸粉"
    assert detail["direction"] == "reverse"


def test_match_fuzzy_above_threshold() -> None:
    """互不为前缀但 ratio ≥0.6（'硫酸按' vs '硫酸铵'）→ fuzzy。"""
    entries = [_entry("硫酸铵", code="10107")]
    entry, confidence, detail = match_material("硫酸按", entries)
    assert confidence == "fuzzy"
    assert entry is not None and entry.name == "硫酸铵"
    assert detail["ratio"] is not None and detail["ratio"] >= 0.6


def test_match_fuzzy_below_threshold_is_none() -> None:
    """ratio <0.6 → none（不硬凑）。"""
    entry, confidence, detail = match_material("完全不相关的东西xyz", _fake_entries())
    assert confidence == "none"
    assert entry is None
    assert detail["matched_by"] == "none"


def test_match_empty_name_is_none() -> None:
    """识别名为空/纯空白 → 直接 none，不进匹配。"""
    for name in ("", "   ", None):
        entry, confidence, detail = match_material(name or "", _fake_entries())
        assert confidence == "none"
        assert entry is None


def test_match_manufacturer_tiebreak_on_exact() -> None:
    """同名多条记录（同名不同生产商）→ 识别生产商命中者优先。"""
    entries = [
        _entry("硫酸", code="10212", manufacturer="广西华御吸附材料科技有限公司"),
        _entry("硫酸", code="10228", manufacturer="广州市谊丽科技有限公司"),
    ]
    entry, confidence, detail = match_material(
        "硫酸", entries, manufacturer="广州市谊丽科技有限公司"
    )
    assert confidence == "exact"
    assert entry is not None and entry.code == "10228"
    assert detail["manufacturer_matched"] is True


def test_match_prefix_candidate_tiebreak() -> None:
    """prefix 多候选（'纸箱(19#)'/'纸箱(18#)'）→ 生产商/供应商辅助择优。"""
    entries = [
        _entry("纸箱(19#)", code="20819", manufacturer="A厂", supplier="S1"),
        _entry("纸箱(18#)", code="20818", manufacturer="B厂", supplier="S2"),
    ]
    entry, confidence, _ = match_material("纸箱", entries, manufacturer="B厂")
    assert confidence == "prefix"
    assert entry is not None and entry.code == "20818"


# ── 单测：align_receipt 集成（假缓存） ──


async def test_align_receipt_builds_aligned_fields(fake_cache: dict) -> None:
    """exact 命中：aligned 带标准名/代码/大类/细分类/单位建议 + 匹配标记。"""
    aligned = await align_receipt(
        _receipt("硫酸铵", manufacturer="OXOID", supplier="安徽天地生命科技有限公司")
    )
    assert isinstance(aligned, AlignedReceipt)
    assert aligned.match_confidence == "exact"
    assert aligned.aligned["material_name"] == "硫酸铵"
    assert aligned.aligned["code"] == "10107"
    assert aligned.aligned["material_category"] == "原辅料"
    assert aligned.aligned["unit_suggestion"] == "吨"
    assert aligned.aligned["manufacturer_matched"] is True
    assert aligned.aligned["supplier_matched"] is True
    assert aligned.recognized.material_name.value == "硫酸铵"  # recognized 原样保留


async def test_align_receipt_none_keeps_original(fake_cache: dict) -> None:
    """未命中 → aligned.material_name 保留识别原文、confidence=none。"""
    aligned = await align_receipt(_receipt("乱七八糟不存在的东西xyz"))
    assert aligned.match_confidence == "none"
    assert aligned.aligned["material_name"] == "乱七八糟不存在的东西xyz"
    assert aligned.aligned["code"] == ""


async def test_align_receipt_empty_name(fake_cache: dict) -> None:
    """识别物料名为空 → none、aligned.material_name 为空串。"""
    aligned = await align_receipt(_receipt(None))
    assert aligned.match_confidence == "none"
    assert aligned.aligned["material_name"] == ""


# ── 单测：缓存 TTL（注入时钟） ──


async def test_cache_ttl_reuse_and_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTL 内复用不重拉；过期后刷新。"""
    cache: dict[str, tuple[float, list[MaterialMasterEntry]]] = {}
    monkeypatch.setattr(aligner_module, "_master_cache", cache)
    calls = {"n": 0}

    async def fake_fetch() -> list[MaterialMasterEntry]:
        calls["n"] += 1
        return _fake_entries()

    monkeypatch.setattr(aligner_module, "_fetch_master_entries", fake_fetch)
    clock = {"t": 100.0}
    monkeypatch.setattr(aligner_module, "_now", lambda: clock["t"])

    await get_master_entries()
    await get_master_entries()
    assert calls["n"] == 1, "TTL 内第二次调用应复用缓存"

    clock["t"] += MASTER_CACHE_TTL + 1
    await get_master_entries()
    assert calls["n"] == 2, "TTL 过期后应重新拉取"


# ── 单测：align_batch 报表（假缓存 + 临时 truth） ──


async def test_align_batch_report(tmp_path: Path, fake_cache: dict) -> None:
    """批处理报表分级统计与命中率公式（exact+prefix 满命中、fuzzy 半命中）。"""
    lines = [
        {"物料名称": "硫酸铵", "生产商": "OXOID", "供应商": "安徽天地生命科技有限公司"},
        {"物料名称": "纸箱", "生产商": "", "供应商": ""},
        {"物料名称": "乱七八糟不存在的东西q", "生产商": "", "供应商": ""},
    ]
    (tmp_path / "truth.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
        encoding="utf-8",
    )
    report = await align_batch(tmp_path)
    assert report["total"] == 3
    assert report["exact"] == 1
    assert report["prefix"] == 1
    assert report["fuzzy"] == 0
    assert report["none"] == 1
    assert report["hit_rate"] == pytest.approx((1 + 1 + 0.5 * 0) / 3, abs=1e-4)
    assert len(report["misses"]) == 1
    assert report["misses"][0]["confidence"] == "none"


# ── live：真实主数据拉取 ──


async def test_live_master_fetch() -> None:
    """全量分页拉取 material_master 并载入缓存，断言 ≥500 条。"""
    entries = await get_master_entries()
    assert len(entries) >= 500, f"主数据应 ≥500 条，实际 {len(entries)}"
    named = [e for e in entries if e.name.strip()]
    assert len(named) >= 500, f"有名称的主数据应 ≥500 条，实际 {len(named)}"
    with_code = [e for e in entries if e.code.strip()]
    print(
        f"\n[master] 共 {len(entries)} 条，有名称 {len(named)} 条，有代码 {len(with_code)} 条；"
        f"样例: {entries[0].name}/{entries[0].code}"
    )


# ── live：truth.jsonl 对齐评估（命中率 ≥95% 验收线） ──


async def test_live_align_batch_hit_rate() -> None:
    """truth.jsonl 60 条真值物料名批量对齐。

    命中率 =（exact + prefix + 0.5×fuzzy）/ total ≥95%；
    none/fuzzy 明细全部打印（如实报告，不造假）。
    """
    if not TRUTH_PATH.is_file():
        pytest.skip(f"truth.jsonl 不存在: {TRUTH_PATH}（先运行 scripts/build_recognition_dataset.py）")

    report = await align_batch(DATASET_DIR)
    total = report["total"]
    print(
        f"\n[align] total={total} exact={report['exact']} prefix={report['prefix']} "
        f"fuzzy={report['fuzzy']} none={report['none']} hit_rate={report['hit_rate']:.2%}"
    )
    for miss in report["misses"]:
        print(
            f"  [{miss['confidence']}] truth={miss['name']!r} -> "
            f"aligned={miss.get('aligned_name')!r} detail={miss.get('detail')}"
        )

    assert total >= 60, f"真值应 ≥60 条，实际 {total}"
    assert report["hit_rate"] >= 0.95, (
        f"对齐命中率 {report['hit_rate']:.2%} < 95% 验收线："
        f"exact={report['exact']} prefix={report['prefix']} "
        f"fuzzy={report['fuzzy']} none={report['none']}"
    )


# ── live：单条真值端到端（RecognizedReceipt → AlignedReceipt） ──


async def test_live_align_receipt_from_truth() -> None:
    """取 truth.jsonl 第一条构造 RecognizedReceipt 走 align_receipt 全链路。"""
    if not TRUTH_PATH.is_file():
        pytest.skip(f"truth.jsonl 不存在: {TRUTH_PATH}")
    first = json.loads(TRUTH_PATH.read_text(encoding="utf-8").splitlines()[0])
    aligned = await align_receipt(
        _receipt(
            str(first.get("物料名称") or ""),
            manufacturer=str(first.get("生产商") or "") or None,
            supplier=str(first.get("供应商") or "") or None,
        )
    )
    print(
        f"\n[align_receipt] truth={first.get('物料名称')!r} -> "
        f"{aligned.aligned['material_name']!r} ({aligned.match_confidence}, "
        f"code={aligned.aligned['code']})"
    )
    assert aligned.match_confidence in ("exact", "prefix", "fuzzy", "none")
    if aligned.match_confidence != "none":
        assert aligned.aligned["code"]
