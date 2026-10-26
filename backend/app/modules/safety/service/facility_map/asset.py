"""平台风险分区 payload → 归一化资产纯函数。

输入：WorkTicketPlatformClient.list_risk_districts() 原始记录
（distId/distName/riskLevel/riskLevelDesc/rails[{id,name,pointDTOS,pointsList}]）。
输出：{districts:[{distId,distName,riskLevel,riskLevelDesc,
rails:[{name,polygon:[[x,y],…]}]}]}——asset 主坐标 pointDTOS 经纬度
（6 位小数，~0.1m 精度），pointsList 米制串仅回退。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "build_asset_doc",
    "build_frontend_doc",
    "normalize_districts",
    "rail_polygon",
]

# 有效多边形最少点数
_MIN_POINTS = 3

# 经纬度舍入位数（1e-6 度 ≈ 0.1m，厂区图卡足够）
_LNG_LAT_ROUND = 6


def _point_xy(item: Any) -> tuple[float, float] | None:
    if not isinstance(item, dict):
        return None
    x, y = item.get("x"), item.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return (round(float(x), _LNG_LAT_ROUND), round(float(y), _LNG_LAT_ROUND))


def rail_polygon(rail: dict[str, Any]) -> list[tuple[float, float]] | None:
    """单条 rail → 多边形顶点序列；无法得到 ≥3 个有效点时返回 None。

    主源 pointDTOS（已是解析好的列表）；为空时回退解析 pointsList
    （本地米制平面坐标的嵌套 JSON 字符串，点形同 {x,y,z}）。
    """
    points: list[tuple[float, float]] = []
    dtos = rail.get("pointDTOS")
    if isinstance(dtos, list) and dtos:
        points = [p for p in (_point_xy(item) for item in dtos) if p is not None]
    else:
        raw = rail.get("pointsList")
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
            except ValueError:
                logger.warning("rail pointsList 非合法 JSON，跳过: %s", rail.get("name"))
                parsed = None
            if isinstance(parsed, list):
                points = [p for p in (_point_xy(item) for item in parsed) if p is not None]
    if len(points) < _MIN_POINTS:
        return None
    return points


def normalize_districts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """平台分区记录列表 → 归一化结构（rail 级跳过无效轮廓，分区全保留）。"""
    out: list[dict[str, Any]] = []
    for record in records:
        rails_out: list[dict[str, Any]] = []
        for rail in record.get("rails") or []:
            poly = rail_polygon(rail if isinstance(rail, dict) else {})
            if poly is None:
                logger.warning(
                    "分区 %s(%s) rail「%s」轮廓无效（<%d 点或不可解析），跳过",
                    record.get("distId"), record.get("distName"),
                    rail.get("name") if isinstance(rail, dict) else rail, _MIN_POINTS,
                )
                continue
            rails_out.append(
                {"name": str((rail.get("name") or "") if isinstance(rail, dict) else ""), "polygon": [list(p) for p in poly]}
            )
        out.append(
            {
                "distId": str(record.get("distId") or ""),
                "distName": str(record.get("distName") or ""),
                "riskLevel": record.get("riskLevel"),
                "riskLevelDesc": str(record.get("riskLevelDesc") or ""),
                "rails": rails_out,
            }
        )
    return out


def build_asset_doc(
    records: list[dict[str, Any]], *, fetched_at: str
) -> dict[str, Any]:
    """归一化 + 坐标系说明头（docs/assets/ 权威存档形态）。"""
    districts = normalize_districts(records)
    return {
        "_meta": {
            "source": "GET /api/tiji-risk-prevention/openapi/risk-district/page（blade-auth 平台 token）",
            "fetched_at": fetched_at,
            "count": len(districts),
            "coordinate_system": (
                "rail.pointDTOS 经纬度（x=经度 y=纬度，福清厂区 ~119.28E/25.46N），"
                "前端 SVG 以北上方向渲染（y 轴翻转）"
            ),
            "fallback_note": (
                "rail.pointsList 为本地米制平面坐标嵌套 JSON 字符串"
                "（x≈16-19 万、y≈28 万，原点随平台 jsmap 底图），与 pointDTOS 点数"
                "一一对应，仅作解析回退源，未收录本文件"
            ),
            "risk_level_note": (
                "riskLevel 1=低风险 / 2=一般风险 / 空=未填（2026-10-26 实测 46/4/14）；"
                "平台无颜色字段，图卡着色不依赖本字段"
            ),
            "snapshot": (
                "分区属一次性建模、平台无维护迹象，本文件按快照处理；"
                "刷新=人工重跑 backend/scripts/fetch_risk_districts.py"
            ),
        },
        "districts": districts,
    }


def build_frontend_doc(asset_doc: dict[str, Any]) -> dict[str, Any]:
    """前端打包副本：去掉 _meta 只留几何（districts 原样）。"""
    return {"districts": asset_doc.get("districts") or []}
