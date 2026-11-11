"""宣传函工具单测（fake GitHub 通道，不触网）。

覆盖：渲染完整性 / update 板块替换与结构校验 / patch 唯一性约束 /
rollback 快照 / creator-only 权限。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.safety import invitation_page
from app.modules.safety.business_agent.core.permissions import (
    ROLE_CREATOR,
    ROLE_MANAGER,
    ROLE_TOOL_POLICY,
    ROLE_VIEWER,
    TOOL_PATCH_INVITATION_HTML,
    TOOL_READ_INVITATION,
    TOOL_ROLLBACK_INVITATION,
    TOOL_UPDATE_INVITATION,
)


# ── fixtures：隔离 var 目录 + fake 发布 ─────────────────────────

@pytest.fixture(autouse=True)
def _isolated_var(tmp_path, monkeypatch):
    var = tmp_path / "var" / "invitation"
    monkeypatch.setattr(invitation_page, "_VAR_DIR", var)
    monkeypatch.setattr(invitation_page, "_SNAPSHOT_DIR", var / "snapshots")
    return var


@pytest.fixture()
def _fake_publish(monkeypatch):
    """假发布：记录调用，直接成功。"""
    calls: list[dict] = []
    async def _fake_fetch():
        return "<html>online</html>"

    monkeypatch.setattr(invitation_page, "fetch_published_html", _fake_fetch)

    async def _pub(html, message):
        calls.append({"html": html, "message": message})
        return {"ok": True, "url": "https://example.github.io/x/", "note": "ok"}

    monkeypatch.setattr(invitation_page, "publish_html", _pub)
    return calls


# ── 渲染 ─────────────────────────────────────────────────────────

def test_render_contains_all_sections():
    html = invitation_page.render(invitation_page.load_content())
    for marker in (
        "共逐梦", "点击立即报名", "赛区组成", "积分规则", "奖项设置",
        "第一赛区", "优秀运动员", "cdD", "cheerBtn",
    ):
        assert marker in html, f"渲染缺 {marker}"
    assert "data:image/png;base64," in html  # 会徽内嵌


def test_render_follows_content_change():
    content = invitation_page.load_content()
    content["页头"]["口号"] = "测试口号甲\n测试口号乙"
    html = invitation_page.render(content)
    assert "测试口号甲<br>测试口号乙" in html


def test_content_file_exists_with_sections():
    content = invitation_page.load_content()
    for key in ("meta描述", "页头", "信息条", "流程", "项目", "积分", "奖项", "赛区", "助威", "尾部", "报名"):
        assert key in content


# ── update_invitation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_rejects_unknown_section(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import update_invitation
    result = await update_invitation(None, "不存在的板块", {"a": 1})
    assert result["ok"] is False and "可用" in result["error"]
    assert not _fake_publish


@pytest.mark.asyncio
async def test_update_rejects_bad_structure(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import update_invitation
    result = await update_invitation(None, "赛区", [{"编号": "一", "名称": "只有一区"}])
    assert result["ok"] is False
    assert any("8 项" in p for p in result["problems"])
    assert not _fake_publish  # 校验失败不发布


@pytest.mark.asyncio
async def test_update_section_and_publish(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import update_invitation
    result = await update_invitation(None, "温馨提示", "新的温馨提示文字")
    assert result["ok"] is True and result["published"] is True
    assert invitation_page.load_content()["温馨提示"] == "新的温馨提示文字"
    assert len(_fake_publish) == 1
    assert "新的温馨提示文字" in _fake_publish[0]["html"]


@pytest.mark.asyncio
async def test_update_draft_mode_skips_publish(monkeypatch):
    from app.modules.safety.business_agent.tools.office_tools import update_invitation
    async def _fake_fetch2():
        return "<html/>"

    monkeypatch.setattr(invitation_page, "fetch_published_html", _fake_fetch2)

    async def _fail_pub(html, message):  # pragma: no cover
        raise AssertionError("draft 模式不应发布")

    monkeypatch.setattr(invitation_page, "publish_html", _fail_pub)
    result = await update_invitation(None, "温馨提示", "草稿文案", publish=False)
    assert result["ok"] is True and result["published"] is False
    assert invitation_page.load_content()["温馨提示"] == "草稿文案"


# ── patch_invitation_html ────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_requires_unique_match(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import patch_invitation_html
    result = await patch_invitation_html(None, "不存在的文本xyz", "y")
    assert result["ok"] is False and "不存在" in result["error"]


@pytest.mark.asyncio
async def test_patch_rejects_multiple_matches(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import patch_invitation_html
    # "每项前三名" 在奖项中出现 3 次
    result = await patch_invitation_html(None, "每项前三名", "x")
    assert result["ok"] is False and "3 次" in result["error"]


@pytest.mark.asyncio
async def test_patch_unique_success(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import patch_invitation_html
    result = await patch_invitation_html(None, "QC部", "质量部")
    assert result["ok"] is True
    assert "质量部" in _fake_publish[0]["html"]


# ── rollback ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_without_snapshot_fails():
    from app.modules.safety.business_agent.tools.office_tools import rollback_invitation
    result = await rollback_invitation(None)
    assert result["ok"] is False and "快照" in result["error"]


@pytest.mark.asyncio
async def test_rollback_restores_previous(_fake_publish):
    from app.modules.safety.business_agent.tools.office_tools import rollback_invitation
    # 制造一次发布（产生快照：快照内容=发布前线上版）
    online = invitation_page.render(invitation_page.load_content())
    invitation_page.snapshot_current(online, invitation_page.load_content())
    # 当前内容改掉
    content = invitation_page.load_content()
    content["温馨提示"] = "已被改掉"
    invitation_page.save_content(content)
    result = await rollback_invitation(None)
    assert result["ok"] is True
    assert invitation_page.load_content()["温馨提示"] != "已被改掉"


# ── 权限：creator-only ───────────────────────────────────────────

def test_invitation_tools_creator_only():
    creator = ROLE_TOOL_POLICY[ROLE_CREATOR]
    manager = ROLE_TOOL_POLICY[ROLE_MANAGER]
    viewer = ROLE_TOOL_POLICY[ROLE_VIEWER]
    assert TOOL_READ_INVITATION in creator
    for tool in (TOOL_UPDATE_INVITATION, TOOL_PATCH_INVITATION_HTML, TOOL_ROLLBACK_INVITATION):
        assert tool in creator, f"{tool} 应对 creator 开放"
        assert tool not in manager, f"{tool} 不应对 manager 开放"
        assert tool not in viewer, f"{tool} 不应对 viewer 开放"
