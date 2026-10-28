"""知识库 AI 生产执行面（agent-action-p3）：卡片/PPT/摘要三件。

- generate_knowledge_card：AI 从文档全文生成 6 维度知识卡片并回写
- generate_knowledge_ppt：AI 生成大纲 + python-pptx 落盘，返回下载路径
- generate_knowledge_summary：AI 生成结构化摘要并回写

工具体不重写业务逻辑：直接调 KnowledgeService 对应方法（同步 await，
内部闭环含回写）。文档定位双态（照二期 report_no/report_id 先例）：
article_id（UUID）直传，或 keyword 模糊匹配（title/summary/content/tags/
article_no/source/author，唯一命中即用；多命中返回候选让用户挑）。
生成是同步 AI 调用（可能数十秒），确认卡应提示用户稍候。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

__all__ = [
    "generate_knowledge_card",
    "generate_knowledge_ppt",
    "generate_knowledge_summary",
]

_CANDIDATE_LIMIT = 8


def _new_service(ctx: RunContext[SafetyDeps]) -> Any:
    from app.modules.safety.service.knowledge import KnowledgeService

    return KnowledgeService(ctx.deps.db)


async def _resolve_article(
    ctx: RunContext[SafetyDeps],
    article_id: str,
    keyword: str,
) -> tuple[uuid.UUID | None, str, dict[str, Any] | None]:
    """双态定位文章。返回 (article_uuid, title, error_dict)；error 非 None 即失败。"""
    service = _new_service(ctx)
    aid_raw = (article_id or "").strip()
    kw_raw = (keyword or "").strip()
    if not aid_raw and not kw_raw:
        return None, "", {
            "success": False,
            "message": "请提供 article_id 或 keyword 至少一项（keyword 为文档标题等关键词，用于定位知识库文章）",
        }
    if aid_raw:
        try:
            return uuid.UUID(aid_raw), "", None
        except (ValueError, TypeError):
            return None, "", {
                "success": False,
                "message": f"文章 ID 无效：{aid_raw!r}（应为 UUID）",
            }
    items, _total = await service.get_articles(0, _CANDIDATE_LIMIT, None, None, kw_raw)
    if not items:
        return None, "", {
            "success": False,
            "message": f"未找到与「{kw_raw}」匹配的知识库文档，请换个关键词或确认文档已收录",
        }
    if len(items) > 1:
        candidates = [
            {"article_id": str(a.id), "title": a.title or "(无标题)"}
            for a in items
        ]
        return None, "", {
            "success": False,
            "message": f"「{kw_raw}」匹配到 {len(items)} 篇文档，请从候选中指定一篇（回复标题或 article_id）",
            "candidates": candidates,
        }
    a = items[0]
    return a.id, a.title or "", None


async def generate_knowledge_card(
    ctx: RunContext[SafetyDeps],
    article_id: str = "",
    keyword: str = "",
) -> dict[str, Any]:
    """为知识库文档生成 AI 知识卡片（6 维度结构化，回写文档；写操作）。

    Args:
        article_id: 文档 UUID（可选）
        keyword: 文档关键词（如标题「动火作业安全管理规定」；唯一命中即用）

    示例：给这份制度生成一张 AI 卡片。

    注意：此操作会调用 AI 并回写文档（card_version+1），需要用户确认后才执行；
    确认卡应复述文档标题；生成是同步 AI 调用，可能需要数十秒。
    """
    try:
        aid, title, err = await _resolve_article(ctx, article_id, keyword)
        if err:
            err["action"] = "knowledge_card_generate"
            return err
        service = _new_service(ctx)
        result = await service.generate_knowledge_card(aid)
        if result is None:
            return {
                "success": False,
                "action": "knowledge_card_generate",
                "message": f"文档不存在（article_id={aid}）",
            }
        return {
            "success": True,
            "action": "knowledge_card_generate",
            "article_id": str(aid),
            "title": title,
            "card_version": result.card_version,
            "knowledge_card": result.knowledge_card,
            "message": result.message or "卡片生成成功",
        }
    except Exception as e:
        logger.exception("generate_knowledge_card failed")
        return {"success": False, "action": "knowledge_card_generate",
                "error": f"生成失败: {e}"}


async def generate_knowledge_ppt(
    ctx: RunContext[SafetyDeps],
    article_id: str = "",
    keyword: str = "",
    template: str = "training",
    style: str = "professional",
) -> dict[str, Any]:
    """为知识库文档生成培训 PPT（AI 大纲 + python-pptx 落盘；写操作）。

    Args:
        article_id: 文档 UUID（可选）
        keyword: 文档关键词（唯一命中即用）
        template: 模板 training（培训）/ briefing（汇报）/ audit（审核）
        style: 风格 professional / modern / minimal

    示例：帮我把这个文档做一份PPT。

    注意：此操作会调用 AI 并生成文件，需要用户确认后才执行；确认卡应复述
    文档标题与模板/风格；生成可能需要数十秒。download_url 为服务器相对路径。
    """
    try:
        aid, title, err = await _resolve_article(ctx, article_id, keyword)
        if err:
            err["action"] = "knowledge_ppt_generate"
            return err
        service = _new_service(ctx)
        result = await service.generate_ppt(aid, template=template, style=style)
        if result is None:
            return {
                "success": False,
                "action": "knowledge_ppt_generate",
                "message": f"文档不存在（article_id={aid}）",
            }
        ok = bool(result.download_url)
        return {
            "success": ok,
            "action": "knowledge_ppt_generate",
            "article_id": str(aid),
            "title": title,
            "download_url": result.download_url,
            "file_name": result.file_name,
            "page_count": result.page_count,
            "message": result.message or ("PPT 生成成功" if ok else "PPT 未生成"),
        }
    except Exception as e:
        logger.exception("generate_knowledge_ppt failed")
        return {"success": False, "action": "knowledge_ppt_generate",
                "error": f"生成失败: {e}"}


async def generate_knowledge_summary(
    ctx: RunContext[SafetyDeps],
    article_id: str = "",
    keyword: str = "",
) -> dict[str, Any]:
    """为知识库文档生成 AI 结构化摘要（150-300 字，回写文档；写操作）。

    Args:
        article_id: 文档 UUID（可选）
        keyword: 文档关键词（唯一命中即用）

    示例：给这篇规定生成摘要。

    注意：此操作会调用 AI 并回写文档 summary 字段，需要用户确认后才执行；
    确认卡应复述文档标题。
    """
    try:
        aid, title, err = await _resolve_article(ctx, article_id, keyword)
        if err:
            err["action"] = "knowledge_summary_generate"
            return err
        service = _new_service(ctx)
        result = await service.generate_summary(aid)
        if result is None:
            return {
                "success": False,
                "action": "knowledge_summary_generate",
                "message": f"文档不存在（article_id={aid}）",
            }
        ok = bool(result.summary)
        return {
            "success": ok,
            "action": "knowledge_summary_generate",
            "article_id": str(aid),
            "title": title,
            "summary": result.summary,
            "message": result.message or ("摘要生成成功" if ok else "摘要未生成"),
        }
    except Exception as e:
        logger.exception("generate_knowledge_summary failed")
        return {"success": False, "action": "knowledge_summary_generate",
                "error": f"生成失败: {e}"}
