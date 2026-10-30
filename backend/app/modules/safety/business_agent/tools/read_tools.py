"""只读工具：查隐患 / 知识库检索。

每个工具的 docstring 即发给模型的功能描述，需保持准确、有参数示例。
所有工具通过 ``ctx.deps.db`` 调用已有 service，**不重写任何业务逻辑**。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.knowledge.query_service import run_knowledge_chat
from app.modules.safety.knowledge.web_search import WebSearchService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.modules.safety.models import FireAlarmRecord

# ── 整改状态 → Bitable 中文标签（与多维表格"整改状态"字段选项一致，仅两个值）──
# 多维表格"整改状态"字段仅有两个选项：已关闭 / 未关闭
_RECTIFICATION_STATUS_LABEL: dict[str, str] = {
    "closed": "已关闭",
    "no_rectification_needed": "已关闭",
    "level3_approved": "已关闭",
}


def _to_display_status(rectification_status: str) -> str:
    """将整改状态转为 Bitable 多维表格的中文标签。
    多维表格仅两个选项：已关闭 / 未关闭。closed 相关映射为「已关闭」，其余为「未关闭」。
    """
    if rectification_status in _RECTIFICATION_STATUS_LABEL:
        return _RECTIFICATION_STATUS_LABEL[rectification_status]
    return "未关闭"


# ── 隐患查询 ────────────────────────────────────────────────────


async def query_hazards(
    ctx: RunContext[SafetyDeps],
    department: str = "",
    status: str = "",
    rectification_status: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
    source: str = "",
) -> dict[str, Any]:
    """查询隐患记录列表（默认公司内部登记表；可切换/合并管委会外审来源）。

    数据源：**直读飞书多维表格**——内部隐患走「隐患登记表」，external 走
    「管委会检查缺陷项汇总表」（两张表无交集）。

    可按部门、隐患状态、整改状态、关键词、日期范围等条件筛选。

    Args:
        department: 部门名称（如"生产部"，需与多维表格「整改责任人.部门」选项一致）
        status: 隐患状态（"open"/"closed"）
        rectification_status: 整改状态（"pending"未关闭/"in_progress"整改中/"closed"已关闭）
        keyword: 搜索关键词（匹配隐患描述或隐患编号）
        date_from: 起始日期 ISO（按检查日期）
        date_to: 截止日期 ISO（按检查日期）
        limit: 返回条数上限（默认20）
        source: 数据来源——空/internal=公司内部隐患登记表（默认）/
            external=管委会检查外审隐患 / all=两表合并（items 带 source 标记）
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    department = department or None
    status = status or None
    rectification_status = rectification_status or None
    keyword = keyword or None
    date_from = date_from or None
    date_to = date_to or None
    src = (source or "internal").strip().lower()
    if src not in ("internal", "external", "all"):
        return {
            "success": False,
            "error": f"未知 source={source!r}，可选：internal / external / all",
        }

    async def _internal_items() -> tuple[list[dict[str, Any]], int]:
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient
        from app.modules.safety.service.hazard_direct import bitable_repo

        views, total = await bitable_repo.query_hazards(
            SafetyBitableClient(),
            department=department,
            status=status,
            rectification_status=rectification_status,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        items = [
            {
                "id": v.record_id,
                "source": "internal",
                "hazard_no": v.hazard_no,
                "department": v.department,
                "description": v.description,
                "status": v.status,
                "rectification_status": v.rectification_status,
                "display_status": _to_display_status(v.rectification_status),
                "discovered_at": (
                    v.discovered_at.isoformat() if v.discovered_at else None
                ),
                "rectification_responsible_person_name": (
                    v.rectification_responsible_person_name
                ),
            }
            for v in views
        ]
        return items, total

    async def _external_items() -> tuple[list[dict[str, Any]], int, str | None]:
        """外审缺陷项 → hazard 风格 items；未接入返回 (空, 0, 提示)。

        过滤映射：status/rectification_status=closed→已关闭行、其余值→未关闭行；
        date_from/date_to 按检查日期 checked_at（含当日）；截断同 limit。
        过滤实现复用 external_audit.filter_views（与报表导出同口径）。"""
        from app.modules.safety.service.hazard_direct.external_audit import (
            fetch_external_audit,
            filter_views,
        )

        views = await fetch_external_audit()
        if views is None:
            return [], 0, "管委会外审隐患表未接入"
        want_closed: bool | None = None
        if rectification_status or status:
            want_closed = (rectification_status or status) == "closed"
        rows = filter_views(
            views,
            department=department,
            closed=want_closed,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
        )[:limit]
        items = [
            {
                "id": v.record_id,
                "source": "external",
                "seq": v.seq,
                "departments": v.departments,
                "description": v.description,
                "plan": v.plan,
                "closed": v.closed,
                "in_progress": v.in_progress,
                "display_status": "已关闭" if v.closed else "未关闭",
                "checked_at": (
                    v.checked_at.isoformat() if v.checked_at else None
                ),
                "target_date": (
                    v.target_date.isoformat() if v.target_date else None
                ),
                "responsible_names": [name for name, _ in v.responsible],
            }
            for v in rows
        ]
        return items, len(items), None

    try:
        if src == "external":
            items, total, note = await _external_items()
            return {
                "items": items, "total": total,
                "source": "external_audit",
                **({"not_connected": note} if note else {}),
            }
        if src == "all":
            int_items, int_total = await _internal_items()
            ext_items, ext_total, note = await _external_items()
            return {
                "items": int_items + ext_items,
                "total": int_total + ext_total,
                "source": "bitable",
                "internal_total": int_total,
                "external_total": ext_total,
                **({"not_connected": note} if note else {}),
            }
        items, total = await _internal_items()
        return {"items": items, "total": total, "source": "bitable"}
    except Exception as e:
        logger.exception("query_hazards failed")
        return {"success": False, "error": f"查询失败: {e}"}


# ── 隐患统计 ────────────────────────────────────────────────────


async def query_hazard_stats(
    ctx: RunContext[SafetyDeps],
    date_from: str = "",
    date_to: str = "",
    department: str = "",
) -> dict[str, Any]:
    """获取隐患统计精确计数（直读飞书「隐患登记表」多维表格）。

    统计类问题（"本月多少条""各部门分布""整改完成率"）必须优先用本工具，
    禁止逐条数后估算、禁止"约/大约"等模糊词。状态仅两个值：已关闭 / 未关闭。

    Args:
        date_from: 起始日期 ISO（如 "2026-07-01"，按检查日期）
        date_to: 截止日期 ISO（如 "2026-07-31"）
        department: 部门（如"生产部"，不传统计全部）
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    date_from = date_from or None
    date_to = date_to or None
    department = department or None
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct import bitable_repo

    stats = await bitable_repo.count_hazards(
        SafetyBitableClient(),
        department=department,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "total": stats["total"],
        "closed": stats["closed"],
        "unclosed": stats["unclosed"],
        "abnormal_records": stats["abnormal_records"],
        "status_labels": {
            "closed": "已关闭",
            "unclosed": "未关闭",
            "abnormal_records": "异常记录",
        },
        "source": "bitable",
    }


# ── 检查记录查询 ────────────────────────────────────────────────


# ── 知识库检索（包装现有 RAG）───────────────────────────────────


# P2-10：RAG snippet 可能含整段文档 HTML（表格倒灌），渲染观感差；后端统一清洗
_HTML_TAG_RE = None  # 惰性编译（避免 import 期正则开销）


def _clean_snippet(text: Any, limit: int = 120) -> str:
    """snippet 清洗：strip HTML 标签 → 压空白 → 截断 ~120 字。"""
    global _HTML_TAG_RE
    import re

    if _HTML_TAG_RE is None:
        _HTML_TAG_RE = re.compile(r"<[^>]{1,200}>")
    cleaned = _HTML_TAG_RE.sub("", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _serialize_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确保 sources 中的值均为 JSON 可序列化类型（snippet 顺带清洗截断）。"""
    clean: list[dict[str, Any]] = []
    for s in sources:
        clean.append({
            "doc_title": str(s.get("doc_title", "")),
            "article_ref": str(s.get("article_ref", "")),
            "chunk_text": _clean_snippet(s.get("chunk_text", "")),
            "doc_category": str(s.get("doc_category", "")),
            "feishu_url": str(s.get("feishu_url", "")),
        })
    return clean


async def knowledge_search(
    ctx: RunContext[SafetyDeps],
    query: str,
) -> dict[str, Any]:
    """搜索安全法规、标准和管理制度知识库（仅内部知识库，不联网）。

    当内部知识库检索不到相关结果时，answer 中会说明未找到，
    同时 kb_empty 为 true。此时你应主动询问用户是否需要使用互联网搜索，
    并明确告知注意事项。

    Args:
        query: 用户的自然语言查询（如"防爆电气安装标准"）

    Returns:
        dict: {"answer": "...", "kb_empty": bool, "sources": [...]}
        - answer: AI 生成的带引用回答（含内联 [N] 标注）
        - kb_empty: True 表示知识库中完全未找到相关法规条款
        - sources: 法规来源列表（含 doc_title / feishu_url，供卡片构建器生成参考法规栏）

    ⚠️ 引用编号规则（转述 answer 时严格遵守）：
    - answer 中的 [N] 与 sources 数组一一对应（[1]=sources[0]），系统末尾的
      参考法规栏按同一编号渲染。转述/改写 answer 时必须原样保留 [N]，
      不得重新编号、不得增删。
    - 只允许在 sources 内的文档名旁保留 [N]；条款正文中提及的其他标准
      （如规范性引用清单里列出的 SH/T、GB/T 编号）不是 sources 文档，
      严禁给它们添加 [N]。
    - 禁止自行生成「参考法规」列表——系统会依据 sources 自动附加。
    """
    user_id = ctx.deps.person.user_id if ctx.deps.person else None
    answer, sources = await run_knowledge_chat(
        query=query, db=ctx.deps.db, user_id=user_id,
        enable_web_search=False,
    )
    # 兜底移除 RAG AI 可能生成的参考法规列表区块
    # 方案：找到最后一个 "参考法规" 出现的位置，如果它前面紧邻 --- 分隔符则截断
    ref_pos = answer.rfind("参考法规")
    if ref_pos > 0:
        # 向前查找最近的 \n---\n
        before = answer[:ref_pos]
        sep_pos = before.rfind("\n---")
        if sep_pos > 0 and ref_pos - sep_pos < 300:
            answer = answer[:sep_pos].rstrip()
            logger.debug("Stripped reference section at position %d", sep_pos)
    # 通过 answer 文本判断知识库是否无结果（比 sources 长度更准确）
    kb_empty = any(
        phrase in answer
        for phrase in (
            "未找到相关法规条款",
            "未检索到",
            "知识库中暂无",
            "知识库中未收录",
            "未查询到相关",
        )
    )
    # 部分命中但核心内容缺失：answer 中"未找到"后紧跟"不过/但/然而"等转折词，
    # 说明 KB 只有间接引用而无用户要的实质性内容，应告知用户并询问是否联网搜索。
    if not kb_empty:
        unfound_idx = answer.find("未找到")
        if unfound_idx >= 0:
            after = answer[unfound_idx:unfound_idx + 200]
            if any(w in after for w in ("不过", "但", "然而", "但是", "可参考", "现有法规", "相关规定")):
                kb_empty = True
    return {"answer": answer, "kb_empty": kb_empty, "sources": _serialize_sources(sources)}


# ── 互联网搜索（用户主动触发）──────────────────────────────────


async def web_search(
    ctx: RunContext[SafetyDeps],
    query: str,
) -> dict[str, Any]:
    """互联网搜索安全法规信息（严格受限的工具）。

    ⚠️ 仅当 knowledge_search 返回 kb_empty=true、用户明确同意联网、且已向用户
    展示风险提示（信息可能过时/不权威、AI 可能有幻觉、需自行经官方渠道核实）
    后才可调用；否则一律不调用。

    Args:
        query: 要在互联网上搜索的问题描述
    """
    web_service = WebSearchService()
    results = await web_service.search(query, num_results=5)

    if not results:
        return {
            "answer": "互联网搜索也未找到相关信息。建议：\n"
                      "1. 尝试使用不同的关键词重新搜索\n"
                      "2. 联系安全管理部门获取最新法规文本\n"
                      "3. 访问全国标准信息公共服务平台（std.samr.gov.cn）查询",
            "sources": [],
        }

    # 构建信息源列表（URL 供用户核实）
    sources = []
    for i, r in enumerate(results, 1):
        sources.append({
            "index": i,
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet[:150],
            "source_name": r.source_name,
        })

    # 构建用户消息中的上下文（注入 AI 生成回答）
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    with ai_audit_scope(scenario="knowledge_chat", channel="web"):
        ai = create_ai_service("text")
        context = WebSearchService.build_prompt_context(results)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个安全生产法规知识库助手。以下信息来自互联网搜索，"
                    "可能不是最新官方版本，请谨慎参考。\n\n"
                    "回答规则：\n"
                    "1. 基于提供的搜索结果回答，每引用一条信息标注编号 [N]\n"
                    "2. 回答末尾附上信息来源列表，每项格式：\n"
                    "   [N] 标题 — 来源网址\n"
                    "3. 回答开头必须声明：\n"
                    "   ⚠️ 以下信息来自互联网搜索，仅供参考，"
                    "不构成正式法规解释或合规建议。请通过官方渠道核实。\n"
                ),
            },
            {
                "role": "user",
                "content": f"{context}\n\n---\n\n## 问题\n\n{query}",
            },
        ]
        try:
            answer = await ai.chat(
                messages=messages,
                response_format="text",
                temperature=0.3,
                max_tokens=4096,
            )
        except Exception:
            answer = (
                f"AI 服务暂时不可用。以下是互联网搜索到的原始信息：\n\n"
                f"{context}"
            )
        finally:
            await ai.close()

    return {"answer": answer, "sources": sources}


async def query_latest_regulations(
    ctx: RunContext[SafetyDeps],
    view: str = "crawl",
    limit: int | None = None,
    days: int = 30,
    impact_level: str = "",
    business_domain: str = "",
) -> dict[str, Any]:
    """查询最新法规标准动态（view 区分爬取/收录两个视角）。

    Args:
        view: crawl=爬取视角（最近抓取的法规标准更新，支持按影响等级/业务领域筛选）/
            ingested=收录管线视角（最新收录，含 AI 判定摘要与修订标记，limit 上限 20）
        limit: 返回条数上限（缺省：crawl=10 / ingested=5，最大 20）
        days: 查询最近 N 天（默认 30，仅 view=crawl）
        impact_level: 影响等级筛选：高 / 中 / 低（空=全部，仅 view=crawl）
        business_domain: 业务领域筛选：安全生产 / 职业健康 / 环保 / 消防 / 危化品 / 特种设备
            （空=全部，仅 view=crawl）

    示例：最近 30 天有哪些高影响等级的法规更新；最新收录了哪些法规。
    """
    if view == "crawl":
        return await _query_regulations_crawl_impl(
            ctx, limit=10 if limit is None else limit, days=days,
            impact_level=impact_level, business_domain=business_domain,
        )
    if view == "ingested":
        return await _query_regulations_ingested_impl(
            ctx, limit=5 if limit is None else limit,
        )
    return {"error": f"未知 view={view!r}，可选：crawl / ingested"}


async def _query_regulations_crawl_impl(
    ctx: RunContext[SafetyDeps],
    limit: int = 10,
    days: int = 30,
    impact_level: str = "",
    business_domain: str = "",
) -> dict[str, Any]:
    """爬取视角：最近抓取的安全法规标准更新（合并前 query_latest_regulations 本体）。"""
    # 直读分支（批次二-4）：DIRECT 开启时走两表（安全/环保法规标准）Bitable 直读，
    # 语义忠实复刻 legacy（.scratch/knowledge-direct/spec.md D4/D5）；关=逐行 legacy。
    from app.modules.safety.service.knowledge_direct import config as kd_config

    if kd_config.direct_enabled():
        from app.modules.safety.service.knowledge_direct import query as kd_query
        from app.modules.safety.service.knowledge_direct import reader as kd_reader

        views = await kd_reader.open_reader().fetch_all()
        return kd_query.latest_regulations(
            views, limit=limit, days=days,
            impact_level=impact_level, business_domain=business_domain,
        )

    from datetime import date, timedelta

    from sqlalchemy import select

    from app.modules.safety.models import SafetyKnowledgeArticle

    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(SafetyKnowledgeArticle)
        .where(
            SafetyKnowledgeArticle.is_deleted.is_(False),
            SafetyKnowledgeArticle.created_at >= cutoff,
        )
        .order_by(SafetyKnowledgeArticle.created_at.desc())
        .limit(limit)
    )
    result = await ctx.deps.db.execute(stmt)
    articles = result.scalars().all()

    items = []
    for a in articles:
        # 客户端的筛选（impact_level 存在 notes 中，business_domain 影响 category）
        notes = a.notes or ""
        item_level = ""
        if "影响等级: 高" in notes:
            item_level = "高"
        elif "影响等级: 中" in notes:
            item_level = "中"
        elif "影响等级: 低" in notes:
            item_level = "低"

        if impact_level and item_level != impact_level:
            continue
        if business_domain and business_domain not in (a.category or ""):
            continue

        items.append({
            "id": str(a.id),
            "article_no": a.article_no,
            "title": a.title,
            "category": a.category,
            "impact_level": item_level or None,
            "publish_date": a.publish_date.isoformat() if a.publish_date else None,
            "status": a.status,
            "source": a.source,
        })
    return {"items": items, "total": len(items)}


# ── AI 调用审计查询 ──────────────────────────────────────────────


async def query_ai_audits(
    ctx: RunContext[SafetyDeps],
    scenario: str | None = None,
    status: str | None = None,
    days: int = 7,
    limit: int = 10,
) -> dict[str, Any]:
    """查询 AI 调用审计记录（仅创建者可用）。

    可回答"昨天整改初审失败的调用有哪些""这周 AI 花了多少 token"等问题。
    返回每次 AI 调用的场景、关联业务对象、模型、token 用量、耗时、状态与错误信息。

    Args:
        scenario: 场景过滤，可选值：hazard_identification（隐患识别）/
            rectification_review（整改初审）/ agent_chat（助手对话）/
            knowledge_chat（知识库问答）/ graph_build（图谱构建）
        status: 调用状态（"success" / "failed"），如只看失败的调用传 "failed"
        days: 查询最近几天（默认 7）
        limit: 返回条数上限（默认 10）
    """
    from datetime import timedelta

    from app.modules.safety.ai_audit.store import get_stats, list_audits
    from app.modules.safety.business_agent.permissions import (
        TOOL_QUERY_AI_AUDITS,
    )
    from app.modules.safety.business_agent.permissions import (
        check as perm_check,
    )

    # 硬护栏：只读工具不走 resume 权限校验，审计数据仅 creator 可查，
    # 必须在工具执行层自行强制（deny-by-default）。
    if not perm_check(ctx.deps.role, TOOL_QUERY_AI_AUDITS):
        return {
            "error": "权限不足：AI 调用审计仅创建者（creator）可查询。",
            "items": [],
            "total": 0,
        }

    date_from = datetime.now().astimezone() - timedelta(days=days)
    rows, total = await list_audits(
        ctx.deps.db,
        scenario=scenario,
        status=status,
        date_from=date_from,
        page=1,
        page_size=limit,
    )
    items = [
        {
            "id": str(r.id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "scenario": r.scenario,
            "resource_type": r.resource_type,
            "resource_id": str(r.resource_id) if r.resource_id else None,
            "user_name": r.user_name,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "latency_ms": r.latency_ms,
            "status": r.status,
            "error": (r.error or "")[:200] or None,
            "degradation_level": r.degradation_level,
        }
        for r in rows
    ]
    stats = await get_stats(ctx.deps.db, days=days)
    return {"items": items, "total": total, "stats": stats}


# ── 应急演练查询 ──────────────────────────────────────────────────


async def _query_drill_plans_impl(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    status: str | None = None,
    drill_type: str | None = None,
    keyword: str | None = None,
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查询应急演练计划（计划阶段：尚未执行的演练记录）。

    参数：
    - department: 部门筛选（如"设备动力部"）
    - status: 复核状态筛选（已完成/未完成）
    - drill_type: 演练类型（应急疏散演练/现场岗位处置/专项应急演练/综合应急演练/消防器材培训）
    - keyword: 演练内容关键词搜索
    - date_from/date_to: 日期区间（ISO，按计划时间过滤，含两端，可选）
    - limit: 返回条数上限，默认 20
    """
    from app.modules.safety.service.emergency_drill import EmergencyDrillService

    items, total = await EmergencyDrillService(ctx.deps.db).list_records(
        skip=0, limit=limit, department=department, drill_type=drill_type,
        status=status, keyword=keyword, stage="plan",
        date_from=date_from, date_to=date_to,
    )
    return {
        "items": [
            {
                "id": str(r.id), "drill_content": r.drill_content,
                "drill_type": r.drill_type, "department": r.department,
                "organizer": r.organizer, "participants": r.participants,
                "plan_time": r.plan_time, "plan_time_ref": str(r.plan_time_ref) if r.plan_time_ref else None,
                "duration": r.duration, "notes": r.notes,
            }
            for r in items
        ],
        "total": total,
    }


async def _query_drill_records_impl(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    status: str | None = None,
    drill_type: str | None = None,
    keyword: str | None = None,
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查询应急演练记录（已执行的演练记录，含待复核与已复核的）。

    参数：
    - department: 部门筛选
    - status: 复核状态筛选（已完成/未完成）
    - drill_type: 演练类型
    - keyword: 演练内容关键词搜索
    - date_from/date_to: 日期区间（ISO，按实施时间过滤，含两端，可选）
    - limit: 返回条数上限，默认 20
    """
    from app.modules.safety.service.emergency_drill import EmergencyDrillService

    items, total = await EmergencyDrillService(ctx.deps.db).list_records(
        skip=0, limit=limit, department=department, drill_type=drill_type,
        status=status, keyword=keyword, stage="execution",
        date_from=date_from, date_to=date_to,
    )
    return {
        "items": [
            {
                "id": str(r.id), "drill_content": r.drill_content,
                "drill_type": r.drill_type, "department": r.department,
                "execution_time": str(r.execution_time) if r.execution_time else None,
                "issues": r.issues, "status": r.status,
                "rectification_person": r.rectification_person,
                "confirmer": r.confirmer,
            }
            for r in items
        ],
        "total": total,
    }


async def query_drills(
    ctx: RunContext[SafetyDeps],
    kind: str = "plans",
    department: str = "",
    status: str = "",
    drill_type: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """查询应急演练计划或实施记录（kind 区分两类）。

    Args:
        kind: plans=演练计划（计划阶段、尚未执行）/ records=实施记录（已执行，
            含待复核与已复核，含执行时间/发现问题/整改人/复核人）
        department: 部门筛选（如"设备动力部"）
        status: 复核状态筛选（已完成/未完成）
        drill_type: 演练类型（应急疏散演练/现场岗位处置/专项应急演练/综合应急演练/消防器材培训）
        keyword: 演练内容关键词搜索
        date_from: 起始日期（ISO，如 2026-10-01；plans 按计划时间、records 按
            实施时间过滤，可选）
        date_to: 结束日期（ISO，含当日，可选）
        limit: 返回条数上限（默认20）

    示例：本月执行了多少次演练；查生产部今年的演练计划；上月有哪些记录未复核。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    from datetime import date as _date

    department = department or None
    status = status or None
    drill_type = drill_type or None
    keyword = keyword or None
    kw = {
        "department": department, "status": status, "drill_type": drill_type,
        "keyword": keyword,
        "date_from": _date.fromisoformat(date_from) if date_from else None,
        "date_to": _date.fromisoformat(date_to) if date_to else None,
        "limit": 20 if limit is None else limit,
    }
    if kind == "plans":
        return await _query_drill_plans_impl(ctx, **kw)
    if kind == "records":
        return await _query_drill_records_impl(ctx, **kw)
    return {"error": f"未知 kind={kind!r}，可选：plans / records"}


# ═══════════════════════════════════════════════════════════════════
# MSDS 智能提取入库 — 只读工具
# ═══════════════════════════════════════════════════════════════════


async def _query_msds_documents_impl(
    ctx: RunContext[SafetyDeps],
    name: str | None = None,
    cas_no: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查询 MSDS 化学品安全数据台账（标准化收录结果）。

    参数：
    - name: 物质名称模糊搜索（如"异丙醇"）
    - cas_no: CAS号搜索（如"67-63-0"）
    - limit: 返回条数上限，默认 20

    示例：查一下异丙醇的 MSDS；搜索 CAS 67-63-0 的化学品信息。
    """
    # 直读分支（批次二-5）：DIRECT 开启时走 MSDS 收录台账表 Bitable 直读，
    # 语义忠实复刻 legacy（.scratch/msds-direct/spec.md D3/D5）；关=逐行 legacy。
    from app.modules.safety.service.msds_direct import config as md_config

    if md_config.direct_enabled():
        from app.modules.safety.service.msds_direct import query as md_query
        from app.modules.safety.service.msds_direct import reader as md_reader

        views = await md_reader.open_reader().fetch_all()
        items, total = md_query.msds_documents(
            views, name=name, cas_no=cas_no, limit=limit,
        )
        return {"items": items, "total": total}

    from app.modules.safety.service.msds import MsdsService

    items, total = await MsdsService(ctx.deps.db).list_documents(
        skip=0, limit=limit, name=name, cas_no=cas_no,
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "cas_no": r.cas_no,
                "molecular_formula": r.molecular_formula,
                "un_no": r.un_no,
                "hazard_statement": r.hazard_statement,
                "appearance": r.appearance,
                "flash_point": r.flash_point,
                "relative_density": r.relative_density,
                "pc_twa": r.pc_twa,
                "health_hazard": r.health_hazard,
                "first_aid": r.first_aid,
                "review_status": r.review_status,
                "archive_status": r.archive_status,
            }
            for r in items
        ],
        "total": total,
    }


async def _query_msds_collections_impl(
    ctx: RunContext[SafetyDeps],
    parse_status: str | None = None,
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查询供应商 MSDS 资料采集记录（解析状态跟踪）。

    参数：
    - parse_status: 解析状态筛选（pending=待解析 / parsed=已解析 / failed=解析失败）
    - date_from/date_to: 日期区间（ISO，按采集时间过滤，含两端，可选）
    - limit: 返回条数上限，默认 20

    示例：本月采集了多少份供应商资料；有哪些 MSDS 解析失败的记录。
    """
    from app.modules.safety.service.msds import MsdsService

    items, total = await MsdsService(ctx.deps.db).list_collections(
        skip=0, limit=limit, parse_status=parse_status,
        date_from=date_from, date_to=date_to,
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "feishu_record_id": r.feishu_record_id,
                "parse_status": r.parse_status,
                "parse_error": r.parse_error,
                "entry_count": len(r.parse_result) if r.parse_result else 0,
                "registry_ids": r.msds_table_record_ids or [],
            }
            for r in items
        ],
        "total": total,
    }


async def query_msds(
    ctx: RunContext[SafetyDeps],
    kind: str = "documents",
    name: str = "",
    cas_no: str = "",
    parse_status: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """查询 MSDS 化学品安全数据台账或供应商资料采集记录（kind 区分两类）。

    Args:
        kind: documents=MSDS 标准化台账（危险性说明/理化特性/职业接触限值/
            健康危害/急救措施等）/ collections=供应商 MSDS 资料采集记录
            （解析状态跟踪：pending=待解析 / parsed=已解析 / failed=解析失败）
        name: 物质名称模糊搜索（如"异丙醇"，kind=documents 时有效）
        cas_no: CAS号搜索（如"67-63-0"，kind=documents 时有效）
        parse_status: 解析状态筛选（kind=collections 时有效）
        date_from: 起始日期（ISO，如 2026-10-01；按采集时间过滤，仅
            kind=collections 时有效，可选）
        date_to: 结束日期（ISO，含当日，可选，仅 kind=collections 时有效）
        limit: 返回条数上限（默认 20）

    示例：本月采集了多少份供应商 MSDS 资料；查异丙醇的 MSDS；哪些采集记录解析失败。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    from datetime import date as _date

    name = name or None
    cas_no = cas_no or None
    parse_status = parse_status or None
    kw = {"limit": 20 if limit is None else limit}
    if kind == "documents":
        return await _query_msds_documents_impl(ctx, name=name, cas_no=cas_no, **kw)
    if kind == "collections":
        return await _query_msds_collections_impl(
            ctx, parse_status=parse_status,
            date_from=_date.fromisoformat(date_from) if date_from else None,
            date_to=_date.fromisoformat(date_to) if date_to else None,
            **kw,
        )
    return {"error": f"未知 kind={kind!r}，可选：documents / collections"}


# ═══════════════════════════════════════════════════════════════════
# 职业健康管理 — 只读工具
# ═══════════════════════════════════════════════════════════════════


def _oh_field(row: Any, key: str, default: Any = None) -> Any:
    """OH 行统一取值：直读行（OhRowView）mapped 条件写键，缺键不得抛
    AttributeError 崩工具（验收 #4：无体检号行 query_oh_exams 直接崩）；
    镜像 ORM 行走 getattr。缺键/无属性 → default。
    """
    mapped = getattr(row, "mapped", None)
    if isinstance(mapped, dict):
        return mapped.get(key, default)
    return getattr(row, key, default)


def _oh_date(value: Any) -> str | None:
    return value.isoformat() if value else None


async def query_oh_persons(
    ctx: RunContext[SafetyDeps],
    department: str = "",
    position: str = "",
    hazard_exposure: str = "",
    last_exam_conclusion: str = "",
    keyword: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """查询人员职业健康台账（一人一条，含接害与最后体检状态）。

    Args:
        department: 部门（如"生产部"）
        position: 岗位（如"合成操作工"）
        hazard_exposure: 是否接触危害（"true"/"false"）
        last_exam_conclusion: 最后体检结论（normal/abnormal_other/contraindicated/
            suspected_od/od_diagnosed/re_examination）
        keyword: 姓名/工号/身份证号
        limit: 条数上限（默认 20）

    示例：生产部有多少接触危害的员工；查张三的职业健康档案。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    department = department or None
    position = position or None
    hazard_exposure = hazard_exposure or None
    last_exam_conclusion = last_exam_conclusion or None
    keyword = keyword or None
    from app.modules.safety.service.oh_person import OhPersonService

    items, total = await OhPersonService(ctx.deps.db).get_persons(
        skip=0,
        limit=limit,
        department=department,
        position=position,
        hazard_exposure=hazard_exposure,
        last_exam_conclusion=last_exam_conclusion,
        keyword=keyword,
    )
    return {
        "items": [
            {
                "id": str(p.id),
                "name": _oh_field(p, "name"),
                "employee_no": _oh_field(p, "employee_no"),
                "department": _oh_field(p, "department"),
                "position": _oh_field(p, "position"),
                "gender": _oh_field(p, "gender"),
                "age": _oh_field(p, "age"),
                "work_status": _oh_field(p, "work_status"),
                "hazard_exposure_years": _oh_field(p, "hazard_exposure_years"),
                "hazard_factors": _oh_field(p, "hazard_factors") or [],
                "last_exam_at": _oh_date(_oh_field(p, "last_exam_at")),
                "last_exam_type": _oh_field(p, "last_exam_type"),
                "last_exam_conclusion": _oh_field(p, "last_exam_conclusion"),
            }
            for p in items
        ],
        "total": total,
    }


async def query_oh_exams(
    ctx: RunContext[SafetyDeps],
    exam_type: str = "",
    ai_conclusion: str = "",
    ai_parse_status: str = "",
    department: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """查询职业健康体检记录（含 AI 智能解读、结论分类与适配判定）。

    统计某月体检数量（如"本月有多少人体检"）用 date_from/date_to 圈定区间看 total。

    Args:
        exam_type: 体检类型
        ai_conclusion: AI 结论（normal/abnormal/contraindicated 等）
        ai_parse_status: 解析状态（pending/parsed/failed）
        department: 部门
        keyword: 姓名/工号模糊匹配
        date_from: 起始日期（ISO，如 2026-10-01；按体检时间过滤，可选）
        date_to: 结束日期（ISO，含当日，如 2026-10-31，可选）
        limit: 条数上限（默认 20）

    示例：本月有多少人体检；查一下张三最近的体检记录；哪些体检结论为职业禁忌证。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    from datetime import date as _date

    exam_type = exam_type or None
    ai_conclusion = ai_conclusion or None
    ai_parse_status = ai_parse_status or None
    department = department or None
    keyword = keyword or None
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    items, total = await OhHealthExamService(ctx.deps.db).get_exams(
        skip=0,
        limit=limit,
        exam_type=exam_type,
        department=department,
        ai_conclusion=ai_conclusion,
        ai_parse_status=ai_parse_status,
        keyword=keyword,
        date_from=_date.fromisoformat(date_from) if date_from else None,
        date_to=_date.fromisoformat(date_to) if date_to else None,
    )
    return {
        "items": [
            {
                "id": str(e.id),
                "exam_no": _oh_field(e, "exam_no"),
                "employee_name": _oh_field(e, "employee_name"),
                "department": _oh_field(e, "department"),
                "position": _oh_field(e, "position"),
                "exam_type": _oh_field(e, "exam_type"),
                "exam_agency": _oh_field(e, "exam_agency"),
                "exam_date": _oh_date(_oh_field(e, "exam_date")),
                "hazard_factors": _oh_field(e, "hazard_factors") or [],
                "status": _oh_field(e, "status"),
                "ai_parse_status": _oh_field(e, "ai_parse_status"),
                "ai_conclusion": _oh_field(e, "ai_conclusion"),
                "override_conclusion": _oh_field(e, "override_conclusion"),
                "ai_fitness": _oh_field(e, "ai_fitness"),
                "ai_interpretation": _oh_field(e, "ai_interpretation"),
            }
            for e in items
        ],
        "total": total,
    }


async def _query_oh_positions_impl(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    hazard_factors_status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查询岗位危害因素台账（部门+岗位 → 接触危害因素标准名）。

    Args:
        department: 部门名称筛选（如"生产部"）
        hazard_factors_status: 危害因素登记状态（filled=已登记 / empty=未登记 / inferred=推断）
        limit: 返回条数上限（默认 20）

    Returns:
        dict: {"items": [{id, department, position, job_title, hazard_factors,
            hazard_factors_status}], "total": int}

    示例：查一下哪些岗位接触噪声；合成车间的岗位危害台账。
    """
    # 维持镜像（批次四-1 盘点结论，spec §0.1）：oh_positions 镜像表双源承重——
    # 除 Bitable 镜像行外还承载历史迁移手动行（source=manual、无
    # feishu_record_id、代码无创建路径），直读结构性丢失；直读链路已在
    # service/oh_direct/ 建成（验证/复评用），工具分支不接防呆。
    from app.modules.safety.service.oh_position import OhPositionService

    items, total = await OhPositionService(ctx.deps.db).get_positions(
        skip=0,
        limit=limit,
        department=department,
        hazard_factors_status=hazard_factors_status,
    )
    return {
        "items": [
            {
                "id": str(p.id),
                "department": p.department,
                "position": p.position,
                "job_title": p.job_title,
                "hazard_factors": p.hazard_factors or [],
                "hazard_factors_status": p.hazard_factors_status,
            }
            for p in items
        ],
        "total": total,
    }


async def _query_oh_hazard_factors_impl(
    ctx: RunContext[SafetyDeps],
    keyword: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """查询危害因素 PPE 映射字典（危害因素标准名 → 呼吸防护用品）。

    Args:
        keyword: 危害因素名称关键词（如"氨"、"粉尘"），不传返回全部
        limit: 返回条数上限（默认 50）

    Returns:
        dict: {"items": [{id, factor_name, ppe_respiratory}], "total": int}

    示例：氨的防护用品是什么；查一下有 PPE 配置的危害因素清单。
    """
    # 直读分支（批次四-1）：DIRECT 开启时走危害因素 PPE 表 Bitable 直读，语义
    # 忠实复刻 legacy 含「先 LIMIT 后 keyword 过滤」quirk（spec D5）；关=逐行
    # legacy。同批盘点结论：query_oh_positions 因镜像表双源承重维持镜像（不接
    # 直读分支），本域仅此一工具切换。
    from app.modules.safety.service.oh_direct import config as od_config

    if od_config.direct_enabled():
        from app.modules.safety.service.oh_direct import query as od_query
        from app.modules.safety.service.oh_direct import reader as od_reader

        views = await od_reader.open_reader().fetch_factors()
        items, total = od_query.oh_hazard_factors(
            views, keyword=keyword, limit=limit,
        )
        return {"items": items, "total": total}

    from app.modules.safety.service.oh_hazard_factor import OhHazardFactorService

    svc = OhHazardFactorService(ctx.deps.db)
    items, total = await svc.get_factors(skip=0, limit=limit)
    if keyword:
        kw = keyword.strip()
        items = [f for f in items if kw in (f.factor_name or "")]
    return {
        "items": [
            {
                "id": str(f.id),
                "factor_name": f.factor_name,
                "ppe_respiratory": f.ppe_respiratory,
            }
            for f in items
        ],
        "total": len(items),
    }


async def _query_oh_followups_impl(
    ctx: RunContext[SafetyDeps],
    status: str | None = None,
    category: str | None = None,
    person_id: str | None = None,
    due_order: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """查询职业健康异常随访记录（体检异常指标 → 复查/转诊闭环跟踪）。

    Args:
        status: 随访状态（open=待处置 / followed=已处置待闭环 / closed=已关闭 / expired=已逾期）
        category: 指标类别（lab=检验 / vision=视力 / hearing=听力 / physique=体格 / other=其他）
        person_id: 人员 ID（UUID 字符串），只看某人的随访
        due_order: 是否按建议处置日期排序（True=到期优先，默认 False）
        limit: 返回条数上限（默认 20）

    Returns:
        dict: {"items": [{id, person_name, indicator_name, indicator_value,
            abnormal_level, category, followup_type, followup_date, status, ...}], "total": int}

    示例：查一下有哪些待处置的异常随访；张三的听力异常随访处理得怎么样了。
    """
    import uuid

    from app.modules.safety.service.oh_followup import OhFollowupService

    pid = uuid.UUID(person_id) if person_id else None
    items, total = await OhFollowupService(ctx.deps.db).get_followups(
        skip=0,
        limit=limit,
        status=status,
        category=category,
        person_id=pid,
        due_order=due_order,
    )
    return {
        "items": [
            {
                "id": str(f.id),
                "exam_id": str(f.exam_id) if f.exam_id else None,
                "person_id": str(f.person_id) if f.person_id else None,
                "person_name": f.person_name,
                "indicator_name": f.indicator_name,
                "indicator_value": f.indicator_value,
                "reference_range": f.reference_range,
                "abnormal_level": f.abnormal_level,
                "category": f.category,
                "followup_type": f.followup_type,
                "followup_date": f.followup_date.isoformat() if f.followup_date else None,
                "status": f.status,
                "action_taken": f.action_taken,
                "responsible": f.responsible,
                "closed_at": f.closed_at.isoformat() if f.closed_at else None,
                "source": f.source,
            }
            for f in items
        ],
        "total": total,
    }


async def _query_oh_applications_impl(
    ctx: RunContext[SafetyDeps],
    status: str | None = None,
    transfer_type: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """查询转岗/离岗体检申请记录（含危害差异分析结果）。

    Args:
        status: 申请状态（已通过/审批中/已拒绝/已取消/已终止/已撤回/已删除）
        transfer_type: 申请类型（transfer=转岗 / post_employment=离岗）
        keyword: 搜索关键词（匹配申请编号、员工姓名、原部门、转入部门）
        limit: 返回条数上限（默认 20）

    Returns:
        dict: {"items": [{id, application_no, apply_status, transfer_type, employee_name,
            department, position, new_department, new_position, diff_analyze_status,
            needs_exam, exam_suggestion, ...}], "total": int}

    示例：查一下有哪些转岗申请需要体检；生产部最近的转岗申请分析结果。
    """
    from app.modules.safety.service.oh_transfer import OhTransferService

    items, total = await OhTransferService(ctx.deps.db).get_applications(
        skip=0,
        limit=limit,
        status=status,
        transfer_type=transfer_type,
        keyword=keyword,
    )
    return {
        "items": [
            {
                "id": str(a.id),
                "application_no": a.application_no,
                "apply_status": a.apply_status,
                "transfer_type": a.transfer_type,
                "exam_type": a.exam_type,
                "employee_name": a.employee_name,
                "department": a.department,
                "position": a.position,
                "new_department": a.new_department,
                "new_position": a.new_position,
                "transfer_date": a.transfer_date.isoformat() if a.transfer_date else None,
                "diff_analyze_status": a.diff_analyze_status,
                "needs_exam": a.needs_exam,
                "exam_suggestion": a.exam_suggestion,
                "diff_summary": a.diff_summary,
                "created_exam_id": str(a.created_exam_id) if a.created_exam_id else None,
            }
            for a in items
        ],
        "total": total,
    }


async def _query_oh_hazard_enums_impl(
    ctx: RunContext[SafetyDeps],
) -> dict[str, Any]:
    """查询危害因素标准字典（42 项，GBZ 188 相关标准名清单）。

    危害因素标准名全量清单，用于核对岗位/人员接触危害因素的规范性。
    不需要任何参数。

    Returns:
        dict: {"items": ["噪声", "氨", "高温", ...], "total": 42}

    示例：职业健康危害因素标准清单有哪些？
    """
    from app.modules.safety.service.oh_hazard_factor import OhHazardFactorService

    enums = await OhHazardFactorService(ctx.deps.db).get_enums()
    return {"items": list(enums), "total": len(enums)}


async def query_oh(
    ctx: RunContext[SafetyDeps],
    entity: str,
    department: str = "",
    hazard_factors_status: str = "",
    keyword: str = "",
    status: str = "",
    category: str = "",
    person_id: str = "",
    due_order: bool = False,
    transfer_type: str = "",
    detection_type: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """查询职业健康明细（entity 指定查什么；人员台账/体检记录见独立工具）。

    Args:
        entity: positions=岗位危害台账 / hazard_factors=PPE 映射字典 /
            followups=异常随访闭环 / applications=转岗离岗申请 /
            monitors=职业危害因素监测 /
            hazard_enums=危害因素标准字典（42 项，无其他参数）
        department: 部门（positions）
        hazard_factors_status: 登记状态 filled/empty/inferred（positions）
        keyword: 关键词（hazard_factors 按名称；applications 按编号/姓名/部门；
            monitors 按监测编号/场所/位置）
        status: followups: open/followed/closed/expired；applications: 已通过/审批中等
        category: 随访指标类别 lab/vision/hearing/physique/other（followups）
        person_id: 人员 ID（UUID，followups 只看某人）
        due_order: 到期优先排序（followups）
        transfer_type: transfer=转岗 / post_employment=离岗（applications）
        detection_type: 检测类型（monitors：regular=定期/commissioned=委托/
            evaluation=验收/accident=事故）
        limit: 条数上限（缺省 positions/followups/applications=20、hazard_factors=50）

    示例：哪些岗位接触噪声；待处置的异常随访；生产部最近的转岗申请；
    今年的职业危害因素监测做了哪些。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    department = department or None
    hazard_factors_status = hazard_factors_status or None
    keyword = keyword or None
    status = status or None
    category = category or None
    person_id = person_id or None
    transfer_type = transfer_type or None
    detection_type = detection_type or None
    if entity == "monitors":
        return await _query_oh_monitors_impl(
            ctx, status=status, detection_type=detection_type,
            keyword=keyword, limit=20 if limit is None else limit,
        )
    if entity == "positions":
        return await _query_oh_positions_impl(
            ctx, department=department,
            hazard_factors_status=hazard_factors_status,
            limit=20 if limit is None else limit,
        )
    if entity == "hazard_factors":
        return await _query_oh_hazard_factors_impl(
            ctx, keyword=keyword, limit=50 if limit is None else limit,
        )
    if entity == "followups":
        return await _query_oh_followups_impl(
            ctx, status=status, category=category, person_id=person_id,
            due_order=due_order, limit=20 if limit is None else limit,
        )
    if entity == "applications":
        return await _query_oh_applications_impl(
            ctx, status=status, transfer_type=transfer_type, keyword=keyword,
            limit=20 if limit is None else limit,
        )
    if entity == "hazard_enums":
        return await _query_oh_hazard_enums_impl(ctx)
    return {
        "error": (
            f"未知 entity={entity!r}，可选：positions / hazard_factors / "
            f"followups / applications / monitors / hazard_enums"
        )
    }


async def _query_oh_monitors_impl(
    ctx: RunContext[SafetyDeps],
    *,
    status: str | None,
    detection_type: str | None,
    keyword: str | None,
    limit: int,
) -> dict[str, Any]:
    """monitors=职业危害因素监测（本地库，agent-query-p1 新增）。"""
    from app.modules.safety.service.oh_hazard_monitor import OhHazardMonitorService

    rows, total = await OhHazardMonitorService(ctx.deps.db).get_monitors(
        skip=0,
        limit=min(max(limit, 1), 100),
        status=status,
        detection_type=detection_type,
        workplace=None,
        keyword=keyword,
    )
    items = [
        {
            "id": str(m.id),
            "monitor_no": m.monitor_no,
            "workplace": m.workplace,
            "location": m.location,
            "equipment_info": m.equipment_info,
            "detection_type": m.detection_type,
            "detection_date": (
                m.detection_date.isoformat() if m.detection_date else None
            ),
            "detection_agency": m.detection_agency,
            "status": m.status,
            "inspector_name": m.inspector_name,
            "detection_results": m.detection_results,
        }
        for m in rows
    ]
    return {"items": items, "total": total, "source": "db"}


# ═══════════════════════════════════════════════════════════════════
# 消防报警分析 — 只读工具
# ═══════════════════════════════════════════════════════════════════


def _to_dict(r: FireAlarmRecord) -> dict[str, Any]:
    """报警记录 → JSON 可序列化 dict（字段与 api/fire_alarm.py _serialize 一致）。"""
    return {
        "id": str(r.id),
        "feishu_record_id": r.feishu_record_id,
        "source": r.source,
        "alarm_time": r.alarm_time.isoformat() if r.alarm_time else None,
        "alarm_type": r.alarm_type,
        "department": r.department,
        "department_leader_name": r.department_leader_name,
        "building": r.building,
        "location": r.location,
        "alarm_nature": r.alarm_nature,
        "cause_category": r.cause_category,
        "cause_description": r.cause_description,
        "ai_dimension": r.ai_dimension,
        "ai_reason_analysis": r.ai_reason_analysis,
        "ai_rectification_direction": r.ai_rectification_direction,
        "ai_analyzed_at": r.ai_analyzed_at.isoformat() if r.ai_analyzed_at else None,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def query_fire_alarms(
    ctx: RunContext[SafetyDeps],
    date_from: str = "",
    date_to: str = "",
    department: str = "",
    alarm_type: str = "",
    alarm_nature: str = "",
    ai_dimension: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询消防报警记录（飞书「火灾报警信息」表直读，含 AI 维度分类与原因分析）。

    未给日期范围时默认最近 30 天；超过 31 天返回提示。items 中 id 为飞书记录 ID。

    Args:
        date_from / date_to: 起止日期（ISO）
        department: 报警部门
        alarm_type: 报警类型
        alarm_nature: 报警性质
        ai_dimension: AI 维度（process/operation/equipment/other）
        keyword: 报警部位/原因模糊匹配
        page / page_size: 页码/每页条数（默认 20）

    示例：查一下 8 月份生产部的消防报警记录；昨天有哪些工艺类报警。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    date_from = date_from or None
    date_to = date_to or None
    department = department or None
    alarm_type = alarm_type or None
    alarm_nature = alarm_nature or None
    ai_dimension = ai_dimension or None
    keyword = keyword or None
    from datetime import date as _date

    from app.modules.safety.service.fire_alarm.query import query_fire_alarms_direct

    try:
        return await query_fire_alarms_direct(
            date_from=_date.fromisoformat(date_from) if date_from else None,
            date_to=_date.fromisoformat(date_to) if date_to else None,
            department=department,
            alarm_type=alarm_type,
            alarm_nature=alarm_nature,
            ai_dimension=ai_dimension,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.exception("query_fire_alarms failed")
        return {"success": False, "error": f"查询失败: {e}"}


async def query_central_alarms(
    ctx: RunContext[SafetyDeps],
    date_from: str = "",
    date_to: str = "",
    workshop: str = "",
    line: str = "",
    post: str = "",
    ai_alarm_type: str = "",
    ai_dimension: str = "",
    ai_pattern: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询中控报警记录（含 AI 分析：报警类型/异常模式/维度/原因与整改方向）。

    Args:
        date_from / date_to: 起止日期（ISO）
        workshop: 车间（如 车间一/车间二/新罐区）
        line: 产线/区域（如 达托/达巴/替考）
        post: 岗位（如 乙醇纳滤/一次层析）
        ai_alarm_type: 报警类型（高液位/高温/误报等）
        ai_dimension: AI 维度（process/operation/equipment/other）
        ai_pattern: 异常模式（normal_transient/repeated/false_alarm/anomalous）
        keyword: 报警情况说明模糊匹配
        page / page_size: 页码（默认 1）/每页条数（默认 20）

    示例：查一下车间一最近的中控高液位报警；有哪些重复报警。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    date_from = date_from or None
    date_to = date_to or None
    workshop = workshop or None
    line = line or None
    post = post or None
    ai_alarm_type = ai_alarm_type or None
    ai_dimension = ai_dimension or None
    ai_pattern = ai_pattern or None
    keyword = keyword or None
    from datetime import date as _date

    from app.modules.safety.service.central_alarm import config as ca_config
    from app.modules.safety.service.central_alarm import query as ca_query
    from app.modules.safety.service.central_alarm.service import CentralAlarmService

    try:
        if ca_config.direct_enabled():
            result = await ca_query.query_central_alarms_direct(
                date_from=_date.fromisoformat(date_from) if date_from else None,
                date_to=_date.fromisoformat(date_to) if date_to else None,
                workshop=workshop,
                line=line,
                post=post,
                ai_alarm_type=ai_alarm_type,
                ai_dimension=ai_dimension,
                ai_pattern=ai_pattern,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
            return {
                "success": True,
                "items": [ca_query.serialize_view(v) for v in result.items],
                "page": page,
                "page_size": page_size,
                "total": result.total,
                "note": "直读模式：ai_* 字段不可用（AI 分析不落盘），窗口默认近 7 天",
            }
        service = CentralAlarmService(ctx.deps.db)
        items, total = await service.get_records(
            date_from=_date.fromisoformat(date_from) if date_from else None,
            date_to=_date.fromisoformat(date_to) if date_to else None,
            workshop=workshop,
            line=line,
            post=post,
            ai_alarm_type=ai_alarm_type,
            ai_dimension=ai_dimension,
            ai_pattern=ai_pattern,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return {
            "success": True,
            "items": [_to_central_dict(r) for r in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    except Exception as e:
        logger.exception("query_central_alarms failed")
        return {"success": False, "error": f"查询失败: {e}"}


def _to_central_dict(r: Any) -> dict[str, Any]:
    """CentralAlarmRecord → 可读 dict（供 Agent 工具返回）。"""
    from datetime import timedelta

    return {
        "id": str(r.id),
        "date": (r.alarm_date + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if r.alarm_date else None,
        "workshop": r.workshop,
        "line": r.line,
        "post": r.post,
        "alarm_description": r.alarm_description,
        "special_note": r.special_note,
        "ai_alarm_type": r.ai_alarm_type,
        "ai_pattern": r.ai_pattern,
        "ai_dimension": r.ai_dimension,
        "ai_reason_analysis": r.ai_reason_analysis,
        "ai_rectification_direction": r.ai_rectification_direction,
        "ai_analyzed_at": r.ai_analyzed_at.isoformat() if r.ai_analyzed_at else None,
    }


# ═══════════════════════════════════════════════════════════════════
# 相关方准入查询 — 只读工具
# ═══════════════════════════════════════════════════════════════════


async def query_contractor_admissions(
    ctx: RunContext[SafetyDeps],
    related_party_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    submit_status: str | None = None,
    ai_review_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询相关方准入记录。

    按相关方类型/日期区间/提交状态/AI审核状态/关键词查询准入审核记录，返回记录列表与统计。
    适用于：查看哪些承包商已通过准入审核、哪些材料待补充、准入进度跟踪。
    统计某月准入数量（如"本月有多少相关方准入"）用 date_from/date_to 圈定区间看 total。

    Args:
        related_party_type: 相关方类型筛选（承包商/合作类相关方/劳务派遣/其他相关方）
        date_from: 起始日期（ISO，如 2026-10-01；按记录创建日期=准入申请提交日，可选）
        date_to: 结束日期（ISO，含当日，如 2026-10-31，可选）
        submit_status: 提交状态（已完成/进行中/未开始）
        ai_review_status: AI审核状态（none/processing/completed/failed）
        keyword: 关键词（作业单位名称模糊匹配）
        page: 页码（从1开始）
        page_size: 每页条数

    Returns:
        {items: [...], total: N, page, page_size}
    """
    from datetime import date as _date

    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )

    items, total = await ContractorAdmissionService(ctx.deps.db).get_list(
        filters={
            "related_party_type": related_party_type,
            "submit_status": submit_status,
            "ai_review_status": ai_review_status,
            "keyword": keyword,
            "date_from": _date.fromisoformat(date_from) if date_from else None,
            "date_to": _date.fromisoformat(date_to) if date_to else None,
        },
        page=page,
        page_size=page_size,
    )
    return {
        "items": [
            {
                "id": str(i.id),
                "company_name": i.company_name,
                "related_party_type": i.related_party_type,
                "contact_person": i.contact_person,
                "liaison_user_name": i.liaison_user_name,
                "entry_date": i.entry_date.isoformat() if i.entry_date else None,
                "submit_status": i.submit_status,
                "ai_review_status": i.ai_review_status,
                "ai_overall_conclusion": (i.ai_review_result or {}).get(
                    "overall_conclusion"
                ),
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ═══════════════════════════════════════════════════════════════════
# 持证到期预警查询 — 只读工具
# ═══════════════════════════════════════════════════════════════════


async def query_cert_warnings(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    cert_category: str | None = None,
    status_level: str | None = None,
    days_within: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """查询人员持证到期预警明细。

    返回每个持证人员的当前节点（复审/第一次复审/第二次复审/换证）、截止日期、
    剩余天数、预警等级（6 档：normal/early_notice/to_schedule/key_warning/urgent/overdue）
    与建议措施。可按部门、证件类别（special_op=特种作业证 / guardian_a=监护人A证 /
    guardian_b=监护人B证）、预警状态、剩余天数范围筛选。

    Args:
        department: 部门名称（如"生产部"）
        cert_category: 证件类别（special_op / guardian_a / guardian_b）
        status_level: 预警等级（normal / early_notice / to_schedule /
            key_warning / urgent / overdue）
        days_within: 剩余天数 ≤ N（如 30 表示 30 天内到期或已逾期）
        limit: 返回条数上限（默认 50）

    Returns:
        dict: {"items": [{id, person_name, department, cert_category,
            current_node, deadline, remaining_days, status_level, suggestion, ...}],
            "total": int}

    示例：本月有哪些人证到期？查 overdue 和 urgent 两个等级的；生产部 30 天内到期的证。
    """
    from app.modules.safety.service.cert_direct import config as cert_direct_config

    if cert_direct_config.direct_enabled():
        from app.modules.safety.service.cert_direct.query import get_warnings_direct
        from app.modules.safety.service.cert_direct.reader import open_reader

        items, total = await get_warnings_direct(
            open_reader(),
            limit=limit,
            department=department,
            cert_category=cert_category,
            status_level=status_level,
            days_within=days_within,
        )
        return {
            "items": [i.model_dump(mode="json") for i in items],
            "total": total,
        }

    from app.modules.safety.service.cert_warning import CertWarningService

    items, total = await CertWarningService(ctx.deps.db).get_warnings(
        skip=0,
        limit=limit,
        department=department,
        cert_category=cert_category,
        status_level=status_level,
        days_within=days_within,
    )
    return {
        "items": [i.model_dump(mode="json") for i in items],
        "total": total,
    }


async def query_chemical_inventory(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    material_name: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """查询危化品库存台账（当前固定行）。

    返回每条化学品当前的部门、存放部位、物料名称、库存数量/单位、现场物料总量(T)、
    库存上限、危险性类别、风险标记、最后更新时间等。可按部门、物料名称（模糊）筛选。

    Args:
        department: 部门（仓储部/提炼一期/提炼二期/发酵一部/菌种中心/QC/环保/精制等）
        material_name: 物料名称，支持模糊匹配（如"乙醇"）
        limit: 返回条数上限（默认 50）

    Returns:
        dict: {"items": [{id, department, storage_location, material_name,
            quantity, unit, total_quantity_t, max_limit, hazard_classes,
            risk_flag, last_updated_at, ...}], "total": int}

    示例：查一下仓储部现在的危化品库存；乙醇现在库存有多少。
    """
    from app.modules.safety.service.chemical_inventory import ChemicalInventoryService

    service = ChemicalInventoryService(ctx.deps.db)
    items, total = await service.get_records(
        0, limit, department=department, material_name=material_name,
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "department": r.department,
                "storage_location": r.storage_location,
                "material_name": r.material_name,
                "package_spec": r.package_spec,
                "quantity": float(r.quantity) if r.quantity is not None else None,
                "unit": r.unit,
                "total_quantity_t": float(r.total_quantity_t) if r.total_quantity_t is not None else None,
                "max_limit": float(r.max_limit) if r.max_limit is not None else None,
                "hazard_classes": r.hazard_classes,
                "risk_flag": r.risk_flag,
                "risk_note": r.risk_note,
                "last_updated_at": r.last_updated_at.isoformat() if r.last_updated_at else None,
            }
            for r in items
        ],
        "total": total,
    }


async def analyze_chemical_risk(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
) -> dict[str, Any]:
    """分析危化品库存风险，返回每个化学品的风险标记与风险说明。

    基于规则引擎（超量/未分类/单位异常/专库违规）
    对当前库存台账做只读分析，不修改任何数据。

    Args:
        department: 部门名称，可选；不传则分析全部部门

    Returns:
        dict: {"alert_count": int,
            "items": [{department, storage_location, material_name,
                risk_flag(正常=normal/预警=warn), risk_note([预警类型列表])}]}

    示例：我们部门现在危化品有什么风险？分析全公司当前的危化品库存风险。
    """
    from app.modules.safety.service.chemical_inventory import ChemicalInventoryService

    service = ChemicalInventoryService(ctx.deps.db)
    return await service.analyze_risk(department=department)


# ═══════════════════════════════════════════════════════════════════
# AI 配置 / 定时任务管理 — 只读工具
# ═══════════════════════════════════════════════════════════════════


async def query_ai_config(ctx: RunContext[SafetyDeps]) -> dict[str, Any]:
    """查看当前安全模块 AI 模型配置与已注册 AI 调用功能。

    返回文本模型（DeepSeek）/视觉模型（qwen-vl）的 Base URL、模型名、超时、
    温度与脱敏密钥状态（完整 API Key 不会返回），以及 AI 调用功能清单
    （隐患识别、整改初审、知识库问答、消防/中控报警分析等）。

    Returns:
        dict: {"configured": bool, "text_model": {...}, "vision_model": {...}, "functions": [...]}
    """
    from app.modules.safety.service.ai_config import build_ai_config_view

    return build_ai_config_view()


async def query_scheduler_tasks(ctx: RunContext[SafetyDeps]) -> dict[str, Any]:
    """查看安全模块当前已配置的定时任务列表。

    返回每个任务的任务名、执行时间（时:分）、星期、启停状态、发送群聊、
    今日/最近运行状态与失败次数。

    Returns:
        dict: {"items": [{job_name, hour, minute, dow, enabled,
            target_chat_id, target_chat_name, report_type,
            run_state: {status, attempt_count, fired_date, last_attempt_at}}]}
    """
    from sqlalchemy import select

    from app.modules.safety.models import SchedulerJobRun
    from app.modules.safety.service.scheduler_config import (
        load_scheduled_jobs_with_overrides,
    )

    tasks = await load_scheduled_jobs_with_overrides(ctx.deps.db)
    rows = (
        await ctx.deps.db.execute(
            select(SchedulerJobRun).where(SchedulerJobRun.is_deleted.is_(False))
        )
    ).scalars().all()
    run_map = {r.job_name: r for r in rows}
    items = []
    for t in tasks:
        row = run_map.get(t["job_name"])
        t = dict(t)
        t["run_state"] = {
            "status": row.status if row else None,
            "attempt_count": row.attempt_count if row else 0,
            "fired_date": row.fired_date.isoformat() if row else None,
            "last_attempt_at": (
                row.last_attempt_at.isoformat() if row and row.last_attempt_at else None
            ),
            "alerted": row.alerted if row else False,
        }
        items.append(t)
    return {"items": items}


# ═══════════════════════════════════════════════════════════════════
# Bitable 配置中心 — 只读工具
# ═══════════════════════════════════════════════════════════════════


def _mask_app_token(app_token: str | None) -> str | None:
    """脱敏 app_token：仅显示前 6 位 + *（配置管理员场景可查看，不泄露完整 token）。"""
    if not app_token:
        return None
    return f"{app_token[:6]}****"


def _domain_config_item(view: Any, *, with_mappings: bool) -> dict[str, Any]:
    """DomainConfigView → Agent 可读 dict（app_token 脱敏，table_id 全显示）。"""
    from app.modules.safety.bitable_config import registry

    domain_info = registry.get_domain(view.domain)
    connections = []
    for kind, conn in view.connections.items():
        kind_info = domain_info.get_kind(kind)
        connections.append({
            "kind": kind,
            "label": kind_info.label,
            "app_token_masked": _mask_app_token(conn.app_token),
            "table_id": conn.table_id or None,
            "enabled": conn.enabled,
            "status": conn.status,
        })
    item: dict[str, Any] = {
        "domain": view.domain,
        "label": domain_info.label,
        "purpose": domain_info.purpose,
        "connections": connections,
    }
    if with_mappings:
        # 指定 domain：含映射概览（仅关键三字段，value_map 等不返回，控制输出体积）
        item["mappings"] = {
            kind: [
                {
                    "source_field": m.get("source_field"),
                    "target_field": m.get("target_field"),
                    "field_type": m.get("field_type"),
                }
                for m in mapping
            ]
            for kind, mapping in view.mappings.items()
        }
    else:
        item["mapping_counts"] = {
            kind: len(mapping) for kind, mapping in view.mappings.items()
        }
    return item


async def query_bitable_config(
    ctx: RunContext[SafetyDeps],
    domain: str | None = None,
) -> dict[str, Any]:
    """查询安全模块多维表格（Bitable）连接与字段映射配置状态（只读）。

    可回答"隐患登记连的是哪个多维表格""危化品库存表是否启用"
    "哪些域的多维表格没配置""职业健康各表映射了哪些字段"等问题。

    Args:
        domain: 域 key，可选。合法值：
            hazard(隐患登记) / knowledge(知识库法规) / emergency_drill(应急演练) /
            msds(MSDS台账) / chemical_inventory(危化品库存) / oh(职业健康) /
            fire_alarm(消防报警) / central_alarm(中控报警) / ehs_change(EHS变更) /
            contractor_admission(相关方准入) / cert(持证台账) / hazard_id(危险源辨识) /
            special_op(特殊作业日报) / key_risk_op(关键风险作业)。
            不传返回全部域概览（仅连接与映射条数）。

    Returns:
        dict: {"items": [{
            "domain": 域key, "label": 域中文名, "purpose": 用途,
            "connections": [{"kind": 表类型key, "label": 表中文名,
                "app_token_masked": app_token 仅前 6 位 + *（脱敏，完整 token 不返回）,
                "table_id": 表 ID（完整）, "enabled": 是否启用,
                "status": db=已配置 / default=默认配置 / disabled=已停用 / missing=未配置}],
            "mappings"(仅指定 domain 时): {kind: [{source_field, target_field, field_type}]},
            "mapping_counts"(全部域概览时): {kind: 映射条数}
        }]}

    示例：查一下隐患登记的多维表格配置；看看哪些域的多维表格没有配置。
    """
    from app.modules.safety.bitable_config import registry
    from app.modules.safety.bitable_config.store import store

    if domain is not None:
        try:
            registry.get_domain(domain)
        except ValueError as exc:
            return {"items": [], "error": str(exc)}
        view = store.get_domain_view(domain)
        return {"items": [_domain_config_item(view, with_mappings=True)]}

    items = [
        _domain_config_item(store.get_domain_view(info.key), with_mappings=False)
        for info in registry.REGISTRY.values()
    ]
    return {"items": items}


# ═══════════════════════════════════════════════════════════════════
# 已同步本地库的明细查询（特殊作业 / 关键风险作业 / EHS 变更 / 作业票审核 / 危险源辨识）
# 数据源 = 飞书 Bitable 事件同步落库的本地表，直接查库，不依赖 Bitable API。
# ═══════════════════════════════════════════════════════════════════

# 中文 → code 映射（与 bitable_config/registry.py special_op 映射一致，兼容直接传 code）
_SPECIAL_OP_TYPE_MAP = {
    "动火作业": "hot_work", "受限空间": "confined_space", "受限空间作业": "confined_space",
    "高处作业": "height_work", "吊装作业": "lifting", "临时用电": "temporary_electricity",
    "动土作业": "excavation", "断路作业": "road_breaking", "盲板抽堵": "blind_plate",
    "常规作业": "hot_work",
}
_SPECIAL_OP_LEVEL_MAP = {
    "特级/Ⅳ级": "special", "特级": "special", "一级（Ⅰ级）": "grade1", "一级": "grade1",
    "二级（Ⅱ级）": "grade2", "二级": "grade2", "三级（Ⅲ级）": "grade2", "三级": "grade2",
    "不涉及": "not_applicable",
}
_SPECIAL_OP_RISK_MAP = {
    "高": "high", "高风险": "high", "中": "medium", "中风险": "medium",
    "低": "low", "低风险": "low",
}
_SPECIAL_OP_REPORT_TYPE_MAP = {
    "计划内": "planned", "计划内作业": "planned",
    "计划外": "unplanned", "计划外作业": "unplanned",
}
_HI_LEVEL_KEYWORDS = {
    "1": ["一级", "重大"], "2": ["二级", "较大"], "3": ["三级", "一般"], "4": ["四级", "低风险"],
    "一级": ["一级"], "二级": ["二级"], "三级": ["三级"], "四级": ["四级"],
    "重大": ["重大"], "较大": ["较大"], "一般": ["一般"], "低": ["低风险"],
}


def _norm_choice(value: str | None, mapping: dict[str, str]) -> str | None:
    """枚举参数规范化：先查中文→code 映射，再兼容小写 code，未知值原样返回。"""
    if not value:
        return None
    v = value.strip()
    if v in mapping:
        return mapping[v]
    low = v.lower()
    if low in set(mapping.values()):
        return low
    return v


def _date_bounds(date_from: str | None, date_to: str | None) -> tuple[Any, Any]:
    """ISO 日期串 → (>= 起始零点, < 结束次日零点) 半开区间。"""
    from datetime import date as _date
    from datetime import timedelta

    start = _date.fromisoformat(date_from) if date_from else None
    end_exclusive = _date.fromisoformat(date_to) + timedelta(days=1) if date_to else None
    return start, end_exclusive


def _next_day(d: Any) -> Any:
    """date + 1 天（半开区间上界，工具内 date 过滤统一用）。"""
    from datetime import timedelta

    return d + timedelta(days=1)


def _detail_result(items: list[Any], page: int, page_size: int, total: int) -> dict[str, Any]:
    return {"success": True, "items": items, "page": page, "page_size": page_size, "total": total}


async def query_special_op_records(
    ctx: RunContext[SafetyDeps],
    department: str = "",
    date_from: str = "",
    date_to: str = "",
    operation_type: str = "",
    operation_level: str = "",
    daily_risk_level: str = "",
    report_type: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询全厂特殊作业判定明细（飞书「全厂特殊作业一览表」直读，含每日风险判定）。

    查"某部门的作业判定记录"用本工具而非生成日报。风险等级优先读表内
    「日报风险等级（AI）」列（每日回写两次），列为空则现场判定不回写；
    被排除的作业仍返回（带 is_excluded/exclusion_reason）。

    Args:
        department: 部门（子串匹配，如"五部"）
        date_from: 起始日期（ISO，按作业计划开始时间）
        date_to: 结束日期（ISO）
        operation_type: 动火/受限空间/高处/吊装/临时用电/动土/断路/盲板抽堵（或英文 code）
        operation_level: 特级/一级/二级/三级/不涉及（或 special/grade1 等）
        daily_risk_level: 高/中/低（或 high/medium/low）
        report_type: 计划内/计划外（或 planned/unplanned）
        keyword: 内容/地点/申请编号模糊匹配
        page: 页码（默认 1）
        page_size: 每页条数（默认 20，最大 100）

    示例：提炼五部的作业判定记录；今天的计划外高风险作业。
    """
    from datetime import date as _date

    from app.modules.safety.service.special_op_direct import query as direct_query

    try:
        result = await direct_query.query_records(
            department=department,
            date_from=_date.fromisoformat(date_from) if date_from else None,
            date_to=_date.fromisoformat(date_to) if date_to else None,
            operation_type=_norm_choice(operation_type, _SPECIAL_OP_TYPE_MAP),
            operation_level=_norm_choice(operation_level, _SPECIAL_OP_LEVEL_MAP),
            daily_risk_level=_norm_choice(daily_risk_level, _SPECIAL_OP_RISK_MAP),
            report_type=_norm_choice(report_type, _SPECIAL_OP_REPORT_TYPE_MAP),
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return _detail_result(result["items"], page, page_size, result["total"])
    except Exception as e:
        logger.exception("query_special_op_records failed")
        return {"success": False, "error": f"查询失败: {e}"}

async def query_key_risk_ops(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    apply_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询关键风险作业明细（周末节假日/非上班时段关键作业台账）。

    可按部门、作业开始日期、审批状态、关键词（作业内容/区域）筛选。

    Args:
        department: 部门名称，模糊匹配（如"提炼工程五部"）
        date_from: 起始日期（ISO，按作业开始时间，可选）
        date_to: 结束日期（ISO，可选）
        apply_status: 审批状态（已通过/审批中/已撤回/已拒绝，可选）
        keyword: 关键词（作业内容/区域模糊匹配，可选）
        page: 页码（默认 1）
        page_size: 每页条数（默认 20，最大 100）

    Returns:
        {success, items, page, page_size, total}
        - items: 明细（编号/部门/区域/作业内容/起止时间/时长/审批状态/当前节点/
          监护人/现场监护/部门安全员等）
        - total: 满足条件的总条数

    示例：本周有哪些关键风险作业；提炼五部的关键作业审批到哪一步了。
    """
    from sqlalchemy import func, or_, select

    from app.modules.safety.models import KeyRiskOperationReport

    try:
        start, end_exclusive = _date_bounds(date_from, date_to)

        # 直读模式：Bitable 全量 + 内存过滤/分页（Agent 口径：department 模糊、
        # keyword 两字段、无 source 过滤，与 legacy ORM 查询逐项一致）
        from app.modules.safety.service.key_risk_op_direct import config

        if config.direct_enabled():
            from app.modules.safety.service.key_risk_op_direct.query import (
                query_ops_for_agent,
            )
            from app.modules.safety.service.key_risk_op_direct.reader import open_reader

            rows, total = await query_ops_for_agent(
                await open_reader().fetch_all(),
                department=department, start=start, end_exclusive=end_exclusive,
                apply_status=apply_status, keyword=keyword,
                page=page, page_size=page_size,
            )
        else:
            conds = [KeyRiskOperationReport.is_deleted.is_(False)]
            if department:
                conds.append(KeyRiskOperationReport.department.ilike(f"%{department}%"))
            if start:
                conds.append(KeyRiskOperationReport.start_time >= start)
            if end_exclusive:
                conds.append(KeyRiskOperationReport.start_time < end_exclusive)
            if apply_status:
                conds.append(KeyRiskOperationReport.apply_status == apply_status.strip())
            if keyword:
                conds.append(or_(
                    KeyRiskOperationReport.operation_content.ilike(f"%{keyword}%"),
                    KeyRiskOperationReport.area.ilike(f"%{keyword}%"),
                ))

            db = ctx.deps.db
            total = (await db.execute(
                select(func.count()).select_from(KeyRiskOperationReport).where(*conds)
            )).scalar() or 0
            rows = (await db.execute(
                select(KeyRiskOperationReport).where(*conds)
                .order_by(KeyRiskOperationReport.start_time.desc())
                .offset((max(page, 1) - 1) * page_size).limit(min(page_size, 100))
            )).scalars().all()
        items = [{
            "report_no": r.report_no,
            "department": r.department,
            "area": r.area,
            "operation_content": r.operation_content,
            "start_time": r.start_time.isoformat() if r.start_time else None,
            "end_time": r.end_time.isoformat() if r.end_time else None,
            "duration_hours": r.duration_hours,
            "apply_status": r.apply_status,
            "approval_node": r.approval_node,
            "current_handler": r.current_handler,
            "initiator_name": r.initiator_name,
            "initiator_department": r.initiator_department,
            "guardian": r.guardian,
            "site_guardian": r.site_guardian,
            "dept_safety_officer": r.dept_safety_officer,
        } for r in rows]
        return _detail_result(items, page, page_size, total)
    except Exception as e:
        logger.exception("query_key_risk_ops failed")
        return {"success": False, "error": f"查询失败: {e}"}


async def query_ehs_changes(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    change_type: str | None = None,
    change_grade: str | None = None,
    status: str | None = None,
    ai_review_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询 EHS 变更管理明细（变更台账，含 AI 预审状态）。

    可按部门、日期区间、变更类型、变更等级、流程状态、AI 预审状态、关键词筛选。
    统计某月变更数量（如"本月有多少变更"）用 date_from/date_to 圈定区间看 total。

    Args:
        department: 部门名称，模糊匹配（可选）
        date_from: 起始日期（ISO，如 2026-10-01；按记录创建时间=申请提交日，可选）
        date_to: 结束日期（ISO，含当日，如 2026-10-31，可选）
        change_type: 变更类型（设备变更/工艺技术/管理等，可选）
        change_grade: 变更等级（重大/一般，或 major/general，可选）
        status: 流程状态（under_review/approved/closed/rejected/withdrawn，可选）
        ai_review_status: AI 预审状态（completed=已预审 / none=未预审，可选）
        keyword: 关键词（变更标题/内容描述模糊匹配，可选）
        page: 页码（默认 1）
        page_size: 每页条数（默认 20，最大 100）

    Returns:
        {success, items, page, page_size, total}
        - items: 明细（变更编号/标题/类型/等级/部门/状态/计划与实际起止/
          申请人/AI 预审状态等）
        - total: 满足条件的总条数

    示例：本月有多少变更；生产部有哪些重大变更；最近 AI 预审完成的变更。
    """
    # 直读分支（批次三）：DIRECT 开启时走 EHS 变更审批/验收两表 Bitable 直读，
    # 语义忠实复刻 legacy（spec D3：排序键 created_at→Bitable created_time 受控
    # 偏差、offset raw/limit cap 分页 quirk、actual_* 恒 None 复刻——状态机零
    # 使用探针坐实）。关=逐行 legacy。事件链路/AI 审核回写/API/状态机/前端零
    # 改动（spec D1）。
    from datetime import date as _date

    from app.modules.safety.service.ehs_change_direct import config as ehs_config

    try:
        d_from = _date.fromisoformat(date_from) if date_from else None
        d_to = _date.fromisoformat(date_to) if date_to else None

        if ehs_config.direct_enabled():
            from app.modules.safety.service.ehs_change_direct import (
                query as ehs_query,
            )
            from app.modules.safety.service.ehs_change_direct import (
                reader as ehs_reader,
            )

            views = await ehs_reader.open_reader().fetch_all()
            items, total = ehs_query.ehs_changes(
                views,
                department=department,
                date_from=d_from,
                date_to=d_to,
                change_type=change_type,
                change_grade=change_grade,
                status=status,
                ai_review_status=ai_review_status,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
            return _detail_result(items, page, page_size, total)

        from sqlalchemy import func, or_, select

        from app.modules.safety.models import EhsChange

        conds = [EhsChange.is_deleted.is_(False)]
        if department:
            conds.append(EhsChange.department.ilike(f"%{department}%"))
        # legacy created_at 为镜像首次插入时间（与直读 created_time 存在受控
        # 偏差，同排序偏差口径）；直读开着时不走本分支
        if d_from:
            conds.append(EhsChange.created_at >= d_from)
        if d_to:
            conds.append(EhsChange.created_at < _next_day(d_to))
        if change_type:
            conds.append(EhsChange.change_type == change_type.strip())
        if grade := _norm_choice(change_grade, {"重大": "major", "一般": "general"}):
            conds.append(EhsChange.change_grade == grade)
        if status:
            conds.append(EhsChange.status == status.strip().lower())
        if ai_review_status:
            conds.append(EhsChange.ai_review_status == ai_review_status.strip().lower())
        if keyword:
            conds.append(or_(
                EhsChange.title.ilike(f"%{keyword}%"),
                EhsChange.description.ilike(f"%{keyword}%"),
            ))

        db = ctx.deps.db
        total = (await db.execute(
            select(func.count()).select_from(EhsChange).where(*conds)
        )).scalar() or 0
        rows = (await db.execute(
            select(EhsChange).where(*conds)
            .order_by(EhsChange.created_at.desc())
            .offset((max(page, 1) - 1) * page_size).limit(min(page_size, 100))
        )).scalars().all()
        items = [{
            "change_no": r.change_no,
            "title": r.title,
            "change_type": r.change_type,
            "change_grade": r.change_grade,
            "department": r.department,
            "location_unit": r.location_unit,
            "status": r.status,
            "expected_start": r.expected_start.isoformat() if r.expected_start else None,
            "expected_completion": r.expected_completion.isoformat() if r.expected_completion else None,
            "actual_start": r.actual_start.isoformat() if r.actual_start else None,
            "actual_completion": r.actual_completion.isoformat() if r.actual_completion else None,
            "applicant_name": r.applicant_name,
            "ai_review_status": r.ai_review_status,
        } for r in rows]
        return _detail_result(items, page, page_size, total)
    except Exception as e:
        logger.exception("query_ehs_changes failed")
        return {"success": False, "error": f"查询失败: {e}"}


async def query_work_ticket_reviews(
    ctx: RunContext[SafetyDeps],
    date_from: str = "",
    date_to: str = "",
    ticket_type: str = "",
    rule_no: str = "",
    ticket_no: str = "",
    keyword: str = "",
    include_not_applicable: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询作业票 AI 审核记录与违规明细（审核批次统计 + 逐条违规）。

    默认仅返回真实违规；规则"不适用"记录需 include_not_applicable=True。

    Args:
        date_from / date_to: 起止日期（ISO，按审核日期）
        ticket_type: 票种（动火作业/受限空间/高处作业/临时用电，或 hot_work 等 code）
        rule_no: 规则编号（如 "7.1.3"）
        ticket_no: 作业票编号（模糊匹配）
        keyword: 违规详情/规则名称模糊匹配
        include_not_applicable: 含"规则不适用"记录（默认 False）
        page / page_size: 页码/每页条数（作用于审核批次，默认 20）

    示例：8月31日的作业票审核结果；动火票都有哪些违规。
    """
    # schema 瘦身：可选过滤参数默认空串（去除 anyOf 包装），空串与 None 等价
    date_from = date_from or None
    date_to = date_to or None
    ticket_type = ticket_type or None
    rule_no = rule_no or None
    ticket_no = ticket_no or None
    keyword = keyword or None
    from datetime import date as _date

    from sqlalchemy import func, or_, select

    from app.modules.safety.models import WorkTicketReview, WorkTicketReviewViolation

    try:
        conds = [WorkTicketReview.is_deleted.is_(False)]
        if date_from:
            conds.append(WorkTicketReview.date >= _date.fromisoformat(date_from))
        if date_to:
            conds.append(WorkTicketReview.date <= _date.fromisoformat(date_to))
        if keyword:
            conds.append(or_(
                WorkTicketReview.report_markdown.ilike(f"%{keyword}%"),
            ))

        db = ctx.deps.db
        total = (await db.execute(
            select(func.count()).select_from(WorkTicketReview).where(*conds)
        )).scalar() or 0
        reviews = (await db.execute(
            select(WorkTicketReview).where(*conds)
            .order_by(WorkTicketReview.date.desc())
            .offset((max(page, 1) - 1) * page_size).limit(min(page_size, 100))
        )).scalars().all()
        review_items = [{
            "date": r.date.isoformat() if r.date else None,
            "total": r.total,
            "reviewed": r.reviewed,
            "violation_count": r.violation_count,
            "compliant_count": r.compliant_count,
            "data_insufficient": r.data_insufficient,
            "status": r.status,
            "pushed": r.pushed,
        } for r in reviews]

        # 违规明细：按批次日期范围关联过滤 + 票种/规则/票号筛选
        v_conds = [WorkTicketReviewViolation.is_deleted.is_(False)]
        if not include_not_applicable:
            v_conds.append(WorkTicketReviewViolation.not_applicable.is_(False))
        if reviews:
            v_conds.append(WorkTicketReviewViolation.review_id.in_([r.id for r in reviews]))
        elif date_from or date_to:
            d_conds = [WorkTicketReview.is_deleted.is_(False)]
            if date_from:
                d_conds.append(WorkTicketReview.date >= _date.fromisoformat(date_from))
            if date_to:
                d_conds.append(WorkTicketReview.date <= _date.fromisoformat(date_to))
            v_conds.append(WorkTicketReviewViolation.review_id.in_(
                select(WorkTicketReview.id).where(*d_conds)
            ))
        if ticket_type:
            code = _norm_choice(ticket_type, _SPECIAL_OP_TYPE_MAP)
            v_conds.append(WorkTicketReviewViolation.ticket_type == code)
        if rule_no:
            v_conds.append(WorkTicketReviewViolation.rule_no == rule_no.strip())
        if ticket_no:
            v_conds.append(WorkTicketReviewViolation.ticket_no.ilike(f"%{ticket_no}%"))
        if keyword:
            v_conds.append(or_(
                WorkTicketReviewViolation.detail.ilike(f"%{keyword}%"),
                WorkTicketReviewViolation.rule_name.ilike(f"%{keyword}%"),
            ))

        v_rows = (await db.execute(
            select(WorkTicketReviewViolation, WorkTicketReview.date)
            .join(WorkTicketReview, WorkTicketReviewViolation.review_id == WorkTicketReview.id)
            .where(*v_conds)
            .order_by(WorkTicketReview.date.desc(), WorkTicketReviewViolation.id)
            .limit(200)
        )).all()
        violations = [{
            "review_date": d.isoformat() if d else None,
            "ticket_no": v.ticket_no,
            "ticket_type": v.ticket_type,
            "rule_no": v.rule_no,
            "rule_name": v.rule_name,
            "detail": v.detail,
            "not_applicable": v.not_applicable,
        } for v, d in v_rows]
        violation_total = (await db.execute(
            select(func.count())
            .select_from(WorkTicketReviewViolation)
            .join(WorkTicketReview, WorkTicketReviewViolation.review_id == WorkTicketReview.id)
            .where(*v_conds)
        )).scalar() or 0
        return {
            "success": True,
            "reviews": review_items,
            "violations": violations,
            "page": page,
            "page_size": page_size,
            "total": total,
            "violation_total": violation_total,
        }
    except Exception as e:
        logger.exception("query_work_ticket_reviews failed")
        return {"success": False, "error": f"查询失败: {e}"}


async def query_hazard_identifications(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    position: str | None = None,
    risk_stage: str | None = None,
    risk_level: str | None = None,
    overall_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询危险源辨识记录明细（LEC 评级结果）。

    每条含辨识的作业活动/设备设施、危险因素、可能事故、固有/残余/事后
    三阶段 LEC 评级（一级/重大 ～ 四级/低）。可按部门、日期区间、岗位、
    评级阶段与等级、整体状态筛选。统计某月辨识数量（如"本月辨识了多少
    条"）用 date_from/date_to 圈定区间看 total。

    Args:
        department: 部门名称，模糊匹配（如"提炼工程五部"）
        date_from: 起始日期（ISO，如 2026-10-01；按记录创建时间=辨识提交日，可选）
        date_to: 结束日期（ISO，含当日，如 2026-10-31，可选）
        position: 岗位，模糊匹配（可选）
        risk_stage: 评级阶段（inherent=固有 / residual=残余 / post=事后，可选；
            需与 risk_level 搭配使用）
        risk_level: 风险等级（一级/重大、二级/较大、三级/一般、四级/低 或
            1/2/3/4，需与 risk_stage 搭配）
        overall_status: 整体状态（如 pending/processing/completed，可选）
        keyword: 关键词（作业活动/危险因素/可能事故模糊匹配，可选）
        page: 页码（默认 1）
        page_size: 每页条数（默认 20，最大 100）

    Returns:
        {success, items, page, page_size, total}
        - items: 明细（辨识编号/部门/岗位/作业活动/危险因素/可能事故/
          三阶段风险等级/管控层级/建议措施/整体状态/飞书链接）
        - total: 满足条件的总条数

    示例：本月辨识了多少条危险源；提炼五部有哪些重大风险辨识。
    """
    # 直读分支（批次四-2）：DIRECT 开启时走危险源辨识表 Bitable 直读，语义
    # 忠实复刻 legacy（spec D5：排序键 created_at→Bitable created_time 受控
    # 偏差、offset raw/limit cap 分页 quirk、脚本6 人工列缺失 quirk、
    # feishu_url 恒 None 死值复刻）；部门按提交人 identity 现算（镜像同规则，
    # spec D6）。关=逐行 legacy。事件链路/AI 流程/API/前端零改动（spec D1）。
    from datetime import date as _date

    from app.modules.safety.service.hazard_id_direct import config as hid_config

    try:
        d_from = _date.fromisoformat(date_from) if date_from else None
        d_to = _date.fromisoformat(date_to) if date_to else None

        if hid_config.direct_enabled():
            from app.modules.safety.service.hazard_id_direct import (
                query as hid_query,
            )
            from app.modules.safety.service.hazard_id_direct import (
                reader as hid_reader,
            )

            views = await hid_reader.open_reader().fetch_all()
            departments = await hid_query.resolve_departments(
                ctx.deps.db, {v.submitter_name for v in views},
            )
            items, total = hid_query.hazard_identifications(
                views,
                departments=departments,
                department=department,
                position=position,
                risk_stage=risk_stage,
                risk_level=risk_level,
                overall_status=overall_status,
                keyword=keyword,
                date_from=d_from,
                date_to=d_to,
                page=page,
                page_size=page_size,
            )
            return _detail_result(items, page, page_size, total)

        from sqlalchemy import func, or_, select

        from app.modules.safety.models import HazardIdentification

        conds = [HazardIdentification.is_deleted.is_(False)]
        if department:
            conds.append(HazardIdentification.department.ilike(f"%{department}%"))
        # legacy created_at 为镜像首次插入时间（与直读 created_time 存在受控
        # 偏差，同排序偏差口径）；直读开着时不走本分支
        if d_from:
            conds.append(HazardIdentification.created_at >= d_from)
        if d_to:
            conds.append(HazardIdentification.created_at < _next_day(d_to))
        if position:
            conds.append(HazardIdentification.position.ilike(f"%{position}%"))
        if risk_stage and risk_level:
            stage_cols = {
                "inherent": HazardIdentification.inherent_risk_label,
                "residual": HazardIdentification.residual_risk_label,
                "post": HazardIdentification.post_risk_label,
            }
            col = stage_cols.get(risk_stage.strip().lower())
            kws = _HI_LEVEL_KEYWORDS.get(risk_level.strip())
            if col and kws:
                conds.append(or_(*[col.ilike(f"%{kw}%") for kw in kws]))
        if overall_status:
            conds.append(HazardIdentification.overall_status == overall_status.strip().lower())
        if keyword:
            conds.append(or_(
                HazardIdentification.specific_activity.ilike(f"%{keyword}%"),
                HazardIdentification.hazard_type.ilike(f"%{keyword}%"),
                HazardIdentification.possible_accident.ilike(f"%{keyword}%"),
            ))

        db = ctx.deps.db
        total = (await db.execute(
            select(func.count()).select_from(HazardIdentification).where(*conds)
        )).scalar() or 0
        rows = (await db.execute(
            select(HazardIdentification).where(*conds)
            .order_by(HazardIdentification.created_at.desc())
            .offset((max(page, 1) - 1) * page_size).limit(min(page_size, 100))
        )).scalars().all()
        items = [{
            "hazard_id_no": r.hazard_id_no,
            "department": r.department,
            "position": r.position,
            "production_step": r.production_step,
            "specific_activity": r.specific_activity,
            "hazard_type": r.hazard_type,
            "possible_accident": r.possible_accident,
            "inherent_risk_label": r.inherent_risk_label,
            "residual_risk_label": r.residual_risk_label,
            "post_risk_label": r.post_risk_label,
            "control_level": r.control_level,
            "recommendation_content": r.recommendation_content,
            "overall_status": r.overall_status,
            "submitter_name": r.submitter_name,
            "feishu_url": r.feishu_url,
        } for r in rows]
        return _detail_result(items, page, page_size, total)
    except Exception as e:
        logger.exception("query_hazard_identifications failed")
        return {"success": False, "error": f"查询失败: {e}"}


async def screen_work_ticket_personnel(
    ctx: RunContext[SafetyDeps],
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """作业票外包人员直读筛查（票面人员 x 平台承包商台账，只读、不落库）。

    实时从作业票平台拉取窗口内作业票的票面人员（动火/高处/吊装有人员
    子表），与平台承包商人员台账（约 350 人）比对：选择器人员按 ID 精确
    匹配（并区分内部员工），动火票文本行按姓名匹配。身份证号/手机号
    输出前打码。

    Args:
        date_from: 起始日期（ISO，如 "2026-09-28"，默认今天）
        date_to: 结束日期（ISO，可选，默认同 date_from；窗口最长 31 天）

    Returns:
        {success, date_from, date_to, registry_total, tickets_scanned,
         tickets_with_personnel, person_rows, stats, abnormal, per_ticket}
        - stats: id_matched / name_matched / not_registered（未命中台账，
          可能为内部人员或未录入实名台账）/ ambiguous（同名多条）/
          internal_user（内部员工，不比对）各计数
        - abnormal: 需人工跟进条目（票号/票种/人员/状态/同名候选）

    示例：今天作业票上的外包人员核查；9月有哪些票面人员不在承包商台账里。
    """
    from datetime import date as _date

    from app.modules.safety.workticket_review.personnel_screening import (
        ContractorPersonnelScreeningService,
    )

    try:
        base = _date.fromisoformat(date_from) if date_from else _date.today()
        end = _date.fromisoformat(date_to) if date_to else base
        service = ContractorPersonnelScreeningService()
        return await service.screen(base, end)
    except ValueError as e:
        return {"success": False, "error": f"参数无效: {e}"}
    except RuntimeError as e:
        logger.exception("screen_work_ticket_personnel failed")
        return {"success": False, "error": f"平台拉取失败: {e}"}


# ══════════════════════════════════════════════════════════════
# 法规采集监控（regulation-ingest 09：收录管线视角，与台账维度的
# query_latest_regulations 互补——本组数据来自采集监控聚合信封）
# ══════════════════════════════════════════════════════════════


async def query_regulation_crawl_status(
    ctx: RunContext[SafetyDeps],
) -> dict[str, Any]:
    """查询法规采集监控状态：数据源健康、最近运行与大盘摘要。

    Returns:
        dict: {"status": "live|degraded|not_connected", "stats": {...},
               "sources": [...], "errors": [...], "source": "regulation-monitor"}
    """
    from app.modules.safety.regulation_ingest.monitor import build_monitor_envelope

    try:
        envelope = await build_monitor_envelope(ctx.deps.db, page=1, page_size=1)
    except Exception as e:
        logger.exception("query_regulation_crawl_status failed")
        return {"success": False, "error": f"采集监控聚合失败: {e}"}
    return {
        "success": True,
        "status": envelope["status"],
        "stats": envelope["stats"],
        "sources": [
            {
                "name": s.get("name"),
                "status": s.get("status"),
                "consecutive_failures": s.get("consecutive_failures"),
                "items_7d": s.get("items_7d"),
            }
            for s in envelope["sources"]
        ],
        "errors": envelope["errors"],
        "source": "regulation-monitor",
    }


async def _query_regulations_ingested_impl(
    ctx: RunContext[SafetyDeps],
    limit: int = 5,
) -> dict[str, Any]:
    """收录管线视角：最新收录的法规（合并前 query_regulation_latest 本体）。

    Args:
        limit: 返回条数上限（默认 5，最大 20）
    """
    from app.modules.safety.regulation_ingest.monitor import build_monitor_envelope

    limit = max(1, min(limit, 20))
    try:
        envelope = await build_monitor_envelope(ctx.deps.db, page=1, page_size=1)
    except Exception as e:
        logger.exception("query_regulation_latest failed")
        return {"success": False, "error": f"采集监控聚合失败: {e}"}
    items = [
        {
            "title": f.get("title"),
            "ingested_at": f.get("ingested_at"),
            "is_revision": f.get("is_revision"),
            "reason": f.get("reason"),
            "url": f.get("url"),
        }
        for f in envelope["feed"][:limit]
    ]
    return {"success": True, "items": items, "total": len(items), "source": "regulation-monitor"}


async def query_standard_compliance(
    ctx: RunContext[SafetyDeps],
    element: str = "",
    status: str = "",
    year: int | None = None,
) -> dict[str, Any]:
    """查询体系标准符合性核查结果（目标责任与绩效：标准×运行数据四态判定）。

    标准清单=GB/T 33000 八要素下的可核查条款（如"综合或专项应急预案演练
    每半年≥1次"），平台自动对比系统运行数据判定：达标 ok / 进行中
    in_progress（周期未满）/ 未达标 missed / 无数据 no_data（依赖域未接入）。

    Args:
        element: 要素归属筛选（目标职责/制度化管理/教育培训/现场管理/
            风险管控与隐患治理/应急管理/事故管理/持续改进，可选）
        status: 四态筛选（ok/in_progress/missed/no_data，可选）
        year: 年度（默认当年，如 2026，可选）

    Returns:
        {success, summary, groups}
        - summary: 当年四态计数与综合符合率
        - groups: 按要素分组的标准行（编号/条款/目标/当前完成值/状态/
          责任部门/剩余天数/无数据原因）

    示例：今年综合演练做了吗；哪些标准还没达标；应急管理要素的符合情况。
    """
    from app.modules.safety.service.standard_check import build_standard_check_page

    try:
        data = await build_standard_check_page(
            db=ctx.deps.db,
            element=element or None,
            status=status or None,
            year=year,
        )
        if data["status"] == "not_connected":
            return {
                "success": False,
                "error": "体系标准核查表未接入（goals/standard_check 连接未登记）",
            }
        if data["status"] == "degraded":
            return {"success": False, "error": "核查表读取降级，稍后重试"}
        summary = data["summary"]
        return {
            "success": True,
            "summary": summary,
            "groups": [
                {
                    "element": g["element"],
                    "rows": [
                        {
                            "no": r["no"],
                            "clause": r["clause"],
                            "target": r["target_display"],
                            "actual": r["actual_display"],
                            "status": r["status"],
                            "residual_days": r["residual_days"],
                            "department": "、".join(r["department"]) or "未指派",
                            "note": r["note"],
                        }
                        for r in g["rows"]
                    ],
                }
                for g in data["groups"]
            ],
        }
    except Exception as e:  # noqa: BLE001 —— 工具边界兜底，报错回 Agent
        logger.exception("query_standard_compliance failed")
        return {"success": False, "error": f"查询失败: {e}"}


# ═══════════════════════════════════════════════════════════════════
# 承包商在册人员 / 岗位字典 — 只读工具（3.x 平台关联 F1，按需挂载）
# ═══════════════════════════════════════════════════════════════════


async def query_contractor_workers(
    ctx: RunContext[SafetyDeps],
    contractor: str | None = None,
    work_type: str | None = None,
    age_above: int | None = None,
    insurance_missing: bool = False,
    cert_missing_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询承包商在册人员（3.x 平台实名台账 + 三组交叉核验）。

    「现场现在有哪些承包商的电工」「保险没覆盖的外包人员名单」直接可答。
    口径统一「在册」（平台 bind/定位字段全空，不称「在场」）；身份证/手机
    返回打码值（前 3 后 2，与 S14 副台账页面同口径）。

    Args:
        contractor: 承包商单位名（包含匹配，如"天目"）
        work_type: 工种精确匹配（普工/焊工/电工/架子工/驾驶员等，平台实测值域）
        age_above: 年龄阈值（≥该值的在册人员）
        insurance_missing: 仅看无有效保险人员（未覆盖/未填报/已过期；
            临期属已覆盖需关注，不算缺失——与统计卡口径一致）
        cert_missing_only: 仅看特种工种且证书台账未见持证记录人员
            （注意：dazah 证书台账主体是内部员工证书，未见记录≠无证）
        page: 页码（从1开始）
        page_size: 每页条数

    Returns:
        {status, fetched_at, message, stats, total, page, page_size, items: [...]}
    """
    from app.modules.safety.service.contractor_workers import open_service

    payload = await open_service().get_payload()
    if payload["status"] == "empty":
        return {
            "status": "empty",
            "message": payload["message"],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "items": [],
        }

    # 口径与统计卡一致：expiring（临期）属「已覆盖但需关注」，不算缺失——
    # 临期人员经 anomalies「保险临期」标签与「仅看异常」筛选可及
    no_effective_insurance = ("uncovered", "unfiled", "expired")
    workers = payload["workers"]
    if contractor:
        kw = contractor.strip()
        workers = [w for w in workers if kw in (w.get("contractor_name") or "")]
    if work_type:
        workers = [w for w in workers if (w.get("work_type") or "") == work_type]
    if age_above is not None:
        workers = [
            w for w in workers
            if isinstance(w.get("age"), (int, float)) and w["age"] >= age_above
        ]
    if insurance_missing:
        workers = [
            w for w in workers
            if w.get("insurance_status") in no_effective_insurance
        ]
    if cert_missing_only:
        workers = [w for w in workers if w.get("cert_status") == "missing"]

    total = len(workers)
    start = max(page - 1, 0) * page_size
    items = [
        {
            "name": w.get("name"),
            "contractor_name": w.get("contractor_name"),
            "work_type": w.get("work_type"),
            "age": w.get("age"),
            "join_job_date": w.get("join_job_date"),
            "card_no_masked": w.get("card_no_masked"),
            "phone_masked": w.get("phone_masked"),
            "insurance_status": w.get("insurance_status"),
            "insurance_expire_date": w.get("insurance_expire_date"),
            "cert_status": w.get("cert_status"),
            "cert_project": w.get("cert_project"),
            "age_flag": w.get("age_flag"),
            "anomalies": w.get("anomalies"),
        }
        for w in workers[start : start + page_size]
    ]
    return {
        "status": payload["status"],
        "fetched_at": payload["fetched_at"],
        "message": payload["message"],
        "stats": payload["stats"],
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


async def query_org_posts(
    ctx: RunContext[SafetyDeps],
    dept: str | None = None,
    keyword: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    """查询全厂岗位字典（3.x 平台全员主档去重；#4 可按岗位族过滤）。

    「厂里冻干岗位有哪些」「特种作业相关岗位有哪些」可答：返回岗位
    （postName 分组）× 部门列表 × 人数，行带岗位族归类（未归类为 null）。
    个人明细不返回（隐私口径，平台主档身份证为空）。

    Args:
        dept: 部门名（包含匹配，如"精制"）
        keyword: 岗位名关键词（包含匹配，如"冻干"）
        family: 岗位族过滤（#4 九族枚举之一，如"特种作业相关"；「未归类」
            可查尚未归类的岗位）

    Returns:
        {status, fetched_at, message, total, truncated, families,
         posts: [{post_name, dept_names, headcount, family}]}
    """
    from app.modules.safety.service.org_directory import open_org_posts_service
    from app.modules.safety.service.org_post_families import (
        build_family_aggregation,
        family_map_for_posts,
    )

    payload = await open_org_posts_service().get_payload(dept=dept, keyword=keyword)
    posts = payload["posts"]
    family_map = await family_map_for_posts(ctx.deps.db)
    families = build_family_aggregation(
        open_org_posts_service().cached_all_posts() or posts, family_map
    )
    rows = [{**p, "family": family_map.get(p["post_name"])} for p in posts]
    if family:
        rows = [r for r in rows if (r["family"] or "未归类") == family]
    # 防刷屏：超出 50 条截断并提示（岗位字典全量约 300+，按需收窄关键词）
    capped = rows[:50]
    return {
        "status": payload["status"],
        "fetched_at": payload["fetched_at"],
        "message": payload["message"],
        "total": len(rows),
        "truncated": len(rows) > len(capped),
        "families": families,
        "posts": capped,
    }
