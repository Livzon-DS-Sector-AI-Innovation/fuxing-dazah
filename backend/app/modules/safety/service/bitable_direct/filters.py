"""底座过滤条件构造、下推能力矩阵与北京时间日期窗口（纯函数，只依赖标准库）。

把前两次改造在真机上实测出的 Bitable filter 约束固化成可执行规则：

1. **只支持单层 conjunction**。嵌套条件组（AND 里再放 OR 组）会被 API 拒绝
   （实测 field validation failed），因此构造期直接拒绝，不给调用方机会。
2. **顶层 OR 可用，但不能与日期条件组合**（组合必须嵌套，而嵌套非法）。
   需要「日期窗口 + OR」的场景改用按天多次查询后合并：
   day_queries() -> union_by_record_id() -> trim_records()。
3. **单选字段不支持 contains**（实测 InvalidFilter），只支持
   is / isNot / isEmpty / isNotEmpty；文本字段支持 contains。
   矩阵见 OPERATORS_BY_FIELD_TYPE，checked_condition() 让规则强制生效。
4. **日期过滤用 ExactDate，按天粒度、以表格时区（北京时间）切天**。
   day_filter() 给出某一天的过滤条件；半开区间的精确边界由应用侧毫秒裁剪保证。
5. **日期字段不支持 isGreaterEqual / isLessEqual**（实测 InvalidFilter）：
   下界用 isGreater、上界用 isLess，见 DATE_RANGE_OPERATORS。

本模块不做任何 IO，不 import 任何重依赖或业务域，可被任意域安全复用。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

# 北京时间固定偏移（中国大陆无夏令时；与 special_op_direct.bitable_repo.BJT 一致）
BJT = timezone(timedelta(hours=8))

# 日期字段精确过滤的取值标记（实测：ExactDate 按天粒度、以表格时区切天）
EXACT_DATE = "ExactDate"

# 日期区间算子。日期字段不支持 isGreaterEqual / isLessEqual（实测 InvalidFilter），
# 因此下界只能用 isGreater、上界只能用 isLess。
DATE_RANGE_OPERATORS: frozenset[str] = frozenset({"isGreater", "isLess"})

# 已知算子全集（能力矩阵的并集，用于识别拼错的算子）
COMPARISON_OPERATORS: frozenset[str] = frozenset(
    {
        "is",
        "isNot",
        "contains",
        "doesNotContain",
        "isEmpty",
        "isNotEmpty",
        "isGreater",
        "isLess",
        "isGreaterEqual",
        "isLessEqual",
    }
)

# 字段类型 -> 可用算子（下推能力矩阵）。
#
# 实测确认（2026-09-14 连生产表）：
#   select 不支持 contains（InvalidFilter）；text 支持 contains；
#   datetime 不支持 isGreaterEqual / isLessEqual，只能用 isGreater / isLess。
# 其余条目按飞书官方文档口径收录，尚未连生产表逐条验证；本矩阵是唯一入口，
# 后续只读探针若发现偏差，改这一处即可。
# 只覆盖底座 fields 模块认识的字段类型；number / checkbox 等不在底座取值范围内，
# 不在这里臆造。
OPERATORS_BY_FIELD_TYPE: dict[str, frozenset[str]] = {
    "text": frozenset(
        {"is", "isNot", "contains", "doesNotContain", "isEmpty", "isNotEmpty"}
    ),
    "select": frozenset({"is", "isNot", "isEmpty", "isNotEmpty"}),
    "multi_select": frozenset(
        {"contains", "doesNotContain", "isEmpty", "isNotEmpty"}
    ),
    "person": frozenset({"contains", "doesNotContain", "isEmpty", "isNotEmpty"}),
    "datetime": frozenset({"is", "isGreater", "isLess", "isEmpty", "isNotEmpty"}),
    "attachment": frozenset({"isEmpty", "isNotEmpty"}),
}

FIELD_TYPES: tuple[str, ...] = tuple(OPERATORS_BY_FIELD_TYPE)


def operators_for(field_type: str) -> frozenset[str]:
    """字段类型的可用算子集合；未知类型返回空集合（调用方据此拒绝，而不是猜）。"""
    return OPERATORS_BY_FIELD_TYPE.get(field_type.strip().lower(), frozenset())


def supports(field_type: str, operator: str) -> bool:
    """字段类型是否支持某算子（能力矩阵查询）。"""
    return operator in operators_for(field_type)


def ensure_supported(field_type: str, operator: str) -> None:
    """能力矩阵校验；不支持的组合抛 ValueError（构造期编程错误，不是运行时故障）。"""
    if supports(field_type, operator):
        return
    known = sorted(operators_for(field_type))
    raise ValueError(
        f"字段类型 {field_type!r} 不支持算子 {operator!r}；可用算子: {known}"
    )


#
# 条件构造（Bitable filter 语法）
#


def condition(
    field_name: str,
    operator: str,
    value: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """构造一条扁平 leaf 条件。

    空 value 统一写成 []（与两个旧包一致：isEmpty / isNotEmpty 不带值）。
    本函数不查能力矩阵，需要校验时用 checked_condition()。
    """
    if not field_name:
        raise ValueError("field_name 不能为空")
    if not operator:
        raise ValueError("operator 不能为空")
    return {
        "field_name": field_name,
        "operator": operator,
        "value": list(value) if value is not None else [],
    }


def checked_condition(
    field_type: str,
    field_name: str,
    operator: str,
    value: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """按能力矩阵校验后构造条件；未知算子或不支持的组合直接拒绝。"""
    if operator not in COMPARISON_OPERATORS:
        raise ValueError(
            f"未知算子 {operator!r}；已知算子: {sorted(COMPARISON_OPERATORS)}"
        )
    ensure_supported(field_type, operator)
    return condition(field_name, operator, value)


def _is_condition_group(value: Any) -> bool:
    return isinstance(value, dict) and "conditions" in value


def _ensure_flat_conditions(conditions: list[dict[str, Any]]) -> None:
    if not conditions:
        raise ValueError(
            "空 conditions 会被 Bitable 判为非法过滤；列表可能为空时请改用 flat_group()"
        )
    for index, cond in enumerate(conditions):
        if _is_condition_group(cond):
            raise ValueError(
                f"conditions[{index}] 是嵌套条件组；Bitable filter 只支持单层 "
                "conjunction（实测 field validation failed）。请拆成多条扁平查询后"
                "用 union_by_record_id() 合并"
            )
        if (
            not isinstance(cond, dict)
            or not cond.get("field_name")
            or not cond.get("operator")
        ):
            raise ValueError(f"conditions[{index}] 不是合法的 leaf 条件: {cond!r}")


def is_date_condition(cond: dict[str, Any]) -> bool:
    """是否为日期条件（区间算子 或 ExactDate 取值标记）。

    日期字段用 is + ExactDate 表达「等于某天」，因此不能只看算子。
    """
    if cond.get("operator") in DATE_RANGE_OPERATORS:
        return True
    value = cond.get("value")
    return isinstance(value, (list, tuple)) and bool(value) and value[0] == EXACT_DATE


def and_group(conditions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """扁平 AND 条件组（Bitable filter 的默认形态）。拒绝空列表与嵌套条件组。"""
    items = list(conditions)
    _ensure_flat_conditions(items)
    return {"conjunction": "and", "conditions": items}


def or_group(conditions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """顶层 OR 条件组。

    实测（2026-09-14）：顶层 OR 可用（两个 is 条件返回 2076 条），但**不能与
    日期条件组合**（组合必须嵌套，而嵌套非法）。这里直接拒绝日期条件，并把
    替代做法写进报错信息。

    说明：实测只证明「两个 is 条件的顶层 OR」可用；扁平 OR + 日期条件未实测可行，
    而需要 OR 的日期场景一定得靠嵌套，因此这里把日期条件一并拒绝，统一引导到按天
    查询。将来只读探针若证明可行，改这一处即可。
    """
    items = list(conditions)
    _ensure_flat_conditions(items)
    for cond in items:
        if is_date_condition(cond):
            raise ValueError(
                "顶层 OR 不能与日期条件组合（Bitable filter 不支持嵌套）；"
                "请改用 day_queries() 按天查询后用 union_by_record_id() 合并"
            )
    return {"conjunction": "or", "conditions": items}


def flat_group(
    conditions: Iterable[dict[str, Any]],
    conjunction: str = "and",
) -> dict[str, Any] | None:
    """扁平条件组；空列表返回 None（Bitable 不接受空 conditions）。

    与 hazard_direct 既有 _flat 语义一致：调用方把 None 当作「不过滤」。
    """
    items = list(conditions)
    if not items:
        return None
    if conjunction == "and":
        return and_group(items)
    if conjunction == "or":
        return or_group(items)
    raise ValueError(f"conjunction 只能是 'and' / 'or'，收到 {conjunction!r}")


#
# 北京时间日期（固定 UTC+8，不读进程本地时钟）
#


def epoch_ms(moment: datetime) -> int:
    """aware datetime -> 毫秒时间戳；naive 直接拒绝（时区不明的时间戳是错误来源）。

    与 fields.utc_to_ms 的差别：这里不允许 naive 值按进程本地时钟解释，否则
    「北京时间固定 UTC+8」的承诺会被部署环境 TZ 破坏。
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"需要 aware datetime，收到 naive 值: {moment!r}")
    return int(moment.timestamp() * 1000)


def bjt_day_start(day: date) -> datetime:
    """北京时间某自然日的 00:00（固定 UTC+8）。"""
    return datetime(day.year, day.month, day.day, tzinfo=BJT)


def day_window(day: date) -> tuple[datetime, datetime]:
    """北京时间自然日的半开区间 [00:00, 次日 00:00)。

    与 special_op_direct.bitable_repo.day_window 语义逐字一致（BJT 日界、左闭右开）。
    """
    start = bjt_day_start(day)
    return start, start + timedelta(days=1)


def date_range_window(
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    """ISO 日期区间 -> 北京时间半开区间 [起始日 00:00, 结束日次日 00:00)。

    与 special_op_direct.query.date_window 语义一致；None 原样保留。
    """
    start = bjt_day_start(date_from) if date_from else None
    end = bjt_day_start(date_to) + timedelta(days=1) if date_to else None
    return start, end


def exact_date_value(moment: datetime) -> list[str]:
    """ExactDate 取值：["ExactDate", "<毫秒>"]。"""
    return [EXACT_DATE, str(epoch_ms(moment))]


def _coerce_boundary(boundary: datetime | str) -> datetime | None:
    """把 ISO 字符串 / datetime 归一为 aware datetime；无法解析返回 None。

    兼容 hazard_direct 既有 _date_cond：无时区信息的输入按 UTC 解释
    （字符串与 naive datetime 同一口径），保证收敛后行为逐字不变。
    """
    if isinstance(boundary, str):
        try:
            parsed = datetime.fromisoformat(boundary)
        except ValueError:
            return None
    elif isinstance(boundary, datetime):
        parsed = boundary
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def date_condition(
    field_name: str,
    boundary: datetime | str,
    *,
    lower: bool = True,
) -> dict[str, Any] | None:
    """日期边界条件：lower -> isGreater，否则 isLess；边界无法解析返回 None。

    日期字段不支持 isGreaterEqual / isLessEqual，因此下界用 isGreater、上界用
    isLess，调用方负责把上界设成「次日 00:00」。与 hazard_direct 既有
    _date_cond(field, value, lower=...) 语义逐字一致（含「解析失败返回 None」）。
    """
    moment = _coerce_boundary(boundary)
    if moment is None:
        return None
    return condition(
        field_name,
        "isGreater" if lower else "isLess",
        exact_date_value(moment),
    )


def day_conditions(field_name: str, day: date) -> list[dict[str, Any]]:
    """某北京时间自然日的两个日期条件（isGreater 当日 00:00 + isLess 次日 00:00）。"""
    start, end = day_window(day)
    return [
        condition(field_name, "isGreater", exact_date_value(start)),
        condition(field_name, "isLess", exact_date_value(end)),
    ]


def day_filter(field_name: str, day: date) -> dict[str, Any]:
    """某北京时间自然日的 flat AND 过滤条件（ExactDate 按天粒度）。"""
    return and_group(day_conditions(field_name, day))


def window_days(start: datetime, end: datetime) -> list[date]:
    """半开区间 [start, end) 覆盖的北京时间自然日集合（升序，天然去重）。

    - 两个边界都必须是 aware datetime；北京时间语义来自固定 BJT 偏移，
      不依赖进程本地时区
    - 空窗口 / 倒置窗口返回 []
    - 终点恰好落在自然日 00:00 时，该自然日不计入（半开区间的直接推论）
    """
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("窗口边界必须是 aware datetime")
    if end <= start:
        return []
    days: list[date] = []
    cursor = start.astimezone(BJT).date()
    while bjt_day_start(cursor) < end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def day_queries(
    field_name: str,
    start: datetime,
    end: datetime,
) -> list[tuple[date, dict[str, Any]]]:
    """窗口 -> [(北京时间自然日, 该日的 flat AND 查询条件)]。

    这是「顶层 OR 不能与日期条件组合」的正式替代做法：逐天查询，再用
    union_by_record_id() 合并，最后用 trim_records() 按毫秒精确裁剪。
    空 / 倒置窗口返回 []。
    """
    return [(day, day_filter(field_name, day)) for day in window_days(start, end)]


#
# 应用侧毫秒裁剪与合并
#


def in_window(
    moment: datetime | int | float | None,
    start: datetime,
    end: datetime,
) -> bool:
    """时间是否落在半开区间 [start, end)（起点包含、终点不包含）。

    - 接受毫秒时间戳（Bitable 日期字段原值）或 aware datetime
    - None / 0 / 负数（Bitable 空日期）一律 False
    """
    if moment is None:
        return False
    millis = epoch_ms(moment) if isinstance(moment, datetime) else int(moment)
    if millis <= 0:
        return False
    return epoch_ms(start) <= millis < epoch_ms(end)


def trim_records[T](
    records: Iterable[T],
    moment_of: Callable[[T], datetime | int | float | None],
    *,
    start: datetime,
    end: datetime,
) -> list[T]:
    """应用侧毫秒裁剪：只保留时间落在 [start, end) 内的记录，保持输入顺序。

    Bitable 日期过滤只到天，窗口的精确边界只能在这里保证。时间缺失
    （None / 0 / 空）的记录不进入任何窗口。
    """
    return [record for record in records if in_window(moment_of(record), start, end)]


def union_by_record_id(
    groups: Iterable[Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """多组查询结果按 record_id 去重合并（按首次出现顺序）。

    用于两种既有实测做法：
    - 按天多次查询后合并（day_queries 的配套）
    - 需要 OR 的筛选拆成多条 flat-AND 分支后取并集（special_op 的部门 / 风险分支）

    同一 record_id 重复出现时保留最后一次（与 special_op_direct.query 的既有
    实现一致）；没有 record_id 的记录无法去重，保留在末尾。
    """
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for group in groups:
        for record in group:
            record_id = str(record.get("record_id") or "")
            if record_id:
                merged[record_id] = record
            else:
                anonymous.append(record)
    return [*merged.values(), *anonymous]
