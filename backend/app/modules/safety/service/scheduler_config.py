"""安全模块定时任务配置读写服务。

- load_scheduled_jobs_with_overrides(): 以 SCHEDULED_JOBS 为代码默认值，合并
  scheduler_task_configs 非软删行（NULL = 使用代码默认值）。
- upsert_task_config(): 校验 + 写入 scheduler_task_configs + 追加 scheduler_config_audits。
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SchedulerConfigAudit, SchedulerTaskConfig
from app.modules.safety.scheduler import SCHEDULED_JOBS

# 报告类任务静态映射（report_type=true 才开放预览/手动触发等相关能力）
REPORT_TYPE_JOBS: frozenset[str] = frozenset({
    "特殊作业日报",
    "特殊作业日报17点",
    "作业票审核",
    "消防报警日报",
    "中控报警日报",
    "危化品库存周报",
    "危化品库存日报",
    "隐患分析报告",
    "隐患督办通报",
})

# ── 任务「生效发送对象」解析（仅展示用，不改调度行为）──
# 调度器实际推送顺序：DB 覆写 target_chat_id > 各服务模块 env > 代码默认群。
# 前端列表/抽屉「发送对象」据此展示真实生效目标，避免 DB 覆写为空时误显示「无」。
EFFECTIVE_TARGET_ENV: dict[str, str] = {
    "作业票审核": "SAFETY_WORKTICKET_GROUP_ID",
    "消防报警日报": "SAFETY_FIRE_ALARM_ANALYSIS_CHAT_ID",
    "中控报警日报": "SAFETY_CENTRAL_ALARM_ANALYSIS_CHAT_ID",
    "危化品库存周报": "SAFETY_CHEMICAL_INVENTORY_WEEKLY_CHAT_ID",
    "危化品库存日报": "SAFETY_CHEMICAL_INVENTORY_DAILY_CHAT_ID",
}
EFFECTIVE_TARGET_CODE: dict[str, str] = {
    "隐患督办通报": "oc_f05532603bd7682fc520929c01aca88d",  # 安全AI创新交流群
    "未更新进展催办": "ou_495039d6335d347b07ff92ad982b3b4e",  # 许康福（个人 DM）
    "特殊作业日报": "oc_d102e1a11eaaa9a1de3b41859de9d0c1",  # 特殊作业自动分配群
    "特殊作业日报17点": "oc_d102e1a11eaaa9a1de3b41859de9d0c1",
    "作业票审核": "oc_d102e1a11eaaa9a1de3b41859de9d0c1",
    "危化品库存日报": "oc_f05532603bd7682fc520929c01aca88d",
    "危化品库存周报": "oc_f05532603bd7682fc520929c01aca88d",  # 与日报同群（env 已清空，代码默认兜底）
}


def _resolve_target_type(job_name: str, target_id: str | None) -> str:
    """目标类型：ou_ = 个人 DM；oc_ = 群聊；无目标时取任务代码默认。"""
    if target_id:
        return "person" if str(target_id).startswith("ou_") else "group"
    job = _jobs_index().get(job_name) or {}
    return job.get("target_type", "group")


def _resolve_effective_target(
    job_name: str, override_id: str | None
) -> tuple[str | None, str | None]:
    """返回 (生效 chat_id, 来源)。来源: db / env / code / None。"""
    if override_id:
        return override_id, "db"
    env_key = EFFECTIVE_TARGET_ENV.get(job_name)
    if env_key:
        env_val = (os.getenv(env_key) or "").strip()
        if env_val:
            return env_val, "env"
    code_val = EFFECTIVE_TARGET_CODE.get(job_name)
    if code_val:
        return code_val, "code"
    return None, None

# 供前端展示/覆写使用的字段（scheduler_task_configs 可覆写字段）
_OVERRIDE_FIELDS = (
    "hour",
    "minute",
    "dow",
    "target_chat_id",
    "target_chat_name",
    "retry_until_hour",
    "retry_until_minute",
)
_SCHEDULE_FIELDS = ("hour", "minute", "dow", "retry_until_hour", "retry_until_minute")


def _jobs_index() -> dict[str, dict[str, Any]]:
    """SCHEDULED_JOBS 按 job_name 转为 dict，用于查找/校验。"""
    return {job["name"]: job for job in SCHEDULED_JOBS}


def _attach_resolved_default(job_name: str, result: dict[str, Any]) -> None:
    """无 DB 配置行时的回退：把 env/代码默认目标落到 target_chat_id。

    仅播种前/新增任务场景；DB 行存在后 target_chat_id 一律以 DB 为准（统一来源）。
    """
    if result.get("target_chat_id"):
        return
    effective_id, _source = _resolve_effective_target(job_name, None)
    result["target_chat_id"] = effective_id


def _merge_job(job: dict[str, Any], row: SchedulerTaskConfig | None) -> dict[str, Any]:
    """合并单个任务的代码默认值与数据库覆写。"""
    name = job["name"]
    result: dict[str, Any] = {
        "job_name": name,
        "hour": job.get("hour"),
        "minute": job.get("minute"),
        "dow": job.get("dow"),
        "enabled": job.get("enabled", True),
        "target_chat_id": None,
        "target_chat_name": None,
        "mode": job.get("mode", "today"),
        "description": job.get("description"),
        "report_type": name in REPORT_TYPE_JOBS,
        "retry_until_hour": job.get("retry_until_hour"),
        "retry_until_minute": job.get("retry_until_minute"),
        "config_source": "code",
    }
    if row is None:
        _attach_resolved_default(name, result)
        result["target_type"] = _resolve_target_type(
            name, result.get("target_chat_id")
        )
        return result

    if row.enabled is not None:
        result["enabled"] = row.enabled
    for field in _OVERRIDE_FIELDS:
        value = getattr(row, field, None)
        if value is not None:
            result[field] = value

    # 完整覆盖（所有调度字段均由 DB 提供）为 db，否则为 db_partial
    if all(getattr(row, field, None) is not None for field in _SCHEDULE_FIELDS):
        result["config_source"] = "db"
    else:
        result["config_source"] = "db_partial"
    # DB 行存在：发送对象以 DB 为准（None = 无目标，不再回退 env/代码默认）
    result["target_type"] = _resolve_target_type(
        name, result.get("target_chat_id")
    )
    return result


async def _load_in_session(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(SchedulerTaskConfig).where(SchedulerTaskConfig.is_deleted.is_(False))
        )
    ).scalars().all()
    overrides = {r.job_name: r for r in rows}
    return [_merge_job(job, overrides.get(job["name"])) for job in SCHEDULED_JOBS]


async def load_scheduled_jobs_with_overrides(
    db: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """返回合并后的定时任务列表（代码默认 + DB 覆写）。

    db 为空时自建一次性会话（供调度器等无 HTTP 上下文场景使用）。
    """
    if db is None:
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            return await _load_in_session(session)
    return await _load_in_session(db)


def _validate_int(name: str, value: int | None, maximum: int) -> None:
    if value is not None and (value < 0 or value > maximum):
        raise ValueError(f"{name} 必须在 0-{maximum}")


def _validate_data(job_name: str, data: dict[str, Any]) -> None:
    jobs = _jobs_index()
    if job_name not in jobs:
        raise ValueError("未知定时任务")

    enabled = data.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled 必须为布尔值")

    _validate_int("hour", data.get("hour"), 23)
    _validate_int("minute", data.get("minute"), 59)
    _validate_int("dow", data.get("dow"), 6)
    _validate_int("retry_until_hour", data.get("retry_until_hour"), 23)
    _validate_int("retry_until_minute", data.get("retry_until_minute"), 59)

    target_chat_id = data.get("target_chat_id")
    if target_chat_id is not None:
        if not isinstance(target_chat_id, str) or not (
            target_chat_id.startswith("oc_") or target_chat_id.startswith("ou_")
        ):
            raise ValueError("target_chat_id 必须以 oc_（群聊）或 ou_（个人）开头")


async def _find_config_row(db: AsyncSession, job_name: str) -> SchedulerTaskConfig | None:
    """查找 job_name 对应配置行（含软删行，用于恢复）。"""
    stmt = (
        select(SchedulerTaskConfig)
        .where(SchedulerTaskConfig.job_name == job_name)
        .order_by(SchedulerTaskConfig.updated_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


def _compact_before(row: SchedulerTaskConfig) -> dict[str, Any]:
    """审计 before_json：只保留当前已有覆写值（compact）。"""
    before: dict[str, Any] = {"enabled": row.enabled}
    for field in _OVERRIDE_FIELDS:
        value = getattr(row, field, None)
        if value is not None:
            before[field] = value
    return before


def _compact_after(values: dict[str, Any]) -> dict[str, Any]:
    """审计 after_json：本次写入的字段（compact；显式清空也记录 null）。"""
    after: dict[str, Any] = {}
    if values.get("enabled") is not None:
        after["enabled"] = values["enabled"]
    for field in _OVERRIDE_FIELDS:
        value = values.get(field)
        if value is not None:
            after[field] = value
    if "target_chat_id" in values and values.get("target_chat_id") is None:
        after["target_chat_id"] = None
        after["target_chat_name"] = None
    return after


async def upsert_task_config(
    db: AsyncSession,
    job_name: str,
    data: dict[str, Any],
    operator_name: str | None = None,
) -> dict[str, Any]:
    """校验并写入任务覆写配置，同时追加审计记录。

    - job_name 必须精确存在于 SCHEDULED_JOBS；
    - hour/minute/dow/retry 范围 0-23/0-59/0-6；
    - target_chat_id 若提供必须以 oc_ 开头；
    - enabled 必填 bool；
    - 软删行恢复（is_deleted=false）。
    """
    data = dict(data or {})
    _validate_data(job_name, data)

    row = await _find_config_row(db, job_name)
    before = _compact_before(row) if row is not None else None

    values: dict[str, Any] = {}
    if data.get("enabled") is not None:
        values["enabled"] = data["enabled"]
    for field in _OVERRIDE_FIELDS:
        if field in data and data[field] is not None:
            values[field] = data[field]

    # 显式清空发送对象：target_chat_id=null → 无推送目标（同步清空名称）
    if "target_chat_id" in data and data.get("target_chat_id") is None:
        values["target_chat_id"] = None
        values["target_chat_name"] = None

    if row is None:
        row = SchedulerTaskConfig(job_name=job_name)
        db.add(row)
    if row.is_deleted:
        row.is_deleted = False

    for key, value in values.items():
        setattr(row, key, value)
    if values.get("enabled") is None and row.enabled is None:
        row.enabled = True

    after = _compact_after(values)
    audit = SchedulerConfigAudit(
        job_name=job_name,
        action="update",
        before_json=before,
        after_json=after,
        operator_name=operator_name,
    )
    db.add(audit)
    await db.flush()

    return _merge_job(_jobs_index()[job_name], row)


async def write_audit_job_run(
    db: AsyncSession,
    job_name: str,
    operator_name: str | None = None,
) -> Any:
    """占位：手动触发/运行审计入口，Ticket 07 实现。

    预留用于 action='run' 的 scheduler_config_audits 写入。
    """
    return None


async def seed_default_task_targets() -> None:
    """为没有配置行的任务播种 DB 行（发送对象统一落库，前端唯一编辑入口）。

    - 把 env / 代码默认发送对象写入 scheduler_task_configs，此后 target_chat_id
      一律以 DB 为准（调度器直接取用，不再逐层回退）
    - 只创建缺失行，不覆写已有配置；幂等，调度器启动时执行一次
    """
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(SchedulerTaskConfig).where(
                    SchedulerTaskConfig.is_deleted.is_(False)
                )
            )
        ).scalars().all()
        existing = {r.job_name: r for r in rows}
        created = 0
        for job in SCHEDULED_JOBS:
            name = job["name"]
            if name in existing:
                continue
            effective_id, _source = _resolve_effective_target(name, None)
            session.add(
                SchedulerTaskConfig(
                    job_name=name,
                    enabled=job.get("enabled", True),
                    target_chat_id=effective_id,
                    target_chat_name=None,
                )
            )
            created += 1
        if created:
            await session.commit()
