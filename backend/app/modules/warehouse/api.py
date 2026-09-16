"""Warehouse HTTP 路由：只做入参、依赖注入、调用 service、返回统一响应。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.warehouse import dashboard as dashboard_service
from app.modules.warehouse import intelligence as intelligence_service
from app.modules.warehouse import morning_report as morning_report_service
from app.modules.warehouse import plans as plans_service
from app.modules.warehouse import reports as reports_service
from app.modules.warehouse import service
from app.modules.warehouse.models import WarehouseMovement
from app.modules.warehouse.schemas import (
    AlertRecordResponse,
    IntelligenceRuleResponse,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    MaterialCreate,
    MaterialResponse,
    MaterialUpdate,
    MovementCreate,
    MovementResponse,
    OverviewResponse,
    PlanCancel,
    PlanCreate,
    PlanMovementCreate,
    PlanResponse,
    ReplenishmentSuggestionResponse,
    RuleUpdate,
    StockResponse,
    StocktakeCreate,
    StocktakeUpdate,
    SuggestionStatusUpdate,
)
from app.modules.warehouse.system_config_api import system_config_router
from app.modules.warehouse.web_gateway import router as web_agent_router
from app.modules.warehouse.web_quick_register import router as web_quick_register_router
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

router = create_module_router(MODULES_BY_CODE["warehouse"])
router.include_router(system_config_router)
router.include_router(web_agent_router)
router.include_router(web_quick_register_router)


def _clean(value: str | None) -> str | None:
    text = value.strip() if value else ""
    return text or None


# ── 概览 ──


@router.get("/overview", summary="仓储概览统计")
async def get_overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    data = await service.get_overview(db)
    return success_response(OverviewResponse(**data).model_dump(mode="json"))


# ── 驾驶舱 ──


@router.get("/dashboard/summary", summary="驾驶舱：KPI 与规则摘要")
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    return success_response(await dashboard_service.get_summary(db))


@router.get("/dashboard/movement-trend", summary="驾驶舱：出入库趋势（北京时间按天聚合）")
async def dashboard_movement_trend(
    days: int = Query(default=30, ge=1, le=90, description="统计天数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    return success_response(await dashboard_service.get_movement_trend(db, days))


@router.get("/dashboard/stock-distribution", summary="驾驶舱：库存分布（分类/库位类型）")
async def dashboard_stock_distribution(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    return success_response(await dashboard_service.get_stock_distribution(db))


@router.get("/dashboard/low-stock-top", summary="驾驶舱：低库存与呆滞 Top")
async def dashboard_low_stock_top(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    return success_response(await dashboard_service.get_low_stock_top(db, limit))


@router.get("/dashboard/todos", summary="驾驶舱：待办与预警流")
async def dashboard_todos(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    return success_response(await dashboard_service.get_todos(db))


# ── 物料主数据 ──


@router.get("/materials", summary="物料主数据分页列表")
async def list_materials(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    category: str | None = Query(default=None, description="物料分类"),
    keyword: str | None = Query(default=None, description="编码/名称关键词"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:read")),
) -> JSONResponse:
    items, total = await service.list_materials(
        db, page=page, page_size=page_size, category=_clean(category), keyword=_clean(keyword)
    )
    data = [MaterialResponse.model_validate(m).model_dump(mode="json") for m in items]
    return paginated_response(data, page, page_size, total)


@router.post("/materials", status_code=201, summary="新增物料")
async def create_material(
    payload: MaterialCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:create")),
) -> JSONResponse:
    material = await service.create_material(db, payload, user)
    return success_response(
        MaterialResponse.model_validate(material).model_dump(mode="json"), status_code=201
    )


@router.put("/materials/{material_id}", summary="编辑物料")
async def update_material(
    material_id: UUID,
    payload: MaterialUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:update")),
) -> JSONResponse:
    material = await service.update_material(db, material_id, payload, user)
    return success_response(
        MaterialResponse.model_validate(material).model_dump(mode="json")
    )


@router.delete("/materials/{material_id}", summary="删除物料（软删除）")
async def delete_material(
    material_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:delete")),
) -> JSONResponse:
    await service.delete_material(db, material_id, user)
    return success_response(message="删除成功")


# ── 库位 ──


@router.get("/locations", summary="库位列表")
async def list_locations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:read")),
) -> JSONResponse:
    locations = await service.list_locations(db)
    data = [LocationResponse.model_validate(loc).model_dump(mode="json") for loc in locations]
    return success_response(data)


@router.post("/locations", status_code=201, summary="新增库位")
async def create_location(
    payload: LocationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:create")),
) -> JSONResponse:
    location = await service.create_location(db, payload, user)
    return success_response(
        LocationResponse.model_validate(location).model_dump(mode="json"), status_code=201
    )


@router.put("/locations/{location_id}", summary="编辑库位")
async def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:update")),
) -> JSONResponse:
    location = await service.update_location(db, location_id, payload, user)
    return success_response(
        LocationResponse.model_validate(location).model_dump(mode="json")
    )


@router.delete("/locations/{location_id}", summary="删除库位（软删除）")
async def delete_location(
    location_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:delete")),
) -> JSONResponse:
    await service.delete_location(db, location_id, user)
    return success_response(message="删除成功")


# ── 出入库计划单（V2.0 分期A） ──


@router.get("/plans", summary="出入库计划单分页列表")
async def list_plans(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    direction: str | None = Query(default=None, description="inbound/outbound"),
    status: str | None = Query(default=None, description="planned/in_progress/completed/cancelled"),
    keyword: str | None = Query(default=None, description="单号/物料/批次关键词"),
    planned_before: date | None = Query(default=None, description="预计日期不晚于（含未填日期）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:plans:list")),
) -> JSONResponse:
    items, total = await plans_service.list_plans(
        db,
        page=page,
        page_size=page_size,
        direction=_clean(direction),
        status=_clean(status),
        keyword=_clean(keyword),
        planned_before=planned_before,
    )
    data = [PlanResponse.model_validate(p).model_dump(mode="json") for p in items]
    return paginated_response(data, page, page_size, total)


@router.get("/plans/{plan_id}", summary="出入库计划单详情")
async def get_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:plans:list")),
) -> JSONResponse:
    plan = await plans_service.get_plan(db, plan_id)
    return success_response(PlanResponse.model_validate(plan).model_dump(mode="json"))


@router.post("/plans", status_code=201, summary="创建出入库计划单")
async def create_plan(
    payload: PlanCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:plans:create")),
) -> JSONResponse:
    plan = await plans_service.create_plan(db, payload, user)
    return success_response(
        PlanResponse.model_validate(plan).model_dump(mode="json"), status_code=201
    )


@router.post("/plans/{plan_id}/start", summary="开始执行计划单")
async def start_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:plans:update")),
) -> JSONResponse:
    plan = await plans_service.start_plan(db, plan_id, user)
    return success_response(PlanResponse.model_validate(plan).model_dump(mode="json"))


@router.post("/plans/{plan_id}/cancel", summary="取消计划单（必填原因）")
async def cancel_plan(
    plan_id: UUID,
    payload: PlanCancel,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:plans:cancel")),
) -> JSONResponse:
    plan = await plans_service.cancel_plan(db, plan_id, payload.reason, user)
    return success_response(PlanResponse.model_validate(plan).model_dump(mode="json"))


@router.post("/plans/{plan_id}/movement", status_code=201, summary="从计划单生成出入库登记")
async def create_plan_movement(
    plan_id: UUID,
    payload: PlanMovementCreate | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:plans:update")),
) -> JSONResponse:
    plan, movement = await plans_service.generate_plan_movement(db, plan_id, payload, user)
    return success_response(
        {
            "plan": PlanResponse.model_validate(plan).model_dump(mode="json"),
            "movement": MovementResponse.model_validate(movement).model_dump(mode="json"),
        },
        status_code=201,
    )


# ── 智能中心（分期B） ──


@router.get("/intelligence/rules", summary="预警规则列表")
async def list_intelligence_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:read")),
) -> JSONResponse:
    rules = await intelligence_service.list_rules(db)
    data = [IntelligenceRuleResponse.model_validate(r).model_dump(mode="json") for r in rules]
    return success_response(data)


@router.put("/intelligence/rules/{rule_key}", summary="修改预警规则（阈值/启停）")
async def update_intelligence_rule(
    rule_key: str,
    payload: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:update")),
) -> JSONResponse:
    rule = await intelligence_service.update_rule(db, rule_key, payload, user)
    return success_response(IntelligenceRuleResponse.model_validate(rule).model_dump(mode="json"))


@router.get("/intelligence/rules/{rule_key}/audits", summary="预警规则变更审计")
async def list_intelligence_rule_audits(
    rule_key: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:read")),
) -> JSONResponse:
    audits = await intelligence_service.get_rule_audits(db, rule_key, limit)
    data = [
        {
            "action": a.action,
            "before_json": a.before_json,
            "after_json": a.after_json,
            "operator_name": a.operator_name,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audits
    ]
    return success_response(data)


@router.get("/intelligence/alerts", summary="异常记录分页列表")
async def list_intelligence_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    rule_key: str | None = Query(default=None, description="规则键"),
    status: str | None = Query(default=None, description="open/resolved"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:read")),
) -> JSONResponse:
    items, total = await intelligence_service.list_alert_records(
        db, page=page, page_size=page_size, rule_key=_clean(rule_key), status=_clean(status)
    )
    data = [AlertRecordResponse.model_validate(a).model_dump(mode="json") for a in items]
    return paginated_response(data, page, page_size, total)


@router.get("/intelligence/alerts/summary", summary="异常分类 AI 解读（降级安全）")
async def intelligence_alert_summary(
    rule_key: str = Query(..., description="规则键"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:read")),
) -> JSONResponse:
    return success_response(await intelligence_service.get_alert_summary(db, rule_key))


@router.post("/intelligence/alerts/{record_id}/resolve", summary="标记异常已处理")
async def resolve_intelligence_alert(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:update")),
) -> JSONResponse:
    record = await intelligence_service.resolve_alert_record(db, record_id, user)
    return success_response(AlertRecordResponse.model_validate(record).model_dump(mode="json"))


@router.post("/intelligence/scan", summary="手动触发异常扫描")
async def run_intelligence_scan(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:update")),
) -> JSONResponse:
    counts = await intelligence_service.run_intelligence_scan(db)
    return success_response({"counts": counts})


@router.get("/replenishment/suggestions", summary="补货建议分页列表")
async def list_replenishment_suggestions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None, description="pending/handled/ignored"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:replenishment:read")),
) -> JSONResponse:
    items, total = await intelligence_service.list_replenishment_suggestions(
        db, page=page, page_size=page_size, status=_clean(status)
    )
    data = [
        ReplenishmentSuggestionResponse.model_validate(s).model_dump(mode="json")
        for s in items
    ]
    return paginated_response(data, page, page_size, total)


@router.post(
    "/replenishment/suggestions/{suggestion_id}/status",
    summary="处理补货建议（已处理/忽略）",
)
async def update_replenishment_status(
    suggestion_id: UUID,
    payload: SuggestionStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:replenishment:update")),
) -> JSONResponse:
    suggestion = await intelligence_service.set_suggestion_status(
        db, suggestion_id, payload.status, user
    )
    return success_response(
        ReplenishmentSuggestionResponse.model_validate(suggestion).model_dump(mode="json")
    )


# ── 报表中心（分期C） ──


def _xlsx_response(filename: str, content: bytes) -> Response:
    from urllib.parse import quote

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/reports/monthly", summary="出入库月报")
async def report_monthly(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> JSONResponse:
    return success_response(await reports_service.get_monthly_report(db, year, month))


@router.get("/reports/monthly/export", summary="出入库月报导出 Excel")
async def report_monthly_export(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> Response:
    report = await reports_service.get_monthly_report(db, year, month)
    return _xlsx_response(
        f"出入库月报-{year}-{month:02d}.xlsx", reports_service.build_monthly_xlsx(report)
    )


@router.get("/reports/turnover", summary="库存周转率排行")
async def report_turnover(
    days: int = Query(default=30, ge=1, le=365),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> JSONResponse:
    return success_response(await reports_service.get_turnover_ranking(db, days, limit, order))


@router.get("/reports/turnover/export", summary="库存周转率排行导出 Excel")
async def report_turnover_export(
    days: int = Query(default=30, ge=1, le=365),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> Response:
    rows = await reports_service.get_turnover_ranking(db, days, limit, order)
    content = reports_service.build_table_xlsx(
        "周转率排行",
        ["物料编码", "物料名称", "出库数量", "当前库存", "周转率"],
        [[r["material_code"], r["material_name"], r["outbound_qty"],
          r["current_stock"], r["turnover"] or ""] for r in rows],
    )
    return _xlsx_response(f"库存周转率排行-{days}天.xlsx", content)


@router.get("/reports/consumption", summary="物料消耗排名")
async def report_consumption(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> JSONResponse:
    return success_response(await reports_service.get_consumption_ranking(db, days, limit))


@router.get("/reports/consumption/export", summary="物料消耗排名导出 Excel")
async def report_consumption_export(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> Response:
    rows = await reports_service.get_consumption_ranking(db, days, limit)
    content = reports_service.build_table_xlsx(
        "消耗排名",
        ["物料编码", "物料名称", "单位", "出库数量"],
        [[r["material_code"], r["material_name"], r["unit"], r["outbound_qty"]] for r in rows],
    )
    return _xlsx_response(f"物料消耗排名-{days}天.xlsx", content)


@router.get("/reports/stock", summary="当前库存报表")
async def report_stock(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> JSONResponse:
    items, total = await reports_service.get_stock_report(db, page=page, page_size=page_size)
    data = [
        {
            "material_code": s.material_code,
            "material_name": s.material_name,
            "batch_no": s.batch_no,
            "location_name": s.location_name,
            "expiry_date": s.expiry_date.isoformat() if s.expiry_date else None,
            "quantity": float(s.quantity),
        }
        for s in items
    ]
    return paginated_response(data, page, page_size, total)


@router.get("/reports/stock/export", summary="当前库存报表导出 Excel")
async def report_stock_export(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> Response:
    items, _total = await reports_service.get_stock_report(db, page=1, page_size=5000)
    content = reports_service.build_table_xlsx(
        "当前库存",
        ["物料编码", "物料名称", "批次号", "库位", "效期", "数量"],
        [
            [s.material_code, s.material_name, s.batch_no, s.location_name,
             s.expiry_date.isoformat() if s.expiry_date else "", float(s.quantity)]
            for s in items
        ],
    )
    return _xlsx_response("当前库存报表.xlsx", content)


@router.post("/reports/nl-export", summary="AI 自然语言导出")
async def nl_export(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> Response:

    from app.modules.warehouse.agent.llm_client import get_llm_client

    query = str(payload.get("query", "")).strip()
    fallback = payload.get("fallback_filters") or {}
    if not query:
        return JSONResponse(status_code=422, content={"code": 422, "message": "请输入导出条件"})

    # LLM 解析自然语言 → 筛选条件 JSON（白名单字段）
    filters: dict[str, Any] = {}
    try:
        client = get_llm_client()
        prompt = (
            "将以下中文查询解析为 JSON 筛选条件。可用字段："
            "direction(inbound/outbound), material_keyword(str), "
            "days(int,最近N天), min_qty(number,最小数量)。"
            f'只输出 JSON，不要其他内容。查询：{query}'
        )
        data = await client._post_chat(  # noqa: SLF001
            {"model": client.model,
             "messages": [{"role": "user", "content": prompt}],
             "temperature": 0.1}
        )
        import json as json_mod
        raw = data["choices"][0]["message"]["content"].strip()
        # 去掉可能的 markdown 包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0]
        parsed = json_mod.loads(raw)
        for k in ("direction", "material_keyword", "days", "min_qty"):
            if k in parsed:
                filters[k] = parsed[k]
    except Exception:  # noqa: BLE001 — LLM 失败降级
        filters = {}

    if not filters:
        filters = fallback  # 降级到前端提供的筛选

    # 按筛选条件查询 movements
    cn_tz = ZoneInfo("Asia/Shanghai")
    start = datetime.now(cn_tz) - timedelta(days=int(filters.get("days", 30)))
    stmt = select(WarehouseMovement).where(
        WarehouseMovement.is_deleted == False,  # noqa: E712
        WarehouseMovement.occurred_at >= start,
    )
    if filters.get("direction") in ("inbound", "outbound"):
        stmt = stmt.where(WarehouseMovement.direction == filters["direction"])
    if filters.get("material_keyword"):
        kw = f"%{filters['material_keyword']}%"
        stmt = stmt.where(
            (WarehouseMovement.material_code.ilike(kw))
            | (WarehouseMovement.material_name.ilike(kw))
        )
    if filters.get("min_qty") is not None:
        try:
            stmt = stmt.where(WarehouseMovement.quantity >= float(filters["min_qty"]))
        except (ValueError, TypeError):
            pass

    rows = list(await db.execute(stmt.order_by(WarehouseMovement.occurred_at.desc())).scalars().all())
    content = reports_service.build_table_xlsx(
        "导出结果",
        ["单号", "方向", "物料编码", "物料名称", "数量", "单位", "库位", "发生时间"],
        [
            [m.movement_no, m.direction, m.material_code, m.material_name,
             float(m.quantity), m.unit, m.location_name,
             m.occurred_at.strftime("%Y-%m-%d %H:%M")]
            for m in rows
        ],
    )
    resp = _xlsx_response("导出数据.xlsx", content)
    resp.headers["X-Export-Count"] = str(len(rows))
    return resp


@router.get("/reports/briefings", summary="晨报历史列表")
async def list_morning_briefings(
    limit: int = Query(default=30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> JSONResponse:
    items = await morning_report_service.list_briefings(db, limit)
    return success_response(
        [
            {
                "brief_date": b.brief_date.isoformat(),
                "content": b.content,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in items
        ]
    )


@router.get("/reports/briefings/{brief_date}", summary="晨报详情")
async def get_morning_briefing(
    brief_date: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:reports:read")),
) -> JSONResponse:
    briefing = await morning_report_service.get_briefing(db, brief_date)
    if briefing is None:
        return JSONResponse(status_code=404, content={"code": 404, "message": "该日无晨报"})
    return success_response(
        {
            "brief_date": briefing.brief_date.isoformat(),
            "content": briefing.content,
            "created_at": briefing.created_at.isoformat() if briefing.created_at else None,
        }
    )


# ── 库存 ──


@router.get("/stocks", summary="现有库存分页列表")
async def list_stocks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    category: str | None = Query(default=None, description="物料分类"),
    keyword: str | None = Query(default=None, description="物料/批次关键词"),
    location_id: UUID | None = Query(default=None, description="库位ID"),
    batch_no: str | None = Query(default=None, description="批次号（模糊）"),
    expiry_from: date | None = Query(default=None, description="效期起"),
    expiry_to: date | None = Query(default=None, description="效期止"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    items, total = await service.list_stocks(
        db,
        page=page,
        page_size=page_size,
        category=_clean(category),
        keyword=_clean(keyword),
        location_id=location_id,
        batch_no=_clean(batch_no),
        expiry_from=expiry_from,
        expiry_to=expiry_to,
    )
    data = [StockResponse.model_validate(s).model_dump(mode="json") for s in items]
    return paginated_response(data, page, page_size, total)


# ── 出入库 ──


@router.get("/movements", summary="出入库记录分页列表")
async def list_movements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    direction: str | None = Query(default=None, description="inbound/outbound/adjust"),
    source_type: str | None = Query(default=None, description="业务来源"),
    keyword: str | None = Query(default=None, description="单号/物料/批次关键词"),
    location_id: UUID | None = Query(default=None, description="库位ID"),
    material_id: UUID | None = Query(default=None, description="物料ID（详情时间线用）"),
    occurred_from: datetime | None = Query(default=None, description="发生时间起"),
    occurred_to: datetime | None = Query(default=None, description="发生时间止"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:read")),
) -> JSONResponse:
    items, total = await service.list_movements(
        db,
        page=page,
        page_size=page_size,
        direction=_clean(direction),
        source_type=_clean(source_type),
        keyword=_clean(keyword),
        location_id=location_id,
        material_id=material_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    data = [MovementResponse.model_validate(m).model_dump(mode="json") for m in items]
    return paginated_response(data, page, page_size, total)


@router.post("/movements", status_code=201, summary="登记出入库")
async def create_movement(
    payload: MovementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    movement = await service.create_movement(db, payload, user)
    return success_response(
        MovementResponse.model_validate(movement).model_dump(mode="json"), status_code=201
    )


@router.delete("/movements/{movement_id}", summary="撤销出入库记录")
async def delete_movement(
    movement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:delete")),
) -> JSONResponse:
    await service.delete_movement(db, movement_id, user)
    return success_response(message="撤销成功")


# ── 盘点 ──


async def _stocktake_response(db: AsyncSession, stocktake_id: UUID) -> dict[str, Any]:
    return await service.build_stocktake_response(db, stocktake_id)


@router.get("/stocktakes", summary="盘点单分页列表")
async def list_stocktakes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None, description="draft/confirmed"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:read")),
) -> JSONResponse:
    items, total = await service.list_stocktakes(
        db, page=page, page_size=page_size, status=_clean(status)
    )
    data = [await _stocktake_response(db, st.id) for st in items]
    return paginated_response(data, page, page_size, total)


@router.get("/stocktakes/{stocktake_id}", summary="盘点单详情")
async def get_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:read")),
) -> JSONResponse:
    return success_response(await _stocktake_response(db, stocktake_id))


@router.post("/stocktakes", status_code=201, summary="创建盘点单")
async def create_stocktake(
    payload: StocktakeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:create")),
) -> JSONResponse:
    stocktake = await service.create_stocktake(db, payload, user)
    return success_response(await _stocktake_response(db, stocktake.id), status_code=201)


@router.put("/stocktakes/{stocktake_id}", summary="填写盘点结果")
async def update_stocktake(
    stocktake_id: UUID,
    payload: StocktakeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:update")),
) -> JSONResponse:
    await service.update_stocktake(db, stocktake_id, payload, user)
    return success_response(await _stocktake_response(db, stocktake_id))


@router.post("/stocktakes/{stocktake_id}/confirm", summary="确认盘点单")
async def confirm_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:confirm")),
) -> JSONResponse:
    await service.confirm_stocktake(db, stocktake_id, user)
    return success_response(await _stocktake_response(db, stocktake_id))


@router.delete("/stocktakes/{stocktake_id}", summary="删除盘点单（仅草稿）")
async def delete_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:delete")),
) -> JSONResponse:
    await service.delete_stocktake(db, stocktake_id, user)
    return success_response(message="删除成功")
