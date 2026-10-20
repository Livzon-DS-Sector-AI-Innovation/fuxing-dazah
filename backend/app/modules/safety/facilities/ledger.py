"""三台账列映射适配层（纯函数，无 IO）。

设计拍板（DESIGN §3.1）：三张 bitable 台账已存在，**不改表结构**，接入=登记
连接+列映射适配。实际列名未知（连接待登记），映射两段式：

1. 候选列名**精确匹配**（按优先序，先命中先占列——一个真实列只归一个标准字段）；
2. 未命中的标准字段再做**表头关键词模糊匹配**（表头含全部关键词即命中，
   同样占列互斥；消防特有列如「换药/报废」优先于通用「下次」认领）。

锚点口径（督办锚点 = 校验任务 due_date 的来源）：

- 优先取「下次日期」列；缺则「上次日期 + 周期（月）」**运行时推算**
  （只读不回写）；两者皆缺 → 行进信息不全清单（原因可查，倒逼补录）。
- 消防器材多锚点：下次日期→检查、换药到期→换药、报废到期→报废更换，
  各锚点独立派生任务（幂等键含 due_date 天然去重）。
- 编号列缺 → **合成展示编号**（`类别·位置`→名称→record_id 兜底；2026-10-20
  灭火器台账拍板：真实表无编号列，行标识本就是 record_id，不阻塞派发）；
  状态列缺 → 视为全部在用。
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields

logger = logging.getLogger(__name__)

# ── biz_type / kind / API url key 三方映射 ──────────────────────────
BIZ_ACCESSORY = "accessory"
BIZ_FIRE = "fire_equipment"
BIZ_SPECIAL = "special_equipment"

DOMAIN = "facilities"

# biz_type -> registry kind
BIZ_TO_KIND: dict[str, str] = {
    BIZ_ACCESSORY: "accessory_ledger",
    BIZ_FIRE: "fire_equipment_ledger",
    BIZ_SPECIAL: "special_equipment_ledger",
}
# API url key -> biz_type（GET /facilities/ledgers/{url_key}）
URL_TO_BIZ: dict[str, str] = {
    "accessories": BIZ_ACCESSORY,
    "fire-equipment": BIZ_FIRE,
    "special-equipment": BIZ_SPECIAL,
}
BIZ_LABELS: dict[str, str] = {
    BIZ_ACCESSORY: "安全附件",
    BIZ_FIRE: "消防器材",
    BIZ_SPECIAL: "特种设备",
}

# 派发提前量（DESIGN §4.2 / P4 拍板：附件 30 天、特种设备 45 天；
# 消防 60 天——2026-10-20 拍板：灭火器换新含采购周期约 2 个月，提前两个月预警追踪）
LEAD_DAYS: dict[str, int] = {
    BIZ_ACCESSORY: 30,
    BIZ_FIRE: 60,
    BIZ_SPECIAL: 45,
}

# ── 标准字段候选列名（精确匹配，按优先序）────────────────────────────
_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "equipment_no": (
        "设备编号", "附件编号", "器材编号", "特种设备编号", "登记编号", "编号",
    ),
    "name": ("设备名称", "附件名称", "器材名称", "名称"),
    "category": ("设备类别", "附件类别", "器材类别", "类别", "类型", "分类"),
    "location": ("安装位置", "存放位置", "使用位置", "位置", "位置/区域", "区域"),
    "department": ("责任部门", "所属部门", "使用部门", "管理部门", "部门"),
    "owner": ("责任人", "责任人员", "负责人", "保管人", "到期提醒人员"),
    "last_date": (
        "上次校验日期", "上次检验日期", "上次检查日期",
        "最近校验日期", "最近检验日期", "校验日期", "检验日期",
    ),
    "cycle_months": (
        "校验周期（月）", "检验周期（月）", "检查周期（月）",
        "校验周期", "检验周期", "检查周期", "周期（月）", "周期",
    ),
    "next_date": (
        "下次校验日期", "下次检验日期", "下次检查日期",
        "校验到期日期", "检验到期日期", "到期日期",
    ),
    "status": ("设备状态", "使用状态", "器材状态", "状态"),
    # 消防器材特有
    "refill_due": ("换药到期", "下次换药日期", "换药/维修到期", "换药日期", "维修到期"),
    "scrap_due": ("报废到期", "报废日期", "使用年限至", "报废年限"),
    # 特种设备特有
    "register_code": ("注册代码", "设备注册代码", "注册号"),
    "inspection_category": ("检验类别", "定期检验类别"),
    "agency": ("检验机构", "检测机构"),
    "monitor_flag": ("接入监控", "是否接入监控", "监控接入"),
}

# 模糊匹配关键词组（表头含组内全部关键词即命中；组按序尝试）
_FIELD_KEYWORDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "equipment_no": (("编号",),),
    "name": (("名称",),),
    "category": (("类别",), ("类型",)),
    "location": (("位置",), ("区域",)),
    "department": (("部门",),),
    "owner": (("责任人",), ("负责人",), ("保管",)),
    "last_date": (("上次",), ("最近", "校验"), ("最近", "检验"), ("最近", "检查")),
    "cycle_months": (("周期",),),
    "next_date": (("下次",), ("到期",)),
    "status": (("状态",),),
    "refill_due": (("换药",),),
    "scrap_due": (("报废",),),
    "register_code": (("注册", "代码"),),
    "inspection_category": (("检验类别",),),
    "agency": (("机构",),),
    "monitor_flag": (("监控",),),
}

# 模糊匹配时通用日期字段须排除的表头关键词（防「下次换药日期」被 next_date 认领）
_DATE_FIELD_EXCLUDES: dict[str, tuple[str, ...]] = {
    "last_date": ("换药", "报废", "维修", "购", "入职", "登记"),
    "next_date": ("换药", "报废", "维修"),
    "cycle_months": ("安全", "培训"),
}

# 模糊认领顺序：特有字段先认领，通用字段（编号/名称/日期）最后
_FUZZY_ORDER: tuple[str, ...] = (
    "register_code", "inspection_category", "agency", "monitor_flag",
    "refill_due", "scrap_due",
    "status", "cycle_months", "last_date", "next_date",
    "department", "owner", "location", "category", "equipment_no", "name",
)

# 状态口径（值包含关键词即判定；状态列缺/未知值→视为在用，保守不丢行）
_STATUS_INACTIVE_KEYWORDS: tuple[str, ...] = (
    "报废", "停用", "封存", "淘汰", "失效",
)

# 消防特有锚点 -> (标准字段, 工作性质 task_subtype, 任务文案 task_kind)
_FIRE_EXTRA_ANCHORS: tuple[tuple[str, str, str], ...] = (
    ("refill_due", "换药", "换药到期"),
    ("scrap_due", "报废更换", "报废到期"),
)

# 各 biz_type 的默认任务文案（task_kind，触发主锚点时）
_BIZ_TASK_KIND: dict[str, str] = {
    BIZ_ACCESSORY: "校验",
    BIZ_FIRE: "检查",
    BIZ_SPECIAL: "定期检验",
}


@dataclass(frozen=True)
class LedgerAnchorSpec:
    """一个可派发锚点（台账行的某个到期性质）。"""

    field: str          # 标准字段名（next_date/refill_due/scrap_due）
    subtype: str        # 工作性质（检查/换药/报废更换/校验/定期检验）
    task_kind: str      # 任务文案


def anchors_of_biz(biz_type: str) -> tuple[LedgerAnchorSpec, ...]:
    """biz_type 的派发锚点集合：主锚点在前，消防特有锚点随后。"""
    main = LedgerAnchorSpec("next_date", _BIZ_TASK_KIND[biz_type], _BIZ_TASK_KIND[biz_type])
    if biz_type != BIZ_FIRE:
        return (main,)
    extras = tuple(
        LedgerAnchorSpec(f, subtype, kind) for f, subtype, kind in _FIRE_EXTRA_ANCHORS
    )
    return (main, *extras)


def resolve_columns(headers: list[str]) -> dict[str, str]:
    """表头列表 → 标准字段→实际列名（精确优先，占列互斥，模糊兜底）。"""
    by_header: dict[str, str] = {}   # 实际列名 -> 标准字段（占列互斥）
    out: dict[str, str] = {}
    header_set = [h for h in dict.fromkeys(headers) if h]

    # 第一遍：精确匹配（候选按优先序，先命中先占列）
    for std, candidates in _FIELD_CANDIDATES.items():
        for cand in candidates:
            if cand in header_set and cand not in by_header:
                by_header[cand] = std
                out[std] = cand
                break

    # 第二遍：模糊匹配（特有字段先认领；表头须含组内全部关键词且未被占用）
    for std in _FUZZY_ORDER:
        if std in out:
            continue
        excludes = _DATE_FIELD_EXCLUDES.get(std, ())
        for header in header_set:
            if header in by_header:
                continue
            if any(ex in header for ex in excludes):
                continue
            if any(all(kw in header for kw in group) for group in _FIELD_KEYWORDS.get(std, ())):
                by_header[header] = std
                out[std] = header
                break
    return out


def _shift_months(d: date, months: int) -> date:
    """按自然月平移（日溢出夹到月末：1-31 + 1 月 → 2-28/29）。"""
    if months <= 0:
        return d
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _as_date(fields: dict[str, Any], column: str | None) -> date | None:
    """列名 -> 北京日期（毫秒时间戳 +8h 取日；缺列/空值 None）。"""
    if not column:
        return None
    dt = bd_fields.datetime_ms(fields, column)
    return (dt + timedelta(hours=8)).date() if dt else None


def _as_int(fields: dict[str, Any], column: str | None) -> int | None:
    if not column:
        return None
    raw = bd_fields.text(fields, column)
    if raw is None:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return int(digits) if digits else None


def _status_value(fields: dict[str, Any], column: str | None) -> str:
    if not column:
        return ""
    return bd_fields.select(fields, column) or ""


def is_active_status(status_value: str) -> bool:
    """状态判定：含停用类关键词 → 非在用；其余（含空/未知）→ 在用。

    状态列缺失（空串）按拍板视为在用；未知值不静默丢行，保守视为在用
    （台账页可见，由人工纠正数据）。
    """
    if any(kw in status_value for kw in _STATUS_INACTIVE_KEYWORDS):
        return False
    return True


@dataclass
class LedgerRowView:
    """台账行的标准字段视图（映射/锚点推算后的内存对象，不落库）。"""

    record_id: str
    biz_type: str
    equipment_no: str | None = None
    name: str | None = None
    category: str | None = None
    location: str | None = None
    department: str | None = None
    owner: str | None = None
    owner_open_id: str | None = None  # person 结构责任人列直取（同应用同号域，@mention 免解析）
    last_date: date | None = None
    cycle_months: int | None = None
    next_date: date | None = None
    status: str = ""
    refill_due: date | None = None
    scrap_due: date | None = None
    register_code: str | None = None
    inspection_category: str | None = None
    agency: str | None = None
    monitor_flag: bool = False

    # 派生口径
    anchor: date | None = None            # 主锚点（next 或 last+周期 推算）
    anchor_source: str = "none"           # next_date / derived / none
    incomplete_reason: str | None = None  # 信息不全原因（编号缺/锚点不可得）
    columns: dict[str, str] = field(default_factory=dict)  # 本表实际列映射快照

    @property
    def active(self) -> bool:
        return is_active_status(self.status)

    @property
    def equipment_label(self) -> str:
        """展示/分组用设备标签：编号优先，缺编号回退名称，再缺回退记录 ID。"""
        return self.equipment_no or self.name or self.record_id

    def anchor_value(self, anchor_field: str) -> date | None:
        """指定锚点字段的当前值（主锚点含推算降级，消防特有锚点直读）。"""
        if anchor_field == "next_date":
            return self.anchor
        return getattr(self, anchor_field, None)


def _owner_person(fields: dict[str, Any], column: str | None) -> tuple[str | None, str | None]:
    """责任人列取值 (name, open_id)：真实表该列可能是 person 型
    （[{"id": "ou_…", "name": …}]，id 与平台同应用同号域可直取）也可能是
    文本型（裸字符串，只有 name）。"""
    if not column:
        return None, None
    raw = fields.get(column)
    if isinstance(raw, str):
        name = raw.strip() or None
        return name, None
    info = bd_fields.person_info(raw)
    name = (info.get("name") or "").strip() or None
    open_id = (info.get("id") or "").strip() or None
    return (name or open_id) or None, open_id


def to_view(
    record: dict[str, Any],
    biz_type: str,
    *,
    columns: dict[str, str] | None = None,
) -> LedgerRowView:
    """一条 Bitable 记录 → 标准视图（columns 由调用方按表头预解析后传入，
    缺省时用本行字段名现解析——单行事件闭环通道用）。"""
    fields = record.get("fields") or {}
    if columns is None:
        columns = resolve_columns(list(fields.keys()))
    record_id = str(record.get("record_id") or "")
    owner_name, owner_open_id = _owner_person(fields, columns.get("owner"))

    view = LedgerRowView(
        record_id=record_id,
        biz_type=biz_type,
        columns=dict(columns),
        equipment_no=bd_fields.text(fields, columns.get("equipment_no") or ""),
        name=bd_fields.text(fields, columns.get("name") or ""),
        category=bd_fields.select(fields, columns.get("category") or ""),
        location=bd_fields.text(fields, columns.get("location") or ""),
        department=bd_fields.select(fields, columns.get("department") or ""),
        owner=owner_name,
        owner_open_id=owner_open_id,
        last_date=_as_date(fields, columns.get("last_date")),
        cycle_months=_as_int(fields, columns.get("cycle_months")),
        next_date=_as_date(fields, columns.get("next_date")),
        status=_status_value(fields, columns.get("status")),
        refill_due=_as_date(fields, columns.get("refill_due")),
        scrap_due=_as_date(fields, columns.get("scrap_due")),
        register_code=bd_fields.text(fields, columns.get("register_code") or ""),
        inspection_category=bd_fields.select(fields, columns.get("inspection_category") or ""),
        agency=bd_fields.text(fields, columns.get("agency") or ""),
        monitor_flag="是" in (bd_fields.select(fields, columns.get("monitor_flag") or "") or ""),
    )

    # 主锚点：next 优先 → last+周期推算 → 不可得（信息不全）
    if view.next_date is not None:
        view.anchor = view.next_date
        view.anchor_source = "next_date"
    elif view.last_date is not None and view.cycle_months:
        view.anchor = _shift_months(view.last_date, view.cycle_months)
        view.anchor_source = "derived"
    else:
        view.anchor = None
        view.anchor_source = "none"

    # 编号/名称合成（2026-10-20 灭火器台账拍板）：真实表可无编号/名称列——
    # 行标识本就是 record_id，二者仅展示用；编号合成 `类别·位置` 链条兜到
    # record_id，「缺编号」不再进信息不全清单、不阻塞派发。
    if not view.name:
        view.name = (view.category or "").strip() or None
    if not view.equipment_no:
        parts = [x for x in (view.category, view.location) if x]
        view.equipment_no = "·".join(parts) or view.name or view.record_id

    # 信息不全判定（主锚点不可得；编号已合成必有值）
    reasons: list[str] = []
    if view.anchor is None:
        reasons.append("缺下次日期且无法由上次日期+周期推算")
    view.incomplete_reason = "；".join(reasons) or None

    return view


def to_views(records: list[dict[str, Any]], biz_type: str) -> list[LedgerRowView]:
    """全表记录 → 视图列表（表头=全表字段名并集，一次性解析映射）。"""
    headers: list[str] = []
    seen: set[str] = set()
    for r in records:
        for k in (r.get("fields") or {}).keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)
    columns = resolve_columns(headers)
    return [to_view(r, biz_type, columns=columns) for r in records]


@dataclass(frozen=True)
class LedgerSummary:
    """台账页 summary（三态信封 live 态的统计组）。"""

    total: int = 0
    active: int = 0
    overdue: int = 0
    due_30d: int = 0
    incomplete: int = 0

    @staticmethod
    def build(views: list[LedgerRowView], today: date) -> LedgerSummary:
        active_rows = [v for v in views if v.active]
        overdue = due30 = 0
        for v in active_rows:
            anchor = v.anchor
            if anchor is None:
                continue
            if anchor < today:
                overdue += 1
            elif (anchor - today).days <= 30:
                due30 += 1
        return LedgerSummary(
            total=len(views),
            active=len(active_rows),
            overdue=overdue,
            due_30d=due30,
            incomplete=sum(1 for v in views if v.incomplete_reason),
        )
