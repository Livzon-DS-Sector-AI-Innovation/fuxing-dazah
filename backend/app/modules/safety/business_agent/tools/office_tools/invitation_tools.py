"""宣传函（运动会邀请函）工具：查看 / 修改 / 精确补丁 / 回滚。

页面 = 模板 + content.json 渲染；发布到 GitHub Pages（单文件 PUT）。
写操作走统一确认流（requires_approval），权限仅 creator（见 core/permissions.py）。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety import invitation_page
from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

# 板块清单（update_invitation 的 section 参数取值）
_SECTIONS = invitation_page._SECTIONS


def _brief(content: dict[str, Any]) -> dict[str, Any]:
    """给模型看的板块速览（键与数据形状），避免每次全量吐 JSON。"""
    brief: dict[str, Any] = {}
    for key in _SECTIONS:
        val = content.get(key)
        if isinstance(val, list):
            brief[key] = f"列表×{len(val)}（元素键：{list(val[0].keys()) if val and isinstance(val[0], dict) else '标量'}）"
        elif isinstance(val, dict):
            brief[key] = {k: type(v).__name__ for k, v in val.items()}
        else:
            brief[key] = val
    return brief


async def read_invitation(ctx: RunContext[SafetyDeps]) -> dict:
    """查看运动会宣传函的当前内容与线上地址。

    返回线上 URL、每个板块的数据速览和完整内容 JSON（字段含中文键，
    结构与 update_invitation 的 section 参数一一对应）。修改前必先读本工具。

    Args:
        ctx: 运行上下文（自动注入）
    """
    content = invitation_page.load_content()
    _, _, _, public_url = invitation_page._github_conf()
    return {
        "url": public_url,
        "板块速览": _brief(content),
        "完整内容": content,
        "提示": (
            "修改流程：read_invitation → update_invitation(section, data) 整板块替换，"
            "或 patch_invitation_html(old_text, new_text) 做渲染产物上的精确文本替换；"
            "两种写操作都会挂确认卡。设计规范见 invitation-html 技能（load_skill）。"
        ),
    }


async def update_invitation(
    ctx: RunContext[SafetyDeps],
    section: str,
    data: Any,
    publish: bool = True,
) -> dict:
    """修改宣传函的一个板块并发布（写操作，会挂确认卡）。

    section 取值：meta描述 / 页头 / 信息条 / 温馨提示 / 流程 / 项目 / 积分 /
    奖项 / 赛区 / 助威 / 尾部 / 报名。data 为该板块的**完整新数据**（结构
    与 read_invitation 返回的同名板块一致；流程/项目/奖项/赛区/信息条 为
    列表，积分 为对象，其余为字符串或对象）。渲染前做结构校验，校验不过
    不发布。publish=False 时只保存草稿不发布。

    Args:
        ctx: 运行上下文（自动注入）
        section: 要替换的板块名（见工具说明）
        data: 该板块完整新数据
        publish: 是否发布上线（默认 true；false 仅存草稿）
    """
    if section not in _SECTIONS:
        return {"ok": False, "error": f"未知板块「{section}」，可用：{' / '.join(_SECTIONS)}"}
    content = invitation_page.load_content()
    content[section] = data
    problems = invitation_page.validate_content(content)
    if problems:
        return {"ok": False, "error": "结构校验未通过，未做任何修改：", "problems": problems}
    invitation_page.save_content(content)
    html = invitation_page.render(content)
    result: dict[str, Any] = {"ok": True, "section": section, "published": False}
    if publish:
        old_html = await invitation_page.fetch_published_html()
        if old_html:
            invitation_page.snapshot_current(old_html, content)
        pub = await invitation_page.publish_html(
            html, f"宣传函更新板块「{section}」（飞书机器人）",
        )
        result["published"] = pub.get("ok", False)
        if pub.get("ok"):
            result["url"] = pub["url"]
            result["生效提示"] = pub.get("note", "")
        else:
            result["error"] = pub.get("error")
            result["草稿"] = "内容已保存本地，配置 token 后重新 update 即可发布"
    return result


async def patch_invitation_html(
    ctx: RunContext[SafetyDeps],
    old_text: str,
    new_text: str,
) -> dict:
    """对宣传函渲染产物做精确文本替换并发布（写操作，会挂确认卡）。

    用于板块结构覆盖不到的角落微调（改一句文案、换 emoji、调一行备注）。
    old_text 必须在当前渲染 HTML 中**恰好出现一次**，否则拒绝执行并列出
    出现次数——此时请携带更多上下文让目标唯一。HTML/CSS/JS 结构性修改
    不适用本工具（应找开发改模板）。

    Args:
        ctx: 运行上下文（自动注入）
        old_text: 要替换的原文（精确匹配，含 HTML 标签时需完整）
        new_text: 替换后的文本
    """
    if not old_text or old_text == new_text:
        return {"ok": False, "error": "old_text 不能为空且不能与 new_text 相同"}
    content = invitation_page.load_content()
    html = invitation_page.render(content)
    count = html.count(old_text)
    if count == 0:
        return {"ok": False, "error": "old_text 在页面中不存在（请从 read_invitation 的内容核对原文）"}
    if count > 1:
        return {"ok": False, "error": f"old_text 出现 {count} 次，不唯一；请补充上下文使其唯一"}
    new_html = html.replace(old_text, new_text, 1)
    invitation_page.save_content(content)
    old_online = await invitation_page.fetch_published_html()
    if old_online:
        invitation_page.snapshot_current(old_online, content)
    pub = await invitation_page.publish_html(
        new_html, f"宣传函文本补丁（飞书机器人）：{old_text[:20]}",
    )
    result: dict[str, Any] = {"ok": pub.get("ok", False), "published": pub.get("ok", False)}
    if pub.get("ok"):
        result["url"] = pub["url"]
        result["生效提示"] = pub.get("note", "")
    else:
        result["error"] = pub.get("error")
    return result


async def rollback_invitation(ctx: RunContext[SafetyDeps]) -> dict:
    """把宣传函回滚到上一个发布版本（写操作，会挂确认卡）。

    使用最近一次发布前保存的快照（线上 HTML + 当时内容）覆盖当前状态并
    重新发布；快照保留最近 10 份，本工具只回滚一步。
    """
    snap = invitation_page.latest_snapshot()
    if not snap:
        return {"ok": False, "error": "没有可用快照（还没有发布过，或快照已被清理）"}
    html, content = snap
    invitation_page.save_content(content)
    pub = await invitation_page.publish_html(html, "宣传函回滚到上一版本（飞书机器人）")
    result: dict[str, Any] = {"ok": pub.get("ok", False)}
    if pub.get("ok"):
        result["url"] = pub["url"]
        result["生效提示"] = pub.get("note", "")
        result["回滚内容"] = "已恢复上一版本页面与内容数据"
    else:
        result["error"] = pub.get("error")
    return result
