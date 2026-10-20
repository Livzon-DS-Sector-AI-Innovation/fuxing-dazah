"""facilities-p1 票 05：滚动批次卡合并通知 + 速递格子 + 逾期升级。

mock sender/updater 断言（DESIGN §4.5 拍板口径）：
- 同部门同类型任务合并为一张批次卡（单次 send、卡内分组分区）；
- 新任务并入原卡原地 PATCH（不另发新卡）；
- 闭环原地刷新进度（不发新消息）；
- 全闭环置绿归档；此后新任务 → 新开一张批次卡；
- PATCH 限流：5 分钟窗口内合并刷新；
- 逾期升级刷新引用原卡（追加催办区）；
- 速递格子 facility_check 文案口径。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.modules.safety.facilities.dispatch import run_escalation
from app.modules.safety.facilities.ledger import BIZ_ACCESSORY
from app.modules.safety.facilities.notify import (
    DIGEST_KEY,
    _task_line,
    build_batch_card,
    build_digest_cell_payload,
    record_urls_for,
    refresh_department_batch,
    reset_throttle,
)
from app.modules.safety.models import (
    FacilityCheckTask,
    FacilityNoticeBatch,
    FacilityTaskEvent,
)

TODAY = date(2026, 10, 20)


class SpySender:
    """send_group_card 替身：记录调用并回递增 message_id。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, *, chat_id: str, title: str, content: str,
                       elements=None, header_template: str = "orange", **kw) -> str:
        self.calls.append({
            "chat_id": chat_id, "title": title, "content": content,
            "elements": elements, "template": header_template,
        })
        return f"om_{len(self.calls)}"


class SpyUpdater:
    """update_card 替身：记录 PATCH（默认成功）。"""

    def __init__(self, *, ok: bool = True) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.ok = ok

    async def __call__(self, message_id: str, card: dict) -> bool:
        self.calls.append((message_id, card))
        return self.ok


def _task(rid: str, *, dept: str = "提炼一部", group: str = "安全阀·校验",
          due: date = TODAY, status: str = "issued",
          assignee: str | None = "ou_zhang") -> FacilityCheckTask:
    return FacilityCheckTask(
        biz_type=BIZ_ACCESSORY, ledger_key=rid, equipment_no=f"AQ-{rid}",
        department=dept, task_kind="校验", due_date=due, lead_days=30,
        status=status, group_key=group, task_subtype="校验",
        anchor_at_dispatch=due, issued_on=TODAY - timedelta(days=10),
        assignee_open_id=assignee, assignee_name="张三",
    )


async def _seed(db, tasks: list[FacilityCheckTask]) -> None:
    db.add_all(tasks)
    await db.flush()


def _card_markdown(card: dict) -> str:
    return card["body"]["elements"][0]["content"]


def _panel_markdown(card: dict) -> str:
    return card["body"]["elements"][1]["elements"][0]["content"]


async def test_same_department_merged_into_single_card(db_session):
    await _seed(db_session, [
        _task("k1", group="安全阀·校验"),
        _task("k2", group="安全阀·校验", due=TODAY - timedelta(days=2)),
        _task("k3", group="压力表·校验"),
    ])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()

    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY,
    )
    assert out["action"] == "sent"
    assert out["total"] == 3 and out["open"] == 3
    assert len(sender.calls) == 1  # 单卡
    card = sender.calls[0]
    assert "提炼一部 合计 **3** 件" in card["content"]
    panel_md = card["elements"][0]["elements"][0]["content"]  # 分组明细面板
    assert "安全阀·校验 2 件" in panel_md
    assert "压力表·校验 1 件" in panel_md
    batch = (await db_session.execute(select(FacilityNoticeBatch))).scalar_one()
    assert batch.card_message_id == "om_1"
    assert batch.total_count == 3 and batch.open_count == 3


async def test_new_tasks_patch_original_card_not_resend(db_session):
    await _seed(db_session, [_task("k1")])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=0.0,
    )
    assert len(sender.calls) == 1

    # 次日新任务并入：新开窗口（>5min）后 PATCH 原卡
    db_session.add(_task("k2", group="灭火器·换药"))
    await db_session.flush()
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY,
        now=1000.0,
    )
    assert out["action"] == "patched"
    assert len(sender.calls) == 1  # 不另发新卡
    assert len(updater.calls) == 1
    assert updater.calls[0][0] == "om_1"  # 原卡 message_id
    assert "灭火器·换药" in str(updater.calls[0][1])


async def test_closure_refreshes_in_place_and_archives_when_all_closed(db_session):
    t1 = _task("k1")
    t2 = _task("k2", status="closed")
    await _seed(db_session, [t1, t2])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=0.0,
    )
    assert len(sender.calls) == 1

    # 闭环刷新：新窗口内原地 PATCH（不发新消息）
    t1.status = "closed"
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY,
        now=2000.0,
    )
    assert out["action"] == "archived"
    assert len(sender.calls) == 1  # 没有新消息
    patched_card = updater.calls[-1][1]
    assert "✅ 全部完成" in _card_markdown(patched_card)
    assert patched_card["header"]["template"] == "green"

    batch = (await db_session.execute(select(FacilityNoticeBatch))).scalar_one()
    assert batch.status == "archived"

    # 归档后新周期任务 → 新开一张批次卡
    db_session.add(_task("k9"))
    await db_session.flush()
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY,
        now=3000.0,
    )
    assert out["action"] == "sent"
    assert len(sender.calls) == 2
    batches = (await db_session.execute(select(FacilityNoticeBatch))).scalars().all()
    assert len(batches) == 2


async def test_patch_throttle_within_window(db_session):
    await _seed(db_session, [_task("k1")])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=0.0,
    )
    # 5 分钟窗口内第二次刷新 → 跳过（不发不 PATCH）
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=60.0,
    )
    assert out["action"] == "throttled"
    assert len(sender.calls) == 1 and len(updater.calls) == 0
    # 窗口过后 → 正常 PATCH
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY,
        now=400.0,
    )
    assert out["action"] == "patched"


async def test_patch_failure_degrades_to_resend(db_session):
    await _seed(db_session, [_task("k1")])
    sender, updater = SpySender(), SpyUpdater(ok=False)  # 旧卡已删
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=0.0,
    )
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=400.0,
    )
    assert out["action"] == "resent"
    assert len(sender.calls) == 2  # 降级重发新卡
    batch = (await db_session.execute(select(FacilityNoticeBatch))).scalar_one()
    assert batch.card_message_id == "om_2"


async def test_mention_assignees_and_guidance_in_card(db_session):
    await _seed(db_session, [_task("k1", assignee="ou_zhang")])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY,
    )
    content = sender.calls[0]["content"]
    assert '<at user_id="ou_zhang"></at>' in content
    assert "更新校验时间" in content
    assert "自动闭环" in content


async def test_escalation_refreshes_existing_card_with_at_leader(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.modules.safety.facilities.reader.connection_configured",
        lambda biz: True,
    )
    t = _task("k1", due=TODAY - timedelta(days=9))  # 逾期 9 天 → 红档
    await _seed(db_session, [t])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=0.0,
    )

    refreshed: list[dict] = []

    async def spy_refresher(session, dept, *, escalation_md="", escalate_open_ids=None, **kw):
        refreshed.append({"md": escalation_md, "ids": escalate_open_ids})
        return await refresh_department_batch(
            session, dept, sender=sender, updater=updater,
            escalation_md=escalation_md, escalate_open_ids=escalate_open_ids, **kw,
        )

    class FakeResolver:
        async def resolve_by_name(self, name, department_hint=None):
            return None

        async def resolve_department_leader(self, dept):
            return type("L", (), {"open_id": "ou_leader", "name": "李部长"})()

    result = await run_escalation(
        db_session, resolver=FakeResolver(), refresher=spy_refresher, today=TODAY,
    )
    assert result.escalated == 1
    assert result.departments == ["提炼一部"]
    assert "逾期升级" in refreshed[0]["md"]
    assert ">7 天红档 1 件" in refreshed[0]["md"]
    assert "ou_leader" in refreshed[0]["ids"]
    assert t.remind_count == 1
    events = (await db_session.execute(select(FacilityTaskEvent))).scalars().all()
    assert [e.event_type for e in events if e.event_type == "escalated"]

    # 升级走 refresh 引用原卡（PATCH 而非新发）
    assert len(sender.calls) == 1
    assert len(updater.calls) >= 1
    assert '<at user_id="ou_leader"></at>' in _card_markdown(updater.calls[-1][1])


async def test_escalation_no_source(monkeypatch):

    monkeypatch.setattr(
        "app.modules.safety.facilities.reader.connection_configured",
        lambda biz: False,
    )
    # dispatch 引用的是模块内 import 的函数名，patch reader 层即可（run_escalation
    # 从 reader 模块 import connection_configured——函数内延迟 import 每次现取）
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        result = await run_escalation(session, today=TODAY)
    assert result.no_source is True


def test_digest_cell_order_contains_facility_check():
    from app.modules.safety.feishu.daily_digest import CELL_ORDER

    assert "facility_check" in CELL_ORDER


def test_digest_cell_payload_copy():
    cell = build_digest_cell_payload(
        open_total=5, overdue=2, due_30d=3,
        top_overdue=[
            {"department": "提炼一部", "equipment_no": "AQ-1",
             "group_key": "安全阀·校验", "over_days": 9},
            {"department": "仓储部", "equipment_no": "FE-2",
             "group_key": "灭火器·换药", "over_days": 2},
        ],
        incomplete=4, unresolved_owner=1,
    )
    assert cell.tag_color == "red"
    assert "待闭环 5" in cell.stats and "逾期 **2**" in cell.stats
    assert "🔴" in cell.detail  # >7 天红档
    assert "🟠" in cell.detail
    assert "信息不全 4 行" in cell.detail
    assert "责任人解析失败 1 条" in cell.detail
    assert DIGEST_KEY == "facility_check"

async def test_archived_cycle_tasks_not_pulled_into_new_card(db_session):
    """MAJOR3 回归：归档周期的历史任务不进新卡、batch_id 不被改写。"""
    old = _task("old1", status="closed")
    old.batch_id = None
    await _seed(db_session, [old])
    sender, updater = SpySender(), SpyUpdater()
    reset_throttle()
    await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=0.0,
    )
    batch1 = (await db_session.execute(select(FacilityNoticeBatch))).scalar_one()
    old.batch_id = batch1.id
    await db_session.flush()
    batch1.status = "archived"  # 模拟全闭环归档
    await db_session.flush()

    # 新周期任务 → 新卡：不含旧周期 closed 条目
    db_session.add(_task("new1"))
    await db_session.flush()
    out = await refresh_department_batch(
        db_session, "提炼一部", sender=sender, updater=updater, today=TODAY, now=100.0,
    )
    assert out["action"] == "sent" and out["total"] == 1
    panel_md = sender.calls[1]["elements"][0]["elements"][0]["content"]
    assert "old1" not in panel_md and "AQ-new1" in panel_md
    # 旧任务仍挂在已归档批次上（审计锚点不被污染）
    await db_session.refresh(old)
    assert old.batch_id == batch1.id


# ── 明细行记录直达链接（2026-10-20 需求：待闭环后附多维表格记录链接）──


def test_task_line_appends_record_link():
    t = _task("k9")
    url = "https://j0eukrlohu.feishu.cn/base/TOKEN?table=TBL&record=k9"
    assert _task_line(t, TODAY, record_url=url).endswith(f"⏳ 待闭环｜[📋记录]({url})")
    # 无链接时退化为原格式（未配置连接的台账）
    assert _task_line(t, TODAY).endswith("⏳ 待闭环")


def test_record_urls_for_via_connection(monkeypatch):
    from app.modules.safety.bitable_config import store as store_mod

    class _Conn:
        app_token = "Ngd7bJRxMaf6DpsqwlIcZtvpnce"
        table_id = "tblcnSMMA8vs5p33"

    monkeypatch.setattr(
        store_mod.store, "get_connection",
        lambda domain, kind: _Conn() if kind == "accessory_ledger" else None,
    )
    urls = record_urls_for([_task("rec1")])
    assert urls == {
        "accessory:rec1": (
            "https://j0eukrlohu.feishu.cn/base/Ngd7bJRxMaf6DpsqwlIcZtvpnce"
            "?table=tblcnSMMA8vs5p33&record=rec1"
        )
    }


def test_card_copy_and_fire_pending_text():
    """2026-10-20 拍板：标题=设备设施跟进提醒；头部只显示剩余合计；
    已闭环项不进明细；消防待办文案=待更换（其余台账默认待闭环）。"""
    from app.modules.safety.facilities.ledger import BIZ_FIRE

    card, title = build_batch_card(
        "提炼一部",
        [_task("k1"), _task("k2"), _task("k3", status="closed")],
        today=TODAY,
    )
    assert title == "🔧 提炼一部 设备设施跟进提醒"
    md = card["body"]["elements"][0]["content"]
    assert "提炼一部 合计 **2** 件" in md  # 只数未完成
    panel = card["body"]["elements"][1]["elements"][0]["content"]
    assert "安全阀·校验 2 件" in panel
    assert "k3" not in panel and "AQ-k3" not in panel  # 已闭环不展示

    fire = _task("f1")
    fire.biz_type = BIZ_FIRE
    assert "⏳ 待更换" in _task_line(fire, TODAY)
    assert "⏳ 待闭环" in _task_line(_task("a1"), TODAY)  # 附件默认口径
