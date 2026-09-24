"""调度任务 dom（每月几号）回归测试。

背景（2026-09-24 生产缺陷）：`_merge_job` 的基础字典漏拷代码默认 `dom`，
「消防报警月报」的 dom=1 在「代码默认 → DB 覆写合并」后丢失，任务退化成
每天 08:30 触发，月报格子天天出现在安全速递总卡。本文件锁死三条防线：
合并保留默认值、月度任务当天过滤、日任务不受影响。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.models import SchedulerTaskConfig
from app.modules.safety.scheduler import SCHEDULED_JOBS, _matches_day
from app.modules.safety.service.scheduler_config import _merge_job


def _job(name: str) -> dict:
    return next(job for job in SCHEDULED_JOBS if job["name"] == name)


class TestMergePreservesDomDefault:
    """_merge_job 必须把代码默认 dom 带进合并结果（生产缺陷根因）。"""

    def test_monthly_job_without_db_row_keeps_dom_1(self):
        merged = _merge_job(_job("消防报警月报"), None)
        assert merged["dom"] == 1

    def test_monthly_job_row_without_dom_keeps_default(self):
        # DB 播种行 dom=NULL = 使用代码默认值
        row = SchedulerTaskConfig(job_name="消防报警月报", enabled=True)
        merged = _merge_job(_job("消防报警月报"), row)
        assert merged["dom"] == 1

    def test_monthly_job_row_dom_override(self):
        row = SchedulerTaskConfig(job_name="消防报警月报", enabled=True, dom=2)
        merged = _merge_job(_job("消防报警月报"), row)
        assert merged["dom"] == 2

    def test_daily_job_dom_is_none(self):
        row = SchedulerTaskConfig(job_name="消防报警日报", enabled=True)
        merged = _merge_job(_job("消防报警日报"), row)
        assert merged["dom"] is None


class TestMatchesDay:
    """dom/dow 当天过滤（_run_scheduled_job 的入口闸门）。"""

    def test_monthly_job_only_runs_on_day_1(self):
        job = _job("消防报警月报")
        assert _matches_day(job, date(2026, 10, 1)) is True
        assert _matches_day(job, date(2026, 9, 24)) is False
        assert _matches_day(job, date(2026, 9, 30)) is False

    def test_monthly_job_after_merge_only_runs_on_day_1(self):
        # 端到端：合并结果（而非手写 job dict）直接喂给日期过滤
        merged = _merge_job(_job("消防报警月报"), None)
        assert _matches_day(merged, date(2026, 9, 24)) is False
        assert _matches_day(merged, date(2026, 10, 1)) is True

    def test_weekly_job_dow_filter(self):
        job = _job("隐患督办通报")  # dow=3 周四
        assert _matches_day(job, date(2026, 9, 24)) is True  # 周四
        assert _matches_day(job, date(2026, 9, 25)) is False  # 周五

    def test_daily_job_runs_every_day(self):
        job = _job("消防报警日报")
        assert _matches_day(job, date(2026, 9, 24)) is True
        assert _matches_day(job, date(2026, 10, 1)) is True
