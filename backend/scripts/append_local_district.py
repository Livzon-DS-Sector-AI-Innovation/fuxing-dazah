"""append_local_district.py — 本地补建/微调平台未覆盖的分区几何（静态资产维护）。

背景：罐区（中控「新罐区」136 次/30 天 + 100/200 段罐号作业票所在区域）
平台风险分区未建模（接口 total=64 无该区域）。2026-10-27 用户在图卡圈选
位置后拍板：不等平台，本地直接补建。

2026-10-27 二次修订（用户看图微调）：
- 罐区北界南缩至 25.461907——与危化品库拉开约 17 米（原 ~6 米太贴），
  且不扩大画布 bbox；
- 危化品库(37)整体上移 +0.000048——底边与成品包材库(43)南界平齐。

幂等：本地分区（distId 9xxx）存在则用本文件定义覆盖几何（定义可迭代）；
GEOMETRY_ADJUSTMENTS 对平台分区做平移覆盖（fetch 重跑后被平台原样覆盖，
重跑本脚本即恢复微调）。

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

# 本地补建分区（distId 9xxx 段与平台 id 区分；平台未来真建模后以平台
# distId 为准，本地行随映射表人工迁移后废弃）
LOCAL_DISTRICTS: list[dict] = [
    {
        "distId": "9001",
        "distName": "罐区",
        "riskLevel": None,
        "riskLevelDesc": "",
        "local_note": (
            "2026-10-27 本地补建（平台未建模）：用户图卡圈选位置，"
            "中心 (119.289507, 25.461457)；北界 25.461907 与危化品库保持约 17m 间距"
        ),
        "rails": [
            {
                "name": "罐区",
                "polygon": [
                    [119.289327, 25.461007],
                    [119.289687, 25.461007],
                    [119.289687, 25.461907],
                    [119.289327, 25.461907],
                    [119.289327, 25.461007],
                ],
            }
        ],
    }
]

# 平台分区几何微调（fetch 重跑后需重跑本脚本恢复）：
# shift_lat/shift_lng 为整体平移量（度）
GEOMETRY_ADJUSTMENTS: dict[str, dict[str, float]] = {
    # 危化品库上移：底边 25.462014+0.000048=25.462062 与成品包材库南界平齐
    "37": {"shift_lat": 0.000048},
}


def _bj_now_iso() -> str:
    now = datetime.now(UTC) + timedelta(hours=8)
    return now.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _shift_polygon(rail: dict, dlat: float, dlng: float) -> None:
    rail["polygon"] = [[lng + dlng, lat + dlat] for lng, lat in rail["polygon"]]


def main() -> None:
    doc = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    districts: list[dict] = doc.get("districts") or []
    by_id = {str(d.get("distId")): d for d in districts}

    # ① 本地分区：新增或以本文件定义覆盖（几何定义可迭代）
    changed: list[str] = []
    for local in LOCAL_DISTRICTS:
        key = str(local["distId"])
        if key in by_id:
            if by_id[key].get("rails") != local["rails"]:
                by_id[key]["rails"] = local["rails"]
                by_id[key]["local_note"] = local.get("local_note")
                changed.append(f"更新几何 {key}={local['distName']}")
        else:
            districts.append(local)
            by_id[key] = local
            changed.append(f"新增 {key}={local['distName']}")

    # ② 平台分区平移微调（local_adjust 标记防重：平移是增量操作，重复
    # 执行会叠加——已有标记且平移量相同则跳过；fetch 重跑覆盖后标记消失
    # 需重跑本脚本恢复）
    for dist_id, adj in GEOMETRY_ADJUSTMENTS.items():
        d = by_id.get(str(dist_id))
        if d is None:
            continue
        dlat = adj.get("shift_lat", 0.0)
        dlng = adj.get("shift_lng", 0.0)
        if dlat == 0 and dlng == 0:
            continue
        marker = f"dlat={dlat:+f}/dlng={dlng:+f}"
        if marker in str(d.get("local_adjust") or ""):
            continue  # 同一平移已应用
        for rail in d.get("rails") or []:
            _shift_polygon(rail, dlat, dlng)
        d["local_adjust"] = (
            f"{_bj_now_iso()} 本地平移 {marker}"
            "（fetch 重跑后需重跑本脚本恢复）"
        )
        changed.append(f"平移 {dist_id}={d.get('distName')}")

    if not changed:
        print("无变更（本地分区与微调均已应用）")
        return

    doc["districts"] = districts
    doc["_meta"]["count"] = len(districts)
    doc["_meta"]["local_append"] = (
        f"{_bj_now_iso()} 本地维护：{'；'.join(changed)}"
    )
    ASSET_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    FRONTEND_PATH.write_text(
        json.dumps(build_frontend_doc(doc), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"已应用：{'；'.join(changed)}（现共 {len(districts)} 个分区）")
    print(f"docs 存档: {ASSET_PATH}")
    print(f"前端副本: {FRONTEND_PATH}")


if __name__ == "__main__":
    main()
