"""SOP AI 层 — 对照源文档的 AI 审核 + 章节重组。

生成后自动审核：按章节输出结构化修正，重组 9 章；未命中修正的章节原文逐字节透传。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from ._prompts import SOP_REVIEW_SYSTEM_PROMPT, SOP_VISION_REVIEW_SYSTEM_PROMPT
from ._validate import MAX_LAYOUT_ISSUES, _validate_review, _validate_vision_review

logger = logging.getLogger(__name__)

# 源文档截断上限（审核需同时容纳源文档 + 生成内容，源文档截断控制成本）
MAX_REVIEW_SOURCE_CHARS = 60000

# 视觉审核每批页数上限（控制单次视觉调用图片数，避免超上下文与成本失控）
VISION_REVIEW_BATCH_SIZE = 4

# 视觉维度状态严重度排序（跨批同名维度取最坏：fail > warn > pass）
_STATUS_RANK = {"pass": 0, "warn": 1, "fail": 2}

# 章节标题正则：`# N.`（行首，N ∈ 1..9）
_CHAPTER_HEADING_RE = re.compile(r"^# ([1-9])\.", re.MULTILINE)


def _split_chapters(generated_md: str) -> list[dict]:
    """按 `# N.` 将 Markdown 拆成 9 章。

    返回 [{chapter, title, heading_line, content}]，content 为整章文本（含标题行）。
    第 1 章从 `# 1.` 到 `# 2.` 之前；第 9 章到文件尾。
    """
    headings = list(_CHAPTER_HEADING_RE.finditer(generated_md))
    chapters: list[dict] = []
    for i, m in enumerate(headings):
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(generated_md)
        chapter_md = generated_md[start:end]
        # 标题行 = 从匹配起点到行尾（如 `# 5. 工艺控制参数`）
        line_end = chapter_md.find("\n")
        if line_end == -1:
            line_end = len(chapter_md)
        heading_line = chapter_md[:line_end].rstrip()
        # 标题 = 去掉 `# N.` 编号前缀（如 `# 5. 工艺控制参数` → `工艺控制参数`）
        title = re.sub(r"^#\s*\d+\.\s*", "", heading_line).strip()
        chapters.append(
            {"chapter": int(m.group(1)), "title": title, "heading_line": heading_line, "content": chapter_md}
        )
    return chapters


def reassemble_sop(generated_md: str, chapter_fixes: list[dict]) -> str:
    """按结构化章节修正重组 9 章 Markdown。

    - 未命中修正的章节原文逐字节透传（防 AI 一次误改破坏整份操规）。
    - ch1（页眉元信息区）与 ch9（签名表）只允许 append；AI 返回 rewrite 降级为 append。
    - 章标题行永远以 `# N.` 开头（服务端写死，不信任 AI 返回的标题）。
    """
    chapters = _split_chapters(generated_md)
    by_chapter = {c["chapter"]: c for c in chapters}

    for fix in chapter_fixes or []:
        try:
            chapter = int(fix.get("chapter") or 0)
            action = str(fix.get("action") or "keep").strip()
            corrected = str(fix.get("corrected_content") or "").strip()
        except (TypeError, ValueError):
            continue
        if chapter not in by_chapter:
            continue
        if not corrected:
            continue

        # ch1/ch9 只允许 append（rewrite 降级）
        if chapter in (1, 9) and action == "rewrite":
            action = "append"

        # AI 返回整章重写（corrected 以章标题开头）时，append 会把一整章
        # 内容拼到原文后 → 文档出现两段重复章节（验收复现：结晶与脱盐 ch1
        # 出现两段"1. 目的"）。此时剥离 AI 标题行，按正文替换处理。
        if action == "append" and re.match(rf"^#\s*{chapter}[\.、\s]", corrected):
            corrected = corrected.split("\n", 1)[1].lstrip() if "\n" in corrected else corrected
            action = "rewrite"

        if action == "rewrite":
            heading = f"# {chapter}. {by_chapter[chapter]['title']}"
            by_chapter[chapter]["content"] = f"{heading}\n\n{corrected}\n"
        elif action == "append":
            by_chapter[chapter]["content"] = by_chapter[chapter]["content"].rstrip() + f"\n\n{corrected}\n"

    # 按原顺序重组
    chapters.sort(key=lambda c: c["chapter"])
    return "".join(c["content"] for c in chapters)


async def sop_review_document(
    *,
    source_text: str,
    generated_md: str,
    regulation_id: uuid.UUID | None = None,
    channel: str = "web",
) -> dict | None:
    """对照源文档对生成的标准化操规执行 AI 审核。

    Args:
        source_text: 源文档全文（截断至 MAX_REVIEW_SOURCE_CHARS）。
        generated_md: 生成的标准化 Markdown（9 章，全量传入）。
        regulation_id: 操规记录 ID，写入审计 resource_id。
        channel: 审计 channel（web=用户发起 / system=后台自动触发）。

    Returns:
        规范化审核结果 {summary, dimensions, chapter_fixes}；AI 失败/校验不过返回 None。

    说明：审核输出需内嵌整章修正 Markdown（corrected_content），输出量大时
    DeepSeek 偶发返回空串或截断 JSON。此处对解析/调用失败重试最多 2 次
    （每次独立审计落表，便于观察每次尝试的输入输出），全部失败才返回 None。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    source_text = (source_text or "")[:MAX_REVIEW_SOURCE_CHARS]

    user_content = (
        "请对照源文档原文，审核下面这份已生成的标准化操规，输出 JSON 对象。\n\n"
        f"## 源文档原文\n{source_text}\n\n"
        f"## 已生成的标准化操规\n{generated_md}"
    )

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with ai_audit_scope(
                scenario="sop_review",
                channel=channel,
                resource_type="regulation",
                resource_id=regulation_id,  # UUID 类型列，直接传对象
            ):
                ai = create_ai_service("text")
                result = await ai.chat_parsed(
                    messages=[
                        {"role": "system", "content": SOP_REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    expected_keys=["summary", "dimensions", "chapter_fixes"],
                    temperature=0.1,
                    # 审核输出内嵌 9 章 corrected_content，16K 上限会硬截断 → JSON 解析失败
                    # （验收复现：新线纯化 3 次重试均 "not valid JSON"，output_tokens=16384 顶格）。
                    # 实际生效模型（本地代理 deepseek-v4-flash-vision-exp）支持 32K 输出。
                    max_tokens=32768,
                )
            return _validate_review(result)
        except Exception as exc:  # noqa: BLE001 — AI 失败保留原稿，可重试
            last_exc = exc
            logger.warning(
                "SOP AI 审核调用失败（第 %d/3 次）：%s", attempt + 1, exc
            )
            if attempt < 2:
                await asyncio.sleep(1.0 + attempt)

    logger.error("SOP AI 审核调用 3 次均失败：%s", last_exc)
    return None


async def sop_review_document_vision(
    *,
    page_paths: list[str],
    regulation_id: uuid.UUID | None = None,
    channel: str = "web",
    batch_size: int = VISION_REVIEW_BATCH_SIZE,
) -> dict | None:
    """对操规渲染后的页面图片执行视觉审核（分批串行，聚合报告）。

    视觉通道专注**渲染页面上看得见的东西**：排版布局 / 格式规范 / 页面可见
    内容完整度。内容对源文档的深度保真由文本通道（sop_review_document）负责，
    因此本函数**不接收源文档全文**——分批串行下每批是独立无状态调用，带源
    文档会成本 ×批次且批间一致性差。

    每批独立 ai_audit_scope（scenario="sop_review"，extra.kind="vision" 区分
    批次），调用 VisionService.analyze_parsed 自动落审计表；批间结果聚合：
    layout_issues 按 (page, issue_type) 去重拼接、dimensions 按名去重
    （跨批同名维度取最坏 status，fail > warn > pass）、summary 按批拼接。

    Args:
        page_paths: 渲染后的每页 PNG 路径列表（按页序）。
        regulation_id: 操规记录 ID，写入审计 resource_id。
        channel: 审计 channel（web=用户发起 / system=后台自动触发）。
        batch_size: 每批送审页数。

    Returns:
        聚合视觉审核报告 {summary, dimensions, layout_issues}；
        无页面 / 全部批次失败或校验不过返回 None（调用方降级为纯文本通道）。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service
    from app.modules.safety.vision.service import VisionService

    if not page_paths:
        return None

    total = len(page_paths)
    batches: list[list[str]] = [
        page_paths[i : i + batch_size] for i in range(0, total, batch_size)
    ]

    agg_summaries: list[str] = []
    agg_dimensions: dict[str, dict] = {}  # 按维度名去重，首见保留
    agg_layout_issues: list[dict] = []
    seen_issue: set[tuple] = set()
    any_ok = False
    offset = 0

    for idx, batch in enumerate(batches, start=1):
        first_page = offset + 1
        last_page = offset + len(batch)
        offset += len(batch)
        try:
            with ai_audit_scope(
                scenario="sop_review",
                channel=channel,
                resource_type="regulation",
                resource_id=regulation_id,
                extra={"kind": "vision", "batch": idx, "pages": f"{first_page}-{last_page}"},
            ):
                ai = create_ai_service("vision")
                vision = VisionService(ai)
                # 前缀缓存友好：静态 prompt 在前，页面范围变量放尾部
                text_prompt = (
                    f"{SOP_VISION_REVIEW_SYSTEM_PROMPT}\n"
                    f"本批页面：第 {first_page}~{last_page} 页，共 {total} 页。"
                )
                result = await vision.analyze_parsed(
                    text_prompt=text_prompt,
                    image_urls=batch,
                    expected_keys=["summary"],  # 只强制锚定 summary，缺维度/问题允许默认
                    temperature=0.1,
                )
            parsed = _validate_vision_review(result)
            if not parsed:
                logger.warning(
                    "SOP 视觉审核第 %d/%d 批结果校验不过", idx, len(batches)
                )
                continue
            any_ok = True
            agg_summaries.append(
                f"第 {first_page}-{last_page} 页：{parsed.get('summary') or '（无结论）'}"
            )
            for dim in parsed.get("dimensions") or []:
                name = dim["dimension"]
                prev = agg_dimensions.get(name)
                if prev is None:
                    agg_dimensions[name] = dict(dim)
                elif _STATUS_RANK.get(dim["status"], 0) > _STATUS_RANK.get(
                    prev["status"], 0
                ):
                    # 同名维度跨批取最坏 status（如批1 pass、批2 fail → fail），
                    # 并同步替换为该批的 detail，避免"总体 pass 但某页有严重问题"被掩盖
                    prev["status"] = dim["status"]
                    prev["detail"] = dim["detail"]
            for issue in parsed.get("layout_issues") or []:
                key = (issue["page"], issue["issue_type"])
                if key in seen_issue:
                    continue
                seen_issue.add(key)
                agg_layout_issues.append(issue)
        except Exception as exc:  # noqa: BLE001 — 单批失败不影响其余批次
            logger.warning(
                "SOP 视觉审核第 %d/%d 批调用失败：%s", idx, len(batches), exc
            )

    if not any_ok:
        logger.error("SOP 视觉审核全部 %d 批失败或校验不过", len(batches))
        return None

    return {
        "summary": "；".join(agg_summaries),
        "dimensions": list(agg_dimensions.values()),
        "layout_issues": agg_layout_issues[:MAX_LAYOUT_ISSUES],
    }


def merge_reviews(text_review: dict, vision_review: dict | None) -> dict:
    """合并文本审核与视觉审核结果，供 run_ai_review 落库。

    - dimensions：文本维度在前（REVIEW_DIMENSIONS 顺序已由 _validate_review
      保证），视觉新增维度按名去重追加尾部（文本同名维度优先）。
    - chapter_fixes：只取文本通道（视觉不产生整章重写，避免视觉误改正文）。
    - summary：文本结论；视觉结论单独放 layout_summary。
    - layout_issues：视觉页级问题（仅视觉审核成功时存在）。

    vision_review 为 None 时仅返回文本结果（不含 layout_issues/layout_summary），
    由调用方负责追加「排版布局未检查」的 warn 维度提示。
    """
    merged: dict = {
        "summary": (text_review or {}).get("summary", ""),
        "dimensions": list((text_review or {}).get("dimensions", [])),
        "chapter_fixes": list((text_review or {}).get("chapter_fixes", [])),
    }
    if vision_review:
        existing = {d["dimension"] for d in merged["dimensions"]}
        for dim in vision_review.get("dimensions", []):
            if dim["dimension"] not in existing:
                merged["dimensions"].append(dim)
                existing.add(dim["dimension"])
        merged["layout_issues"] = list(vision_review.get("layout_issues", []))
        if vision_review.get("summary"):
            merged["layout_summary"] = vision_review["summary"]
    return merged
