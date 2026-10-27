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
    "open_pins_service",
]

Readers = tuple[
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[date], Any],
    Callable[[], Any],
]

_SOURCE_LABELS = ("作业票", "消防报警", "中控报警", "关键风险作业", "超储物料", "分区映射表")


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
            self._map_rows,
        ) = readers

    async def get_pins(self, target: date) -> dict[str, Any]:
        errors: list[str] = []
        jobs: list[dict[str, Any]] = []
        fires: list[dict[str, Any]] = []
        centrals: list[dict[str, Any]] = []
        key_risks: list[dict[str, Any]] = []
        over_limits: list[dict[str, Any]] = []
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
        rows = await _gather(_SOURCE_LABELS[5], self._map_rows)
        if rows:
            map_rows = rows

        index = build_match_index(map_rows)
        aggregated = aggregate_pins(
            jobs=jobs,
            fires=fires,
            centrals=centrals,
            key_risks=key_risks,
            over_limits=over_limits,
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
    """生产装配：平台/消防/中控/关键风险/超储物料默认读取器 + DB 映射表读取器。"""
    return FacilityMapPinsService(
        readers=(
            _default_ticket_reader(),
            _default_fire_reader(),
            _default_central_reader(),
            _default_key_risk_reader(session),
            _default_over_limit_reader(session),
            _default_map_rows(session),
        )
    )
