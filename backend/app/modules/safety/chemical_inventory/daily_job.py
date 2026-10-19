"""危化品库存每日任务（sheet 源编排 + 归档总表直读兜底）。

2026-10-19 二期退役（P2）：旧链路「危险品日报群拉 Excel → 异构解析 → 写 Bitable
总表 → 镜像回拉」整体删码（excel_parser/daily_update/import_excel/realtime handler
随本批退役）；Bitable 总表停写冻结为历史只读。数据源唯一事实源 = 飞书电子表格
《危险品日报表》（SAFETY_CHEMICAL_INVENTORY_SOURCE=sheet，2026-10-19 起全面启用）。

流程（每天 19:30，scheduler 调度）：
  1. sheet 模式：直读《危险品日报表》全量 → 内存重算风险（不回写源表）→
     对比昨日快照做每日分析（超量 + 急剧上升/下降 + 主要危化品汇总），
     落今日 daily 快照，把日报投「安全速递」总卡（危险品日报群同款加投）；
  2. bitable 模式（回滚/归档口径）：直读已冻结的总表走同一收尾流程。
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.database import async_session_factory
from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.chemical_inventory.daily_report import (
    compute_daily_analysis,
    render_daily_report,
)
from app.modules.safety.chemical_inventory.snapshots import (
    KIND_DAILY,
    KIND_NIGHTLY,
    load_prev_daily_snapshot_with_source,
    take_snapshot,
)
from app.modules.safety.feishu.notification import send_group_card

if TYPE_CHECKING:
    from app.modules.safety.feishu.daily_digest import DigestCell

logger = logging.getLogger(__name__)

DANGEROUS_GOODS_DAILY_CHAT_ID = "oc_ae9c3a305430cb196e42130f69b052bc"   # 危险品日报群（数据源群，日报加投目标）
# 主推送目标经调度器 DB 配置传入（send_daily_summary(chat_id=...)）；
# env SAFETY_CHEMICAL_INVENTORY_DAILY_CHAT_ID 仅作调度器播种/展示回退
# （service/scheduler_config.py 解析，env > DB 活行 > 代码默认）。


def _extra_chat_enabled() -> str | None:
    """附加投递群生效 chat_id；off/空停用返回 None。

    env 可改目标或置 off/空停用（2026-09-30 需求）；
    读取链：env > DB 活行（app_config，30s TTL）> 代码默认危险品日报群。
    """
    raw = _app_config_store.get_str(
        "SAFETY_CHEMICAL_DAILY_EXTRA_CHAT_ID", DANGEROUS_GOODS_DAILY_CHAT_ID,
    )
    extra = (raw or "").strip()
    if not extra or extra.lower() in ("off", "false", "none"):
        return None
    return extra


def _direct_enabled() -> bool:
    """直读总开关（sheet 源隐含直读语义；惰性导入避免日常模块加载拉起直读包）。"""
    from app.modules.safety.service.chemical_inventory_direct import config

    return config.direct_enabled()


def _sheet_source_enabled() -> bool:
    """《危险品日报表》sheet 源开关（惰性导入）。"""
    from app.modules.safety.service.chemical_inventory_direct import config

    return config.sheet_source_enabled()


async def _run_sheet_mode() -> dict[str, Any]:
    """sheet 源编排：直读《危险品日报表》→内存重算→分析/快照。

    - 不回写：风险值只在内存与快照（源表是人维护的唯一事实源）；
    - D6 revision：与已记录状态（{revision}|{日期}）比对，未变 → 日报标注
      「数据自 xx 未更新」+ 视图 updated_at 置 None（per-row 未更新标记如实）；
    - §5 骤降告警：行数较昨日 daily 快照骤降 >50% → sheet_alerts 红标（不静默接受源表被清空）；
    - D8 环比断点：昨日快照源 != sheet（NULL=legacy/总表口径）→ 本日不做环比并明示。
    """
    from app.modules.safety.service.chemical_inventory_direct.reader import open_reader
    from app.modules.safety.service.chemical_inventory_direct.risk import (
        scan_inventory_views,
    )

    reader = open_reader()
    views = await reader.fetch_all(strict=True)
    if not views:
        return {"source": "sheet", "skipped": True, "reason": "sheet_empty", "files": []}
    scan = await scan_inventory_views(views)

    sheet_alerts: list[str] = []
    compare_note: str | None = None
    async with async_session_factory() as db:
        today = (datetime.now(UTC) + timedelta(hours=8)).date()  # 北京时间
        prev_rows, prev_source = await load_prev_daily_snapshot_with_source(db, today)
        if prev_rows and prev_source != "sheet":
            # 切换首日：旧部门枚举行全体消失/新枚举行全体新增，环比必全量误报
            prev_rows = []
            compare_note = "数据源口径切换，本日不做环比"
        elif prev_rows and len(views) < len(prev_rows) * 0.5:
            sheet_alerts.append(
                f"行数骤降：今日 {len(views)} 行 vs 昨日 {len(prev_rows)} 行，请核实《危险品日报表》是否被误清空"
            )
        inner = getattr(reader, "_inner", None) or reader
        not_updated_note = await _apply_revision_freshness(db, inner, views, today)
        analysis = compute_daily_analysis(
            views, prev_rows, compare_skipped=compare_note is not None,
        )
        await take_snapshot(db, today, kind=KIND_DAILY, records=views, source="sheet")
        await db.commit()

    warnings = [v for v in views if v.risk_flag == "warn"]
    return {
        "source": "sheet",
        "files": [],
        "sync": {"skipped": True, "reason": "sheet_source"},
        "scan": scan,
        "warnings": warnings,
        "analysis": analysis,
        "total_updated": 0,
        "total_created": 0,
        "total_parsed": 0,
        # 红标告警（速递格变红）：仅行数骤降类
        "sheet_alerts": sheet_alerts,
        # 源表异常（未映射子表/列异常等，⚠️ 级）：与红标分离，防告警疲劳
        "sheet_anomalies": list(getattr(inner, "anomalies", []) or []),
        "compare_note": compare_note,
        "not_updated_note": not_updated_note,
    }


async def _run_bitable_mode() -> dict[str, Any]:
    """bitable 归档口径编排：直读已冻结总表 → 内存重算 → 分析/快照（回滚路径）。

    旧 Excel/镜像链路已退役（P2）：本函数是 SAFETY_CHEMICAL_INVENTORY_SOURCE
    拨回 bitable 后的唯一日编排序，总表只读不写（风险值不回写冻结表）。
    """
    from app.modules.safety.service.chemical_inventory_direct.reader import open_reader
    from app.modules.safety.service.chemical_inventory_direct.risk import (
        scan_inventory_views,
    )

    reader = open_reader()
    views = await reader.fetch_all(strict=True)
    scan = await scan_inventory_views(views)

    compare_note: str | None = None
    async with async_session_factory() as db:
        today = (datetime.now(UTC) + timedelta(hours=8)).date()  # 北京时间
        prev_snapshot, prev_source = await load_prev_daily_snapshot_with_source(db, today)
        if prev_snapshot and prev_source == "sheet":
            # D8 对称断点（回滚日）：昨日 sheet 口径 vs 今日总表口径，环比必全量误报
            prev_snapshot = []
            compare_note = "数据源口径切换（回滚至总表），本日不做环比"
        analysis = compute_daily_analysis(
            views, prev_snapshot, compare_skipped=compare_note is not None,
        )
        await take_snapshot(db, today, kind=KIND_DAILY, records=views)
        await db.commit()

    warnings = [v for v in views if v.risk_flag == "warn"]
    return {
        "source": "bitable",
        "files": [],
        "sync": {"skipped": True, "reason": "bitable_archive_direct"},
        "scan": scan,
        "warnings": warnings,
        "analysis": analysis,
        "compare_note": compare_note,
        "total_updated": 0,
        "total_created": 0,
        "total_parsed": 0,
    }


SHEET_REVISION_KEY = "SAFETY_CHEMICAL_INVENTORY_SHEET_REVISION"


async def _apply_revision_freshness(
    db: Any, inner_reader: Any, views: list[Any], today: Any
) -> str | None:
    """D6「数据未更新」：revision 与已记录状态比对。

    inner_reader：真实 SheetsInventoryReader（调用方已剥掉 TTL 缓存包装层）。
    未变 → 视图 updated_at 置 None（compute_daily_analysis 依此把零变化物料
    标「未更新」，车间没填表不会被误读为平稳）并返回标注文案；
    变化 → 状态落库（同事务，app_config set_value 含审计）。
    revision 读取失败/不可用（如 bitable reader）→ 不标注，行为退化为旧语义。
    """
    revision = getattr(inner_reader, "last_revision", None)
    if revision is None:
        return None
    raw = _app_config_store.get_str(SHEET_REVISION_KEY, "")
    stored_rev, _, stored_date = (raw or "").partition("|")
    if str(revision) == stored_rev and stored_date:
        for v in views:
            v.updated_at = None
        return f"数据自 {stored_date} 未更新（表格 revision 无变化）"
    await _app_config_store.set_value(
        db, SHEET_REVISION_KEY, f"{revision}|{today.isoformat()}",
        operator_name="chemical-sheet-daily",
    )
    return None


async def run_nightly_snapshot() -> dict[str, Any]:
    """每日 23:00：日终留一张库存全量快照（kind=nightly，纯存档不分析不推送）。

    读取链与日报一致（SAFETY_CHEMICAL_INVENTORY_SOURCE）：sheet 模式直读
    《危险品日报表》并内存重算风险标记；bitable 模式快照自取 ORM 镜像。
    与 19:30 的 daily 快照 kind 互斥，日报/周报环比口径不受影响。
    """
    from app.modules.safety.service.chemical_inventory_direct.risk import (
        scan_inventory_views,
    )

    rows: list[Any] | None = None
    source: str | None = None
    scan: dict[str, int] | None = None
    if _direct_enabled():
        from app.modules.safety.service.chemical_inventory_direct.reader import (
            open_reader,
        )

        rows = await open_reader().fetch_all(strict=True)
        scan = await scan_inventory_views(rows)
        if _sheet_source_enabled():
            source = "sheet"
    async with async_session_factory() as db:
        today = (datetime.now(UTC) + timedelta(hours=8)).date()  # 北京时间
        count = await take_snapshot(
            db, today, kind=KIND_NIGHTLY, records=rows, source=source,
        )
        await db.commit()
    return {
        "snapshot_date": today.isoformat(),
        "kind": KIND_NIGHTLY,
        "records": count,
        "source": source or "bitable",
        **({"scan": scan} if scan is not None else {}),
    }


async def run_scheduled_daily_update() -> dict[str, Any]:
    """执行每日定时更新：直读当前源 → 内存重算 → 分析/快照 → 返回结果。"""
    if _sheet_source_enabled():
        return await _run_sheet_mode()
    return await _run_bitable_mode()


def build_daily_summary(result: dict[str, Any]) -> str:
    """生成发送到群聊的日报 Markdown（危化品库存每日分析日报）。

    sheet 模式附加标注（D6/D8/§5）：未更新/口径切换/骤降红标前置在正文之前。
    """
    if result.get("skipped"):
        reason = (
            "《危险品日报表》读取异常或无数据"
            if result.get("source") == "sheet"
            else "未配置/跳过"
        )
        return f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n⚠️ {reason}"
    analysis = result.get("analysis")
    if analysis is None:
        return "📅 无分析结果"
    content = render_daily_report(analysis)
    notes: list[str] = []
    if result.get("not_updated_note"):
        notes.append(f"⚠️ {result['not_updated_note']}")
    if result.get("compare_note"):
        notes.append(f"ℹ️ {result['compare_note']}")
    for alert in result.get("sheet_alerts") or []:
        notes.append(f"🚨 {alert}")
    for anomaly in result.get("sheet_anomalies") or []:
        notes.append(f"⚠️ 源表异常：{anomaly}")
    if notes:
        return "\n".join(notes) + "\n\n" + content
    return content


def _build_daily_cell(result: dict[str, Any], content: str) -> tuple[date, DigestCell]:
    """由任务结果构建「安全速递」格子（有分析/无数据两形态）。

    Returns:
        (报告日期, 格子)：有分析取 analysis.report_date；无分析用北京时间今天。
    """
    from app.modules.safety.feishu.daily_digest import DigestCell

    analysis = result.get("analysis")
    if analysis is not None:
        top_over = ""
        if analysis.over_limit_items:
            first = analysis.over_limit_items[0]
            material = getattr(first, "material", "")
            top_over = f"{material} 超量" if material else ""
        return analysis.report_date, DigestCell(
            tag_color=(
                "red" if result.get("sheet_alerts")
                else ("orange" if analysis.over_limit_count else "green")
            ),
            tag_text="危化品库存",
            title="危化品库存日报",
            stats=(
                ("🚨 行数骤降 · " if result.get("sheet_alerts") else "")
                + f"⚠️ 超量 **{analysis.over_limit_count}** · "
                f"急升 {analysis.surge_count} · 急降 {analysis.decline_count}"
            ),
            zone=top_over or ("库存平稳" if not analysis.has_risk() else ""),
            detail=content,
        )
    return (datetime.now(UTC) + timedelta(hours=8)).date(), DigestCell(
        tag_color="red" if result.get("sheet_alerts") else "grey",
        tag_text="危化品库存",
        title="危化品库存日报",
        stats="《危险品日报表》读取异常或无数据",
        zone=result.get("reason") or "",
        detail=content,
    )


async def send_daily_summary(result: dict[str, Any], chat_id: str | None = None) -> str | None:
    """把每日分析日报推送到配置群聊（发送目标唯一来源：调度器配置，不再回退 env）。

    总卡开启时只投「安全速递」格子（安全AI创新交流群不再单独发日报卡）。
    两种模式下均以同款速递版式追加投递「危险品日报」群（2026-09-30 需求，
    失败只告警不影响主推送；env SAFETY_CHEMICAL_DAILY_EXTRA_CHAT_ID=off 停用）。
    """
    effective_chat_id = chat_id
    if not effective_chat_id or effective_chat_id.startswith("#"):
        logger.info("安全AI创新交流群 chat_id 未配置，跳过日报推送")
        return None
    content = build_daily_summary(result)
    analysis = result.get("analysis")

    from app.modules.safety.feishu.daily_digest import (
        digest_enabled,
        send_digest_cell_card,
        upsert_daily_digest,
    )

    async def _send_extra_group(cell_date: date, cell: Any) -> None:
        """危险品日报群追加投递（单格速递版式，失败仅告警）。"""
        extra = _extra_chat_enabled()
        if not extra:
            return
        msg_id = await send_digest_cell_card(
            cell, chat_id=extra, title=f"📌 危化品库存日报 | {cell_date.isoformat()}",
        )
        if not msg_id:
            logger.warning("危化品库存日报追加投递危险品日报群失败: chat=%s", extra)

    if digest_enabled():
        cell_date, cell = _build_daily_cell(result, content)
        ok = await upsert_daily_digest(cell_date, "chemical_daily", cell)
        await _send_extra_group(cell_date, cell)
        return "digest" if ok else None

    if analysis is not None and analysis.has_risk():
        header_template = "red" if analysis.over_limit_count else "orange"
    else:
        header_template = "green"
    msg_id = await send_group_card(
        chat_id=effective_chat_id,
        title="危化品库存每日分析日报",
        content=content,
        header_template=header_template,
    )
    cell_date, cell = _build_daily_cell(result, content)
    await _send_extra_group(cell_date, cell)
    return msg_id
