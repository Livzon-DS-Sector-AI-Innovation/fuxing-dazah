"""运维触发执行面（agent-action-p3）：手动同步 / 手动跑审核 + 第 5 组三件。

- sync_domain_data：手动同步指定域镜像（fire/central/key_risk/special_op）
- run_workticket_review：手动跑作业票审核（date 可选，push 固定 False——
  推群另有 push_report_to_chat）
- freeze_standard_check：S1 季度定格（无参=今天，date 可选补跑定格日）
- scan_chemical_inventory：危化品全量风险扫描
- reseed_daily_digest：按日期重投速递格子（fire_alarm/special_op/special_op_pm）

工具体不重写业务逻辑：直接调各域 service；直读闸门/投格护栏照抄各 API
与调度链口径。直读短路返回 skipped=True + 说明（不是错误）；service 异常
捕获降级返回 success=False 不抛出（照 API 层降级模式）。仅 creator。
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from datetime import datetime as _datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

__all__ = [
    "sync_domain_data",
    "run_workticket_review",
    "freeze_standard_check",
    "scan_chemical_inventory",
    "reseed_daily_digest",
]

_SYNC_DOMAINS = ("fire", "central", "key_risk", "special_op")
_RESEED_KINDS = ("fire_alarm", "special_op", "special_op_pm")
_TZ_BJ = ZoneInfo("Asia/Shanghai")


def _bj_today() -> _date:
    return _datetime.now(_TZ_BJ).date()


def _next_quarter_start(d: _date) -> _date:
    for s in (
        _date(d.year, 1, 1), _date(d.year, 4, 1),
        _date(d.year, 7, 1), _date(d.year, 10, 1),
    ):
        if s >= d:
            return s
    return _date(d.year + 1, 1, 1)


async def sync_domain_data(
    ctx: RunContext[SafetyDeps],
    domain: str,
) -> dict[str, Any]:
    """手动同步指定域的 Bitable 镜像数据（写操作）。

    Args:
        domain: 域——fire（消防报警）/ central（中控报警）/
            key_risk（关键风险作业）/ special_op（特殊作业日报）

    示例：手动同步一下消防报警；把中控数据补同步一下。

    注意：此操作会拉取 Bitable 全量并更新本地镜像（可能需要数十秒），
    需要用户确认后才执行；确认卡应复述域名。直读模式下会如实返回
    「无需同步」的说明。
    """
    action = "domain_sync"
    dom = (domain or "").strip().lower()
    if dom not in _SYNC_DOMAINS:
        return {
            "success": False,
            "action": action,
            "message": f"未知域 {domain!r}，可选：{'/'.join(_SYNC_DOMAINS)}",
        }
    db = ctx.deps.db
    try:
        if dom == "fire":
            from app.modules.safety.service.fire_alarm import config as fire_config
            from app.modules.safety.service.fire_alarm.service import FireAlarmService

            if not fire_config.legacy_sync_job_active():
                return _skipped(action, dom, "直读模式已关闭全量同步（SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED=false）")
            synced, soft_deleted = await FireAlarmService(db).sync_from_bitable()
            return {
                "success": True, "action": action, "domain": dom, "skipped": False,
                "stats": {"synced_count": synced, "soft_deleted_count": soft_deleted},
                "message": f"同步完成，处理 {synced} 条，软删除 {soft_deleted} 条",
            }
        if dom == "central":
            from app.modules.safety.service.central_alarm import config as ca_config
            from app.modules.safety.service.central_alarm.service import CentralAlarmService

            if ca_config.direct_enabled():
                return _skipped(action, dom, "直读模式已开启，无需同步镜像")
            synced, soft_deleted = await CentralAlarmService(db).sync_from_bitable()
            return {
                "success": True, "action": action, "domain": dom, "skipped": False,
                "stats": {"synced_count": synced, "soft_deleted_count": soft_deleted},
                "message": f"同步完成，处理 {synced} 条，软删除 {soft_deleted} 条",
            }
        if dom == "key_risk":
            from app.modules.safety.service.key_risk_operation_report import (
                KeyRiskOperationReportService,
            )

            stats = await KeyRiskOperationReportService(db).sync_from_bitable()
            if isinstance(stats, dict) and stats.get("skipped"):
                return _skipped(action, dom, "直读模式下镜像同步已关闭，直接读 Bitable")
            return {
                "success": True, "action": action, "domain": dom, "skipped": False,
                "stats": stats,
                "message": "同步完成：" + "、".join(
                    f"{k} {v}" for k, v in (stats or {}).items()
                ),
            }
        # special_op
        from app.modules.safety.service.special_op_direct import config as so_config
        from app.modules.safety.service.special_operation_daily_report import (
            SpecialOperationDailyReportService,
        )

        if not so_config.legacy_sync_job_active():
            return _skipped(action, dom, "镜像同步已关闭（直读模式）：日报直接读多维表格，无需同步")
        synced = await SpecialOperationDailyReportService(db).sync_from_bitable()
        return {
            "success": True, "action": action, "domain": dom, "skipped": False,
            "stats": {"synced_count": synced},
            "message": f"同步完成，共处理 {synced} 条记录",
        }
    except Exception as exc:
        logger.exception("sync_domain_data(%s) failed", dom)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"success": False, "action": action, "domain": dom,
                "message": f"同步失败: {exc}"}


def _skipped(action: str, domain: str, message: str) -> dict[str, Any]:
    """直读短路：不是错误，如实告知无需同步。"""
    return {
        "success": True, "action": action, "domain": domain,
        "skipped": True, "stats": {}, "message": message,
    }


async def run_workticket_review(
    ctx: RunContext[SafetyDeps],
    date: str = "",
) -> dict[str, Any]:
    """手动跑一次作业票审核（写操作；不推群）。

    按 date 审核该日作业票（缺省今天），并复查前一日的违规整改情况。
    调度口径为每日 10 点自动审昨日票；本工具用于补跑/复看指定日期。
    结果同时落入速递格（按运行日）。

    Args:
        date: 审核日期 YYYY-MM-DD（缺省今天）

    示例：跑一次作业票审核；补跑一下昨天的作业票审核。

    注意：此操作会拉取平台作业票并写入审核结果，需要用户确认后才执行；
    确认卡应复述审核日期。报告全文不返回，可让用户去 Web 面板查看，
    或后续用 push_report_to_chat 推送。
    """
    action = "workticket_review_run"
    from app.modules.safety.workticket_review.service import WorkTicketReviewService

    raw = (date or "").strip()
    if raw:
        try:
            review_date = _date.fromisoformat(raw)
        except ValueError:
            return {
                "success": False, "action": action,
                "message": f"日期无效：{raw!r}（应为 YYYY-MM-DD）",
            }
    else:
        review_date = _bj_today()
    try:
        service = WorkTicketReviewService(ctx.deps.db, chat_id=None)
        result = await service.run_review(review_date, push=False)
    except Exception as exc:
        logger.exception("run_workticket_review failed")
        return {"success": False, "action": action,
                "message": f"作业票审核失败: {exc}"}
    # markdown_report 全文不进工具返回（体量大），保留摘要字段
    return {
        "success": True,
        "action": action,
        "date": str(result.get("date", review_date)),
        "total": result.get("total"),
        "reviewed": result.get("reviewed"),
        "violation_count": result.get("violation_count"),
        "compliant_count": result.get("compliant_count"),
        "data_insufficient": result.get("data_insufficient"),
        "message": (
            f"审核完成：{result.get('reviewed')}/{result.get('total')} 张，"
            f"违规 {result.get('violation_count')} 条"
        ),
    }


async def freeze_standard_check(
    ctx: RunContext[SafetyDeps],
    date: str = "",
) -> dict[str, Any]:
    """手动触发 S1 标准符合性季度定格（写操作）。

    目标周期由定格日推导（spec 口径）：4/1 定 Q1 终版、7/1 加 H1、
    10/1 定 Q3、1/1 加年度终版；非季度首日调用不产生定格（ran=False）。
    重复定格幂等 upsert，失败补跑安全；定格完成后按调度链同款投速递格。

    Args:
        date: 定格日 YYYY-MM-DD（缺省今天；补跑历史季度请传对应季首日，
            如补 Q3 传 10-01）

    示例：把季度定格跑一下；补跑一下三季度的定格。

    注意：此操作会重算快照并投速递格，需要用户确认后才执行；确认卡应
    复述定格日与目标周期。
    """
    action = "standard_check_freeze"
    from app.modules.safety.service.standard_check.freeze import (
        freeze_due,
        send_standard_compliance_digest,
    )

    raw = (date or "").strip()
    if raw:
        try:
            freeze_day = _date.fromisoformat(raw)
        except ValueError:
            return {
                "success": False, "action": action,
                "message": f"日期无效：{raw!r}（应为 YYYY-MM-DD）",
            }
    else:
        freeze_day = None  # 让 service 用北京时间今天
    try:
        result = await freeze_due(db=ctx.deps.db, today=freeze_day)
    except Exception as exc:
        logger.exception("freeze_standard_check failed")
        return {"success": False, "action": action,
                "message": f"定格失败: {exc}"}
    if result.no_source:
        return {
            "success": False, "action": action,
            "message": "核查表（Bitable）未配置或不可读，无法定格；请先在配置中心完成映射",
        }
    if not result.ran:
        today = freeze_day or _bj_today()
        nxt = _next_quarter_start(today)
        return {
            "success": False, "action": action, "ran": False,
            "message": (
                f"{today.isoformat()} 非季度定格日（定格日为每季首日：1/1、4/1、7/1、10/1），"
                f"本次未定格；下一个定格日是 {nxt.isoformat()}。"
                "如需补跑历史季度，请传对应季首日期（如 2026-10-01）"
            ),
        }
    await ctx.deps.db.commit()
    digest_stats: dict | None = None
    try:
        digest_stats = await send_standard_compliance_digest(result)
    except Exception as exc:
        logger.exception("standard_compliance digest after manual freeze failed")
    return {
        "success": True,
        "action": action,
        "ran": True,
        "frozen": result.frozen,
        "quarter_key": result.quarter_key,
        "targets": len(result.targets or []),
        "digest": digest_stats,
        "message": (
            f"定格完成：{result.quarter_key} 共 {result.frozen} 行快照"
            + ("；速递格已投递" if digest_stats else "")
        ),
    }


async def scan_chemical_inventory(ctx: RunContext[SafetyDeps]) -> dict[str, Any]:
    """手动触发危化品库存全量风险扫描（写操作）。

    重新分析全部库存记录（直读模式直读重算；镜像模式全量重算+按开关回写
    风险列），返回变更/预警/正常统计。

    示例：危化品全量扫描一下。

    注意：此操作会重算风险标记，需要用户确认后才执行。
    """
    action = "chemical_inventory_scan"
    from app.modules.safety.service.chemical_inventory import ChemicalInventoryService

    try:
        stats = await ChemicalInventoryService(ctx.deps.db).run_full_scan()
    except Exception as exc:
        logger.exception("scan_chemical_inventory failed")
        return {"success": False, "action": action,
                "message": f"扫描失败: {exc}"}
    return {
        "success": True,
        "action": action,
        "stats": stats,
        "message": (
            f"扫描完成：风险标记变更 {stats.get('changed', 0)} 条，"
            f"预警 {stats.get('warn_count', 0)} 条，正常 {stats.get('normal_count', 0)} 条"
        ),
    }


async def _reseed_special_op(target_date: _date, mode: str) -> dict[str, Any]:
    """重投特殊作业格：以「板群为目标」走生成链——独立卡被滤除，只落两板格子。"""
    from app.modules.safety.feishu.daily_digest import special_digest_chat_id
    from app.modules.safety.service.special_op_direct import daily as so_daily

    board_chat = (special_digest_chat_id() or "").strip()
    if not board_chat:
        return {"ok": False,
                "message": "特殊作业速递板目标群未配置，无法只投格重跑"}
    await so_daily.run(
        target_date, mode, push=True, target_chats=[board_chat],
    )
    key = "special_op_pm" if mode == "afternoon" else "special_op"
    return {"ok": True, "message": f"{key} 格已重投"}


async def reseed_daily_digest(
    ctx: RunContext[SafetyDeps],
    date: str,
    kinds: str = "",
) -> dict[str, Any]:
    """按日期重投速递格子（写操作；只投格，不重发群消息）。

    重新生成指定日期的日报并落速递格。今日/昨日允许重建发卡；更早日期
    由内置护栏只写存储、不向群重建发卡（返回中如实转述）。
    作业票格投格日期固定为运行日（服务层设计），不支持历史重投——
    补审请用 run_workticket_review。

    Args:
        date: 日期 YYYY-MM-DD（必填）
        kinds: 逗号分隔——fire_alarm（消防日报）/ special_op（特殊作业晨报）/
            special_op_pm（特殊作业晚报）；缺省三种全投

    示例：昨天的速递格子重投一下。

    注意：此操作会重新生成日报并更新速递卡，需要用户确认后才执行；
    确认卡应复述日期与格子种类。
    """
    action = "daily_digest_reseed"
    from app.modules.safety.feishu.daily_digest import digest_enabled

    raw = (date or "").strip()
    if not raw:
        return {"success": False, "action": action, "message": "日期必填（YYYY-MM-DD）"}
    try:
        target = _date.fromisoformat(raw)
    except ValueError:
        return {
            "success": False, "action": action,
            "message": f"日期无效：{raw!r}（应为 YYYY-MM-DD）",
        }
    if not digest_enabled():
        return {
            "success": False, "action": action,
            "message": "速递总卡未开启（SAFETY_DAILY_DIGEST_ENABLED=false），重投无意义",
        }
    raw_kinds = [k.strip() for k in (kinds or "").split(",") if k.strip()]
    if not raw_kinds:
        raw_kinds = list(_RESEED_KINDS)
    bad = [k for k in raw_kinds if k not in _RESEED_KINDS]
    if bad:
        return {
            "success": False, "action": action,
            "message": f"未知格子类型 {bad}，可选：{'/'.join(_RESEED_KINDS)}（workticket 格按运行日落格，请用 run_workticket_review）",
        }

    results: list[dict[str, Any]] = []
    for kind in raw_kinds:
        try:
            if kind == "fire_alarm":
                from app.modules.safety.service.fire_alarm.service import FireAlarmService

                await FireAlarmService(ctx.deps.db).generate_daily_report(
                    target, push=True,
                )
                results.append({"key": kind, "ok": True, "message": "fire_alarm 格已重投"})
            elif kind == "special_op":
                r = await _reseed_special_op(target, "today")
                r["key"] = kind
                results.append(r)
            else:  # special_op_pm
                r = await _reseed_special_op(target, "afternoon")
                r["key"] = kind
                results.append(r)
        except Exception as exc:
            logger.exception("reseed %s for %s failed", kind, target)
            results.append({"key": kind, "ok": False, "message": f"重投失败: {exc}"})

    ok_count = sum(1 for r in results if r.get("ok"))
    notes = [f"{ok_count}/{len(results)} 格重投完成"]
    if target < _bj_today() - timedelta(days=1):
        notes.append("该日期早于昨天：内置护栏只写存储、不向群重建发卡（驾驶舱回放可见）")
    return {
        "success": True,
        "action": action,
        "date": raw,
        "results": results,
        "message": "；".join(notes),
    }
