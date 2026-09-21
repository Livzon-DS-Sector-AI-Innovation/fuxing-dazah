"""领料 FIFO 匹配工具（V3.0 分期C，设计 §4.2）。

``create_picking_draft``：车间/仓管员对机器人说领料信息（如「精制一部
领料 硫酸 500Kg」），LLM 从对话收集字段后调用本工具：

- 缺必收字段（物料/领用数量/单位/领用部门——scene 配置
  ``SCENE_CONFIG["picking_outbound"].required_fields``）→ 返回 ``missing``
  + hint，LLM 向用户追问后重调（不猜、不硬写）；
- **FIFO 匹配引擎**（本地现算，无新表）：读 material_stock 该物料
  QA放行=放行 的批次，按入库日期升序生成 1..N 批号建议（跨批拆分）；
  无放行批次（``no_released_batch``）/放行总量不足（``insufficient_stock``，
  附可用总量）→ 明确 error 分支，LLM 如实转告，不建草稿；
- 用户指定批号：校验该批号存在于库存且为放行态——条件放行放行该操作
  但附 warning（风险可见不阻断）；不存在/未放行/量不足 → error；
- 齐全 → draft_flow.create_dialog_draft（scene=picking_outbound，fields
  即 aligned，picking_plan 结构化快照供卡片展示与改批号后重算）→
  send_confirm_card 确认卡片 → 返回 draft_no。确认后的写入由
  ConfirmService 回调 submit_picking 完成（pipeline/submit.py）。

工具上下文/数据库访问模式与 gmp.py 相同：``execute_tool`` 注入 ``_ctx``；
工具内自开事务（``_db_session`` 注入口），校验失败返回 ``{"error": ...}``
不中断 Runner。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.agent.tools.draft_update import map_fields
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_cells import cell_number, cell_text, unwrap
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
    get_table_fields,
)

logger = logging.getLogger(__name__)

# 目标表（读库存明细做匹配；写台账在 submit_picking 的 material_outbound）
PICKING_STOCK_TABLE = "material_stock"

# 无入库日期批次的排序哨兵（升序下排最后：缺日期不等于最早，FIFO 不抢先发）
_SORT_SENTINEL_LAST = 2**62

# 拆分口径（2026-09-21 真机验收定案）：剩余量 <1 的碎批不参与自动建议
# （避免「首批 0.5」式不可操作拆分）；自动建议最多拆 3 批，凑不齐报
# split_limit_exceeded 引导分次领用。常量先于运行参数，有需求再配置化。
MIN_STOCK_QTY = 1.0
MAX_SPLIT_BATCHES = 3

# 领用类型默认值（质询 Round 2 定案：用户不说就默认生产使用；须在选项集内）
PICKING_DEFAULT_USE_TYPE = "生产使用"

# 对话收集字段（canonical 键）→ 展示名（追问/结果回显共用文案）
PICKING_FIELD_LABELS: dict[str, str] = {
    "material": "物料",
    "quantity": "领用数量",
    "unit": "单位",
    "department": "领用部门",
    "use_type": "领用类型",
    "designated_batch": "指定批号",
    "material_name": "物料名称（匹配结果，自动回填）",
    "remark": "备注",
}

# 自由收集的单选字段（选项集未命中降级为 warning，submit 侧 _select_or_skip
# 同口径跳过；领用部门选项集已存在）
PICKING_SOFT_SELECT_FIELDS: dict[str, str] = {
    "department": "领用部门",
    "use_type": "领用类型",
}

# 库存拉取字段（FIFO 匹配 + 建议卡片共用；一律走 bitable_cells 规范解析）
_STOCK_PULL_FIELDS = [
    "物料批号",
    "物料名称",
    "剩余数量",
    "单位",
    "QA放行",
    "入库日期",
    "贮存/槽车取样点",
]

_STOCK_PAGE_SIZE = 500
_STOCK_MAX_PAGES = 5  # 分页上限防御（>2500 条截断，同 QC 扫描防御口径）


class PickingError(ValueError):
    """领料匹配失败（code: no_released_batch / insufficient_stock /
    batch_not_found；message 用户可见，LLM 如实转告）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── 数据库会话注入口（与 gmp.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db

# adapter 进程级单例（gmp.py 同款；测试经 monkeypatch 注入假件）
_adapter: WarehouseBitableAdapter | None = None


def get_adapter() -> WarehouseBitableAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


async def _outbound_table_fields() -> dict[str, FieldMeta]:
    """material_outbound 字段元数据（运行时选项集优先，静态快照兜底）。

    物料批号/领用类型/领用部门均为单选且 Base 侧持续追加选项（静态快照
    批号仅 50 条而实测 1700+）——先 refresh_table_fields 拉最新选项集
    （bitable_schema TTL 缓存内直用），刷新失败回落静态快照。
    """
    try:
        await get_adapter().refresh_table_fields("material_outbound")
    except Exception:  # noqa: BLE001 — 刷新失败回落静态快照，不阻断
        logger.warning("material_outbound 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields("material_outbound")


# ── FIFO 匹配引擎（纯函数，可直测）──


def _parse_inbound_ms(fields: dict[str, Any]) -> int:
    """入库日期排序键（毫秒；缺失/不可解析排最后——新登记可能未填日期）。

    解包统一走 bitable_cells.unwrap（模块契约：禁止各消费方手写解包链）。
    """
    ms = unwrap(fields.get("入库日期"))
    if isinstance(ms, bool) or ms is None:
        return _SORT_SENTINEL_LAST
    if isinstance(ms, (int, float)):
        return int(ms)
    text = str(ms).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(
                datetime.strptime(text[: len(fmt) + 4], fmt)
                .replace(tzinfo=UTC)
                .timestamp()
                * 1000
            )
        except ValueError:
            continue
    return _SORT_SENTINEL_LAST


def _is_released(fields: dict[str, Any]) -> bool:
    """QA放行（lookup 读回数组）是否为「放行」。"""
    return "放行" in [part.strip() for part in cell_text(fields.get("QA放行")).split("、")]


def _batch_item(fields: dict[str, Any], pick_qty: float) -> dict[str, Any]:
    """建议批次条目（卡片展示 + submit 写入共用结构）。"""
    return {
        "batch_no": cell_text(fields.get("物料批号")),
        "pick_qty": pick_qty,
        "stock_qty": cell_number(fields.get("剩余数量")),
        "unit": cell_text(fields.get("单位")),
        "location": cell_text(fields.get("贮存/槽车取样点")),
        "record_id": "",  # 由 fetch 层回填
    }


def fifo_plan(
    stock_records: list[dict[str, Any]], *, quantity: float
) -> list[dict[str, Any]]:
    """库存记录 → FIFO 建议批次列表（入库日期升序、跨批拆分）。

    仅 QA放行=放行 且剩余量 ≥1 的批次参与（碎批过滤，真机验收定案）；
    升序累计扣减，最多拆 :data:`MAX_SPLIT_BATCHES` 批。总量不足抛
    insufficient_stock（附可参与总量）；凑不齐且批次超上限抛
    split_limit_exceeded（引导分次领用）；无放行批次抛 no_released_batch。
    record_id 由调用方从原始记录带入（纯函数只处理 fields 形态时置空）。
    """
    pool: list[tuple[dict[str, Any], str, float]] = []
    for record in stock_records:
        fields = record.get("fields") or {}
        if not _is_released(fields):
            continue
        stock_qty = cell_number(fields.get("剩余数量"))
        if stock_qty is None or stock_qty < MIN_STOCK_QTY:
            continue
        pool.append((fields, str(record.get("record_id") or ""), stock_qty))
    if not pool:
        raise PickingError("no_released_batch", "该物料没有 QA 放行（放行状态）的批次")
    pool.sort(key=lambda triple: _parse_inbound_ms(triple[0]))
    available = sum(stock_qty for _, _, stock_qty in pool)

    plan: list[dict[str, Any]] = []
    remaining = float(quantity)
    for fields, record_id, stock_qty in pool:
        if remaining <= 0:
            break
        if len(plan) >= MAX_SPLIT_BATCHES:
            break
        pick = min(remaining, stock_qty)
        item = _batch_item(fields, pick)
        item["record_id"] = record_id
        plan.append(item)
        remaining -= pick
    if remaining > 1e-9:
        if available < float(quantity) - 1e-9:
            raise PickingError(
                "insufficient_stock",
                f"放行批次可用总量 {available:g}（单位见台账），不足以满足领用 {float(quantity):g}",
            )
        picked_total = float(quantity) - remaining
        raise PickingError(
            "split_limit_exceeded",
            f"放行批次零散：前 {MAX_SPLIT_BATCHES} 批仅能凑齐 {picked_total:g}"
            f"（不足领用 {float(quantity):g}），请分次领用或先在台账合并零散批次",
        )
    return plan


def plan_for_designated_batch(
    stock_records: list[dict[str, Any]], batch_no: str, *, quantity: float
) -> tuple[list[dict[str, Any]], str]:
    """用户指定批号 → 单批次计划（+ 条件放行 warning）。

    批号不存在 → batch_not_found；批次未放行（QA放行 空/否决）→
    no_released_batch；余量不足 → insufficient_stock；条件放行 → 放行
    该操作并附 warning（质询定案：风险可见不阻断）。
    """
    for record in stock_records:
        fields = record.get("fields") or {}
        if cell_text(fields.get("物料批号")) != batch_no.strip():
            continue
        statuses = [p.strip() for p in cell_text(fields.get("QA放行")).split("、")]
        if "放行" not in statuses and "条件放行" not in statuses:
            raise PickingError(
                "no_released_batch", f"批号 {batch_no} 未放行（QA放行={cell_text(fields.get('QA放行')) or '空'}）"
            )
        stock_qty = cell_number(fields.get("剩余数量"))
        if stock_qty is None or stock_qty < float(quantity):
            raise PickingError(
                "insufficient_stock",
                f"批号 {batch_no} 可用量 {stock_qty if stock_qty is not None else 0:g}，不足以领用 {quantity:g}",
            )
        item = _batch_item(fields, float(quantity))
        item["record_id"] = str(record.get("record_id") or "")
        warning = "指定批号为条件放行，请留意放行条件" if "条件放行" in statuses and "放行" not in statuses else ""
        return [item], warning
    raise PickingError("batch_not_found", f"批号 {batch_no} 不在当前库存明细中")


async def fetch_stock_for_picking(adapter: Any, material: str) -> list[dict[str, Any]]:
    """按物料关键词拉取 material_stock（服务端无 keyword 过滤，本地匹配）。

    物料名称为单选/lookup 混合读回形态，规范化后做包含匹配（大小写不敏）。
    """
    keyword = material.strip().lower()
    matched: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(_STOCK_MAX_PAGES):
        page = await adapter.search_records_page(
            PICKING_STOCK_TABLE,
            filter_json=None,
            field_names=_STOCK_PULL_FIELDS,
            limit=_STOCK_PAGE_SIZE,
            page_token=page_token,
        )
        for record in page.get("records") or []:
            fields = record.get("fields") or {}
            name = cell_text(fields.get("物料名称")).lower()
            batch = cell_text(fields.get("物料批号")).lower()
            if keyword in name or keyword in batch:
                matched.append(record)
        page_token = page.get("page_token")
        if not page_token:
            break
    return matched


def _match_option(meta: FieldMeta | None, text: str) -> str | None:
    """单选值适配：大小写归一匹配选项集（命中返回选项原值）；未命中 None。

    未收录字段/非单选/空选项集放行原值（gmp._match_option 同款契约）。
    """
    if meta is None or meta.type != FIELD_TYPE_SELECT:
        return text
    options: tuple[str, ...] = meta.options
    if not options:
        return text
    if text in options:
        return text
    lowered = text.lower()
    for opt in options:
        if opt.lower() == lowered:
            return opt
    return None


def _label(key: str) -> str:
    return PICKING_FIELD_LABELS.get(key, key)


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入）──


async def create_picking_draft(
    fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """创建领料登记草稿（FIFO 匹配 + 确认卡片；用户说领料信息时调用）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    chat_id = str(ctx.get("chat_id") or "") or None
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法创建领料草稿"}
    if not isinstance(fields, dict) or not fields:
        return {
            "error": "fields 不能为空",
            "hint": f"传 {{字段名: 值}}，必收字段：{_label('material')}、{_label('quantity')}、{_label('unit')}、{_label('department')}",
        }

    mapped, unknown = map_fields(fields)
    if unknown:
        return {
            "error": f"不支持的字段: {'、'.join(unknown)}",
            "hint": f"可收集字段：{'、'.join(_label(k) for k in PICKING_FIELD_LABELS)}",
        }

    # LLM 可能传「物料名称」而非「物料」——同义收编为匹配关键词
    if not str(mapped.get("material") or "").strip() and str(
        mapped.get("material_name") or ""
    ).strip():
        mapped["material"] = mapped.pop("material_name")

    # 1. 必收字段（scene 配置）：缺失列 missing 让 LLM 追问，不猜不硬写
    required = draft_flow.SCENE_CONFIG[draft_flow.PICKING_OUTBOUND_SCENE].required_fields
    missing = [
        _label(key)
        for key in required
        if mapped.get(key) is None or not str(mapped.get(key)).strip()
    ]
    if missing:
        return {
            "status": "incomplete",
            "missing": missing,
            "collected": {_label(k): v for k, v in mapped.items() if v is not None},
            "hint": f"请补充：{'、'.join(missing)}（向用户追问后再调用本工具，不要猜测或编造）",
        }

    quantity = mapped.get("quantity")
    try:
        qty = float(str(quantity).strip().replace(",", ""))
    except (TypeError, ValueError):
        return {"error": f"领用数量 {quantity!r} 不是有效数字，请向用户核对"}
    if qty <= 0:
        return {"error": "领用数量必须为正数，请向用户核对"}

    material = str(mapped["material"]).strip()
    designated = str(mapped.get("designated_batch") or "").strip()

    adapter = get_adapter()
    try:
        stock_records = await fetch_stock_for_picking(adapter, material)
        if designated:
            plan, warning = plan_for_designated_batch(stock_records, designated, quantity=qty)
            mapped["designated_batch"] = designated
        else:
            plan = fifo_plan(stock_records, quantity=qty)
            warning = ""
    except PickingError as exc:
        return {"error": exc.message, "error_code": exc.code}

    # FIFO 结果回填 working set（submit 写入来源；改批号后 update_draft 重算）。
    # 物料名称取建议首批所在库存行的规范值（建议为空不会到达这里）。
    if plan:
        first_id = plan[0].get("record_id")
        first_fields = next(
            (
                record.get("fields") or {}
                for record in stock_records
                if str(record.get("record_id") or "") == first_id
            ),
            {},
        )
        mapped["material_name"] = cell_text(first_fields.get("物料名称"))
    mapped["picking_plan"] = plan
    if warning:
        mapped["picking_warning"] = warning

    table_fields = await _outbound_table_fields()

    # 单选软校验：领用类型缺省生产使用；部门/类型选集未命中附 warning（不阻断）
    warnings: list[str] = []
    use_type_raw = str(mapped.get("use_type") or "").strip() or PICKING_DEFAULT_USE_TYPE
    mapped["use_type"] = use_type_raw
    for key, field_name in PICKING_SOFT_SELECT_FIELDS.items():
        value = mapped.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        meta = table_fields.get(field_name)
        adapted = _match_option(meta, text)
        if adapted is not None:
            mapped[key] = adapted
        elif meta is not None and meta.options:
            warnings.append(
                f"{_label(key)}「{text}」不在系统选项列表，提交时需人工在 Base 补填"
            )
            mapped[key] = text

    # 2. 齐全 → 对话草稿（created→aligned）→ 确认卡片
    try:
        async with _db_session() as db:
            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.PICKING_OUTBOUND_SCENE,
                fields=mapped,
                open_id=open_id,
                chat_id=chat_id,
            )
            await draft_flow.send_confirm_card(
                db, draft, chat_id=chat_id, open_id=open_id
            )
            draft_no = draft.draft_no
            status = draft.status
    except Exception as exc:  # noqa: BLE001 — 创建失败不中断 Runner
        logger.exception("领料登记草稿创建失败: open_id=%r", open_id)
        return {"error": f"领料登记草稿创建失败: {type(exc).__name__}: {exc}"}

    all_warnings = warnings + ([warning] if warning else [])
    logger.info(
        "领料登记草稿已创建: draft_no=%s batches=%s warnings=%s",
        draft_no,
        [item["batch_no"] for item in plan],
        all_warnings,
    )
    return {
        "status": status,
        "draft_no": draft_no,
        "picking_plan": plan,
        "fields": {k: v for k, v in mapped.items() if k != "picking_plan"},
        "warnings": all_warnings,
        "message": (
            f"已创建领料登记草稿 {draft_no} 并发送确认卡片（10 分钟内有效）。"
            f"FIFO 建议：{'、'.join(item['batch_no'] + ' x' + format(item['pick_qty'], 'g') for item in plan)}。"
            "请提醒用户核对后点「确认领料」。"
        ),
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

PICKING_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "create_picking_draft": create_picking_draft,
}

PICKING_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_picking_draft",
            "description": (
                "创建领料登记草稿并做先进先出（FIFO）批次匹配（用户说"
                "「精制一部领料 硫酸 500Kg」等领料/领用信息时用）。系统自动"
                "建议 QA 放行批次（最早入库优先、跨批拆分）。必收字段缺失时"
                "返回 missing，请向用户追问后再调用；返回 error（如无放行"
                "批次/库存不足）时如实转告并停止，不要猜测批次。创建成功后"
                "系统发送确认卡片，用户点「确认领料」才写入台账。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 值。物料（名称或批号关键词）、领用数量"
                            "（纯数字）、单位（Kg/瓶/L）、领用部门 为必收；"
                            "领用类型（缺省生产使用）、指定批号（用户明确要求"
                            "用某批号时传，禁止自行指定）、备注 选填"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]
