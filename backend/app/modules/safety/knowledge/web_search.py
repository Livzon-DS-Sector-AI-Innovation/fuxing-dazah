"""Web search fallback — triggered when internal knowledge base returns no results.

Provides a pluggable web search service that fetches search result
snippets from external engines (DuckDuckGo / Bing) and formats them
as AI prompt context, mirroring the RAG context format.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

logger = logging.getLogger(__name__)

# ── Timeouts ──

_SEARCH_TIMEOUT = 10.0  # seconds — web search must fail fast
_HTTP_TIMEOUT = 8.0     # seconds — individual HTTP fetch


# ═══════════════════════════════════════════════════════════════
# Data Class
# ═══════════════════════════════════════════════════════════════


@dataclass
class WebSearchResult:
    """A single web search result snippet."""

    title: str
    snippet: str
    url: str
    source_name: str = "web"  # engine name, e.g. "Bing", "DuckDuckGo"


# ═══════════════════════════════════════════════════════════════
# HTML Parser: DuckDuckGo Lite results
# ═══════════════════════════════════════════════════════════════


class _DuckDuckGoLiteParser(HTMLParser):
    """Parse DuckDuckGo Lite HTML into WebSearchResult list.

    DuckDuckGo Lite (lite.duckduckgo.com/lite) returns results as:
      <a href="url" class="result-link">title</a>
      <span class="result-snippet">snippet...</span>
    """

    def __init__(self):
        super().__init__()
        self.results: list[WebSearchResult] = []
        self._current_url: str = ""
        self._current_title: str = ""
        self._in_link: bool = False
        self._in_snippet: bool = False
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attrs_dict = dict(attrs)
        css_class = attrs_dict.get("class", "")

        if tag == "a" and "result-link" in css_class:
            self._current_url = attrs_dict.get("href", "")
            self._in_link = True
            self._current_title = ""
        elif tag == "span" and "result-snippet" in css_class:
            self._in_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str):
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "span" and self._in_snippet:
            self._in_snippet = False
            snippet = " ".join(self._snippet_parts).strip()
            if self._current_title and snippet:
                self.results.append(WebSearchResult(
                    title=self._current_title.strip(),
                    snippet=snippet,
                    url=self._current_url,
                    source_name="DuckDuckGo",
                ))
            self._current_title = ""
            self._current_url = ""

    def handle_data(self, data: str):
        if self._in_link:
            self._current_title += data
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def error(self, message):
        pass  # Suppress parse warnings in strict mode


# ═══════════════════════════════════════════════════════════════
# HTML Parser: Bing raw results (fallback if JSON API used)
# ═══════════════════════════════════════════════════════════════


class _BingHTMLParser(HTMLParser):
    """Parse Bing search HTML into WebSearchResult list (fallback parser).

    Used only when the Bing Web Search API JSON response is unavailable
    and we fall back to scraping the HTML search page.
    """

    def __init__(self):
        super().__init__()
        self.results: list[WebSearchResult] = []
        self._current: dict[str, str] = {}
        self._in_link: bool = False
        self._in_snippet: bool = False
        self._depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        pass  # Simplified; production Bing path uses JSON API

    def handle_data(self, data: str):
        pass


# ═══════════════════════════════════════════════════════════════
# Bing HTML Parser (module-level helper)
# ═══════════════════════════════════════════════════════════════


def _parse_bing_html(html: str, num_results: int) -> list[WebSearchResult]:
    """Parse Bing.com search results page HTML into WebSearchResult list.

    Bing wraps each result in ``<li class="b_algo">`` blocks containing:
      - ``<h2><a href="...">title</a></h2>``
      - ``<p>snippet text</p>`` (inside the ``b_caption`` div)

    Also extracts ``b_algoSlug`` links that Bing prefixes before the actual URL.
    """
    # Split into result blocks
    blocks = re.split(r'<li\s+class="b_algo"', html)
    if len(blocks) <= 1:
        return []

    results: list[WebSearchResult] = []

    for block in blocks[1:]:
        # Extract URL and title from <h2><a href="URL">TITLE</a>
        link_m = re.search(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            block, re.DOTALL,
        )
        if not link_m:
            continue

        url = link_m.group(1)
        title = re.sub(r'<[^>]+>', '', link_m.group(2)).strip()

        # Clean up Bing's internal URL prefixing (e.g. "domain.comhttps://actual.url")
        # Bing sometimes prepends the display domain before the actual href
        double_proto = re.search(r'\.(com|cn|org|net|gov)\s*https?://', url)
        if double_proto:
            url = "https://" + url.split("https://", 1)[-1]

        # Extract snippet from <p> inside the result block
        snippet = ""
        snippet_m = re.search(
            r'<p[^>]*>(.*?)</p>', block, re.DOTALL,
        )
        if snippet_m:
            snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip()
            # Collapse whitespace and HTML entities
            snippet = re.sub(r'&ensp;|&nbsp;|&#0183;', ' ', snippet)
            snippet = re.sub(r'\s+', ' ', snippet).strip()

        # Skip results with empty titles
        if not title:
            continue

        results.append(WebSearchResult(
            title=title,
            snippet=snippet,
            url=url,
            source_name="Bing",
        ))

        if len(results) >= num_results:
            break

    return results


# ═══════════════════════════════════════════════════════════════
# Web Search Service
# ═══════════════════════════════════════════════════════════════


class WebSearchService:
    """Pluggable web search service for knowledge base fallback.

    Engine selection (via ``WEB_SEARCH_ENGINE`` env var):
      - ``bing_html`` — free Bing HTML scraping (default, works in China)
      - ``duckduckgo`` — free, no API key, HTML scraping (dev, blocked in CN)
      - ``bing`` — Azure Bing Web Search API v7 (production, needs key)

    Usage::

        service = WebSearchService()
        results = await service.search("受限空间氧气含量标准")
        context = service.build_prompt_context(results)
    """

    def __init__(
        self,
        engine: str | None = None,
        api_key: str | None = None,
        bing_endpoint: str | None = None,
    ):
        self.engine = engine or os.getenv("WEB_SEARCH_ENGINE", "bing_html")
        self.api_key = api_key or os.getenv("WEB_SEARCH_API_KEY", "")
        self.bing_endpoint = bing_endpoint or os.getenv(
            "AZURE_BING_SEARCH_ENDPOINT", ""
        )

    # ── Public API ──

    async def search(
        self,
        query: str,
        num_results: int = 5,
    ) -> list[WebSearchResult]:
        """Execute a web search and return formatted results.

        Args:
            query: Search query string (natural language).
            num_results: Maximum number of results to return (default 5).

        Returns:
            List of WebSearchResult; empty list if all engines fail.
        """
        if self.engine == "bing" and self.api_key:
            return await self._search_bing_api(query, num_results)
        elif self.engine == "bing_html":
            return await self._search_bing_html(query, num_results)
        elif self.engine == "duckduckgo":
            return await self._search_duckduckgo(query, num_results)
        else:
            # Fallback: try Bing HTML first, then DuckDuckGo
            results = await self._search_bing_html(query, num_results)
            if results:
                return results
            return await self._search_duckduckgo(query, num_results)

    @staticmethod
    def build_prompt_context(results: list[WebSearchResult]) -> str:
        """Format web search results as AI prompt context.

        Mirrors the RAG context format so the AI receives a consistent
        input structure regardless of the data source.

        Returns:
            Markdown string suitable for injection into the user message.
        """
        if not results:
            return "（互联网搜索也未找到相关信息）"

        count = len(results)
        parts = [
            f"（共 {count} 条互联网搜索结果，有效编号范围：[1] 到 [{count}]）",
            "",
        ]
        for i, r in enumerate(results, 1):
            parts.append(
                f"[{i}] **{r.title}**\n"
                f"    来源：{r.url}\n"
                f"    摘要：{r.snippet}"
            )

        return "\n\n".join(parts)

    # ── DuckDuckGo Backend ──

    async def _search_duckduckgo(
        self, query: str, num_results: int,
    ) -> list[WebSearchResult]:
        """Search via DuckDuckGo Lite (free, no API key).

        Uses lite.duckduckgo.com/lite which returns plain HTML — easy to
        parse and less likely to be rate-limited than the full JS version.
        """
        url = "https://lite.duckduckgo.com/lite"
        payload = {"q": query, "kl": "cn-zh"}  # Chinese region preferences

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    data=payload,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    },
                    follow_redirects=True,
                )
                resp.raise_for_status()

                parser = _DuckDuckGoLiteParser()
                parser.feed(resp.text)

                results = parser.results[:num_results]
                logger.info(
                    "DuckDuckGo search returned %d results for query=%r",
                    len(results), query[:60],
                )
                return results

        except httpx.TimeoutException:
            logger.warning("DuckDuckGo search timed out for query=%r", query[:60])
            return []
        except Exception:
            logger.exception("DuckDuckGo search failed for query=%r", query[:60])
            return []

    # ── Bing HTML Backend (free, works in China) ──

    async def _search_bing_html(
        self, query: str, num_results: int,
    ) -> list[WebSearchResult]:
        """Search via Bing.com HTML scraping (free, no API key).

        Parses the public Bing search results page. Works inside mainland
        China where DuckDuckGo is blocked.
        """
        url = "https://www.bing.com/search"
        params = {
            "q": query,
            "mkt": "zh-CN",
            "setlang": "zh-CN",
            "count": str(num_results),
        }

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    },
                    follow_redirects=True,
                )
                resp.raise_for_status()

                results = _parse_bing_html(resp.text, num_results)
                logger.info(
                    "Bing HTML search returned %d results for query=%r",
                    len(results), query[:60],
                )
                return results

        except httpx.TimeoutException:
            logger.warning("Bing HTML search timed out for query=%r", query[:60])
            return []
        except Exception:
            logger.exception("Bing HTML search failed for query=%r", query[:60])
            return []

    # ── Bing API Backend (Azure, production quality) ──

    async def _search_bing_api(
        self, query: str, num_results: int,
    ) -> list[WebSearchResult]:
        """Search via Azure Bing Web Search API v7.

        Requires WEB_SEARCH_API_KEY + AZURE_BING_SEARCH_ENDPOINT env vars.
        """
        endpoint = self.bing_endpoint.rstrip("/") + "/v7.0/search"
        params = {
            "q": query,
            "count": num_results,
            "mkt": "zh-CN",
            "safeSearch": "Strict",
        }
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    endpoint,
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                results: list[WebSearchResult] = []
                for item in data.get("webPages", {}).get("value", [])[:num_results]:
                    results.append(WebSearchResult(
                        title=item.get("name", ""),
                        snippet=item.get("snippet", ""),
                        url=item.get("url", ""),
                        source_name="Bing",
                    ))

                logger.info(
                    "Bing search returned %d results for query=%r",
                    len(results), query[:60],
                )
                return results

        except httpx.TimeoutException:
            logger.warning("Bing search timed out for query=%r", query[:60])
            return []
        except Exception:
            logger.exception("Bing search failed for query=%r", query[:60])
            return []

    # ── Sanitize ──

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Strip tracking params and enforce https."""
        if not url:
            return ""
        # Ensure https
        if url.startswith("http://"):
            url = "https://" + url[7:]
        # Strip common tracking params
        for param in ("utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid"):
            url = re.sub(rf"[?&]{param}=[^&]+", "", url)
        return url
