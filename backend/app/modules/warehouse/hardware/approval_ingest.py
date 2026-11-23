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

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareRequisition,
    HardwareRequisitionItem,
    HardwareReturn,
)
from app.modules.warehouse.hardware.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
)

logger = logging.getLogger(__name__)

# 审批定义「福兴电子领/退料单审批」控件 ID
KIND_WIDGET_ID = "widget17942773552310001"  # 单选：五金库领料/五金库退料/平台
DETAIL_WIDGET_ID = "widget17942790533710001"  # 明细 fieldList

# 「是否紧急」+「紧急原因」（2026-11-20 改版：紧急领料打标，与 approval_channel
# 同源；紧急原因仅 是否紧急=是 时显示/必填，退料分支无这两个控件）
URGENT_WIDGET_ID = "widget17951544578680001"
URGENT_VALUE_YES = "mwokm4ng-jf0ljqu7rwb-0"
URGENT_REASON_WIDGET_ID = "widget17951566636350001"

# 「五金库领料-平台」分支：普通控件六个顶层字段（系统代发起写入，2026-11-19）
PLATFORM_KIND_TEXT = "平台"
PLATFORM_NAME_WIDGET_ID = "widget17950811558710001"
PLATFORM_SPEC_WIDGET_ID = "widget17950811686580001"
PLATFORM_QTY_WIDGET_ID = "widget17950812036890001"

KIND_REQUISITION = "领料"
KIND_RETURN = "退料"


class IngestError(Exception):
    """实例不可摄取（表单解析失败/物资不匹配等）——记日志跳过，不重试。"""


@dataclass
class ParsedForm:
    kind: str  # KIND_REQUISITION / KIND_RETURN
    rows: list[dict[str, Any]] = field(default_factory=list)  # [{name, spec, quantity}]
    linked_code: str = ""  # 退料：关联领料审批实例 code（货对板校验锚点）
    raw: str = ""  # 原始 form JSON（观察模式）
    platform: bool = False  # 五金库领料-平台分支（系统代发起：顶层普通控件）
    urgent: bool = False  # 是否紧急=是（紧急单：仓管可审批前发料）
    urgent_reason: str = ""  # 紧急原因（urgent=是 时必填）


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


def _is_urgent_value(v: Any) -> bool:
    """「是否紧急」控件值 → bool（读回文本「是」与选项 value 双形态兼容）。"""
    s = _text(v)
    return bool(s) and (s == "是" or s == URGENT_VALUE_YES)


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
    """明细值 → [{name, spec, quantity, linked_code?}]；数量缺失的行跳过并记原始。

    数量列名历经三次改版：数量 → 领取量 → 领料量（领料）→ 退料量（退料，2026-11-19
    双表明细）。退料行内「关联审批」connect 列 → linked_code（行级挂原领料单）。
    """
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
        qty_raw = _row_value(row, "数量", "领取量", "领料量", "退料量", "quantity")
        try:
            qty = float(_text(qty_raw))
        except (TypeError, ValueError):
            logger.warning("[摄取] 明细行数量不可解析: name=%s raw=%s", name, qty_raw)
            continue
        if not name or qty <= 0:
            logger.warning("[摄取] 明细行缺名称或数量非正: name=%s qty=%s", name, qty)
            continue
        row_out: dict[str, Any] = {"name": name, "spec": spec, "quantity": qty}
        linked = _extract_link_code(_row_value(row, "关联审批", "关联领料审批"))
        if linked:
            row_out["linked_code"] = linked
        rows_out.append(row_out)
    return rows_out


def _extract_link_code(v: Any) -> str:
    """关联审批控件值 → 实例 code（兼容 str / dict / list 形态）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return str(v.get("instance_code") or v.get("code") or "").strip()
    if isinstance(v, list):
        for item in v:
            code = _extract_link_code(item)
            if code:
                return code
    return ""


def _parse_platform_rows(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """平台分支（五金库领料-平台）→ 单行 [{name, spec, quantity}]。

    系统代发起走六个顶层普通控件（类别/名称/规格/单位/可领量/领料量）；按
    控件名优先、id 兜底取值（防定义改名）。数量非正 = 行无效（由调用方报错）。
    """
    def pick(*names: str, widget_id: str = "") -> Any:
        for w in widgets:
            if widget_id and str(w.get("id") or "") == widget_id:
                return w.get("value")
            if str(w.get("name") or "") in names:
                return w.get("value")
        return None

    name = _text(pick("名称", widget_id=PLATFORM_NAME_WIDGET_ID))
    spec = _text(pick("规格", widget_id=PLATFORM_SPEC_WIDGET_ID))
    qty_raw = pick("领料量", widget_id=PLATFORM_QTY_WIDGET_ID)
    try:
        qty = float(_text(qty_raw))
    except (TypeError, ValueError):
        logger.warning("[摄取] 平台分支领料量不可解析: raw=%s", qty_raw)
        return []
    if not name or qty <= 0:
        logger.warning("[摄取] 平台分支缺名称或数量非正: name=%s qty=%s", name, qty)
        return []
    return [{"name": name, "spec": spec, "quantity": qty}]


def parse_form(form_str: str | list | None) -> ParsedForm:
    """实例 form JSON → 分流键 + 明细行 + 退料行级关联领料实例。

    兼容两种形态：事件/直注路径的 JSON 字符串；get_instance 已解析的 list。
    明细表 2026-11-19 拆双表：五金库领料明细 / 五金库退料明细（退料行内含
    「关联审批」connect 列挂原领料单）；按分流键选表，旧单字段形态兜底。
    「五金库领料-平台」分支（系统代发起）无明细表，走六个顶层普通控件。
    """
    if isinstance(form_str, list):
        widgets = form_str
    else:
        try:
            widgets = json.loads(form_str or "[]")
        except ValueError:
            widgets = []
    kind: str | None = None
    platform = False
    urgent = False
    urgent_reason = ""
    detail_lists: list[tuple[str, str, Any]] = []  # (widget_id, name, value)
    linked_code = ""  # 表单级独立关联控件（旧设计兼容；现设计为行内 connect 列）
    for w in widgets if isinstance(widgets, list) else []:
        wid = str(w.get("id") or "")
        wname = str(w.get("name") or "")
        wtype = str(w.get("type") or "")
        if wid == KIND_WIDGET_ID or "领/退料" in wname:
            kind = _kind_from_value(w.get("value"))
            platform = PLATFORM_KIND_TEXT in _text(w.get("value"))
        if wid == URGENT_WIDGET_ID or wname == "是否紧急":
            urgent = _is_urgent_value(w.get("value"))
        if wid == URGENT_REASON_WIDGET_ID or wname == "紧急原因":
            urgent_reason = _text(w.get("value"))
        if wtype == "fieldList" or wname == "明细" or "明细" in wname:
            detail_lists.append((wid, wname, w.get("value")))
        if (
            ("关联领料" in wname or "关联审批" in wname)
            or wtype in ("approve", "associated_approval")
        ) and wtype != "fieldList" and not linked_code:
            linked_code = _extract_link_code(w.get("value"))
    if kind is None:
        raise IngestError(f"领/退料分流键未识别: {_text(form_str)[:200]}")

    if platform:
        rows = _parse_platform_rows(list(widgets))
        return ParsedForm(
            kind=KIND_REQUISITION, rows=rows, linked_code="",
            raw=_text(form_str), platform=True,
            urgent=urgent, urgent_reason=urgent_reason,
        )

    def _pick(prefer: str) -> list[dict[str, Any]]:
        for _wid, name, value in detail_lists:
            if prefer in name:
                rows_ = _parse_field_list(value)
                if rows_:
                    return rows_
        for wid, name, value in detail_lists:  # 兜底：任一非空明细表
            if wid == DETAIL_WIDGET_ID or "明细" in name or name == "明细":
                rows_ = _parse_field_list(value)
                if rows_:
                    return rows_
        return []

    rows = _pick("退料明细" if kind == KIND_RETURN else "领料明细")
    return ParsedForm(
        kind=kind, rows=rows, linked_code=linked_code, raw=_text(form_str),
        urgent=urgent, urgent_reason=urgent_reason,
    )


# ── 发起人身份 / 物资匹配 ──


async def _starter(db: AsyncSession, instance: dict[str, Any]) -> dict[str, str]:
    """发起人 → {name, dept, open_id, identity_id}（identity 三绑缺失时兜底 user_id）。

    open_id 优先取实例详情自带的（仓储应用凭证拉取 → 天然本应用作用域）；
    identity.feishu_open_id 是混合作用域（库存/安全 app 的 ou_），跨应用发送
    会报 99992361 cross app，仅作兜底。identity_id 供补办强键匹配
    （↔ 紧急单 applicant_user_id）。
    """
    user_id = str(
        instance.get("start_user_id")
        or (instance.get("starter") or {}).get("user_id")
        or instance.get("user_id")
        or ""
    )
    inst_open_id = str(instance.get("open_id") or "")
    row = (
        await db.execute(
            text(
                "select id, name, coalesce(department, ''), feishu_open_id "
                "from identity.users where feishu_user_id=:u and is_deleted=false limit 1"
            ),
            {"u": user_id},
        )
    ).first()
    if row:
        return {
            "name": row[1],
            "dept": row[2] or "未匹配部门",
            "open_id": inst_open_id or row[3] or user_id,
            "identity_id": str(row[0]),
        }
    return {
        "name": user_id or "未知发起人",
        "dept": "未匹配部门",
        "open_id": inst_open_id or user_id,
        "identity_id": "",
    }


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


async def _validate_return_rows(
    db: AsyncSession,
    rows: list[dict[str, Any]],
    matched: list[tuple[HardwareMaterial, float]],
) -> str:
    """退料货对板校验（行级关联版，2026-11-19 双表明细）：返回问题文案，空串=通过。

    - 每行须挂关联领料审批（行内 connect 列）；
    - 关联领料单必须存在且已发料（issued）；
    - 退料物资必须在对应领料明细内（防货不对板）；
    - 逐料 退量 ≤ 领量 − 已退量（draft+accepted 行级归集，防领10退20/拆单）。
    rows 与 matched 一一对应（_match_materials 保序）。
    """
    problems: list[str] = []
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        code = str(r.get("linked_code") or "")
        if not code:
            problems.append(f"第{i + 1}行 {r.get('name')} 未选择关联领料审批")
            continue
        groups.setdefault(code, []).append(i)

    for linked_code, idxs in groups.items():
        req = await _find_requisition(db, linked_code)
        if req is None:
            problems.append(f"关联领料审批 {linked_code} 未在系统建单（或非本定义实例）")
            continue
        if req.status != "issued":
            problems.append(
                f"关联领料单 {req.req_no} 状态为 {req.status}（须已发料才可退料）"
            )
            continue

        issued: dict[str, float] = {}
        items = (
            await db.execute(
                select(HardwareRequisitionItem).where(
                    HardwareRequisitionItem.requisition_id == req.id
                )
            )
        ).scalars().all()
        for it in items:
            key = str(it.material_id)
            qty = it.issued_qty if it.issued_qty is not None else it.need_qty
            issued[key] = issued.get(key, 0) + float(qty or 0)

        # 已退量：行级 linked_code 归集（JSONB contains 圈定+行级兜底单据级列）
        returned: dict[str, float] = {}
        prior = (
            await db.execute(
                select(HardwareReturn).where(
                    HardwareReturn.status.in_(["draft", "accepted"]),
                    HardwareReturn.is_deleted.is_(False),
                    or_(
                        HardwareReturn.requisition_instance_code == linked_code,
                        text("hardware_returns.items @> :jq"),
                    ),
                ),
                {"jq": json.dumps([{"linked_code": linked_code}])},
            )
        ).scalars().all()
        for ret in prior:
            doc_link = ret.requisition_instance_code
            for row in ret.items or []:
                row_link = str(row.get("linked_code") or "")
                if row_link != linked_code and not (
                    not row_link and doc_link == linked_code
                ):
                    continue
                key = str(row.get("material_id") or "")
                returned[key] = returned.get(key, 0) + float(row.get("quantity") or 0)

        cumulative: dict[str, float] = {}
        for i in idxs:
            m, q = matched[i]
            key = str(m.id)
            cap = issued.get(key)
            if cap is None:
                problems.append(
                    f"{m.name} {m.spec or ''} 不在关联领料单 {req.req_no} 明细中"
                )
                continue
            already = returned.get(key, 0) + cumulative.get(key, 0)
            remain = cap - already
            if q > remain + 1e-9:
                problems.append(
                    f"{m.name} {m.spec or ''} 退 {q:g} 超 关联可退 {remain:g}"
                    f"（领 {cap:g}，已退/在退 {already:g}，单 {req.req_no}）"
                )
            cumulative[key] = already + q
    return "；".join(problems)


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
        # 静默跳过曾吞掉全部真机实例（get_instance 未透传 approval_code），必须留痕
        logger.info(
            "[摄取] 跳过非目标定义实例: %s approval_code=%s",
            instance_code, inst.get("approval_code"),
        )
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
                req_type="urgent" if parsed.urgent else "normal",
                urgent_reason=parsed.urgent_reason or None,
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
            # 未受理退回（2026-11-18 拍板）：仍在审批中的实例直接撤回，审批人
            # 不再处理注定缺料的单；已 APPROVED 的不撤（撤回会使实例退回审批中）
            if status == "PENDING":
                await _cancel_feishu_instance(instance_code, inst)
            return {"action": "rejected_shortage", "kind": "领料", "doc_no": req.req_no}
        # 紧急单：建单预扣即私发仓管加急卡（可审批前发料，先发后批）
        if parsed.urgent:
            from app.modules.warehouse.hardware.urgent_flow import send_urgent_notice

            await send_urgent_notice(db, req)
        # 迟到状态补偿（对账兜底路径：事件丢失后按当前状态对齐）
        await _apply_status(db, req, status)
        logger.info(
            "[摄取] 领料单已建: %s instance=%s rows=%d urgent=%s",
            req.req_no, instance_code, len(matched), parsed.urgent,
        )
        return {"action": "ingested", "kind": "领料", "doc_no": req.req_no, "status": req.status}

    # 退料：先货对板校验（2026-11-19 拍板）——过验建草稿（不动账，审批通过后
    # 仓管系统内 accept 批次回加）；未过验拒收留痕+通知+退回审批（同缺料口径）
    matched = await _match_materials(db, parsed.rows)
    from app.modules.warehouse.hardware.stocktake import create_return

    def _apply_row_links(ret_: HardwareReturn) -> None:
        """行级关联落 items JSON；单一关联时冗余记单据级列（查询友好）。"""
        distinct = {str(r.get("linked_code") or "") for r in parsed.rows} - {""}
        ret_.requisition_instance_code = next(iter(distinct)) if len(distinct) == 1 else None
        if not any("linked_code" in r for r in parsed.rows):
            return
        items = [dict(row) for row in (ret_.items or [])]
        for i, r in enumerate(parsed.rows):
            if "linked_code" in r and i < len(items):
                items[i]["linked_code"] = r["linked_code"]
        ret_.items = items

    problem = await _validate_return_rows(db, parsed.rows, matched)
    if problem:
        ret = await create_return(
            db,
            dept_name=starter["dept"],
            returned_by=starter["name"],
            returned_by_open_id=starter["open_id"] or None,
            items=[{"material_id": str(m.id), "quantity": str(q)} for m, q in matched],
            remark=f"飞书退料审批 {instance_code}（校验未过）",
        )
        ret.approval_instance_code = instance_code
        _apply_row_links(ret)
        ret.status = "rejected"
        ret.rejected_reason = f"货对板校验未过：{problem}"
        await db.flush()
        await _notify_return_rejected(starter["open_id"], ret.return_no, problem)
        logger.warning("[摄取] 退料校验拒收: %s err=%s", instance_code, problem)
        if status == "PENDING":
            await _cancel_feishu_instance(instance_code, inst)
        return {"action": "rejected_mismatch", "kind": "退料", "doc_no": ret.return_no}

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
    _apply_row_links(ret)
    await db.flush()
    logger.info("[摄取] 退库草稿已建: %s instance=%s", ret.return_no, instance_code)
    return {"action": "ingested", "kind": "退料", "doc_no": ret.return_no}


async def _apply_status(db: AsyncSession, req: HardwareRequisition, status: str) -> None:
    """按飞书实例状态对齐领料单状态机（幂等）。

    语义（2026-11-19 拍板）：审批定义含仓管员办理节点，实例 APPROVED=终态
    =审批关闭=仓管已在飞书确认发料 → 自动 approve+issue 实扣（镜像三值
    20/10/10 → 10/0/10）；PENDING 全程预扣，REJECTED/CANCELED 释放。

    紧急单先发后批（2026-11-20 改版，审批单据即闭环手续）：
    - 仓管已审批前发料（issued）收到 APPROVED → 只落审批结果闭环，
      绝不二次发料；
    - pending 收 APPROVED → 走正常 approve+issue（与普通单同轨）；
    - 已发料收到 REJECTED/CANCELED → 不回退不释放（物料已实际发出），
      approval_status 留痕 + 通知申请人按退料流程处理。
    """
    if status == "APPROVED":
        if req.status == "pending":
            await hw_service.approve_requisition(
                db, req.id, approver="飞书审批", note="飞书审批通过（事件/对账同步）"
            )
            req.approval_status = "approved"
        if req.status == "approved":
            await hw_service.issue_requisition(
                db, req.id,
                issued_by="飞书审批·仓管办理",
                received_by=req.applicant or "领用人",
            )
        elif req.status == "issued" and req.req_type == "urgent":
            # 先发后批闭环：仓管已发料，审批通过只补手续（approve 的 issued
            # urgent 分支），库存已实扣绝不二次发料
            await hw_service.approve_requisition(
                db, req.id, approver="飞书审批", note="紧急领料审批通过（先发后批闭环）"
            )
            await _notify_urgent_closed(req)
    elif status in ("REJECTED", "CANCELED"):
        if req.status == "issued" and req.req_type == "urgent":
            # 物料已发出：不回退不释放，审批结论留痕并提示按退料流程处理
            req.approval_status = "rejected" if status == "REJECTED" else "cancelled"
            req.remark = (
                f"{req.remark or ''}；紧急领料（先发后批）审批"
                f"{'驳回' if status == 'REJECTED' else '撤回'}，请仓管与申请人核对退料"
            )
            await _notify_urgent_closed(req, approved=False, status=status)
        elif req.status == "pending":
            if status == "REJECTED":
                await hw_service.reject_requisition(
                    db, req.id, approver="飞书审批", reason="飞书审批驳回（事件/对账同步）"
                )
                req.approval_status = "rejected"
            else:
                await hw_service.cancel_requisition(db, req.id)
                req.approval_status = "cancelled"
    await db.flush()


async def _apply_return_status(db: AsyncSession, ret: HardwareReturn, status: str) -> None:
    """飞书实例状态对齐退库单（幂等，2026-11-19 对称语义）。

    APPROVED=终态=审批关闭=仓管已在飞书办理收料 → 负责人签（飞书审批链
    「主管及以上」节点视同签收）+ 自动验收回加（对称领料自动发料实扣）；
    REJECTED/CANCELED → 草稿作废留痕。
    """
    if status == "APPROVED" and ret.status == "draft":
        from app.modules.warehouse.hardware.stocktake import accept_return

        if not ret.leader_signed:
            ret.leader_signed = True
            ret.leader_signed_by = "飞书审批"
            ret.leader_signed_at = datetime.now(UTC)
            await db.flush()
        await accept_return(db, ret.id, accepted_by="飞书审批·仓管办理")
    elif status in ("REJECTED", "CANCELED") and ret.status == "draft":
        ret.status = "rejected"
        ret.rejected_reason = (
            f"飞书审批{'驳回' if status == 'REJECTED' else '撤销'}（事件/对账同步）"
        )
        await db.flush()


async def sync_status(
    db: AsyncSession, instance_code: str, *, status: str | None = None
) -> dict[str, Any]:
    """审批结果事件 → 领料单/退库单状态机同步。"""
    if status is None:
        status = str((await _fetch_instance(instance_code)).get("status") or "")
    req = await _find_requisition(db, instance_code)
    if req is not None:
        await _apply_status(db, req, status)
        return {"action": "synced", "doc_no": req.req_no, "status": req.status}
    ret = await _find_return(db, instance_code)
    if ret is not None:
        await _apply_return_status(db, ret, status)
        return {"action": "synced", "doc_no": ret.return_no, "status": ret.status}
    return {"action": "ignore", "reason": "无关联单据"}


# ── 通知 ──


async def _cancel_feishu_instance(instance_code: str, inst: dict[str, Any]) -> None:
    """缺料拒收后退回飞书审批（以提交人身份撤回实例，best-effort 不抛）。

    撤回成功后飞书会推 CANCELED 事件（v1/v2 双格式都由既有处理器幂等吸收）。
    """
    user_id = str(
        inst.get("user_id")
        or inst.get("start_user_id")
        or (inst.get("starter") or {}).get("user_id")
        or ""
    )
    approval_code = str(get_settings().HARDWARE_APPROVAL_CODE or "").strip()
    if not user_id or not approval_code:
        logger.info("[摄取] 缺料退回跳过（缺 user_id/approval_code）: %s", instance_code)
        return
    try:
        from app.platform.integrations.feishu.approval import cancel_instance

        app_id, app_secret = _credentials()
        ok = await cancel_instance(
            approval_code, instance_code, user_id, app_id=app_id, app_secret=app_secret
        )
        if ok:
            logger.info("[摄取] 缺料单已退回飞书审批: %s", instance_code)
    except Exception:  # noqa: BLE001 — 退回失败不影响拒收留痕主流程
        logger.warning("[摄取] 缺料退回飞书审批失败: %s", instance_code, exc_info=True)


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


async def _notify_return_rejected(open_id: str, return_no: str, problem: str) -> None:
    """退料校验拒收通知（私发卡片，best-effort 不抛）。"""
    if not open_id:
        return
    try:
        from app.modules.warehouse.feishu.notification import send_card_to_user

        card = {
            "config": {"wide_screen": True},
            "header": {
                "title": {"tag": "plain_text", "content": "五金库退料申请未受理"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"你的飞书退料审批已退回（{return_no} 留痕）。\n\n"
                            f"原因：{problem}\n\n"
                            "退料须关联原领料审批，且物资与数量不得超出原单可退量，"
                            "请核对后重新发起。"
                        ),
                    },
                }
            ],
        }
        await send_card_to_user(open_id, card)
    except Exception:  # noqa: BLE001 — 通知失败不影响摄取主流程
        logger.warning("[摄取] 退料拒收通知发送失败: %s", exc_info=True)


async def _notify_urgent_closed(
    req: HardwareRequisition, *, approved: bool = True, status: str = "APPROVED"
) -> None:
    """紧急领料（先发后批）审批结论通知（私发申请人，best-effort 不抛）。

    approved=通过→手续闭环确认；驳回/撤回→留痕提示按退料流程处理。
    """
    open_id = req.applicant_open_id or ""
    if not open_id:
        return
    if approved:
        title, template, content = (
            "紧急领料手续已闭环",
            "green",
            f"你的紧急领用单 **{req.req_no}** 审批已通过（先发后批闭环），手续完成。",
        )
    else:
        verb = "被驳回" if status == "REJECTED" else "被撤回"
        title, template, content = (
            "紧急领料审批未通过",
            "orange",
            (
                f"你的紧急领用单 **{req.req_no}** 的审批{verb}。物料已先行发出，"
                "请与仓管员核对后按退料流程办理退回或补交说明。"
            ),
        )
    try:
        from app.modules.warehouse.feishu.notification import send_card_to_user

        card = {
            "config": {"wide_screen": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
        }
        await send_card_to_user(open_id, card)
    except Exception:  # noqa: BLE001 — 通知失败不影响主流程
        logger.warning("[紧急领料] 结论通知发送失败: %s", req.req_no, exc_info=True)


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

    @on_event("approval_instance")
    async def _on_approval_instance_v1(event: dict[str, Any]) -> None:
        """v1 旧格式审批实例事件（订阅审批事件 API 实际推送的就是这个格式：
        {"type": "event_callback", "event": {"type": "approval_instance",
         "instance_code": .., "status": PENDING/APPROVED/REJECTED/CANCELED, ..}}）。
        状态映射到 v2 语义处理器；摄取幂等（instance_code 唯一），双格式并存安全。
        """
        code = _extract_instance_code(event)
        status = str(event.get("status") or "").upper()
        if not code:
            logger.warning(
                "[摄取] v1 审批事件缺 instance_code: %s",
                json.dumps(event, ensure_ascii=False)[:200],
            )
            return
        logger.info("[摄取] v1 审批实例事件: %s status=%s", code, status)
        if status == "PENDING":
            await _on_started({"instance": {"instance_code": code}})
        elif status == "APPROVED":
            await _on_approved({"instance": {"instance_code": code}})
        elif status == "REJECTED":
            await _on_rejected({"instance": {"instance_code": code}})
        elif status == "CANCELED":
            await _on_canceled({"instance": {"instance_code": code}})
        else:
            logger.info("[摄取] v1 审批事件状态 %s 忽略: instance=%s", status, code)


# ── 对账兜底（scheduled 定时任务调用；事件丢失补漏）──


async def reconcile_recent_instances(
    db: AsyncSession, *, hours: int = 2, now: datetime | None = None
) -> dict[str, int]:
    """扫描近 N 小时实例：未摄取的补摄取 + pending 单状态对齐（幂等）。"""
    from app.platform.integrations.feishu.approval import list_instance_codes

    approval_code = str(get_settings().HARDWARE_APPROVAL_CODE or "").strip()
    if not approval_code:
        return {"enabled": 0, "codes": 0, "ingested": 0, "synced": 0, "skipped": 0}
    now = now or datetime.now(UTC)
    start_ms = int((now - timedelta(hours=hours)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    app_id, app_secret = _credentials()
    codes = await list_instance_codes(
        approval_code, start_ms, end_ms, app_id=app_id, app_secret=app_secret
    )
    stats = {"enabled": 1, "codes": len(codes), "ingested": 0, "synced": 0, "skipped": 0}
    for code in codes:
        try:
            if await _find_requisition(db, code) or await _find_return(db, code):
                result = await sync_status(db, code)
                if result.get("action") == "synced":
                    stats["synced"] += 1
            else:
                result = await ingest_instance(db, code)
                if result.get("action") == "skip":
                    stats["skipped"] += 1
                else:
                    stats["ingested"] += 1
        except IngestError:
            logger.warning("[对账] 实例不可摄取: %s", code, exc_info=True)
    return stats


# 模块导入即注册事件处理器（main lifespan import 本模块后长连接自动分发审批事件）
register_event_handlers()
