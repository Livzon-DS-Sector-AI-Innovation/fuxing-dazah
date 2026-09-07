"""构建送货单识别测试集（S2 ticket 01，spec Implementation Decisions 1）。

从测试版物料入库总账（material_receipt）筛「外包装/厂家报告单/送货单照片」
附件非空的记录，按物料大类（原辅料/危化品/包材）分层抽样，逐条下载第一个
附件到仓库根 ``.scratch/s2-recognition/dataset/images/{record_id}.jpg``，
真值导出 ``truth.jsonl``（每行一份记录字段子集，空则 null）。

- 图片不入库：脚本在 dataset 目录落一个 ``.gitignore``（内容 ``*``）；
  backend/.gitignore 另有 ``.dataset/`` 条目（本仓库约定位置）。
- 幂等：已存在的图片跳过下载（附件 token 可能失效，重跑只补缺）。
- 下载失败重试 1 次，仍失败跳过并记录（60 条抽样合格线 ≥55 张）。

用法（backend 目录下）::

    uv run python scripts/build_recognition_dataset.py            # 默认 60 条
    uv run python scripts/build_recognition_dataset.py --limit 20
    uv run python scripts/build_recognition_dataset.py --out-dir <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")

from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter  # noqa: E402
from app.modules.warehouse.bitable_schema import WarehouseBitableError  # noqa: E402
from app.modules.warehouse.feishu.media import download_attachment  # noqa: E402

# 真值字段（记录字段名 → truth 键，键即中文字段名便于人工比对）
TRUTH_FIELD_NAMES = (
    "物料名称",
    "物料批号",
    "厂家批号",
    "入库数量",
    "单位",
    "供应商",
    "生产商",
    "车牌",
    "合同编号或订单号",
)
CATEGORY_FIELD = "物料大类"
ATTACHMENT_FIELD = "外包装/厂家报告单/送货单照片"
QUERY_FIELDS = [ATTACHMENT_FIELD, CATEGORY_FIELD, *TRUTH_FIELD_NAMES]

# 分层抽样的三大类（spec：原辅料/危化品/包材 各占约 1/3）
STRATA = ("原辅料", "危化品", "包材")

DEFAULT_OUT_DIR = (
    Path(__file__).resolve().parents[2] / ".scratch" / "s2-recognition" / "dataset"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建送货单识别测试集")
    parser.add_argument("--limit", type=int, default=60, help="抽样总条数（默认 60）")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"输出目录（默认 {DEFAULT_OUT_DIR}）",
    )
    return parser.parse_args()


def first_text(value: Any) -> str | None:
    """单选/文本字段读回值归一为文本；空转 None。

    读写不对称：单选读回是数组（取首元素）；部分文本字段读回是
    ``{"text": ..., "type": "text"}`` 段结构（取 text）；数字整值去 .0。
    """
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("text") or value.get("value") or value.get("name")
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


# 常见图片 magic 头（Base 附件以手机拍照为主：JPEG/HEIC，偶尔 PNG/WEBP）
_IMAGE_MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"BM", b"RIFF")


def sniff_image_kind(content: bytes) -> str:
    """嗅探下载内容的图片格式：jpeg/png/gif/bmp/webp 可用；heic/其他不可用。"""
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    if content.startswith(_IMAGE_MAGICS):
        return "image"
    if content[4:8] == b"ftyp":  # ISO BMFF 容器：HEIC/HEIF/AVIF 等
        return "heic"
    return "unknown"


def first_file_token(value: Any) -> str | None:
    """附件字段读回 [{file_token, name}] 数组，取第一个附件的 file_token。"""
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict) and item.get("file_token"):
            return str(item["file_token"])
    return None


def has_attachment(fields: dict[str, Any]) -> bool:
    return first_file_token(fields.get(ATTACHMENT_FIELD)) is not None


async def fetch_records_with_attachment(
    adapter: WarehouseBitableAdapter,
) -> list[dict[str, Any]]:
    """分页拉 material_receipt 全量（只取所需字段），本地过滤附件非空。

    附件列的 isNotEmpty 结构化 filter 不保证支持（V1.0 实测 datetime 过滤
    亦 1254018），直接拉全量本地过滤最稳。
    """
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        page = await adapter.search_records_page(
            "material_receipt",
            field_names=QUERY_FIELDS,
            limit=500,
            page_token=page_token,
        )
        records.extend(page["records"])
        page_token = page["page_token"]
        if not page_token:
            break
    return [r for r in records if has_attachment(r["fields"])]


def stratified_sample(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """按物料大类分层抽样：各层配额 limit//3，缺额先补未满大类再兜底。

    按 record_id 排序后顺序取（确定性，重跑可复现同一批样本）。
    """
    by_category: dict[str, list[dict[str, Any]]] = {cat: [] for cat in STRATA}
    others: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda r: r["record_id"]):
        category = first_text(record["fields"].get(CATEGORY_FIELD))
        if category in by_category:
            by_category[category].append(record)
        else:
            others.append(record)

    per_stratum = max(1, limit // len(STRATA))
    quota = {cat: min(per_stratum, len(by_category[cat])) for cat in STRATA}
    remaining = limit - sum(quota.values())
    if remaining > 0:
        # 缺额按序补到未满的大类（spec：不足大类取满）
        for cat in STRATA:
            take = min(len(by_category[cat]) - quota[cat], remaining)
            quota[cat] += take
            remaining -= take
            if remaining <= 0:
                break
    sampled: list[dict[str, Any]] = []
    for cat in STRATA:
        sampled.extend(by_category[cat][: quota[cat]])
    if remaining > 0:
        # 三大类仍不足 limit，用其他大类/未分类记录兜底
        sampled.extend(others[:remaining])
    return sampled


def truth_row(record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """从记录字段抽真值行（record_id + 大类 + 真值字段，空则 null）。"""
    row: dict[str, Any] = {"record_id": record_id}
    row[CATEGORY_FIELD] = first_text(fields.get(CATEGORY_FIELD))
    for name in TRUTH_FIELD_NAMES:
        row[name] = first_text(fields.get(name))
    return row


async def main() -> int:
    args = parse_args()
    out_dir: Path = args.out_dir
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    # 图片不入库（spec）：dataset 目录整体 git 忽略
    gitignore = out_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")

    adapter = WarehouseBitableAdapter()
    print("拉取 material_receipt 附件非空记录...")
    records = await fetch_records_with_attachment(adapter)
    print(f"附件非空记录共 {len(records)} 条")
    if not records:
        print("没有可抽样的记录")
        return 1

    sampled = stratified_sample(records, args.limit)
    counter = Counter(
        first_text(r["fields"].get(CATEGORY_FIELD)) or "未分类" for r in sampled
    )
    print(f"抽样 {len(sampled)} 条，各大类: {dict(counter)}")

    truth_rows: list[dict[str, Any]] = []
    failed: list[str] = []
    non_image: list[str] = []
    downloaded = skipped = 0
    for index, record in enumerate(sampled, start=1):
        record_id = record["record_id"]
        fields = record["fields"]
        # 真值与图片下载独立：真值行恒写，票05 评估按有图记录过滤
        truth_rows.append(truth_row(record_id, fields))
        file_token = first_file_token(fields.get(ATTACHMENT_FIELD))
        if file_token is None:  # 理论不可达（fetch 阶段已过滤）
            failed.append(record_id)
            continue
        image_path = images_dir / f"{record_id}.jpg"
        if image_path.exists() and image_path.stat().st_size > 0:
            skipped += 1
            continue
        try:
            content = await download_attachment(file_token)
            kind = sniff_image_kind(content)
            if kind not in ("image", "webp"):
                non_image.append(record_id)
                print(f"[{index}/{len(sampled)}] 非图片格式({kind})跳过 {record_id}")
                continue
            image_path.write_bytes(content)
            downloaded += 1
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻塞整体
            failed.append(record_id)
            print(f"[{index}/{len(sampled)}] 下载失败 {record_id}: {exc}")
            continue
        if index % 10 == 0 or index == len(sampled):
            print(f"[{index}/{len(sampled)}] 已处理（成功 {downloaded}，跳过 {skipped}）")

    truth_path = out_dir / "truth.jsonl"
    truth_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in truth_rows),
        encoding="utf-8",
    )

    print("\n===== 数据集构建完成 =====")
    print(f"输出目录: {out_dir}")
    print(f"抽样: {len(sampled)} 条，各大类: {dict(counter)}")
    print(
        f"图片: 新下载 {downloaded}，已有跳过 {skipped}，"
        f"下载失败 {len(failed)}，非图片格式 {len(non_image)}"
    )
    print(f"truth.jsonl: {len(truth_rows)} 行 -> {truth_path}")
    if failed:
        print(f"下载失败记录: {failed}")
    if non_image:
        print(f"非图片格式记录（无图片文件，真值保留）: {non_image}")
    if failed or non_image:
        print("注意：图片不足抽样数时重跑本脚本补缺（幂等，只补缺；HEIC 等格式无法转码将重复跳过）")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except WarehouseBitableError as exc:
        print(f"Base 读取失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
