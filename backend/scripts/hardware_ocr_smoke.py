"""五金库送货单 OCR 冒烟脚本：真实照片 → 真链（旋正+识别+四级匹配+草稿）。

用法（在 backend/ 下）：
    ./.venv/bin/python -m scripts.hardware_ocr_smoke /path/to/送货单1.jpg /path/to/送货单2.jpg ...

每张照片走 build_ocr_draft 生产路径（Web 入库台同款）：
- 方向预判 + 结构化识别（scenario=hardware_receipt_recognition，真实 vision 调用）
- 四级匹配（code→名称规格→同义词→人工兜底）
- 生成 draft 草稿（不动账；M9 开关默认关，不会自动入账）
- 落库并 commit（操作人=smoke），供入库台 UI 人工复核

输出：每单耗时/供应商/单号/日期/逐行匹配方式与得分/汇总统计（JSON 打印）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path


async def run_one(session, path: str, index: int) -> dict:
    from app.modules.warehouse.hardware.receipt_pipeline import build_ocr_draft

    raw = Path(path).read_bytes()
    image_b64 = base64.b64encode(raw).decode()

    started = time.monotonic()
    receipt, summary = await build_ocr_draft(
        session,
        image_b64=image_b64,
        content_type="image/jpeg",
        operator=f"smoke-{index}",
        # Web 入库台口径（auto 评估跑但开关默认关 → 恒人工确认）
        auto_accept=True,
    )
    await session.commit()
    elapsed = round(time.monotonic() - started, 1)

    rows = summary.get("rows") or summary.get("match_summary") or []
    return {
        "file": Path(path).name,
        "seconds": elapsed,
        "receipt_no": getattr(receipt, "receipt_no", None),
        "status": getattr(receipt, "status", None),
        "supplier": getattr(receipt, "supplier_name", None),
        "delivery_note_no": getattr(receipt, "delivery_note_no", None),
        "arrived_at": str(getattr(receipt, "arrived_at", None)),
        "mode": getattr(receipt, "mode", None),
        "rows": rows,
        "row_count": len(rows),
    }


async def main(paths: list[str]) -> None:
    from app.core.database import async_session_factory

    results = []
    async with async_session_factory() as session:
        for i, p in enumerate(paths, 1):
            print(f"[{i}/{len(paths)}] {p} …", flush=True)
            try:
                r = await run_one(session, p, i)
            except Exception as exc:  # noqa: BLE001 — 冒烟要收集全部结果
                r = {"file": Path(p).name, "error": f"{type(exc).__name__}: {exc}"}
            results.append(r)
            print(json.dumps(r, ensure_ascii=False, indent=1, default=str), flush=True)

    ok = [r for r in results if "error" not in r]
    total_rows = sum(r.get("row_count", 0) for r in ok)
    print("\n==== 冒烟汇总 ====")
    print(f"成功 {len(ok)}/{len(results)}；总行数 {total_rows}；"
          f"平均单耗 {round(sum(r['seconds'] for r in ok)/len(ok), 1) if ok else '-'}s")
    for r in ok:
        methods: dict[str, int] = {}
        for row in r.get("rows", []):
            m = str(row.get("match") or row.get("method") or "?")
            methods[m] = methods.get(m, 0) + 1
        print(f"  {r['file']}: {r['row_count']}行 {r['seconds']}s 匹配分布={methods}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: python -m scripts.hardware_ocr_smoke <图片路径>…")
    asyncio.run(main(sys.argv[1:]))
