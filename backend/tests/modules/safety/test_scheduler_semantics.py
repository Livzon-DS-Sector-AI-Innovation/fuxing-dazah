"""2-C 调度归一对照测试（迁移前先写、迁移后必须仍绿）。

钉死自研调度循环的核心语义——「时间窗 >= 触发、重启不漏发」：
- 到点判定（current >= scheduled）、当日 success 去重（重启不重发）、
  新的一天重置、失败 10min 退避 + 补发窗口、enabled 熔断；
- 状态持久化（内存首层 → DB，DB 不可用退化纯内存 fail-open）；
- 留痕 fail-open（写失败不影响任务本体）；
- 群→私顺序信号的 DB 兜底。

这些测试面向 scheduler 的公共行为函数；2-C 桥接迁移只替换「运行时宿主」
（自研 30s 循环 → 平台引擎 interval 任务），本文件语义断言零改动。

依据：.scratch/safety-agent-optimization-p2/spec.md 2-C 节。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _fresh_state_cache(monkeypatch: pytest.MonkeyPatch):
    """每个用例独立内存状态缓存；走真 _load_state/_save_state（首层内存命中不打 DB）。"""
    from app.modules.safety import scheduler

    cache: dict[str, dict] = {}
    monkeypatch.setattr(scheduler, "_state_cache", cache)
    return cache


def _job(**overrides) -> dict:
    job = {"name": "测试任务", "hour": 8, "minute": 0, "enabled": True}
    job.update(overrides)
    return job


def _state(status: str, *, fired: date | None = None, minutes_ago: float = 30,
           attempt: int = 1) -> dict:
    return {
        "job_name": "测试任务",
        "fired_date": fired or date(2026, 10, 16),
        "status": status,
        "last_attempt_at": datetime.now(UTC) - timedelta(minutes=minutes_ago),
        "attempt_count": attempt,
        "alerted": False,
    }


def _run(job, state: dict | None = None, *, now: datetime,
         today: date = date(2026, 10, 16)) -> bool:
    from app.modules.safety import scheduler

    if state is not None:
        scheduler._state_cache["测试任务"] = state
    return asyncio.run(scheduler._should_run(job, today, now))


# ── 到点判定（时间窗 >= 触发）─────────────────────────────────────


def test_not_due_before_scheduled_time() -> None:
    now = datetime(2026, 10, 16, 7, 59)
    assert _run(_job(), now=now) is False


def test_due_exactly_at_scheduled_time() -> None:
    """到点即触发：current == scheduled 为 >= 边界（08:00:00 整）。"""
    now = datetime(2026, 10, 16, 8, 0)
    assert _run(_job(), now=now) is True


def test_due_anytime_after_scheduled_same_day() -> None:
    """过点后当天任意时刻（如重启到 15:00）首次判定仍 True → 重启不漏发。"""
    now = datetime(2026, 10, 16, 15, 0)
    assert _run(_job(), now=now) is True


def test_disabled_job_never_runs() -> None:
    now = datetime(2026, 10, 16, 9, 0)
    assert _run(_job(enabled=False), now=now) is False


# ── 当日去重 / 新一天重置 / 重启不重发 ──────────────────────────


def test_same_day_success_dedup_after_restart() -> None:
    """当天已 success → 重启后（内存清空、DB 有 success 行）不重发。"""
    now = datetime(2026, 10, 16, 17, 0)
    assert _run(_job(), _state("success"), now=now) is False


def test_new_day_resets_state() -> None:
    now = datetime(2026, 10, 16, 8, 0)
    assert _run(_job(), _state("success", fired=date(2026, 10, 15)), now=now) is True


# ── 失败退避重试 + 补发窗口 ──────────────────────────────────────


def test_failed_within_backoff_not_due() -> None:
    """失败后 10 分钟内不重试（退避）。"""
    now = datetime(2026, 10, 16, 8, 5)
    assert _run(_job(), _state("failed", minutes_ago=5), now=now) is False


def test_failed_after_backoff_due_within_window() -> None:
    now = datetime(2026, 10, 16, 12, 0)
    assert _run(_job(), _state("failed", minutes_ago=11), now=now) is True


def test_failed_outside_retry_window_not_due() -> None:
    """超出补发窗口（retry_until 12:30）不再补发；窗口边界内仍补发。"""
    job = _job(retry_until_hour=12, retry_until_minute=30)
    failed = _state("failed", minutes_ago=30, attempt=5)
    assert _run(job, {**failed, "alerted": True}, now=datetime(2026, 10, 16, 12, 31)) is False
    assert _run(job, failed, now=datetime(2026, 10, 16, 12, 30)) is True


def test_retry_until_defaults_to_end_of_day() -> None:
    from app.modules.safety.scheduler import _retry_until

    assert _retry_until({}) == 23 * 60 + 59
    assert _retry_until({"retry_until_hour": 12, "retry_until_minute": 30}) == 12 * 60 + 30


# ── dow/dom 星期与日期过滤（跨天不补）────────────────────────────


def test_matches_day_dow_dom() -> None:
    from app.modules.safety.scheduler import _matches_day

    thursday = date(2026, 10, 15)  # 周四
    friday = date(2026, 10, 16)    # 周五
    assert _matches_day({"dow": 3}, thursday) is True   # dow=3 周四
    assert _matches_day({"dow": 3}, friday) is False    # 周五不跑（跨天不补）
    assert _matches_day({"dom": 1}, date(2026, 10, 1)) is True
    assert _matches_day({"dom": 1}, date(2026, 10, 2)) is False
    assert _matches_day({}, friday) is True             # 未配置不限


def test_matches_day_months_quarter_gate() -> None:
    """months=季度首月：非季度月 1 日为空跑（S1 二期标准符合性定格）。"""
    from app.modules.safety.scheduler import _matches_day

    job = {"dom": 1, "months": [1, 4, 7, 10]}
    assert _matches_day(job, date(2026, 10, 1)) is True   # 10-1 季度首日触发
    assert _matches_day(job, date(2026, 11, 1)) is False  # 非季度月 1 日空跑
    assert _matches_day(job, date(2026, 10, 2)) is False  # dom 不符
    # 未配置 months 的既有任务不受影响（月报 dom=1 月月照跑）
    assert _matches_day({"dom": 1}, date(2026, 11, 1)) is True


def test_freeze_job_registered_with_quarter_gate() -> None:
    """SCHEDULED_JOBS 含「标准符合性定格」且带 months 门（装配链透传契约）。"""
    from app.modules.safety.scheduler import SCHEDULED_JOBS

    job = next(j for j in SCHEDULED_JOBS if j["name"] == "标准符合性定格")
    assert (job["hour"], job["minute"], job["dom"]) == (8, 20, 1)
    assert job["months"] == [1, 4, 7, 10]
    assert (job["retry_until_hour"], job["retry_until_minute"]) == (23, 30)


# ── 状态持久化 fail-open（DB 不可用退化纯内存）──────────────────


def test_load_state_db_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB 不可用：无内存缓存 → None（宁重复不错过，不抛异常）。"""
    from app.modules.safety import scheduler

    monkeypatch.setattr(scheduler, "_state_cache", {})
    import app.core.database as db_mod

    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(db_mod, "async_session_factory", boom)
    state = asyncio.run(scheduler._load_state("任何任务"))
    assert state is None


def test_save_state_db_failure_still_writes_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety import scheduler

    mem: dict[str, dict] = {}
    monkeypatch.setattr(scheduler, "_state_cache", mem)

    import app.core.database as db_mod

    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(db_mod, "async_session_factory", boom)
    asyncio.run(
        scheduler._save_state("任务A", {"fired_date": date(2026, 10, 16), "status": "success",
                                        "last_attempt_at": None, "attempt_count": 0,
                                        "alerted": False})
    )
    assert mem["任务A"]["status"] == "success"


# ── 留痕 fail-open ───────────────────────────────────────────────


def test_record_task_run_fail_open_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.database as db_mod
    from app.modules.safety.service import task_run_log

    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(db_mod, "async_session_factory", boom)
    asyncio.run(  # 不抛异常即通过（留痕失败不影响任务本体）
        task_run_log.record_task_run_fail_open(
            job_name="任务A", started_at=datetime.now(UTC), status="failed", error="x" * 900,
        )
    )


def test_error_summary_truncated() -> None:
    from app.modules.safety.service.task_run_log import _ERROR_MAX_CHARS, error_summary

    out = error_summary(ValueError("x" * 2000))
    assert out is not None and len(out) <= _ERROR_MAX_CHARS + 1  # +1 省略号


# ── 群→私顺序信号 DB 兜底 ────────────────────────────────────────


def test_group_done_db_fallback_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """内存信号丢失（重启）→ 查 DB success 行兜底为 True。"""
    from app.modules.safety import scheduler

    today = date(2026, 10, 16)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def scalar(self, *_args, **_kwargs):
            return SimpleNamespace(fired_date=today, status="success")

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "async_session_factory", lambda: _FakeSession())
    assert asyncio.run(scheduler._fire_group_report_done_today(today)) is True
    assert asyncio.run(scheduler._central_group_report_done_today(today)) is True


def test_group_done_db_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB 不可用 → False（回退内存信号等待，不抛异常）。"""
    import app.core.database as db_mod
    from app.modules.safety import scheduler

    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(db_mod, "async_session_factory", boom)
    assert asyncio.run(scheduler._fire_group_report_done_today()) is False
    assert asyncio.run(scheduler._central_group_report_done_today()) is False
