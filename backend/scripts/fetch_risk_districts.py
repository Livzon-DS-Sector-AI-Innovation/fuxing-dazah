"""fetch_risk_districts.py — 一次性抓取 3.x 平台风险分区轮廓为静态资产。

用法（backend 下）：
    .venv/bin/python -m scripts.fetch_risk_districts

产出（幂等覆盖写）：
- docs/assets/tiji-risk-districts-20261026.json   权威存档（_meta 坐标系说明头）
- frontend/src/data/tiji-risk-districts.json      前端打包副本（纯几何）

分区属一次性建模、平台无维护迹象——按快照处理，刷新=人工重跑本脚本。
坐标主源 rail.pointDTOS（经纬度，北上渲染），pointsList 米制串仅回退。
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.service.facility_map.asset import (  # noqa: E402
    build_asset_doc,
    build_frontend_doc,
)
from app.modules.safety.workticket_review.client import (  # noqa: E402
    WorkTicketPlatformClient,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_PATH = REPO_ROOT / "docs" / "assets" / "tiji-risk-districts-20261026.json"
FRONTEND_PATH = REPO_ROOT / "frontend" / "src" / "data" / "tiji-risk-districts.json"

# 前端副本体积护栏（超出则提示人工评估抽稀，不自动改几何）
FRONTEND_SIZE_GUARD_BYTES = 2 * 1024 * 1024


def _bj_now_iso() -> str:
    now = datetime.now(UTC) + timedelta(hours=8)
    return now.strftime("%Y-%m-%dT%H:%M:%S+08:00")


async def main() -> None:
    async with WorkTicketPlatformClient() as client:
        records = await client.list_risk_districts()
    if not records:
        raise SystemExit("平台返回 0 个分区，疑似接口异常——不落盘")

    doc = build_asset_doc(records, fetched_at=_bj_now_iso())
    frontend_doc = build_frontend_doc(doc)

    ASSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSET_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    FRONTEND_PATH.write_text(
        json.dumps(frontend_doc, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    districts = doc["districts"]
    rails = sum(len(d["rails"]) for d in districts)
    points = sum(len(r["polygon"]) for d in districts for r in d["rails"])
    fe_bytes = FRONTEND_PATH.stat().st_size
    print(f"分区 {len(districts)} 个 / rail {rails} 条 / 顶点 {points} 点")
    print(f"docs 存档: {ASSET_PATH} ({ASSET_PATH.stat().st_size} bytes)")
    print(f"前端副本: {FRONTEND_PATH} ({fe_bytes} bytes)")
    if fe_bytes > FRONTEND_SIZE_GUARD_BYTES:
        print(
            f"⚠ 前端副本超过 {FRONTEND_SIZE_GUARD_BYTES} bytes 护栏，"
            "请评估共线点抽稀后再提交"
        )


if __name__ == "__main__":
    asyncio.run(main())
