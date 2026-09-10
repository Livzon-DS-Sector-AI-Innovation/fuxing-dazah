"""爬虫抽象基类。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.modules.safety.regulation_crawler.schemas import CrawledRegulation

logger = logging.getLogger(__name__)


@dataclass
class RegulationSource:
    """法规数据源配置。"""

    name: str  # 人类可读的名称（如"全国人大法律法规数据库"）
    base_url: str  # 爬取入口 URL
    source_type: str  # 来源类型标识：npc / gov_cn / mem / local_gov
    strategy: str  # 爬取策略：api / playwright / http_parse
    encoding: str = "utf-8"
    headers: dict[str, str] | None = None
    # 列表页选择器（http_parse / playwright 策略用）
    list_selector: str = ""
    title_selector: str = ""
    date_selector: str = ""
    detail_link_selector: str = ""
    # 详情页附件选择器
    attachment_selector: str = ""
    # API 策略额外参数（URL 查询字符串）
    api_params: dict[str, str] | None = None
    # API 结果过滤
    puborg_whitelist: list[str] | None = None  # 发布机关白名单（空=不过滤）
    title_blacklist: list[str] | None = None    # 标题黑名单关键词（空=不过滤）
    # 分页
    pagination_pattern: str = ""
    max_pages: int = 5
    # 时间过滤：仅爬取最近 N 天的文档（0=不过滤，由 ApiCrawler 动态计算 mintime/maxtime）
    lookback_days: int = 0
    # Playwright 搜索关键词（用于 JS 渲染网站的搜索框输入）
    search_keywords: str = ""
    # 限速
    rate_limit_seconds: float = 2.0


class BaseCrawler(ABC):
    """爬虫抽象基类：输入 = RegulationSource，输出 = list[CrawledRegulation]。"""

    def __init__(self, source: RegulationSource) -> None:
        self.source = source
        self._headers = source.headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    @abstractmethod
    async def crawl(self) -> list[CrawledRegulation]:
        """执行爬取，返回提取的法规列表。"""
        ...

    # ── 非法规内容的通用过滤模式 ──
    _TRASH_TITLE_PATTERNS: list[str] = [
        "每页显示", "条/页", "首页", "上一页", "下一页", "末页",
        "规范性文件", "政策解读", "更多>>", "点击查看",
        "返回首页", "设为首页", "加入收藏", "网站地图",
        "法律法规", "标准规范", "标准公开", "规章制度",
        "地方法规", "国家法规", "部门规章",
        "行政法规", "司法解释",  # 分类标签，不是法规标题
        # ── 政府网站页脚导航部门名 ──
        "外交部", "国防部", "教育部", "公安部",
        "民政部", "司法部", "财政部", "科学技术部",
        "自然资源部", "交通运输部", "水利部", "农业农村部",
        "商务部", "文化和旅游部", "退役军人事务部",
        "中国人民银行", "审计署",
        "国家民族事务委员会", "国家发展和改革委员会",
        "人力资源和社会保障部", "工业和信息化部",
        "住房和城乡建设部", "国家卫生健康委员会",
        "生态环境部",  # 网站 logo/header 链接
    ]
    # ── 明确非法规文档的标题关键词（AI 分类之前即拦截） ──
    _NON_REGULATION_TITLE_KW: list[str] = [
        "政府工作报告", "产业目录", "投资目录", "规划纲要",
        "五年规划", "工作计划", "工作总结", "会议纪要",
        "表彰", "任免", "任职", "免职", "招标", "中标",
        "领导讲话", "在…会议上", "致辞", "贺信", "批示",
        # ── 应急管理部通知公告中的非法规条目 ──
        "网站检查", "网站抽查", "知识竞赛", "作品征集",
        "消防演练", "应急演练通知", "演习通知",
        "挂牌督办",  # 事故调查督办函，非法规
        "公开征求",  # 征求意见稿，非正式法规
        "专项治理", "专项整治", "整治工作",  # 部门工作通知，非法规
    ]
    # ── 非安全生产领域的法律/行政法规关键词（AI 分类之前即拦截） ──
    # 这些是中国法律体系中的通用法律，不涉及安全生产/职业健康/消防/危化品/特种设备
    _NON_SAFETY_LEGAL_KW: list[str] = [
        "行政许可法", "行政处罚法", "行政强制法", "行政复议法",
        "行政诉讼法", "国家赔偿法", "立法法", "监督法",
        "刑法", "刑事诉讼法", "民事诉讼法", "民法典",
        "防洪法", "防震减灾法", "抗旱条例", "防汛条例",
        "矿山安全法", "煤炭法", "矿产资源法",
        "烟花爆竹", "民用爆炸物品",
        "消防救援衔", "消防员", "消防队伍",
        "劳动法", "劳动合同法", "劳动争议", "社会保险法",
        "自然灾害", "气象法", "测绘法", "水法", "水土保持",
        "公司法", "合伙企业法", "个人独资法", "企业破产法",
        "对外贸易法", "海商法", "票据法", "信托法", "证券法",
        "国籍法", "护照法", "出境入境", "外国人入境",
        "档案法", "保密法", "密码法", "数据安全法",
        "野生动物", "文物保护", "非物质文化遗产",
        "立法法", "司法鉴定",
        # ── 与原料药制药企业无关的行业法规（快速预过滤，节省 AI 调用）──
        # 边缘案例由 AI 行业相关性终判兜底
        "烟花爆竹", "煤矿", "矿山", "页岩气", "海洋石油",
        "耐火材料", "铁合金", "商业综合体", "应急避难场所",
        "社会应急力量", "应急指挥无线", "消防数据元",
    ]
    # ── 安全/环保法规正向关键词（智能回退时使用，标题必须命中至少一个）──
    _SAFETY_KEYWORDS: list[str] = [
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
        # ── 环境保护 ──
        "环境保护", "排污许可", "固废管理", "废气治理",
        "废水治理", "污水处理", "大气污染", "水污染",
        "土壤污染", "噪声污染", "危废管理", "危险废物",
        "清洁生产", "环境影响评价", "环评", "排污口",
        "污染物排放", "排放标准", "总量控制", "环境监测",
        "环境管理", "环境应急", "碳达峰", "碳中和",
        "碳排放", "温室气体", "挥发性有机物", "VOCs",
        "制药工业", "原料药", "发酵类", "化学合成",
    ]

    def _should_skip(self, title: str, puborg: str = "") -> bool:
        """发布机关白名单 + 标题黑名单 + 标题质量过滤。返回 True = 跳过。

        由子类在解析每条记录时调用，确保所有策略共享一致的过滤逻辑。
        """
        # ── ① 标题质量检查（最小长度 + 必须含中文） ──
        title_stripped = title.strip()
        if len(title_stripped) < 3:
            # 少于 3 字符不可能是法规标题（"首页"、"末页" 等导航标签）
            return True
        if not any("一" <= c <= "鿿" for c in title_stripped):
            # 全部非中文 → 可能是页面控件文字
            return True

        # ── ② 通用垃圾标题模式（页面导航/分类标签/UI控件） ──
        for pattern in self._TRASH_TITLE_PATTERNS:
            if pattern in title_stripped:
                return True

        # ── ②.5 明确非法规文档关键词（政府工作报告/产业目录/规划等） ──
        for kw in self._NON_REGULATION_TITLE_KW:
            if kw in title_stripped:
                return True

        # ── ②.6 非安全生产领域的法律/行政法规 ──
        for kw in self._NON_SAFETY_LEGAL_KW:
            if kw in title_stripped:
                return True

        # ── ③ 白名单：非空时 puborg 必须命中其一 ──
        whitelist = self.source.puborg_whitelist or []
        if whitelist and puborg:
            if not any(w in puborg for w in whitelist):
                return True

        # ── ④ 黑名单：标题包含任一关键词 → 跳过 ──
        blacklist = self.source.title_blacklist or []
        title_lower = title_stripped.lower()
        for kw in blacklist:
            if kw in title_lower:
                return True

        return False

    async def fetch_page(self, url: str, timeout: float = 30.0) -> str:
        """获取单个页面内容（httpx GET，带超时 + 重试）。"""
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            for attempt in range(3):
                try:
                    resp = await http.get(url, headers=self._headers)
                    resp.raise_for_status()
                    # 自动检测编码
                    resp.encoding = (
                        resp.charset_encoding
                        or self.source.encoding
                        or "utf-8"
                    )
                    return resp.text
                except httpx.TimeoutException:
                    logger.warning("请求超时 (尝试 %d/3): %s", attempt + 1, url)
                    if attempt == 2:
                        raise
                except Exception:
                    logger.exception("请求失败 (尝试 %d/3): %s", attempt + 1, url)
                    if attempt == 2:
                        raise
            raise RuntimeError(f"获取页面失败: {url}")

    async def download_file(
        self, url: str, referer: str = "", timeout: float = 120.0,
    ) -> bytes | None:
        """下载二进制文件（PDF/DOCX 等）。

        带 3 次重试、Referer 防盗链、文件类型验证。
        返回 bytes 或 None（失败时不抛异常）。
        """
        headers = dict(self._headers)
        headers["Accept"] = (
            "application/pdf,application/msword,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "*/*;q=0.5"
        )
        if referer:
            headers["Referer"] = referer

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            for attempt in range(3):
                try:
                    resp = await http.get(url, headers=headers)
                    resp.raise_for_status()
                    content = resp.content
                    if not content:
                        logger.warning("下载文件为空 (尝试 %d/3): %s", attempt + 1, url)
                        if attempt == 2:
                            return None
                        continue
                    # 验证文件类型：拒绝 HTML 错误页
                    if self._looks_like_html(content):
                        logger.warning("下载内容疑似 HTML 而非文件: %s", url)
                        if attempt == 2:
                            return None
                        continue
                    content_type = resp.headers.get("content-type", "")
                    logger.info(
                        "文件下载成功: url=%s size=%d type=%s",
                        url, len(content), content_type,
                    )
                    return content
                except httpx.TimeoutException:
                    logger.warning("下载超时 (尝试 %d/3): %s", attempt + 1, url)
                    if attempt == 2:
                        return None
                except Exception:
                    logger.warning("下载失败 (尝试 %d/3): %s", attempt + 1, url)
                    if attempt == 2:
                        return None
        return None

    @staticmethod
    def _looks_like_html(content: bytes) -> bool:
        """检查文件内容是否疑似 HTML（防止下载到错误页面）。"""
        head = content[:200].lstrip()
        return head.startswith(b"<!") or head.startswith(b"<htm") or head.startswith(b"<HTML")
