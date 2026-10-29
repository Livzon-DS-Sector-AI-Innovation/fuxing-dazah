"""检查未整改隐患 — 督办通报「外审节」（未关闭即红色预警，2026-10-21 拍板）。

通报内同级栏头（格式一致，顺序即列示顺序）：
- **公司内检查未整改隐患**：主表督办数据，由 ``bulletin.build_bulletin``
  直接渲染（不经本模块，无独立数据源）；
- **管委会检查未整改隐患**：本模块直读江阴管委会安全检查缺陷项汇总表；
- **重大隐患**（栏头定名 2026-10-29 拍板，即省应急局检查缺陷项）：本模块直读
  福建省应急局安全检查缺陷项汇总表（2026-10-29 接入；字段差异：方案列叫
  「目前进展」、无目标完成日期列，经 ``SourceSpec`` 覆盖）。

展示名 2026-10-22/29 定稿「{源名}未整改隐患」，域名/文件名仍为
external_audit 不动——registry 键是 DB 播种配置，改名断源。

纯只读：无事件订阅、无缓存，随督办通报每周四拉一次 + 值守轮询。

拍板口径：
- **未关闭 = 红色预警**（唯一规则，不看目标期限、不看等级字段——检查表也没有）；
- **整改中不预警**（2026-10-22 拍板，与主表同口径）：「整改状态=整改中」不进
  明细、不计入未整改，仅收口行计数——主表对 in_progress 是整条不通报；
- **已关闭不再追踪**：明细不列，仅统计行计数；
- 并入 ``hazard_bulletin`` 速递格子（不新增格子），本模块只负责取数与渲染，
  组装见 ``bulletin.build_bulletin``。

关闭判定**只看「整改状态」字段**（实测存在「未关闭但已填实际完成时间」的行，
日期字段不可作关闭依据）；三态映射：「已关闭」→closed、「整改中」→
in_progress、空/异常值从宽视为未关闭（字段默认值即未关闭，不漏报）。

@ 提及直取记录「责任人」人员字段自带的 open_id（读取应用作用域，与卡片 @
同源，无需 identity 解析——对齐 ``bulletin._harvest_person_ids`` 口径）。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError

logger = logging.getLogger(__name__)

# 北京时区（Bitable 日期字段按北京日界填写，UTC datetime 直接 .date() 会早一天）
_BJ = timezone(timedelta(hours=8))

# 外审缺陷项汇总表字段（field_names 投影，只请求本节消费的列）
F_SEQ = "序号"
F_DESC = "缺陷项描述"
F_PLAN = "整改方案"
F_DEPT = "隐患部门"
F_STATUS = "整改状态"
F_CHECKED_AT = "检查时间"
F_TARGET = "目标完成日期"
F_RESPONSIBLE = "责任人"

STATUS_CLOSED = "已关闭"
STATUS_IN_PROGRESS = "整改中"

# registry 域/kind（bitable_config 配置中心；registry 默认连接即生产表）
DOMAIN = "external_audit_hazard"


@dataclass(frozen=True)
class SourceSpec:
    """一个外审检查源（kind + 展示名 + 字段覆盖）。

    字段名与管委会表不同的源只覆盖差异项：省应急局表的方案列叫
    「目前进展」、无目标完成日期列。
    """

    kind: str
    label: str                              # 收口行/汇总段/速递格标注用名
    plan_field: str = F_PLAN                # 方案/进展列名
    plan_label: str = "方案"                # 明细行前缀
    target_field: str | None = F_TARGET     # 目标完成日期列名（无此列 None）
    title: str = ""                         # 栏头全名（缺省 f"{label}未整改隐患"）

    @property
    def bar_title(self) -> str:
        return self.title or f"{self.label}未整改隐患"


# 检查源清单（顺序即通报节顺序：管委会检查 → 重大隐患；同级的
# 「公司内检查未整改隐患」节由主表数据渲染，见 bulletin，不经本清单）
SOURCE_MGMT = SourceSpec("defect_summary", "管委会检查")
SOURCE_EMERGENCY_BUREAU = SourceSpec(
    "emergency_bureau", "重大隐患",
    plan_field="目前进展", plan_label="进展", target_field=None,
    title="重大隐患",
)
SOURCES: tuple[SourceSpec, ...] = (
    SOURCE_MGMT, SOURCE_EMERGENCY_BUREAU,
)

# 兼容导出：默认源（管委会检查）
KIND = SOURCE_MGMT.kind
SOURCE_LABEL = SOURCE_MGMT.label


def request_fields(spec: SourceSpec) -> tuple[str, ...]:
    """按源拼 field_names 投影（只请求该源消费的列）。"""
    names = [F_SEQ, F_DESC, spec.plan_field, F_DEPT, F_STATUS, F_CHECKED_AT]
    if spec.target_field:
        names.append(spec.target_field)
    names.append(F_RESPONSIBLE)
    return tuple(names)


REQUEST_FIELD_NAMES: tuple[str, ...] = request_fields(SOURCE_MGMT)

_SEP = "━" * 20


@dataclass
class ExternalAuditView:
    """一条外审缺陷项的内存视图（不落库、不参与 ORM）。"""

    record_id: str
    seq: int | None = None
    description: str = ""
    plan: str = ""
    departments: list[str] = field(default_factory=list)
    closed: bool = False
    in_progress: bool = False
    checked_at: date | None = None
    target_date: date | None = None
    responsible: list[tuple[str, str]] = field(default_factory=list)  # (姓名, open_id)


def to_view(
    record: dict[str, Any],
    *,
    plan_field: str = F_PLAN,
    target_field: str | None = F_TARGET,
) -> ExternalAuditView | None:
    """API 记录 → 视图（plan/target 列名按源覆盖，缺列自然为空）。

    无缺陷描述的行跳过（明细无从落地）；「隐患部门」多选取并集为组键，
    空归「未分配部门」。
    """
    fields = record.get("fields") or {}
    desc = (bd_fields.text(fields, F_DESC) or "").strip()
    if not desc:
        return None

    try:
        seq = int(fields.get(F_SEQ)) if fields.get(F_SEQ) is not None else None
    except (TypeError, ValueError):
        seq = None

    checked = bd_fields.datetime_ms(fields, F_CHECKED_AT)
    target = (
        bd_fields.datetime_ms(fields, target_field)
        if target_field else None
    )

    def _bj_date(dt: datetime | None) -> date | None:
        return dt.astimezone(_BJ).date() if dt else None

    responsible: list[tuple[str, str]] = []
    value = fields.get(F_RESPONSIBLE)
    entries = value.get("users") if isinstance(value, dict) else value
    for p in entries or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "")
        if not name:
            continue
        responsible.append((name, str(p.get("id") or p.get("userId") or "")))

    status = bd_fields.select(fields, F_STATUS)
    return ExternalAuditView(
        record_id=str(record.get("record_id") or ""),
        seq=seq,
        description=desc,
        plan=(bd_fields.text(fields, plan_field) or "").strip() if plan_field else "",
        departments=bd_fields.multi(fields, F_DEPT),
        # 三态从宽判定：已关闭/整改中显式识别，其余（空/乱填）视为未关闭（不漏报）
        closed=status == STATUS_CLOSED,
        in_progress=status == STATUS_IN_PROGRESS,
        checked_at=_bj_date(checked),
        target_date=_bj_date(target),
        responsible=responsible,
    )


async def fetch_external_audit(
    spec: SourceSpec = SOURCE_MGMT,
) -> list[ExternalAuditView] | None:
    """全量拉取指定检查源的缺陷项（含已关闭/整改中，供统计计数）。

    Args:
        spec: 检查源（``SOURCES`` 之一，默认管委会检查）。

    Returns:
        None：源未配置/已停用（该源节整体缺席，通报输出与「无该节」基线
        逐字节一致）；strict 拉取失败向上抛，由 ``bulletin._load_external_sections``
        兜底为缺席。
    """
    try:
        client = bd_reader.resolve_client(DOMAIN, spec.kind)
    except BitableConfigError:
        return None
    records = await bd_reader.fetch_all_records(
        client, field_names=request_fields(spec), strict=True,
    )
    views = [
        v for v in (
            to_view(
                r, plan_field=spec.plan_field, target_field=spec.target_field,
            )
            for r in records
        )
        if v is not None
    ]
    logger.info("检查缺陷项直读完成: kind=%s records=%d views=%d",
                spec.kind, len(records), len(views))
    return views


def _dept_label(view: ExternalAuditView) -> str:
    """部门组键：多选并集 + DEPT_NORMALIZE 归一（与内部督办汇总同口径）。"""
    from app.modules.safety.service.hazard_supervision import DEPT_NORMALIZE

    if not view.departments:
        return "未分配部门"
    return "、".join(DEPT_NORMALIZE.get(d, d) for d in view.departments)


def filter_views(
    views: list[ExternalAuditView],
    *,
    department: str | None = None,
    closed: bool | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[ExternalAuditView]:
    """外审缺陷项内存过滤（查询工具与报表导出共用，保持两路口径一致）。

    department 子串匹配多选部门并集；closed=True/False 精确筛选（None=不过滤）；
    keyword 匹配描述或整改方案；date_from/date_to 按检查日期（含当日，ISO）。
    """
    from datetime import date as _date

    rows = views
    if department:
        rows = [v for v in rows if department in "、".join(v.departments)]
    if closed is not None:
        rows = [v for v in rows if v.closed == closed]
    if keyword:
        rows = [v for v in rows if keyword in v.description or keyword in v.plan]
    d_from = _date.fromisoformat(date_from) if date_from else None
    d_to = _date.fromisoformat(date_to) if date_to else None
    if d_from or d_to:
        def _in_window(v: ExternalAuditView) -> bool:
            if v.checked_at is None:
                return False
            if d_from and v.checked_at < d_from:
                return False
            if d_to and v.checked_at > d_to:
                return False
            return True
        rows = [v for v in rows if _in_window(v)]
    return rows


def _record_link(view: ExternalAuditView, app_token: str, table_id: str) -> str:
    if not (view.record_id and app_token and table_id):
        return ""
    url = (
        f"https://j0eukrlohu.feishu.cn/base/{app_token}"
        f"?table={table_id}&record={view.record_id}"
    )
    return f"[📋 查看记录]({url})"


def all_clear_line(stats: dict[str, Any], source_label: str) -> str:
    """单源无未整改时的收口行（build_bulletin 早退分支复用）。

    全部已关闭 → 累计收口；有整改中 → 并陈计数（整改中不预警但如实计数）；
    既无已关闭也无整改中（源缺席/空统计）返回空串。
    """
    closed = int(stats.get("ext_closed") or 0)
    doing = int(stats.get("ext_doing") or 0)
    if not closed and not doing:
        return ""
    if not doing:
        return f"✅ {source_label}已全部关闭（累计 {closed} 条）"
    segs = [f"已关闭 {closed} 条"] if closed else []
    segs.append(f"整改中 {doing} 条")
    return f"✅ {source_label}无未整改项（{'，'.join(segs)}）"


def build_external_section(
    views: list[ExternalAuditView],
    *,
    source_label: str = SOURCE_LABEL,
    plan_label: str = "方案",
    bar_title: str = "",
    app_token: str = "",
    table_id: str = "",
    today: date | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """渲染单源栏头节（markdown 行列表 + 统计，不推送）。

    栏头全名 ``bar_title`` 缺省 ``f"{source_label}未整改隐患"``；未关闭进
    明细按部门分组 @ 责任人；整改中与主表同口径不进明细不计数为未整改
    （仅收口行计数）；已关闭仅计数。目标完成日期纯展示，不做逾期/剩余
    天数判定（拍板：不看目标期限）。
    """
    from app.modules.safety.feishu import mention

    open_views = [v for v in views if not v.closed and not v.in_progress]
    ext_by_dept: dict[str, int] = defaultdict(int)
    for v in open_views:
        ext_by_dept[_dept_label(v)] += 1
    stats: dict[str, Any] = {
        "ext_open": len(open_views),
        "ext_closed": sum(1 for v in views if v.closed),
        "ext_doing": sum(1 for v in views if v.in_progress),
        "ext_depts": len(ext_by_dept),
        "ext_by_dept": dict(ext_by_dept),
    }

    lines: list[str] = [
        _SEP, f"📌 {bar_title or f'{source_label}未整改隐患'}", _SEP,
    ]
    if not open_views:
        clear = all_clear_line(stats, source_label)
        if clear:
            lines.append(clear)
        lines.append("")
        return lines, stats

    today = today or (datetime.now(UTC) + timedelta(hours=8)).date()
    lines.append(
        f"🔴 未关闭 **{len(open_views)}** 条  ·  "
        f"✅ 已关闭 {stats['ext_closed']} 条  ·  "
        f"涉及 **{stats['ext_depts']}** 个部门"
    )
    lines.append("")

    by_dept: dict[str, list[ExternalAuditView]] = defaultdict(list)
    for v in open_views:
        by_dept[_dept_label(v)].append(v)

    def _flat(text: str) -> str:
        return text.replace("\n", " ").replace("\r", " ")

    for dept in sorted(by_dept, key=lambda d: (-len(by_dept[d]), d)):
        # 部门内：检查日期升序（挂账久的在前）→ 序号
        items = sorted(
            by_dept[dept],
            key=lambda v: (v.checked_at or date.max, v.seq or 0),
        )
        count_str = f"（{len(items)}条）" if len(items) > 1 else ""
        dept_open_ids: dict[str, str] = {}
        for v in items:
            for name, pid in v.responsible:
                dept_open_ids.setdefault(name, pid)
        head = f"**{dept}{count_str}**"
        if dept_open_ids:
            head += "　" + "　".join(
                mention.at_tag(n, pid) for n, pid in dept_open_ids.items()
            )
        lines.append(head)

        for idx, v in enumerate(items, 1):
            lines.append(f"**{idx}.** {_flat(v.description)}")
            if v.plan:
                lines.append(f"{plan_label}：{_flat(v.plan)}")
            segs: list[str] = []
            if v.checked_at:
                days = (today - v.checked_at).days
                segs.append(f"检查：{v.checked_at.isoformat()}（{days} 天）")
            if v.target_date:
                segs.append(f"目标：{v.target_date.isoformat()}")
            link = _record_link(v, app_token, table_id)
            if link:
                segs.append(link)
            if segs:
                lines.append("｜".join(segs))
        lines.append("")

    return lines, stats


__all__ = [
    "DOMAIN",
    "KIND",
    "SOURCE_LABEL",
    "SOURCES",
    "SOURCE_MGMT",
    "SOURCE_EMERGENCY_BUREAU",
    "SourceSpec",
    "ExternalAuditView",
    "REQUEST_FIELD_NAMES",
    "all_clear_line",
    "build_external_section",
    "fetch_external_audit",
    "filter_views",
    "request_fields",
    "to_view",
]
