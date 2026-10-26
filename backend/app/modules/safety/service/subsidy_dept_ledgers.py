"""提炼工程四部/五部/六部监护补贴台账（飞书多维表格，第二数据源族）。

三个部门不使用电子作业票，监护人特殊作业数据固定来源于各自的 Bitable 台账
（2026-10-08 五部拍板，2026-10-26 四部/六部按同口径接入），安全员按补贴模板
逐行登记。与作业票平台源（``subsidy_plan.SubsidyPlanBuilder``）的统一口径：

- **数据与证书级别均以台账为准**；级别只认台账级别列，不回退证书台账；
  未登级别（含六部整表无级别列）进待核对，按 A 证暂计（与平台源
  ``uncertified_level`` 口径一致）；
- **同日重叠去重**：与平台源同规则（同监护人+同日+时间区间重叠的连通分量
  保留补贴最高一行），台账行重叠按重复登记处理；金额/许可封顶/午休扣除仍由
  ``SubsidyService.calculate`` 按起止时间实算；
- **无票号列**：跳过/待核对的行以「MM-DD 姓名」标识；月份按开始时间归集；
- 表内类型 select 与费率键的差异（动土作业/盲板抽堵/断路作业）经 ``_OP_TYPE_ALIAS``
  归一到 ``SUBSIDY_RATES`` 键（「高处作业」为费率表既有别名键，直接可用）。

三表结构差异（2026-10-26 全量盘点）：

- **五部**：监护人（人员字段）/监护人级别/特殊作业类型(select)/作业级别/
  开始·结束时间（毫秒时间戳列）——开始结束为独立 datetime 列；
- **四部**（提四特殊作业监护人作业统计）：姓名(Text)/监护证类别(select)/
  特殊作业类型(select)/作业级别/日期(datetime 列)/时间段(Text)；
- **六部**：姓名(Text)/特殊作业类型(**MultiSelect**)/作业级别/
  作业地点及内容/日期(**Text**)/时间段(Text)，**无级别列**。

四/六部的时间以「日期 + 时间段文本」表达，时间段为自由文本，实测取值含：
半角/全角冒号（``09:10`` / ``09：10``）、点分（``08.20``）、分隔符
``- — ～ ~ 一 至``、多段以换行/逗号/空格分隔（``09：15-11：30\\n13：10-17:10``）、
链式四时间（``09:16-11:30-13:00-17:10``）、段内带完整日期前缀
（``2026.09.10 09:10-2026.09.10 18:00``）。解析规则见 ``_parse_period_segments``：
按 token 顺序两两配对成段；多段时开始=首段起点、结束=末段终点，
段间空档（含午休）经 ``interval_hours`` 交给计算引擎扣除（引擎收到
interval>0 时不再重复扣午休）。日期区间（``2026.09.06-2026.09.07``）
取首日为基准，仅当结束时刻不晚于开始时刻才顺延一天（跨零点兜底）。
多类型行（六部 MultiSelect 组合如「动火作业|受限空间」）按**该行级别下
单价最高**的类型计费（同价取表内第一个），与重叠去重「保留补贴最高」
同一精神。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.schemas.subsidy import SubsidyRecordInput
from app.modules.safety.service.bitable_direct.reader import fetch_all_records
from app.modules.safety.service.subsidy import PER_OCCURRENCE_TYPES
from app.modules.safety.service.subsidy_plan import (
    SkippedTicket,
    SubsidyPlan,
    UnmatchedGuardian,
    _dedup_overlapping_records,
    _normalize_name,
)

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Shanghai")

# ── 表内 select → SUBSIDY_RATES 键（未列出的键两边一致） ──
_OP_TYPE_ALIAS: dict[str, str] = {
    "动土作业": "动土",
    "盲板抽堵": "抽堵盲板",
    "断路作业": "断路",
}

_LEVEL_A = "A证"
_LEVEL_B = "B证"
_UNCERTIFIED_LEVEL = "A证"  # 与 subsidy_tools._UNCERTIFIED_LEVEL 口径一致

# 布局常量：开始/结束为独立 datetime 列（五部）｜日期列+时间段文本（四/六部）
_LAYOUT_START_END = "start_end"
_LAYOUT_DATE_PERIOD = "date_period"


@dataclass(frozen=True)
class DeptLedgerConfig:
    """一个部门的台账源配置（表结构差异用 layout + 字段名表达）。"""

    department: str                 # 归集部门全名（departments/Excel 标题）
    aliases: tuple[str, ...]        # 路由别名：alias 是部门关键词的子串即命中
    app_token: str                  # Bitable app_token（wiki 节点 token 亦可）
    table_id: str
    layout: str
    fetch_fields: tuple[str, ...]   # 拉取列（只请求需要的列）
    f_guardian: str = "监护人"       # 人员字段（五部）或 Text 姓名（四/六部）
    f_level: str | None = None      # 级别列；None = 表无级别列（六部）
    f_op_type: str = "特殊作业类型"
    f_op_level: str = "作业级别"
    f_location: str = "作业地点+作业内容"
    f_start: str = ""               # start_end 布局
    f_end: str = ""
    f_date: str = ""                # date_period 布局
    f_period: str = ""
    f_date_datetime: bool = False   # 日期列是真 datetime（四部）还是文本（六部）


LEDGER_SOURCES: tuple[DeptLedgerConfig, ...] = (
    DeptLedgerConfig(
        department="提炼工程四部",
        aliases=("提炼工程四部", "提炼四部", "四部"),
        # wiki: https://j0eukrlohu.feishu.cn/wiki/EpW4wkioGivl13kihomcDA0AnTd
        # （底层 Base app_token=TPe1bPKRxaxNX5sBIqAcJtUXn9e，表名「提四特殊作业监护人作业统计」）
        app_token="EpW4wkioGivl13kihomcDA0AnTd",
        table_id="tblDqCn4k6cnGD0V",
        layout=_LAYOUT_DATE_PERIOD,
        fetch_fields=(
            "姓名", "特殊作业类型", "监护内容（具体到作业位置）", "日期",
            "作业级别", "时间段（写全：如8:30-11:00  13:30-17:00）", "监护证类别",
        ),
        f_guardian="姓名",
        f_level="监护证类别",
        f_location="监护内容（具体到作业位置）",
        f_date="日期",
        f_period="时间段（写全：如8:30-11:00  13:30-17:00）",
        f_date_datetime=True,
    ),
    DeptLedgerConfig(
        department="提炼工程五部",
        aliases=("提炼工程五部", "提炼五部", "五部"),
        # https://j0eukrlohu.feishu.cn/base/QHm7bOyMlaWLZysRYw6cnA5tnHh
        app_token="QHm7bOyMlaWLZysRYw6cnA5tnHh",
        table_id="tblXsOBhSvv1JW8Q",
        layout=_LAYOUT_START_END,
        fetch_fields=(
            "监护人", "监护人级别", "特殊作业类型", "作业级别",
            "开始时间", "结束时间", "作业地点+作业内容",
        ),
        f_guardian="监护人",
        f_level="监护人级别",
        f_start="开始时间",
        f_end="结束时间",
    ),
    DeptLedgerConfig(
        department="提炼工程六部",
        aliases=("提炼工程六部", "提炼六部", "六部"),
        # wiki: https://j0eukrlohu.feishu.cn/wiki/Kq15wDxPoibykdkBZ12ce0wjnSh
        # （底层 Base app_token=MKfvbc552a28JOs6dSkc4vxjnge，表名「提炼工程六部监护人补贴记录表」）
        app_token="Kq15wDxPoibykdkBZ12ce0wjnSh",
        table_id="tblGELhxJrfIyBal",
        layout=_LAYOUT_DATE_PERIOD,
        fetch_fields=(
            "姓名", "特殊作业类型", "作业级别", "作业地点及内容", "日期", "时间段",
        ),
        f_guardian="姓名",
        f_level=None,  # 六部台账无级别列：全员进待核对，按 A 证暂计
        f_location="作业地点及内容",
        f_date="日期",
        f_period="时间段",
    ),
)


def match_ledger_source(dept_keyword: str) -> DeptLedgerConfig | None:
    """部门关键词是否命中台账源（提炼四/五/六部走台账，不走平台作业票）。

    规则：任一别名是关键词的子串即命中；零命中或同时命中多表（罕见，
    如关键词同时含「四部」「五部」）返回 None 走平台源。
    """
    keyword = (dept_keyword or "").strip()
    if not keyword:
        return None
    hits = [s for s in LEDGER_SOURCES if any(a in keyword for a in s.aliases)]
    return hits[0] if len(hits) == 1 else None


# ═══════════════════════════════════════════════════════════════════
# Bitable 取值辅助
# ═══════════════════════════════════════════════════════════════════


def _ms_to_datetime(value: Any) -> datetime | None:
    """Bitable datetime 字段（毫秒时间戳）→ 带时区 datetime；非法值返回 None。"""
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=TZ)


def _first_user_name(value: Any) -> str:
    """人员字段（list[dict]，multiple=false）→ 首个姓名。"""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"])
    return ""


def _cell_text(value: Any) -> str:
    """Text 列（list[{text}]）→ 拼接文本。"""
    if isinstance(value, list):
        return "".join(
            str(item.get("text", "")) for item in value if isinstance(item, dict)
        )
    return str(value) if value is not None else ""


def _first_select(value: Any) -> str:
    """select 字段（API 可能返回 str 或 list[str]）→ 首个选项。"""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _norm_op_label(label: str) -> str:
    """表内类型 select → ``SUBSIDY_RATES`` 键（动土作业→动土 等别名归一）。"""
    return _OP_TYPE_ALIAS.get(label, label)


def _all_select_labels(value: Any) -> list[str]:
    """select/多选字段 → 全部选项（单选返回单元素；均过类型别名归一）。"""
    if isinstance(value, list):
        return [_norm_op_label(str(v)) for v in value if v]
    return [_norm_op_label(str(value))] if value else []


# ═══════════════════════════════════════════════════════════════════
# 日期/时间段文本解析（四部/六部布局）
# ═══════════════════════════════════════════════════════════════════

# 分隔符归一：全角冒号→冒号；各类破折号/波浪线/「一」「至」→ '-'
# （'一' 仅出现在时间段文本的「9：45一18：00」写法；逗号/分号→换行分段）。
_PERIOD_TRANS = str.maketrans({
    "：": ":", "，": "\n", "、": "\n", ";": "\n", "；": "\n",
    "—": "-", "–": "-", "－": "-", "～": "-", "~": "-", "至": "-",
})
# 「一」可能出现于正常词汇，仅当夹在两个时间 token 之间才像分隔符；
# 直接归一风险（时间段列无其他中文）可控，实测 2 行使用该写法。
_PERIOD_TRANS["一"] = "-"

# 日期 token：2026.09.10 / 2026-09-10 / 2026/9/10 / 2026年9月10日
# 时间 token：09:10 / 9:00 / 08.20（点分）/ 8时30分
# DATE 必须排在 TIME 之前：'2026.09.10' 的 '26.09' 才不会先被当成时间吞掉。
_DT_TOKEN_RE = re.compile(
    r"(?P<dy>\d{4})[./\-年](?P<dm>\d{1,2})[./\-月](?P<dd>\d{1,2})日?"
    r"|(?P<th>\d{1,2})[:.时](?P<tm>\d{1,2})分?"
)


def _scan_datetime_tokens(text: str) -> list[tuple[str, Any]]:
    """扫描归一化后的文本，产出有序 token：('d', date) / ('t', (时, 分))。

    非法值防御：小时>23 / 分钟>59 的时间 token 丢弃；日期由 ``date()``
    构造失败时丢弃（如 2026.02.30）。
    """
    tokens: list[tuple[str, Any]] = []
    for m in _DT_TOKEN_RE.finditer(text):
        if m.group("dy"):
            try:
                tokens.append(("d", date(int(m.group("dy")), int(m.group("dm")), int(m.group("dd")))))
            except ValueError:
                continue
        else:
            hour, minute = int(m.group("th")), int(m.group("tm"))
            if hour <= 23 and minute <= 59:
                tokens.append(("t", (hour, minute)))
    return tokens


def _parse_date_text(text: str) -> date | None:
    """日期文本（如 '2026.09.03'，也可能带区间 '2026.09.06-2026.09.07'）→ 首个日期。"""
    for kind, value in _scan_datetime_tokens(_normalize_period_text(text)):
        if kind == "d":
            return value
    return None


def _normalize_period_text(text: str) -> str:
    return (text or "").translate(_PERIOD_TRANS)


@dataclass(frozen=True)
class _Segment:
    start: datetime
    end: datetime


def _parse_period_segments(
    period_text: str, base_date: date
) -> tuple[datetime, datetime, float] | None:
    """时间段文本 + 基准日期 → (开始, 结束, 段间空档小时)。

    - token 按出现顺序两两配对成段（链式 ``09:16-11:30-13:00-17:10`` 天然配成两段）；
    - 段内自带日期前缀时优先用段内日期，否则用基准日期；
    - 结束时刻不晚于开始时刻 → 顺延一天（跨零点兜底；日期区间行取首日基准）；
    - 多段时空档 = (末段结束-首段开始) - Σ段时长，经 ``interval_hours`` 交给引擎扣除
      （引擎 interval>0 时不再重复扣午休，避免双扣）；
    - 无法解析出至少一个完整段（无时间 token / 奇数个 token）→ None。
    """
    tokens = _scan_datetime_tokens(_normalize_period_text(period_text))
    segments: list[tuple[tuple[date | None, tuple[int, int]], tuple[date | None, tuple[int, int]]]] = []
    ctx_date: date | None = None
    pending: tuple[date | None, tuple[int, int]] | None = None
    for kind, value in tokens:
        if kind == "d":
            ctx_date = value
            continue
        if pending is None:
            pending = (ctx_date, value)
        else:
            segments.append((pending, (ctx_date, value)))
            pending = None
    if pending is not None or not segments:
        return None  # 奇数个时间 token：无法配对

    resolved: list[_Segment] = []
    for (sd, (sh, sm)), (ed, (eh, em)) in segments:
        start = datetime.combine(sd or base_date, time(sh, sm), tzinfo=TZ)
        end = datetime.combine(ed or base_date, time(eh, em), tzinfo=TZ)
        if end <= start:
            end += timedelta(days=1)
        resolved.append(_Segment(start, end))

    first, last = resolved[0].start, resolved[-1].end
    span = (last - first).total_seconds() / 3600.0
    worked = sum((seg.end - seg.start).total_seconds() / 3600.0 for seg in resolved)
    return first, last, round(max(span - worked, 0.0), 2)


def _pick_primary_op_type(labels: list[str], op_level: str) -> str:
    """多类型行（六部 MultiSelect 组合）→ 该行级别下单价最高的类型。

    同价取表内第一个（如 动火|受限 一级均为 10 元/半小时 → 动火作业）。
    与同日重叠去重「保留补贴最高一张」同一精神：一行只按一种类型计费。
    """
    if len(labels) <= 1:
        return labels[0] if labels else ""

    from app.modules.safety.service.subsidy import SUBSIDY_RATES

    def unit_price(label: str) -> float:
        rates = SUBSIDY_RATES.get(label, {})
        price = rates.get(op_level, rates.get("默认", 0))
        return float(price)

    return max(labels, key=unit_price)


def _known_op_type(op_label: str) -> bool:
    """是否为费率表可计费的作业类型（用于未知类型跳过判定）。"""
    from app.modules.safety.service.subsidy import SUBSIDY_RATES

    return op_label in SUBSIDY_RATES


# ═══════════════════════════════════════════════════════════════════
# 拉取 + 计划整理
# ═══════════════════════════════════════════════════════════════════


async def fetch_ledger_rows(source: DeptLedgerConfig) -> list[dict[str, Any]]:
    """分页拉取台账全部行（安全应用凭据已验证可读；只请求需要的列）。"""
    client = SafetyBitableClient(app_token=source.app_token)
    rows = await fetch_all_records(
        client,
        table_id=source.table_id,
        field_names=list(source.fetch_fields),
    )
    logger.info("%s监护台账拉取完成: %d 行", source.department, len(rows))
    return rows


@dataclass
class _RawRow:
    """行归一中间结构（布局差异在此抹平）。"""

    guardian_name: str
    op_labels: list[str]
    op_level: str
    location: str
    start: datetime | None
    end: datetime | None
    interval_hours: float = 0.0
    row_date: date | None = None  # 行标识「MM-DD 姓名」用


def _extract_row(source: DeptLedgerConfig, fields: dict[str, Any]) -> _RawRow:
    if source.layout == _LAYOUT_START_END:
        return _RawRow(
            guardian_name=_normalize_name(_first_user_name(fields.get(source.f_guardian))),
            op_labels=[_norm_op_label(_first_select(fields.get(source.f_op_type)))],
            op_level=_first_select(fields.get(source.f_op_level)),
            location=str(fields.get(source.f_location) or "").strip(),
            start=_ms_to_datetime(fields.get(source.f_start)),
            end=_ms_to_datetime(fields.get(source.f_end)),
        )

    # date_period 布局：日期列 + 时间段文本
    if source.f_date_datetime:
        base = _ms_to_datetime(fields.get(source.f_date))
        base_date = base.date() if base else None
    else:
        base_date = _parse_date_text(_cell_text(fields.get(source.f_date)))

    period = _cell_text(fields.get(source.f_period))
    start = end = None
    interval = 0.0
    if base_date is not None:
        parsed = _parse_period_segments(period, base_date)
        if parsed is not None:
            start, end, interval = parsed
    return _RawRow(
        guardian_name=_normalize_name(_cell_text(fields.get(source.f_guardian))),
        op_labels=_all_select_labels(fields.get(source.f_op_type)),
        op_level=_first_select(fields.get(source.f_op_level)),
        location=_cell_text(fields.get(source.f_location)).strip(),
        start=start,
        end=end,
        interval_hours=interval,
        row_date=base_date,
    )


def build_ledger_plan(
    source: DeptLedgerConfig,
    rows: list[dict[str, Any]],
    year: int,
    month: int,
    *,
    uncertified_level: str | None = _UNCERTIFIED_LEVEL,
) -> SubsidyPlan:
    """台账行 → SubsidyPlan（纯函数，布局差异已抹平）。

    - **级别只认台账登记**（同名多行以最后一次登记为准；六部无级别列 →
      全员进待核对，按 ``uncertified_level`` 暂计，None 则不计入）；
    - **同日重叠去重**：与平台源同规则（连通分量保留补贴最高一行）；
    - 跳过原因与平台源对齐：缺少开始时间 / 缺少结束时间（按次类型兜底除外）/
      无监护人 / 未知作业类型 / 时间段无法解析；行标识 = "MM-DD 姓名"。
    """
    # 表内级别映射（全表登记皆参与；级别是人的属性，不限目标月）
    sheet_level_map: dict[str, str] = {}
    if source.f_level is not None:
        for row in rows:
            fields = row.get("fields") or {}
            name = _normalize_name(
                _first_user_name(fields.get(source.f_guardian))
                if source.layout == _LAYOUT_START_END
                else _cell_text(fields.get(source.f_guardian))
            )
            sheet_level = _first_select(fields.get(source.f_level))
            if name and sheet_level in (_LEVEL_A, _LEVEL_B):
                sheet_level_map[name] = sheet_level

    records: list[SubsidyRecordInput] = []
    skipped: list[SkippedTicket] = []
    unmatched: list[UnmatchedGuardian] = []
    unmatched_by_name: dict[str, UnmatchedGuardian] = {}
    unmatched_tickets = 0

    for row in rows:
        fields = row.get("fields") or {}
        raw = _extract_row(source, fields)
        op_label = _pick_primary_op_type(raw.op_labels, raw.op_level)
        row_id = (
            f"{raw.row_date:%m-%d} {raw.guardian_name}"
            if raw.row_date and raw.guardian_name
            else f"{raw.start:%m-%d} {raw.guardian_name}"
            if raw.start and raw.guardian_name
            else "(不完整行)"
        )

        if raw.start is None:
            # 日期/时间段缺失或无法解析：区分原因便于台账修正
            if (
                source.layout == _LAYOUT_DATE_PERIOD
                and _cell_text(fields.get(source.f_period))
            ):
                reason = "时间段无法解析"
            else:
                reason = "缺少开始时间"
            skipped.append(SkippedTicket(row_id, op_label or "?", reason))
            continue
        if raw.start.year != year or raw.start.month != month:
            continue  # 非目标月：直接忽略（不进任何清单）
        if raw.end is None:
            if op_label in PER_OCCURRENCE_TYPES:
                raw.end = raw.start  # 按次计费：时长不影响金额
            else:
                skipped.append(SkippedTicket(row_id, op_label or "?", "缺少结束时间"))
                continue
        if not raw.guardian_name:
            skipped.append(SkippedTicket(row_id, op_label or "?", "无监护人"))
            continue
        if not _known_op_type(op_label):
            skipped.append(SkippedTicket(row_id, op_label or "?", "未知作业类型"))
            continue

        level = sheet_level_map.get(raw.guardian_name)
        if level is None:
            unmatched_tickets += 1
            entry = unmatched_by_name.get(raw.guardian_name)
            if entry is None:
                entry = UnmatchedGuardian(name=raw.guardian_name, ticket_count=0)
                unmatched_by_name[raw.guardian_name] = entry
                unmatched.append(entry)
            entry.ticket_count += 1
            if op_label not in entry.operation_types:
                entry.operation_types.append(op_label)
            if not uncertified_level:
                continue  # 未登级别且未开暂计：不计金额
            level = uncertified_level

        records.append(
            SubsidyRecordInput(
                guardian_name=raw.guardian_name,
                guardian_level=level,
                ticket_no=row_id,  # 台账无票号,以「MM-DD 姓名」行标识(去重淘汰说明/Excel 票号列用)
                department=source.department,
                operation_type=op_label,
                operation_level=raw.op_level,
                location_content=raw.location,
                start_time=raw.start.isoformat(),
                end_time=raw.end.isoformat(),
                interval_hours=f"{raw.interval_hours:g}",
            )
        )

    # 同监护人同日重叠去重（与平台源同规则；台账行重叠多为重复登记）
    records, dedup_skipped = _dedup_overlapping_records(records)
    skipped.extend(dedup_skipped)

    return SubsidyPlan(
        records=records,
        unmatched=unmatched,
        skipped=skipped,
        departments={source.department},
        total_tickets=len(rows),
        domain_tickets=len(records) + unmatched_tickets + len(skipped),
        matched_tickets=len(records),
        unmatched_tickets=unmatched_tickets,
        skipped_tickets=len(skipped),
    )


__all__ = [
    "DeptLedgerConfig",
    "LEDGER_SOURCES",
    "match_ledger_source",
    "fetch_ledger_rows",
    "build_ledger_plan",
    "_ms_to_datetime",
    "_parse_period_segments",
    "_parse_date_text",
    "_pick_primary_op_type",
]
