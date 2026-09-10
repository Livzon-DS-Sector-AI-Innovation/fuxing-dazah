"""法规抓取编排服务。

职责：遍历数据源 → 爬取 → AI 管线（分类→提取→评估→对比）→ 写入 Bitable → 通知。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re as _re
import uuid
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.attachment_store import (
    cleanup_temp,
    materialize,
    resolve_local_path,
    store_bytes,
)
from app.modules.safety.regulation_crawler.engine.base import RegulationSource
from app.modules.safety.regulation_crawler.engine.extractors import AIExtractor
from app.modules.safety.regulation_crawler.engine.sources import DEFAULT_SOURCES
from app.modules.safety.regulation_crawler.engine.strategies import crawler_factory
from app.modules.safety.regulation_crawler.schemas import (
    ChangeDetectionWebhookRequest,
    CrawledRegulation,
    CrawlItemResult,
    CrawlResultSummary,
)
from app.modules.safety.regulation_crawler.writer.bitable_writer import BitableWriter

logger = logging.getLogger(__name__)

# ── 实质性变更判定阈值 ──
_SUBSTANTIVE_DIFF_MIN_CHARS = 30


def _guess_document_content_type(name: str) -> str:
    """按扩展名猜文档 Content-Type（未知类型回退 octet-stream）。"""
    ext = os.path.splitext(name)[1].lower()
    return {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        ".txt": "text/plain; charset=utf-8",
    }.get(ext, "application/octet-stream")

# ── recency 窗口：发布日期过老的非新法规跳过写入 ──
# 与 engine/strategies.py 的 _MAX_STANDARD_AGE_YEARS 保持一致（1 年）。
# 用途：hbba/openstd 等全量历史目录源在爬取层已过滤；此兜底覆盖所有来源，
# 防止未来新增全量目录源时再次把历史老法规当"新增"写入并推送。
# 2026-08-31 按运维要求由 2 年收紧为 1 年（每周爬取场景，1 年窗口足够覆盖新增）。
_MAX_REGULATION_AGE_YEARS = 1

# ── 原文待补：标准发布公告正文特征 ──
# 标准编号，如 "HJ 1480-2026" / "GB 3095-2026" / "GB 14287.9-2026"
_STD_NO_RE = _re.compile(r"[A-Z]{2,5}\s?\d{3,5}[.\-0-9]*\s*[-—]\s*20\d{2}")


def _is_standard_publish_announcement(body: str) -> bool:
    """判定 mee 公告页是否为「标准发布公告」（正文只声明发布，标准全文在别处）。

    标准发布公告特征：
      - 正文出现「标准内容可在…查询」（明确指向外部标准正文）
      - 正文含标准编号（HJ/GB/AQ 等）
    此类页面渲染成 PDF 只是公告页截图，不是法规原文，应标记原文待补。
    """
    if not body:
        return False
    if "标准内容可在" in body and "查询" in body:
        return True
    if _STD_NO_RE.search(body):
        return True
    return False


def _is_repeal_or_revision(item: CrawledRegulation) -> bool:
    """判断是否需豁免 recency 过滤（将触发 Bitable 旧记录删除）。

    仅当状态为「已废止」（与 write_regulation 的删除路径一致）时才豁免，
    以便废止类条目能走到写入层触发 Bitable 删除。

    不再因标题含"修订/替代/作废/失效"等关键词豁免——那常常是 2011-2017 年的
    老法修订版（如"XX管理办法（2016修订）"），放行会把它们当作新增写入。
    真正的废止/替代通知是近期发布的（发布日期落在 2 年窗口内），recency 本身会放行，
    无需依赖标题关键词豁免。
    """
    if not item:
        return False
    return bool(item.status and "已废止" in item.status)


class RegulationCrawlerService:
    """法规抓取编排服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.writer = BitableWriter()
        self.extractor = AIExtractor()
        # fire-and-forget 后台任务（chunk 重建等），供调用方在进程退出前等待
        self._background_tasks: set[asyncio.Task] = set()

    # ═══════════════════════════════════════════════════════════
    # 公共接口
    # ═══════════════════════════════════════════════════════════

    async def crawl_sources(
        self,
        source_url: str | None = None,
        source_type: str | None = None,
    ) -> CrawlResultSummary:
        """遍历所有（或指定）数据源，执行全量爬取 + AI 智能分析管线。

        Args:
            source_url: 可选，指定 URL 以仅爬取匹配的来源。
            source_type: 可选，指定类型以仅爬取匹配的来源。

        Returns:
            CrawlResultSummary: 爬取结果汇总。
        """
        sources = self._get_sources(source_url, source_type)
        if not sources:
            logger.info("没有匹配的数据源: url=%s type=%s", source_url, source_type)
            return CrawlResultSummary()

        result = CrawlResultSummary()

        for source in sources:
            try:
                crawler = crawler_factory(source)
                raw_items = await crawler.crawl()

                # ── 预去重：过滤已在库中的条目（避免重复 AI 判定 + 详情抓取）──
                # 每周执行时，列表里绝大多数是已入库/已判定过的，只有少数是新条。
                # 在 AI 判定前用列表页数据（标准号/文号/标题）与 Bitable 已有记录比对，
                # 已在库的直接跳过，只对真正的新增做后续 AI 相关性判定 + 详情抓取。
                if raw_items:
                    raw_items = await self._prefilter_known_items(raw_items)

                # ── 批量分类+评估（合并 classify_content + assess_relevance）──
                # 将逐条的 2 次 AI 调用合并为 1 次批量调用（仅对预去重后的新条目）
                if raw_items:
                    await self._batch_classify_and_assess(raw_items, result)

                for raw_item in raw_items:
                    result.crawled_count += 1
                    await self._process_item(raw_item, result, source)

                await asyncio.sleep(source.rate_limit_seconds)

            except Exception:
                logger.exception("数据源爬取异常: %s", source.name)
                result.errors.append(f"source:{source.name}")

        # 有新增或删除时发送通知
        if result.new_count > 0 or result.deleted_count > 0:
            await self._notify(result)

        return result

    async def process_changedetection_webhook(
        self,
        body: ChangeDetectionWebhookRequest,
    ) -> CrawlResultSummary | None:
        """处理 changedetection.io 的变更通知。

        流程：验证实质性变更 → 内容分类 → AI 提取法规 → AI 评估 → 写 Bitable → 返回摘要。
        如果不是实质性变更或非法规内容，返回 None。
        """
        from app.modules.safety.ai_audit import ai_audit_scope

        # 审计归因：整个 webhook 处理共享一个 trace（内部逐条 _process_item 的
        # scope 嵌套继承 trace_id），AI 调用落 scenario="regulation_crawl"
        with ai_audit_scope(
            scenario="regulation_crawl",
            channel="system",
            extra={"entry": "webhook", "url": body.watch_url},
        ):
            return await self._process_changedetection_webhook_inner(body)

    async def _process_changedetection_webhook_inner(
        self,
        body: ChangeDetectionWebhookRequest,
    ) -> CrawlResultSummary | None:
        """process_changedetection_webhook 的实现体（由外层套审计作用域）。"""
        # 1. 检查是否为实质性变更
        if not self._is_substantive_change(body.diff):
            logger.info(
                "非实质性变更 (diff=%d chars)，跳过: %s",
                len(body.diff), body.watch_url,
            )
            return None

        logger.info(
            "收到实质性变更: url=%s title=%s tag=%s diff_len=%d",
            body.watch_url, body.watch_title, body.source_tag, len(body.diff),
        )

        # 2. 内容分类
        content = body.current_snapshot or body.diff
        content_type = await self.extractor.classify_content(content, body.watch_url)
        if content_type != "regulation":
            logger.info(
                "非法规内容 (type=%s)，跳过: %s", content_type, body.watch_url,
            )
            return CrawlResultSummary(crawled_count=1, filtered_count=1)

        # 3. AI 批量提取法规
        source_type = body.source_tag or "webhook"
        items = await self.extractor.extract_batch(
            raw_text=content,
            source_url=body.watch_url,
            source_type=source_type,
        )

        if not items:
            logger.info("Webhook 内容未提取到法规: %s", body.watch_url)
            return CrawlResultSummary(crawled_count=1, new_count=0)

        # 4. AI 管线 + 写入（含附件下载）
        # 根据 source_tag 匹配 RegulationSource，获取 attachment_selector
        webhook_source = None
        source_type = body.source_tag or ""
        if source_type:
            for s in DEFAULT_SOURCES:
                if s.source_type == source_type:
                    webhook_source = s
                    break

        result = CrawlResultSummary()
        for item in items:
            result.crawled_count += 1
            await self._process_item(item, result, webhook_source)

        # 5. 通知
        if result.new_count > 0 or result.deleted_count > 0:
            await self._notify(result)

        return result

    # ═══════════════════════════════════════════════════════════
    # AI 管线（核心）
    # ═══════════════════════════════════════════════════════════

    async def _batch_classify_and_assess(
        self,
        items: list[CrawledRegulation],
        result: CrawlResultSummary,
    ) -> None:
        """批量分类+评估：将逐条的 classify_content + assess_relevance 合并为批量调用。

        成功时原地填充 item.content_type / impact_level / business_domains /
        relevance_score / core_summary。失败时静默降级——逐条 _process_item 会执行
        单独的 classify+assess 作为回退。
        """
        if not items:
            return

        batch_inputs: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            classify_input = (
                item.raw_text
                if (item.raw_text and len(item.raw_text.strip()) >= 50)
                else f"标题: {item.title}\n来源: {item.source_url}"
            )
            batch_inputs.append({
                "index": idx,
                "title": item.title or "",
                "source_url": item.source_url or "",
                "raw_text": classify_input or "",
            })

        try:
            batch_results = await self.extractor.classify_and_assess_batch(batch_inputs)
        except Exception:
            logger.exception("批量分类+评估失败，逐条回退")
            return

        if not batch_results:
            return

        result_map: dict[int, dict[str, Any]] = {
            r["index"]: r for r in batch_results if "index" in r
        }
        saved_calls = 0
        for idx, item in enumerate(items):
            br = result_map.get(idx)
            if br is None:
                continue
            saved_calls += 1

            # 分类结果
            ct = (br.get("content_type") or "regulation").strip()
            if ct not in ("regulation", "news", "speech", "other"):
                ct = "regulation"
            item.content_type = ct
            if ct != "regulation":
                result.filtered_count += 1
                result.items.append(CrawlItemResult(
                    title=item.title, status="filtered",
                ))
                continue

            # 评估结果
            impact = (br.get("impact_level") or "").strip()
            if impact in ("高", "中", "低"):
                item.impact_level = impact
            domains = br.get("business_domains")
            if isinstance(domains, list):
                item.business_domains = [d.strip() for d in domains if d and isinstance(d, str)]
            score = br.get("relevance_score")
            if isinstance(score, (int, float)):
                item.relevance_score = float(score)
            summary = (br.get("core_summary") or "").strip()
            if summary:
                item.core_summary = summary

        if saved_calls:
            logger.info(
                "batch classify+assess: filled %d/%d items (saved %d individual AI calls)",
                saved_calls, len(items), saved_calls * 2,
            )

    # ═══════════════════════════════════════════════════════════
    # 预去重（在 AI 判定前过滤已在库中的条目）
    # ═══════════════════════════════════════════════════════════

    async def _prefilter_known_items(
        self, items: list[CrawledRegulation],
    ) -> list[CrawledRegulation]:
        """在 AI 判定前过滤已在库中的条目，避免重复判定 + 重复抓详情。

        依据列表页数据（标准号/文号/标题）与 Bitable 已有记录比对：
          - 同标准号且同年份 / 完全相同标题 / 文号命中 → 已入库（duplicate），跳过；
          - 同标准号但不同年份（新版）→ 保留（走 update 替换旧版）；
          - 全新 → 保留（走 AI 相关性判定 + 详情抓取 + 写入）。

        这样每周执行只对真正的新增条目做 AI 判定，大多数早已判定过的直接跳过。
        """
        try:
            keys = await self._load_existing_standard_keys()
        except Exception:
            logger.exception("加载已有标准键失败，本次跳过预去重")
            return items
        kept: list[CrawledRegulation] = []
        skipped = 0
        for item in items:
            if self._is_known_duplicate(item, keys):
                skipped += 1
                continue
            kept.append(item)
        if skipped:
            logger.info(
                "预去重：跳过已在库中 %d 条，剩 %d 条待判定",
                skipped, len(kept),
            )
        return kept

    async def _load_existing_standard_keys(self) -> dict[str, Any]:
        """加载 Bitable 已有记录的标准号/文号/标题集合（单次 list_all_records）。"""
        from app.modules.safety.regulation_crawler.writer.bitable_writer import (
            _extract_document_number,
            _extract_plain_text,
            _extract_standard_identifier,
            _normalize_title,
        )

        # 法规标准分家（安全/环保双表）：预去重需覆盖两张表
        records: list[dict[str, Any]] = []
        for client in (self.writer.safety_bitable, self.writer.env_bitable):
            records.extend(await client.list_all_records(page_size=500))
        exact_titles: set[str] = set()
        norm_titles: set[str] = set()
        std_to_years: dict[str, set[str]] = {}
        doc_numbers: set[str] = set()
        for rec in records:
            fields = rec.get("fields", {}) or {}
            title = _extract_plain_text(fields.get("法律法规及标准名称")).strip()
            if not title:
                continue
            exact_titles.add(title)
            nt = _normalize_title(title)
            if nt:
                norm_titles.add(nt)
            std, year = _extract_standard_identifier(title)
            if std:
                std_to_years.setdefault(std, set()).add(year)
            doc = _extract_document_number(title)
            if doc:
                doc_numbers.add(doc)
        return {
            "exact_titles": exact_titles,
            "norm_titles": norm_titles,
            "std_to_years": std_to_years,
            "doc_numbers": doc_numbers,
        }

    @staticmethod
    def _is_known_duplicate(item: CrawledRegulation, keys: dict[str, Any]) -> bool:
        """判断条目是否已在库中（依据标准号/文号/标题）。True=已入库，应跳过。"""
        from app.modules.safety.regulation_crawler.writer.bitable_writer import (
            _extract_document_number,
            _extract_standard_identifier,
            _normalize_title,
        )

        title = (item.title or "").strip()
        if not title:
            return False
        # ① 标题精确 / 归一化匹配
        if title in keys["exact_titles"]:
            return True
        if _normalize_title(title) in keys["norm_titles"]:
            return True
        # ② 标准号：同年份=重复；不同年份=新版（保留，走 update）
        std, year = _extract_standard_identifier(title)
        if std and std in keys["std_to_years"]:
            if year in keys["std_to_years"][std]:
                return True
            return False  # 同标准号不同年份 → 新版，保留判定
        # ③ 文号匹配
        doc = _extract_document_number(title)
        if doc and doc in keys["doc_numbers"]:
            return True
        return False

    async def _process_item(
        self,
        item: CrawledRegulation,
        result: CrawlResultSummary,
        source: RegulationSource | None = None,
    ) -> Any:
        """完整的 AI 处理管线：分类→评估→对比→附件→写入。

        审计归因：每条法规一个 scope（webhook 入口下嵌套继承其 trace；
        定时爬取入口下则各自独立 trace）。
        """
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="regulation_crawl",
            channel="system",
            extra={"title": (item.title or "")[:100]},
        ):
            return await self._process_item_inner(item, result, source)

    async def _process_item_inner(
        self,
        item: CrawledRegulation,
        result: CrawlResultSummary,
        source: RegulationSource | None = None,
    ) -> None:
        """_process_item 的实现体（由外层套审计作用域）。"""

        # ── 快照：爬取层解析的权威日期（在 AI 元数据补全之前） ──
        # recency 过滤必须基于来源列表页/爬虫解析出的日期，避免被 AI 补全覆盖成错误值
        # （samr 等来源的「查看详细」是按钮，source_url 曾指向列表页，AI 提取的日期严重失真）。
        crawl_pub_date = item.publish_date
        crawl_impl_date = item.implementation_date

        # ── ① 内容类型判定（策略层黑名单 + AI 分类双重过滤） ──
        if not item.content_type:
            # raw_text 不足时用标题 + 来源构造最小分类输入
            classify_input = (
                item.raw_text
                if (item.raw_text and len(item.raw_text.strip()) >= 50)
                else f"标题: {item.title}\n来源: {item.source_url}"
            )
            try:
                ct = await self.extractor.classify_content(classify_input, item.source_url)
                item.content_type = ct
                if ct != "regulation":
                    logger.info("内容过滤 (type=%s): %s", ct, item.title)
                    result.filtered_count += 1
                    result.items.append(CrawlItemResult(
                        title=item.title, status="filtered",
                    ))
                    return
            except Exception:
                # AI 分类失败不阻塞，降级通过（策略层已做黑名单过滤）
                logger.warning("AI 内容分类失败，降级通过: %s", item.title)
                item.content_type = "regulation"

        # ── ② AI 相关性评估（影响等级 + 业务领域 + 摘要 + 建议） ──
        # 批量处理已完成的跳过此步
        if item.impact_level is None:
            try:
                await self.extractor.assess_relevance(item)
            except Exception:
                logger.exception("相关性评估异常: %s", item.title)
            # 评估失败不阻塞流程，使用默认值继续

        # ── ②.5 行业相关性 AI 终判（管线第 2 步：AI 判断是否符合行业 ──
        # 全源强制 force_ai（不再依赖 source_type 白名单）：Layer 1/2 的粗粒度
        # 关键词/业务域匹配会把"船舶排气烟度""核安全文化建设""海洋倾倒监控"
        # 等误放行（AI 粗评估都给"环境保护"域），必须逐条 AI 终判。
        # 成本：每条 1 次轻量判定（~500 tok），换取行业无关零入库。
        try:
            is_relevant = await self._check_industry_relevance(
                item.title,
                summary=item.core_summary or "",
                business_domains=None,
                force_ai=True,
                relevance_score=item.relevance_score,
                impact_level=item.impact_level,
            )
        except Exception:
            logger.exception("行业相关性 AI 判定异常，按不相关处理: %s", item.title)
            is_relevant = False
        if not is_relevant:
            logger.info("行业无关过滤（AI 终判）: %s", item.title)
            item.content_type = "irrelevant_industry"
            result.filtered_count += 1
            result.items.append(CrawlItemResult(
                title=item.title, status="filtered",
                error="行业无关（AI 终判）",
            ))
            return

        # ── ③ 新旧法规对比（检测修订/替代关键词） ──
        if self.extractor.has_revision_indicator(item.title):
            try:
                old = await self._find_old_version(item.title)
                if old:
                    await self.extractor.compare_with_previous(
                        item,
                        old_title=old.get("title", ""),
                        old_publish_date=old.get("publish_date", ""),
                        old_summary=old.get("summary", ""),
                    )
            except Exception:
                logger.exception("法规对比异常: %s", item.title)

        # ── ③.9 recency 兜底过滤（提前到详情抓取之前）──
        # 用列表页快照日期判定，避免为已判定过的老标准抓详情页 + 跑 AI 元数据补全。
        # 豁免：状态含"已废止"的条目必须放行，否则无法触发 Bitable 旧记录删除。
        # 无日期（None）暂不拦截——列表页无日期时由 ③.9b 复审用 AI 补全日期终判。
        _recency_snapshot = self._is_recent(item, crawl_pub_date, crawl_impl_date)
        if _recency_snapshot is False and not _is_repeal_or_revision(item):
            logger.info(
                "recency 过滤（发布日期过老）: pub=%s impl=%s title=%s",
                crawl_pub_date, crawl_impl_date, item.title,
            )
            result.filtered_count += 1
            result.items.append(CrawlItemResult(
                title=item.title, status="filtered",
                error="发布日期过老，非新发布法规",
            ))
            return

        # ── ③.4 详情页预取 + AI 元数据补全（不下载文件） ──
        # 提前执行以便 ③.7/③.8/③.9 的过滤基于补全后的元数据；
        # 附件文件下载推迟到全部过滤 + 入库预检通过之后（③.5），避免孤儿文件。
        detail_html: str | None = None
        if source:
            try:
                detail_html = await self._prepare_attachment(item, source)
            except Exception:
                logger.exception("详情页预取异常: %s", item.title)
                detail_html = None

        # ── ③.7 行业无关二次过滤（AI 元数据补全后可能标记）──
        if item.content_type == "irrelevant_industry":
            logger.info("行业无关过滤: %s", item.title)
            result.filtered_count += 1
            result.items.append(CrawlItemResult(
                title=item.title, status="filtered",
            ))
            return

        # ── ③.9b 时效复审（AI 元数据补全后，管线第 2 步收尾）──
        # 快照日期缺失（None 被前置放行）的条目，用 AI 从详情页补全的日期终判：
        # 超窗口或无法核实 → 拦截。防止无日期标准在 AI 补日期后仍把老标准当新增。
        _recency_refined = self._is_recent(item)
        if _recency_refined is not True and not _is_repeal_or_revision(item):
            logger.info(
                "时效复审过滤（AI 补全日期超窗口/无法核实）: pub=%s impl=%s title=%s",
                item.publish_date, item.implementation_date, item.title,
            )
            result.filtered_count += 1
            result.items.append(CrawlItemResult(
                title=item.title, status="filtered",
                error="时效复审未通过（发布超 1 年或日期不可核实）",
            ))
            return

        # ── ③.9c 标准源标准号检查（无标准号 → 无法确认规格/新旧，不入库）──
        # openstd/hbba/mee_std 这类标准目录源的标准必须带标准号
        # （如 GB xxx-2026 / HJ xxx-2024），空标准号说明列表页只抓到残缺名称
        # （如"电子衡器安全要求"），详情 AI 也未补全——无法确认是哪版标准，拦截。
        if item.source_type in ("samr_hbba", "samr_openstd", "mee_std") and not item.document_number:
            logger.info(
                "标准号缺失过滤: title=%s document_number=%s",
                item.title, item.document_number,
            )
            result.filtered_count += 1
            result.items.append(CrawlItemResult(
                title=item.title, status="filtered",
                error="标准目录源条目缺少标准号，无法确认规格",
            ))
            return

        # ── ③.8 元数据完整性检查 ──
        # 至少需要颁发机关 + (发布日期或实施日期之一)
        has_authority = bool(item.issuing_authority)
        has_pub_date = bool(item.publish_date)
        has_impl_date = bool(item.implementation_date)

        if not has_authority or (not has_pub_date and not has_impl_date):
            missing = []
            if not has_authority:
                missing.append("颁发机关")
            if not has_pub_date and not has_impl_date:
                missing.append("发布日期/实施日期")
            logger.warning(
                "元数据严重缺失，跳过写入: title=%s missing=%s",
                item.title, missing,
            )
            result.filtered_count += 1
            result.items.append(CrawlItemResult(
                title=item.title, status="filtered",
                error=f"元数据不完整: {', '.join(missing)}",
            ))
            return

        if not has_pub_date or not has_impl_date:
            missing_detail = []
            if not has_pub_date:
                missing_detail.append("发布日期")
            if not has_impl_date:
                missing_detail.append("实施日期")
            logger.info(
                "元数据轻度缺失（仍写入）: title=%s missing=%s",
                item.title, missing_detail,
            )

        # ── ③.9.5 入库预检：确认条目最终会写入 Bitable 后再下载附件 ──
        # duplicate → 直接跳过（不下载、不写入）；error → 交由写入层兜底重试。
        is_repealed = bool(
            item.status and any(kw in item.status for kw in ("废止", "作废", "失效"))
        )
        if not is_repealed:
            try:
                preflight = await self.writer.preflight_check(item)
            except Exception:
                logger.warning("入库预检异常，按可写入处理: %s", item.title)
                preflight = "new"
            if preflight == "duplicate":
                logger.info("预检重复，跳过（不下载附件）: %s", item.title[:80])
                result.skipped_duplicate += 1
                return
            if preflight == "repealed":
                is_repealed = True

        # ── ③.5 附件下载 + 上传 Feishu Drive（仅通过全部过滤 + 预检的条目） ──
        # 废止/失效条目不需要附件（仅触发 Bitable 旧记录删除），跳过下载。
        if source and not is_repealed:
            try:
                await self._download_upload_attachment(item, source, detail_html)
                if source.attachment_selector and not item.attachment_file_token:
                    result.attachment_failed_count += 1
                    logger.info(
                        "附件下载未成功 (selector=%s): %s",
                        source.attachment_selector, item.title,
                    )
            except Exception:
                result.attachment_failed_count += 1
                logger.exception("附件处理异常: %s", item.title)
                # 附件失败不阻塞流程

        # ── ④ 写入 Bitable ──
        try:
            write_result = await self.writer.write_regulation(item)
            if write_result:
                action = write_result.get("action", "created")
                if action == "deleted":
                    # 已废止且实际删除了 Bitable 记录 → 计入废止
                    result.deleted_count += 1
                    result.items.append(CrawlItemResult(
                        title=item.title,
                        impact_level=item.impact_level,
                        status="deleted",
                    ))
                else:
                    result.new_count += 1
                    if action == "updated":
                        result.deleted_count += 1  # 更新流程中旧记录已删除
                    result.items.append(CrawlItemResult(
                        title=item.title,
                        impact_level=item.impact_level,
                        bitable_record_id=write_result["record_id"],
                        bitable_shared_url=write_result.get("shared_url", ""),
                        status="created",
                        action=action,
                        core_summary=item.core_summary,
                        comparison_summary=item.comparison_summary,
                    ))
                    # ── ⑤ 显式触发知识库同步（不依赖飞书 webhook）──
                    await self._sync_knowledge_article(write_result, item)
            else:
                # write_regulation 返回 None：重复/更新去重，或「已废止但无匹配记录可删」。
                # 后者说明该废止项此前已处理过，不再重复上报（按重复跳过）。
                result.skipped_duplicate += 1
        except Exception as e:
            logger.exception("写入 Bitable 失败: %s", item.title)
            result.errors.append(f"{item.title}: {e}")
            result.items.append(CrawlItemResult(
                title=item.title, status="error", error=str(e),
            ))

    # ═══════════════════════════════════════════════════════════
    # 知识库同步（步骤④：显式触发，不依赖 webhook）
    # ═══════════════════════════════════════════════════════════

    # ── recency 判定辅助 ──

    def _is_recent(
        self,
        item: CrawledRegulation,
        pub_date: str | None = None,
        impl_date: str | None = None,
    ) -> bool | None:
        """发布日期或实施日期任一落在 recency 窗口内 → 视为新法规。

        pub_date/impl_date 可选：优先使用调用方传入的爬取层快照日期
        （权威、未被 AI 元数据补全覆盖），避免标准来源的日期被失真覆盖后误判为近期。

        三态返回（2026-08-31 调整，配合管线 AI 补全后复审）：
        - True:  任一日期可解析且在 1 年窗口内（近期新法规）
        - False: 有可解析日期但全部超窗（或日期在窗口之前）
        - None:  无任何可解析日期（无法判定——列表页无日期）。
          前置阶段(③.9)放行，等待 AI 详情补全；复审阶段(③.9b)按不可核实拦截。
        """
        from datetime import date, datetime

        pub_date = pub_date if pub_date is not None else item.publish_date
        impl_date = impl_date if impl_date is not None else item.implementation_date
        today = date.today()

        any_date_parsed = False
        for ds in (pub_date, impl_date):
            ds = (ds or "").strip()
            if not ds:
                continue
            try:
                d = datetime.strptime(ds[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                for fmt in ("%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
                    try:
                        d = datetime.strptime(ds[:10], fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    continue
            any_date_parsed = True
            if (today - d).days / 365.25 <= _MAX_REGULATION_AGE_YEARS:
                return True

        if not any_date_parsed:
            # 两个日期都没有/无法解析 → 无法判定（由调用方决定放行或拦截至复审）
            return None
        return False

    async def _sync_knowledge_article(
        self, write_result: dict[str, Any], item: CrawledRegulation,
    ) -> None:
        """Bitable 写入成功后，显式触发 PostgreSQL 文章创建 + chunk 重建。

        不再依赖飞书 webhook 异步链路（drive.file.bitable_record_changed_v1），
        而是直接调用 knowledge_bitable_handler 的创建逻辑，确保：
        1. SafetyKnowledgeArticle 立即入库
        2. Chunk 重建 + Embedding 生成被调度
        3. RAG 缓存失效

        与 webhook 路径安全共存：_create_knowledge_from_bitable 内部有
        Redis INSERT 互斥锁（120s TTL）+ 幂等检查，重复调用不会产生双写。
        """
        try:
            from app.modules.safety.feishu.knowledge_bitable_handler import (
                _create_knowledge_from_bitable,
                _schedule_graph_rebuild,
            )
            from app.modules.safety.knowledge.chunk_service import (
                rebuild_article_chunks,
            )

            record_id = write_result["record_id"]
            bitable_fields = self.writer._map_fields(item)
            # 显式同步与写入同表（安全/环保按类别路由），否则事件回源会落错表
            bitable = self.writer._client_for(self.writer._map_category(item))

            article = await _create_knowledge_from_bitable(
                bitable, record_id, bitable_fields,
            )
            if article is not None:
                # 异步触发 chunk 重建（不阻塞主流程，但保留任务引用，
                # 供 wait_background_tasks 在手动脚本退出前等待完成）
                task = asyncio.create_task(
                    rebuild_article_chunks(article.id)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                # 触发图谱增量重建
                await _schedule_graph_rebuild()
                logger.info(
                    "知识库同步已触发: article_id=%s title=%s",
                    article.id, item.title,
                )
            else:
                logger.debug(
                    "知识库同步跳过（已存在或锁冲突）: title=%s", item.title,
                )
        except Exception:
            logger.exception("知识库同步异常: title=%s", item.title)
            # 同步失败不阻塞爬虫主流程

    async def wait_background_tasks(self) -> None:
        """等待所有 fire-and-forget 后台任务（chunk 重建）完成。

        手动脚本进程退出会取消未完成的任务并回滚其事务，
        导致文章入库但 chunks 缺失；退出前必须调用本方法。
        """
        if not self._background_tasks:
            return
        logger.info("等待 %d 个后台 chunk 重建任务完成...", len(self._background_tasks))
        await asyncio.gather(*list(self._background_tasks), return_exceptions=True)

    # ═══════════════════════════════════════════════════════════
    # 内部辅助
    # ═══════════════════════════════════════════════════════════

    async def _find_old_version(self, title: str) -> dict[str, str] | None:
        """在 Bitable 中查找可能的旧版法规（用于对比）。"""
        try:
            # 使用模糊匹配查找
            from app.modules.safety.regulation_crawler.writer.bitable_writer import (
                _normalize_title,
            )

            norm = _normalize_title(title)
            if len(norm) < 4:
                return None

            records: list[dict[str, Any]] = []
            for client in (self.writer.safety_bitable, self.writer.env_bitable):
                records.extend(await client.list_all_records(page_size=100))
            best_match: dict[str, str] | None = None
            best_score = 0

            for record in records:
                fields = record.get("fields", {})
                existing = fields.get("法律法规及标准名称", "")
                if not existing:
                    continue
                existing_norm = _normalize_title(existing)
                if len(existing_norm) < 4:
                    continue

                # 归一化后有一个包含另一个 → 可能相关
                if norm in existing_norm or existing_norm in norm:
                    score = len(existing_norm)
                    if score > best_score:
                        best_score = score
                        best_match = {
                            "title": existing,
                            "publish_date": str(fields.get("颁布修订日期", "")),
                            "summary": str(fields.get("核心要点总结", "")),
                        }

            if best_match:
                logger.info("找到旧版法规: new=%s old=%s", title, best_match["title"])
            return best_match

        except Exception:
            logger.exception("查找旧版法规失败: title=%s", title)
            return None

    # ═══════════════════════════════════════════════════════════
    # 附件处理（V1.2）
    # ═══════════════════════════════════════════════════════════

    async def _prepare_attachment(
        self, item: CrawledRegulation, source: RegulationSource,
    ) -> str | None:
        """附件预取阶段（Phase A，不落盘）：获取详情页 + AI 元数据补全。

        在 ③.7/③.8/③.9 过滤之前执行，让过滤基于补全后的元数据；
        不下载任何文件，附件文件下载推迟到「确认入库后」的
        _download_upload_attachment（Phase B），避免被过滤条目留下孤儿文件。
        返回详情页正文（供 Phase B 的渲染/TXT 回退使用），失败返回 None。
        """
        if not item.source_url:
            logger.debug("附件预取跳过（无 source_url）: %s", item.title)
            return None

        logger.info("[附件 1/3] 获取详情页: %s", item.title[:60])
        detail_html = await self._enrich_detail_page(item, source)
        if detail_html:
            logger.info(
                "[附件 1/3] 详情页获取成功 (%d 字符): %s",
                len(detail_html), item.title[:60],
            )
        else:
            logger.warning("[附件 1/3] 详情页获取失败: %s", item.title[:60])

        # AI 补全元数据（法规名称、颁发机关、实施日期等）—— 不依赖本地文件
        if detail_html:
            await self._enrich_metadata_from_detail(item, source, detail_html)

        return detail_html

    async def _download_upload_attachment(
        self,
        item: CrawledRegulation,
        source: RegulationSource,
        detail_html: str | None,
    ) -> None:
        """附件下载 + 上传阶段（Phase B，仅对确认入库的条目执行）。

        下载主附件/额外附件 → 原文待补检测 → Playwright/TXT 回退 → 上传 Feishu Drive。
        全程 best-effort，失败不阻塞主流程。
        """
        # 2. 尝试下载附件（如果有 URL）
        if item.attachment_url and not item.attachment_path:
            logger.info("[附件 2/3] 尝试下载附件: url=%s", item.attachment_url[:120])
            await self._download_attachment(item, source)
            if item.attachment_path:
                logger.info("[附件 2/3] 附件下载成功: %s", item.title[:60])
            else:
                logger.warning("[附件 2/3] 附件下载失败: %s", item.title[:60])
        elif not item.attachment_url:
            logger.info("[附件 2/3] 页面无直接附件链接，跳过下载: %s", item.title[:60])

        # 2.5 下载额外附件（多附件公告，如附件1/附件2）
        for extra in item.extra_attachments:
            if extra.get("path"):
                continue
            res = await self._download_attachment_file(
                url=extra.get("url", ""),
                name=extra.get("name", "附件.pdf"),
                referer=item.source_url,
                source=source,
                title=item.title,
            )
            if res:
                extra["path"], extra["name"] = res
                local_size = 0
                if extra["path"]:
                    _local = resolve_local_path(extra["path"])
                    if _local is not None:
                        try:
                            local_size = os.path.getsize(_local)
                        except OSError:
                            pass
                logger.info(
                    "[附件 2.5/3] 额外附件下载成功: name=%s size=%d",
                    extra["name"], local_size,
                )
            else:
                logger.warning("[附件 2.5/3] 额外附件下载失败: name=%s", extra.get("name"))

        # 2.6 行业无关早停（防御：③.7 已过滤，此处兜底避免残留飞书文件）
        if item.content_type == "irrelevant_industry":
            logger.info("[附件] 行业无关，跳过渲染/上传: %s", item.title[:60])
            return

        # 3.4 openstd 官方 PDF 直下：网页「下载标准」= showGb 中间页 → viewGb 文件流，
        #     会话 cookie 三步可拿到免费官方原文，先于「原文待补」检测尝试
        if (not item.attachment_path and source.source_type == "samr_openstd"
                and item.source_url):
            await self._try_openstd_download(item)

        # 3.5 原文待补检测：无真实附件时，若详情页是标准发布公告 / JS 壳信息页，
        #     则禁止渲染为伪原文，标记待补原因写入 Bitable 备注
        pending_reason = None
        if not item.attachment_path:
            pending_reason = self._detect_pending_origin(item, source, detail_html or "")
            if pending_reason:
                item.attachment_pending_reason = pending_reason
                logger.warning(
                    "[附件 3.5/3] 原文待补（不渲染伪原文）: %s 原因=%s",
                    item.title[:60], pending_reason,
                )

        # 4. 仅 gov_cn / mem / mem_standards / mee 的详情页回退到 Playwright PDF 渲染
        #    这些来源的 source_url 指向法规正文文章页，渲染 PDF 有实际价值。
        #    SAMR/NHC/NMPA 的 URL 是目录/搜索页或数据库详情页，
        #    Playwright 渲染出来只是网页截图，不是法规原件，故跳过。
        if (not item.attachment_path and not pending_reason
                and source.source_type in ("gov_cn", "mem", "mem_standards", "mee", "samr_hbba", "samr_openstd")):
            logger.info("[附件 3/3] Playwright PDF 渲染回退: %s", item.title[:60])
            await self._render_page_pdf(item, source)
            if item.attachment_path:
                logger.info("[附件 3/3] Playwright PDF 渲染成功: %s", item.title[:60])
            else:
                logger.warning("[附件 3/3] Playwright PDF 渲染失败: %s", item.title[:60])

        # 4.5 最终回退：Playwright 也失败时，保存 HTML 正文为 .txt 上传
        if not item.attachment_path and detail_html and not pending_reason:
            logger.info("[附件 3.5/3] TXT 正文回退: %s", item.title[:60])
            await self._save_body_text(item, source, detail_html)
            if item.attachment_path:
                logger.info("[附件 3.5/3] TXT 正文保存成功: %s", item.title[:60])

        if not item.attachment_path and pending_reason:
            logger.warning("[附件] 原文待补（跳过伪原文上传）: %s", item.title[:60])
            return

        if not item.attachment_path:
            logger.warning("[附件] 最终无附件（所有路径均失败）: %s", item.title[:60])
            return

        # 5. 上传到飞书 Drive（需要本地文件）
        # 分家后 BitableWriter 无单例 client，按类别路由（Drive 凭证一致）
        drive_client = self.writer._client_for(self.writer._map_category(item))
        logger.info("[附件 4/3] 上传到飞书 Drive: %s", item.title[:60])
        for upload_attempt in range(3):
            try:
                result = await drive_client.upload_media(
                    file_path=item.attachment_path,
                    file_name=item.attachment_name or "regulation.pdf",
                )
                if result:
                    item.attachment_file_token = result["file_token"]
                    logger.info(
                        "[附件 4/3] 上传成功: title=%s file_token=%s",
                        item.title, item.attachment_file_token,
                    )
                    break
                else:
                    logger.warning(
                        "[附件 4/3] 上传返回空 (attempt %d/3): %s",
                        upload_attempt + 1, item.title,
                    )
            except Exception:
                logger.exception(
                    "[附件 4/3] 上传异常 (attempt %d/3): %s",
                    upload_attempt + 1, item.title,
                )
        else:
            logger.error("[附件 4/3] 上传全部重试失败: %s", item.title)

        # 5.5 上传额外附件（多附件公告，如附件1/附件2）到飞书 Drive
        for extra in item.extra_attachments:
            extra_path = extra.get("path")
            if not extra_path or extra.get("file_token"):
                continue
            try:
                result = await drive_client.upload_media(
                    file_path=extra_path,
                    file_name=extra.get("name") or "附件.pdf",
                )
                if result:
                    extra["file_token"] = result["file_token"]
                    logger.info(
                        "[附件 5.5/3] 额外附件上传成功: title=%s name=%s file_token=%s",
                        item.title, extra.get("name"), extra["file_token"],
                    )
                else:
                    logger.warning(
                        "[附件 5.5/3] 额外附件上传返回空: title=%s name=%s",
                        item.title, extra.get("name"),
                    )
            except Exception:
                logger.exception(
                    "[附件 5.5/3] 额外附件上传异常: title=%s name=%s",
                    item.title, extra.get("name"),
                )

    async def _enrich_detail_page(
        self, item: CrawledRegulation, source: RegulationSource,
    ) -> str | None:
        """获取详情页 HTML，提取附件下载链接和正文文本。

        gov_cn 等政府网站有反爬机制，使用增强的浏览器伪装 header。
        返回详情页 body 文本（供后续 AI 元数据提取），失败时返回 None。
        """
        from app.modules.safety.regulation_crawler.engine.strategies import (
            HttpParseCrawler,
        )

        try:
            # 构造一个临时 crawler 实例来复用 fetch_page
            crawler = HttpParseCrawler(source)
            # gov.cn 反爬增强：使用更强的浏览器伪装
            if source.source_type in ("gov_cn", "mem", "mem_standards", "mee", "samr_hbba", "samr_openstd"):
                crawler._headers.update({
                    "Referer": "https://www.gov.cn/",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                })
            html = await crawler.fetch_page(item.source_url, timeout=30.0)
        except Exception:
            logger.warning(
                "详情页 httpx 获取失败（将尝试 Playwright 回退）: %s src=%s",
                item.source_url, source.source_type,
            )
            html = None

        # playwright 策略来源（nhc/nmpa/samr）详情页常被 412 反爬拦截（httpx 无法执行 JS 挑战），
        # 回退到 Playwright 浏览器获取正文。
        if not html and source.strategy == "playwright":
            html = await self._fetch_detail_html_playwright(item, source)

        if not html:
            return None

        # ── 提取正文文本（供后续 AI 元数据提取）──
        detail_text: str | None = None
        try:
            detail_text = BeautifulSoup(html, "html.parser").get_text(
                separator="\n", strip=True,
            )
        except Exception:
            pass

        try:
            soup = BeautifulSoup(html, "html.parser")
            attachment_els: list[Any] = []

            # 优先级 1: source 配置的 selector
            if source.attachment_selector:
                attachment_els = soup.select(source.attachment_selector)
                if attachment_els:
                    logger.debug("附件 selector 命中: %s → %d 个链接", source.attachment_selector, len(attachment_els))

            # 优先级 2: 通用 PDF/DOC selector
            if not attachment_els:
                attachment_els = soup.select(
                    "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx']"
                )
                if attachment_els:
                    logger.debug("附件 selector 命中(P2 通用): %d 个链接", len(attachment_els))

            # 优先级 3: 关键词回退
            if not attachment_els:
                attachment_els = soup.select("a[href*='附件'], a[href*='下载']")
                if attachment_els:
                    logger.debug("附件 selector 命中(P3 关键词): %d 个链接", len(attachment_els))

            if not attachment_els:
                logger.info("详情页无附件链接（三优先级均未命中），将回退到 Playwright PDF 渲染: %s", item.title[:60])
                return detail_text

            # 收集全部匹配的附件链接（多附件公告，如附件1/附件2），主附件取第一个
            parsed: list[tuple[str, str]] = []  # (abs_url, name)
            for el in attachment_els:
                href = el.get("href", "")
                if not href:
                    continue
                abs_url = urljoin(item.source_url, href)
                name = (el.get_text(strip=True) or abs_url.split("/")[-1] or "附件").strip()
                # 确保文件名有合理的扩展名
                if "." not in name.rsplit("/", 1)[-1]:
                    ext = ".pdf"
                    for ext_candidate in [".pdf", ".doc", ".docx"]:
                        if abs_url.lower().endswith(ext_candidate):
                            ext = ext_candidate
                            break
                    name = f"{name}{ext}"
                parsed.append((abs_url, name))

            if not parsed:
                return detail_text

            # 第一个作为主附件，其余放入 extra_attachments
            # 若爬取层已设置附件 URL（如 hbba 的 portal 下载链接），不覆盖主附件
            if not item.attachment_url:
                item.attachment_url, item.attachment_name = parsed[0]
                extra_list = parsed[1:]
            else:
                extra_list = parsed
            # 额外附件按 URL 去重（避免与主附件重复）
            existing_urls = {item.attachment_url} if item.attachment_url else set()
            item.extra_attachments = []
            for url, name in extra_list:
                if url in existing_urls:
                    continue
                existing_urls.add(url)
                item.extra_attachments.append({"url": url, "name": name})
            logger.info(
                "命中附件: title=%s url=%s extras=%d",
                item.title, item.attachment_url or "", len(item.extra_attachments),
            )
        except Exception:
            logger.exception("详情页解析异常: %s", item.source_url)

        return detail_text

    async def _fetch_detail_html_playwright(
        self, item: CrawledRegulation, source: RegulationSource,
    ) -> str | None:
        """用 Playwright 获取详情页 HTML（nhc/nmpa/samr 等站点的 httpx 请求会 412）。

        412 反爬需浏览器执行 JS 挑战：首次 domcontentloaded 失败回退 commit，
        412 状态时重载一次。返回正文 HTML，失败返回 None。
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                    extra_http_headers={
                        "Accept": (
                            "text/html,application/xhtml+xml,application/xml;"
                            "q=0.9,image/webp,*/*;q=0.8"
                        ),
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                        "Referer": item.source_url or source.base_url,
                    },
                )
                page = await context.new_page()
                resp = None
                for wait_until in ("domcontentloaded", "commit"):
                    try:
                        resp = await page.goto(
                            item.source_url, wait_until=wait_until, timeout=30000,
                        )
                        break
                    except Exception:
                        continue
                if resp is not None and resp.status == 412:
                    await page.wait_for_timeout(2000)
                    try:
                        await page.goto(item.source_url, wait_until="commit", timeout=30000)
                    except Exception:
                        pass
                await page.wait_for_timeout(2000)
                html = await page.content()
                await context.close()
                await browser.close()
                if html and len(html) > 50:
                    logger.info(
                        "详情页 Playwright 获取成功 (%d 字符): %s",
                        len(html), item.title[:60],
                    )
                    return html
        except Exception:
            logger.warning("详情页 Playwright 获取失败: %s", item.title[:60])
        return None

    def _detect_pending_origin(
        self, item: CrawledRegulation, source: RegulationSource,
        detail_text: str,
    ) -> str | None:
        """检测详情页是否无法提供真实法规原文，返回待补原因（无则 None）。

        仅在无真实附件可下载（item.attachment_path 为空）时调用。触发场景：
        1. mee 标准发布公告：正文仅声明「标准内容可在…查询」，标准全文在正式发布文本中
           → 渲染公告页 / 保存正文 TXT 都不是法规原件，标记待补
        2. samr_openstd / samr_hbba：openstd/hbba 是 JS 在线预览壳（国家标准全文公开系统），
           标准全文仅可在线预览，暂无免费官方下载链接
           → 渲染 PDF 只是网页截图，标记待补
        """
        # openstd/hbba 是 JS 在线预览壳（标准全文公开系统），标准全文只能在线预览，
        # 渲染 PDF / 保存正文 TXT 都不是法规原件。即使详情页正文为空也一律标记待补，
        # 否则会落入 _save_body_text 的 TXT 存根（正文只是元数据页文字，非标准原文）。
        if source.source_type in ("samr_openstd", "samr_hbba"):
            return "原文待补：标准全文需通过国家标准全文公开系统(openstd)在线预览，暂无免费官方下载链接"

        if not detail_text:
            return None

        if source.source_type == "mee" and _is_standard_publish_announcement(detail_text):
            return "原文待补：公告仅声明标准发布，标准全文请以正式发布文本为准"

        return None

    # ═══════════════════════════════════════════════════════════
    # 元数据补全（从详情页 AI 提取）
    # ═══════════════════════════════════════════════════════════

    async def _enrich_metadata_from_detail(
        self, item: CrawledRegulation, source: RegulationSource,
        detail_html: str,
    ) -> None:
        """从详情页正文 AI 提取缺失的元数据字段。

        补全：法规名称（尤其批量公告中的具体标准名）、颁发机关、实施日期、文号等。
        仅当字段当前为空时才覆盖，不覆盖已有数据。
        失败不阻塞主流程。
        """
        # ── 提取正文文本 ──
        try:
            soup = BeautifulSoup(detail_html, "html.parser")
            body_text = soup.get_text(separator="\n", strip=True)
            # 去除空白行，合并为紧凑文本
            lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
            body_text = "\n".join(lines)
        except Exception:
            logger.warning("详情页正文提取失败: %s", item.title)
            return

        if not body_text or len(body_text) < 100:
            logger.info("详情页正文过短 (%d 字符)，尝试 PDF 回退: %s",
                        len(body_text) if body_text else 0, item.title)
            # 不 return——继续往下走，尝试从 PDF 附件提取文字

        # ── 检查哪些字段需要补全 ──
        needs_extraction = (
            item.issuing_authority is None
            or item.publish_date is None
            or item.implementation_date is None
            or item.document_number is None
            or item.regulation_level is None
            or item.status is None
        )
        # 批量公告检测：标题含"批准X项"、"发布X项"等
        is_batch = bool(
            item.title
            and (
                "批准" in item.title and "项" in item.title
                or "发布" in item.title and "项" in item.title
                or "等" in item.title and "项行业标准" in item.title
                or "等" in item.title and "项国家标准" in item.title
            )
        )

        if not needs_extraction and not is_batch:
            return  # 所有字段已有值且非批量公告，跳过

        # ── AI 提取 ──
        try:
            extracted = await self.extractor.extract_batch(
                raw_text=body_text[:8000],  # 截断到 8000 字符
                source_url=item.source_url,
                source_type=source.source_type,
            )
        except Exception:
            logger.exception("AI 元数据提取失败: %s", item.title)
            return

        if not extracted:
            # ── 回退：尝试从已下载的 PDF 附件直接提取文字 ──
            # 回读适配：attachment_path 可能是 MinIO key，物化到临时文件后解析
            if item.attachment_path:
                _local = resolve_local_path(item.attachment_path)
                _is_temp = _local is None
                local = materialize(item.attachment_path)
                if local is not None:
                    try:
                        import fitz

                        doc = fitz.open(str(local))
                        pdf_text = ""
                        for page in doc:
                            t = page.get_text()
                            if t and t.strip():
                                pdf_text += t + "\n"
                        doc.close()
                        if pdf_text.strip() and len(pdf_text.strip()) > 100:
                            logger.info("从 PDF 附件提取文字: %s (%d chars)", item.title, len(pdf_text))
                            extracted = await self.extractor.extract_batch(
                                raw_text=pdf_text[:8000],
                                source_url=item.source_url,
                                source_type=source.source_type,
                            )
                    except Exception:
                        pass
                    finally:
                        if _is_temp:
                            cleanup_temp(local)

        if not extracted:
            return

        first = extracted[0]

        # ── 标题将替换检测（提前计算，供行业相关性判定使用）──
        is_notice_format = bool(
            item.title and (
                "关于发布" in item.title
                or ("公告" in item.title and "批准" not in item.title and "项" not in item.title)
                or ("通知" in item.title and "关于印发" in item.title)
                or "令（第" in item.title  # 部令格式: "应急管理部令（第20号）"
                or "令(第" in item.title
            )
        )
        title_will_change = (is_batch or is_notice_format) and first.title and first.title != item.title

        # ── 后提取过滤：三层正向判定行业相关性 ──
        # ②.5 已在详情抓取前按列表页标题做过全源 AI 终判；此处仅当标题被替换
        # （批量公告 → 具体标准名）时用新标题终判一次，避免按公告名误判。
        force_ai = title_will_change
        if first.title:
            is_relevant = await self._check_industry_relevance(
                first.title,
                summary=first.core_summary or "",
                business_domains=None if force_ai else item.business_domains,
                force_ai=force_ai,
                relevance_score=item.relevance_score,
                impact_level=item.impact_level,
            )
            if not is_relevant:
                logger.info(
                    "行业相关性判定不通过，标记过滤: title=%s", first.title[:80],
                )
                item.content_type = "irrelevant_industry"
                return

        # ── 补全空字段（不覆盖已有数据） ──
        # 标题替换：以下格式的标题需替换为 AI 提取的法规名
        if title_will_change:
            logger.info(
                "法规名称替换: old=%s new=%s", item.title[:60], first.title[:100],
            )
            item.title = first.title

        # ── 补全空字段（AI 从详情页正文提取的值优先于列表页抓取值）──
        # 爬虫从列表页提取的日期是公告日期，AI 从详情页正文提取的才是法规颁布日期。
        # 因此 publish_date 允许 AI 覆盖已有值（只要 AI 返回了不同的值）。
        if item.issuing_authority is None and first.issuing_authority:
            item.issuing_authority = first.issuing_authority
            logger.info("补全颁布机关: %s → %s", item.title, first.issuing_authority)

        if first.publish_date:
            if item.publish_date is None:
                item.publish_date = first.publish_date
                logger.info("补全颁布日期: %s → %s", item.title, first.publish_date)
            elif item.publish_date != first.publish_date:
                logger.info(
                    "颁布日期覆盖（列表页=%s → 详情页AI=%s）: %s",
                    item.publish_date, first.publish_date, item.title[:60],
                )
                item.publish_date = first.publish_date

        if item.implementation_date is None and first.implementation_date:
            item.implementation_date = first.implementation_date
            logger.debug("补全实施日期: %s → %s", item.title, first.implementation_date)

        if item.document_number is None and first.document_number:
            item.document_number = first.document_number
            logger.debug("补全文号: %s → %s", item.title, first.document_number)

        if item.regulation_level is None and first.regulation_level:
            item.regulation_level = first.regulation_level

        if item.status is None and first.status:
            item.status = first.status

        # ── 正则兜底：AI 未补到的日期字段，从结构化详情页文本直接匹配 ──
        # openstd 等页面字段为「标签行 + 日期行」相邻结构（发布日期\n2025-10-31），
        # 偶发列表页日期列解析失败时由详情页兜住，避免元数据带空入库。
        if item.publish_date is None or item.implementation_date is None:
            fb_pub, fb_impl = self._fallback_detail_dates(body_text)
            if item.publish_date is None and fb_pub:
                item.publish_date = fb_pub
                logger.info("详情页正则兜底颁布日期: %s → %s", item.title, fb_pub)
            if item.implementation_date is None and fb_impl:
                item.implementation_date = fb_impl
                logger.info("详情页正则兜底实施日期: %s → %s", item.title, fb_impl)

        # ── 更新 raw_text 为更丰富的正文内容（改善后续 AI 评估质量）──
        if len(body_text) > len(item.raw_text or ""):
            item.raw_text = body_text[:3000]

    @staticmethod
    def _fallback_detail_dates(body_text: str) -> tuple[str | None, str | None]:
        """从结构化详情页文本提取 (发布日期, 实施日期)：标签行同行或次行匹配日期。"""
        date_re = _re.compile(r"20\d{2}-\d{2}-\d{2}")
        pub = impl = None
        lines = [ln.strip() for ln in (body_text or "").split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            pub_key = next((k for k in ("发布日期", "颁布日期") if k in ln), None)
            if pub is None and pub_key:
                seg = ln[ln.index(pub_key) + len(pub_key):]
                m = date_re.search(seg) or date_re.search(nxt)
                if m:
                    pub = m.group(0)
            if impl is None and "实施日期" in ln:
                seg = ln[ln.index("实施日期") + len("实施日期"):]
                m = date_re.search(seg) or date_re.search(nxt)
                if m:
                    impl = m.group(0)
            if pub and impl:
                break
        return pub, impl

    async def _try_openstd_download(self, item: CrawledRegulation) -> bool:
        """openstd 官方 PDF 三步下载（详情页建会话 → showGb 中间页 → viewGb 文件流）。

        网页「下载标准」按钮即此链路：showGb 中间页刷新会话 cookie 后，
        viewGb 以 attachment 流返回标准 PDF。成功则写入 item.attachment_path。
        """
        m = _re.search(r"hcno=([0-9A-Fa-f]+)", item.source_url or "")
        if not m:
            return False
        hcno = m.group(1)
        base = "https://openstd.samr.gov.cn"
        detail_url = f"{base}/bzgk/std/newGbInfo?hcno={hcno}"
        showgb_url = f"{base}/bzgk/std/showGb?type=download&hcno={hcno}&request_locale=zh"
        view_url = f"{base}/bzgk/std/viewGb?hcno={hcno}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": detail_url,
        }
        try:
            import httpx as _httpx

            async with _httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
                # 1. 详情页：建立 JSESSIONID 会话
                await http.get(detail_url, headers=headers)
                # 2. showGb 中间页：校验下载资格并刷新会话（viewGb 校验依赖其 cookie）
                resp2 = await http.get(showgb_url, headers=headers)
                if "viewGb" not in (resp2.text or ""):
                    logger.info(
                        "[附件 3.4/3] openstd showGb 未放行（可能需验证码）: %s",
                        item.title[:50],
                    )
                    return False
                # 3. viewGb 文件流（Referer 必须为 showGb 中间页）
                h3 = dict(headers)
                h3["Referer"] = showgb_url
                resp3 = await http.get(view_url, headers=h3)
                data = resp3.content or b""

            if not data.startswith(b"%PDF") or len(data) < 10240:
                logger.info(
                    "[附件 3.4/3] openstd 下载内容非有效 PDF (%d bytes): %s",
                    len(data), item.title[:50],
                )
                return False
            safe_title = _re.sub(r'[\\/*?:"<>|]', "", item.title or "regulation")[:80]
            item.attachment_path = store_bytes(
                "regulation",
                f"pdf_{uuid.uuid4().hex[:8]}_{safe_title}.pdf",
                data,
                content_type="application/pdf",
            )
            item.attachment_name = f"{safe_title}.pdf"
            logger.info(
                "[附件 3.4/3] openstd 官方 PDF 下载成功: %s (%d KB) → %s",
                item.title[:50], len(data) // 1024, item.attachment_path,
            )
            return True
        except Exception:
            logger.warning(
                "[附件 3.4/3] openstd 下载异常: %s", item.title[:60], exc_info=True,
            )
            return False

    async def _download_attachment_file(
        self,
        *,
        url: str,
        name: str,
        referer: str,
        source: RegulationSource,
        title: str,
    ) -> tuple[str, str] | None:
        """下载单个附件文件到统一存储（MinIO key / 本地 safety/regulation/）。

        Args:
            url: 附件直接下载链接
            name: 附件原始文件名
            referer: 来源页 URL（反爬 Referer）
            source: 来源配置（决定下载策略/UA）
            title: 法规标题（仅用于日志）

        Returns:
            (存储标识, 安全文件名) 或 None（下载/校验失败）
        """
        from app.modules.safety.regulation_crawler.engine.strategies import (
            HttpParseCrawler,
        )

        if not url:
            return None

        try:
            crawler = HttpParseCrawler(source)
            content = await crawler.download_file(
                url=url,
                referer=referer,
                timeout=120.0,
            )
        except Exception:
            logger.exception("附件下载异常: title=%s url=%s", title, url)
            return None

        if not content:
            return None

        # ── 文件类型验证：拒绝 HTML 页面和非文档格式 ──
        if not self._is_valid_document(content, name or ""):
            logger.warning(
                "附件类型无效，已丢弃: title=%s name=%s size=%d first_bytes=%s",
                title, name, len(content),
                content[:80].hex() if len(content) >= 4 else "N/A",
            )
            return None

        try:
            # 存储到统一存储（MinIO key / 本地相对路径 safety/regulation/）
            safe_name = name or "regulation.pdf"
            # 替换路径分隔符和危险字符
            safe_name = safe_name.replace("\\", "_").replace("/", "_")
            unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
            stored = store_bytes(
                "regulation",
                unique_name,
                content,
                content_type=_guess_document_content_type(unique_name),
            )
            logger.info(
                "附件已下载: title=%s path=%s size=%d",
                title, stored, len(content),
            )
            return stored, safe_name
        except Exception:
            logger.exception("附件保存异常: %s", title)
            return None

    async def _download_attachment(
        self, item: CrawledRegulation, source: RegulationSource,
    ) -> None:
        """下载主附件到统一存储（MinIO key / 本地相对路径）。"""
        res = await self._download_attachment_file(
            url=item.attachment_url or "",
            name=item.attachment_name or "regulation.pdf",
            referer=item.source_url,
            source=source,
            title=item.title,
        )
        if res:
            item.attachment_path, item.attachment_name = res

    async def _render_page_pdf(
        self, item: CrawledRegulation, source: RegulationSource,
    ) -> None:
        """gov.cn / mem 等页面无直接 PDF 链接时，使用 Playwright 渲染页面为 PDF。

        仅在 _enrich_detail_page 未找到 attachment_url 时调用。
        渲染前检查页面正文长度：若 < 2000 字符则视为目录/错误页，跳过渲染。
        支持最多 2 次重试（首次超时后放宽 timeout 重试）。
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright 未安装，跳过 PDF 渲染: %s", item.title)
            return

        last_error: str | None = None
        for attempt in range(2):
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                        locale="zh-CN",
                    )
                    page = await context.new_page()
                    try:
                        goto_timeout = 30000 if attempt == 0 else 60000
                        await page.goto(
                            item.source_url,
                            wait_until="networkidle",
                            timeout=goto_timeout,
                        )
                        await page.wait_for_timeout(1500)

                        # ── 页面正文长度检查：避免渲染目录/搜索/错误页 ──
                        # MEE 页面通常较短（法规公告正文简洁），阈值放宽到 500 字符
                        body_text = await page.evaluate(
                            "() => document.body?.innerText || ''"
                        )
                        body_text = (body_text or "").strip()
                        min_chars = 500 if source.source_type == "mee" else 2000
                        if len(body_text) < min_chars:
                            logger.warning(
                                "PDF 渲染跳过（页面正文过短 %d 字符 < %d，疑似目录/错误页）: %s",
                                len(body_text), min_chars, item.title,
                            )
                            return

                        content = await page.pdf(
                            format="A4",
                            print_background=True,
                            margin={
                                "top": "20mm", "bottom": "20mm",
                                "left": "15mm", "right": "15mm",
                            },
                        )
                    finally:
                        await context.close()
                        await browser.close()

                if not content or len(content) < 1000:
                    logger.warning("PDF 渲染内容过短 (%d bytes): %s", len(content) if content else 0, item.title)
                    return

                # 存储到统一存储（MinIO key / 本地相对路径）
                safe_title = _re.sub(r'[\\/*?:"<>|]', '', item.title or "regulation")[:80]
                unique_name = f"pdf_{uuid.uuid4().hex[:8]}_{safe_title}.pdf"
                item.attachment_path = store_bytes(
                    "regulation",
                    unique_name,
                    content,
                    content_type="application/pdf",
                )
                item.attachment_name = f"{safe_title}.pdf"
                logger.info(
                    "PDF 渲染成功: title=%s path=%s size=%d attempt=%d",
                    item.title, item.attachment_path, len(content), attempt + 1,
                )
                return  # 成功，直接返回

            except Exception as e:
                last_error = str(e)[:200]
                if attempt == 0:
                    logger.warning(
                        "PDF 渲染失败 (attempt 1/2)，将重试: title=%s error=%s",
                        item.title, last_error,
                    )
                else:
                    logger.error(
                        "PDF 渲染失败 (attempt 2/2): title=%s error=%s",
                        item.title, last_error,
                    )

    async def _save_body_text(
        self, item: CrawledRegulation, source: RegulationSource,
        detail_html: str,
    ) -> None:
        """最终回退：将详情页 HTML 正文保存为 .txt 文件并上传到飞书 Drive。

        当 PDF 渲染也失败时，至少保留法规文本，避免附件完全为空。
        """
        try:
            soup = BeautifulSoup(detail_html, "html.parser")
            body_text = soup.get_text(separator="\n", strip=True)
            lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
            clean_text = "\n".join(lines)

            if len(clean_text) < 200:
                logger.warning("TXT 回退正文过短 (%d 字符)，跳过: %s", len(clean_text), item.title)
                return

            safe_title = _re.sub(r'[\\/*?:"<>|]', '', item.title or "regulation")[:60]
            unique_name = f"txt_{uuid.uuid4().hex[:8]}_{safe_title}.txt"
            item.attachment_path = store_bytes(
                "regulation",
                unique_name,
                clean_text.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
            )
            item.attachment_name = f"{safe_title}.txt"
            logger.info(
                "TXT 回退保存成功: title=%s path=%s chars=%d",
                item.title, item.attachment_path, len(clean_text),
            )
        except Exception:
            logger.exception("TXT 回退保存异常: %s", item.title)

    async def _notify(self, result: CrawlResultSummary) -> None:
        """发送飞书通知（延迟导入避免循环引用）。"""
        try:
            from app.modules.safety.regulation_crawler.notifier.push_notifier import (
                PushNotifier,
            )

            notifier = PushNotifier()
            await notifier.send_crawl_result_notification(result)
        except Exception:
            logger.exception("发送法规更新通知失败")

    # ── 与原料药制药企业无关的行业关键词（AI 后提取过滤用）──
    # ── 安全/环保正向关键词（用于 Layer 1 快速命中）──
    # 来源 engine/base.py 的 _SAFETY_KEYWORDS，保持同步
    _SAFETY_DOMAIN_KW: list[str] = [
        "安全生产", "危险化学品", "危化品", "特种设备",
        "消防", "职业病", "职业健康", "防爆", "防护用品",
        "应急预案", "应急救援", "应急管理", "事故应急",
        "突发事件", "应急",
        "化学品安全", "化学安全", "储存安全", "运输安全",
        "压力容器", "锅炉", "起重", "厂内车辆",
        "作业安全", "操作规程", "安全规程", "安全规范",
        "安全标准", "安全技术", "安全管理", "安全评价",
        "安全培训", "安全教育", "劳动防护", "劳动安全",
        "事故报告", "事故调查", "隐患排查", "安全风险",
        "重大危险源", "双重预防", "安全许可", "安全设施",
        "防尘", "防毒", "电气安全", "机械安全", "防火",
        "防雷", "防静电", "受限空间", "动火作业", "高处作业",
        "环境保护", "排污许可", "固废管理", "废气治理",
        "废水治理", "污水处理", "大气污染", "水污染",
        "土壤污染", "噪声污染", "危废管理", "危险废物",
        "清洁生产", "环境影响评价", "环评", "排污口",
        "污染物排放", "排放标准", "总量控制", "环境监测",
        "环境管理", "环境应急", "碳达峰", "碳中和",
        "碳排放", "温室气体", "挥发性有机物", "VOCs",
        "制药工业", "原料药", "发酵类", "化学合成",
    ]

    # ── 已知与原料药业务匹配的 domain 值（Layer 2 匹配）──
    _RELEVANT_DOMAINS: set[str] = {
        "安全生产", "消防安全", "特种设备", "特殊作业",
        "职业健康", "环境保护", "危化品管理", "化学品管理",
        "药品GMP", "通用", "环保", "安全",
    }

    # ── AI 低分判定阈值：影响=低 且 相关性评分低于此值时，Layer 2 的粗粒度
    # 业务领域匹配不可信，强制走 Layer 3 AI 终判（不直接放行，也不直接过滤）──
    _LOW_RELEVANCE_SCORE_THRESHOLD = 0.3

    @staticmethod
    def _is_domain_relevant(business_domains: list[str] | None) -> bool:
        """检查 AI 评定的业务领域是否与原料药工厂相关。"""
        if not business_domains:
            return False
        for d in business_domains:
            for rd in RegulationCrawlerService._RELEVANT_DOMAINS:
                if rd in d or d in rd:
                    return True
        return False

    async def _check_industry_relevance(
        self, title: str, summary: str = "", business_domains: list[str] | None = None,
        force_ai: bool = False, relevance_score: float | None = None,
        impact_level: str | None = None,
    ) -> bool:
        """三层正向判定：该法规是否适用于原料药制药工厂的安全/环保管理。

        Layer 1: 正向关键词快速命中（免费，覆盖 95% 场景）
        Layer 2: AI 业务领域匹配（已有数据，零额外成本）
        Layer 3: AI 终判（轻量调用，仅 是/否）

        当 force_ai=True 时跳过 Layer 1+2，直接走 AI 终判。
        用于批量公告的子项判定——批次公告标题被替换为具体标准名后，
        Layer 1 的正向关键词可能产生误匹配（如"烟花爆竹安全生产"命中"安全生产"）。

        低分强制 L3：当 AI 评估为「低影响」且相关性评分低于 _LOW_RELEVANCE_SCORE_THRESHOLD 时，
        Layer 2 的粗粒度业务领域匹配不可信（如"远海倾倒区"被误标为"环境保护"
        但实际与原料药工厂无关联），跳过 Layer 2 放行、强制走 Layer 3 AI 终判。

        返回 True=相关放行，False=不相关过滤。
        """
        if not force_ai:
            # ── Layer 1: 正向关键词 ──
            for kw in self._SAFETY_DOMAIN_KW:
                if kw in title:
                    return True

            # ── Layer 2: AI 业务领域匹配（低分项不放行，强制 L3）──
            low_score = (
                impact_level == "低"
                and relevance_score is not None
                and relevance_score < self._LOW_RELEVANCE_SCORE_THRESHOLD
            )
            if not low_score and self._is_domain_relevant(business_domains):
                return True

        # ── Layer 3: AI 终判 ──
        return await self.extractor.check_industry_relevance(title, summary)

    @staticmethod
    def _is_valid_document(content: bytes, filename: str) -> bool:
        """验证下载的文件是否为有效的 PDF/DOC/DOCX 文档。

        通过文件魔数（magic bytes）检测，拒绝：
        - HTML 页面（伪装成文档的网页）
        - 纯文本文件
        - 其他非文档二进制格式
        """
        if len(content) < 4:
            return False

        filename_lower = filename.lower()

        # ── 大小检查：小于 50KB 的 PDF 几乎肯定是目录页/错误页 ──
        if filename_lower.endswith(".pdf") and len(content) < 50000:
            logger.debug("PDF 文件过小 (%d bytes)，疑似目录/错误页: %s", len(content), filename)
            return False

        head = content[:16]

        # ── PDF: %PDF- 魔数 ──
        if head.startswith(b"%PDF"):
            # ── 内容检查：拒绝只有结构没有内容的空壳 PDF ──
            # MEM 等网站的附件可能使用 CID 字体编码，正文无法提取。
            # 这类 PDF 文件虽结构有效，但实际内容是页码/空白页。
            if len(content) < 80000:
                # 小型 PDF 需额外验证：至少要有明显的文本流内容
                textish = content[:30000]
                # 检查是否有足够多的 BT/ET 文本块（至少 20 个）
                bt_count = len(__import__("re").findall(rb"BT\s", textish))
                if bt_count < 20:
                    logger.debug(
                        "PDF 文本块过少 (%d)，疑似空壳: %s", bt_count, filename,
                    )
                    return False
            return True

        # ── DOC (OLE2): D0 CF 11 E0 ──
        if head[:4] == b"\xD0\xCF\x11\xE0":
            return True

        # ── DOCX/XLSX/PPTX (ZIP-based Office): PK 魔数 ──
        if head[:2] == b"PK" and any(
            filename_lower.endswith(ext) for ext in (".docx", ".xlsx", ".pptx")
        ):
            return True

        # ── 明确拒绝：HTML ──
        if head.startswith(b"<!") or head.startswith(b"<htm") or head.startswith(b"<HTM"):
            return False

        # ── 拒绝纯文本 ──
        if head.startswith(b"HTTP/") or head.startswith(b"<?xml"):
            return False

        # ── 回退：基于扩展名信任 ──
        if any(filename_lower.endswith(ext) for ext in (".pdf", ".doc", ".docx")):
            return True

        return False

    @staticmethod
    def _is_substantive_change(diff: str) -> bool:
        """判断 diff 是否为实质性变更（非仅有时间戳/格式变化）。"""
        if not diff:
            return False
        noise_patterns = [
            "---", "+++", "@@",
            "更新时间", "发布时间", "访问量",
        ]
        meaningful_lines = [
            line
            for line in diff.split("\n")
            if line.strip() and not any(p in line for p in noise_patterns)
        ]
        total_chars = sum(len(line) for line in meaningful_lines)
        return total_chars >= _SUBSTANTIVE_DIFF_MIN_CHARS

    @staticmethod
    def _get_sources(
        source_url: str | None,
        source_type: str | None,
    ) -> list[RegulationSource]:
        """筛选数据源。"""
        sources = DEFAULT_SOURCES
        if source_url:
            sources = [s for s in sources if s.base_url == source_url]
        if source_type:
            sources = [s for s in sources if s.source_type == source_type]
        return sources
