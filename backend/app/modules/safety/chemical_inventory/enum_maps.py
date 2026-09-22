"""危化品库存总表字段映射纯函数（feishu handler 与直读 reader 共用的单一来源）。

从 feishu/chemical_inventory_bitable_handler.py 抽出（Ticket 01，行为逐字保留）：
- 中文字段 → DB 列映射 INVENTORY_BITABLE_TO_MODEL；
- 五组中文标签 ↔ 枚举双向映射（部门/单位/危险性/风险标记/风险说明）；
- Bitable 原始值解析（富文本/select/多选/数字/毫秒日期）。

口径铁律：**未映射标签原样透传**（``_UNIT_LABEL_TO_ENUM.get(v, v)``）——总表「单位」
列存在脏选项（'槽车'/'500g/瓶'/'易制毒'/数字串等），镜像与直读必须逐字一致。
本模块零 IO、零飞书依赖，仅供纯函数测试。
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# 总表 Bitable 中文字段 → DB 列
INVENTORY_BITABLE_TO_MODEL: dict[str, str] = {
    "部门": "department",
    "存放部位": "storage_location",
    "物料名称": "material_name",
    "包装规格": "package_spec",
    "库存数量": "quantity",
    "单位": "unit",
    "现场物料总量(T)": "total_quantity_t",
    "库存上限": "max_limit",
    "上限单位": "max_limit_unit",
    "危险性": "hazard_classes",
    "品类": "category",
    "最后更新时间": "last_updated_at",
    "备注": "remark",
    "风险标记": "risk_flag",
    "风险说明": "risk_note",
}


# ── 中文标签 ↔ 枚举值 双向映射 ──

_DEPT_LABEL_TO_ENUM: dict[str, str] = {
    "仓储部": "warehouse",
    "提炼一部": "extraction_1",
    "提炼二期": "extraction_2",
    "提炼二部": "extraction_2b",
    "发酵一部": "fermentation_1",
    "发酵二部": "fermentation_2",
    "菌种中心": "strain",
    "QC": "qc",
    "环保": "env",
    "精制": "purification",
    "提炼半合成工程中心": "semi_synth",
    "提炼技术精进中心": "tech_refine",
    "其他": "other",
}
_DEPT_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _DEPT_LABEL_TO_ENUM.items()}

_UNIT_LABEL_TO_ENUM: dict[str, str] = {
    "kg": "kg", "g": "g", "T": "T", "L": "L", "ml": "ml", "瓶": "bottle",
}
_UNIT_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _UNIT_LABEL_TO_ENUM.items()}

_HAZARD_LABEL_TO_ENUM: dict[str, str] = {
    "易燃": "flammable",
    "易爆": "explosive",
    "易制毒": "precursor_drug",
    "易制爆": "precursor_explosive",
    "腐蚀": "corrosive",
    "毒性": "toxic",
    "氧化剂": "oxidizer",
    "刺激性": "irritant",
}
_HAZARD_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _HAZARD_LABEL_TO_ENUM.items()}

_RISK_FLAG_LABEL_TO_ENUM: dict[str, str] = {"正常": "normal", "预警": "warn"}
_RISK_FLAG_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _RISK_FLAG_LABEL_TO_ENUM.items()}

# 风险说明：正常 + 预警类型
_ALERT_TYPE_LABEL_TO_ENUM: dict[str, str] = {
    "正常": "normal",
    "超量": "over_limit",
    "临限": "near_limit",
    "高占比": "high_ratio",
    "未分类": "unclassified",
    "单位异常": "unit_anomaly",
    "专库违规": "special_storage",
}
_ALERT_TYPE_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _ALERT_TYPE_LABEL_TO_ENUM.items()}


# ── 值提取 ──


def _text(raw: Any) -> str | None:
    if raw is None:
        return None
    # 飞书文本字段读回为富文本数组 [{"text": "...", "type": "text"}]
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        s = "".join(parts).strip()
        return s or None
    if isinstance(raw, dict):
        return _text(raw.get("text"))
    s = str(raw).strip()
    return s or None


def _num(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except Exception:  # noqa: BLE001
        return None


def _datetime_from_raw(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000, tz=UTC)
        except (OSError, ValueError):
            return None
    return None


def _multi_select(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = []
        for item in raw:
            if isinstance(item, dict):
                if item.get("text"):
                    values.append(str(item["text"]))
            else:
                values.append(str(item))
    elif isinstance(raw, dict):
        values = [str(raw.get("text", ""))]
    else:
        return None
    values = [v.strip() for v in values if str(v).strip()]
    return values or None


def _map_inventory_fields(values: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for bitable_field, model_col in INVENTORY_BITABLE_TO_MODEL.items():
        raw = values.get(bitable_field)
        if model_col == "last_updated_at":
            mapped[model_col] = _datetime_from_raw(raw)
        elif model_col in ("quantity", "total_quantity_t", "max_limit"):
            mapped[model_col] = _num(raw)
        elif model_col == "hazard_classes":
            labels = _multi_select(raw)
            if labels:
                mapped[model_col] = [_HAZARD_LABEL_TO_ENUM.get(v, v) for v in labels]
        elif model_col == "risk_note":
            labels = _multi_select(raw)
            if labels:
                mapped[model_col] = [_ALERT_TYPE_LABEL_TO_ENUM.get(v, v) for v in labels]
        elif model_col == "department":
            value = _text(raw)
            if value:
                mapped[model_col] = _DEPT_LABEL_TO_ENUM.get(value, value)
        elif model_col in ("unit", "max_limit_unit"):
            value = _text(raw)
            if value:
                mapped[model_col] = _UNIT_LABEL_TO_ENUM.get(value, value)
        elif model_col == "risk_flag":
            value = _text(raw)
            if value:
                mapped[model_col] = _RISK_FLAG_LABEL_TO_ENUM.get(value, value)
        else:
            mapped[model_col] = _text(raw)
    return {k: v for k, v in mapped.items() if v is not None}
