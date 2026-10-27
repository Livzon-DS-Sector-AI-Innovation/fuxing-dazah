"""当日作业票/报警/关键风险作业/超储物料 → 分区 pins 聚合（纯函数）。

输入为已归一的浅 dict（服务层适配器负责从各源 reader 拉取并转形）：
- job:        {ticket_type, ticket_no, work_site, work_content}
- fire:       {alarm_time, alarm_type, location, building}   位置=部位优先楼栋兜底
- central:    {alarm_date, alarm_description, workshop, line} 位置=车间+产线
- key_risk:   {report_no, apply_status, area, operation_content, start_time}
              位置=区域（area）
- over_limit: {material_name, department, storage_location, total_quantity_t,
              max_limit, unit}                                  位置=存储位置
输出 pins 聚合 + 未映射清单，契约见 .scratch/f2-facility-map/spec.md。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.modules.safety.service.facility_map.mapping import (
    match_location,
    normalize_location_text,
)

__all__ = [
    "EMPTY_SITE_PLACEHOLDER",
    "REFS_CAP",
    "aggregate_pins",
    "central_location_text",
    "job_bucket",
]

# 作业票未填作业地点时的未映射占位文本（与报警侧共用）
EMPTY_SITE_PLACEHOLDER = "（未填写作业地点）"

# 单分区 refs 明细上限（超出截断并置 truncated）
REFS_CAP = 50

# 作业票类型 → 图卡徽标桶（其余 6 类全部 other）
_JOB_BUCKETS: dict[str, str] = {"hot_work": "hot", "confined_space": "confined"}


def job_bucket(ticket_type: str | None) -> str:
    return _JOB_BUCKETS.get(ticket_type or "", "other")


def central_location_text(workshop: str | None, line: str | None) -> str:
    """中控位置文本 = 车间 + 产线（车间一+达托 恰合分区名「车间一达托」）。"""
    return f"{workshop or ''}{line or ''}".strip()


def _fire_location(fire: dict[str, Any]) -> str:
    """消防位置文本 = 报警部位优先，空则报警楼栋兜底。"""
    return (fire.get("location") or fire.get("building") or "").strip()


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def aggregate_pins(
    *,
    jobs: list[dict[str, Any]],
    fires: list[dict[str, Any]],
    centrals: list[dict[str, Any]],
    index: Any,
    key_risks: list[dict[str, Any]] | None = None,
    over_limits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """五路数据 × 匹配索引 → {pins, unmapped}。

    - 命中 → 分区聚合：jobs 按 hot/confined/other 计数，key_risks/over_limits
      单计，alarms 按 fire/central 计数，refs 保明细（job/fire/central/
      key_risk/over_limit 五形）；计数全保留，refs 截 REFS_CAP。
    - 未命中/空文本 → unmapped 按归一化文本去重，累计 count 与 kinds。
    """
    pins: dict[str, dict[str, Any]] = {}
    unmapped: dict[str, dict[str, Any]] = {}

    def _pin(dist_id: str) -> dict[str, Any]:
        if dist_id not in pins:
            pins[dist_id] = {
                "dist_id": dist_id,
                "jobs": {"hot": 0, "confined": 0, "other": 0},
                "alarms": {"fire": 0, "central": 0},
                "key_risks": 0,
                "over_limits": 0,
                "refs": [],
                "truncated": False,
            }
        return pins[dist_id]

    def _unmapped(text: str, kind: str) -> None:
        key = normalize_location_text(text) or EMPTY_SITE_PLACEHOLDER
        entry = unmapped.setdefault(
            key,
            {"text": text if str(text or "").strip() else EMPTY_SITE_PLACEHOLDER,
             "count": 0, "kinds": []},
        )
        entry["count"] += 1
        if kind not in entry["kinds"]:
            entry["kinds"].append(kind)

    def _add_ref(pin: dict[str, Any], ref: dict[str, Any]) -> None:
        if not pin["truncated"]:
            if len(pin["refs"]) >= REFS_CAP:
                pin["truncated"] = True
            else:
                pin["refs"].append(ref)

    for job in jobs:
        site = (job.get("work_site") or "").strip()
        ref = {
            "kind": "job",
            "ticket_type": _as_str(job.get("ticket_type")) or "",
            "ticket_no": _as_str(job.get("ticket_no")) or "",
            "work_site": site or None,
            "work_content": _as_str(job.get("work_content")),
        }
        dist_id = match_location(site, index) if site else None
        if dist_id is None:
            _unmapped(site, "job")
            continue
        pin = _pin(dist_id)
        pin["jobs"][job_bucket(job.get("ticket_type"))] += 1
        _add_ref(pin, ref)

    for fire in fires:
        text = _fire_location(fire)
        # 部位优先、未命中回退楼栋（实测部位多为设备点位，楼栋才带区域词）
        dist_id = match_location(fire.get("location"), index)
        if dist_id is None:
            dist_id = match_location(fire.get("building"), index)
        ref = {
            "kind": "fire",
            "alarm_time": _as_str(fire.get("alarm_time")),
            "alarm_type": _as_str(fire.get("alarm_type")),
            "location": (fire.get("location") or fire.get("building") or None),
        }
        if dist_id is None:
            _unmapped(text, "fire")
            continue
        pin = _pin(dist_id)
        pin["alarms"]["fire"] += 1
        _add_ref(pin, ref)

    for central in centrals:
        text = central_location_text(central.get("workshop"), central.get("line"))
        ref = {
            "kind": "central",
            "alarm_date": _as_str(central.get("alarm_date")),
            "alarm_description": _as_str(central.get("alarm_description")),
            "workshop": _as_str(central.get("workshop")),
        }
        dist_id = match_location(text, index) if text else None
        if dist_id is None:
            _unmapped(text, "central")
            continue
        pin = _pin(dist_id)
        pin["alarms"]["central"] += 1
        _add_ref(pin, ref)

    for kr in key_risks or []:
        area = (kr.get("area") or "").strip()
        ref = {
            "kind": "key_risk",
            "report_no": _as_str(kr.get("report_no")) or "",
            "apply_status": _as_str(kr.get("apply_status")),
            "area": area or None,
            "operation_content": _as_str(kr.get("operation_content")),
            "start_time": _as_str(kr.get("start_time")),
        }
        dist_id = match_location(area, index) if area else None
        if dist_id is None:
            _unmapped(area, "key_risk")
            continue
        pin = _pin(dist_id)
        pin["key_risks"] += 1
        _add_ref(pin, ref)

    for ol in over_limits or []:
        site = (ol.get("storage_location") or "").strip()
        ref = {
            "kind": "over_limit",
            "material_name": _as_str(ol.get("material_name")),
            "department": _as_str(ol.get("department")),
            "storage_location": site or None,
            "total_quantity_t": ol.get("total_quantity_t"),
            "max_limit": ol.get("max_limit"),
            "unit": _as_str(ol.get("unit")),
        }
        dist_id = match_location(site, index) if site else None
        if dist_id is None:
            _unmapped(site, "over_limit")
            continue
        pin = _pin(dist_id)
        pin["over_limits"] += 1
        _add_ref(pin, ref)

    pin_list = sorted(
        pins.values(),
        key=lambda p: (
            -(
                sum(p["jobs"].values())
                + sum(p["alarms"].values())
                + p["key_risks"]
                + p["over_limits"]
            ),
            p["dist_id"],
        ),
    )
    unmapped_list = sorted(
        unmapped.values(), key=lambda u: (-u["count"], u["text"])
    )
    return {"pins": pin_list, "unmapped": unmapped_list}
