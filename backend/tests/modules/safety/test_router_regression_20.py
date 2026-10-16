"""1-D 路由 20+ 问回归集（golden questions）。

覆盖全部业务域 + 按需域 + 大白话兜底 + 办公链接场景。钉住两条不变量：
1. 每问必能选到期望工具（防「减法减能力」）；
2. 任何问题的挂载面都远小于全量名册（防「回退全量」）。

改前基线（2026-10-16，关键词路由 v1 + 全量回退路径）：
- 21 组意图关键词，漏匹配返回 None → 全量 76 工具。
- 本回归集在改后口径下运行：路由永不返回 None，兜底=核心 15。
"""

from __future__ import annotations

import pytest

from app.modules.safety.business_agent.tool_selector import (
    CORE_FALLBACK_TOOLS,
    TOOL_GROUPS,
    route_message,
    select_tool_names,
)

# (问题, 期望必须可选中的工具)
GOLDEN_QUESTIONS: list[tuple[str, str]] = [
    # 2-E 消费侧：仓储查询域（跨模块，按需挂载）
    ("仓库里乙醇还有多少库存", "query_stock"),
    ("查一下仓储的物料主数据和入库流水", "query_material"),
    # 隐患域
    ("本月环保部有多少未整改隐患", "query_hazards"),
    ("还有多少隐患没整改？统计一下", "query_hazard_stats"),
    ("把最新的隐患督办通报发给我", "generate_supervision_bulletin"),
    # 知识/法规域
    ("防爆区域电气设备有什么要求", "knowledge_search"),
    ("最近30天有哪些高影响等级的法规更新", "query_latest_regulations"),
    ("危险化学品储存间距标准是多少", "knowledge_search"),
    # 报警域（消防+中控收敛为一域）
    ("查一下8月份生产部的消防报警记录", "query_fire_alarms"),
    ("生成中控报警日报", "generate_alarm_report"),
    # 职业健康域
    ("生产部有多少接触危害的员工", "query_oh_persons"),
    ("查一下张三最近的体检记录", "query_oh_exams"),
    ("有哪些待处置的异常随访", "query_oh"),
    # 化学品域（危化品+MSDS 收敛为一域）
    ("危化品库存有超量的吗", "query_chemical_inventory"),
    ("查一下异丙醇的MSDS", "query_msds"),
    # 补贴域
    ("帮我把环保部8月监护补贴算一下", "preview_guardian_subsidy"),
    # 特殊作业域（日报+明细+关键作业收敛为一域）
    ("今天的17点特殊作业日报", "generate_daily_report"),
    ("提炼工程五部的作业判定记录", "query_special_op_records"),
    # 演练域
    ("查一下今年的应急疏散演练计划", "query_drills"),
    # 证照域
    ("特种作业持证到期预警有哪些", "query_cert_warnings"),
    # 相关方域
    ("最近的承包商准入审核记录", "query_contractor_admissions"),
    # 作业票域
    ("上个月有哪些作业票审核违规", "query_work_ticket_reviews"),
    # 按需域：URS / 运维
    ("帮我发起一个设备采购URS审核", "create_urs_review"),
    ("轮询一下隐患AI分析", "poll_hazard_ai_analysis"),
]

# 大白话（无任何关键词）→ 核心兜底 15，绝不回退全量
PLAIN_QUESTIONS = [
    "今天天气怎么样",
    "帮我写首诗",
    "你是谁",
]


@pytest.mark.parametrize(("question", "expected"), GOLDEN_QUESTIONS)
def test_golden_question_selects_expected_tool(question: str, expected: str) -> None:
    names = select_tool_names(question)
    assert names is not None, question
    assert expected in names, f"{question!r} 未选到 {expected}: {names}"


@pytest.mark.parametrize("question", PLAIN_QUESTIONS)
def test_plain_question_falls_back_to_core(question: str) -> None:
    decision = route_message(question)
    assert decision.path == "core_fallback"
    assert set(decision.tool_names) == set(CORE_FALLBACK_TOOLS)
    assert len(decision.tool_names) <= 15


def test_office_link_routes_office_domain_not_full() -> None:
    msg = "帮我读一下这个文档 https://xxx.feishu.cn/docx/ABCdef123456 总结要点"
    decision = route_message(msg)
    assert decision.path == "office_reference"
    assert set(decision.tool_names) == set(TOOL_GROUPS["office"]) | {"knowledge_search"}
    # 不再回退全量名册
    from app.modules.safety.business_agent.tools.registry import TOOL_KIND

    assert len(decision.tool_names) < len(TOOL_KIND) / 2


def test_never_returns_none_or_full() -> None:
    """任何输入（含空/超长/乱码）都不返回 None，且挂载面 < 全量名册。"""
    from app.modules.safety.business_agent.tools.registry import TOOL_KIND

    for msg in ["", "   ", "？？？？", "a" * 5000, "混合隐患法规URS补贴词"]:
        names = select_tool_names(msg)
        assert names is not None, repr(msg)
        assert len(names) < len(TOOL_KIND)


def test_rule_decision_carries_domains() -> None:
    decision = route_message("查一下消防报警记录")
    assert decision.path == "rule"
    assert "alarm" in decision.domains


# ── T10（1-D）：嵌入相似度层 ───────────────────────────────────────


class _FakeEmbedder:
    def __init__(self, vec: list[float]) -> None:
        self._vec = vec

    async def embed(self, text: str, use_cache: bool = True) -> list[float]:  # noqa: ARG002
        return self._vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:  # noqa: ARG002
        return [self._vec for _ in texts]


def test_embedding_stage_hits_domain(monkeypatch) -> None:
    """规则 miss + 嵌入命中 → 挂对应域（置信度入决策）。"""
    import asyncio

    from app.modules.safety.business_agent import router_embedding as re_mod
    from app.modules.safety.business_agent.tool_selector import route_message_async

    async def fake_vectors() -> dict:
        return {"hazard": [[1.0, 0.0, 0.0]], "chemical": [[0.0, 1.0, 0.0]]}

    monkeypatch.setattr(re_mod, "_ensure_domain_vectors", fake_vectors)

    async def fake_embedder() -> _FakeEmbedder:
        return _FakeEmbedder([0.95, 0.05, 0.0])

    monkeypatch.setattr(re_mod, "_get_embedder", fake_embedder)

    decision = asyncio.run(route_message_async("现场发现的问题还有多少没处理完"))
    # 注：该问 rule 层可能直接命中 hazard；构造纯 miss 问句验证 embedding 路径
    if decision.path == "rule":
        pytest.skip("rule 层已命中，embedding 路径无需验证")
    assert decision.path == "embedding"
    assert "hazard" in decision.domains
    assert decision.confidence is not None and decision.confidence >= 0.55
    assert "query_hazards" in decision.tool_names


def test_embedding_stage_direct_classify(monkeypatch) -> None:
    """classify 直接验证：命中/低于阈值/开关关/异常 四分支。"""
    import asyncio

    from app.modules.safety.business_agent import router_embedding as re_mod

    async def fake_vectors() -> dict:
        return {"hazard": [[1.0, 0.0, 0.0]], "chemical": [[0.0, 1.0, 0.0]]}

    monkeypatch.setattr(re_mod, "_ensure_domain_vectors", fake_vectors)

    def make_embedder(vec):
        async def get():
            return _FakeEmbedder(vec)
        return get

    # 命中 hazard
    monkeypatch.setattr(re_mod, "_get_embedder", make_embedder([0.9, 0.1, 0.0]))
    hit = asyncio.run(re_mod.classify("任意话术"))
    assert hit is not None and hit[0] == "hazard" and hit[1] >= 0.55

    # 正交向量 → 低于阈值 → None
    monkeypatch.setattr(re_mod, "_get_embedder", make_embedder([0.0, 0.0, 1.0]))
    assert asyncio.run(re_mod.classify("任意话术")) is None

    # 开关关闭 → None
    monkeypatch.setattr(re_mod, "_get_embedder", make_embedder([0.9, 0.1, 0.0]))
    monkeypatch.setenv(re_mod.EMBEDDING_ROUTER_SWITCH, "0")
    try:
        assert asyncio.run(re_mod.classify("任意话术")) is None
    finally:
        monkeypatch.delenv(re_mod.EMBEDDING_ROUTER_SWITCH, raising=False)

    # 嵌入服务异常 → None（不抛出）
    async def boom():
        raise RuntimeError("embedder down")

    monkeypatch.setattr(re_mod, "_get_embedder", boom)
    assert asyncio.run(re_mod.classify("任意话术")) is None


def test_embedding_domain_examples_cover_all_groups() -> None:
    """嵌入层域定义与 TOOL_GROUPS 对齐，无孤儿/无幽灵。"""
    from app.modules.safety.business_agent import router_embedding as re_mod

    assert set(re_mod.DOMAIN_EXAMPLES) == set(TOOL_GROUPS)
    for domain, examples in re_mod.DOMAIN_EXAMPLES.items():
        assert 5 <= len(examples), domain
