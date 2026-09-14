"""定时任务/告警目标注册表 — 任务行的代码唯一事实源（只能改值不能新增 job）。

- ``system_alert``：事件触发的系统告警目标（AI 调用失败、提醒触发失败等），
  target 缺省回落 ``target_env_var`` 指向的 env；
- ``draft_expire_stale`` / ``reminder_recover``：V1.1 调度化任务的配置行，
  本轮只播种（执行引擎属后续票，见设计稿 §7）。

schedule 语义（platform/scheduler/strategies 三态的仓库子集）：
``{"type": "interval", "seconds": N}`` / ``{"type": "cron", "expr": "..."}`` /
``null``（事件触发，无调度）。
本模块零副作用导入，migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskInfo:
    """单个任务行（job_name 是稳定标识，DB 只能改值不能新增）。"""

    job_name: str
    label: str
    description: str
    default_schedule: dict[str, Any] | None   # null = 事件触发
    target_env_var: str                       # target 缺省回落 env（空 = 无兜底）


_TASKS: tuple[TaskInfo, ...] = (
    TaskInfo(
        job_name="system_alert",
        label="系统告警目标",
        description="AI 调用失败等系统级告警的飞书投递目标（群 chat_id）",
        default_schedule=None,
        target_env_var="WAREHOUSE_ALERT_CHAT_ID",
    ),
    TaskInfo(
        job_name="draft_expire_stale",
        label="草稿过期清扫",
        description="批量将超过 TTL 的草稿/确认置为 expired（执行引擎属 V1.1 调度化票）",
        default_schedule={"type": "interval", "seconds": 300},
        target_env_var="",
    ),
    TaskInfo(
        job_name="reminder_recover",
        label="提醒重启恢复",
        description="进程重启后扫表重调度未触发的 scheduled 提醒（执行引擎属 V1.1 调度化票）",
        default_schedule={"type": "interval", "seconds": 300},
        target_env_var="",
    ),
)

SCHEDULER_REGISTRY: dict[str, TaskInfo] = {t.job_name: t for t in _TASKS}
assert len(SCHEDULER_REGISTRY) == len(_TASKS), "任务注册表存在重复 job_name"


def get_task(job_name: str) -> TaskInfo:
    """未知任务抛 ValueError（消息以「未知任务」开头，404 语义）。"""
    info = SCHEDULER_REGISTRY.get(job_name)
    if info is None:
        raise ValueError(f"未知任务: {job_name}")
    return info


def iter_tasks() -> tuple[TaskInfo, ...]:
    """遍历全部任务行，供 migration 播种 + 遍历视图。"""
    return _TASKS
