"""链1 年度培训需求生成：AI 插件 + 五源 digest + 生成/采纳/驳回测试。

接缝（一期拍板的双接缝）：① opener 替身（hazard_id/hazard/violation/
training 四客户端注入）② ai_service 构造注入（假 chat_parsed）。
PG 部分走 db_session（dev 库回滚会话），年份用 2099 隔离并在收尾清行，
不污染线上口径。规格：docs/DESIGN-教育培训与行为管控域-二期培训生产链-
开发规格-20261023.md §4/§9。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import delete

from app.modules.safety.ai_training_demand import (
    TrainingDemandError,
    TrainingDemandInput,
    TrainingDemandPlugin,
)
from app.modules.safety.models.training_demand_draft import (
    STATUS_ADOPTED,
    STATUS_DRAFT,
    STATUS_REJECTED,
    TrainingDemandDraft,
)
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior import demand
from app.modules.safety.service.training_behavior.common import BJ_TZ

_TEST_YEAR = 2099  # 与 S1 一致的隔离年份口径（线上查询永不命中）

_RAW_AI = {
    "summary": "法定缺口1条+高发违章2条",
    "demands": [
        {
            "position": "新员工",
            "topic": "危化品单位新员工岗前三级教育",
            "suggested_hours": 72,
            "form": "线下",
            "audience": "本年度新入职员工",
            "basis": "输入显示未安排岗前三级教育",
            "is_statutory_gap": True,
        },
        {
            "position": "电工、焊工",
            "topic": "特种作业复审培训",
            "suggested_hours": 4,
            "form": "实操",
            "audience": "电工与焊工持证人员",
            "basis": "本年度操作违章（一般）3 次",
            "is_statutory_gap": False,
        },
        {
            "position": "全体员工",
            "topic": "新《安全生产法》宣贯",
            "suggested_hours": 2,
            "form": "线上",
            "audience": "全员",
            "basis": "本年度新收录《安全生产法》",
            "is_statutory_gap": False,
        },
    ],
    "statutory_notes": ["从业人员年度再培训≥20学时未见安排"],
}


class FakeAIService:
    def __init__(self, raw: dict | Exception = _RAW_AI) -> None:
        self.raw = raw
        self.calls: list[dict] = []

    async def chat_parsed(self, *, messages, expected_keys, temperature=None):
        self.calls.append(
            {"messages": messages, "expected_keys": expected_keys,
             "temperature": temperature}
        )
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


class FakeRecordsClient:
    def __init__(self, records: list[dict] | None = None) -> None:
        self.records: list[dict] = records or []
        self.created: list[dict] = []
        self.fail_create = False

    async def list_all_records(self, **kwargs) -> list[dict]:
        return self.records

    async def create_record(self, fields: dict) -> dict:
        if self.fail_create:
            raise RuntimeError("bitable write boom")
        self.created.append(fields)
        return {"record_id": f"recT{len(self.created)}"}


def _bj_ms(*, year: int, month: int = 6, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=BJ_TZ).timestamp() * 1000)


def _hid_row(
    position: str | None, behavior: str, controls: str | None = None
) -> dict:
    fields: dict[str, Any] = {"不规范作业行为表现（人工）": behavior}
    if position:
        fields["岗位（人工）"] = position
    if controls:
        fields["现有管理控制措施（AI）"] = controls
    return {"record_id": uuid.uuid4().hex, "fields": fields}


def _hazard_row(category: str | None, *, year: int) -> dict:
    fields: dict[str, Any] = {"检查日期": _bj_ms(year=year)}
    if category:
        fields["隐患类别（AI）"] = category
    return {"record_id": uuid.uuid4().hex, "fields": fields}


def _violation_row(category: str, level: str, *, year: int) -> dict:
    return {"record_id": uuid.uuid4().hex, "fields": {
        "违章日期": _bj_ms(year=year),
        "违章类别": category,
        "违章等级": level,
    }}


def _training_row(
    name: str, status: str, *, year: int, passed: str | None = None,
    expected: str | None = None,
) -> dict:
    fields: dict[str, Any] = {
        "培训名称": name, "状态": status, "计划日期": _bj_ms(year=year),
    }
    if passed is not None:
        fields["考核合格人数"] = passed
    if expected is not None:
        fields["应到人数"] = expected
    return {"record_id": uuid.uuid4().hex, "fields": fields}


def _opener(
    *,
    hid: FakeRecordsClient | None = None,
    hazard: FakeRecordsClient | None = None,
    violation: FakeRecordsClient | None = None,
    training: FakeRecordsClient | None = None,
):
    hid = hid or FakeRecordsClient()
    hazard = hazard or FakeRecordsClient()
    violation = violation or FakeRecordsClient()
    training = training or FakeRecordsClient()
    clients = {
        ("hazard_id", "identification"): hid,
        ("hazard", "hazard"): hazard,
        ("training_behavior", "violation"): violation,
        ("training_behavior", "training"): training,
    }

    def open_client(domain: str, kind: str):
        if (domain, kind) not in clients:
            raise BitableConfigError(f"未配置: {domain}/{kind}")
        return clients[(domain, kind)]

    return open_client, hid, hazard, violation, training


@pytest.fixture
async def demand_db(db_session):
    """草案 PG 测试：2099 年隔离 + 用后清行（服务内 commit 会真落库）。"""
    yield db_session
    from sqlalchemy.ext.asyncio import AsyncSession

    session: AsyncSession = db_session
    await session.execute(
        delete(TrainingDemandDraft).where(TrainingDemandDraft.year == _TEST_YEAR)
    )
    await session.commit()


async def _make_draft(
    db, *, topic: str = "测试草案", position: str = "电工", gap: bool = False,
    form: str | None = "线下",
) -> TrainingDemandDraft:
    draft = TrainingDemandDraft(
        year=_TEST_YEAR, position=position, topic=topic,
        suggested_hours=4, form=form, audience="电工岗",
        basis="测试依据", is_statutory_gap=gap, status=STATUS_DRAFT,
    )
    db.add(draft)
    await db.commit()
    return draft


# ── 插件 ────────────────────────────────────────────────────────


class TestPlugin:
    async def test_generate_parses_demands(self) -> None:
        service = FakeAIService()
        output = await TrainingDemandPlugin(service).generate(
            TrainingDemandInput(
                hazard_id_digest="【电工】\n- 无证上岗",
                hazard_stats="2098 年隐患共 3 条",
                violation_stats="2098 年违章共 2 条",
                regulation_list="本年度新收录/修订法规 1 部：",
                last_year_summary="2098 年计划 5 项，完成 4 项",
            )
        )
        assert output.summary == "法定缺口1条+高发违章2条"
        assert len(output.demands) == 3
        gap_row = output.demands[0]
        assert gap_row.is_statutory_gap is True
        assert gap_row.suggested_hours == 72.0
        assert output.statutory_notes == ["从业人员年度再培训≥20学时未见安排"]
        # 调用形态：temp 0.2 + 三键 + 五段 user prompt
        call = service.calls[0]
        assert call["temperature"] == 0.2
        assert call["expected_keys"] == ["summary", "demands", "statutory_notes"]
        user_msg = call["messages"][1]["content"]
        assert "## 一、危险源辨识摘要" in user_msg
        assert "无证上岗" in user_msg
        assert "## 五、上学年培训完成情况" in user_msg

    async def test_empty_demands_raises(self) -> None:
        plugin = TrainingDemandPlugin(FakeAIService({
            "summary": "s", "demands": [], "statutory_notes": [],
        }))
        try:
            await plugin.generate(TrainingDemandInput())
            raise AssertionError("应抛 TrainingDemandError")
        except TrainingDemandError:
            pass

    async def test_ai_failure_wraps_error(self) -> None:
        plugin = TrainingDemandPlugin(FakeAIService(RuntimeError("boom")))
        try:
            await plugin.generate(TrainingDemandInput())
            raise AssertionError("应抛 TrainingDemandError")
        except TrainingDemandError:
            pass

    async def test_coercions(self) -> None:
        output = TrainingDemandPlugin(FakeAIService({
            "summary": "s",
            "demands": [{
                "position": "p", "topic": "t", "suggested_hours": "8",
                "form": "线下", "audience": "a", "basis": "b",
                "is_statutory_gap": "true",
            }],
            "statutory_notes": "单条说明",
        })).generate(TrainingDemandInput())
        result = await output
        assert result.demands[0].suggested_hours == 8.0
        assert result.demands[0].is_statutory_gap is True
        assert result.statutory_notes == ["单条说明"]


# ── 五源 digest 组装（纯函数） ─────────────────────────────────


class TestDigestBuilders:
    def test_hazard_id_digest_groups_and_limits(self) -> None:
        rows = [_hid_row("电工", f"违规行为{i}") for i in range(7)]
        rows.append(_hid_row("焊工", "未办动火证", controls="动火审批制度"))
        rows.append(_hid_row(None, "无岗位行为"))
        rows.append(_hid_row("电工", ""))  # 无行为跳过
        digest = demand.build_hazard_id_digest(rows)
        assert "【电工】" in digest and "【焊工】" in digest
        assert "（未填岗位）" in digest
        assert digest.count("- 违规行为") == 5  # 每岗位前 5
        assert "违规行为4" in digest and "违规行为5" not in digest
        assert "未办动火证（现有管理控制：动火审批制度）" in digest

    def test_hazard_id_digest_total_cap(self) -> None:
        rows = []
        for pos in range(45):  # 45 岗位 × 5 = 225 > 200
            rows.extend(_hid_row(f"岗{pos}", f"行为{i}") for i in range(5))
        digest = demand.build_hazard_id_digest(rows)
        assert digest.count("- 行为") == 200
        assert "已达 200 行上限" in digest

    def test_hazard_id_digest_empty(self) -> None:
        assert "无可用" in demand.build_hazard_id_digest([])

    def test_hazard_stats_year_filter_and_top(self) -> None:
        rows = (
            [_hazard_row("高处坠落", year=2098) for _ in range(7)]
            + [_hazard_row("触电", year=2098) for _ in range(3)]
            + [_hazard_row("噪声超标", year=2098)]
            + [_hazard_row("往年类别", year=2097)]  # 统计年外剔除
        )
        digest = demand.build_hazard_stats(rows, year=2098)
        assert "共 11 条" in digest
        assert "- 高处坠落：7 次" in digest and "- 触电：3 次" in digest
        assert "往年类别" not in digest

    def test_hazard_stats_empty(self) -> None:
        assert "无隐患类别统计" in demand.build_hazard_stats([], year=2098)

    def test_violation_stats_category_level(self) -> None:
        rows = (
            [_violation_row("操作违章", "一般", year=2098) for _ in range(4)]
            + [_violation_row("操作违章", "严重", year=2098)]
            + [_violation_row("防护缺失", "一般", year=2098)]
        )
        digest = demand.build_violation_stats(rows, year=2098)
        assert "- 操作违章（一般）：4 次" in digest
        assert "- 操作违章（严重）：1 次" in digest

    def test_regulation_list_cap(self) -> None:
        rows = [(f"法规{i}号", None) for i in range(35)]
        digest = demand.build_regulation_list(rows)
        assert digest.count("《") == 30
        assert "仅列前 30 部" in digest
        assert "（本年度无新收录/修订法规记录）" in demand.build_regulation_list([])

    def test_last_year_summary(self) -> None:
        rows = [
            _training_row("完成项A", "已完成", year=2098),
            _training_row("完成项B", "已完成", year=2098),
            _training_row("薄弱项C", "已完成", year=2098, passed="8", expected="10"),
            _training_row("未完成项D", "进行中", year=2098),
            _training_row("取消项E", "已取消", year=2098),
            _training_row("往年项F", "已完成", year=2097),
        ]
        digest = demand.build_last_year_summary(rows, year=2098)
        assert "计划 4 项（非取消），已完成 3 项，完成率 75%" in digest
        assert "薄弱项C（合格 8/应到 10）" in digest

    def test_last_year_summary_no_weak(self) -> None:
        rows = [_training_row("满合格", "已完成", year=2098, passed="10", expected="10")]
        digest = demand.build_last_year_summary(rows, year=2098)
        assert "无（合格数均达应到或未填考核数）" in digest

    async def test_collect_all_disconnected_degrades(self, db_session) -> None:
        def opener(domain: str, kind: str):
            raise BitableConfigError("未接入")

        demand_input, profile = await demand.collect_five_sources(
            db_session, opener, year=2099
        )
        assert profile["disconnected"] == 4
        assert demand_input.hazard_id_digest == "（危险源辨识数据未接入）"
        assert demand_input.hazard_stats == "（隐患统计数据未接入）"
        assert demand_input.violation_stats == "（违章档案数据未接入）"
        assert demand_input.last_year_summary == "（培训台账数据未接入）"
        assert demand_input.regulation_list == "（本年度无新收录/修订法规记录）"


# ── 生成编排（PG） ──────────────────────────────────────────────


class TestGenerate:
    async def test_ai_output_to_draft_rows(self, demand_db) -> None:
        opener, *_ = _opener(hazard=FakeRecordsClient(
            [_hazard_row("高处坠落", year=2098)]
        ))
        outcome = await demand.generate_demand_drafts(
            demand_db, year=_TEST_YEAR,
            opener=opener, ai_service=FakeAIService(),
        )
        assert outcome["count"] == 3
        assert outcome["replaced"] == 0
        rows = await demand.list_drafts(demand_db, year=_TEST_YEAR)
        assert len(rows) == 3
        gap_rows = [r for r in rows if r["is_statutory_gap"]]
        assert len(gap_rows) == 1
        assert gap_rows[0]["topic"] == "危化品单位新员工岗前三级教育"
        assert gap_rows[0]["status_label"] == "草案"
        assert rows[0]["is_statutory_gap"] is True  # 法定缺口排前

    async def test_regenerate_replaces_drafts_keeps_final(
        self, demand_db
    ) -> None:
        opener, _, _, _, training_client = _opener()
        await demand.generate_demand_drafts(
            demand_db, year=_TEST_YEAR, opener=opener, ai_service=FakeAIService()
        )
        rows = await demand.list_drafts(demand_db, year=_TEST_YEAR)
        adopted_id = rows[0]["id"]      # 法定缺口行
        rejected_id = rows[1]["id"]
        await demand.adopt_draft(demand_db, adopted_id, opener=opener)
        await demand.reject_draft(demand_db, rejected_id)

        raw2 = {
            "summary": "第二轮", "statutory_notes": [],
            "demands": [_RAW_AI["demands"][1], _RAW_AI["demands"][2]],
        }
        outcome = await demand.generate_demand_drafts(
            demand_db, year=_TEST_YEAR, opener=opener,
            ai_service=FakeAIService(raw2),
        )
        assert outcome["replaced"] == 1  # 只替换剩余 1 条 draft

        drafts = await demand.list_drafts(
            demand_db, year=_TEST_YEAR, status=STATUS_DRAFT
        )
        adopted = await demand.list_drafts(
            demand_db, year=_TEST_YEAR, status=STATUS_ADOPTED
        )
        rejected = await demand.list_drafts(
            demand_db, year=_TEST_YEAR, status=STATUS_REJECTED
        )
        assert len(drafts) == 2
        assert len(adopted) == 1 and adopted[0]["id"] == adopted_id
        assert len(rejected) == 1 and rejected[0]["id"] == rejected_id
        assert training_client.created  # 采纳已写台账


# ── 采纳/驳回（PG + Bitable 替身） ──────────────────────────────


class TestAdopt:
    async def test_adopt_maps_fields_to_bitable(self, demand_db) -> None:
        draft = await _make_draft(
            demand_db, topic="三级教育", position="电工、焊工,仪表工",
            gap=True, form="线下",
        )
        opener, _, _, _, training_client = _opener()
        result = await demand.adopt_draft(demand_db, str(draft.id), opener=opener)
        fields = training_client.created[0]
        assert fields["培训名称"] == "三级教育"
        assert fields["组织部门"] == ["电工", "焊工", "仪表工"]
        assert fields["培训学时"] == 4.0
        assert fields["培训形式"] == "线下"
        assert fields["状态"] == "未开始"
        assert fields["备注"].startswith("【法定缺口】依据：测试依据；对象：电工岗")
        assert result["adopted_record_id"] == "recT1"
        assert draft.status == STATUS_ADOPTED
        assert draft.adopted_record_id == "recT1"

    async def test_adopt_unregistered_form_omits_select(self, demand_db) -> None:
        draft = await _make_draft(demand_db, form="现场演示")
        opener, _, _, _, training_client = _opener()
        await demand.adopt_draft(demand_db, str(draft.id), opener=opener)
        fields = training_client.created[0]
        assert "培训形式" not in fields  # 坑5：不写未注册选项
        assert "形式待定（AI建议：现场演示）" in fields["备注"]

    async def test_adopt_twice_rejected(self, demand_db) -> None:
        draft = await _make_draft(demand_db)
        opener = _opener()[0]
        await demand.adopt_draft(demand_db, str(draft.id), opener=opener)
        with pytest.raises(demand.DemandStateError):
            await demand.adopt_draft(demand_db, str(draft.id), opener=opener)

    async def test_adopt_bitable_failure_keeps_draft(self, demand_db) -> None:
        draft = await _make_draft(demand_db)
        opener, _, _, _, training_client = _opener()
        training_client.fail_create = True
        with pytest.raises(RuntimeError):
            await demand.adopt_draft(demand_db, str(draft.id), opener=opener)
        await demand_db.refresh(draft)
        assert draft.status == STATUS_DRAFT  # 失败可重试
        assert draft.adopted_record_id is None

    async def test_adopt_not_connected_raises(self, demand_db) -> None:
        draft = await _make_draft(demand_db)

        def opener(domain: str, kind: str):
            raise BitableConfigError("未接入")

        with pytest.raises(demand.DemandStateError):
            await demand.adopt_draft(demand_db, str(draft.id), opener=opener)

    async def test_adopt_missing_draft(self, demand_db) -> None:
        with pytest.raises(demand.DemandStateError):
            await demand.adopt_draft(
                demand_db, str(uuid.uuid4()), opener=_opener()[0]
            )


class TestReject:
    async def test_reject_draft(self, demand_db) -> None:
        draft = await _make_draft(demand_db)
        result = await demand.reject_draft(demand_db, str(draft.id))
        assert result["status"] == STATUS_REJECTED
        assert draft.status == STATUS_REJECTED

    async def test_reject_adopted_forbidden(self, demand_db) -> None:
        draft = await _make_draft(demand_db)
        await demand.adopt_draft(demand_db, str(draft.id), opener=_opener()[0])
        with pytest.raises(demand.DemandStateError):
            await demand.reject_draft(demand_db, str(draft.id))

    async def test_list_status_filter_validation(self, demand_db) -> None:
        with pytest.raises(demand.DemandStateError):
            await demand.list_drafts(demand_db, status="已采纳")
