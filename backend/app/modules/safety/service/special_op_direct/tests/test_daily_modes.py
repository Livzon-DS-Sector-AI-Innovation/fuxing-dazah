"""晨报 / 晚报双模式渲染与口径单测（2026-09-24 早晚报区分改造）。

覆盖：
- ReportBuilder 晚报构建器：已完成/进行中/待作业分区、夜间作业（18:00 阈值边界）、
  今日新增（计划外标记）、未完成高风险、口径标注、段落顺序
- ReportBuilder 晨报构建器：计划内/外拆分、低风险单行、空窗口隐藏新增段
- AIAnalyst 汇总 prompt 分模式要求（开工前检查 vs 收工+夜间管控）
- 速递卡双布局（晚报标签/进度副标题、晨报计划内外副标题）
- daily.run 晚报编排（固定时钟注入：AI 只分析未完成记录、推送标题、stats 扩展）
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.modules.safety.feishu.special_op_digest import build_special_op_digest
from app.modules.safety.service.special_op_direct import bitable_repo, daily
from app.modules.safety.service.special_op_direct.tests.factories import (
    DAY,
    HIGH_FIELDS,
    LOW_FIELDS,
    MEDIUM_FIELDS,
    FakeAnalyst,
    FakePusher,
    FakeReader,
    ms,
    record,
)
from app.modules.safety.service.special_operation_daily_report import (
    AIAnalyst,
    ReportBuilder,
)

# 固定时钟：DAY 当天 17:00 北京时间（= 09:00 UTC）
NOW_PM = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
# 晨报定时时刻：DAY 当天 08:00 北京时间（= 00:00 UTC）
NOW_AM = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
# 白天机器人查询时刻：12:00 北京时间
NOW_NOON = datetime(2026, 9, 11, 4, 0, tzinfo=UTC)

_OLD_SUBMITTED = ms(datetime(2026, 9, 10, 15, 0, tzinfo=UTC))  # 前一晚提交


def _view(record_id: str, **fields: Any) -> Any:
    payload = record(record_id, **fields)
    return bitable_repo.assess_view(bitable_repo.to_view(payload))


def _scenario() -> list[Any]:
    """8 条记录覆盖晚报全部分区（时间均为 UTC；BJT = UTC+8）。

    1 h_done        动火罐区     08:30—11:30  已完成(高风险)
    2 h_ongoing     动火RTO      13:00—18:30  进行中·夜间(高风险)
    3 h_pending     动火罐区     18:30—次日01:00 待作业·夜间(高风险)
    4 m_done        受限空间     09:00—13:00  已完成(中)
    5 m_pending     受限空间     17:30—18:00  待作业·非夜间(结束恰为 18:00 边界)
    6 l_done        临时用电     09:00—11:00  已完成(低)
    7 l_night       临时用电     20:00—次日06:00 待作业·夜间(低)
    8 new_unplanned 临时用电     14:00—16:30  已完成(低)·10:00 新提交·计划外
    """
    planned = {"报备类型": "计划内作业", "发起时间": _OLD_SUBMITTED}
    return [
        _view("h_done", **HIGH_FIELDS, **planned),
        _view(
            "h_ongoing",
            作业类型="动火作业", 作业地点="RTO焚烧炉二层", 作业内容="炉膛焊补",
            作业时间_开始时间=ms(datetime(2026, 9, 11, 5, 0, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 11, 10, 30, tzinfo=UTC)),
            作业时间_时长=5.5, **planned,
        ),
        _view(
            "h_pending",
            **HIGH_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 10, 30, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 12, 17, 0, tzinfo=UTC)),
            作业时间_时长=6.5, **planned,
        ),
        _view(
            "m_done", **MEDIUM_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 1, 0, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 11, 5, 0, tzinfo=UTC)),
            **planned,
        ),
        _view(
            "m_pending", **MEDIUM_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 9, 30, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 11, 10, 0, tzinfo=UTC)),
            **planned,
        ),
        _view(
            "l_done", **LOW_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 1, 0, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 11, 3, 0, tzinfo=UTC)),
            **planned,
        ),
        _view(
            "l_night", **LOW_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 12, 0, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 12, 22, 0, tzinfo=UTC)),
            **planned,
        ),
        _view(
            "new_unplanned", **LOW_FIELDS,
            报备类型="计划外作业",
            发起时间=ms(datetime(2026, 9, 11, 2, 0, tzinfo=UTC)),
            作业时间_开始时间=ms(datetime(2026, 9, 11, 6, 0, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 11, 8, 30, tzinfo=UTC)),
        ),
    ]


def _stats(views: list[Any]) -> dict[str, int]:
    return {
        "total": len(views), "effective_total": len(views),
        "high": sum(1 for v in views if v.daily_risk_level == "high"),
        "medium": sum(1 for v in views if v.daily_risk_level == "medium"),
        "low": sum(1 for v in views if v.daily_risk_level == "low"),
        "excluded": 0,
    }


# ── 晚报构建器 ──


def test_afternoon_report_sections_and_counts() -> None:
    views = _scenario()
    md = ReportBuilder.build(DAY, "afternoon", views, _stats(views), now=NOW_PM)

    assert md.splitlines()[0] == "📋 【特殊作业日报·晚报】 2026年09月11日"
    # 概况进度行：4 完成 / 1 进行 / 3 待作业 / 夜间 3
    assert "今日作业: 8 项 ｜ 已完成 4 · 进行中 1 · 待作业 3（今晚 18:00 后作业 3 项）" in md
    # 段落顺序：概况 < 已完成 < 新增 < 夜间 < 未完成高风险 < 中风险 < 低风险
    order = [
        md.index("📊 作业概况"),
        md.index("✅ 已完成作业（4 项，其中高风险 1 项）"),
        md.index("🆕 今日新增作业（08:00 以来 1 项）"),
        md.index("🌙 夜间作业（18:00 后 3 项）"),
        md.index("🔴 重点关注（未完成高风险 2 项）"),
        md.index("🟡 常规作业（中风险 2 项，其中未完成 1 项）"),
        md.index("🟢 低风险作业（3 项）: 临时用电 ×3"),
    ]
    assert order == sorted(order)
    # 已收工高风险点名 + 口径标注
    assert "已收工高风险点名:" in md
    assert "✔ 已按计划收工" in md
    assert "（口径：按计划结束时间推算收工，非现场实际确认）" in md
    # 新增条目带计划外标记与进度
    assert "【临时用电｜计划外】" in md
    assert "▸ 已完成" in md
    # 夜间条目进度（延入夜间的进行中 + 今晚开始的待作业）
    assert "▸ 进行中" in md
    assert "▸ 待作业" in md
    # 今晚盯防重点叙事
    assert "今晚盯防重点：" in md


def test_night_cutoff_boundaries() -> None:
    """结束恰为 18:00 不算夜间；开始恰为 18:00 算；跨到次日算。"""
    end_1800 = _view(
        "b1", **MEDIUM_FIELDS,
        作业时间_开始时间=ms(datetime(2026, 9, 11, 9, 30, tzinfo=UTC)),
        作业时间_结束时间=ms(datetime(2026, 9, 11, 10, 0, tzinfo=UTC)),
    )
    start_1800 = _view(
        "b2", **MEDIUM_FIELDS,
        作业时间_开始时间=ms(datetime(2026, 9, 11, 10, 0, tzinfo=UTC)),
        作业时间_结束时间=ms(datetime(2026, 9, 11, 12, 0, tzinfo=UTC)),
    )
    overnight = _view(
        "b3", **MEDIUM_FIELDS,
        作业时间_开始时间=ms(datetime(2026, 9, 11, 12, 0, tzinfo=UTC)),
        作业时间_结束时间=ms(datetime(2026, 9, 12, 22, 0, tzinfo=UTC)),
    )
    night = ReportBuilder.select_night_ops(DAY, [end_1800, start_1800, overnight])
    assert [v.record_id for v in night] == ["b2", "b3"]


def test_progress_helpers_edges() -> None:
    end_eq_now = _view(
        "p1", **MEDIUM_FIELDS,
        作业时间_开始时间=ms(datetime(2026, 9, 11, 1, 0, tzinfo=UTC)),
        作业时间_结束时间=ms(NOW_PM),
    )
    no_end = _view(
        "p2", **MEDIUM_FIELDS,
        作业时间_开始时间=ms(datetime(2026, 9, 11, 5, 0, tzinfo=UTC)),
        作业时间_结束时间=None,
    )
    future = _view(
        "p3", **MEDIUM_FIELDS,
        作业时间_开始时间=ms(datetime(2026, 9, 11, 10, 30, tzinfo=UTC)),
        作业时间_结束时间=ms(datetime(2026, 9, 12, 17, 0, tzinfo=UTC)),
    )
    assert ReportBuilder.is_completed(end_eq_now, NOW_PM) is True
    assert ReportBuilder.progress_label(no_end, NOW_PM) == "进行中"
    assert ReportBuilder.progress_label(future, NOW_PM) == "待作业"
    # 「完成时间」列（审批流时间）不参与收工判定：早于作业开始也不影响
    approved_early = _view(
        "p4", **MEDIUM_FIELDS, 完成时间=ms(datetime(2026, 9, 10, 15, 0, tzinfo=UTC)),
        作业时间_开始时间=ms(datetime(2026, 9, 11, 10, 30, tzinfo=UTC)),
        作业时间_结束时间=ms(datetime(2026, 9, 12, 17, 0, tzinfo=UTC)),
    )
    assert ReportBuilder.is_completed(approved_early, NOW_PM) is False


# ── 晨报构建器 ──


def test_morning_report_hides_empty_new_section_and_splits_report_type() -> None:
    views = _scenario()
    md = ReportBuilder.build(DAY, "today", views, _stats(views), now=NOW_AM)

    assert md.splitlines()[0] == "📋 【特殊作业日报】 2026年09月11日"
    # 计划内/外拆分（7 计划内 + 1 计划外，无未分类）
    assert "• 今日计划作业: 8 项（计划内 7 · 计划外 1）" in md
    # 08:00 定时推送时新增窗口恒空 → 整段隐藏
    assert "今日新增" not in md
    # 晨报高风险列全部（3 项）
    assert "🔴 重点关注（高风险 3 项）" in md
    # 低风险压缩为单行
    assert "🟢 低风险作业（3 项）: 临时用电 ×3" in md


def test_morning_query_shows_new_section() -> None:
    """白天机器人随时查询（today 模式）时新增段正常渲染。"""
    views = _scenario()
    md = ReportBuilder.build(DAY, "today", views, _stats(views), now=NOW_NOON)

    assert "🆕 今日新增作业（08:00 以来 1 项）" in md
    assert "【临时用电｜计划外】" in md


# ── AI 汇总 prompt 分模式 ──


def test_aggregate_prompt_mode_requirements() -> None:
    views = _scenario()
    high = [v for v in views if v.daily_risk_level == "high"]
    stats = {
        **_stats(views),
        "completed": 4, "ongoing": 1, "pending": 3, "night": 3,
    }

    pm = AIAnalyst._build_aggregate_prompt(DAY, "afternoon", high, ["作业1: x"], stats)
    assert "特殊作业日报·晚报" in pm
    assert "仅未完成高风险" in pm
    assert "进度: 已完成 4 · 进行中 1 · 待作业 3（今晚 18:00 后作业 3 项）" in pm
    assert "收工确认与夜间管控" in pm

    am = AIAnalyst._build_aggregate_prompt(DAY, "today", high, ["作业1: x"], stats)
    assert "开工前检查" in am
    assert "收工确认" not in am


# ── 速递卡双布局 ──


async def test_digest_afternoon_layout() -> None:
    views = _scenario()
    stats = {**_stats(views), "completed": 4, "ongoing": 1, "pending": 3, "night": 3}
    built = await build_special_op_digest(
        DAY, "afternoon", views, stats, None, "完整明细", now=NOW_PM,
    )
    assert built is not None
    assert built.title.startswith("📋 特殊作业速递·晚报")
    assert "完成 4" in built.subtitle and "夜间 3" in built.subtitle
    assert built.header_tags and built.header_tags[0]["text"]["content"] == "晚报"
    texts = json.dumps(built.elements, ensure_ascii=False)
    assert "已完成" in texts and "夜间作业" in texts and "今日新增" in texts
    assert "计划外 1" in texts


async def test_digest_morning_subtitle() -> None:
    views = _scenario()
    built = await build_special_op_digest(
        DAY, "today", views, _stats(views), None, "完整明细", now=NOW_AM,
    )
    assert built is not None
    assert built.title.startswith("📋 特殊作业速递 |")
    assert built.header_tags is None
    assert "计划内 7 · 计划外 1" in built.subtitle
    texts = json.dumps(built.elements, ensure_ascii=False)
    assert "夜间作业" not in texts


# ── daily.run 晚报编排（固定时钟）──


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return NOW_PM


class RecordingAnalyst(FakeAnalyst):
    """记录 analyze 入参的替身（晚报应只收到未完成记录）。"""

    def __init__(self) -> None:
        super().__init__()
        self.args: list[dict[str, Any]] = []

    async def analyze(
        self, report_date: date, mode: str, reports: Any, stats: dict[str, int],
    ) -> None:
        self.args.append({
            "mode": mode, "n": len(list(reports)), "stats": dict(stats),
        })
        return await super().analyze(report_date, mode, reports, stats)


async def test_run_afternoon_filters_finished_for_ai_and_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED", "false")
    monkeypatch.setenv("SAFETY_DAILY_DIGEST_ENABLED", "false")
    monkeypatch.setattr(daily, "datetime", _FixedDatetime)

    items = [
        record(
            "h_done", **HIGH_FIELDS,
            报备类型="计划内作业", 发起时间=_OLD_SUBMITTED,
        ),
        record(
            "h_pending", **HIGH_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 10, 30, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 12, 17, 0, tzinfo=UTC)),
            报备类型="计划内作业", 发起时间=_OLD_SUBMITTED,
        ),
        record(
            "l_done", **LOW_FIELDS,
            作业时间_开始时间=ms(datetime(2026, 9, 11, 1, 0, tzinfo=UTC)),
            作业时间_结束时间=ms(datetime(2026, 9, 11, 3, 0, tzinfo=UTC)),
            报备类型="计划内作业", 发起时间=_OLD_SUBMITTED,
        ),
    ]
    pusher = FakePusher()
    analyst = RecordingAnalyst()

    result = await daily.run(
        DAY, "afternoon", reader=FakeReader(records=items),
        pusher=pusher, analyst=analyst, writeback=False,
    )

    # 推送标题带「晚报」
    assert pusher.calls[0]["title"] == "特殊作业日报·晚报 - 2026-09-11"
    # AI 只收到未完成记录（1 条），stats 带进度/夜间扩展
    assert analyst.args[0]["n"] == 1
    assert analyst.args[0]["stats"]["completed"] == 2
    assert analyst.args[0]["stats"]["night"] == 1
    # 已收工高风险移入已完成段点名，🔴 只列未完成
    assert "✅ 已完成作业（2 项，其中高风险 1 项）" in result.markdown_report
    assert "🔴 重点关注（未完成高风险 1 项）" in result.markdown_report


# ── 安全速递总卡：晚报追加独立格子，不覆盖晨报格子 ──


class _FakeStore:
    """dict 版 Redis 接缝（hset/hgetall/expire/get/set）。"""

    def __init__(self) -> None:
        self.hash: dict[str, dict[str, str]] = {}
        self.kv: dict[str, str] = {}

    async def hset(self, key: str, field: str, value: str) -> None:
        self.hash.setdefault(key, {})[field] = value

    async def expire(self, key: str, ttl: int) -> None:
        assert ttl > 0

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hash.get(key, {}))

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kv[key] = value


async def _fake_sender(**kwargs: Any) -> str:
    return "om_digest"


async def _fake_updater(message_id: str, card: dict[str, Any]) -> bool:
    return True


async def test_digest_card_keeps_morning_and_evening_cells_separate() -> None:
    """晚报投 special_op_pm 独立格子：晨报格子不被覆盖，两格子按序渲染。"""
    from app.modules.safety.feishu import daily_digest

    store = _FakeStore()

    async def _capture_sender(**kwargs: Any) -> str:
        store.last_elements = kwargs.get("elements") or []
        return await _fake_sender()

    morning = daily_digest.DigestCell(
        tag_color="blue", tag_text="特殊作业", title="特殊作业日报",
        stats="今日计划 8 项", zone="", detail="晨报明细",
    )
    evening = daily_digest.DigestCell(
        tag_color="orange", tag_text="特殊作业·晚报", title="特殊作业日报·晚报",
        stats="完成 4 · 夜间 3", zone="", detail="晚报明细",
    )
    ok1 = await daily_digest.upsert_daily_digest(
        DAY, "special_op", morning,
        store=store, sender=_capture_sender, updater=_fake_updater,
    )
    ok2 = await daily_digest.upsert_daily_digest(
        DAY, "special_op_pm", evening,
        store=store, sender=_capture_sender, updater=_fake_updater,
    )
    assert ok1 and ok2

    fields = store.hash[f"safety:daily_digest:{DAY.isoformat()}"]
    assert set(fields) == {"special_op", "special_op_pm"}

    # 渲染顺序：晨报在前、晚报在后（CELL_ORDER 注册生效，否则 _load_cells 会丢弃）
    cells = await daily_digest._load_cells(store, DAY)
    elements = await daily_digest._build_elements(cells, {})
    texts = [json.dumps(e, ensure_ascii=False) for e in elements]
    assert any("特殊作业日报**" in t and "晨报明细" in t for t in texts)
    assert any("特殊作业日报·晚报**" in t and "晚报明细" in t for t in texts)
    assert texts.index(next(t for t in texts if "晨报明细" in t)) < texts.index(
        next(t for t in texts if "晚报明细" in t)
    )


async def test_run_upserts_evening_to_separate_cell_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """daily.run 晨/晚两次运行分别投 special_op / special_op_pm 格子。"""
    import app.modules.safety.feishu.daily_digest as daily_digest_module

    monkeypatch.setenv("SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED", "false")
    # 总卡开关保持开启（不设 env 即默认开）；upsert 打桩只记录调用
    calls: list[dict[str, Any]] = []

    async def _spy(report_date: date, key: str, cell: Any) -> bool:
        calls.append({"key": key, "title": cell.title, "color": cell.tag_color})
        return True

    monkeypatch.setattr(daily_digest_module, "upsert_daily_digest", _spy)

    items = [record("r1", **LOW_FIELDS, 报备类型="计划内作业", 发起时间=_OLD_SUBMITTED)]
    await daily.run(
        DAY, "today", reader=FakeReader(records=items),
        pusher=FakePusher(), analyst=FakeAnalyst(), writeback=False,
    )
    await daily.run(
        DAY, "afternoon", reader=FakeReader(records=items),
        pusher=FakePusher(), analyst=FakeAnalyst(), writeback=False,
    )

    assert [c["key"] for c in calls] == ["special_op", "special_op_pm"]
    assert calls[0]["title"] == "特殊作业日报" and calls[0]["color"] == "blue"
    assert calls[1]["title"] == "特殊作业日报·晚报" and calls[1]["color"] == "orange"

