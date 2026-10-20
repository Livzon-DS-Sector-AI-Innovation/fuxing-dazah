"""遥测阈值规则引擎（facilities-p2 票 02，纯函数，now 可注入）。

照 facilities/engine.py 范式：判定口径（上下限/变化率/连续点去抖/静默窗桶）
单点定义，编排层（alerter/collector）与单测共用，防两处漂移。

规则分层（DESIGN §5.3）：代码默认规则 + app_config 键 SAFETY_TELEMETRY_RULES
JSON 覆写，合并为并集；同一 (设备, 指标) 匹配时取最具体：
设备级 > 类别级 > 通配默认。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# 级别常量与 models.telemetry.ALARM_LEVEL_* 同值（本模块保持纯函数不 import
# ORM；改动需两处同步——测试断言双端字面量防漂移）
LEVEL_WARNING = "warning"
LEVEL_ALARM = "alarm"

# 连续异常点默认去抖：2 点（防单点毛刺，DESIGN §5.2）
DEFAULT_CONSECUTIVE = 2


@dataclass(frozen=True)
class RuleSpec:
    """一条阈值规则（metric 必填；equipment_no/category 可空=层级更低）。"""

    metric: str
    equipment_no: str | None = None
    category: str | None = None
    min: float | None = None
    max: float | None = None
    # 相邻两点每分钟变化量上限（绝对值）
    rate_per_min: float | None = None
    consecutive: int = DEFAULT_CONSECUTIVE
    level: str = LEVEL_ALARM
    unit: str | None = None

    @property
    def specificity(self) -> int:
        """匹配优先级：设备级 2 > 类别级 1 > 通配 0。"""
        if self.equipment_no:
            return 2
        if self.category:
            return 1
        return 0

    def matches(self, equipment_no: str | None, category: str | None) -> bool:
        if self.equipment_no and self.equipment_no != equipment_no:
            return False
        if self.category and self.category != category:
            return False
        return True

    def to_dict(self) -> dict:
        out: dict = {"metric": self.metric}
        for key in ("equipment_no", "category", "min", "max", "rate_per_min", "unit", "level"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        out["consecutive"] = self.consecutive
        return out


# 锅炉典型默认规则（DESIGN §5.3：汽压上下限/水位上下限/炉膛温度上限）
DEFAULT_RULES: tuple[RuleSpec, ...] = (
    RuleSpec(metric="汽压", category="锅炉", min=0.2, max=1.0, unit="MPa",
             rate_per_min=0.05, level=LEVEL_WARNING),
    RuleSpec(metric="水位", category="锅炉", min=-50, max=50, unit="mm",
             rate_per_min=10.0, level=LEVEL_WARNING),
    RuleSpec(metric="炉膛温度", category="锅炉", max=1200, unit="℃",
             level=LEVEL_ALARM),
)


def rule_for(
    rules: tuple[RuleSpec, ...],
    equipment_no: str | None,
    category: str | None,
    metric: str,
) -> RuleSpec | None:
    """(设备, 类别, 指标) → 最具体匹配规则；无匹配返回 None。"""
    best: RuleSpec | None = None
    for r in rules:
        if r.metric != metric:
            continue
        if not r.matches(equipment_no, category):
            continue
        if best is None or r.specificity > best.specificity:
            best = r
    return best


# ── 覆写合并（app_config JSON → RuleSpec 并集；非法回退默认）──────────

_OVERRIDE_KEYS = {
    "metric": str,
    "equipment_no": str,
    "category": str,
    "unit": str,
    "level": str,
}


def _parse_override_item(item: object) -> RuleSpec | None:
    if not isinstance(item, dict):
        return None
    kwargs: dict = {}
    for key, typ in _OVERRIDE_KEYS.items():
        if key in item and item[key] is not None:
            if not isinstance(item[key], typ):
                return None
            kwargs[key] = item[key]
    metric = kwargs.get("metric")
    if not metric:
        return None
    for key in ("min", "max", "rate_per_min"):
        if key in item and item[key] is not None:
            try:
                kwargs[key] = float(item[key])
            except (TypeError, ValueError):
                return None
    if "consecutive" in item and item["consecutive"] is not None:
        try:
            consecutive = int(item["consecutive"])
        except (TypeError, ValueError):
            return None
        if consecutive < 1:
            return None
        kwargs["consecutive"] = consecutive
    if kwargs.get("level") not in (None, LEVEL_WARNING, LEVEL_ALARM):
        return None
    return RuleSpec(**kwargs)


def effective_rules(override_json: str | None) -> tuple[RuleSpec, ...]:
    """默认规则 + JSON 覆写并集；任一非法（非 JSON/非 list/字段类型错）整体
    回退默认（保守：宁可用已知好规则，不用半份覆写）。"""
    if not override_json:
        return DEFAULT_RULES
    try:
        raw = json.loads(override_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("SAFETY_TELEMETRY_RULES 非法 JSON，回退代码默认规则")
        return DEFAULT_RULES
    if not isinstance(raw, list):
        logger.warning("SAFETY_TELEMETRY_RULES 须为规则数组，回退代码默认规则")
        return DEFAULT_RULES
    parsed = [_parse_override_item(item) for item in raw]
    if any(p is None for p in parsed):
        logger.warning("SAFETY_TELEMETRY_RULES 存在非法规则项，整体回退代码默认规则")
        return DEFAULT_RULES
    return DEFAULT_RULES + tuple(parsed)  # type: ignore[operator]


# ── 判定（上下限去抖 / 变化率）──────────────────────────────────────


@dataclass(frozen=True)
class Violation:
    """一次规则命中（报警记录的原料）。"""

    kind: str           # limit_high / limit_low / rate
    metric: str
    value: float
    recorded_at: datetime
    rule_desc: str
    level: str


def _fmt(value: float, unit: str | None) -> str:
    text = f"{value:g}"
    return f"{text}{unit}" if unit else text


def evaluate(
    points: list[tuple[datetime, float]],
    rule: RuleSpec,
    *,
    now: datetime,
) -> Violation | None:
    """对升序点位跑规则（now 可注入，当前判定不依赖墙钟）。

    - 上下限：最后 consecutive 点同向越界才触发（去抖）；方向混合的毛刺
      往返不算连续异常；
    - 变化率：最新相邻两点每分钟变化量超 rate_per_min 即触发（两点自含
      去抖语义，不再叠加 consecutive）。
    """
    if not points:
        return None
    latest_ts, latest_value = points[-1]
    unit = rule.unit

    # 去抖铁律：历史点数不足 consecutive 时上下限不判（防首点毛刺误报；
    # 全新设备首条越界读数等第二条同向越界才触发）
    tail = points[-rule.consecutive:] if len(points) >= rule.consecutive else []
    streak = len(tail)
    if streak and rule.max is not None and all(v > rule.max for _, v in tail):
        return Violation(
            kind="limit_high", metric=rule.metric, value=latest_value,
            recorded_at=latest_ts,
            rule_desc=f"{rule.metric} {_fmt(latest_value, unit)} 连续{streak}点超上限 {_fmt(rule.max, unit)}",
            level=rule.level,
        )
    if streak and rule.min is not None and all(v < rule.min for _, v in tail):
        return Violation(
            kind="limit_low", metric=rule.metric, value=latest_value,
            recorded_at=latest_ts,
            rule_desc=f"{rule.metric} {_fmt(latest_value, unit)} 连续{streak}点低于下限 {_fmt(rule.min, unit)}",
            level=rule.level,
        )

    if rule.rate_per_min is not None and len(points) >= 2:
        (t1, v1), (t2, v2) = points[-2], points[-1]
        elapsed_min = (t2 - t1).total_seconds() / 60.0
        if elapsed_min > 0:
            rate = abs(v2 - v1) / elapsed_min
            if rate > rule.rate_per_min:
                return Violation(
                    kind="rate", metric=rule.metric, value=latest_value,
                    recorded_at=latest_ts,
                    rule_desc=(
                        f"{rule.metric} {_fmt(latest_value, unit)} 变化率 "
                        f"{rate:.3f}/分钟 超限 {rule.rate_per_min:g}/分钟"
                    ),
                    level=rule.level,
                )
    return None


def dedupe_key(
    equipment_no: str,
    metric: str,
    level: str,
    now: datetime,
    silence_seconds: int,
) -> str:
    """静默窗时间桶键：同窗同源同级别 → 同 key（唯一键拦截重发）。"""
    window = int(now.timestamp()) // max(1, int(silence_seconds))
    return f"{equipment_no}|{metric}|{level}|{window}"
