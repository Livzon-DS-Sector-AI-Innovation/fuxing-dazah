"""作业票规则引擎（WorkTicketRuleEngine）——纯函数规则审核。

对规范化 WorkTicket 执行 5 条确定性规则，返回 Violation 列表：
  - TIME_ORDER     时间顺序链（申请≤气体分析≤审批≤开始<结束≤验收）
  - GAS_VALIDITY   作业前 ≤30min 气体分析（仅含气体分析类型）
  - DURATION       作业时长上限（按类型/动火级别）
  - GAS_INTERVAL   受限空间·监测频率：开始→完工验收 >2.5h 须覆盖检测（≥1 次期间记录、间隔
                    ≤2h 含开始/验收边界），≤2.5h 不适用；动火·午后检测：验收跨 12:00 须有午后
                    分析记录；临电/其他不适用（仅含气体分析类型）；缺完工验收时间记数据不足
  - PERSONNEL_CERT 人员证件判定：动火方式涉及电焊/氩弧焊/气焊（割）须登记持证特种作业人员
                    （证件列非空；无特种作业人员行/无子表视为未登记）；其他类型不适用

纯函数：只依赖 ticket，无 IO / DB / 外部服务，结果可确定性复现。
缺失关键时间按“数据不足”处理（not_applicable=False，detail 标明缺字段），
零容忍仅对“明确违规”记 violation；不适用类型用 not_applicable=True 标记。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import overload
from zoneinfo import ZoneInfo

from app.modules.safety.workticket_review.parser import WorkTicket

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Shanghai")

_GAS_INTERVAL_MAX_GAP = timedelta(hours=2)
# 受限空间·监测频率门槛：开始→完工验收总时长严格大于 2.5h 才要求期间检测记录
_CONFINED_GAS_MIN_TOTAL = timedelta(hours=2, minutes=30)
_GAS_VALIDITY_MAX = timedelta(minutes=30)


class RuleNo(StrEnum):
    """规则编号（str 枚举，可直接与字符串比较）。"""

    TIME_ORDER = "TIME_ORDER"
    GAS_VALIDITY = "GAS_VALIDITY"
    DURATION = "DURATION"
    GAS_INTERVAL = "GAS_INTERVAL"
    PERSONNEL_CERT = "PERSONNEL_CERT"


RULE_NAME_MAP: dict[str, str] = {
    RuleNo.TIME_ORDER: "时间顺序链",
    RuleNo.GAS_VALIDITY: "作业前气体分析时限",
    RuleNo.DURATION: "作业时长上限",
    RuleNo.GAS_INTERVAL: "气体分析间隔/午后覆盖",
    RuleNo.PERSONNEL_CERT: "人员证件判定",
}

# 含气体分析子表的类型（动火/受限/临电）
GAS_BEARING_TYPES: frozenset[str] = frozenset(
    {"hot_work", "confined_space", "temporary_electricity"}
)

# 类型 → 时长上限；None 表示该类不设时长上限（规则三不适用）
DURATION_LIMIT_BY_TYPE: dict[str, timedelta | None] = {
    "hot_work": None,  # 由动火级别决定，见 DONGHUO_LEVEL_HOURS
    "confined_space": timedelta(hours=24),
    "temporary_electricity": timedelta(hours=360),
    "height_work": timedelta(hours=72),
    "lifting": None,
    "excavation": None,
    "road_breaking": None,
    "blind_plate": None,
}

# 动火级别编码 → 时长上限。平台原始值（如 1/2/3、一级/二级/三级/特级）集中在此维护。
DONGHUO_LEVEL_HOURS: dict[str, int] = {
    "特": 8,
    "特级": 8,
    "特殊": 8,
    "1": 8,
    "一": 8,
    "一级": 8,
    "grade1": 8,
    "grade_1": 8,
    "special": 8,
    "2": 72,
    "二": 72,
    "二级": 72,
    "grade2": 72,
    "grade_2": 72,
    "3": 72,
    "三": 72,
    "三级": 72,
}

# 未知/缺失动火级别：保守宽松按二级(72h)处理，不误报
DEFAULT_DONGHUO_HOURS = 72


@dataclass
class Violation:
    """单条规则结论（违规或“数据不足/不适用”标记）。"""

    rule_no: str
    rule_name: str
    detail: str
    key_times: list[str] = field(default_factory=list)
    not_applicable: bool = False


@overload
def _tz(dt: None) -> None: ...


@overload
def _tz(dt: datetime) -> datetime: ...


def _tz(dt: datetime | None) -> datetime | None:
    """把时间统一到 Asia/Shanghai；None 原样返回。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt is not None else "—"


def _mk(
    rule_no: str,
    detail: str,
    key_times: list[str] | None = None,
    *,
    not_applicable: bool = False,
) -> Violation:
    return Violation(
        rule_no=rule_no,
        rule_name=RULE_NAME_MAP[rule_no],
        detail=detail,
        key_times=key_times or [],
        not_applicable=not_applicable,
    )


def _missing(rule_no: str, labels: list[str]) -> Violation:
    return _mk(
        rule_no,
        f"数据不足：缺少 {'、'.join(labels)}",
        [],
    )


def _latest_gas_before_start(ticket: WorkTicket) -> datetime | None:
    """取开始前最近一次（最后一次）气体分析时间；无则 None。"""
    if ticket.start_time is None:
        return None
    start = _tz(ticket.start_time)
    candidates = [
        _tz(r.analysis_time)
        for r in ticket.gas_analysis
        if r.analysis_time is not None and _tz(r.analysis_time) <= start
    ]
    return max(candidates) if candidates else None


class WorkTicketRuleEngine:
    """作业票规则引擎（纯函数）。"""

    def evaluate(self, ticket: WorkTicket) -> list[Violation]:
        """对一张票执行全部 5 条规则，返回 Violation 列表。

        只返回“违规”或“数据不足/不适用”标记；合格不返回。
        """
        violations: list[Violation] = []
        violations.extend(self._eval_time_order(ticket))
        violations.extend(self._eval_gas_validity(ticket))
        violations.extend(self._eval_duration(ticket))
        violations.extend(self._eval_gas_interval(ticket))
        violations.extend(self._eval_personnel_cert(ticket))
        return violations

    # ── 规则一：时间顺序链 ──
    def _eval_time_order(self, ticket: WorkTicket) -> list[Violation]:
        if ticket.start_time is None:
            return [_missing(RuleNo.TIME_ORDER, ["start_time"])]

        apply_time = _tz(ticket.apply_time)
        approve_time = _tz(ticket.approve_time)
        start_time = _tz(ticket.start_time)
        end_time = _tz(ticket.end_time)

        # 注：应需求删除规则一第5条「结束晚于完工验收」，验收时间仅作数据展示，
        # 不再参与时间链违规判定，故 验收 不纳入 core/chain。
        core: list[tuple[str, datetime | None]] = [
            ("申请", apply_time),
            ("审批", approve_time),
            ("开始", start_time),
            ("结束", end_time),
        ]
        missing_core = [label for label, dt in core if dt is None]

        # 气体节点（仅含气体分析类型且有作业前分析记录时插入申请与审批之间）
        gas_dt: datetime | None = None
        if not ticket.gasless:
            gas_dt = _latest_gas_before_start(ticket)

        chain: list[tuple[str, datetime | None]] = [
            ("申请", apply_time),
            ("气体分析", gas_dt),
            ("审批", approve_time),
            ("开始", start_time),
            ("结束", end_time),
        ]

        result: list[Violation] = []
        # 对相邻且均存在的节点做比较；后一个节点为“结束”时用严格小于
        for (prev_label, prev_dt), (curr_label, curr_dt) in zip(chain, chain[1:]):
            if prev_dt is None or curr_dt is None:
                continue
            if prev_label == "开始" and curr_label == "结束":
                if prev_dt >= curr_dt:
                    result.append(
                        _mk(
                            RuleNo.TIME_ORDER,
                            "开始时间不早于结束时间（开始≥结束）",
                            [
                                f"开始={_fmt(prev_dt)}",
                                f"结束={_fmt(curr_dt)}",
                            ],
                        )
                    )
            elif prev_dt > curr_dt:
                result.append(
                    _mk(
                        RuleNo.TIME_ORDER,
                        f"{prev_label}晚于{curr_label}",
                        [
                            f"{prev_label}={_fmt(prev_dt)}",
                            f"{curr_label}={_fmt(curr_dt)}",
                        ],
                    )
                )

        if missing_core:
            result.append(_missing(RuleNo.TIME_ORDER, missing_core))
        return result

    # ── 规则二：作业前 ≤30min 气体分析 ──
    def _eval_gas_validity(self, ticket: WorkTicket) -> list[Violation]:
        if ticket.gasless or ticket.ticket_type not in GAS_BEARING_TYPES:
            return [
                _mk(
                    RuleNo.GAS_VALIDITY,
                    "该作业类型无气体分析要求，规则不适用",
                    [],
                    not_applicable=True,
                )
            ]
        if ticket.start_time is None:
            return [_missing(RuleNo.GAS_VALIDITY, ["start_time"])]

        start_time = _tz(ticket.start_time)
        latest = _latest_gas_before_start(ticket)
        if latest is None:
            return [
                _mk(
                    RuleNo.GAS_VALIDITY,
                    "作业开始前无有效气体分析记录",
                    [
                        f"开始={_fmt(start_time)}",
                        "最近一次作业前气体分析=无",
                    ],
                )
            ]

        delta = start_time - latest
        if delta > _GAS_VALIDITY_MAX:
            return [
                _mk(
                    RuleNo.GAS_VALIDITY,
                    f"作业前最近一次气体分析距今 {delta}，超过 30 分钟",
                    [
                        f"开始={_fmt(start_time)}",
                        f"最近一次作业前气体分析={_fmt(latest)}",
                        f"间隔={delta}",
                    ],
                )
            ]
        return []

    # ── 规则三：作业时长上限 ──
    def _duration_limit(self, ticket: WorkTicket) -> timedelta | None:
        if ticket.ticket_type == "hot_work":
            return timedelta(hours=_resolve_donghuo_hours(ticket.level))
        return DURATION_LIMIT_BY_TYPE.get(ticket.ticket_type)

    def _eval_duration(self, ticket: WorkTicket) -> list[Violation]:
        limit = self._duration_limit(ticket)
        if limit is None:
            return [
                _mk(
                    RuleNo.DURATION,
                    "该类作业无时长上限，规则不适用",
                    [],
                    not_applicable=True,
                )
            ]

        if ticket.start_time is None or ticket.end_time is None:
            missing_labels = [
                label
                for label, dt in (("start_time", ticket.start_time), ("end_time", ticket.end_time))
                if dt is None
            ]
            return [_missing(RuleNo.DURATION, missing_labels)]

        start_time = _tz(ticket.start_time)
        end_time = _tz(ticket.end_time)
        duration = end_time - start_time
        if duration > limit:
            return [
                _mk(
                    RuleNo.DURATION,
                    f"作业时长 {duration} 超过上限 {limit}",
                    [
                        f"开始={_fmt(start_time)}",
                        f"结束={_fmt(end_time)}",
                        f"时长={duration}",
                        f"上限={limit}",
                    ],
                )
            ]
        return []

    # ── 规则四：气体分析间隔/午后覆盖（受限·监测频率 + 动火·午后检测） ──
    def _eval_gas_interval(self, ticket: WorkTicket) -> list[Violation]:
        if ticket.gasless or ticket.ticket_type not in GAS_BEARING_TYPES:
            return [
                _mk(
                    RuleNo.GAS_INTERVAL,
                    "该作业类型无气体分析要求，规则不适用",
                    [],
                    not_applicable=True,
                )
            ]
        if ticket.start_time is None or ticket.finish_time is None:
            missing_labels = [
                label
                for label, dt in (("start_time", ticket.start_time), ("finish_time", ticket.finish_time))
                if dt is None
            ]
            # 用户规则：缺少完工验收时间必须单独提示
            return [_missing(RuleNo.GAS_INTERVAL, missing_labels)]

        start_time = _tz(ticket.start_time)
        finish_time = _tz(ticket.finish_time)

        if ticket.ticket_type == "confined_space":
            return self._eval_gas_interval_periodic(ticket, start_time, finish_time)

        if ticket.ticket_type == "hot_work":
            return self._eval_gas_interval_hot_work(ticket, start_time, finish_time)

        return [
            _mk(
                RuleNo.GAS_INTERVAL,
                "未定义的气体分析间隔规则，规则不适用",
                [],
                not_applicable=True,
            )
        ]

    # ── 规则五：人员证件判定（动火涉及焊接切割类须有持证特种作业人员） ──
    _WELD_MODE_KEYWORDS = ("电焊", "氩弧焊", "气焊")
    _SPECIALIST_ROLE = "特种作业人员"

    def _eval_personnel_cert(self, ticket: WorkTicket) -> list[Violation]:
        if ticket.ticket_type != "hot_work":
            return [
                _mk(
                    RuleNo.PERSONNEL_CERT,
                    "该作业类型无人员证件判定要求，规则不适用",
                    [],
                    not_applicable=True,
                )
            ]

        # 精确匹配触发词，不用泛"焊"字：'塑料焊'、'角磨机' 等不触发
        mode = (ticket.work_mode or "").strip()
        if not mode:
            return [_missing(RuleNo.PERSONNEL_CERT, ["work_mode"])]
        if not any(keyword in mode for keyword in self._WELD_MODE_KEYWORDS):
            return [
                _mk(
                    RuleNo.PERSONNEL_CERT,
                    "动火方式不涉及电焊/氩弧焊/气焊（割），规则不适用",
                    [f"动火方式={mode}"],
                    not_applicable=True,
                )
            ]

        specialists = [
            p for p in ticket.personnel if p.role == self._SPECIALIST_ROLE
        ]
        if not specialists:
            return [
                _mk(
                    RuleNo.PERSONNEL_CERT,
                    "动火方式涉及焊接切割类，但人员子表未登记持证特种作业人员",
                    [f"动火方式={mode}"],
                )
            ]

        uncertified = [p.name or "（未填姓名）" for p in specialists if not p.cert_no]
        if uncertified:
            return [
                _mk(
                    RuleNo.PERSONNEL_CERT,
                    f"动火方式涉及焊接切割类，特种作业人员证件为空：{'、'.join(uncertified)}",
                    [f"动火方式={mode}"],
                )
            ]
        return []

    def _eval_gas_interval_periodic(
        self,
        ticket: WorkTicket,
        start_time: datetime,
        finish_time: datetime,
    ) -> list[Violation]:
        total = finish_time - start_time
        if total <= _CONFINED_GAS_MIN_TOTAL:
            return [
                _mk(
                    RuleNo.GAS_INTERVAL,
                    "开始至完工验收未超过 2.5 小时，不要求期间检测记录",
                    [
                        f"开始={_fmt(start_time)}",
                        f"完工验收={_fmt(finish_time)}",
                        f"总时长={total}",
                    ],
                    not_applicable=True,
                )
            ]

        during: list[datetime] = sorted(
            _tz(r.analysis_time)
            for r in ticket.gas_analysis
            if r.analysis_time is not None
            and start_time <= _tz(r.analysis_time) <= finish_time
        )
        if not during:
            return [
                _mk(
                    RuleNo.GAS_INTERVAL,
                    "开始至完工验收超过 2.5 小时，作业期间无气体分析记录（作业前分析除外）",
                    [
                        f"开始={_fmt(start_time)}",
                        f"完工验收={_fmt(finish_time)}",
                        f"总时长={total}",
                    ],
                )
            ]

        # 覆盖检查：开始→首条记录、记录间、末条记录→完工验收，任一间超过 2h 即违规
        chain = [start_time] + during + [finish_time]
        worst_gap = timedelta(0)
        gap_left: datetime | None = None
        gap_right: datetime | None = None
        for left, right in zip(chain, chain[1:]):
            gap = right - left
            if gap > worst_gap:
                worst_gap = gap
                gap_left = left
                gap_right = right

        if worst_gap > _GAS_INTERVAL_MAX_GAP:
            return [
                _mk(
                    RuleNo.GAS_INTERVAL,
                    f"作业期间气体分析间隔 {worst_gap}，超过 2 小时",
                    [
                        f"开始={_fmt(start_time)}",
                        f"完工验收={_fmt(finish_time)}",
                        f"总时长={total}",
                        f"最大间隔={worst_gap}",
                        f"上次分析={_fmt(gap_left)}",
                        f"下次分析={_fmt(gap_right)}",
                    ],
                )
            ]
        return []

    def _eval_gas_interval_hot_work(
        self,
        ticket: WorkTicket,
        start_time: datetime,
        finish_time: datetime,
    ) -> list[Violation]:
        noon = start_time.replace(hour=12, minute=0, second=0, microsecond=0)
        covers_noon = start_time < noon < finish_time
        if not covers_noon:
            return [
                _mk(
                    RuleNo.GAS_INTERVAL,
                    "动火作业未覆盖午后期，规则不适用",
                    [
                        f"开始={_fmt(start_time)}",
                        f"完工验收={_fmt(finish_time)}",
                    ],
                    not_applicable=True,
                )
            ]

        has_after_noon = any(
            r.analysis_time is not None and _tz(r.analysis_time) > noon
            for r in ticket.gas_analysis
        )
        if not has_after_noon:
            return [
                _mk(
                    RuleNo.GAS_INTERVAL,
                    "动火作业覆盖午后期，但午后无气体分析记录",
                    [
                        f"开始={_fmt(start_time)}",
                        f"完工验收={_fmt(finish_time)}",
                        "午后(12:00)后气体分析=无",
                    ],
                )
            ]
        return []


def _resolve_donghuo_hours(level: str | None) -> int:
    """解析动火级别为时长上限小时数；未知/缺失按二级(72h)并告警。"""
    text = (level or "").strip()
    if not text:
        logger.warning("动火作业级别缺失，按二级(72h)处理（保守宽松不误报）")
        return DEFAULT_DONGHUO_HOURS
    if text in DONGHUO_LEVEL_HOURS:
        return DONGHUO_LEVEL_HOURS[text]
    if "特" in text or "一" in text:
        return DONGHUO_LEVEL_HOURS["一级"]
    if "二" in text or "三" in text or text in ("2", "3"):
        return DONGHUO_LEVEL_HOURS["二级"]
    logger.warning("未知动火级别 %r，按二级(72h)处理（保守宽松不误报）", text)
    return DEFAULT_DONGHUO_HOURS


__all__ = [
    "TZ",
    "RuleNo",
    "RULE_NAME_MAP",
    "GAS_BEARING_TYPES",
    "DURATION_LIMIT_BY_TYPE",
    "DONGHUO_LEVEL_HOURS",
    "DEFAULT_DONGHUO_HOURS",
    "Violation",
    "WorkTicketRuleEngine",
]
