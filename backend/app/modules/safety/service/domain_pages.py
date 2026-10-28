"""四新域页面骨架服务（3.0 四期 1-B）。

四域（goals / training-behavior / facilities / incidents）的只读页面数据骨架：
三态信封 + 蓝本口径统计 + 主台账分页。表结构、统计口径与健康度判据的
唯一事实源是 docs/DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md，
本模块是该文档的可执行翻译——将来接入 = 按蓝本建表 + bitable 配置页补连接，
本模块与页面零改码。

三态（蓝本 §6）：
- 未接入 not_connected：registry 已注册但连接解析失败（BitableConfigError）
  → stats=None、空分页。四域当前常态（连接位空，不播种不订阅）。
- 已接入 live：主表连接有效且读取成功 → 统计按蓝本公式内存计算
  （直读全量，百条量级，无缓存无镜像）。
- 降级 degraded：连接有效但读取异常 → errors 标注，整页仍 200。

副表（非主台账 kind）未配置不算降级：其统计组归 None（前端显示「—」），
主台账与已配置表的统计照常。
副台账（DomainPageSpec.secondary，2026-10-23 S6 违章档案首用）：live 时
随页面全量返回映射行（行数据与统计同一次全量拉回，零额外读取；前端客户
端分页），副表未接入/非 live 为 null——不改变三态语义。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError

logger = logging.getLogger(__name__)

# (domain, kind) -> BitablePageClient；测试注入替身（照 cert_direct 手法）
Opener = Callable[[str, str], Any]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 页面/端点 key（= 前端 menu-config 子项 key），顺序即健康度墙卡序
DOMAIN_PAGE_KEYS = ("training-behavior", "facilities", "incidents")

# 行映射的字段语义（蓝本各表「类型」列的代码侧归类）
# text/enum → str | None；multi → list[str]；person → str | None（姓名）；
# datetime → ISO 字符串 | None；attachment → list[str]（文件名）
FieldType = str  # "text" | "enum" | "multi" | "person" | "datetime" | "attachment"


@dataclass(frozen=True)
class KindSpec:
    """单 kind 的投影与行映射（字段口径 = 蓝本对应字段表）。"""

    kind: str
    fields: tuple[tuple[str, str, FieldType], ...]  # (中文列名, 英文字段, 语义)

    @property
    def field_names(self) -> list[str]:
        return [cn for cn, _en, _t in self.fields]


@dataclass(frozen=True)
class DomainPageSpec:
    """单域页面骨架规格。

    analyze 把各表原始记录归约为统计/健康度需要的数字（唯一计算点，
    build_stats 与 build_health 共用，防两处口径漂移）。
    secondary 为副台账展示（live 时随页面全量返回行，前端客户端分页）：
    约定其 KindSpec 必须同时出现在 extra 里（统计取数与行展示同源同一次
    读取）；None=本域无副台账区块。
    """

    url_key: str
    domain: str  # registry 域 key（下划线风格）
    label: str
    primary: KindSpec
    extra: tuple[KindSpec, ...]
    analyze: Callable[[dict[str, list[dict[str, Any]] | None], date], dict[str, Any]]
    stat_keys: tuple[str, ...]
    metric_template: Callable[[dict[str, Any]], str]
    warn_when: Callable[[dict[str, Any]], bool]
    secondary: KindSpec | None = None


def _bj_today() -> date:
    """北京时间今天（与 overview/daily_digest 同口径）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


# ═══════════════════════════════════════════════════════════════
# 记录取值 helper（原始 Bitable 记录 → 业务值）
# ═══════════════════════════════════════════════════════════════


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("fields") or {}


def _enum(record: dict[str, Any], cn: str) -> str:
    return bd_fields.select(_fields(record), cn) or ""


def _num(record: dict[str, Any], cn: str) -> float:
    raw = bd_fields.text(_fields(record), cn)
    try:
        return float(raw) if raw else 0.0
    except (TypeError, ValueError):
        return 0.0


def _date(record: dict[str, Any], cn: str) -> date | None:
    dt = bd_fields.datetime_ms(_fields(record), cn)
    return (dt + timedelta(hours=8)).date() if dt else None


def _count(rows: list[dict[str, Any]], pred: Callable[[dict[str, Any]], bool]) -> int:
    return sum(1 for r in rows if pred(r))


def _in_year(record: dict[str, Any], cn: str, today: date) -> bool:
    d = _date(record, cn)
    return d is not None and d.year == today.year


def _pct(numerator: int, denominator: int) -> int | None:
    return round(numerator * 100 / denominator) if denominator else None


def _map_row(record: dict[str, Any], spec: KindSpec) -> dict[str, Any]:
    fields = _fields(record)
    row: dict[str, Any] = {"record_id": str(record.get("record_id") or "")}
    for cn, en, ftype in spec.fields:
        if ftype == "multi":
            row[en] = bd_fields.multi(fields, cn)
        elif ftype == "person":
            row[en] = bd_fields.person(fields, cn)
        elif ftype == "datetime":
            dt = bd_fields.datetime_ms(fields, cn)
            row[en] = dt.isoformat() if dt else None
        elif ftype == "attachment":
            row[en] = [
                str(a.get("name") or "") for a in bd_fields.attachments(fields, cn)
            ]
        elif ftype == "enum":
            row[en] = bd_fields.select(fields, cn)
        else:  # text / combined_text
            row[en] = bd_fields.text(fields, cn)
    return row


# ═══════════════════════════════════════════════════════════════
# 四域规格（字段与判据 = DESIGN 蓝本 §2-§5 的可执行翻译）
# ═══════════════════════════════════════════════════════════════

_TRAINING_KIND = KindSpec(
    kind="training",
    fields=(
        ("培训名称", "name", "text"),
        ("培训类别", "category", "enum"),
        ("计划日期", "planned_at", "datetime"),
        ("实施日期", "held_at", "datetime"),
        ("培训形式", "form", "enum"),
        ("组织部门", "department", "multi"),
        ("讲师", "lecturer", "person"),
        ("应到人数", "expected_count", "text"),
        ("实到人数", "actual_count", "text"),
        ("签到表", "attendance_file", "attachment"),
        ("考核方式", "assessment", "enum"),
        ("考核合格人数", "passed_count", "text"),
        ("状态", "status", "enum"),
        ("下次复训日期", "next_retraining_at", "datetime"),
        ("备注", "note", "text"),
    ),
)
_VIOLATION_KIND = KindSpec(
    kind="violation",
    fields=(
        ("违章日期", "occurred_at", "datetime"),
        ("违章人员", "person_name", "person"),
        ("所属单位", "department", "multi"),
        ("违章类别", "category", "enum"),
        ("违章等级", "level", "enum"),
        ("违章描述", "description", "text"),
        ("处理方式", "handling", "enum"),
        ("纠正措施", "corrective_action", "text"),
        ("状态", "status", "enum"),
        ("关联隐患编号", "related_hazard_no", "text"),
        ("定向培训", "retraining_note", "text"),
        ("备注", "note", "text"),
        ("证据附件", "evidence_files", "attachment"),
        ("AI判级建议", "ai_level_suggestion", "text"),
    ),
)
_EQUIPMENT_KIND = KindSpec(
    kind="equipment_ledger",
    fields=(
        ("设备编号", "equipment_no", "text"),
        ("设备名称", "name", "text"),
        ("设备类别", "category", "enum"),
        ("位置/区域", "location", "text"),
        ("责任部门", "department", "multi"),
        ("责任人", "owner", "person"),
        ("投用日期", "in_service_at", "datetime"),
        ("设备状态", "status", "enum"),
        ("安全附件情况", "safety_note", "text"),
        ("规程/说明书", "manual_file", "attachment"),
        ("备注", "note", "text"),
    ),
)
_INSPECTION_KIND = KindSpec(
    kind="inspection_record",
    fields=(
        ("设备编号", "equipment_no", "text"),
        ("设备名称", "equipment_name", "text"),
        ("检验类别", "category", "enum"),
        ("上次检验日期", "last_inspected_at", "datetime"),
        ("检验周期（月）", "cycle_months", "text"),
        ("下次检验日期", "next_inspected_at", "datetime"),
        ("检验机构", "agency", "text"),
        ("检验结果", "result", "enum"),
        ("报告附件", "report_file", "attachment"),
        ("备注", "note", "text"),
    ),
)
_INCIDENT_KIND = KindSpec(
    kind="incident",
    fields=(
        ("事件编号", "incident_no", "text"),
        ("发生日期", "occurred_at", "datetime"),
        ("事发地点", "location", "text"),
        ("事发部门", "department", "multi"),
        ("事件类别", "category", "enum"),
        ("事件等级", "level", "enum"),
        ("事件简述", "description", "text"),
        ("伤亡人数", "casualty_count", "text"),
        ("直接损失（万元）", "direct_loss", "text"),
        ("报告人", "reporter", "person"),
        ("报告日期", "reported_at", "datetime"),
        ("状态", "status", "enum"),
        ("调查报告", "report_file", "attachment"),
        ("备注", "note", "text"),
    ),
)
_CAPA_KIND = KindSpec(
    kind="capa",
    fields=(
        ("关联事件编号", "incident_no", "text"),
        ("措施类型", "type", "enum"),
        ("措施描述", "description", "text"),
        ("责任部门", "department", "multi"),
        ("责任人", "owner", "person"),
        ("完成期限", "deadline", "datetime"),
        ("完成日期", "completed_at", "datetime"),
        ("验证人", "verifier", "person"),
        ("验证结果", "verify_result", "enum"),
        ("状态", "status", "enum"),
        ("备注", "note", "text"),
    ),
)


def _analyze_training(
    tables: dict[str, list[dict[str, Any]] | None], today: date
) -> dict[str, Any]:
    trainings = tables.get("training")
    violations = tables.get("violation")

    cur = [
        r
        for r in (trainings or [])
        if _in_year(r, "计划日期", today) and _enum(r, "状态") != "已取消"
    ]
    done = planned = 0
    retraining_due = 0
    overdue_unplanned = 0
    if trainings is not None:
        done = _count(cur, lambda r: _enum(r, "状态") == "已完成")
        planned = _count(cur, lambda r: _enum(r, "状态") in ("未开始", "进行中", "已完成"))
        for r in trainings:
            next_dt = _date(r, "下次复训日期")
            if next_dt is not None and 0 <= (next_dt - today).days <= 30:
                retraining_due += 1
        for r in cur:
            planned_dt = _date(r, "计划日期")
            if (
                planned_dt is not None
                and planned_dt < today
                and _enum(r, "状态") in ("未开始", "进行中")
            ):
                overdue_unplanned += 1
    exam_rows = (
        [r for r in cur if _enum(r, "考核方式") == "考试"] if trainings is not None else []
    )
    actual_sum = sum(_num(r, "实到人数") for r in exam_rows)
    passed_sum = sum(_num(r, "考核合格人数") for r in exam_rows)
    return {
        "training_rows_present": trainings is not None,
        "training_total": len(cur) if trainings is not None else None,
        "training_done": done if trainings is not None else None,
        "completion_rate": _pct(done, planned) if trainings is not None else None,
        "pass_rate": round(passed_sum * 100 / actual_sum) if actual_sum else None,
        "retraining_due_30d": retraining_due if trainings is not None else None,
        "overdue_unplanned": overdue_unplanned,
        "violation_rows_present": violations is not None,
        "violation_total": len(
            [r for r in (violations or []) if _in_year(r, "违章日期", today)]
        )
        if violations is not None
        else None,
        "violation_open": _count(violations or [], lambda r: _enum(r, "状态") == "纠正中")
        if violations is not None
        else None,
    }


def _analyze_facilities(
    tables: dict[str, list[dict[str, Any]] | None], today: date
) -> dict[str, Any]:
    equipment = tables.get("equipment_ledger")
    inspections = tables.get("inspection_record")

    active = [r for r in (equipment or []) if _enum(r, "设备状态") != "已报废"]
    overdue = due30 = 0
    pass_rate: int | None = None
    if inspections is not None:
        for r in inspections:
            nd = _date(r, "下次检验日期")
            if nd is None:
                continue
            if nd < today:
                overdue += 1
            elif (nd - today).days <= 30:
                due30 += 1
        # 合格率 = 各设备最近一次检验结果为合格的比例
        latest_by_no: dict[str, tuple[date | None, dict[str, Any]]] = {}
        for r in inspections:
            no = bd_fields.text(_fields(r), "设备编号") or ""
            last = _date(r, "上次检验日期")
            current = latest_by_no.get(no)
            if current is None:
                latest_by_no[no] = (last, r)
                continue
            current_last = current[0]
            if current_last is None or (last is not None and last > current_last):
                latest_by_no[no] = (last, r)
        if latest_by_no:
            passed = sum(1 for _d, r in latest_by_no.values() if _enum(r, "检验结果") == "合格")
            pass_rate = _pct(passed, len(latest_by_no))
    return {
        "equipment_rows_present": equipment is not None,
        "equipment_total": len(active) if equipment is not None else None,
        "special_equipment": _count(active, lambda r: _enum(r, "设备类别") == "特种设备")
        if equipment is not None
        else None,
        "inactive_equipment": _count(
            active, lambda r: _enum(r, "设备状态") in ("停用", "维修中")
        )
        if equipment is not None
        else None,
        "inspection_rows_present": inspections is not None,
        "inspection_overdue": overdue if inspections is not None else None,
        "inspection_due_30d": due30 if inspections is not None else None,
        "inspection_pass_rate": pass_rate,
    }


def _analyze_incidents(
    tables: dict[str, list[dict[str, Any]] | None], today: date
) -> dict[str, Any]:
    incidents = tables.get("incident")
    capas = tables.get("capa")

    cur = [r for r in (incidents or []) if _in_year(r, "发生日期", today)]
    investigating_over_30d = 0
    if incidents is not None:
        for r in cur:
            if _enum(r, "状态") != "调查中":
                continue
            occurred = _date(r, "发生日期")
            if occurred is not None and (occurred - today).days < -30:
                investigating_over_30d += 1
    return {
        "incident_rows_present": incidents is not None,
        "incident_total": len(cur) if incidents is not None else None,
        "accident_count": _count(cur, lambda r: _enum(r, "事件类别") == "事故")
        if incidents is not None
        else None,
        "near_miss_count": _count(cur, lambda r: _enum(r, "事件类别") == "未遂事件")
        if incidents is not None
        else None,
        "investigating_count": _count(cur, lambda r: _enum(r, "状态") == "调查中")
        if incidents is not None
        else None,
        "investigating_over_30d": investigating_over_30d if incidents is not None else 0,
        "capa_rows_present": capas is not None,
        "capa_open": _count(capas or [], lambda r: _enum(r, "状态") in ("进行中", "已逾期"))
        if capas is not None
        else None,
        "capa_overdue": _count(capas or [], lambda r: _enum(r, "状态") == "已逾期")
        if capas is not None
        else None,
    }


def _training_metric(a: dict[str, Any]) -> str:
    return (
        f"培训 {a['training_done']}/{a['training_total']} · "
        f"违章 {a['violation_total']}"
        f"（未纠正 {a['violation_open']}）"
    )


def _facilities_metric(a: dict[str, Any]) -> str:
    return (
        f"设备 {a['equipment_total']} 台 · "
        f"检验逾期 {a['inspection_overdue']} · "
        f"30天内到期 {a['inspection_due_30d']}"
    )


def _incidents_metric(a: dict[str, Any]) -> str:
    return (
        f"今年事件 {a['incident_total']} · "
        f"调查中 {a['investigating_count']} · "
        f"CAPA 未闭环 {a['capa_open']}"
    )


_SPECS: tuple[DomainPageSpec, ...] = (
    DomainPageSpec(
        url_key="training-behavior",
        domain="training_behavior",
        label="教育培训与行为管控",
        primary=_TRAINING_KIND,
        extra=(_VIOLATION_KIND,),
        analyze=_analyze_training,
        stat_keys=(
            "training_total", "completion_rate", "pass_rate",
            "retraining_due_30d", "violation_total", "violation_open",
        ),
        metric_template=_training_metric,
        warn_when=lambda a: (a["violation_open"] or 0) > 0 or a["overdue_unplanned"] > 0,
        secondary=_VIOLATION_KIND,  # 副台账：违章行为档案（live 全量行随包返回）
    ),
    DomainPageSpec(
        url_key="facilities",
        domain="facilities",
        label="设备设施管理",
        primary=_EQUIPMENT_KIND,
        extra=(_INSPECTION_KIND,),
        analyze=_analyze_facilities,
        stat_keys=(
            "equipment_total", "special_equipment", "inspection_overdue",
            "inspection_due_30d", "inspection_pass_rate", "inactive_equipment",
        ),
        metric_template=_facilities_metric,
        warn_when=lambda a: (a["inspection_overdue"] or 0) > 0,
        secondary=_INSPECTION_KIND,  # 副台账：检验校验记录（接入后零改码出数）
    ),
    DomainPageSpec(
        url_key="incidents",
        domain="incidents",
        label="事故事件管理",
        primary=_INCIDENT_KIND,
        extra=(_CAPA_KIND,),
        analyze=_analyze_incidents,
        stat_keys=(
            "incident_total", "accident_count", "near_miss_count",
            "investigating_count", "capa_open", "capa_overdue",
        ),
        metric_template=_incidents_metric,
        warn_when=lambda a: (a["capa_overdue"] or 0) > 0
        or a["investigating_over_30d"] > 0,
        secondary=_CAPA_KIND,  # 副台账：CAPA 措施跟踪（接入后零改码出数）
    ),
)

SPECS: dict[str, DomainPageSpec] = {s.url_key: s for s in _SPECS}


def _stats_from(spec: DomainPageSpec, analysis: dict[str, Any]) -> dict[str, Any]:
    """analyze 结果 → 蓝本统计卡字段（analyze 已产出全部最终口径值）。"""
    return {key: analysis.get(key) for key in spec.stat_keys}


def _envelope(
    status: str,
    stats: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    total: int,
    page: int,
    page_size: int,
    errors: list[str],
    secondary_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "stats": stats,
        "ledger": {
            "data": rows,
            "meta": {"total": total, "page": page, "page_size": page_size},
        },
        # 副台账（如 S6 违章档案）：行数据随统计同一次全量拉回，live 时整包
        # 返回（前端客户端分页）；副表未接入/not_connected/degraded 为 None
        "secondary_ledger": {"data": secondary_rows} if secondary_rows is not None else None,
        "errors": errors,
    }


async def build_domain_page(
    url_key: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """单域页面数据（三态信封）。url_key = 前端菜单 key。"""
    spec = SPECS.get(url_key)
    if spec is None:
        raise ValueError(f"未知域页面: {url_key}")
    open_client = opener or bd_reader.resolve_client

    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), MAX_PAGE_SIZE)

    tables: dict[str, list[dict[str, Any]] | None] = {}
    errors: list[str] = []
    for kind_spec in (spec.primary, *spec.extra):
        try:
            client = open_client(spec.domain, kind_spec.kind)
            tables[kind_spec.kind] = await bd_reader.fetch_all_records(
                client, field_names=kind_spec.field_names, strict=True
            )
        except BitableConfigError:
            if kind_spec is spec.primary:
                # 主表未配置 → 整域未接入（蓝本 §6）
                return _envelope("not_connected", None, [], 0, page, page_size, [])
            tables[kind_spec.kind] = None  # 副表未配置：统计组归 None
        except Exception as exc:  # noqa: BLE001 —— 读取失败=降级，不炸端点
            logger.warning("域页面读取降级 %s/%s: %r", spec.domain, kind_spec.kind, exc)
            errors.append(f"{kind_spec.kind}: {type(exc).__name__}")

    if errors:
        return _envelope("degraded", None, [], 0, page, page_size, errors)

    analysis = spec.analyze(tables, _bj_today())
    primary_rows = [_map_row(r, spec.primary) for r in (tables[spec.primary.kind] or [])]
    secondary_rows: list[dict[str, Any]] | None = None
    if spec.secondary is not None and tables.get(spec.secondary.kind) is not None:
        secondary_rows = [
            _map_row(r, spec.secondary)
            for r in (tables[spec.secondary.kind] or [])
        ]
    start = (page - 1) * page_size
    return _envelope(
        "live",
        _stats_from(spec, analysis),
        primary_rows[start : start + page_size],
        len(primary_rows),
        page,
        page_size,
        [],
        secondary_rows=secondary_rows,
    )


async def fetch_kind_rows(
    url_key: str, kind: str, *, opener: Opener | None = None
) -> list[dict[str, Any]] | None:
    """单表全量行（标准字段映射后的行视图）；未接入返回 None。

    包外只读消费方（如 business_agent 培训域工具）复用域页读取与字段
    映射，避免复制映射表；主表/副表/extra 均可按 kind 取。
    """
    spec = SPECS.get(url_key)
    if spec is None:
        raise ValueError(f"未知域页面: {url_key}")
    kind_specs = {k.kind: k for k in (spec.primary, *spec.extra)}
    if spec.secondary is not None:
        kind_specs[spec.secondary.kind] = spec.secondary
    kind_spec = kind_specs.get(kind)
    if kind_spec is None:
        raise ValueError(f"域 {url_key} 无表: {kind}")
    open_client = opener or bd_reader.resolve_client
    try:
        client = open_client(spec.domain, kind_spec.kind)
        records = await bd_reader.fetch_all_records(
            client, field_names=kind_spec.field_names, strict=True
        )
    except BitableConfigError:
        return None
    return [_map_row(r, kind_spec) for r in records]


async def collect_domain_health(
    url_key: str, *, opener: Opener | None = None
) -> dict[str, Any]:
    """总览健康度墙采集器（四新域三态卡数据源）。

    未接入 → {"connected": False}；已接入 → connected + health_status/health_metric
    （蓝本各域 ok/warn 判据）；读取异常向上抛（由 overview gather 归入降级）。
    """
    spec = SPECS.get(url_key)
    if spec is None:
        raise ValueError(f"未知域页面: {url_key}")
    open_client = opener or bd_reader.resolve_client

    try:
        client = open_client(spec.domain, spec.primary.kind)
    except BitableConfigError:
        return {"connected": False}

    tables: dict[str, list[dict[str, Any]] | None] = {}
    for kind_spec in (spec.primary, *spec.extra):
        try:
            client = open_client(spec.domain, kind_spec.kind)
            tables[kind_spec.kind] = await bd_reader.fetch_all_records(
                client, field_names=kind_spec.field_names, strict=True
            )
        except BitableConfigError:
            tables[kind_spec.kind] = None
    analysis = spec.analyze(tables, _bj_today())
    return {
        "connected": True,
        "health_status": "warn" if spec.warn_when(analysis) else "ok",
        "health_metric": spec.metric_template(analysis),
    }


def module_health_card(url_key: str, part: dict[str, Any] | None) -> dict[str, Any]:
    """健康度墙单卡构造（三态：live=ok|warn / 未接入=inactive·未接入 / 降级=inactive·None）。"""
    if part and part.get("connected"):
        return {
            "key": url_key,
            "status": part.get("health_status", "ok"),
            "metric": part.get("health_metric"),
        }
    return {
        "key": url_key,
        "status": "inactive",
        "metric": "未接入" if part else None,
    }
