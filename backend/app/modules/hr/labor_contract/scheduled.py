"""劳动合同定时任务：公告期扫描（每天 09:05）+ 审批结果轮询（每 15 分钟）+ 归档缺失周提醒（每周一 09:00）。

公告期扫描：生效合同进入提前 N 天窗口（缺省 50）→ 尝试发起飞书原生审批
→ 失败降级站内待审批 → HR 摘要卡片；同轮把到期未续签的合同翻成
expired_unrenewed。配置全走 hr_contract.*（labor_contract/settings.py），
任务内部自检开关，无需 env。

审批结果轮询：renewal_approval.sync_pending_results 幂等回写。
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


async def _load_context(db: AsyncSession) -> dict[str, Any]:
    kv = await contract_settings.load_contract_settings(db)
    enabled = contract_settings.pipeline_enabled(kv)
    days = contract_settings.days_ahead(kv)
    copy_entries = [
        x.strip() for x in kv.get(contract_settings.KEY_HR_COPY_OPEN_IDS, "").split(",")
        if x.strip()
    ]
    return {"kv": kv, "enabled": enabled, "days": days, "copy_entries": copy_entries}


async def run_renewal_announcement() -> None:
    """每天 09:05：公告期扫描 + 发起审批 + 到期未续签标注。"""
    async with async_session_factory() as db:
        ctx = await _load_context(db)
        if not ctx["enabled"]:
            logger.info("劳动合同续签流程未启用（hr_contract.renewal_pipeline_enabled=false），扫描跳过")
            return
        await _run_announcement(db, days_ahead=ctx["days"], copy_entries=ctx["copy_entries"])


async def _run_announcement(
    db: AsyncSession, *, days_ahead: int, copy_entries: list[str]
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

    receivers = await resolve_receivers(db, copy_entries)
    sent = await notify.send_announcement_summary(
        db,
        announced_rows=feishu_rows,
        manual_rows=manual_rows,
        failed_rows=failed_rows,
        expired_rows=expired_rows,
        receivers=receivers,
        days_ahead=days_ahead,
    )
    logger.info(
        "合同公告期扫描完成: 公告 %d（飞书 %d / 站内 %d），到期未续签 %d，HR 摘要送达 %d",
        len(feishu_rows) + len(manual_rows) + len(failed_rows),
        len(feishu_rows), len(manual_rows), len(expired_rows), sent,
    )


async def run_approval_sync() -> None:
    """每 15 分钟：轮询回写飞书审批结果（幂等）。"""
    async with async_session_factory() as db:
        ctx = await _load_context(db)
        if not ctx["enabled"]:
            return
        counts = await renewal_approval.sync_pending_results(db)
        if any(counts.values()):
            await db.commit()
            logger.info("续签审批结果回写: %s", counts)
        else:
            await db.rollback()


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
