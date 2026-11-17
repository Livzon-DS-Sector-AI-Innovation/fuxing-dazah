"""五金库领/退料审批实例摄取（飞书发单入口，二期）。

事件驱动主通道（approval.instance.* WS 长连接，处理器注册在文件底部）
+ 低频轮询对账兜底（scheduled.reconcile_recent_instances）：
- 领料实例（领/退料=五金库领料）→ PENDING 即建领料单（预扣生效防审批窗口
  被抢），审批结果事件驱动状态机；缺料拒收 + 飞书私发卡片通知发起人。
- 退料实例（五金库退料）→ 建退库草稿（不动账），审批通过后仓管系统内
  accept 批次回加。
幂等键 = approval_instance_code（领料单/退库单各存一列），事件重推与对账
扫描重复摄取零副作用。

表单值按「快照文本」假设解析（引用多维表格控件实例存字段文本），物资匹配
走 名称+规格 = 平台唯一键；首条真机单前为观察模式——解析失败/未识别行以
INFO 落原始 JSON，按日志修正 _text/_parse_field_list 即可（2026-11-11 待实测项）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareRequisition,
    HardwareReturn,
)
from app.modules.warehouse.hardware.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
)

logger = logging.getLogger(__name__)

# 审批定义「福兴电子领/退料单审批」控件 ID（2026-11-11 定稿表单）
KIND_WIDGET_ID = "widget17942773552310001"  # 单选：五金库领料/五金库退料
DETAIL_WIDGET_ID = "widget17942790533710001"  # 明细 fieldList

KIND_REQUISITION = "领料"
KIND_RETURN = "退料"


class IngestError(Exception):
    """实例不可摄取（表单解析失败/物资不匹配等）——记日志跳过，不重试。"""


@dataclass
class ParsedForm:
    kind: str  # KIND_REQUISITION / KIND_RETURN
    rows: list[dict[str, Any]] = field(default_factory=list)  # [{name, spec, quantity}]
    raw: str = ""  # 原始 form JSON（观察模式）


# ── 表单解析（防御式：文本/对象值两形态兼容）──


def _text(v: Any) -> str:
    """控件值 → 文本（兼容 str / {"text": ..} / [{"text": ..}] 形态）。"""
    if v is None:
        return ""
    if isinstance(v, dict):
        return str(v.get("text") or v.get("value") or "").strip()
    if isinstance(v, list):
        return "".join(
            _text(i) if isinstance(i, (dict, list)) else str(i) for i in v
        ).strip()
    return str(v).strip()


def _kind_from_value(v: Any) -> str | None:
    s = _text(v)
    if "领料" in s:
        return KIND_REQUISITION
    if "退料" in s:
        return KIND_RETURN
    return None


def _row_value(row: Any, *names: str) -> Any:
    """明细行内按控件名取值（行=list[widget] 或 dict）。"""
    if isinstance(row, dict):
        for n in names:
            if n in row:
                return row[n]
        return None
    if isinstance(row, list):
        for w in row:
            if isinstance(w, dict) and str(w.get("name") or "") in names:
                return w.get("value")
    return None


def _parse_field_list(v: Any) -> list[dict[str, Any]]:
    """明细值 → [{name, spec, quantity}]；数量缺失的行跳过并记原始。"""
    rows_out: list[dict[str, Any]] = []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = None
    if not isinstance(v, list):
        logger.warning("[摄取] 明细值形态未识别: %s", json.dumps(v, ensure_ascii=False, default=str)[:400])
        return rows_out
    for row in v:
        name = _text(_row_value(row, "物资名称", "名称", "name"))
        spec = _text(_row_value(row, "规格型号", "规格", "spec"))
        qty_raw = _row_value(row, "数量", "quantity")
        try:
            qty = float(_text(qty_raw))
        except (TypeError, ValueError):
            logger.warning("[摄取] 明细行数量不可解析: name=%s raw=%s", name, qty_raw)
            continue
        if not name or qty <= 0:
            logger.warning("[摄取] 明细行缺名称或数量非正: name=%s qty=%s", name, qty)
            continue
        rows_out.append({"name": name, "spec": spec, "quantity": qty})
    return rows_out


def parse_form(form_str: str | None) -> ParsedForm:
    """实例 form JSON → 分流键 + 明细行。"""
    try:
        widgets = json.loads(form_str or "[]")
    except ValueError:
        widgets = []
    kind: str | None = None
    rows: list[dict[str, Any]] = []
    for w in widgets if isinstance(widgets, list) else []:
        wid = str(w.get("id") or "")
        wname = str(w.get("name") or "")
        if wid == KIND_WIDGET_ID or "领/退料" in wname:
            kind = _kind_from_value(w.get("value"))
        if wid == DETAIL_WIDGET_ID or w.get("type") == "fieldList" or wname == "明细":
            rows = _parse_field_list(w.get("value"))
    if kind is None:
        raise IngestError(f"领/退料分流键未识别: {_text(form_str)[:200]}")
    return ParsedForm(kind=kind, rows=rows, raw=form_str or "")


# ── 发起人身份 / 物资匹配 ──


async def _starter(db: AsyncSession, instance: dict[str, Any]) -> dict[str, str]:
    """发起人 → {name, dept, open_id}（identity 三绑缺失时兜底 user_id）。"""
    user_id = str(
        instance.get("start_user_id")
        or (instance.get("starter") or {}).get("user_id")
        or ""
    )
    row = (
        await db.execute(
            text(
                "select name, coalesce(department, ''), feishu_open_id "
                "from identity.users where feishu_user_id=:u and is_deleted=false limit 1"
            ),
            {"u": user_id},
        )
    ).first()
    if row:
        return {
            "name": row[0],
            "dept": row[1] or "未匹配部门",
            "open_id": row[2] or user_id,
        }
    return {"name": user_id or "未知发起人", "dept": "未匹配部门", "open_id": user_id}


async def _match_materials(
    db: AsyncSession, rows: list[dict[str, Any]]
) -> list[tuple[HardwareMaterial, float]]:
    """名称+规格（平台唯一键）精确匹配；未命中即 IngestError。"""
    out: list[tuple[HardwareMaterial, float]] = []
    for r in rows:
        stmt = select(HardwareMaterial).where(
            HardwareMaterial.is_deleted.is_(False),
            HardwareMaterial.active.is_(True),
            HardwareMaterial.name == r["name"],
        )
        spec = r.get("spec") or None
        if spec:
            stmt = stmt.where(HardwareMaterial.spec == spec)
        material = (await db.execute(stmt.limit(1))).scalars().first()
        if material is None:
            raise IngestError(
                f"物资不匹配: {r['name']} | {r.get('spec')}(以快照文本精确匹配失败，"
                f"可能编码/名称回写形态不同——对照镜像表核对)"
            )
        out.append((material, r["quantity"]))
    return out


# ── 摄取主流程 ──


async def _find_requisition(db: AsyncSession, code: str) -> HardwareRequisition | None:
    return (
        await db.execute(
            select(HardwareRequisition).where(
                HardwareRequisition.approval_instance_code == code,
                HardwareRequisition.is_deleted.is_(False),
            )
        )
    ).scalars().first()


async def _find_return(db: AsyncSession, code: str) -> HardwareReturn | None:
    return (
        await db.execute(
            select(HardwareReturn).where(
                HardwareReturn.approval_instance_code == code,
                HardwareReturn.is_deleted.is_(False),
            )
        )
    ).scalars().first()


def _credentials() -> tuple[str | None, str | None]:
    s = get_settings()
    return s.WAREHOUSE_FEISHU_APP_ID or None, s.WAREHOUSE_FEISHU_APP_SECRET or None


async def _fetch_instance(instance_code: str) -> dict[str, Any]:
    from app.platform.integrations.feishu.approval import ApprovalAPIError, get_instance

    app_id, app_secret = _credentials()
    try:
        inst = await get_instance(instance_code, app_id=app_id, app_secret=app_secret)
    except ApprovalAPIError as exc:
        raise IngestError(f"实例详情拉取失败: {exc}") from exc
    return dict(inst or {})


async def ingest_instance(
    db: AsyncSession,
    instance_code: str,
    *,
    instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """幂等摄取：领料→建单预扣；退料→退库草稿。返回 {action, kind, doc_no, ...}。

    已摄取过（领料单或退库单已挂本 instance_code）→ action=exists。
    """
    if await _find_requisition(db, instance_code) or await _find_return(db, instance_code):
        return {"action": "exists", "instance_code": instance_code}

    inst = instance if instance is not None else await _fetch_instance(instance_code)
    approval_code = str(get_settings().HARDWARE_APPROVAL_CODE or "").strip()
    if approval_code and str(inst.get("approval_code") or "") != approval_code:
        return {"action": "skip", "reason": "非五金库领/退料定义"}

    parsed = parse_form(inst.get("form"))
    if not parsed.rows:
        raise IngestError(f"明细行为空: instance={instance_code} raw={parsed.raw[:300]}")
    starter = await _starter(db, inst)
    status = str(inst.get("status") or "PENDING")

    if parsed.kind == KIND_REQUISITION:
        matched = await _match_materials(db, parsed.rows)
        req = await hw_service.create_requisition(
            db,
            RequisitionCreate(
                dept_name=starter["dept"],
                applicant=starter["name"],
                applicant_open_id=starter["open_id"] or None,
                purpose="飞书领/退料审批发起",
                remark=f"飞书审批实例 {instance_code}",
                items=[
                    RequisitionItemIn(
                        material_id=str(m.id), need_qty=str(q)  # type: ignore[arg-type]
                    )
                    for m, q in matched
                ],
            ),
        )
        req.approval_channel = "feishu"
        req.approval_instance_code = instance_code
        await db.flush()
        try:
            await hw_service.submit_requisition(db, req.id)  # 预扣 + 超卖校验
        except hw_service.HardwareError as exc:
            # 缺料拒收：单据留痕（rejected）+ 私发通知发起人
            req.status = "rejected"
            req.approval_status = "rejected"
            req.remark = f"{req.remark or ''}；缺料拒收：{exc}"
            await db.flush()
            await _notify_rejected(starter["open_id"], matched, exc)
            logger.warning("[摄取] 领料缺料拒收: instance=%s err=%s", instance_code, exc)
            return {"action": "rejected_shortage", "kind": "领料", "doc_no": req.req_no}
        # 迟到状态补偿（对账兜底路径：事件丢失后按当前状态对齐）
        await _apply_status(db, req, status)
        logger.info(
            "[摄取] 领料单已建: %s instance=%s rows=%d", req.req_no, instance_code, len(matched)
        )
        return {"action": "ingested", "kind": "领料", "doc_no": req.req_no, "status": req.status}

    # 退料：退库草稿（不动账），审批通过后仓管系统内 accept 批次回加
    matched = await _match_materials(db, parsed.rows)
    from app.modules.warehouse.hardware.stocktake import create_return

    ret = await create_return(
        db,
        dept_name=starter["dept"],
        returned_by=starter["name"],
        returned_by_open_id=starter["open_id"] or None,
        items=[
            {"material_id": str(m.id), "quantity": str(q)} for m, q in matched
        ],
        remark=f"飞书退料审批 {instance_code}（审批通过后请确认回加）",
    )
    ret.approval_instance_code = instance_code
    await db.flush()
    logger.info("[摄取] 退库草稿已建: %s instance=%s", ret.return_no, instance_code)
    return {"action": "ingested", "kind": "退料", "doc_no": ret.return_no}


async def _apply_status(db: AsyncSession, req: HardwareRequisition, status: str) -> None:
    """按飞书实例状态对齐领料单状态机（仅 pending 可迁移；幂等）。"""
    if req.status != "pending":
        return
    if status == "APPROVED":
        await hw_service.approve_requisition(
            db, req.id, approver="飞书审批", note="飞书审批通过（事件/对账同步）"
        )
        req.approval_status = "approved"
    elif status == "REJECTED":
        await hw_service.reject_requisition(
            db, req.id, approver="飞书审批", reason="飞书审批驳回（事件/对账同步）"
        )
        req.approval_status = "rejected"
    elif status == "CANCELED":
        await hw_service.cancel_requisition(db, req.id)
    await db.flush()


async def sync_status(
    db: AsyncSession, instance_code: str, *, status: str | None = None
) -> dict[str, Any]:
    """审批结果事件 → 领料单状态机同步（退库草稿不动，仓管确认制）。"""
    req = await _find_requisition(db, instance_code)
    if req is None:
        return {"action": "ignore", "reason": "无关联领料单"}
    if status is None:
        status = str((await _fetch_instance(instance_code)).get("status") or "")
    await _apply_status(db, req, status)
    return {"action": "synced", "doc_no": req.req_no, "status": req.status}


# ── 通知 ──


async def _notify_rejected(open_id: str, matched: list[Any], exc: Exception) -> None:
    """缺料拒收通知（私发卡片，best-effort 不抛）。"""
    if not open_id:
        return
    try:
        from app.modules.warehouse.feishu.notification import send_card_to_user

        lines = "\n".join(f"· {m.name} {m.spec or ''}" for m, _ in matched)
        card = {
            "config": {"wide_screen": True},
            "header": {
                "title": {"tag": "plain_text", "content": "五金库领料申请未受理"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"你的飞书领料审批未在系统建单（缺料拒收）：\n{lines}\n\n原因：{exc}\n请调整数量或更换物资后重新发起。",
                    },
                }
            ],
        }
        await send_card_to_user(open_id, card)
    except Exception:  # noqa: BLE001 — 通知失败不影响摄取主流程
        logger.warning("[摄取] 缺料通知发送失败: %s", exc_info=True)


# ── 事件接入（approval.instance.* WS 长连接 → _dispatch 分发）──


def _extract_instance_code(event: dict[str, Any]) -> str:
    for v in (
        (event.get("instance") or {}).get("instance_code"),
        event.get("instance_code"),
        (event.get("data") or {}).get("instance_code"),
    ):
        if v:
            return str(v)
    return ""


async def _run_with_session(coro_fn) -> None:  # noqa: ANN001
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        try:
            await coro_fn(session)
            await session.commit()
        except IngestError:
            await session.rollback()
            logger.warning("[摄取] 实例不可摄取，跳过", exc_info=True)
        except Exception:  # noqa: BLE001 — 事件处理异常不崩长连接
            await session.rollback()
            logger.exception("[摄取] 事件处理异常")


def register_event_handlers() -> None:
    """注册审批实例事件处理器（main lifespan 导入本模块即生效）。"""
    from app.modules.warehouse.feishu.event_client import on_event

    @on_event("approval.instance.started")
    async def _on_started(event: dict[str, Any]) -> None:
        code = _extract_instance_code(event)
        logger.info("[摄取] 审批实例创建事件: %s", code)
        if not code:
            return
        await _run_with_session(lambda s: ingest_instance(s, code))

    @on_event("approval.instance.approved")
    async def _on_approved(event: dict[str, Any]) -> None:
        code = _extract_instance_code(event)
        if not code:
            return
        logger.info("[摄取] 审批通过事件: %s", code)
        await _run_with_session(lambda s: sync_status(s, code, status="APPROVED"))

    @on_event("approval.instance.rejected")
    async def _on_rejected(event: dict[str, Any]) -> None:
        code = _extract_instance_code(event)
        if not code:
            return
        logger.info("[摄取] 审批驳回事件: %s", code)
        await _run_with_session(lambda s: sync_status(s, code, status="REJECTED"))

    @on_event("approval.instance.canceled")
    async def _on_canceled(event: dict[str, Any]) -> None:
        code = _extract_instance_code(event)
        if not code:
            return
        logger.info("[摄取] 审批撤销事件: %s", code)
        await _run_with_session(lambda s: sync_status(s, code, status="CANCELED"))


# ── 对账兜底（scheduled 定时任务调用；事件丢失补漏）──


async def reconcile_recent_instances(
    db: AsyncSession, *, hours: int = 2, now: datetime | None = None
) -> dict[str, int]:
    """扫描近 N 小时实例：未摄取的补摄取 + pending 单状态对齐（幂等）。"""
    from app.platform.integrations.feishu.approval import list_instance_codes

    approval_code = str(get_settings().HARDWARE_APPROVAL_CODE or "").strip()
    if not approval_code:
        return {"enabled": 0, "codes": 0, "ingested": 0, "synced": 0}
    now = now or datetime.now(UTC)
    start_ms = int((now - timedelta(hours=hours)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    app_id, app_secret = _credentials()
    codes = await list_instance_codes(
        approval_code, start_ms, end_ms, app_id=app_id, app_secret=app_secret
    )
    stats = {"enabled": 1, "codes": len(codes), "ingested": 0, "synced": 0}
    for code in codes:
        try:
            if await _find_requisition(db, code) or await _find_return(db, code):
                result = await sync_status(db, code)
                if result.get("action") == "synced":
                    stats["synced"] += 1
            else:
                await ingest_instance(db, code)
                stats["ingested"] += 1
        except IngestError:
            logger.warning("[对账] 实例不可摄取: %s", code, exc_info=True)
    return stats


# 模块导入即注册事件处理器（main lifespan import 本模块后长连接自动分发审批事件）
register_event_handlers()
