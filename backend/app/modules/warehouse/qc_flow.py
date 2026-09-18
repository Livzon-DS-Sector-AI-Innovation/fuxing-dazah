"""QC 请验放行闭环（V3.0 分期B，设计 §4.1 旗舰）。

四条链路围绕 material_receipt 的 QC/QA 字段（Bitable 权威，2B）：
1. 到货请验：入库登记确认后自动推 QC 群（submit 钩子 → push_center 事件）；
2. 进度扫描：每 60min 扫描未闭环记录，未取样/未出报超期提醒（阈值走
   预警规则中心全局默认 + material_master「实际物料：请检后出报天数」
   物料级覆盖；alert_records 幂等去重，状态未变不重推）；
3. QA 放行确认门：出报合格 → 自动建门（confirm_request）→ 确认回写
   QA放行/QA放行人(@confirmer)/放行提交时间(@today) → 放行变迁推上架
   通知；出报不合格 → 自动生成 unqualified_stock 记录 + 处理方案门；
4. 状态镜像：扫描 upsert warehouse_qc_status（receipt record_id 唯一），
   库存列表/驾驶舱只读展示，新旧镜像对比 = 变迁检测。

回写开关（质询 Round 1 定案）：qc_writeback_enabled 运行参数（默认 0=关，
fail-safe off）单独管辖 QC 链路 Base 写入（建门/确认回写/不合格生成），
与 A 期总开关 bitable_writeback_enabled 解耦——B 期可独立验收上线。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_cells import cell_number, cell_text
from app.modules.warehouse.models import WarehouseAlertRecord, WarehouseQcStatus

logger = logging.getLogger(__name__)

# 扫描窗口（天）：入库超 120 天的历史记录不进闭环（陈旧数据不重复提醒）
SCAN_WINDOW_DAYS = 120

# QC 超期规则键（alert_rules 全局默认；阈值智能中心预警配置可改）
QC_SAMPLE_RULE = "qc_sample_overdue"
QC_REPORT_RULE = "qc_report_overdue"
DEFAULT_SAMPLE_DAYS = 3
DEFAULT_REPORT_DAYS = 7

# QC 提醒的 alert_records 合成 material_id 命名空间（Base 批次无本地物料行，
# uuid5(record_id) 做稳定幂等键；alerts 列表无 material join，安全）
_ALERT_NAMESPACE = uuid.UUID("6f1a2c94-8d5b-4e7a-9c3f-1a2b3c4d5e01")

# 拉取字段（镜像 + 建门/提醒/不合格生成卡片共用；一律走 bitable_cells 规范解析）
RECEIPT_PULL_FIELDS = [
    "物料批号",
    "物料名称(API)",
    "物料名称",
    "入库日期",
    "QC取样情况",
    "QC出报",
    "QA放行",
    "供应商",
    "厂家批号",
    "入库数量",
]

_SCAN_PAGE_LIMIT = 500
_SCAN_MAX_PAGES = 10  # 分页上限防御（>5000 条截断，同 A 期清单拉取）


def qc_writeback_enabled() -> bool:
    """QC 链路 Base 写入开关（runtime 配置 qc_writeback_enabled，0/1）。

    读取异常/非法值一律按关闭处理（kill switch 语义：fail-safe off，
    对齐 A 期 bitable_writeback_enabled）。
    """
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    try:
        return int(runtime_store.get_value("qc_writeback_enabled")) == 1
    except Exception:  # noqa: BLE001 — 开关读不到 = 不写 Base
        logger.warning("QC 回写开关读取失败，按关闭处理", exc_info=True)
        return False


def qa_confirm_target() -> str:
    """QA 放行确认门投递目标（runtime 配置 qa_confirm_target）。

    群 chat_id 或 ou_ 开头个人 open_id；空值回落 env WAREHOUSE_TEST_CHAT_ID
    （开发/验收即测试群；生产在配置中心指向真实 QA 群/人）。
    """
    from app.core.config import get_settings
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    try:
        value = str(runtime_store.get_value("qa_confirm_target") or "").strip()
    except Exception:  # noqa: BLE001 — 读不到回落 env
        logger.warning("QA 确认门目标读取失败，回落 env", exc_info=True)
        value = ""
    return value or str(get_settings().WAREHOUSE_TEST_CHAT_ID or "")


# QC 链路确认门业务类型（confirm_request 确认闸门按此挂钩独立开关）
QA_RELEASE_BIZ = "qa_release"
QC_REJECTED_BIZ = "qc_rejected_disposition"
# 供应商准入门（V3.0 分期C §4.3）：把关人同为 QA，回写开关与 QC 链路共用
# qc_writeback_enabled（质询 Round 2 定案，不另立参数）
SUPPLIER_ADMIT_BIZ = "supplier_admission"
QC_GATE_BIZ_TYPES = (QA_RELEASE_BIZ, QC_REJECTED_BIZ, SUPPLIER_ADMIT_BIZ)

# 已放行态（链路3 上架通知覆盖；否决不通知）
RELEASED_VALUES = ("放行", "条件放行")

# QA 放行确认后回写映射（@confirmer/@today 由 confirm_request 惰性解析）
RELEASE_WRITEBACK: dict[str, Any] = {
    "QA放行": "放行",
    "QA放行人": "@confirmer",
    "放行提交时间": "@today",
}

# 处理方案门回写（处理方式留 Base 人工填，1C 二值语义同 A 期不合格清单门）
UNQUALIFIED_WRITEBACK: dict[str, Any] = {"处理日期": "@today"}

# 过期/取消门的重建限频（防取消循环轰炸；pending 优先级更高）
GATE_RATE_LIMIT = timedelta(hours=24)


def qc_writeback_allowed(business_type: str) -> bool:
    """某业务类型的确认门在当前开关组合下是否允许确认回写。

    非 QC 链路业务类型不受 qc_writeback_enabled 管辖（返回 True，
    由调用方的 A 期总开关统一裁决）。
    """
    if business_type not in QC_GATE_BIZ_TYPES:
        return True
    return qc_writeback_enabled()


# ── 镜像读取（链路4 前台：库存列表展示 / 驾驶舱待办）──


def qc_stage(
    sample: str | None, report: str | None, release: str | None
) -> str | None:
    """QC 闭环阶段分类（唯一事实源，dashboard 待办复用）。

    已闭环（放行/否决/条件放行）、免检物料、已出报不合格返回 None——
    不合格走处理流程（Ticket 07），免检无需检验。
    """
    if release:  # 放行/否决/条件放行 → 已闭环
        return None
    if report == "已出报（合格）":
        return "待放行"
    if report in ("已出报（不合格）", "免检物料"):
        return None
    if sample in (None, "未取样"):
        return "待取样"
    return "待出报"


async def get_qc_status_by_batches(
    db: AsyncSession, batch_nos: list[str]
) -> dict[str, WarehouseQcStatus]:
    """批号 → QC 镜像行（库存列表展示口径）。

    同批号多条 receipt（分次收货）时未放行的行更可操作，优先返回；
    同等开放度取最近扫描的行。无镜像的批号缺席于结果。
    """
    unique = {b for b in batch_nos if b}
    if not unique:
        return {}
    rows = (
        await db.execute(
            select(WarehouseQcStatus).where(
                WarehouseQcStatus.batch_no.in_(unique),
                WarehouseQcStatus.is_deleted.is_(False),
            )
        )
    ).scalars()
    result: dict[str, WarehouseQcStatus] = {}
    for row in rows:
        current = result.get(row.batch_no)
        if current is None or _display_preferred(row, current):
            result[row.batch_no] = row
    return result


def _display_preferred(candidate: WarehouseQcStatus, current: WarehouseQcStatus) -> bool:
    """展示优先级：未放行（可操作）> 已放行；同等开放度取最近扫描。"""
    candidate_open = candidate.release_status is None
    current_open = current.release_status is None
    if candidate_open != current_open:
        return candidate_open
    return candidate.scanned_at > current.scanned_at


def _receipt_date(fields: dict[str, Any]) -> date | None:
    """入库日期单元格（毫秒时间戳，含类型包裹）→ date；缺失返回 None。"""
    ms = cell_number(fields.get("入库日期"))
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def _status_text(value: Any) -> str | None:
    """状态单元格 → 规范文本；空值统一 None（幂等比较口径）。"""
    text = cell_text(value).strip()
    return text or None


async def _search_pages(
    adapter: Any, *, filter_json: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """分页拉取 material_receipt（上限防御）。"""
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(_SCAN_MAX_PAGES):
        page = await adapter.search_records_page(
            "material_receipt",
            filter_json=filter_json,
            field_names=RECEIPT_PULL_FIELDS,
            limit=_SCAN_PAGE_LIMIT,
            page_token=page_token,
        )
        records.extend(page.get("records") or [])
        page_token = page.get("page_token")
        if not page_token:
            break
    return records


async def fetch_receipt_records(adapter: Any) -> list[dict[str, Any]]:
    """分页拉取 material_receipt 全量（窗口过滤由调用方本地执行）。

    真机实测（2026-09-18 探针，Ticket 08）：测试版 Base 的 search filter
    对日期字段不支持任何范围操作符（>=/>/within 均 99992402），单选 is
    可用——日期过滤为死路径，直接全量分页 + 本地窗口过滤。
    """
    return await _search_pages(adapter, filter_json=None)


def _parse_mirror_state(fields: dict[str, Any]) -> dict[str, Any]:
    """receipt 记录 fields → 镜像列值（规范解析；物料名称 API 字段优先）。

    supplier / vendor_batch_no / quantity 不入镜像表，供确认门卡片与
    不合格记录生成使用。
    """
    return {
        "batch_no": cell_text(fields.get("物料批号"))[:100],
        "material_name": (
            cell_text(fields.get("物料名称(API)")) or cell_text(fields.get("物料名称"))
        )[:200],
        "receipt_date": _receipt_date(fields),
        "sample_status": _status_text(fields.get("QC取样情况")),
        "report_status": _status_text(fields.get("QC出报")),
        "release_status": _status_text(fields.get("QA放行")),
        "supplier": cell_text(fields.get("供应商"))[:200],
        "vendor_batch_no": cell_text(fields.get("厂家批号"))[:100],
        "quantity": cell_number(fields.get("入库数量")),
    }


_MIRROR_STATE_KEYS = (
    "batch_no",
    "material_name",
    "receipt_date",
    "sample_status",
    "report_status",
    "release_status",
)


# ── 超期提醒（链路2：alert_records 幂等开单 + 仅新开推送）──


def _alert_material_id(record_id: str) -> uuid.UUID:
    """receipt record_id → 稳定合成 UUID（alert_records 幂等键）。"""
    return uuid.uuid5(_ALERT_NAMESPACE, record_id)


async def fetch_report_days_override(adapter: Any) -> dict[str, int]:
    """material_master 物料级出报天数覆盖（「实际物料：请检后出报天数」）。

    按物料名称精确匹配；空值/缺行不覆盖（回落 alert_rules 全局默认）。
    """
    page = await adapter.search_records_page(
        "material_master",
        filter_json=None,
        field_names=["物料名称", "实际物料：请检后出报天数"],
        limit=500,
        page_token=None,
    )
    result: dict[str, int] = {}
    for record in page.get("records") or []:
        fields = record.get("fields") or {}
        name = cell_text(fields.get("物料名称")).strip()
        days = cell_number(fields.get("实际物料：请检后出报天数"))
        if name and days is not None and days > 0:
            result[name] = int(days)
    return result


@dataclass
class _OverdueItem:
    """单条超期提醒（开单 + 推送共用结构）。"""

    rule_key: str
    record_id: str
    batch_no: str
    material_name: str
    waited_days: int
    kind: str  # sample | report


def _overdue_items(
    parsed: list[tuple[str, dict[str, Any]]],
    *,
    now: datetime,
    sample_days: int,
    report_days_global: int,
    report_days_override: dict[str, int],
) -> list[_OverdueItem]:
    """开环记录的超期判定（年龄从入库日期起算；免检/无需取不参与对应阶段）。"""
    items: list[_OverdueItem] = []
    for record_id, state in parsed:
        receipt_date = state["receipt_date"]
        if receipt_date is None:
            continue
        age = (now.date() - receipt_date).days
        stage = qc_stage(
            state["sample_status"], state["report_status"], state["release_status"]
        )
        if stage == "待取样" and age >= sample_days:
            items.append(
                _OverdueItem(
                    rule_key=QC_SAMPLE_RULE,
                    record_id=record_id,
                    batch_no=state["batch_no"],
                    material_name=state["material_name"],
                    waited_days=age,
                    kind="sample",
                )
            )
        elif stage == "待出报":
            days = report_days_override.get(state["material_name"], report_days_global)
            if age >= days:
                items.append(
                    _OverdueItem(
                        rule_key=QC_REPORT_RULE,
                        record_id=record_id,
                        batch_no=state["batch_no"],
                        material_name=state["material_name"],
                        waited_days=age,
                        kind="report",
                    )
                )
    return items


async def _existing_alert_keys(
    db: AsyncSession, rule_key: str
) -> tuple[set[tuple[uuid.UUID, str]], set[tuple[uuid.UUID, str]]]:
    """(open 键集, 人工已解决键集)——仅新开推送的去重依据。"""
    rows = (
        await db.execute(
            select(WarehouseAlertRecord).where(
                WarehouseAlertRecord.rule_key == rule_key,
                WarehouseAlertRecord.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    open_keys = {
        (r.material_id, r.batch_no) for r in rows if r.status == "open"
    }
    manual_keys = {
        (r.material_id, r.batch_no)
        for r in rows
        if r.status == "resolved" and r.resolved_by is not None
    }
    return open_keys, manual_keys


async def _run_overdue_alerts(
    db: AsyncSession,
    adapter: Any,
    parsed: list[tuple[str, dict[str, Any]]],
    now: datetime,
) -> dict[str, int]:
    """链路2 主流程：阈值读取 → 超期判定 → 幂等开单 → 仅新开推送。

    单条失败不影响镜像主流程（调用方捕获记日志）。
    """
    # 延迟 import 解模块环：intelligence → dashboard → 本模块
    from app.modules.warehouse.intelligence import (  # noqa: SLF001 — 同包内部复用
        _rule_enabled,
        apply_alert_records,
        get_rule_threshold,
    )
    from app.modules.warehouse.push_center import events

    sample_days = int(
        (await get_rule_threshold(db, QC_SAMPLE_RULE, {"days": DEFAULT_SAMPLE_DAYS}))[
            "days"
        ]
    )
    report_days_global = int(
        (await get_rule_threshold(db, QC_REPORT_RULE, {"days": DEFAULT_REPORT_DAYS}))[
            "days"
        ]
    )
    enabled = {
        rule: await _rule_enabled(db, rule) for rule in (QC_SAMPLE_RULE, QC_REPORT_RULE)
    }
    report_days_override = (
        await fetch_report_days_override(adapter)
        if enabled[QC_REPORT_RULE]
        else {}
    )
    items = [
        item
        for item in _overdue_items(
            parsed,
            now=now,
            sample_days=sample_days,
            report_days_global=report_days_global,
            report_days_override=report_days_override,
        )
        if enabled[item.rule_key]
    ]

    newly_opened: list[_OverdueItem] = []
    counts = {QC_SAMPLE_RULE: 0, QC_REPORT_RULE: 0}
    for rule_key in (QC_SAMPLE_RULE, QC_REPORT_RULE):
        rule_items = [i for i in items if i.rule_key == rule_key]
        counts[rule_key] = len(rule_items)
        # 规则停用 → rule_items 恒空 → apply 空集 = 既有 open 自动解决（停用即清理）
        open_keys, manual_keys = await _existing_alert_keys(db, rule_key)
        for item in rule_items:
            key = (_alert_material_id(item.record_id), item.batch_no)
            if key not in open_keys and key not in manual_keys:
                newly_opened.append(item)
        await apply_alert_records(
            db,
            rule_key,
            [
                {
                    "material_id": _alert_material_id(i.record_id),
                    "material_code": i.batch_no[:50],
                    "material_name": i.material_name[:200],
                    "batch_no": i.batch_no[:100],
                    "detail": {
                        "waited_days": i.waited_days,
                        "kind": i.kind,
                        "record_id": i.record_id,
                    },
                }
                for i in rule_items
            ],
        )

    pushed = 0
    if newly_opened:
        try:
            await events.fire_push_event(
                db,
                "qc_progress_alert",
                {
                    "items": [
                        {
                            "material_name": i.material_name,
                            "batch_no": i.batch_no,
                            "waited_days": i.waited_days,
                            "kind": i.kind,
                        }
                        for i in newly_opened
                    ]
                },
            )
            pushed = len(newly_opened)
        except Exception:  # noqa: BLE001 — 推送失败不影响扫描与开单
            logger.exception("QC 超期提醒推送失败（%d 条）", len(newly_opened))
    return {
        "alert_sample": counts[QC_SAMPLE_RULE],
        "alert_report": counts[QC_REPORT_RULE],
        "alert_pushed": pushed,
    }


async def run_qc_scan(
    db: AsyncSession,
    now: datetime,
    *,
    adapter: Any | None = None,
) -> dict[str, int]:
    """QC 扫描单入口（链路2/3/4 驱动核心）。

    拉取 → 本地窗口过滤 → 与镜像对比 → upsert（record_id 幂等；状态未变
    的行零写入）→ 超期提醒（alert_records 幂等开单 + 仅新开推送）。
    返回 {"pulled", "mirrored", "created", "updated",
    "alert_sample", "alert_report", "alert_pushed"}。
    本函数不 commit（由调用方 session 上下文统一提交/回滚）。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    adapter = adapter or WarehouseBitableAdapter()
    window_start = now - timedelta(days=SCAN_WINDOW_DAYS)
    records = await fetch_receipt_records(adapter)

    # 本地窗口过滤兜底：无入库日期的记录保留（新登记可能未填日期）
    in_window: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        record_id = str(record.get("record_id") or "")
        if not record_id or record_id in seen:
            continue
        fields = record.get("fields") or {}
        receipt_date = _receipt_date(fields)
        if receipt_date is not None and receipt_date < window_start.date():
            continue
        seen.add(record_id)
        in_window.append(record)

    existing = {
        row.record_id: row
        for row in (
            await db.execute(
                select(WarehouseQcStatus).where(
                    WarehouseQcStatus.record_id.in_(seen),
                    WarehouseQcStatus.is_deleted.is_(False),
                )
            )
        ).scalars()
    }

    created = 0
    updated = 0
    parsed: list[tuple[str, dict[str, Any]]] = []
    released_transitions: list[tuple[str, dict[str, Any]]] = []
    for record in in_window:
        record_id = str(record["record_id"])
        state = _parse_mirror_state(record.get("fields") or {})
        parsed.append((record_id, state))
        row = existing.get(record_id)
        if row is None:
            db.add(WarehouseQcStatus(record_id=record_id, scanned_at=now, **_mirror_columns(state)))
            created += 1
            continue
        # 放行变迁（旧值非放行态 → 新值放行/条件放行）：上架通知唯一触发点；
        # 首扫无旧行不触发（部署前的历史放行不补发）
        if (
            row.release_status != state["release_status"]
            and state["release_status"] in RELEASED_VALUES
        ):
            released_transitions.append((record_id, state))
        if any(
            getattr(row, key) != state[key] for key in _MIRROR_STATE_KEYS
        ):
            for key in _MIRROR_STATE_KEYS:
                setattr(row, key, state[key])
            row.scanned_at = now
            updated += 1
    await db.flush()

    # 链路2：超期提醒（失败不影响镜像主流程，记日志继续）
    alert_summary = {"alert_sample": 0, "alert_report": 0, "alert_pushed": 0}
    try:
        alert_summary = await _run_overdue_alerts(db, adapter, parsed, now)
    except Exception:  # noqa: BLE001 — 提醒链路异常不回滚镜像
        logger.exception("QC 超期提醒链路异常（镜像已完成）")

    # 链路3：QA 放行确认门 + 放行上架通知 + 否决分支（同样隔离失败）
    gates_created = 0
    release_notified = 0
    rejected_summary = {"unqualified_created": 0, "rejected_gates": 0}
    try:
        gates_created = await _create_release_gates(db, parsed, now)
        release_notified = await _notify_released(db, released_transitions)
        rejected_summary = await _ensure_rejected_disposition(db, adapter, parsed, now)
    except Exception:  # noqa: BLE001 — 建门/通知/生成异常不回滚镜像
        logger.exception("QA 放行链路异常（镜像已完成）")

    logger.info(
        "QC 扫描完成: pulled=%d mirrored=%d created=%d updated=%d "
        "alert_sample=%d alert_report=%d alert_pushed=%d gates=%d released=%d "
        "unqualified=%d rejected_gates=%d",
        len(in_window), len(in_window), created, updated,
        alert_summary["alert_sample"], alert_summary["alert_report"],
        alert_summary["alert_pushed"], gates_created, release_notified,
        rejected_summary["unqualified_created"], rejected_summary["rejected_gates"],
    )
    return {
        "pulled": len(in_window),
        "mirrored": len(in_window),
        "created": created,
        "updated": updated,
        **alert_summary,
        "gates_created": gates_created,
        "release_notified": release_notified,
        **rejected_summary,
    }


def _mirror_columns(state: dict[str, Any]) -> dict[str, Any]:
    """镜像列取值（parsed state → WarehouseQcStatus 列子集，剔除 supplier）。"""
    return {key: state[key] for key in _MIRROR_STATE_KEYS}


# ── QA 放行确认门与放行通知（链路3 主线）──


async def _create_and_send_gate(
    db: AsyncSession,
    *,
    business_type: str,
    title: str,
    summary: str,
    ref_table: str,
    ref_record_ids: list[str],
    target: str,
    payload: dict[str, Any],
    writeback: dict[str, Any],
) -> bool:
    """建确认单并发卡（放行门/处理方案门共用；发送失败记日志不抛）。"""
    from app.modules.warehouse import confirm_request as cr

    request = await cr.create_request(
        db,
        business_type=business_type,
        title=title,
        summary=summary,
        ref_table=ref_table,
        ref_record_ids=ref_record_ids,
        target=target,
        payload=payload,
        writeback=writeback,
    )
    sent = await cr.send_request_card(request)
    if not sent:
        logger.error(
            "确认卡发送失败: request_no=%s target=%s", request.request_no, target
        )
    return sent


async def _recent_gate_exists(
    db: AsyncSession, business_type: str, record_id: str, now: datetime
) -> bool:
    """确认门去重：pending 门存在，或 24h 内建过门（过期/取消限频）。"""
    from sqlalchemy import func, or_

    from app.modules.warehouse.models import WarehouseConfirmRequest

    count = (
        await db.execute(
            select(func.count()).select_from(WarehouseConfirmRequest).where(
                WarehouseConfirmRequest.business_type == business_type,
                WarehouseConfirmRequest.ref_record_ids.contains([record_id]),
                WarehouseConfirmRequest.is_deleted.is_(False),
                or_(
                    WarehouseConfirmRequest.status == "pending",
                    WarehouseConfirmRequest.created_at >= now - GATE_RATE_LIMIT,
                ),
            )
        )
    ).scalar_one()
    return count > 0


async def _create_release_gates(
    db: AsyncSession, parsed: list[tuple[str, dict[str, Any]]], now: datetime
) -> int:
    """出报合格且未放行的记录 → 建 QA 放行确认门（开关关则整体跳过）。

    去重：pending 门存在不重建；24h 内建过门（含过期/取消）限频跳过——
    过期/取消后 ≥24h 自动重建，被确认人忽略的单子不会被永久遗漏。
    """
    if not qc_writeback_enabled():
        return 0
    candidates = [
        (record_id, state)
        for record_id, state in parsed
        if state["report_status"] == "已出报（合格）" and not state["release_status"]
    ]
    if not candidates:
        return 0
    target = qa_confirm_target()
    created = 0
    for record_id, state in candidates:
        if await _recent_gate_exists(db, QA_RELEASE_BIZ, record_id, now):
            continue
        receipt_date = state["receipt_date"]
        summary = (
            f"**物料** {state['material_name'] or '-'}　**批号** {state['batch_no'] or '-'}\n"
            f"**供应商** {state['supplier'] or '-'}　"
            f"**入库日期** {receipt_date.isoformat() if receipt_date else '-'}\n\n"
            "QC 已出报（合格）。点击「确认」将回写台账：QA放行=放行、"
            "QA放行人=您、放行提交时间=今天；如需条件放行或否决，"
            "请直接在多维表格操作（本卡可忽略）。"
        )
        await _create_and_send_gate(
            db,
            business_type=QA_RELEASE_BIZ,
            title="QA 放行确认",
            summary=summary,
            ref_table="material_receipt",
            ref_record_ids=[record_id],
            target=target,
            payload={
                "record_id": record_id,
                "batch_no": state["batch_no"],
                "material_name": state["material_name"],
            },
            writeback=dict(RELEASE_WRITEBACK),
        )
        created += 1
    return created


async def _notify_released(
    db: AsyncSession, released_transitions: list[tuple[str, dict[str, Any]]]
) -> int:
    """放行变迁 → 推仓库群上架通知（确认门回写与 Base 手工放行同覆盖）。"""
    if not released_transitions:
        return 0
    from app.modules.warehouse.push_center import events

    notified = 0
    for record_id, state in released_transitions:
        try:
            await events.fire_push_event(
                db,
                "release_notify",
                {
                    "material_name": state["material_name"],
                    "batch_no": state["batch_no"],
                    "release_type": state["release_status"],
                },
            )
            notified += 1
        except Exception:  # noqa: BLE001 — 单条通知失败继续
            logger.exception("放行上架通知推送失败（record_id=%s）", record_id)
    return notified


# ── 否决分支：不合格记录生成 + 处理方案确认门（链路3 支线）──


async def _find_unqualified_by_source(adapter: Any, record_id: str) -> str | None:
    """按 SourceID=receipt record_id 查 unqualified_stock（Base 权威去重）。"""
    page = await adapter.search_records_page(
        "unqualified_stock",
        filter_json={
            "conjunction": "and",
            "conditions": [
                {"field_name": "SourceID", "operator": "is", "value": [record_id]}
            ],
        },
        field_names=["SourceID"],
        limit=5,
        page_token=None,
    )
    records = page.get("records") or []
    return str(records[0].get("record_id") or "") if records else None


def _unqualified_fields(
    state: dict[str, Any], record_id: str, now: datetime
) -> dict[str, Any]:
    """receipt 状态 → unqualified_stock 生成字段（登记人/不合格项目留空人工后补）。"""
    from app.modules.warehouse.bitable_schema import validate_write_fields

    receipt_date = state["receipt_date"]
    fields: dict[str, Any] = {
        "SourceID": record_id,
        "物料名称": state["material_name"],
        "厂家批号": state["vendor_batch_no"],
        "内部批号": state["batch_no"],
        "登记时间": int(now.timestamp() * 1000),
    }
    if receipt_date is not None:
        # Base date 字段写入契约：毫秒时间戳（对齐 @today / submit._parse_date_ms）
        fields["到货日期"] = int(
            datetime(
                receipt_date.year, receipt_date.month, receipt_date.day, tzinfo=UTC
            ).timestamp()
            * 1000
        )
    if state["quantity"] is not None:
        fields["到货数量"] = state["quantity"]
    validate_write_fields("unqualified_stock", fields)
    return fields


async def _ensure_rejected_disposition(
    db: AsyncSession,
    adapter: Any,
    parsed: list[tuple[str, dict[str, Any]]],
    now: datetime,
) -> dict[str, int]:
    """出报不合格 → 自动生成不合格记录 + 即时处理方案确认门（开关关整体跳过）。

    生成去重以 Base 为权威（SourceID=receipt record_id）；记录已存在但门
    缺失时自愈补门（生成成功/建门失败的中间态下轮补齐）。
    """
    if not qc_writeback_enabled():
        return {"unqualified_created": 0, "rejected_gates": 0}
    rejected = [
        (record_id, state)
        for record_id, state in parsed
        if state["report_status"] == "已出报（不合格）"
    ]
    if not rejected:
        return {"unqualified_created": 0, "rejected_gates": 0}
    target = qa_confirm_target()
    created = 0
    gates = 0
    for record_id, state in rejected:
        unq_record_id = await _find_unqualified_by_source(adapter, record_id)
        if unq_record_id is None:
            try:
                fields = _unqualified_fields(state, record_id, now)
                result = await adapter.create_record("unqualified_stock", fields)
                unq_record_id = str(result.get("record_id") or "")
            except Exception:  # noqa: BLE001 — 单条生成失败继续下一条
                logger.exception(
                    "不合格记录生成失败（receipt record_id=%s）", record_id
                )
                continue
            if not unq_record_id:
                logger.error("不合格记录生成未返回 record_id（receipt %s）", record_id)
                continue
            created += 1
        if await _recent_gate_exists(db, QC_REJECTED_BIZ, unq_record_id, now):
            continue
        receipt_date = state["receipt_date"]
        await _create_and_send_gate(
            db,
            business_type=QC_REJECTED_BIZ,
            title="不合格物料处理方案确认",
            summary=(
                f"**物料** {state['material_name'] or '-'}　**批号** {state['batch_no'] or '-'}\n"
                f"**厂家批号** {state['vendor_batch_no'] or '-'}　"
                f"**入库日期** {receipt_date.isoformat() if receipt_date else '-'}\n\n"
                "QC 出报不合格，已自动生成不合格物料记录。点击「确认」表示处理方案"
                "已制定并回写台账「处理日期=今天」；处理方式请在多维表格中人工填写。"
            ),
            ref_table="unqualified_stock",
            ref_record_ids=[unq_record_id],
            target=target,
            payload={
                "receipt_record_id": record_id,
                "unqualified_record_id": unq_record_id,
                "batch_no": state["batch_no"],
                "material_name": state["material_name"],
            },
            writeback=dict(UNQUALIFIED_WRITEBACK),
        )
        gates += 1
    return {"unqualified_created": created, "rejected_gates": gates}
