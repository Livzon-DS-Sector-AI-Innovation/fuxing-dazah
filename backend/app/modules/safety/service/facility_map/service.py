"""pins 服务编排：四路读取器（可注入替身）→ 三路降级聚合。

读取器约定（构造注入，测试替身同形；全部返回**已归一**的浅 dict，
平台字段解析在各默认适配器内完成）：
- ticket_reader(date) -> list[dict]     作业票 {ticket_type/ticket_no/
                                        work_site/work_content}（parser 产物）
- fire_reader(date) -> list[dict]       消防报警 {alarm_time/alarm_type/
                                        location/building}
- central_reader(date) -> list[dict]    中控报警 {alarm_date/
                                        alarm_description/workshop/line}
- key_risk_reader(date) -> list[dict]   关键风险作业 {report_no/apply_status/
                                        area/operation_content/start_time}
                                        （当日已通过+审批中，start_time 落日）
- over_limit_reader(date) -> list[dict] 超储物料 {material_name/department/
                                        storage_location/total_quantity_t/
                                        max_limit/unit}（当前态快照，
                                        仅 target=今日时返回，历史日零贡献）
- hazard_reader(date) -> dict           隐患双口径 {"new": […], "open": […]}
                                        {hazard_no/hazard_desc/hazard_level/
                                        progress}——new=检查日期落日（任意
                                        历史日可得，日事件）；open=未闭环
                                        （当前态快照，仅 target=今日时非空）
- fire_ext_reader(date) -> list[dict]   消防设施到期 {location/workshop/
                                        ext_type/ext_count/due_date/
                                        is_overdue}（当前态快照，仅 target=
                                        今日时返回；到期/临期 30 天口径对齐
                                        facilities LedgerSummary）
- map_rows() -> list[dict]              location_district_map 行
                                        （location_text/dist_id）

单路失败 → errors 记一条、该路零贡献，不拖垮响应（总览「单域故障不影响
其他区块」惯例）。映射表失败时票/报警全部进 unmapped（文本可见可解释）。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select

from app.modules.safety.models.location_district_map import LocationDistrictMap
from app.modules.safety.service.facility_map.mapping import (
    build_match_index,
)
from app.modules.safety.service.facility_map.pins import aggregate_pins

logger = logging.getLogger(__name__)

__all__ = [
    "FacilityMapPinsService",
    "bj_today",
    "fire_ext_due_rows",
    "hazard_rows_for_day",
    "open_pins_service",
]

Readers = tuple[
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[], Any],
]

_SOURCE_LABELS = (
    "作业票", "消防报警", "中控报警", "关键风险作业", "超储物料",
    "隐患", "消防设施到期", "分区映射表",
)


def bj_today() -> date:
    """北京时间今日（pins 缺省日期）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


class FacilityMapPinsService:
    """GET /safety/facility-map/pins 的编排层。"""

    def __init__(self, *, readers: Readers) -> None:
        (
            self._ticket_reader,
            self._fire_reader,
            self._central_reader,
            self._key_risk_reader,
            self._over_limit_reader,
            self._hazard_reader,
            self._fire_ext_reader,
            self._map_rows,
        ) = readers

    async def get_pins(self, target: date) -> dict[str, Any]:
        errors: list[str] = []
        jobs: list[dict[str, Any]] = []
        fires: list[dict[str, Any]] = []
        centrals: list[dict[str, Any]] = []
        key_risks: list[dict[str, Any]] = []
        over_limits: list[dict[str, Any]] = []
        hazards_new: list[dict[str, Any]] = []
        hazards_open: list[dict[str, Any]] = []
        fire_ext_dues: list[dict[str, Any]] = []
        map_rows: list[dict[str, Any]] = []

        async def _gather(label: str, fn: Any, *args: Any) -> Any:
            try:
                return await fn(*args)
            except Exception as exc:  # noqa: BLE001 单路降级
                logger.warning("pins 数据源[%s]拉取失败: %s", label, exc)
                errors.append(f"{label}拉取失败: {str(exc)[:120]}")
                return None

        raw_tickets = await _gather(_SOURCE_LABELS[0], self._ticket_reader, target)
        if raw_tickets:
            jobs = raw_tickets
        fires_raw = await _gather(_SOURCE_LABELS[1], self._fire_reader, target)
        if fires_raw:
            fires = fires_raw
        centrals_raw = await _gather(_SOURCE_LABELS[2], self._central_reader, target)
        if centrals_raw:
            centrals = centrals_raw
        key_risks_raw = await _gather(_SOURCE_LABELS[3], self._key_risk_reader, target)
        if key_risks_raw:
            key_risks = key_risks_raw
        over_limits_raw = await _gather(_SOURCE_LABELS[4], self._over_limit_reader, target)
        if over_limits_raw:
            over_limits = over_limits_raw
        hazards_raw = await _gather(_SOURCE_LABELS[5], self._hazard_reader, target)
        if hazards_raw:
            hazards_new = hazards_raw.get("new") or []
            hazards_open = hazards_raw.get("open") or []
        fire_ext_raw = await _gather(_SOURCE_LABELS[6], self._fire_ext_reader, target)
        if fire_ext_raw:
            fire_ext_dues = fire_ext_raw
        rows = await _gather(_SOURCE_LABELS[7], self._map_rows)
        if rows:
            map_rows = rows

        index = build_match_index(map_rows)
        aggregated = aggregate_pins(
            jobs=jobs,
            fires=fires,
            centrals=centrals,
            key_risks=key_risks,
            over_limits=over_limits,
            hazards_new=hazards_new,
            hazards_open=hazards_open,
            fire_ext_dues=fire_ext_dues,
            index=index,
        )
        return {
            "date": target.isoformat(),
            "pins": aggregated["pins"],
            "unmapped": aggregated["unmapped"],
            "errors": errors,
        }


def _default_ticket_reader() -> Callable[[date], Any]:
    """平台票原始记录 → parser 归一化 job dict（work_site 为作业地点显示值）。"""

    async def read(target: date) -> list[dict[str, Any]]:
        from app.modules.safety.workticket_review.client import (
            WorkTicketPlatformClient,
        )
        from app.modules.safety.workticket_review.parser import WorkTicketParser

        async with WorkTicketPlatformClient() as client:
            records = await client.list_tickets_for_date(target)
        parser = WorkTicketParser()
        return [
            {
                "ticket_type": ticket.ticket_type,
                "ticket_no": ticket.ticket_no,
                "work_site": ticket.work_site,
                "work_content": ticket.work_content,
            }
            for ticket in (
                parser.normalize(record, record.get("type") or "")
                for record in records
            )
        ]

    return read


def _default_fire_reader() -> Callable[[date], Any]:
    async def read(target: date) -> list[dict[str, Any]]:
        from app.modules.safety.service.fire_alarm.query import (
            query_fire_alarms_direct,
        )

        result = await query_fire_alarms_direct(
            date_from=target, date_to=target, page_size=1000
        )
        # query_fire_alarms_direct 的 items 已是 _view_to_dict 产物
        # （alarm_time 为 isoformat 字符串），此处只挑 pins 所需四键。
        return [
            {
                "alarm_time": item.get("alarm_time"),
                "alarm_type": item.get("alarm_type"),
                "location": item.get("location"),
                "building": item.get("building"),
            }
            for item in result.get("items") or []
        ]

    return read


def _default_central_reader() -> Callable[[date], Any]:
    async def read(target: date) -> list[dict[str, Any]]:
        from zoneinfo import ZoneInfo

        from app.modules.safety.service.central_alarm.query import (
            query_central_alarms_direct,
        )

        result = await query_central_alarms_direct(
            date_from=target, date_to=target, page_size=1000
        )
        bj = ZoneInfo("Asia/Shanghai")
        return [
            {
                # alarm_date 为 tz-aware UTC，转北京时区再取自然日
                "alarm_date": (
                    view.alarm_date.astimezone(bj).date().isoformat()
                    if view.alarm_date
                    else None
                ),
                "alarm_description": view.alarm_description,
                "workshop": view.workshop,
                "line": view.line,
            }
            for view in result.items
        ]

    return read


def _default_key_risk_reader(session: Any) -> Callable[[date], Any]:
    """关键风险作业（Bitable 直读/镜像）→ 归一 dict；区域文本=area。

    当日口径与总览卡一致：start_time 落目标日 + 状态已通过/审批中。
    """

    async def read(target: date) -> list[dict[str, Any]]:
        from app.modules.safety.service.key_risk_operation_report import (
            KeyRiskOperationReportService,
        )

        service = KeyRiskOperationReportService(session)
        items, _total = await service.get_reports(
            0, 500, date_from=target, date_to=target
        )
        out: list[dict[str, Any]] = []
        for it in items:
            if getattr(it, "apply_status", None) not in ("已通过", "审批中"):
                continue
            start_time = getattr(it, "start_time", None)
            out.append(
                {
                    "report_no": getattr(it, "report_no", None),
                    "apply_status": getattr(it, "apply_status", None),
                    "area": getattr(it, "area", None),
                    "operation_content": getattr(it, "operation_content", None),
                    "start_time": (
                        start_time.isoformat() if start_time is not None else None
                    ),
                }
            )
        return out

    return read


def _default_over_limit_reader(session: Any) -> Callable[[date], Any]:
    """超储物料（当前态快照）→ 归一 dict；位置文本=storage_location。

    库存是当前状态不是当日事件：仅 target=北京时间今日时返回数据，
    历史日期零贡献（AI 建议扫描回溯近 N 天时不会被同一批文本灌水）。
    """

    async def read(target: date) -> list[dict[str, Any]]:
        if target != bj_today():
            return []
        from app.modules.safety.service import ChemicalInventoryService

        service = ChemicalInventoryService(session)
        return await service.get_over_limit_materials(limit=200)

    return read


# ── 第七路：隐患（同源双口径）─────────────────────────────────────────
# 闭环判定（2026-10-27 真表探针拍板）：用「整改状态」单选列（实测 distinct
# {已关闭:2353, 未关闭:38, 整改中:2}），≠已关闭=未闭环——与 hazard_direct
# COND_OPEN / count_hazards.unclosed 全库既有口径一致；「目前进展」实测为
# 自由文本（已完成/已整改/施工说明…），不是枚举，不作判定依据。
def hazard_rows_for_day(
    views: list[Any], target: date, today: date
) -> dict[str, list[dict[str, Any]]]:
    """全量 HazardView → {"new": […], "open": […]}。

    - new：检查日期（discovered_at，UTC）+8h 落 target 日——日事件，任意
      历史日可得（AI 建议扫描逐日回溯的料就来自这里）；
    - open：整改状态≠已关闭——当前态快照，仅 target=今日时返回（历史日
      零贡献，防近 30 天扫描被同一批静态行重复灌水）。
    """

    def _row(v: Any) -> dict[str, Any]:
        return {
            "hazard_no": (v.hazard_no or "").strip() or None,
            "hazard_desc": v.description or "",
            "hazard_level": v.hazard_level or v.hazard_level_manual or None,
            "progress": (v.progress_note or "").strip() or None,
        }

    new_rows: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    is_today = target == today
    for v in views:
        if v.discovered_at is not None and (
            (v.discovered_at + timedelta(hours=8)).date() == target
        ):
            new_rows.append(_row(v))
        if is_today and v.rectification_status != "closed":
            open_rows.append(_row(v))
    return {"new": new_rows, "open": open_rows}


def _default_hazard_reader() -> Callable[[date], Any]:
    """隐患主表全量（TTL 缓存与台账/总览共用）→ 双口径行；位置文本=隐患描述。"""

    async def read(target: date) -> dict[str, list[dict[str, Any]]]:
        from app.modules.safety.service.hazard_direct.reader import open_reader

        views = await open_reader().fetch_all()
        return hazard_rows_for_day(views, target, bj_today())

    return read


# ── 第八路：消防设施到期（当前态快照）─────────────────────────────────
# 到期口径对齐 facilities LedgerSummary：到期日期 ≤ 今日=已到期，
# ≤ 今日+30 天=临期（is_overdue 区分），只取这两态；停用/报废行剔除。
FIRE_EXT_SOON_DAYS = 30

# 公式日期列（实测 1331/1331 行普通「到期日期」列均有 int 值，公式列
# {'type':5,'value':[毫秒时间戳]} 为同值冗余；普通列缺值时才解包回退）
_FIRE_FORMULA_DATE_KEYS = ("到期日期（公式自动生成）",)


def _formula_date(fields: dict[str, Any], key: str) -> date | None:
    """公式日期列 {'type':5,'value':[ms]} → 北京日期（底座 datetime_ms 不认 dict）。"""
    raw = fields.get(key)
    if isinstance(raw, dict):
        value = raw.get("value")
        raw = value[0] if isinstance(value, (list, tuple)) and value else value
    if raw is None or isinstance(raw, bool):
        return None
    try:
        millis = int(raw)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(millis / 1000.0, tz=UTC)
    except (OSError, ValueError, OverflowError):
        return None
    return (dt + timedelta(hours=8)).date()


def fire_ext_due_rows(
    records: list[dict[str, Any]], today: date
) -> list[dict[str, Any]]:
    """fire_equipment_ledger 原始记录 → 到期/临期行（当前态）。

    列名经 facilities resolve_columns 解析（到期日期→next_date 等标准位），
    车间/位置/灭火器类型/数量为本路特有列直读。
    """
    from app.modules.safety.facilities.ledger import BIZ_FIRE, to_views
    from app.modules.safety.service.bitable_direct import fields as bd_fields

    views = to_views(records, BIZ_FIRE)
    soon_bound = today + timedelta(days=FIRE_EXT_SOON_DAYS)
    out: list[dict[str, Any]] = []
    for view, record in zip(views, records):
        if not view.active:
            continue
        fields = record.get("fields") or {}
        due = view.next_date
        if due is None:
            for key in _FIRE_FORMULA_DATE_KEYS:
                due = _formula_date(fields, key)
                if due is not None:
                    break
        if due is None or due > soon_bound:
            continue
        workshop = bd_fields.select(fields, "车间") or None
        location = bd_fields.text(fields, "位置") or None
        raw_count = fields.get("数量")
        try:
            ext_count = int(raw_count) if raw_count is not None else None
        except (TypeError, ValueError):
            ext_count = None
        out.append({
            "location": location,
            "workshop": workshop,
            "ext_type": bd_fields.select(fields, "灭火器类型") or None,
            "ext_count": ext_count,
            "due_date": due.isoformat(),
            "is_overdue": due <= today,
        })
    return out


def _default_fire_ext_reader() -> Callable[[date], Any]:
    """消防器材台账（当前态快照）→ 到期/临期行。

    台账是当前状态不是当日事件：仅 target=北京时间今日时返回数据，
    历史日期零贡献（同超储/未整改隐患的防灌水约定）。
    """

    async def read(target: date) -> list[dict[str, Any]]:
        if target != bj_today():
            return []
        from app.modules.safety.facilities.ledger import BIZ_FIRE
        from app.modules.safety.facilities.reader import resolve_client
        from app.modules.safety.service.bitable_direct import reader as bd_reader

        client = resolve_client(BIZ_FIRE)
        records = await bd_reader.fetch_all_records(
            client, field_names=None, page_size=bd_reader.DEFAULT_PAGE_SIZE,
            strict=True,
        )
        return fire_ext_due_rows(records, bj_today())

    return read


def _default_map_rows(session: Any) -> Callable[[], Any]:
    async def read() -> list[dict[str, Any]]:
        result = await session.execute(
            select(LocationDistrictMap.location_text, LocationDistrictMap.dist_id)
            .where(LocationDistrictMap.is_deleted.is_(False))
            .order_by(LocationDistrictMap.location_text)
        )
        return [
            {"location_text": text, "dist_id": dist_id}
            for text, dist_id in result.all()
        ]

    return read


def open_pins_service(*, session: Any = None) -> FacilityMapPinsService:
    """生产装配：七路数据默认读取器 + DB 映射表读取器。"""
    return FacilityMapPinsService(
        readers=(
            _default_ticket_reader(),
            _default_fire_reader(),
            _default_central_reader(),
            _default_key_risk_reader(session),
            _default_over_limit_reader(session),
            _default_hazard_reader(),
            _default_fire_ext_reader(),
            _default_map_rows(session),
        )
    )
