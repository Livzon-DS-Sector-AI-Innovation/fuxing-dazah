"""S2 ticket 01 验收：送货单 Vision 识别器（单测 + 真数据集 live 识别）。

单测：``parse_receipt_payload``/``build_receipt`` 的 JSON 解析容错
（markdown 代码块包裹/首尾杂文字/字段缺省/confidence 缺省），纯函数零网络。

live 识别（依赖 `scripts/build_recognition_dataset.py` 先产出数据集：
仓库根 `.scratch/s2-recognition/dataset/`）：
- test_recognize_real_image：取数据集前 3 张图逐张真 LLM 识别，断言
  RecognizedReceipt 结构、material_name.value 非空、confidence∈[0,1]、
  quantity.value 可转 float；
- test_dataset_truth_sample：抽 truth.jsonl 5 行断言结构（准确率评估在
  ticket 05，不入 pytest），并打印 1 条识别 vs 真值对比供人工比对。

数据集缺失时 live 用例 pytest.skip（单测不依赖数据集）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_recognizer.py -v
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.warehouse.agent.pipeline.recognizer import (
    REQUIRED_FIELDS,
    RecognizedReceipt,
    build_receipt,
    parse_receipt_payload,
    recognize_receipt,
    required_all_missing,
)

# 仓库根 = tests/modules/warehouse/test_x.py 往上 4 级
REPO_ROOT = Path(__file__).resolve().parents[4]
DATASET_DIR = REPO_ROOT / ".scratch" / "s2-recognition" / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
TRUTH_PATH = DATASET_DIR / "truth.jsonl"

# truth.jsonl 必备键（ticket 01 真值字段清单，空值可为 null）
TRUTH_REQUIRED_KEYS = {
    "record_id",
    "物料名称",
    "物料批号",
    "入库数量",
    "单位",
    "供应商",
    "生产商",
}


# ── 单测：JSON 解析容错（纯函数，零网络） ──


def test_parse_plain_json() -> None:
    """合法 JSON 直接解析。"""
    payload = parse_receipt_payload('{"material_name": {"value": "硫酸", "confidence": 0.9}}')
    assert payload["material_name"]["value"] == "硫酸"


def test_parse_codeblock_wrapped() -> None:
    """markdown 代码块包裹（```json ... ```）可解析。"""
    text = (
        "识别结果如下：\n```json\n"
        '{"material_name": {"value": "氢氧化钠", "confidence": 0.85}}\n'
        "```\n以上。"
    )
    payload = parse_receipt_payload(text)
    assert payload["material_name"]["value"] == "氢氧化钠"
    assert payload["material_name"]["confidence"] == pytest.approx(0.85)


def test_parse_noisy_prefix_suffix() -> None:
    """无代码块但有首尾杂文字：截取首 { 到末 } 之间子串。"""
    text = '好的，以下是识别结果：{"unit": {"value": "Kg", "confidence": 0.7}} 请核对'
    payload = parse_receipt_payload(text)
    assert payload["unit"]["value"] == "Kg"


def test_parse_invalid_raises() -> None:
    """完全不是 JSON → ValueError（recognize_receipt 据此触发重试）。"""
    with pytest.raises(ValueError):
        parse_receipt_payload("这张图片无法识别，抱歉")


def _sample_payload() -> dict[str, Any]:
    """覆盖必提+选提字段的最小合法识别 JSON。"""
    return {
        "material_name": {"value": "硫酸", "confidence": 0.95},
        "vendor_batch_no": {"value": "H26050902", "confidence": 0.9},
        "quantity": {"value": 1200, "confidence": 0.88},
        "unit": {"value": "Kg", "confidence": 0.92},
        "supplier": {"value": "杭州昇昇医药科技有限公司", "confidence": 0.6},
        "manufacturer": {"value": None, "confidence": 0.3},
        "plate_no": {"value": "闽A12345", "confidence": 0.75},
        "contract_no": {"value": "CG-2026-001", "confidence": 0.5},
        "package_spec": {"value": "25Kg/包", "confidence": 0.8},
        "produced_at": {"value": "2026-08-01", "confidence": 0.7},
        "remark": {"value": "急件", "confidence": 0.4},
    }


def test_build_receipt_full_fields() -> None:
    """完整 payload → RecognizedReceipt，raw 保留原始 dict。"""
    receipt = build_receipt(_sample_payload())
    assert isinstance(receipt, RecognizedReceipt)
    assert receipt.material_name.value == "硫酸"
    assert receipt.quantity.value == 1200
    assert receipt.manufacturer.value is None
    assert receipt.package_spec is not None and receipt.package_spec.value == "25Kg/包"
    # arrival_period/contact 未出现在 payload → 选提字段为 None
    assert receipt.arrival_period is None
    assert receipt.contact is None
    assert receipt.raw == _sample_payload()


def test_build_receipt_missing_fields_default() -> None:
    """必提字段缺省 → value=None、confidence=0.0（选提为 None）。"""
    receipt = build_receipt({})
    for name in REQUIRED_FIELDS:
        field = getattr(receipt, name)
        assert field.value is None, f"{name} 缺省应 value=None"
        assert field.confidence == 0.0, f"{name} 缺省应 confidence=0"
    assert receipt.package_spec is None
    assert receipt.raw == {}


def test_build_receipt_confidence_missing_or_bare_value() -> None:
    """confidence 缺省 → 0；裸字符串/数字字段值（无 dict 包裹）→ value 直取、confidence 0。"""
    receipt = build_receipt(
        {
            "material_name": {"value": "磷酸"},  # 无 confidence
            "unit": "Kg",  # 裸字符串
            "quantity": 25,  # 裸数字
        }
    )
    assert receipt.material_name.value == "磷酸"
    assert receipt.material_name.confidence == 0.0
    assert receipt.unit.value == "Kg"
    assert receipt.unit.confidence == 0.0
    assert receipt.quantity.value == 25
    assert receipt.quantity.confidence == 0.0


def test_build_receipt_confidence_clamped() -> None:
    """confidence 越界（>1 / 非法）夹到 [0, 1]。"""
    receipt = build_receipt(
        {
            "material_name": {"value": "x", "confidence": 1.7},
            "unit": {"value": "x", "confidence": "bad"},
        }
    )
    assert receipt.material_name.confidence == 1.0
    assert receipt.unit.confidence == 0.0


def test_required_all_missing_detection() -> None:
    """必提全空检测：模型误置空（选提有值）可识别，触发 recognize 重试。"""
    all_null = {name: {"value": None, "confidence": 0} for name in REQUIRED_FIELDS}
    # 必提全空但选提有值 —— 实测模型误判形态
    assert required_all_missing({**all_null, "package_spec": {"value": "50KG/包"}})
    assert not required_all_missing(_sample_payload())
    # 字段整体缺省同样算全空
    assert required_all_missing({})


# ── live 识别（依赖数据集，缺失则 skip） ──


def _load_images(limit: int) -> list[Path]:
    if not IMAGES_DIR.is_dir():
        pytest.skip(f"数据集图片目录不存在: {IMAGES_DIR}（先运行 scripts/build_recognition_dataset.py）")
    images = sorted(IMAGES_DIR.glob("*.jpg"))[:limit]
    if not images:
        pytest.skip("数据集无图片（先运行 scripts/build_recognition_dataset.py）")
    return images


async def test_recognize_real_image() -> None:
    """数据集前 3 张图真 LLM 识别：结构合法 + 必提断言。"""
    images = _load_images(3)
    for image_path in images:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode()
        receipt = await recognize_receipt(image_b64)

        assert isinstance(receipt, RecognizedReceipt), f"{image_path.name} 应返回 RecognizedReceipt"
        name_value = receipt.material_name.value
        assert name_value is not None and str(name_value).strip(), (
            f"{image_path.name} material_name.value 应非空，实际 {receipt.raw}"
        )
        # 必提 8 字段 confidence 全部在 [0, 1]
        for field_name in REQUIRED_FIELDS:
            confidence = getattr(receipt, field_name).confidence
            assert 0.0 <= confidence <= 1.0, (
                f"{image_path.name} {field_name}.confidence 越界: {confidence}"
            )
        # quantity.value 可转 float（容忍千分位逗号）
        quantity_value = receipt.quantity.value
        assert quantity_value is not None, f"{image_path.name} quantity.value 不应为 None"
        float(str(quantity_value).replace(",", ""))

        print(
            f"\n[recognize] {image_path.name}: 物料={name_value} "
            f"数量={quantity_value} 单位={receipt.unit.value} "
            f"批号={receipt.vendor_batch_no.value} "
            f"车牌={receipt.plate_no.value} "
            f"conf(物料)={receipt.material_name.confidence:.2f}"
        )


def test_dataset_truth_sample() -> None:
    """truth.jsonl 抽 5 行断言结构（准确率评估在 ticket 05，不入 pytest）。"""
    if not TRUTH_PATH.is_file():
        pytest.skip(f"truth.jsonl 不存在: {TRUTH_PATH}（先运行 scripts/build_recognition_dataset.py）")
    lines = [line for line in TRUTH_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 5, f"truth.jsonl 应 ≥5 行，实际 {len(lines)}"

    step = max(1, len(lines) // 5)
    sample = lines[::step][:5]
    assert len(sample) == 5

    for line in sample:
        row = json.loads(line)
        missing = TRUTH_REQUIRED_KEYS - set(row)
        assert not missing, f"truth 行缺键: {missing}，行: {row.get('record_id')}"

    # 第 1 条真值对应图片存在，且识别结果与真值并排打印（人工可比）
    first = json.loads(sample[0])
    record_id = str(first["record_id"])
    image_path = IMAGES_DIR / f"{record_id}.jpg"
    assert image_path.is_file(), f"真值 {record_id} 对应图片应存在: {image_path}"

    import asyncio

    image_b64 = base64.b64encode(image_path.read_bytes()).decode()
    receipt = asyncio.run(recognize_receipt(image_b64))

    print("\n[truth-vs-recognized] record_id=", record_id)
    for field_name, truth_key in (
        ("material_name", "物料名称"),
        ("vendor_batch_no", "厂家批号"),
        ("quantity", "入库数量"),
        ("unit", "单位"),
        ("supplier", "供应商"),
        ("manufacturer", "生产商"),
    ):
        recognized = getattr(receipt, field_name)
        print(
            f"  {truth_key}: truth={first.get(truth_key)!r} "
            f"recognized={recognized.value!r} (conf={recognized.confidence:.2f})"
        )
