"""append_local_district.py — 本地补建平台未建模的分区（静态资产追加）。

背景：罐区（中控「新罐区」136 次/30 天 + 100/200 段罐号作业票所在区域）
平台风险分区未建模（接口 total=64 无该区域）。2026-10-27 用户在图卡圈选
位置后拍板：不等平台，本地直接补建。几何=圈选中心 (119.289507, 25.461507)
外扩约 ±18m×±55m 的矩形（紧邻车间四（甲类）东南侧，与既有轮廓无重叠）。

幂等：distId 已存在则跳过。注意 fetch_risk_districts.py 全量覆盖两份资产，
重跑抓取后需再执行本脚本补回本地分区。

用法（backend 下）：
    .venv/bin/python -m scripts.append_local_district
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.service.facility_map.asset import (  # noqa: E402
    build_frontend_doc,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_PATH = REPO_ROOT / "docs" / "assets" / "tiji-risk-districts-20261026.json"
FRONTEND_PATH = REPO_ROOT / "frontend" / "src" / "data" / "tiji-risk-districts.json"

# 本地补建分区（distId 用 9xxx 段与平台雪花/数字 id 区分；平台未来真建模
# 后以平台 distId 为准，本地行随映射表人工迁移后废弃）
LOCAL_DISTRICTS: list[dict] = [
    {
        "distId": "9001",
        "distName": "罐区",
        "riskLevel": None,
        "riskLevelDesc": "",
        "local_note": (
            "2026-10-27 本地补建（平台未建模）：用户图卡圈选位置，"
            "中心 (119.289507, 25.461507)，覆盖新罐区/100-200 段罐号所在区域"
        ),
        "rails": [
            {
                "name": "罐区",
                "polygon": [
                    [119.289327, 25.461007],
                    [119.289687, 25.461007],
                    [119.289687, 25.462007],
                    [119.289327, 25.462007],
                    [119.289327, 25.461007],
                ],
            }
        ],
    }
]


def _bj_now_iso() -> str:
    now = datetime.now(UTC) + timedelta(hours=8)
    return now.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def main() -> None:
    doc = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    districts: list[dict] = doc.get("districts") or []
    existing = {str(d.get("distId")) for d in districts}
    added: list[str] = []
    for local in LOCAL_DISTRICTS:
        if str(local["distId"]) in existing:
            continue
        districts.append(local)
        added.append(f"{local['distId']}={local['distName']}")
    if not added:
        print("本地分区均已存在，跳过")
        return
    doc["districts"] = districts
    doc["_meta"]["count"] = len(districts)
    doc["_meta"]["local_append"] = (
        f"{_bj_now_iso()} 本地补建 {'、'.join(added)}"
        "（平台未建模，重跑 fetch_risk_districts.py 后需重跑本脚本补回）"
    )
    ASSET_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    FRONTEND_PATH.write_text(
        json.dumps(build_frontend_doc(doc), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"已追加本地分区：{'、'.join(added)}（现共 {len(districts)} 个）")
    print(f"docs 存档: {ASSET_PATH}")
    print(f"前端副本: {FRONTEND_PATH}")


if __name__ == "__main__":
    main()
