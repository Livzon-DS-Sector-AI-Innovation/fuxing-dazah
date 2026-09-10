"""危化品库存风险规则引擎（确定性、库存变化触发 / 手动全量）。

对齐 docs/chemical-inventory-design.md §7 与 backend-design.md §3。

设计原则：
- 纯规则、无 IO，不查库。
- records 用 duck typing（访问 .department/.total_quantity_t 等属性），不依赖 ORM 模型，
  便于单测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# 单位 → 吨 换算系数（密度未知按 1.0 kg/L 处理）
_UNIT_TO_TONNES: dict[str, Decimal] = {
    "T": Decimal("1"),
    "kg": Decimal("0.001"),
    "g": Decimal("0.000001"),
    "L": Decimal("0.001"),       # 1 L × 1.0 kg/L ÷ 1000
    "ml": Decimal("0.000001"),   # 1 ml × 1.0 g/ml ÷ 1e6
}

# 瓶包装规格解析：160Kg/桶 / 500g/瓶 / 25L/桶
_BOTTLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|t|l|ml)", re.IGNORECASE)

# 易制毒/易制爆专用库存放部位关键词（含 危化品储柜/危化品库/试剂间 等）
_SPECIAL_STORAGE_KEYWORDS = ("危库", "试剂柜", "试剂间", "危化品", "储柜")

# 危险性多选值 → 专库规则键（corrosive 简化统一为 corrosive_acid）
_HAZARD_TO_MATRIX: dict[str, str] = {
    "flammable": "flammable",
    "explosive": "explosive",
    "precursor_drug": "precursor_drug",
    "precursor_explosive": "precursor_explosive",
    "corrosive": "corrosive_acid",
    "toxic": "toxic",
    "oxidizer": "oxidizer",
    "irritant": "irritant",
}


@dataclass
class RuleAlert:
    """规则命中结果。"""

    alert_type: str
    severity: str
    description: str
    suggestion: str | None = None
    record_ids: list[Any] = field(default_factory=list)  # 涉及记录 id（uuid 或 str）


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _normalize_to_tonnes(
    quantity: Any, unit: str | None, package_spec: str | None = None
) -> Decimal | None:
    """把 库存数量+单位 换算为吨（系统侧校验口径）。

    - T/kg/g/L/ml 直接按系数换算（L 密度未知取 1.0）；
    - 瓶（bottle）解析 package_spec（如 160Kg/桶 → 0.160 T/瓶）；
    - 无法解析返回 None。
    """
    qty = _to_decimal(quantity)
    if qty is None or qty < 0 or not unit:
        return None

    if unit == "bottle":
        if not package_spec:
            return None
        match = _BOTTLE_RE.search(package_spec)
        if not match:
            return None
        per_bottle = _normalize_to_tonnes(match.group(1), match.group(2).lower())
        if per_bottle is None:
            return None
        return (qty * per_bottle).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    factor = _UNIT_TO_TONNES.get(unit)
    if factor is None:
        return None
    return (qty * factor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# 碱性化学品关键词（用于把 corrosive 拆成 corrosive_alkali，避免碱被当作酸）
_ALKALI_KEYWORDS = (
    "氢氧化钠", "氢氧化钾", "氢氧化钙", "氢氧化锂",
    "氨水", "液碱", "浓氨", "浓氨水", "碱",
)


def _hazard_keys(record: Any) -> list[str]:
    """记录危险性多选 → 矩阵键列表。

    腐蚀性按 品类/名称 拆分：碱 → corrosive_alkali（避免碱被当作酸，
    与易燃/氧化剂误判冲突），酸 → corrosive_acid。
    """
    classes = getattr(record, "hazard_classes", None) or []
    if isinstance(classes, str):
        classes = [classes]
    category = getattr(record, "category", None) or ""
    name = getattr(record, "material_name", "") or ""
    is_alkali = ("碱" in category) or any(k in name for k in _ALKALI_KEYWORDS)
    keys: list[str] = []
    for cls in classes:
        key = _HAZARD_TO_MATRIX.get(cls)
        if not key:
            continue
        if key == "corrosive_acid" and is_alkali:
            key = "corrosive_alkali"
        if key not in keys:
            keys.append(key)
    return keys


# 水位类预警层级（用于去重：命中高等级则不再重复列低等级）
_WATER_LEVEL_ORDER: tuple[str, ...] = ("over_limit", "near_limit", "high_ratio")


def compute_risk(alert_types: list[str]) -> tuple[str, list[str]]:
    """把命中规则类型归并为 风险标记 + 风险说明。

    - 无命中 → ("normal", ["normal"])
    - 有命中 → ("warn", 去重后的预警类型列表)
      其中水位类（over_limit > near_limit > high_ratio）只保留最高等级。
    """
    types = set(alert_types)
    for i, level in enumerate(_WATER_LEVEL_ORDER):
        if level in types:
            for lower in _WATER_LEVEL_ORDER[i + 1 :]:
                types.discard(lower)
            break
    ordered = sorted(types)
    if not ordered:
        return "normal", ["normal"]
    return "warn", ordered


class ChemicalRiskRuleEngine:
    """危化品库存风险规则引擎（确定性、每日全量跑）。

    仅分析库存量的风险（R01 超量 + 数据质量 R06/R07/R08）；
    禁忌混存分析已按业务要求取消（2026-08-31）。
    """

    def __init__(self, msds_names: set[str] | None = None) -> None:
        # 已归档 MSDS 的物料名称/CAS 集合（服务层 _load_msds_names() 传入，
        # 供后续 MSDS 辅助分类使用；当前规则不依赖）。
        self.msds_names = msds_names or set()

    def scan(self, records: list[Any]) -> list[RuleAlert]:
        """对一批记录跑全部规则，返回命中预警。"""
        alerts: list[RuleAlert] = []
        for record in records:
            alerts.extend(self._scan_single(record))
        return alerts

    # ── 单记录规则 ──

    def _scan_single(self, record: Any) -> list[RuleAlert]:
        alerts: list[RuleAlert] = []
        checks = (
            self._r01_over_limit,
            # 按业务要求：水位类预警仅保留「超量」，关闭「临限」与「高占比」
            # self._r02_near_limit,
            # self._r03_high_ratio,
            self._r06_unclassified,
            self._r07_unit_anomaly,
            self._r08_special_storage,
        )
        for check in checks:
            if alert := check(record):
                alerts.append(alert)
        return alerts

    def _r01_over_limit(self, record: Any) -> RuleAlert | None:
        total = _to_decimal(getattr(record, "total_quantity_t", None))
        limit = _to_decimal(getattr(record, "max_limit", None))
        if total is None or limit is None or limit <= 0:
            return None
        if total > limit:
            return RuleAlert(
                alert_type="over_limit",
                severity="red",
                description=(
                    f"「{getattr(record, 'material_name', '')}」现场物料总量 {total} T "
                    f"超过库存上限 {limit} T"
                ),
                suggestion="立即核查实物库存并转移超量物料至合规库区",
                record_ids=[getattr(record, "id", None)],
            )
        return None

    def _r02_near_limit(self, record: Any) -> RuleAlert | None:
        total = _to_decimal(getattr(record, "total_quantity_t", None))
        limit = _to_decimal(getattr(record, "max_limit", None))
        if total is None or limit is None or limit <= 0:
            return None
        if total > Decimal("0.9") * limit:
            return RuleAlert(
                alert_type="near_limit",
                severity="orange",
                description=(
                    f"「{getattr(record, 'material_name', '')}」库存 {total} T 已达上限 "
                    f"{limit} T 的 90%"
                ),
                suggestion="减少进货或提前转移，预留安全余量",
                record_ids=[getattr(record, "id", None)],
            )
        return None

    def _r03_high_ratio(self, record: Any) -> RuleAlert | None:
        total = _to_decimal(getattr(record, "total_quantity_t", None))
        limit = _to_decimal(getattr(record, "max_limit", None))
        if total is None or limit is None or limit <= 0:
            return None
        if total > Decimal("0.8") * limit:
            return RuleAlert(
                alert_type="high_ratio",
                severity="yellow",
                description=(
                    f"「{getattr(record, 'material_name', '')}」库存 {total} T 已达上限 "
                    f"{limit} T 的 80%"
                ),
                suggestion="关注库存水位，避免补货过多",
                record_ids=[getattr(record, "id", None)],
            )
        return None

    def _r06_unclassified(self, record: Any) -> RuleAlert | None:
        classes = getattr(record, "hazard_classes", None)
        category = getattr(record, "category", None) or ""
        # 已知非危险品（危险性为空但品类已识别，如「其他」）不算未分类
        if not classes and not category:
            return RuleAlert(
                alert_type="unclassified",
                severity="yellow",
                description=f"「{getattr(record, 'material_name', '')}」未标注危险性类别",
                suggestion="补全危险性分类（易燃/腐蚀/易制毒/易制爆/毒性/氧化剂/刺激性）",
                record_ids=[getattr(record, "id", None)],
            )
        return None

    def _r07_unit_anomaly(self, record: Any) -> RuleAlert | None:
        reported = _to_decimal(getattr(record, "total_quantity_t", None))
        system = _normalize_to_tonnes(
            getattr(record, "quantity", None),
            getattr(record, "unit", None),
            getattr(record, "package_spec", None),
        )
        # 多规格合并记录：现场物料总量为各规格求和，无法用单一数量复现，跳过不判单位异常
        spec = getattr(record, "package_spec", None) or ""
        if "、" in spec:
            return None
        if reported is None or system is None or reported <= 0:
            return None
        deviation = abs(system - reported) / reported
        if deviation > Decimal("0.05"):
            return RuleAlert(
                alert_type="unit_anomaly",
                severity="yellow",
                description=(
                    f"「{getattr(record, 'material_name', '')}」系统换算 {system} T 与部门填报 "
                    f"{reported} T 偏差 {deviation * 100:.1f}%（>5%）"
                ),
                suggestion="核实单位与包装规格填写是否正确",
                record_ids=[getattr(record, "id", None)],
            )
        return None

    def _r08_special_storage(self, record: Any) -> RuleAlert | None:
        keys = _hazard_keys(record)
        if not {"precursor_drug", "precursor_explosive"}.intersection(keys):
            return None
        location = getattr(record, "storage_location", "") or ""
        if any(kw in location for kw in _SPECIAL_STORAGE_KEYWORDS):
            return None
        return RuleAlert(
            alert_type="special_storage",
            severity="orange",
            description=(
                f"「{getattr(record, 'material_name', '')}」属易制毒/易制爆，未在专用库"
                f"（危库/试剂柜）存放，当前部位：{location or '-'}"
            ),
            suggestion="立即转移至专库并落实双人双锁管理",
            record_ids=[getattr(record, "id", None)],
        )
