"""周期定格测试（S1 体系标准符合性核查二期）。

接缝（照 test_standard_check_page 先例）：quarter_targets/snapshot_status 纯函数
直测；freeze_due 走 db_session + FakePageClient opener 替身。测试数据全部落在
2099 年（家规：防撞本地 dev 库真实数据）。表在测试事务内 create（PG 事务性 DDL
随 fixture 回滚，零 dev 库足迹；迁移已跑时 checkfirst 直通）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.safety.models.contractors import EmergencyDrillRecord
from app.modules.safety.models.standard_check import StandardCheckSnapshot
from app.modules.safety.models.work_ticket_review import WorkTicketReview
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.standard_check import freeze as sc_freeze
from app.modules.safety.service.standard_check.engine import (
    StandardRow,
    Verdict,
)


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


class FakePageClient:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    async def search_records(self, **kwargs: Any) -> dict[str, Any]:
        return {"items": self._items, "has_more": False, "page_token": None}


def _std(
    record_id: str,
    no: str,
    *,
    element: str = "应急管理",
    metric_key: str | None = None,
    period: str = "季度",
    operator: str = "≥",
    target: str = "1",
    unit: str = "次",
    department: list[str] | None = None,
    manual: str | None = None,
    year: str = "2099",
    last_done_ms: int | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "标准编号": no,
        "年度": year,
        "标准条款": f"{no} 条款文本",
        "依据": "测试依据",
        "要素归属": element,
        "指标键": metric_key,
        "比较符": operator,
        "目标值": target,
        "单位": unit,
        "周期": period,
        "责任部门": department if department is not None else ["安环部"],
        "责任人": None,
        "上次完成日期": last_done_ms,
        "人工核查结果": manual,
        "备注": None,
    }
    return {"record_id": record_id, "fields": fields}


@pytest.fixture(autouse=True)
async def _ensure_snapshot_table(db_session):
    """测试事务内确保表存在（checkfirst：dev 库已迁移则直通，未迁移则建表随回滚撤销）。"""

    def _create(ctx) -> None:
        StandardCheckSnapshot.__table__.create(ctx.connection(), checkfirst=True)

    await db_session.run_sync(_create)
    yield


async def _snap_rows(db_session, year: int = 2099) -> list[StandardCheckSnapshot]:
    # populate_existing：幂等重跑用 upsert 原地更新，须击穿 identity map 缓存读新值
    return list(
        (
            await db_session.execute(
                select(StandardCheckSnapshot)
                .where(StandardCheckSnapshot.year == year)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


# ═══════════════════════════════════════════════════════════════
# quarter_targets 纯函数
# ═══════════════════════════════════════════════════════════════


class TestQuarterTargets:
    def test_april_1(self) -> None:
        targets = sc_freeze.quarter_targets(date(2026, 4, 1))
        by_key = {t.period_key: t for t in targets}
        assert set(by_key) == {"2026-Q1", "2026-01", "2026-02", "2026-03", "2026"}
        q = by_key["2026-Q1"]
        assert (q.window.start, q.window.end) == (date(2026, 1, 1), date(2026, 3, 31))
        assert q.kind == "quarter" and q.in_cell is True
        assert by_key["2026-02"].window == sc_freeze.PeriodWindow(
            date(2026, 2, 1), date(2026, 2, 28)
        )
        assert by_key["2026"].kind == "year_interim"
        assert by_key["2026"].in_cell is False
        assert by_key["2026"].window == sc_freeze.PeriodWindow(
            date(2026, 1, 1), date(2026, 12, 31)
        )

    def test_july_1_includes_h1_final(self) -> None:
        targets = sc_freeze.quarter_targets(date(2026, 7, 1))
        by_key = {t.period_key: t for t in targets}
        assert set(by_key) == {
            "2026-Q2", "2026-04", "2026-05", "2026-06", "2026H1", "2026",
        }
        h1 = by_key["2026H1"]
        assert h1.kind == "half_year" and h1.period_value == "半年"
        assert (h1.window.start, h1.window.end) == (date(2026, 1, 1), date(2026, 6, 30))
        assert h1.in_cell is True

    def test_october_1_no_half_year(self) -> None:
        targets = sc_freeze.quarter_targets(date(2026, 10, 1))
        by_key = {t.period_key: t for t in targets}
        assert set(by_key) == {"2026-Q3", "2026-07", "2026-08", "2026-09", "2026"}
        assert by_key["2026-Q3"].window == sc_freeze.PeriodWindow(
            date(2026, 7, 1), date(2026, 9, 30)
        )

    def test_january_1_freezes_previous_year_finals(self) -> None:
        targets = sc_freeze.quarter_targets(date(2027, 1, 1))
        by_key = {t.period_key: t for t in targets}
        assert set(by_key) == {
            "2026-Q4", "2026-10", "2026-11", "2026-12", "2026H2", "2026",
        }
        final = by_key["2026"]
        assert final.kind == "year_final" and final.checklist_year == 2026
        assert final.window == sc_freeze.PeriodWindow(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        assert final.period_value is None  # 年度桶=非月/季/半年全部周期值
        assert by_key["2026H2"].window == sc_freeze.PeriodWindow(
            date(2026, 7, 1), date(2026, 12, 31)
        )

    @pytest.mark.parametrize(
        "d",
        [date(2026, 10, 2), date(2026, 11, 1), date(2026, 3, 1), date(2026, 1, 2)],
    )
    def test_non_quarter_first_day_empty(self, d: date) -> None:
        assert sc_freeze.quarter_targets(d) == ()


# ═══════════════════════════════════════════════════════════════
# snapshot_status 映射（纯函数）
# ═══════════════════════════════════════════════════════════════


def _row(metric_key: str | None, period: str = "季度") -> StandardRow:
    return StandardRow(
        record_id="r", no="D0-01", year="2099", clause="c",
        metric_key=metric_key, period=period,
    )


class TestSnapshotStatus:
    def test_auto_mapping(self) -> None:
        row = _row("drill.count.evacuation")
        assert sc_freeze.snapshot_status(row, Verdict("ok", "2次"))[0] == "achieved"
        assert sc_freeze.snapshot_status(row, Verdict("missed", "0次"))[0] == "missed"
        assert sc_freeze.snapshot_status(row, Verdict("no_data"))[0] == "no_data"
        assert (
            sc_freeze.snapshot_status(row, Verdict("in_progress"))[0] == "in_progress"
        )

    def test_manual_mapping(self) -> None:
        row = _row(None)
        assert sc_freeze.snapshot_status(row, Verdict("ok"))[0] == "manual_done"
        assert sc_freeze.snapshot_status(row, Verdict("missed"))[0] == "manual_missed"
        status, note = sc_freeze.snapshot_status(
            row, Verdict("in_progress", note="待人工核查")
        )
        assert status == "no_data"
        assert note == "定格时未勾选核查结果"


# ═══════════════════════════════════════════════════════════════
# freeze_due（db_session + opener 替身）
# ═══════════════════════════════════════════════════════════════


class TestFreezeDue:
    async def test_october_run_freezes_quarter_months_interim(
        self, db_session,
    ) -> None:
        """10-1 运行：Q3 终版（含 period_end 整季重算）+ 3 个月终版 + 年度中期。

        workticket.audit_rate（period_end 比率，口径=Σreviewed/Σtotal）窗口必须
        =7-1~9-30 整季：7 月 2 张审核 1 张 + 9 月 1 张 0 张 → 1/3≈33% < 95% →
        missed；若窗口错用「至今」（10-1 起的当季）则窗口内无票 → no_data，断言即破。
        """
        db_session.add_all([
            WorkTicketReview(date=date(2099, 7, 15), total=2, reviewed=1),
            WorkTicketReview(date=date(2099, 9, 20), total=1, reviewed=0),
            EmergencyDrillRecord(
                drill_type="综合应急演练", execution_time=date(2099, 8, 15),
                status="已完成", drill_content="罐区综合演练",
            ),
        ])
        await db_session.flush()
        items = [
            _std("r1", "D6-01", metric_key="drill.count.comprehensive_or_special",
                 period="半年"),  # 半年项：10-1 无 H 靶 → 不定格
            _std("r2", "D4-01", element="现场管理",
                 metric_key="workticket.audit_rate", period="季度",
                 operator="≥", target="95", unit="%"),
            _std("r3", "D3-06", element="教育培训",
                 metric_key="visitor.notice_rate", period="月度",
                 operator="≥", target="100", unit="%"),  # opener 未配 visitor → no_data
            _std("r4", "D6-03", metric_key="drill.count.evacuation",
                 period="年度"),  # 年度中期：0 场 → in_progress
            _std("r5", "D1-03", element="目标职责", metric_key=None,
                 manual="已完成", period="季度"),
            _std("r6", "D1-04", element="目标职责", metric_key=None,
                 manual="未完成", period="季度"),
            _std("r7", "D2-01", element="制度化管理", metric_key=None,
                 manual=None, period="季度"),  # 空 → no_data 未核查
            _std("r8", "D0-98", metric_key=None, manual="已完成",
                 period="季度", year="2098"),  # 往年行不参与
        ]
        result = await sc_freeze.freeze_due(
            db=db_session,
            opener=lambda d, k: FakePageClient(items),
            today=date(2099, 10, 1),
        )
        assert result.ran and not result.no_source
        assert result.targets == [
            "2099-Q3", "2099-07", "2099-08", "2099-09", "2099",
        ]

        snaps = {(s.standard_no, s.period_key): s for s in await _snap_rows(db_session)}
        # 半年项与往年行不定格
        assert not any(k[0] == "D6-01" for k in snaps)
        assert not any(k[0] == "D0-98" for k in snaps)

        wt = snaps[("D4-01", "2099-Q3")]
        assert wt.status == "missed"
        assert wt.actual_value == 33
        assert wt.evidence["window"] == {
            "start": "2099-07-01", "end": "2099-09-30",
        }
        assert "窗口内作业票 3 张" in wt.evidence["items"][0]["title"]

        for mm in ("07", "08", "09"):
            row = snaps[("D3-06", f"2099-{mm}")]
            # 无数据原因环境相关（域未接入 / 2099 窗口无申请单），只钉状态不钉原因
            assert row.status == "no_data"
            assert row.evidence["no_data_reason"]

        assert snaps[("D6-03", "2099")].status == "in_progress"  # 年度中期快照
        assert snaps[("D1-03", "2099-Q3")].status == "manual_done"
        assert snaps[("D1-04", "2099-Q3")].status == "manual_missed"
        empty = snaps[("D2-01", "2099-Q3")]
        assert empty.status == "no_data"
        assert empty.note == "定格时未勾选核查结果"

        # 速递格范围=当季定格行（季度+月度），年度中期不入格
        cell = {(c["no"], c["period_key"]) for c in result.cell_rows}
        assert ("D4-01", "2099-Q3") in cell
        assert ("D3-06", "2099-08") in cell
        assert ("D6-03", "2099") not in cell

    async def test_january_run_finalizes_annual_and_half_year(
        self, db_session,
    ) -> None:
        """1-1 运行：上年年度终版覆盖中期 in_progress；H2/长周期随年定格。"""
        items = [
            _std("r1", "D6-03", metric_key="drill.count.evacuation",
                 period="年度"),  # 无演练数据 → 终版 missed
            _std("r2", "D6-01", metric_key="drill.count.comprehensive_or_special",
                 period="半年"),
            _std("r3", "D5-07", element="风险管控与隐患治理", metric_key=None,
                 period="长周期(3年)",
                 last_done_ms=_ms(date(2098, 5, 1))),  # ≤3 年 → manual_done
        ]
        result = await sc_freeze.freeze_due(
            db=db_session, opener=lambda d, k: FakePageClient(items),
            today=date(2100, 1, 1),
        )
        assert result.targets == [
            "2099-Q4", "2099-10", "2099-11", "2099-12", "2099H2", "2099",
        ]
        snaps = {(s.standard_no, s.period_key): s for s in await _snap_rows(db_session)}
        assert snaps[("D6-03", "2099")].status == "missed"  # in_progress→终版
        assert snaps[("D5-07", "2099")].status == "manual_done"
        assert snaps[("D6-01", "2099H2")].status == "missed"
        # 年度终版不入速递格；长周期随年定格（year_final 靶 in_cell=False）同样不在格
        assert {c["period_key"] for c in result.cell_rows} <= {
            "2099-Q4", "2099-10", "2099-11", "2099-12", "2099H2",
        }
        assert not any(c["no"] == "D5-07" for c in result.cell_rows)

    async def test_idempotent_rerun_upserts(self, db_session) -> None:
        """重复定格=upsert：行数不变，清单修订后重跑刷新状态（幂等重跑验收）。"""
        items = [
            _std("r1", "D1-04", element="目标职责", metric_key=None,
                 manual="未完成", period="季度"),
        ]
        opener = lambda d, k: FakePageClient(items)  # noqa: E731
        first = await sc_freeze.freeze_due(
            db=db_session, opener=opener, today=date(2099, 10, 1),
        )
        rows = await _snap_rows(db_session)
        assert len(rows) == first.frozen == 1
        assert rows[0].status == "manual_missed"

        items[0]["fields"]["人工核查结果"] = "已完成"  # 清单补勾后重跑
        await sc_freeze.freeze_due(db=db_session, opener=opener, today=date(2099, 10, 1))
        rows2 = await _snap_rows(db_session)
        assert len(rows2) == 1  # 不重复行
        assert rows2[0].status == "manual_done"  # 值刷新

    async def test_no_source_when_checklist_unconfigured(self, db_session) -> None:
        def _unconfigured(domain: str, kind: str):
            raise BitableConfigError(f"Bitable 连接未配置或已停用: {domain}/{kind}")

        result = await sc_freeze.freeze_due(
            db=db_session, opener=_unconfigured, today=date(2099, 10, 1),
        )
        assert result.no_source is True and result.frozen == 0
        assert await _snap_rows(db_session) == []

    async def test_non_quarter_day_noop(self, db_session) -> None:
        result = await sc_freeze.freeze_due(
            db=db_session, opener=lambda d, k: FakePageClient([]),
            today=date(2099, 10, 2),
        )
        assert result.ran is False
        assert await _snap_rows(db_session) == []


# ═══════════════════════════════════════════════════════════════
# 调度 runner（no_source 哨兵 / 成功串联速递格 / 失败上抛走补发）
# ═══════════════════════════════════════════════════════════════


class TestFreezeRunner:
    @staticmethod
    async def _run(monkeypatch, freeze_ret, digest_ret=None, digest_exc=None):
        from app.modules.safety import scheduler
        from app.modules.safety.service.standard_check import freeze as freeze_mod

        sent: list[Any] = []

        async def fake_freeze(*, db, **kw):
            return freeze_ret

        async def fake_digest(result, *, chat_id=None, report_date=None):
            sent.append(result)
            if digest_exc:
                raise digest_exc
            return digest_ret or {"sent": True}

        monkeypatch.setattr(freeze_mod, "freeze_due", fake_freeze)
        monkeypatch.setattr(freeze_mod, "send_standard_compliance_digest", fake_digest)
        # runner 内部延迟 import 取的是模块属性，monkeypatch 模块级即可生效
        return await scheduler._run_standard_check_freeze(chat_id="oc_x"), sent

    async def test_no_source_skip(self, monkeypatch) -> None:
        ret, sent = await self._run(
            monkeypatch, sc_freeze.FreezeResult(ran=True, no_source=True),
        )
        assert ret is True  # SKIP 哨兵 → no_source 留痕，不假 success
        assert sent == []

    async def test_success_sends_digest(self, monkeypatch) -> None:
        result = sc_freeze.FreezeResult(
            ran=True, frozen=5, targets=["2099-Q3", "2099"],
            cell_rows=[{"no": "D1", "clause": "c", "status": "achieved",
                        "department": ["安环部"], "note": None}],
        )
        ret, sent = await self._run(monkeypatch, result)
        assert ret is False and len(sent) == 1

    async def test_digest_failure_raises_for_retry(
        self, db_session, monkeypatch,
    ) -> None:
        result = sc_freeze.FreezeResult(ran=True, frozen=1, targets=["2099-Q3"])
        with pytest.raises(RuntimeError):
            await self._run(monkeypatch, result, digest_exc=RuntimeError("投递失败"))


# ═══════════════════════════════════════════════════════════════
# 速递格组装（纯函数，见 03 票）
# ═══════════════════════════════════════════════════════════════


class TestComplianceCell:
    def test_build_cell_counts_and_copy(self) -> None:
        from app.modules.safety.service.standard_check.freeze import (
            build_compliance_cell,
        )

        rows = [
            {"period_key": "2099-Q3", "no": "D4-01", "clause": "作业票审核覆盖率95%",
             "status": "achieved", "department": ["生产一部"], "note": None},
            {"period_key": "2099-Q3", "no": "D1-03", "clause": "责任书签订",
             "status": "manual_done", "department": ["安环部"], "note": None},
            {"period_key": "2099-Q3", "no": "D5-04", "clause": "隐患按期整改完成率",
             "status": "missed", "department": ["生产二部", "安环部"], "note": None},
            {"period_key": "2099-07", "no": "D3-06", "clause": "外来人员报备",
             "status": "no_data", "department": ["安环部"], "note": "visitor_notice 域未接入"},
        ]
        cell = build_compliance_cell(rows, quarter_key="2099-Q3")
        assert cell.tag_text == "标准符合性"
        assert "达成 **2**/3" in cell.stats
        assert "未达标 **1**" in cell.stats
        assert "无数据 **1**" in cell.stats
        assert "D5-04" in cell.detail and "生产二部" in cell.detail
        assert "visitor_notice 域未接入" in cell.detail
        assert "未达标" in cell.zone or "达标" in cell.zone

    def test_build_cell_all_achieved(self) -> None:
        from app.modules.safety.service.standard_check.freeze import (
            build_compliance_cell,
        )

        rows = [
            {"period_key": "2099-Q3", "no": "D4-01", "clause": "条款",
             "status": "achieved", "department": ["生产一部"], "note": None},
        ]
        cell = build_compliance_cell(rows, quarter_key="2099-Q3")
        assert "达成 **1**/1" in cell.stats
        assert cell.tag_color == "green"
