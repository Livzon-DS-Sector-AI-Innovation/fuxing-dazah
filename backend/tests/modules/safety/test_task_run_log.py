"""定时任务运行日志（Agent 任务运行中心，3.0 四期 1-D）测试。

接缝：
- record/load 用真实回滚 session（db_session）；
- 端点走 conftest client（get_db 覆写为同一回滚 session，种的数据可见）；
- 调度挂钩（_run_scheduled_job_guarded）不在此测真实任务，只测 fail-open
  的 record_task_run_fail_open 在 DB 异常时静默（monkeypatch session factory）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SchedulerTaskRunLog
from app.modules.safety.service.task_run_log import (
    error_summary,
    load_run_overview,
    record_task_run,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class TestRecordAndQuery:
    async def test_record_success_and_failed_rows(self, db_session: AsyncSession) -> None:
        started = datetime.now(UTC) - timedelta(seconds=3)
        ok = await record_task_run(
            db_session, job_name="测试任务", started_at=started, status="success"
        )
        assert ok.status == "success"
        assert ok.error is None
        assert ok.duration_ms is not None and ok.duration_ms >= 0

        bad = await record_task_run(
            db_session,
            job_name="测试任务",
            started_at=started,
            status="failed",
            error=error_summary(text="ValueError: 演示失败"),
        )
        assert bad.status == "failed"
        assert bad.error == "ValueError: 演示失败"

        rows = (
            await db_session.execute(select(SchedulerTaskRunLog))
        ).scalars().all()
        assert len(rows) == 2

    async def test_error_summary_truncation(self) -> None:
        long_text = "x" * 600
        summary = error_summary(text=long_text)
        assert summary is not None and len(summary) == 501  # 500 + 省略号
        assert summary.endswith("…")
        assert error_summary() is None
        exc = RuntimeError("boom")
        assert error_summary(exc=exc) == "RuntimeError: boom"

    async def test_load_overview_latest_per_job_and_recent(
        self, db_session: AsyncSession
    ) -> None:
        base = datetime.now(UTC) - timedelta(hours=2)
        await record_task_run(
            db_session, job_name="持证到期预警", started_at=base, status="success"
        )
        await record_task_run(  # 更晚的一次（failed）
            db_session,
            job_name="持证到期预警",
            started_at=base + timedelta(minutes=30),
            status="failed",
            error="RuntimeError: boom",
        )
        await record_task_run(
            db_session,
            job_name="消防报警日报",
            started_at=base + timedelta(minutes=50),
            status="success",
        )

        overview = await load_run_overview(db_session, recent_limit=2)
        latest = overview["latest_by_job"]
        assert set(latest) == {"持证到期预警", "消防报警日报"}
        # 每任务取最近一次：持证到期预警取 30 分钟后那次（failed）
        assert latest["持证到期预警"]["status"] == "failed"
        assert latest["持证到期预警"]["error"] == "RuntimeError: boom"
        assert latest["消防报警日报"]["status"] == "success"
        # 全局最近历史：时间倒序 + limit 生效
        assert len(overview["recent"]) == 2
        assert overview["recent"][0]["job_name"] == "消防报警日报"


class TestJobRunsEndpoint:
    async def test_endpoint_full_job_set_and_structure(self, client: AsyncClient) -> None:
        """端点冒烟：任务全集（代码默认+DB 覆写合并）+ 每任务结构完整。

        db_session 与 client 是独立事务，种子行不可见——「最近一次运行」的
        行为断言在 TestRecordAndQuery（服务层）覆盖；此处只验结构与全集。
        """
        resp = await client.get("/api/v1/safety/scheduler-config/job-runs")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        data: dict[str, Any] = body["data"]

        jobs = {j["job_name"]: j for j in data["jobs"]}
        # 任务全集来自 SCHEDULED_JOBS（含最新加入的外来人员保险预警）
        assert "持证到期预警" in jobs
        assert "外来人员保险预警" in jobs
        assert len(data["jobs"]) >= 15
        # 每任务结构完整
        sample = jobs["持证到期预警"]
        for key in ("job_name", "description", "schedule_text", "enabled", "last_run"):
            assert key in sample
        # last_run 形状：null（从未运行）或六字段 dict
        last_run = sample["last_run"]
        if last_run is not None:
            for key in ("job_name", "started_at", "finished_at", "status", "duration_ms", "error"):
                assert key in last_run
        # 最近历史列表形状一致
        for row in data["recent"]:
            assert row["job_name"]
            assert row["status"] in ("success", "failed")

    async def test_schedule_text_formats(self, db_session: AsyncSession, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/safety/scheduler-config/job-runs")
        data = resp.json()["data"]
        by_name = {j["job_name"]: j["schedule_text"] for j in data["jobs"]}
        assert by_name["持证到期预警"] == "每日 08:00"
        assert by_name["外来人员保险预警"] == "每周三 08:30"
        assert by_name["消防报警月报"] == "每月1日 08:30"


class TestFailOpen:
    async def test_record_fail_open_swallows_db_error(
        self, monkeypatch: Any
    ) -> None:
        """挂钩写日志失败仅告警不抛（留痕绝不影响任务本体）。"""
        from app.modules.safety.service import task_run_log

        def _boom() -> Any:
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "app.core.database.async_session_factory", _boom
        )
        # 不抛即通过（内部 logger.warning 兜底）
        await task_run_log.record_task_run_fail_open(
            job_name="任意任务",
            started_at=datetime.now(UTC),
            status="success",
        )
