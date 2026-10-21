"""facilities-p1 票 02：校验任务纯引擎 + 派发编排 + no_source 调度语义。

接缝：
- engine（select_due/category_label/group_key/anchor_advanced）纯函数直测；
- run_dispatch 走 db_session 回滚事务 + FakeReader（page client 协议替身）
  + FakeResolver（OwnerResolver 协议替身）；
- no_source 语义直测 scheduler._should_run / _run_scheduled_job 的哨兵链路
  （不真起调度循环，照 test_scheduler_semantics 风格注入状态）。
"""

# 任务查询一律按 biz_type=accessory 圈定作用域：dev 库 2026-10-21 08:30 首轮
# 真实派发已落地 fire 任务，全表计数/one() 断言不再与数据环境无关。

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.safety.facilities.dispatch import run_dispatch
from app.modules.safety.facilities.engine import (
    anchor_advanced,
    category_label,
    group_key_of,
    select_due,
)
from app.modules.safety.facilities.ledger import (
    BIZ_ACCESSORY,
    BIZ_FIRE,
    BIZ_SPECIAL,
    to_view,
)
from app.modules.safety.facilities.notify import NoopNotifier
from app.modules.safety.facilities.reader import FacilitiesLedgerReader
from app.modules.safety.models import FacilityCheckTask, FacilityTaskEvent
from app.modules.safety.service.bitable_direct.errors import BitableConfigError, BitableQueryError

from .test_facilities_ledger import FakePageClient, _ms, _rec

TODAY = date(2026, 10, 20)

async def _digest_stub(cell, *, today=None, **kwargs):
    return True


def _acc(rid: str, *, anchor: date | None, no: str | None = "AQ-1",
         dept: str = "提炼一部", owner: str | None = "张三",
         status: str = "", last: date | None = None, cycle: int | None = None,
         category: str = "安全阀"):
    fields: dict[str, Any] = {
        "设备编号": no, "设备名称": f"设备{rid}", "类别": category,
        "责任部门": dept, "设备状态": status,
    }
    if owner:
        fields["责任人"] = owner
    if anchor is not None:
        fields["下次校验日期"] = _ms(anchor)
    if last is not None:
        fields["上次校验日期"] = _ms(last)
    if cycle is not None:
        fields["校验周期（月）"] = str(cycle)
    return to_view(_rec(rid, fields), BIZ_ACCESSORY)


# ── 纯引擎：类别归一 / 分组键 ────────────────────────────────────────


def test_category_label_known_and_unknown():
    assert category_label("弹簧式安全阀") == "安全阀"
    assert category_label("干粉灭火器（手提）") == "灭火器"
    assert category_label("立式压力容器") == "压力容器"
    assert category_label("新型未知设备") == "其他"
    assert category_label(None) == "其他"
    assert category_label("") == "其他"


def test_group_key_format():
    assert group_key_of("提炼一部", "安全阀", "校验") == "安全阀·校验"


# ── 纯引擎：到期筛选 ────────────────────────────────────────────────


def test_select_due_window_and_filters():
    views = [
        _acc("r1", anchor=TODAY + timedelta(days=29)),   # 命中（30 天窗口内）
        _acc("r2", anchor=TODAY + timedelta(days=31)),   # 窗外（30 天 lead）
        _acc("r3", anchor=TODAY - timedelta(days=3)),    # 已逾期照派
        _acc("r4", anchor=None, last=date(2026, 10, 1), cycle=12),  # 推算锚点 2027-10 → 窗外
        _acc("r5", anchor=None),                          # 无锚点不派
        _acc("r6", anchor=TODAY, no=None),                # 缺编号→合成「类别」照派（2026-10-20 拍板）
        _acc("r7", anchor=TODAY, status="已报废"),        # 非在用不派
    ]
    due = select_due(views, TODAY, lead_days=30)
    assert sorted(c.view.record_id for c in due) == ["r1", "r3", "r6"]
    r6 = next(c for c in due if c.view.record_id == "r6")
    assert r6.view.equipment_no == "安全阀"  # 合成编号（类别兜底）


def test_select_due_guard_raw_view_without_equipment_no():
    """to_view 已合成编号；引擎守卫仍防裸视图（防御性，非 to_view 产物）。"""
    from app.modules.safety.facilities.ledger import LedgerRowView

    raw = LedgerRowView(record_id="raw1", biz_type=BIZ_ACCESSORY, anchor=TODAY)
    assert select_due([raw], TODAY, lead_days=30) == []


def test_select_due_fire_multi_anchor():
    fields = {
        "器材编号": "FE-1", "名称": "干粉灭火器", "类别": "灭火器", "责任部门": "仓储部",
        "下次检查日期": _ms(TODAY + timedelta(days=40)),   # 检查锚点窗外
        "换药到期": _ms(TODAY + timedelta(days=10)),       # 换药锚点命中
        "报废到期": _ms(TODAY - timedelta(days=1)),        # 报废锚点已逾期命中
    }
    v = to_view(_rec("f1", fields), BIZ_FIRE)
    due = select_due([v], TODAY, lead_days=30)
    assert sorted((c.task_subtype, c.due_date) for c in due) == [
        ("报废更换", TODAY - timedelta(days=1)),
        ("换药", TODAY + timedelta(days=10)),
    ]


def test_select_due_special_45_days_lead():
    v = to_view(
        _rec("s1", {
            "设备编号": "SE-1", "下次检验日期": _ms(TODAY + timedelta(days=44)),
        }),
        BIZ_SPECIAL,
    )
    assert [c.task_subtype for c in select_due([v], TODAY, lead_days=45)] == ["定期检验"]
    assert select_due([v], TODAY, lead_days=30) == []


def test_candidate_group_key_composition():
    v = _acc("g1", anchor=TODAY, category="弹簧式安全阀")
    cand = select_due([v], TODAY, lead_days=30)[0]
    assert cand.group_key == "安全阀·校验"
    assert cand.task_kind == "校验"


# ── 纯引擎：锚点前移判定（闭环铁律）────────────────────────────────


def test_anchor_advanced_by_next_date_rolled():
    assert anchor_advanced(
        due_date=date(2026, 11, 1), issued_on=TODAY,
        current_anchor=date(2026, 11, 20), current_last=None,
    ) is True


def test_anchor_advanced_by_new_last_date_after_dispatch():
    # 下次日期没动，但上次日期出现派发之后的新值 → 闭环
    assert anchor_advanced(
        due_date=date(2026, 11, 1), issued_on=TODAY,
        current_anchor=date(2026, 11, 1), current_last=TODAY,
    ) is True


def test_anchor_not_advanced_on_unrelated_change():
    # 只改了名称/备注：锚点未前移、上次日期仍是派发前的旧值 → 不闭环
    assert anchor_advanced(
        due_date=date(2026, 11, 1), issued_on=TODAY,
        current_anchor=date(2026, 11, 1),
        current_last=TODAY - timedelta(days=300),
    ) is False
    assert anchor_advanced(
        due_date=date(2026, 11, 1), issued_on=TODAY,
        current_anchor=None, current_last=None,
    ) is False


def test_anchor_advanced_boundary_equal_due_not_closed():
    # 锚点 == due_date（未滚动到新周期）且无新上次日期 → 不闭环
    assert anchor_advanced(
        due_date=date(2026, 11, 1), issued_on=TODAY,
        current_anchor=date(2026, 11, 1), current_last=None,
    ) is False


# ── 派发编排（db_session 回滚事务 + FakeReader/FakeResolver）────────


class FakeResolver:
    """OwnerResolver 协议替身：按姓名映射 open_id。"""

    def __init__(self, leaders: dict[str, tuple[str, str]] | None = None):
        self.leaders = leaders or {}
        self.leader_calls: list[str] = []

    async def resolve_by_name(self, name, department_hint=None):
        if name == "幽灵":
            return None
        return type("P", (), {"open_id": f"ou_{name}", "name": name})()

    async def resolve_department_leader(self, department_name):
        self.leader_calls.append(department_name)
        hit = self.leaders.get(department_name)
        if not hit:
            return None
        return type("P", (), {"open_id": hit[0], "name": hit[1]})()


def _reader_for(biz_items: dict[str, list[dict[str, Any]]]) -> FacilitiesLedgerReader:
    return FacilitiesLedgerReader(
        {biz: FakePageClient(items) for biz, items in biz_items.items()}
    )


async def test_dispatch_creates_tasks_idempotent(db_session):
    items = [
        _rec("a1", {
            "设备编号": "AQ-1", "设备名称": "安全阀A", "类别": "安全阀",
            "责任部门": "提炼一部", "责任人": "张三",
            "下次校验日期": _ms(TODAY + timedelta(days=10)),
        }),
    ]
    reader = _reader_for({BIZ_ACCESSORY: items})
    r1 = await run_dispatch(db_session, reader=reader, resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub)
    assert r1.created == 1 and r1.no_source is False
    assert r1.departments == ["提炼一部"]

    tasks = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().all()
    assert len(tasks) == 1
    t = tasks[0]
    assert t.status == "issued"
    assert t.biz_type == BIZ_ACCESSORY
    assert t.ledger_key == "a1"
    assert t.due_date == TODAY + timedelta(days=10)
    assert t.anchor_at_dispatch == TODAY + timedelta(days=10)
    assert t.issued_on == TODAY
    assert t.group_key == "安全阀·校验"
    assert t.assignee_open_id == "ou_张三"
    events = (await db_session.execute(
        select(FacilityTaskEvent).join(FacilityCheckTask).where(
            FacilityCheckTask.biz_type == BIZ_ACCESSORY
        )
    )).scalars().all()
    assert [e.event_type for e in events] == ["issued"]

    # 重跑：幂等（不重复建任务、不重复发事件）
    r2 = await run_dispatch(db_session, reader=reader, resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub)
    assert r2.created == 0 and r2.skipped_existing == 1
    tasks2 = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().all()
    assert len(tasks2) == 1


async def test_dispatch_owner_fallback_to_department_leader(db_session):
    items = [
        _rec("a1", {
            "设备编号": "AQ-2", "设备名称": "压力表", "类别": "压力表",
            "责任部门": "提炼二部", "责任人": "幽灵",  # resolve_by_name 失败
            "下次校验日期": _ms(TODAY),
        }),
    ]
    reader = _reader_for({BIZ_ACCESSORY: items})
    resolver = FakeResolver(leaders={"提炼二部": ("ou_leader", "李部长")})
    result = await run_dispatch(
        db_session, reader=reader, resolver=resolver, notifier=NoopNotifier(),
        today=TODAY, digest_pusher=_digest_stub,
    )
    assert result.created == 1
    assert result.unresolved_owner == 0
    t = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().one()
    assert t.assignee_open_id == "ou_leader"
    assert resolver.leader_calls == ["提炼二部"]


async def test_dispatch_owner_unresolved_still_creates_task(db_session):
    items = [
        _rec("a1", {
            "设备编号": "AQ-3", "责任部门": "未知部", "责任人": "幽灵",
            "下次校验日期": _ms(TODAY),
        }),
    ]
    result = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items}),
        resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub,
    )
    assert result.created == 1
    assert result.unresolved_owner == 1
    t = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().one()
    assert t.assignee_open_id is None


async def test_dispatch_reconcile_closes_and_cancels(db_session):
    # 第一次派发建任务
    items1 = [
        _rec("keep", {
            "设备编号": "AQ-K", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
            "上次校验日期": _ms(TODAY - timedelta(days=400)),
        }),
        _rec("gone", {
            "设备编号": "AQ-G", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
        }),
        _rec("stopped", {
            "设备编号": "AQ-S", "责任部门": "提炼一部", "设备状态": "在用",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
        }),
    ]
    reader1 = _reader_for({BIZ_ACCESSORY: items1})
    await run_dispatch(db_session, reader=reader1, resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub)
    assert (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().all().__len__() == 3

    # 第二次拉取：keep 行更新了校验时间（锚点前移）；gone 行已删除；stopped 行改停用
    items2 = [
        _rec("keep", {
            "设备编号": "AQ-K", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=400)),  # 前移
            "上次校验日期": _ms(TODAY),                          # 新值 ≥ 派发日
        }),
        _rec("stopped", {
            "设备编号": "AQ-S", "责任部门": "提炼一部", "设备状态": "停用",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
        }),
    ]
    r2 = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items2}),
        resolver=FakeResolver(), notifier=NoopNotifier(),
        today=TODAY + timedelta(days=1), digest_pusher=_digest_stub,
    )
    assert r2.reconciled_closed == 1
    assert r2.reconciled_cancelled == 2

    tasks = {t.ledger_key: t for t in (
        (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().all()
    )}
    assert tasks["keep"].status == "closed"
    assert tasks["keep"].closed_trigger == "poll"
    assert tasks["gone"].status == "cancelled"
    assert "删除" in tasks["gone"].closed_reason
    assert tasks["stopped"].status == "cancelled"
    assert "停用" in tasks["stopped"].closed_reason

    events = (await db_session.execute(select(FacilityTaskEvent))).scalars().all()
    closed_ev = [e for e in events if e.event_type == "closed"][0]
    assert closed_ev.payload["anchor_after"] == (TODAY + timedelta(days=400)).isoformat()


async def test_dispatch_reconcile_ignores_unrelated_change(db_session):
    items1 = [
        _rec("a1", {
            "设备编号": "AQ-U", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
            "上次校验日期": _ms(TODAY - timedelta(days=200)),
        }),
    ]
    await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items1}),
        resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub,
    )
    # 只改名称（锚点/上次日期不动）→ 不闭环不取消
    items2 = [
        _rec("a1", {
            "设备编号": "AQ-U", "设备名称": "改名了", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
            "上次校验日期": _ms(TODAY - timedelta(days=200)),
        }),
    ]
    r2 = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items2}),
        resolver=FakeResolver(), notifier=NoopNotifier(),
        today=TODAY + timedelta(days=1), digest_pusher=_digest_stub,
    )
    assert r2.reconciled_closed == 0 and r2.reconciled_cancelled == 0
    t = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().one()
    assert t.status == "issued"


async def test_dispatch_partial_config_no_reconcile_for_missing_biz(db_session):
    """只配置了附件台账时：特设台账的 open 任务不被误对账（不误取消）。"""
    items = [
        _rec("a1", {
            "设备编号": "AQ-1", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
        }),
    ]
    result = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items}),
        resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub,
    )
    assert result.fetched_rows == {BIZ_ACCESSORY: 1}
    assert result.no_source is False

    # 预置一条特设任务（模拟历史派发），本轮特设台账未配置 → 保持 issued
    legacy = FacilityCheckTask(
        biz_type=BIZ_SPECIAL, ledger_key="se-legacy", equipment_no="SE-9",
        department="发酵一部", task_kind="定期检验",
        due_date=TODAY + timedelta(days=3), lead_days=45,
        group_key="锅炉·定期检验", task_subtype="定期检验",
        anchor_at_dispatch=TODAY + timedelta(days=3), issued_on=TODAY,
    )
    db_session.add(legacy)
    await db_session.flush()
    r2 = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items}),
        resolver=FakeResolver(), notifier=NoopNotifier(), today=TODAY,
        digest_pusher=_digest_stub,
    )
    assert r2.reconciled_cancelled == 0
    assert legacy.status == "issued"


async def test_dispatch_no_source_when_all_unconfigured(db_session):
    """封闭式 no_source：一律用替身 reader 模拟「三台账全未配置」。

    真实 FacilitiesLedgerReader 是否查到连接取决于环境 DB——灭火器台账
    已真实登记（2026-10-20），走真实 reader 会拉真数据并以默认通知器
    真发批次卡（当日测试即因此向群里发了 8 张幽灵卡）。本测试禁止任何
    真实 reader/通知/速递路径。
    """
    class _UnconfiguredReader:
        async def fetch_ledger(self, biz_type, strict=False):
            raise BitableConfigError(f"未配置: {biz_type}")

    result = await run_dispatch(
        db_session, reader=_UnconfiguredReader(), notifier=NoopNotifier(),
        digest_pusher=_digest_stub, today=TODAY,
    )
    assert result.no_source is True
    assert result.created == 0
    assert (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().first() is None


async def test_dispatch_query_error_raises(db_session):
    """已配置但读取失败 → 聚合上抛（调度器标 failed 补发），绝不假成功。"""
    reader = FacilitiesLedgerReader({BIZ_ACCESSORY: FakePageClient([], boom=True)})
    with pytest.raises(BitableQueryError):
        await run_dispatch(db_session, reader=reader, today=TODAY)


# ── 调度 no_source 语义（哨兵链路）──────────────────────────────────


async def test_scheduler_no_source_state_dedup_for_day(monkeypatch):
    from app.modules.safety import scheduler

    job = {"name": "设施校验任务派发", "hour": 8, "minute": 30,
           "retry_until_hour": 12, "retry_until_minute": 0}
    today = date.today()
    after = datetime.now().replace(hour=9, minute=0)

    # 无状态 → 应跑
    async def no_state(name):
        return None
    monkeypatch.setattr(scheduler, "_load_state", no_state)
    assert await scheduler._should_run(job, today, now=after) is True

    # 当天 no_source → 不重跑（与 success 同等对待）
    async def no_source_state(name):
        return {"job_name": name, "fired_date": today, "status": "no_source",
                "last_attempt_at": datetime.now(UTC), "attempt_count": 1, "alerted": False}
    monkeypatch.setattr(scheduler, "_load_state", no_source_state)
    assert await scheduler._should_run(job, today, now=after) is False


async def test_scheduler_job_returns_no_source_sentinel(monkeypatch):
    """runner 返回 no_source → _run_scheduled_job 留 no_source 状态并返回哨兵。"""
    from app.modules.safety import scheduler

    saved: list[dict] = []

    async def fake_run():
        return True  # no_source

    async def fake_save(name, state):
        saved.append(state)
    monkeypatch.setattr(scheduler, "_run_facility_dispatch", fake_run)
    monkeypatch.setattr(scheduler, "_save_state", fake_save)

    async def no_state(name):
        return None
    monkeypatch.setattr(scheduler, "_load_state", no_state)

    job = {"name": "设施校验任务派发", "hour": 8, "minute": 30}
    result = await scheduler._run_scheduled_job(job)
    assert result == scheduler.SKIP_NO_SOURCE
    assert saved and saved[-1]["status"] == "no_source"

async def test_dispatch_redispatches_after_cancelled(db_session):
    """MAJOR1 回归：cancelled 任务不阻塞同物同周期重派（停用→取消→再启用）。"""
    items = [
        _rec("a1", {
            "设备编号": "AQ-R", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=5)),
            "设备状态": "在用",
        }),
    ]
    reader = _reader_for({BIZ_ACCESSORY: items})
    r1 = await run_dispatch(
        db_session, reader=reader, resolver=FakeResolver(), notifier=NoopNotifier(),
        today=TODAY, digest_pusher=_digest_stub,
    )
    assert r1.created == 1
    t = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().one()
    t.status = "cancelled"
    t.closed_reason = "台账状态停用：停用"
    await db_session.flush()

    # 行恢复在用（同 due）：cancelled 不拦 → 重派新任务
    r2 = await run_dispatch(
        db_session, reader=reader, resolver=FakeResolver(), notifier=NoopNotifier(),
        today=TODAY, digest_pusher=_digest_stub,
    )
    assert r2.created == 1 and r2.skipped_existing == 0
    tasks = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().all()
    assert len(tasks) == 2
    assert [t.status for t in tasks] == ["cancelled", "issued"]


async def test_dispatch_same_run_no_false_close(db_session):
    """MAJOR2 回归：派发当轮不对新建任务跑闭环判定。

    场景：短周期设备当日已校准（上次=今天）但下次日期仍在窗内——
    派发建任务后本轮对账跳过，不得当分钟误闭环。
    """
    items = [
        _rec("a1", {
            "设备编号": "AQ-S", "责任部门": "提炼一部",
            "下次校验日期": _ms(TODAY + timedelta(days=10)),
            "上次校验日期": _ms(TODAY),  # 当日已校准，但下次列未更新
        }),
    ]
    r = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items}),
        resolver=FakeResolver(), notifier=NoopNotifier(),
        today=TODAY, digest_pusher=_digest_stub,
    )
    assert r.created == 1 and r.reconciled_closed == 0
    t = (await db_session.execute(
        select(FacilityCheckTask).where(FacilityCheckTask.biz_type == BIZ_ACCESSORY)
    )).scalars().one()
    assert t.status == "issued"

    # 次日对账（非同轮）才按「上次≥派发日」判定闭环
    r2 = await run_dispatch(
        db_session, reader=_reader_for({BIZ_ACCESSORY: items}),
        resolver=FakeResolver(), notifier=NoopNotifier(),
        today=TODAY + timedelta(days=1), digest_pusher=_digest_stub,
    )
    assert r2.reconciled_closed == 1
