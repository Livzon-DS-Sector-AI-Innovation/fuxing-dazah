"""人员流动分析（/turnover-analysis）：指标计算、API 数据聚合、AI 降级。

AI 客户端全程 monkeypatch（不依赖真实 DeepSeek 调用）。
"""

from datetime import date
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.ai_service import AiChatService
from app.modules.hr.analysis_service import TurnoverAnalysisService
from app.modules.hr.models import DepartureRecord, OnboardingRecord
from tests.modules.hr.conftest import _rand

# ─── 指标计算（纯函数） ───


def test_metrics_normal_case():
    metrics = TurnoverAnalysisService._calculate_metrics({
        "onboarding_count": 10, "departure_count": 4, "current_headcount": 26,
    })
    # 净增 6；期初 = 26 - 6 = 20；流失率 = 4/20*100 = 20%
    assert metrics.net_change == 6
    assert metrics.initial_headcount == 20
    assert metrics.turnover_rate == 20.0


def test_metrics_zero_initial_headcount():
    """期初人数 ≤ 0 时归零且流失率为 0（防除零）。期初 = 在职 + 离职 - 入职。"""
    metrics = TurnoverAnalysisService._calculate_metrics({
        "onboarding_count": 10, "departure_count": 5, "current_headcount": 0,
    })
    assert metrics.net_change == 5
    assert metrics.initial_headcount == 0
    assert metrics.turnover_rate == 0.0


# ─── API 聚合（AI mock） ───


async def _fake_stream_ok(self, messages, system_prompt=None):
    yield {"type": "content", "text": "一、核心问题诊断：人员"}
    yield {"type": "content", "text": "流失风险中。"}


async def test_endpoint_aggregates_records_and_ai_summary(
    db_session: AsyncSession, client: AsyncClient,
):
    """近 6 个月窗口内的入职/离职记录进入统计；AI 摘要取自流式拼接。"""
    dept = _rand("流动部")
    db_session.add(OnboardingRecord(
        employee_number=_rand("INB"), name="新员工", department=dept,
        position="操作工", hire_date=date.today(), is_employed="是",
    ))
    db_session.add(DepartureRecord(
        name="离职员工", department=dept, position="操作工",
        offboarding_date=date.today(), offboarding_type="辞职",
    ))
    await db_session.flush()

    with patch.object(AiChatService, "stream_chat", _fake_stream_ok):
        res = await client.get("/api/v1/hr/turnover-analysis")
    assert res.status_code == 200, res.text
    data = res.json()["data"]

    raw = data["raw_data"]
    # 共享库可能还有其他近期数据，用本部门精确断言
    assert raw["onboarding_by_department"].get(dept, 0) >= 1
    assert raw["departure_by_department"].get(dept, 0) >= 1
    assert raw["onboarding_count"] >= 1
    assert raw["departure_count"] >= 1
    assert raw["current_headcount"] >= 1

    assert data["ai_summary"] == "一、核心问题诊断：人员流失风险中。"

    metrics = data["metrics"]
    assert metrics["net_change"] == raw["onboarding_count"] - raw["departure_count"]
    assert isinstance(metrics["turnover_rate"], float)


async def test_ai_failure_falls_back_to_data_summary(client: AsyncClient):
    """AI 调用失败时降级为数据事实摘要，不抛 500。"""
    async def _broken_stream(self, messages, system_prompt=None):
        raise RuntimeError("AI 服务不可用")
        yield  # noqa: B027 — 保持为 async generator

    with patch.object(AiChatService, "stream_chat", _broken_stream):
        res = await client.get("/api/v1/hr/turnover-analysis")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert "统计周期" in data["ai_summary"]
    assert data["ai_suggestions"] == []


async def test_departure_reason_list_values_counted_per_item(
    db_session: AsyncSession, client: AsyncClient,
):
    """回归：离职原因是 JSON 多选（list），逐项计数而不是把 list 当键（TypeError → 500）。"""
    dept = _rand("原因部")
    db_session.add(DepartureRecord(
        name="多原因离职", department=dept, position="操作工",
        offboarding_date=date.today(), offboarding_type="辞职",
        offboarding_reason=["家庭原因", "薪资原因"],
        offboarding_reason_2=["个人发展"],
    ))
    await db_session.flush()

    with patch.object(AiChatService, "stream_chat", _fake_stream_ok):
        res = await client.get("/api/v1/hr/turnover-analysis")
    assert res.status_code == 200, res.text
    reasons = res.json()["data"]["raw_data"]["departure_by_reason"]
    assert reasons.get("家庭原因", 0) >= 1
    assert reasons.get("薪资原因", 0) >= 1
    assert reasons.get("个人发展", 0) >= 1
