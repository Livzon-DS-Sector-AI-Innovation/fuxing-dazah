"""Agent 执行面三期（agent-action-p3）知识库 AI 生产三件测试。

覆盖 spec（.scratch/agent-action-p3/spec.md）T3：
generate_knowledge_card / generate_knowledge_ppt / generate_knowledge_summary。
定位双态（照二期 report_no/report_id 先例）：article_id 直传或 keyword
唯一命中；多命中返回候选让用户挑。

测试接缝：工具函数边界直接调用；KnowledgeService 方法打桩
（生成链内部调外部 AI，必须桩掉；get_articles 同桩保持一致）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_CREATOR,
    ROLE_MANAGER,
    ROLE_VIEWER,
    check,
)
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.knowledge_action_tools import (
    generate_knowledge_card,
    generate_knowledge_ppt,
    generate_knowledge_summary,
)


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _ctx(db: Any = None, role: str = "creator") -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(
            db=db or SimpleNamespace(), person=None, role=role,
            session_id="s1", channel="test",
        )
    )


def _article(aid: uuid.UUID, title: str) -> SimpleNamespace:
    return SimpleNamespace(id=aid, title=title, article_no="KB-001")


def _stub_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hits: list[SimpleNamespace] | None = None,
    card_ret: Any = None,
    ppt_ret: Any = None,
    summary_ret: Any = None,
) -> dict[str, Any]:
    """打桩 KnowledgeService 四方法；返回调用记录。"""
    from app.modules.safety.service.knowledge import KnowledgeService

    calls: dict[str, Any] = {"get_articles": [], "gen": []}

    async def fake_get_articles(self, skip, limit, category, status, keyword):
        calls["get_articles"].append(
            {"skip": skip, "limit": limit, "keyword": keyword}
        )
        return list(hits or []), len(hits or [])

    def _mk(name: str, ret: Any):
        async def fake(self, article_id, *args, **kwargs):
            calls["gen"].append({"method": name, "article_id": article_id})
            return ret
        return fake

    monkeypatch.setattr(KnowledgeService, "get_articles", fake_get_articles)
    monkeypatch.setattr(
        KnowledgeService, "generate_knowledge_card", _mk("card", card_ret)
    )
    monkeypatch.setattr(
        KnowledgeService,
        "generate_ppt",
        _mk("ppt", ppt_ret),
    )
    monkeypatch.setattr(
        KnowledgeService, "generate_summary", _mk("summary", summary_ret)
    )
    return calls


# ═══ 接线 ═══


class TestKnowledgeActionWiring:
    def test_tool_kind_write(self) -> None:
        for name in (
            "generate_knowledge_card",
            "generate_knowledge_ppt",
            "generate_knowledge_summary",
        ):
            assert registry.TOOL_KIND[name] is True

    def test_group_mounted(self) -> None:
        group = tool_selector.TOOL_GROUPS["knowledge"]
        assert "generate_knowledge_card" in group
        assert "generate_knowledge_ppt" in group
        assert "generate_knowledge_summary" in group

    @pytest.mark.parametrize(
        "message",
        [
            "给这份制度生成一张 AI 卡片",
            "帮我把这个文档做一份PPT",
            "给这篇规定生成摘要",
        ],
    )
    def test_route_hits_knowledge(self, message: str) -> None:
        decision = tool_selector.route_message(message)
        assert decision.path == "rule"
        group_tools = set(tool_selector.TOOL_GROUPS["knowledge"])
        assert group_tools & set(decision.tool_names), (
            f"{message} 未命中 knowledge 挂载: {decision}"
        )

    def test_permissions_admin_leader_only(self) -> None:
        for tool in (
            "generate_knowledge_card",
            "generate_knowledge_ppt",
            "generate_knowledge_summary",
        ):
            assert check(ROLE_CREATOR, tool)
            assert check(ROLE_MANAGER, tool)
            assert not check(ROLE_VIEWER, tool)


# ═══ 定位双态 ═══


class TestArticleResolution:
    def test_keyword_unique_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aid = uuid.uuid4()
        _stub_service(
            monkeypatch,
            hits=[_article(aid, "动火作业安全管理规定")],
            card_ret=SimpleNamespace(
                knowledge_card=SimpleNamespace(), card_version=2,
                message="卡片生成成功",
            ),
        )
        out = _run(generate_knowledge_card(_ctx(), keyword="动火作业"))
        assert out["success"] is True
        assert out["article_id"] == str(aid)
        assert out["title"] == "动火作业安全管理规定"

    def test_keyword_multi_hit_returns_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_service(
            monkeypatch,
            hits=[
                _article(uuid.uuid4(), "动火作业安全管理规定"),
                _article(uuid.uuid4(), "动火作业操作规程"),
            ],
        )
        out = _run(generate_knowledge_card(_ctx(), keyword="动火"))
        assert out["success"] is False
        assert "候选" in out["message"]
        assert len(out["candidates"]) == 2

    def test_keyword_zero_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_service(monkeypatch, hits=[])
        out = _run(generate_knowledge_summary(_ctx(), keyword="不存在的文档"))
        assert out["success"] is False
        assert "未找到" in out["message"]

    def test_no_locator_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_service(monkeypatch)
        out = _run(generate_knowledge_card(_ctx()))
        assert out["success"] is False
        assert "article_id 或 keyword" in out["message"]


# ═══ 三件生成 ═══


class TestGenerateTools:
    def test_card_success_and_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _stub_service(
            monkeypatch,
            card_ret=SimpleNamespace(
                knowledge_card=SimpleNamespace(
                    hazard_type_definitions=["火灾爆炸"],
                ),
                card_version=3,
                message="卡片生成成功",
            ),
        )
        aid = uuid.uuid4()
        out = _run(generate_knowledge_card(_ctx(), article_id=str(aid)))
        assert out["success"] is True
        assert out["card_version"] == 3
        assert calls["gen"][0]["article_id"] == aid

    def test_card_article_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_service(monkeypatch, card_ret=None)  # service: 文章不存在
        out = _run(generate_knowledge_card(_ctx(), article_id=str(uuid.uuid4())))
        assert out["success"] is False
        assert "不存在" in out["message"]

    def test_card_insufficient_content_message_passthrough(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = "文档正文内容不足，无法生成知识卡片。请先确保文档已解析全文。"
        _stub_service(
            monkeypatch, hits=[_article(uuid.uuid4(), "空文档")],
            card_ret=SimpleNamespace(
                knowledge_card=SimpleNamespace(), card_version=1, message=msg,
            ),
        )
        out = _run(generate_knowledge_card(_ctx(), keyword="空文档"))
        # 正文不足是「执行了但没生成」：如实透传 message，不算系统错误
        assert out["message"] == msg
        assert out["card_version"] == 1

    def test_ppt_zero_hit_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_service(monkeypatch, hits=[])
        out = _run(generate_knowledge_ppt(_ctx(), keyword="培训教材"))
        assert out["success"] is False
        assert "未找到" in out["message"]

    def test_ppt_success_with_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aid = uuid.uuid4()
        calls = _stub_service(
            monkeypatch,
            hits=[_article(aid, "受限空间作业培训教材")],
            ppt_ret=SimpleNamespace(
                download_url="uploads/safety/knowledge/ppt/x.pptx",
                file_name="受限空间作业培训教材.pptx",
                page_count=8,
                message="PPT 生成成功",
            ),
        )
        out = _run(
            generate_knowledge_ppt(
                _ctx(), keyword="受限空间", template="training", style="modern",
            )
        )
        assert out["success"] is True
        assert out["download_url"].startswith("uploads/")
        assert out["page_count"] == 8
        gen = calls["gen"][0]
        assert gen["article_id"] == aid

    def test_ppt_invalid_article_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_service(monkeypatch)
        out = _run(generate_knowledge_ppt(_ctx(), article_id="not-an-uuid"))
        assert out["success"] is False
        assert "无效" in out["message"]

    def test_summary_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_service(
            monkeypatch,
            hits=[_article(uuid.uuid4(), "化工过程安全管理导则")],
            summary_ret=SimpleNamespace(
                summary="本导则规定了化工过程安全管理的…", message="摘要生成成功，已保存到文档。",
            ),
        )
        out = _run(generate_knowledge_summary(_ctx(), keyword="化工过程"))
        assert out["success"] is True
        assert out["summary"].startswith("本导则")
