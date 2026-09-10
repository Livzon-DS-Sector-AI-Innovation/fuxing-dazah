"""AI + 字典补全缺失字段（危险性/品类）；确实缺失的列出，不捏造。"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, cast

from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.chemical_inventory.chemical_dict import lookup_hazard_category

logger = logging.getLogger(__name__)


async def ai_classify_missing(names: list[str]) -> dict[str, dict[str, Any]]:
    """AI 对未命中字典的物料名做危险性/品类分类（不确定返回空/未知）。"""
    if not names or not os.getenv("SAFETY_AI_TEXT_API_KEY"):
        return {}
    from app.modules.safety.service.config import create_ai_service

    ai = create_ai_service("text")
    prompt = (
        "以下是危化品物料名称。请对每个名称给出危险性类别（从 flammable易燃/explosive易爆/"
        "precursor_drug易制毒/precursor_explosive易制爆/corrosive腐蚀/toxic毒性/oxidizer氧化剂/"
        "irritant刺激性 中选择，可多选）和品类（溶剂/酸/碱/氧化剂/其他/未知）。"
        "只识别你确知的常见危化品；不确定的一律 hazard_classes=[]、category=未知，绝不编造。"
        "只输出 JSON：{\"items\":[{\"name\":\"...\",\"hazard_classes\":[...],\"category\":\"...\"}]}"
    )
    try:
        with ai_audit_scope(scenario="chemical_inventory_enrich", channel="system"):
            raw = await ai.chat(
                messages=[
                    {"role": "system", "content": "你是危化品安全专家，严格按已知安全数据分类，不猜测不编造。"},
                    {"role": "user", "content": prompt + "\n物料名称：" + json.dumps(names, ensure_ascii=False)},
                ],
                temperature=0.0,
            )
        data = _extract_json(raw)
        result: dict[str, dict[str, Any]] = {}
        for item in data.get("items", []):
            if isinstance(item, dict) and item.get("name"):
                result[str(item["name"])] = {
                    "hazard_classes": item.get("hazard_classes") or [],
                    "category": item.get("category") or "未知",
                }
        return result
    except Exception:  # noqa: BLE001
        logger.exception("AI 补全分类失败")
        return {}
    finally:
        await ai.close()


def _extract_json(raw: str) -> dict[str, Any]:
    """从 AI 返回文本中抽取 JSON 对象。"""
    raw = raw.strip()
    tick = chr(96)
    if raw.startswith(tick * 3):
        raw = raw.split(tick * 3, 2)[1].lstrip("json").strip()
    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return cast(dict[str, Any], json.loads(raw[start : end + 1]))
            except json.JSONDecodeError:
                return {}
        return {}


def enrich_hazard_category(
    records: list[Any], ai_result: dict[str, dict[str, Any]] | None = None
) -> tuple[int, list[dict[str, Any]]]:
    """补危险性/品类；返回 (补全条数, 仍缺失清单)。"""
    ai_result = ai_result or {}
    filled = 0
    missing: list[dict[str, Any]] = []
    for r in records:
        name = getattr(r, "material_name", "")
        hazards = getattr(r, "hazard_classes", None) or []
        category = getattr(r, "category", None) or ""
        if not hazards or not category:
            hit = lookup_hazard_category(name)
            if hit:
                d_hazards, d_category = hit
            else:
                ai = ai_result.get(name, {})
                d_hazards = ai.get("hazard_classes") or []
                d_category = ai.get("category") or ""
            if not hazards and d_hazards:
                r.hazard_classes = list(d_hazards)
                filled += 1
            if not category and d_category and d_category != "未知":
                r.category = d_category
                filled += 1
        if not (getattr(r, "hazard_classes", None) or []) or not (getattr(r, "category", None) or ""):
            missing.append({
                "department": r.department,
                "storage_location": r.storage_location,
                "material_name": name,
                "missing_hazard": not (getattr(r, "hazard_classes", None) or []),
                "missing_category": not (getattr(r, "category", None) or ""),
            })
    return filled, missing
