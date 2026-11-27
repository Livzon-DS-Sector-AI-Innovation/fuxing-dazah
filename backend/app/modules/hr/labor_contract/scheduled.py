"""劳动合同定时任务：公告期扫描（每天 09:05）+ 审批结果轮询（每 15 分钟）+ 归档缺失周提醒（每周一 09:00）。

公告期扫描：生效合同进入提前 N 天窗口（缺省 50）→ 部门审批默认站内
（台账勾选），同时给部门负责人发续签审批提醒卡片（需求：到期预警通知用人部门负责人）；
仅当配置了飞书审批定义编码（hr_contract.renewal_approval_code）才改走原生审批，
那时负责人收到的是飞书审批待办、不再另发卡片。同轮先把已离职人员的未完结合同归入
离职台账，再把到期未续签的合同翻成 expired_unrenewed。配置全走 hr_contract.*
（labor_contract/settings.py），任务内部自检开关，无需 env。

审批结果轮询：renewal_approval.sync_pending_results 幂等回写；飞书审批被撤销而退回
站内待审批的合同，补发负责人提醒卡片。
归档缺失周提醒：见 archive_scheduled.py。
"""

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.hr.labor_contract import (
    archive_scheduled,
    departure_service,
    dept_notice,
    notify,
    renewal_approval,
)
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import service as contract_service
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.reminder.config import resolve_receivers
from app.platform.scheduler import (
    ScheduleConfig,
    SchedulerRegistry,
    ScheduleStrategy,
    TaskDefinition,
)

logger = logging.getLogger(__name__)

# 飞书审批被撤销、合同退回站内待审批时，负责人卡片上的附加说明
_CANCELED_NOTE = "此前的飞书审批已撤销，请改在合同台账内审批。"
# 负责人提醒关闭时，HR 摘要里对站内待审批合同的说明
_NOTICE_OFF_REASON = "负责人提醒已关闭，请 HR 通知负责人"


async def _load_context(db: AsyncSession) -> dict[str, Any]:
    kv = await contract_settings.load_contract_settings(db)
    enabled = contract_settings.pipeline_enabled(kv)
    days = contract_settings.days_ahead(kv)
    copy_entries = [
        x.strip() for x in kv.get(contract_settings.KEY_HR_COPY_OPEN_IDS, "").split(",")
        if x.strip()
    ]
    return {
        "kv": kv, "enabled": enabled, "days": days, "copy_entries": copy_entries,
        "dept_notice": contract_settings.dept_head_notice_enabled(kv),
    }


async def run_renewal_announcement() -> None:
    """每天 09:05：公告期扫描 + 发起审批 + 通知部门负责人 + 到期未续签标注。"""
    async with async_session_factory() as db:
        ctx = await _load_context(db)
        if not ctx["enabled"]:
            logger.info("劳动合同续签流程未启用（hr_contract.renewal_pipeline_enabled=false），扫描跳过")
            return
        await _run_announcement(
            db, days_ahead=ctx["days"], copy_entries=ctx["copy_entries"],
            dept_notice=ctx["dept_notice"],
        )


async def _run_announcement(
    db: AsyncSession, *, days_ahead: int, copy_entries: list[str], dept_notice: bool,
) -> None:
    today = date.today()

    # 0) 已离职人员的未完结合同归入离职台账（两本台账不交叉，不再参与预警）
    reconciled_rows = await departure_service.reconcile_departed_contracts(db)

    # 1) 到期未续签标注（在职员工）
    expired_rows = await contract_service.flip_expired_contracts(db)

    # 2) 公告期扫描
    due_contracts = await contract_service.find_expiring_active(db, days_ahead=days_ahead)
    if due_contracts:
        active_map = await repo.list_active_employees(
            db, [c.employee_number for c in due_contracts]
        )
    else:
        active_map = {}

    feishu_rows: list[tuple[LaborContract, str]] = []
    manual_rows: list[LaborContract] = []
    failed_rows: list[tuple[LaborContract, str]] = []
    for contract in due_contracts:
        employee = active_map.get(contract.employee_number)
        if not employee:
            continue  # 员工已离职：合同不进续签流程（P3 离职台账处理）
        # 预告起始日：默认原合同到期日次日（可确认时在续签办理修改）
        proposed_start = (contract.end_date or today) + timedelta(days=1)
        ok, result = await renewal_approval.initiate(
            db, contract, next_start=proposed_start
        )
        if ok:
            await contract_service.mark_pending_renewal(
                db, contract, mode=LaborContract.APPROVAL_FEISHU,
                instance_code=result,
            )
            feishu_rows.append((contract, "部门负责人（飞书审批待办）"))
        else:
            await contract_service.mark_pending_renewal(
                db, contract, mode=LaborContract.APPROVAL_MANUAL
            )
            manual_rows.append(contract)
            logger.info("公告期降级站内审批: %s → %s", contract.employee_number, result)

    if feishu_rows or manual_rows or failed_rows or expired_rows or reconciled_rows:
        await db.commit()
    else:
        await db.rollback()

    # 3) 站内待审批的合同：给部门负责人发提醒卡片（需求「到期预警通知用人部门负责人」）。
    #    必须在上面 commit 之后发：卡片只发一次，不能出现提醒发了、状态却没落库。
    notified_rows: list[tuple[LaborContract, str]] = []
    unreached_rows: list[tuple[LaborContract, str]] = []
    if manual_rows:
        if dept_notice:
            notified_rows, unreached_rows = await _push_dept_notices(db, manual_rows)
        else:
            unreached_rows = [(c, _NOTICE_OFF_REASON) for c in manual_rows]

    receivers = await resolve_receivers(db, copy_entries)
    sent = await notify.send_announcement_summary(
        db,
        announced_rows=feishu_rows,
        notified_rows=notified_rows,
        unreached_rows=unreached_rows,
        failed_rows=failed_rows,
        expired_rows=expired_rows,
        receivers=receivers,
        days_ahead=days_ahead,
    )
    logger.info(
        "合同公告期扫描完成: 公告 %d（飞书 %d / 站内 %d），负责人提醒送达 %d / 未通知到 %d，"
        "到期未续签 %d，HR 摘要送达 %d",
        len(feishu_rows) + len(manual_rows) + len(failed_rows),
        len(feishu_rows), len(manual_rows), len(notified_rows), len(unreached_rows),
        len(expired_rows), sent,
    )


async def _push_dept_notices(
    db: AsyncSession, contracts: list[LaborContract], *, note: str | None = None,
) -> tuple[list[tuple[LaborContract, str]], list[tuple[LaborContract, str]]]:
    """站内待审批的合同逐个解析部门负责人并推送提醒卡片。

    返回 (已通知, 未通知到)，元素都是 (合同, 负责人姓名 / 没通知到的原因)：
    负责人匹配不到飞书账号、推送失败的都归到「未通知到」，由 HR 摘要兜底。
    """
    targets: list[tuple[LaborContract, str, str]] = []
    unreached: list[tuple[LaborContract, str]] = []
    for contract in contracts:
        manager_name, open_id = await renewal_approval.resolve_approver(db, contract)
        if open_id:
            targets.append((contract, manager_name or "", open_id))
        elif manager_name:
            unreached.append((contract, f"负责人「{manager_name}」匹配不到飞书账号"))
        else:
            unreached.append((contract, "部门表与员工档案均无负责人"))
    result = (
        await dept_notice.notify_dept_heads(targets, note=note)
        if targets else {"notified": [], "failed": []}
    )
    unreached.extend(
        (contract, f"负责人「{manager}」推送失败")
        for contract, manager in result["failed"]
    )
    logger.info(
        "部门负责人续签审批提醒: 已通知 %d 人，未通知到 %d 人",
        len(result["notified"]), len(unreached),
    )
    return result["notified"], unreached


async def _notify_back_to_manual(
    db: AsyncSession, contracts: list[LaborContract], *, days_ahead: int,
    copy_entries: list[str], dept_notice: bool,
) -> None:
    """飞书审批被撤销 → 退回站内待审批：负责人已没有审批待办，补发站内提醒。

    通知不到的（匹配不到负责人 / 推送失败 / 提醒已关闭）发 HR 摘要兜底；
    退回后合同不再被轮询，同一次审批不会重复提醒。
    """
    if dept_notice:
        notified_rows, unreached_rows = await _push_dept_notices(
            db, contracts, note=_CANCELED_NOTE,
        )
    else:
        notified_rows = []
        unreached_rows = [(c, _NOTICE_OFF_REASON) for c in contracts]
    if unreached_rows:
        receivers = await resolve_receivers(db, copy_entries)
        await notify.send_announcement_summary(
            db,
            announced_rows=[],
            notified_rows=notified_rows,
            unreached_rows=unreached_rows,
            failed_rows=[],
            expired_rows=[],
            receivers=receivers,
            days_ahead=days_ahead,
        )


async def run_approval_sync() -> None:
    """每 15 分钟：轮询回写飞书审批结果（幂等）；被撤销退回站内的合同补发负责人提醒。"""
    async with async_session_factory() as db:
        ctx = await _load_context(db)
        if not ctx["enabled"]:
            return
        counts, canceled_rows = await renewal_approval.sync_pending_results(db)
        if not any(counts.values()):
            await db.rollback()
            return
        await db.commit()
        logger.info("续签审批结果回写: %s", counts)
        if canceled_rows:
            await _notify_back_to_manual(
                db, canceled_rows,
                days_ahead=ctx["days"], copy_entries=ctx["copy_entries"],
                dept_notice=ctx["dept_notice"],
            )


RENEWAL_ANNOUNCE_TASK = TaskDefinition(
    name="hr.contract.renewal_announcement",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.FIXED_TIME, time_of_day="09:05"),
    coro=run_renewal_announcement,
    settings_toggle_key="",
    module="hr",
)

APPROVAL_SYNC_TASK = TaskDefinition(
    name="hr.contract.approval_sync",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=900
    ),
    coro=run_approval_sync,
    settings_toggle_key="",
    module="hr",
)


def register_labor_contract_tasks(registry: SchedulerRegistry) -> None:
    """注册劳动合同定时任务（hr/lifecycle.py 挂载）。"""
    registry.register_task(RENEWAL_ANNOUNCE_TASK)
    registry.register_task(APPROVAL_SYNC_TASK)
    registry.register_task(archive_scheduled.ARCHIVE_REMINDER_TASK)
