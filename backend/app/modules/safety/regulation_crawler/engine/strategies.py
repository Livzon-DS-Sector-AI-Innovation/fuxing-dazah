"""爬虫策略实现：ApiCrawler / HttpParseCrawler / PlaywrightCrawler。"""

from __future__ import annotations

import json as _json
import logging
import re as _re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from app.modules.safety.regulation_crawler.engine.base import (
    BaseCrawler,
    RegulationSource,
)
from app.modules.safety.regulation_crawler.schemas import CrawledRegulation

logger = logging.getLogger(__name__)

# 用于清除 gov.cn 标题中的 HTML 高亮标签（<em>keyword</em>）
_HTML_TAG_RE = _re.compile(r"<[^>]+>")
# 用于剥离标题末尾的日期后缀（如 "安全生产法2024-07-15"、"公告：批准5项行业标准2026-06-22 09:20"）
_STRIP_TRAILING_DATE_RE = _re.compile(
    r"[\s-]*\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?[\s-]*$"
)
# 从任意文本中提取首个日期（处理 "(2026-06-25)"、"2026年6月25日" 等列表项日期格式）
_DATE_EXTRACT_RE = _re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?")
# 剥离标题开头的媒体来源前缀（如 "[中国政府网] 人体器官捐献和移植条例"）
_BRACKET_PREFIX_RE = _re.compile(r"^\[[^\]]*\]\s*")


def _extract_date_text(text: str) -> str:
    """从文本中提取首个日期并规范化为 YYYY-MM-DD；无匹配返回空串。

    兼容 "(2026-06-25)"、"2026年6月25日"、"2026/06/25" 等格式。
    """
    m = _DATE_EXTRACT_RE.search(text or "")
    if not m:
        return ""
    raw = m.group(0).replace("年", "-").replace("月", "-").replace("日", "")
    parts = [p for p in raw.split("-") if p]
    if len(parts) != 3:
        return ""
    try:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    except ValueError:
        return ""

# ── 老标准窗口：仅保留最近 N 年内发布/实施的标准 ──
# hbba/openstd 是全量历史标准目录（含 2007~2026 所有年份），若不过滤，
# 每次爬取都会把历史老标准当成"新增"写入 Bitable 并推送通知（2026-08-17 事故根因）。
# 过滤依据：发布日期或实施日期任一落在窗口内即保留（实施日期的存在说明近期仍生效/施行）。
_MAX_STANDARD_AGE_YEARS = 2


def _is_recent_standard(pub_date: str, impl_date: str = "") -> bool:
    """判断标准是否在 recency 窗口内（pub 或 impl 任一不早于窗口）。

    两个日期都缺失/不可解析时返回 True（放行），由服务层元数据完整性检查兜底。
    """
    today = date.today()
    has_any_date = False
    for ds in (pub_date, impl_date):
        ds = (ds or "").strip()
        if not ds:
            continue
        has_any_date = True
        try:
            d = datetime.strptime(ds[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            # 兼容 "2026/06/22"、"2026.06.22" 等格式
            for fmt in ("%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
                try:
                    d = datetime.strptime(ds[:10], fmt).date()
                    break
                except ValueError:
                    continue
            else:
                continue
        age_years = (today - d).days / 365.25
        if age_years <= _MAX_STANDARD_AGE_YEARS:
            return True
    # 无任何可解析日期 → 不拦截（由元数据完整性检查决定）
    return not has_any_date



# ═══════════════════════════════════════════════════════════════
# 策略 1: API 爬虫（JSON API 端点）
# ═══════════════════════════════════════════════════════════════


class ApiCrawler(BaseCrawler):
    """调用 JSON REST API 获取法规列表。

    支持分页（通过 pagination_pattern 或 base_url?page={page} 自动追加）。
    支持 API 查询参数（通过 source.api_params dict 追加到 URL）。
    """

    async def crawl(self) -> list[CrawledRegulation]:
        logger.info("ApiCrawler 开始爬取: %s", self.source.name)
        items: list[CrawledRegulation] = []

        try:
            for page in range(1, self.source.max_pages + 1):
                url = self._build_api_url(page)
                raw = await self.fetch_page(url)
                data = _json.loads(raw)
                records = self._extract_records(data)
                if not records:
                    break
                for record in records:
                    item = self._parse_record(record)
                    if item:
                        items.append(item)
                if len(records) < 10:
                    break  # 最后一页
        except Exception:
            logger.exception("ApiCrawler 爬取失败: %s", self.source.name)

        logger.info("ApiCrawler 完成: %s, 提取 %d 条", self.source.name, len(items))
        return items

    def _build_api_url(self, page: int) -> str:
        """构建 API URL，追加分页和查询参数。

        当 source.lookback_days > 0 时，动态计算 mintime/maxtime
        以限制只抓取最近 N 天的文档。

        注意：如果 source 同时配置了 pagination_pattern 和 lookback_days，
        则忽略 pagination_pattern，改用动态构建 URL（以确保时间参数正确注入）。
        """
        import urllib.parse as _up
        from datetime import datetime, timedelta

        base = self.source.base_url
        params: dict[str, str] = dict(self.source.api_params or {})

        # 动态时间过滤
        if self.source.lookback_days > 0:
            end = datetime.now()
            start = end - timedelta(days=self.source.lookback_days)
            params["mintime"] = start.strftime("%Y-%m-%d")
            params["maxtime"] = end.strftime("%Y-%m-%d")

        # 分页参数
        params["page"] = str(page)

        # lookback_days > 0 时强制使用动态 URL（忽略静态 pagination_pattern）
        if self.source.lookback_days <= 0 and self.source.pagination_pattern:
            return self.source.pagination_pattern.format(page=page, page0=page - 1)

        if "?" in base:
            return f"{base}&{_up.urlencode(params)}"
        return f"{base}?{_up.urlencode(params)}"

    def _extract_records(self, data: dict | list) -> list[dict]:
        """从 API 响应中提取记录列表。

        支持常见结构：
        - gov.cn: catMap.gongwen.listVO + catMap.bumenfile.listVO
        - flk.npc.gov.cn: result.data[]
        - 通用: data[], result[], records[], items[], list[]
        """
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []

        # gov.cn 特殊结构：searchVO.catMap -> gongwen/bumenfile -> listVO[]
        data_dict = data.get("data") or {}
        search_vo = data.get("searchVO") or {}
        cat_map = (
            data.get("catMap")
            or (data_dict.get("catMap") if isinstance(data_dict, dict) else None)
            or (search_vo.get("catMap") if isinstance(search_vo, dict) else None)
        )
        if cat_map and isinstance(cat_map, dict):
            combined: list[dict] = []
            for cat_key in ("gongwen", "bumenfile", "gongbao"):
                cat = cat_map.get(cat_key)
                if isinstance(cat, dict):
                    lst = cat.get("listVO") or cat.get("list") or []
                    if isinstance(lst, list):
                        combined.extend(lst)
            if combined:
                return combined

        # 通用结构
        for key in ("data", "result", "records", "items", "list"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for sub_key in ("data", "records", "items", "list"):
                    sub_val = val.get(sub_key)
                    if isinstance(sub_val, list):
                        return sub_val
        return []

    def _parse_record(self, record: dict) -> CrawledRegulation | None:
        """解析单个 API 记录，支持 gov.cn 和 flk.npc.gov.cn 格式。

        内置发布机关白名单 + 标题黑名单过滤。
        """
        # 标题
        title = (
            record.get("title")
            or record.get("name")
            or record.get("法规名称")
            or record.get("lawName")
            or ""
        ).strip()
        if not title or len(title) < 3:
            return None

        # ── HTML 标签清理（gov.cn 标题含 <em>keyword</em> 高亮）──
        title = _HTML_TAG_RE.sub("", title).strip()
        # ── 剥离标题末尾的日期后缀（如 "安全生产法2024-07-15" → "安全生产法"）──
        title = _STRIP_TRAILING_DATE_RE.sub("", title).strip()
        if not title or len(title) < 3:
            return None

        # ── 过滤 ──
        if self._should_skip(title, record.get("puborg", "")):
            return None

        # URL
        source_url = record.get("url") or record.get("link") or self.source.base_url
        if source_url and not str(source_url).startswith("http"):
            source_url = "https://www.gov.cn" + str(source_url)

        # 日期: gov.cn uses pubtimeStr (e.g. "2026.04.07"), NPC uses publish
        pub_date = (
            record.get("pubtimeStr")
            or record.get("publishDate")
            or record.get("publish")
            or record.get("发布日期")
        )
        if pub_date:
            pub_date = str(pub_date).replace(".", "-")[:10]  # normalize "2026.04.07" → "2026-04-07"

        # 发布机关: gov.cn uses puborg, NPC uses office
        authority = (
            record.get("puborg")
            or record.get("office")
            or record.get("issuingAuthority")
            or record.get("发布机关")
        )

        # 文号: gov.cn uses pcode/wenhao
        doc_number = (
            record.get("wenhao")
            or record.get("pcode")
            or record.get("documentNumber")
            or record.get("文号")
        )

        # 状态: gov.cn uses shixiao
        status = (
            record.get("shixiao")
            or record.get("status")
            or record.get("时效状态")
        )

        return CrawledRegulation(
            title=str(title),
            document_number=str(doc_number) if doc_number else None,
            publish_date=str(pub_date) if pub_date else None,
            implementation_date=None,
            issuing_authority=str(authority) if authority else None,
            regulation_level=None,
            status=str(status) if status else None,
            source_url=str(source_url),
            source_type=self.source.source_type,
            raw_text=record.get("summary") or str(title),
        )

# ═══════════════════════════════════════════════════════════════
# 策略 2: HTTP 解析爬虫（静态 HTML）
# ═══════════════════════════════════════════════════════════════


class HttpParseCrawler(BaseCrawler):
    """httpx + BeautifulSoup 解析静态 HTML 页面。"""

    async def crawl(self) -> list[CrawledRegulation]:
        logger.info("HttpParseCrawler 开始爬取: %s", self.source.name)
        items: list[CrawledRegulation] = []

        try:
            for page in range(1, self.source.max_pages + 1):
                url = self._build_page_url(page)
                html = await self.fetch_page(url)
                page_items = self._parse_html(html)
                if not page_items:
                    break  # 空页面 = 到达末页
                items.extend(page_items)
                logger.debug("  page=%d, items=%d", page, len(page_items))
        except Exception:
            logger.exception("HttpParseCrawler 爬取失败: %s", self.source.name)

        logger.info("HttpParseCrawler 完成: %s, 提取 %d 条", self.source.name, len(items))
        return items

    def _build_page_url(self, page: int) -> str:
        if page <= 1:
            return self.source.base_url
        if self.source.pagination_pattern:
            return self.source.pagination_pattern.format(page=page, page0=page - 1)
        return self.source.base_url.rstrip("/") + f"/index_{page}.html"

    def _parse_html(self, html: str) -> list[CrawledRegulation]:
        """用 CSS 选择器解析列表页。

        支持两种选择器模式：
        1. 容器模式：选择器匹配 li/div 等容器元素 → 内部查找 <a>
        2. 直选模式：选择器直接匹配 <a> 元素 → 直接使用
        """
        soup = BeautifulSoup(html, "lxml")
        items: list[CrawledRegulation] = []

        # 选择法规列表项
        list_items = soup.select(self.source.list_selector) if self.source.list_selector else []
        if not list_items:
            # 回退：查找所有 <li> 元素
            list_items = soup.select("ul li, ol li")[:20]

        for elem in list_items:
            # ── 直选模式：元素本身就是 <a> 标签 ──
            if elem.name == "a":
                title = elem.get_text(strip=True)
                # ── 剥离标题末尾的日期后缀（部分源日期嵌入标题文本，无独立 span）──
                title = _STRIP_TRAILING_DATE_RE.sub("", title).strip()
                # ── 剥离开头媒体来源前缀（如 "[中国政府网] xxx"）──
                title = _BRACKET_PREFIX_RE.sub("", title).strip()
                if not title or len(title) < 3:
                    continue

                # ── 提取日期：优先在 <a> 内部查找（MEM 模式：<a>TITLE<span>DATE</span></a>）──
                date_str = None
                if self.source.date_selector:
                    # ① 先在 <a> 元素内部查找
                    date_el = elem.select_one(self.source.date_selector)
                    if not date_el:
                        # ② 回退到父元素
                        parent = elem.parent
                        if parent:
                            date_el = parent.select_one(self.source.date_selector)
                    if date_el:
                        date_str = date_el.get_text(strip=True)
                        # ── 从标题末尾剥离日期文本 ──
                        if date_str and title.endswith(date_str):
                            title = title[:-len(date_str)].strip()
                        # ── 日期规范化（处理 "(2026-06-25)" 等包裹格式）──
                        date_str = _extract_date_text(date_str) or None

                if not title or len(title) < 3:
                    continue
                if self._should_skip(title):
                    logger.debug("HttpParseCrawler 标题过滤: %s", title[:80])
                    continue

                link_str = str(elem.get("href", ""))
                if link_str and not link_str.startswith("http"):
                    from urllib.parse import urljoin
                    link_str = urljoin(self.source.base_url, link_str)

                items.append(CrawledRegulation(
                    title=title, document_number=None,
                    publish_date=date_str, implementation_date=None,
                    issuing_authority=None, regulation_level=None,
                    status=None,
                    source_url=link_str or self.source.base_url,
                    source_type=self.source.source_type,
                    raw_text=elem.get_text(separator="\n", strip=True),
                ))
                continue

            # ── 容器模式：查找内部的 <a> 标签 ──
            title_el = None
            if self.source.title_selector:
                title_el = elem.select_one(self.source.title_selector)
            if not title_el:
                title_el = elem.find("a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            # ── 剥离标题末尾的日期后缀（部分源日期嵌入标题文本）──
            title = _STRIP_TRAILING_DATE_RE.sub("", title).strip()
            # ── 剥离开头媒体来源前缀（如 "[中国政府网] xxx"）──
            title = _BRACKET_PREFIX_RE.sub("", title).strip()
            if not title or len(title) < 3:
                continue

            # 标题黑名单过滤
            if self._should_skip(title):
                logger.debug("HttpParseCrawler 标题过滤: %s", title[:80])
                continue

            # 提取链接
            link = title_el.get("href", "") if title_el.name == "a" else ""
            link_str = str(link) if link else ""
            if link_str and not link_str.startswith("http"):
                from urllib.parse import urljoin
                link_str = urljoin(self.source.base_url, link_str)

            # 提取日期
            date_str = None
            if self.source.date_selector:
                date_el = elem.select_one(self.source.date_selector)
                if date_el:
                    date_str = date_el.get_text(strip=True)
                    # ── 从标题末尾剥离日期文本（MEM 模式：<a>TITLE<span>DATE</span></a>）──
                    if date_str and title.endswith(date_str):
                        title = title[:-len(date_str)].strip()
                    # ── 日期规范化（处理 "(2026-06-25)" 等包裹格式）──
                    date_str = _extract_date_text(date_str) or None

            items.append(
                CrawledRegulation(
                    title=title,
                    document_number=None,
                    publish_date=date_str,
                    implementation_date=None,
                    issuing_authority=None,
                    regulation_level=None,
                    status=None,
                    source_url=link_str or self.source.base_url,
                    source_type=self.source.source_type,
                    raw_text=elem.get_text(separator="\n", strip=True),
                )
            )

        return items


# ═══════════════════════════════════════════════════════════════
# 策略 3: Playwright 爬虫（JS 渲染页面）
# ═══════════════════════════════════════════════════════════════


class PlaywrightCrawler(BaseCrawler):
    """使用 Playwright headless 浏览器爬取 JS 动态渲染的页面。

    适用于使用 React/Vue 等前端框架的政府网站，以及需要搜索交互的页面。
    需要安装: pip install playwright && playwright install chromium

    支持两种模式：
    1. 简单模式：直接访问 URL → 等待列表加载 → 解析 HTML
    2. 搜索模式（source.search_keywords 非空）：访问 → 输入搜索词 → 点击搜索 → 解析结果
    """

    async def crawl(self) -> list[CrawledRegulation]:
        logger.info("PlaywrightCrawler 开始爬取: %s", self.source.name)
        items: list[CrawledRegulation] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright 未安装，回退到 HttpParseCrawler: %s", self.source.name)
            fallback = HttpParseCrawler(self.source)
            return await fallback.crawl()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            # 补全浏览器上下文请求头：nhc/nmpa 等站点通过 Accept/Referer 识别自动化流量并返回 412
            context_headers: dict[str, str] = {}
            for hk in ("Accept", "Accept-Language"):
                hv = self._headers.get(hk)
                if hv:
                    context_headers[hk] = hv
            if "Referer" not in context_headers and self.source.base_url:
                context_headers["Referer"] = self.source.base_url
            context = await browser.new_context(
                user_agent=self._headers.get("User-Agent", ""),
                extra_http_headers=context_headers,
                locale="zh-CN",
            )
            page = await context.new_page()

            try:
                if self.source.search_keywords:
                    # ── 搜索模式：按空格拆分关键词逐个搜索（多个词一次填入会命中 0 结果）──
                    keywords = [
                        k for k in _re.split(r"[\s,，、;；]+", self.source.search_keywords) if k
                    ]
                    for kw in keywords:
                        try:
                            await self._goto_retry(page, self.source.base_url)
                            await self._search_keyword(page, kw)
                            html = await page.content()
                            page_items = self._parse_content(html, self.source)
                            if page_items:
                                items.extend(page_items)
                                logger.info(
                                    "搜索关键词 '%s' → %d 条（累计 %d）",
                                    kw, len(page_items), len(items),
                                )
                        except Exception:
                            logger.debug("搜索失败，跳过关键词: kw=%s", kw)
                    items = self._dedup(items)[:140]
                else:
                    # ── 简单模式：直接访问 + 分页 ──
                    await self._goto_retry(page, self.source.base_url)

                    # 等待列表加载
                    if self.source.list_selector:
                        try:
                            await page.wait_for_selector(self.source.list_selector, timeout=10000)
                        except Exception:
                            logger.debug("等待列表选择器超时: %s", self.source.list_selector)

                    for page_num in range(1, self.source.max_pages + 1):
                        if page_num > 1:
                            # 尝试点击下一页
                            try:
                                next_btn = await page.wait_for_selector(
                                    'a:has-text("下一页"), button:has-text(">"), .pagination a:has-text(">"), '
                                    'li.next a, a[href*="page"]',
                                    timeout=5000,
                                )
                                if next_btn:
                                    await next_btn.click()
                                await page.wait_for_timeout(3000)
                            except Exception:
                                logger.debug("无法翻页，停止于第 %d 页", page_num - 1)
                                break

                        html = await page.content()
                        page_items = self._parse_content(html, self.source)
                        if not page_items:
                            break
                        items.extend(page_items)
                        logger.debug("  page=%d, items=%d", page_num, len(page_items))

                        if len(page_items) < 5:
                            break  # 最后一页

            except Exception:
                logger.exception("PlaywrightCrawler 爬取失败: %s", self.source.name)
            finally:
                await browser.close()

        logger.info("PlaywrightCrawler 完成: %s, 提取 %d 条", self.source.name, len(items))
        return items

    async def _goto_retry(self, page: Any, url: str) -> None:
        """访问页面：domcontentloaded 失败回退 commit；412 反爬挑战页重载一次。

        nhc/nmpa 等政府站点有首访 412 JS 挑战：首次加载返回 412，
        浏览器执行挑战脚本种下 cookie 后重载即可拿到真实内容。
        """
        resp = None
        for wait_until in ("domcontentloaded", "commit"):
            try:
                resp = await page.goto(url, wait_until=wait_until, timeout=30000)
                break
            except Exception:
                continue
        if resp is not None and resp.status == 412:
            logger.info("412 反爬挑战，重载一次: %s", self.source.name)
            await page.wait_for_timeout(2000)
            try:
                await page.goto(url, wait_until="commit", timeout=30000)
            except Exception:
                logger.debug("412 重载失败，使用当前内容: %s", self.source.name)
        await page.wait_for_timeout(2000)

    async def _search_keyword(self, page: Any, keyword: str) -> None:
        """在 SAMR 标准检索页执行单关键词搜索（输入 → 在结果中筛选）。"""
        search_input = await page.wait_for_selector(
            'input[name="search1"], input[placeholder*="标准号"], input[type="text"]',
            timeout=8000,
        )
        await search_input.fill(keyword)
        await page.wait_for_timeout(300)  # 等待输入完成
        try:
            filter_btn = await page.wait_for_selector(
                'button:has-text("在结果中筛选")', timeout=5000,
            )
            await filter_btn.click()
        except Exception:
            await search_input.press("Enter")
        await page.wait_for_timeout(4000)

    @staticmethod
    def _dedup(items: list[CrawledRegulation]) -> list[CrawledRegulation]:
        """按标题去重（多关键词搜索会产生重复结果）。"""
        seen: set[str] = set()
        out: list[CrawledRegulation] = []
        for it in items:
            key = (it.title or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    def _parse_content(self, html: str, source: RegulationSource) -> list[CrawledRegulation]:
        """解析页面内容，支持表格格式（SAMR 标准列表）和列表格式。"""
        from urllib.parse import urljoin

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        items: list[CrawledRegulation] = []

        # ── 模式 1: 表格（SAMR 标准列表）──
        trs = soup.select("tr")
        for tr in trs:
            tds = tr.select("td")
            if len(tds) < 6:
                continue
            first = tds[0].get_text(strip=True)
            if not first.isdigit():
                continue  # 跳过表头/筛选行

            # 列: [序号, 标准号, ?, 采标, 名称, 类型, 状态, 发布日期, 实施日期, 操作]
            std_number = tds[1].get_text(strip=True) if len(tds) > 1 else ""
            title = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            std_type = tds[5].get_text(strip=True) if len(tds) > 5 else ""  # 强标/推标
            status = tds[6].get_text(strip=True) if len(tds) > 6 else ""   # 现行/废止/即将实施
            pub_date = tds[7].get_text(strip=True) if len(tds) > 7 else ""
            impl_date = tds[8].get_text(strip=True) if len(tds) > 8 else ""

            if not title or len(title) < 3:
                continue

            # 标题黑名单过滤
            combined_title = f"{std_number} {title}" if std_number else title
            if self._should_skip(combined_title):
                logger.debug("PlaywrightCrawler 标题过滤: %s", combined_title[:80])
                continue

            # 构建详情链接：openstd 的「查看详细」是 <button onclick="showInfo('HASH')">，
            # 无 <a href>；从 onclick 提取 HASH 构造真实的标准详情页 URL。
            detail_link = ""
            if len(tds) > 9:
                detail_a = tds[9].find("a") or tds[-1].find("a")
                if detail_a:
                    detail_link = detail_a.get("href", "")
                    if detail_link and not detail_link.startswith("http"):
                        detail_link = urljoin(source.base_url, detail_link)
                else:
                    # 从「查看详细」按钮的 showInfo('HASH') 提取标准详情 hash
                    btn = tds[9].find("button") or tds[-1].find("button")
                    if btn is not None:
                        onclick = str(btn.get("onclick", ""))
                        m = _re.search(r"showInfo\('([^']+)'\)", onclick)
                        if m:
                            detail_link = f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={m.group(1)}"

            items.append(CrawledRegulation(
                title=f"{std_number} {title}",
                document_number=std_number,
                publish_date=pub_date,
                implementation_date=impl_date,
                issuing_authority="国家标准化管理委员会",
                regulation_level="国家标准" if "强" in std_type else "推荐标准",
                status="现行有效" if "现行" in status else ("即将实施" if "即将" in status else status),
                source_url=detail_link or source.base_url,
                source_type=source.source_type,
                raw_text=f"{std_number} {title} | {std_type} | {status}",
            ))

        if items:
            return items

        # ── 模式 2: 列表（回退到 HttpParseCrawler 的解析逻辑）──
        parser = HttpParseCrawler(source)
        items = parser._parse_html(html)
        if items:
            return items

        # ── 模式 3: 智能回退 — 提取页面中所有类法规链接 ──
        # 当网站改版导致选择器全部失效时，不再返回空列表，
        # 而是提取所有 <a> 标签，用标题质量过滤后交由 AI 管线处理。
        return self._extract_all_regulation_links(html, source)

    def _extract_all_regulation_links(
        self, html: str, source: RegulationSource,
    ) -> list[CrawledRegulation]:
        """智能回退：从页面中提取所有可能是法规的链接。

        当网站改版导致配置的 CSS 选择器失效时使用此方法。
        过滤条件：
        1. 标题 ≥ 10 个字符且含中文
        2. href 不是锚点/javascript
        3. 通过 _should_skip 过滤（黑名单 + 非法规关键词）
        4. 优先提取长标题、含法规关键词的链接
        5. 上限 30 条（避免 AI 管线过载）
        """
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "lxml")
        all_links = soup.select("a[href]")

        # ── 法规关键词加权（标题含以下词的优先）──
        _REGULATION_KW = [
            "条例", "办法", "规定", "规程", "规范", "规则", "通知",
            "公告", "意见", "标准", "安全", "管理", "生产", "应急",
            "消防", "职业", "健康", "环保", "药品", "化学品", "设备",
            "特种", "锅炉", "压力", "电气", "防爆", "作业", "事故",
        ]

        candidates: list[tuple[int, str, str]] = []  # (score, title, href)

        for a in all_links:
            title = a.get_text(strip=True)
            href = str(a.get("href", ""))

            # ── 基础过滤 ──
            if not title or len(title) < 3:
                continue
            if not any("一" <= c <= "鿿" for c in title):
                continue
            if href.startswith("#") or href.startswith("javascript"):
                continue

            # ── 导航链接过滤 ──
            nav_keywords = [
                "首页", "上一页", "下一页", "末页", "返回", "设为首页",
                "加入收藏", "网站地图", "更多>>", "点击查看", "每页",
            ]
            if any(kw in title for kw in nav_keywords):
                continue

            # ── 复用通用过滤（黑名单 + 非法规关键词 + 非安全法律 + 标题质量）──
            if self._should_skip(title):
                continue

            # ── 安全法规门控：标题必须命中至少一个安全关键词 ──
            # 智能回退从页面中提取所有链接，很多是非安全领域的法律/法规，
            # 此门控确保只有安全生产相关的内容进入 AI 管线。
            if not any(kw in title for kw in self._SAFETY_KEYWORDS):
                # 额外检查：标题含"安全"二字的必定保留
                if "安全" not in title:
                    continue

            # ── 计算相关性评分 ──
            score = len(title)  # 基础分 = 标题长度
            for kw in _REGULATION_KW:
                if kw in title:
                    score += 20  # 命中法规关键词加权

            # ── 解析 URL ──
            if not href.startswith("http"):
                href = urljoin(source.base_url, href)

            candidates.append((score, title, href))

        # 按 score 降序排列，取前 30 条
        candidates.sort(key=lambda x: x[0], reverse=True)
        candidates = candidates[:30]

        items: list[CrawledRegulation] = []
        for _score, title, href in candidates:
            # ── 剥离标题末尾的日期后缀（如 "安全生产法2024-07-15" → "安全生产法"）──
            # NPC 搜索结果中标题常附带发布日期，保留会破坏 L1 精确去重
            clean_title = _STRIP_TRAILING_DATE_RE.sub("", title).strip()
            if len(clean_title) < 6:
                clean_title = title  # 剥离后太短则保留原标题
            items.append(CrawledRegulation(
                title=clean_title,
                document_number=None,
                publish_date=None,
                implementation_date=None,
                issuing_authority=None,
                regulation_level=None,
                status=None,
                source_url=href,
                source_type=source.source_type,
                raw_text=title,
            ))

        logger.info(
            "智能回退提取: source=%s total_links=%d after_filter=%d top_candidates=%d",
            source.name, len(all_links), len(candidates), len(items),
        )
        return items


# ═══════════════════════════════════════════════════════════════
# SAMR 公告爬虫（全国标准信息公共服务平台）
# ═══════════════════════════════════════════════════════════════


class SamrListCrawler(BaseCrawler):
    """SAMR 标准列表爬虫（hbba/openstd）。

    直接爬取已分类的标准列表页，逐条提取标准元数据 + 下载 PDF。
    hbba（安全生产行业标准）：逐条可下载 PDF → attachment_url 设为下载链接
    openstd（强制性国标）：逐条元数据 → Playwright PDF 渲染回退
    """

    # ── hbba PDF 下载 URL 模板 ──
    _HBBA_DOWNLOAD_URL = "https://hbba.sacinfo.org.cn/portal/download/"

    async def crawl(self) -> list[CrawledRegulation]:
        """爬取 SAMR 标准列表页 → 提取逐条标准。

        hbba:   bootstrap-table 客户端分页 → 切换 page-size=100 后点击 › 翻页
        openstd: laypage 客户端分页 → 切换 page-size=50 后点击 next 翻页
        """
        items: list[CrawledRegulation] = []
        seen_std_nos: set[str] = set()  # 跨页去重

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright 未安装，跳过: %s", self.source.name)
            return items

        src_type = self.source.source_type
        is_hbba = src_type == "samr_hbba"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # ── 加载首页 ──
                await page.goto(self.source.base_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # ── 切换每页显示数量（减少翻页次数）──
                if is_hbba:
                    try:
                        size_btn = page.locator(".page-list .btn-group .dropdown-toggle")
                        if await size_btn.count() > 0:
                            await size_btn.click()
                            await page.wait_for_timeout(500)
                            size_options = page.locator(".page-list .dropdown-menu li a")
                            opt_count = await size_options.count()
                            if opt_count > 0:
                                await size_options.nth(opt_count - 1).click()  # 最后一项 = 100
                                await page.wait_for_timeout(2000)
                                logger.info("hbba page-size → 100: %s", self.source.name)
                    except Exception:
                        logger.warning("hbba page-size 切换失败: %s", self.source.name)
                else:
                    try:
                        await page.select_option("select.pageNumSelect", "50")
                        await page.wait_for_timeout(3000)
                        logger.info("openstd page-size → 50: %s", self.source.name)
                    except Exception:
                        logger.warning("openstd page-size 切换失败: %s", self.source.name)

                # ── 翻页爬取 ──
                for pg_num in range(1, self.source.max_pages + 1):
                    if pg_num > 1:
                        # 点击『下一页』按钮
                        if is_hbba:
                            next_li = page.locator(".page-item.page-next")
                            if await next_li.count() > 0:
                                disabled = await next_li.get_attribute("class") or ""
                                if "disabled" in disabled:
                                    logger.info("hbba 已到末页（disabled），停止翻页")
                                    break
                                await page.locator(".page-item.page-next a.page-link").click()
                                await page.wait_for_timeout(2000)
                            else:
                                break
                        else:
                            next_link = page.locator("a.laypage_next")
                            if await next_link.count() > 0:
                                await next_link.click()
                                await page.wait_for_timeout(3000)
                            else:
                                break

                    # ── JS 提取表格行 ──
                    rows = await page.evaluate('''(isHbba) => {
                        const results = [];
                        document.querySelectorAll('table tr').forEach(tr => {
                            const cells = tr.querySelectorAll('td');
                            if (cells.length < 4) return;
                            const row = {};
                            if (isHbba) {
                                // hbba: 序号|标准号|标准名称|行业分类|状态|发布日期|实施日期
                                row.stdNo = (cells[1]?.innerText || '').trim();
                                row.name = (cells[2]?.innerText || '').trim();
                                row.status = (cells[4]?.innerText || '').trim();
                                row.pubDate = (cells[5]?.innerText || '').trim();
                                row.implDate = (cells[6]?.innerText || '').trim();
                                // 详情链接：标准名称列 <a href="stdDetail/{hash}">
                                const nameLink = cells[2]?.querySelector('a[href*="stdDetail"]');
                                if (nameLink) {
                                    row.detailUrl = nameLink.href || '';
                                    const m = (nameLink.href || '').match(/stdDetail\\/([a-f0-9]+)/i);
                                    if (m) row.hash = m[1];
                                }
                            } else {
                                // openstd: 序号|标准号|(空)|标准名称|状态|发布日期|实施日期|查看详细
                                row.stdNo = (cells[1]?.innerText || '').trim();
                                row.name = (cells[3]?.innerText || '').trim();
                                row.status = (cells[4]?.innerText || '').trim();
                                row.pubDate = (cells[5]?.innerText || '').trim();
                                row.implDate = (cells[6]?.innerText || '').trim();
                                // 详情按钮：<button onclick="showInfo('HASH')">查看详细</button>
                                const detailBtn = cells[7]?.querySelector('button');
                                if (detailBtn) {
                                    const onclick = detailBtn.getAttribute('onclick') || '';
                                    const m = onclick.match(/showInfo\\('([^']+)'\\)/);
                                    if (m) {
                                        row.hash = m[1];
                                        row.detailUrl = 'https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=' + m[1];
                                    }
                                }
                            }
                            if (row.name && row.name.length >= 3) results.push(row);
                        });
                        return results;
                    }''', is_hbba)

                    logger.info("SAMR 列表第%d页: %d 条", pg_num, len(rows))

                    page_new = 0
                    for row in rows:
                        name = row.get("name", "")
                        if not name or len(name) < 3:
                            continue
                        if self._should_skip(name):
                            continue

                        std_no = row.get("stdNo", "")

                        # ── 标准号格式验证：拒绝分页栏 UI 文本 ──
                        if not self._is_valid_std_no(std_no):
                            continue

                        # ── 跨页去重 ──
                        if std_no in seen_std_nos:
                            continue
                        seen_std_nos.add(std_no)

                        # ── recency 过滤：跳过发布时间早于窗口的历史老标准 ──
                        # hbba/openstd 是全量历史目录（含 2007~2026 全部年份），
                        # 老标准在此拦截，避免后续 PDF 下载 + AI 评估白耗资源，
                        # 更避免被误判为"新增"写入 Bitable 并推送通知。
                        pub_date_raw = (row.get("pubDate") or "").strip()
                        impl_date_raw = (row.get("implDate") or "").strip()
                        if not _is_recent_standard(pub_date_raw, impl_date_raw):
                            logger.debug(
                                "跳过老标准 (pub=%s impl=%s): %s",
                                pub_date_raw, impl_date_raw, name[:60],
                            )
                            continue

                        hash_val = row.get("hash", "")
                        detail_url = row.get("detailUrl", "")
                        if not detail_url and is_hbba and hash_val:
                            detail_url = f"https://hbba.sacinfo.org.cn/stdDetail/{hash_val}"

                        # ── hbba PDF 延迟下载：不在爬取阶段落盘，仅记录下载 URL ──
                        # 文件下载移到 service 层「确认入库前」执行（_download_upload_attachment），
                        # 避免被过滤/去重掉的条目留下孤儿文件。
                        attachment_url = None
                        attachment_name = None
                        if is_hbba and hash_val:
                            attachment_url = self._HBBA_DOWNLOAD_URL + hash_val
                            safe_name = name.replace("\\", "_").replace("/", "_")[:60]
                            attachment_name = f"{safe_name}.pdf"

                        items.append(CrawledRegulation(
                            title=name,
                            document_number=std_no or None,
                            publish_date=row.get("pubDate") or None,
                            implementation_date=row.get("implDate") or None,
                            status=row.get("status") or None,
                            issuing_authority="国家标准化管理委员会",
                            source_url=detail_url or self.source.base_url,
                            source_type=src_type,
                            attachment_url=attachment_url,
                            attachment_name=attachment_name,
                            attachment_path=None,
                            attachment_file_token=None,
                            raw_text=(
                                f"标准号: {std_no}\n"
                                f"标准名: {name}\n"
                                f"状态: {row.get('status', '')}\n"
                                f"发布: {row.get('pubDate', '')}\n"
                                f"实施: {row.get('implDate', '')}"
                            ),
                        ))
                        page_new += 1

                    logger.info("SAMR 列表第%d页: %d 条, 本页新增 %d 条", pg_num, len(rows), page_new)

                    # ── 停止条件：本页无新条目或行数过少 ──
                    if page_new == 0:
                        logger.info("本页无新条目（跨页去重），停止翻页")
                        break
                    if len(rows) < 5:
                        break  # 最后一页不足5条

                await browser.close()

        except Exception:
            logger.exception("SAMR 列表爬取异常: %s", self.source.name)

        logger.info("SAMR 列表爬取完成: %s, %d 条 (去重后)", self.source.name, len(items))
        return items

    # ── 标准号格式正则：GB/T 1234-2025, AQ 3058—2023, HG/T 6465-2026 ──
    _STD_NO_RE = __import__("re").compile(r"^[A-Z]{2,}(\s*/\s*[A-Z]+)?\s*\d+")

    @staticmethod
    def _is_valid_std_no(std_no: str) -> bool:
        """校验标准号格式，拒绝分页栏/UI 文本等非标准数据。"""
        if not std_no or len(std_no) < 3:
            return False
        return bool(SamrListCrawler._STD_NO_RE.match(std_no.strip()))

    @staticmethod
    def _build_page_url(base_url: str, page_num: int) -> str:
        """构建分页 URL。hbba 和 openstd 都使用 pageNo 参数。"""
        if page_num <= 1:
            return base_url
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}pageNo={page_num}"


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════


def crawler_factory(source: RegulationSource) -> BaseCrawler:
    """根据 source.strategy 创建对应的爬虫实例。"""
    strategy_map: dict[str, type[BaseCrawler]] = {
        "api": ApiCrawler,
        "http_parse": HttpParseCrawler,
        "playwright": PlaywrightCrawler,
        "samr_list": SamrListCrawler,
    }
    cls = strategy_map.get(source.strategy, HttpParseCrawler)
    return cls(source)
