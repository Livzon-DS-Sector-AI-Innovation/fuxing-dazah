"""字段提取器：AI（DeepSeek V4）+ 正则回退。

V1.1 新增：
- classify_content: 内容类型判定（过滤新闻/讲话）
- extract_batch: 批量提取多法规
- assess_relevance: 相关性匹配 + 影响评估 + 应对建议
- compare_with_previous: 新旧法规对比
"""

from __future__ import annotations

import json as _json
import logging
import re

from app.modules.safety.regulation_crawler.schemas import CrawledRegulation

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# AI Prompt 定义
# ═══════════════════════════════════════════════════════════════

# ── 内容类型判定 ──

CLASSIFY_SYSTEM_PROMPT = """你是一个法规内容分类助手。判定网页内容是否属于「法规标准」。

## 定义：什么是 regulation
以下任一类型即为 regulation：
- 法律、行政法规、部门规章、地方性法规的发布/修订/废止公告
- 国务院令、部委令（含"令第X号"、"公告第X号"）
- 国家/行业标准（GB/GB/T/AQ/TSG/HJ/YY 等标准号）
- 标题含"条例""办法""规定""规程""规范""规则"的规范性文件

## 排除清单（以下是 news/speech/other）
- news: 会议报道、领导调研、工作动态、新闻发布会
- speech: 政府工作报告、领导讲话、政策吹风、答记者问、规划纲要（十五五/十四五等）
- other: 产业目录、投资目录、表彰/任免/招标/中标公告、网站导航；
  行政审批/管理措施类公告（试点、分类管理、许可发放、名单确定等安排性文件，非规范性文件）；
  征求意见/公开征求意见/征集/公示/入选名单/人选等过程性通知

## 判断优先级
1. 标题含"令"+"条例"/"办法"/"规定" → **必是 regulation**
2. 标题含标准号（GB/GB/T/AQ 等）→ **必是 regulation**
3. 标题含"征求意见""征集""公示""名单""人选" → **必不是 regulation**（即使是政府/部门公告）
4. 标题为"XX部门公告第X号"但正文是试点/管理措施/审批安排等行政文件 → **other**（无具体法条/标准条文）
5. 政府工作报告/规划纲要/产业目录 → **必不是 regulation**（即使提及安全法规）
6. 以上都不匹配时，看内容是否有具体法条 → 有则是 regulation

## 输出格式
返回严格 JSON：{"content_type": "regulation|news|speech|other"}
"""

CLASSIFY_USER_TEMPLATE = """请判定以下网页内容属于哪种类型。

## 来源 URL
{source_url}

## 网页内容（已截断）
{content}
"""

# ── 字段提取（V1.1 增强：支持批量） ──

EXTRACTION_SYSTEM_PROMPT = """你是一个法规信息提取助手。你的任务是从网页内容中提取安全生产相关的法规标准信息。

## 提取规则
1. 仅提取与安全生产、职业健康、特种设备、消防、化学品管理、环境保护相关的法规标准
2. 如果页面包含多条法规，全部提取出来（最多 10 条）
3. 日期统一为 YYYY-MM-DD 格式，无法确定具体日期时用 YYYY-01-01
4. 如果某个字段无法从内容中推断，设为 null
5. 时效状态从发布日期推断：超过2年的通常是"现行有效"，近期发布的可能是"即将实施"

## 输出格式
返回严格 JSON，包含一个 items 数组：
{
  "items": [
    {
      "title": "法规名称（完整）",
      "document_number": "文号（如'国务院令第XXX号'、'GB xxxx-2025'）",
      "publish_date": "YYYY-MM-DD",
      "implementation_date": "YYYY-MM-DD",
      "issuing_authority": "发布机关",
      "regulation_level": "法律 | 行政法规 | 部门规章 | 地方性法规 | 标准规范",
      "status": "现行有效 | 即将实施 | 征求意见中 | 已废止"
    }
  ]
}

如果没有找到安全生产相关法规，返回：{"items": []}
"""

EXTRACTION_USER_TEMPLATE = """请从以下网页内容中提取安全生产相关法规信息。

## 来源 URL
{source_url}

## 来源类型
{source_type}

## 网页内容（已截断）
{content}
"""

# ── 相关性评估 ──

ASSESS_SYSTEM_PROMPT = """你是安全生产法规评估专家。你的任务是对给定的法规标准，评估其对原料药生产企业的影响。

## 企业背景
- 行业：医药制造业（化学药品原料药制造）
- 涉及领域：安全生产、职业健康、环境保护、消防安全、危化品管理、特种设备
- 工厂位于福建省福州市

## 评估维度

### 1. 业务领域匹配
从以下领域中选择所有匹配的（可多选）：
安全生产 / 职业健康 / 环境保护 / 消防安全 / 危化品管理 / 特种设备 / 通用
（"通用"表示不特定于某一领域，对所有企业均有影响）

### 2. 影响等级
- 高：强制性法规标准，与企业主营业务直接相关，不遵守将面临停产/处罚风险
- 中：推荐性标准或与企业部分业务相关，需要关注但非紧急
- 低：参考性文件、地方性法规（非企业所在地）、关联度较低

### 3. 核心内容摘要
用简洁语言概括法规的核心要求，≤300字。聚焦于与企业相关的条款。

### 4. 应对建议
如果影响等级为高或中，给出具体的应对建议：
- 制度层面：需修订/新建哪些制度
- 培训层面：需对哪些人员开展什么培训
- 时间节点：建议在什么时间前完成（如距实施日期X个月）

如果影响等级为低，应对建议可简短或留空。

## 输出格式
返回严格 JSON：
{
  "business_domains": ["安全生产", "危化品管理"],
  "impact_level": "高",
  "relevance_score": 0.92,
  "core_summary": "该标准规定了...（≤300字）",
  "action_recommendations": "制度层面：...\\n培训层面：...\\n时间节点：..."
}
"""

ASSESS_USER_TEMPLATE = """请评估以下法规对原料药生产企业的影响。

## 法规信息
- 名称：{title}
- 文号：{document_number}
- 发布机关：{issuing_authority}
- 发布日期：{publish_date}
- 实施日期：{implementation_date}
- 法规层级：{regulation_level}
- 时效状态：{status}

## 法规原文摘要
{raw_text}
"""

# ── 新旧法规对比 ──

COMPARE_SYSTEM_PROMPT = """你是一个法规对比分析助手。你的任务是比较新旧两版法规标准，识别主要变化。

## 对比维度
1. 新增内容：新增了哪些条款/要求
2. 修改内容：哪些条款发生了变化
3. 删除内容：哪些条款被移除
4. 对企业影响最大的变化（1-3条）

## 输出格式
返回严格 JSON：
{
  "comparison_summary": "主要变化描述（≤200字）"
}
"""

COMPARE_USER_TEMPLATE = """请对比以下新旧法规的变化。

## 新法规
- 名称：{new_title}
- 发布日期：{new_publish_date}
- 内容摘要：{new_summary}

## 旧法规
- 名称：{old_title}
- 发布日期：{old_publish_date}
- 内容摘要：{old_summary}
"""

# ═══════════════════════════════════════════════════════════════
# 正则回退模式
# ═══════════════════════════════════════════════════════════════

TITLE_PATTERNS = [
    r"《([^》]+)》",
    r"【(.+?)】",
    r"关于.{4,60}?(?:的通知|意见|办法|规定|条例|决定)",
]

DOC_NUMBER_PATTERNS = [
    r"(?:国务院|主席)?令\s*第?\s*(\d+[号]?)",
    r"(GB|GB/T|GBZ|AQ|HG|SH|SY)\s*[\d.]+[-—]\d{4}",
    r"([〔\[]\d{4}[〕\]\d]+号)",
]

DATE_PATTERN = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?")

# 修订/替代关键词
REVISION_KEYWORDS = re.compile(
    r"(修订|替代|代替|取代|修正|废止.*代|新版|修订版|修改)"
)

# ═══════════════════════════════════════════════════════════════
# 提取器类
# ═══════════════════════════════════════════════════════════════


class AIExtractor:
    """使用 DeepSeek V4 进行法规字段提取、内容分类、相关性评估和对比分析。"""

    def __init__(self) -> None:
        self._ai_service = None  # 延迟初始化

    async def _get_ai_service(self):  # type: ignore[no-untyped-def]
        """延迟创建 AI 服务，避免提前触发环境变量校验。"""
        if self._ai_service is None:
            from app.modules.safety.service.config import create_ai_service

            self._ai_service = create_ai_service("text")
        return self._ai_service

    # ═══════════════════════════════════════════════════════════
    # ① 内容类型判定
    # ═══════════════════════════════════════════════════════════

    async def classify_content(
        self,
        raw_text: str,
        source_url: str = "",
    ) -> str:
        """判定网页内容类型。返回 "regulation" | "news" | "speech" | "other"。"""
        if not raw_text or len(raw_text.strip()) < 50:
            return "other"

        truncated = raw_text[:4000] if len(raw_text) > 4000 else raw_text

        try:
            ai = await self._get_ai_service()
            response = await ai.chat(
                messages=[
                    {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": CLASSIFY_USER_TEMPLATE.format(
                        source_url=source_url, content=truncated,
                    )},
                ],
                response_format="json_object",
                temperature=0.0,
                max_tokens=256,
            )
            data = _json.loads(response)
            ct = (data.get("content_type") or "other").strip()
            if ct not in ("regulation", "news", "speech", "other"):
                ct = "other"
            return ct
        except Exception:
            logger.exception("内容类型判定失败: url=%s", source_url)
            return "regulation"  # 判定失败时保守处理：当作法规继续

    # ═══════════════════════════════════════════════════════════
    # ② 字段提取（支持批量）
    # ═══════════════════════════════════════════════════════════

    async def extract(
        self,
        raw_text: str,
        source_url: str = "",
        source_type: str = "",
    ) -> CrawledRegulation | None:
        """从原始文本中提取单条法规（保持向后兼容）。"""
        items = await self.extract_batch(raw_text, source_url, source_type)
        return items[0] if items else None

    async def extract_batch(
        self,
        raw_text: str,
        source_url: str = "",
        source_type: str = "",
    ) -> list[CrawledRegulation]:
        """从原始文本中批量提取法规（支持一页多条法规）。"""
        if not raw_text or len(raw_text.strip()) < 50:
            return []

        truncated = raw_text[:8000] if len(raw_text) > 8000 else raw_text

        try:
            ai = await self._get_ai_service()
            response = await ai.chat(
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": EXTRACTION_USER_TEMPLATE.format(
                        source_url=source_url,
                        source_type=source_type,
                        content=truncated,
                    )},
                ],
                response_format="json_object",
                temperature=0.1,
                max_tokens=4096,
            )
            data = _json.loads(response)
        except Exception:
            logger.exception("AI 批量提取法规字段失败: url=%s", source_url)
            return []

        items_data = data.get("items", [])
        if not isinstance(items_data, list):
            # 向后兼容：旧版单条格式
            title = (data.get("title") or "").strip()
            if title:
                items_data = [data]
            else:
                return []

        results: list[CrawledRegulation] = []
        for item_data in items_data:
            title = (item_data.get("title") or "").strip()
            if not title:
                continue
            results.append(CrawledRegulation(
                title=title,
                document_number=(item_data.get("document_number") or "").strip() or None,
                publish_date=(item_data.get("publish_date") or "").strip() or None,
                implementation_date=(item_data.get("implementation_date") or "").strip() or None,
                issuing_authority=(item_data.get("issuing_authority") or "").strip() or None,
                regulation_level=(item_data.get("regulation_level") or "").strip() or None,
                status=(item_data.get("status") or "").strip() or None,
                source_url=source_url,
                source_type=source_type,
                raw_text=truncated,
            ))

        return results

    # ═══════════════════════════════════════════════════════════
    # ③ 相关性评估 + 影响等级 + 应对建议
    # ═══════════════════════════════════════════════════════════

    async def assess_relevance(self, item: CrawledRegulation) -> CrawledRegulation:
        """评估法规对企业的相关性、影响等级，并生成摘要和应对建议。

        原地修改传入的 CrawledRegulation 并返回。
        """
        # 构建法规信息摘要
        raw_summary = item.raw_text or ""
        if len(raw_summary) > 3000:
            raw_summary = raw_summary[:3000]

        try:
            ai = await self._get_ai_service()
            response = await ai.chat(
                messages=[
                    {"role": "system", "content": ASSESS_SYSTEM_PROMPT},
                    {"role": "user", "content": ASSESS_USER_TEMPLATE.format(
                        title=item.title,
                        document_number=item.document_number or "未知",
                        issuing_authority=item.issuing_authority or "未知",
                        publish_date=item.publish_date or "未知",
                        implementation_date=item.implementation_date or "未知",
                        regulation_level=item.regulation_level or "未知",
                        status=item.status or "未知",
                        raw_text=raw_summary,
                    )},
                ],
                response_format="json_object",
                temperature=0.1,
                max_tokens=2048,
            )
            data = _json.loads(response)
        except Exception:
            logger.exception("相关性评估失败: title=%s", item.title)
            # 失败时设置默认值
            item.impact_level = "中"
            item.business_domains = ["通用"]
            item.relevance_score = 0.5
            return item

        # 填充字段
        item.impact_level = (data.get("impact_level") or "中").strip()
        if item.impact_level not in ("高", "中", "低"):
            item.impact_level = "中"

        domains = data.get("business_domains")
        if isinstance(domains, list):
            item.business_domains = [d.strip() for d in domains if d and isinstance(d, str)]
        else:
            item.business_domains = ["通用"]

        score = data.get("relevance_score")
        if isinstance(score, (int, float)):
            item.relevance_score = float(score)
        else:
            item.relevance_score = 0.5

        item.core_summary = (data.get("core_summary") or "").strip() or None
        item.action_recommendations = (data.get("action_recommendations") or "").strip() or None

        return item

    # ═══════════════════════════════════════════════════════════
    # ⑤ 批量分类+评估（合并 classify_content + assess_relevance，减少 API 调用）
    # ═══════════════════════════════════════════════════════════

    BATCH_CLASSIFY_ASSESS_PROMPT = """你是一个法规内容分类与相关性评估助手。对给定的法规列表进行批量判定。

## 企业背景
- 行业：医药制造业（化学药品原料药制造）
- 涉及领域：安全生产、职业健康、环境保护、消防安全、危化品管理、特种设备

## 对每条法规进行两项判定

### 1. 内容类型
- regulation: 法律/行政法规/部门规章/标准规范
- news: 会议报道/领导调研/工作动态
- speech: 政府工作报告/讲话/规划纲要
- other: 产业目录/任免/招标/其他

### 2. 影响评估（仅当 content_type="regulation" 时评估）
- 业务领域（可多选）：安全生产/职业健康/环境保护/消防安全/危化品管理/特种设备/通用
- 影响等级（高/中/低）
- 核心摘要（≤100字）

## 输出格式
返回严格 JSON：{"results": [{"index": 0, "content_type": "regulation", "impact_level": "高", "business_domains": ["安全生产"], "core_summary": "..."}, ...]}
"""

    BATCH_CLASSIFY_USER_TEMPLATE = """请批量判定以下法规。

{items_json}
"""

    async def classify_and_assess_batch(
        self,
        items: list[dict],
    ) -> list[dict]:
        """批量判定内容类型 + 相关性评估。

        一次 AI 调用处理最多 20 条法规。将原本 2×N 次 API 调用合并为 1 次。

        Args:
            items: [{"index": 0, "title": "...", "source_url": "...", "raw_text": "..."}, ...]

        Returns:
            [{"index": 0, "content_type": "regulation", "impact_level": "高",
              "business_domains": [...], "core_summary": "..."}, ...]
            失败时返回空列表（调用方走逐条回退）。
        """
        if not items:
            return []

        validated = []
        for it in items:
            raw = (it.get("raw_text") or "")[:2000]
            if not raw.strip():
                continue
            validated.append({
                "index": it["index"],
                "title": (it.get("title") or "")[:200],
                "source_url": (it.get("source_url") or "")[:300],
                "raw_text": raw,
            })

        if not validated:
            return []

        batch_size = 20
        all_results: list[dict] = []

        for i in range(0, len(validated), batch_size):
            batch = validated[i:i + batch_size]
            try:
                ai = await self._get_ai_service()
                response = await ai.chat(
                    messages=[
                        {"role": "system", "content": self.BATCH_CLASSIFY_ASSESS_PROMPT},
                        {"role": "user", "content": self.BATCH_CLASSIFY_USER_TEMPLATE.format(
                            items_json=_json.dumps(batch, ensure_ascii=False),
                        )},
                    ],
                    response_format="json_object",
                    temperature=0.0,
                    max_tokens=4096,
                )
                data = _json.loads(response)
                batch_results = data.get("results", [])
                if isinstance(batch_results, list):
                    all_results.extend(batch_results)
                else:
                    logger.warning("batch classify: unexpected results format, falling back")
                    return []
            except Exception:
                logger.exception("batch classify+assess failed at batch offset=%d", i)
                return []  # 批量失败 → 调用方走逐条回退

        logger.info(
            "batch classify+assess: %d items → %d results (%d API calls)",
            len(validated), len(all_results),
            (len(validated) + batch_size - 1) // batch_size,
        )
        return all_results

    # ═══════════════════════════════════════════════════════════
    # ④ 新旧法规对比
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def has_revision_indicator(title: str) -> bool:
        """检测标题是否包含修订/替代关键词。"""
        return bool(REVISION_KEYWORDS.search(title))

    # ═══════════════════════════════════════════════════════════
    # ③.5 行业相关性终判（Layer 3：AI 判定）
    # ═══════════════════════════════════════════════════════════

    _INDUSTRY_CHECK_CACHE: dict[str, bool] = {}

    async def check_industry_relevance(
        self, title: str, summary: str = "",
    ) -> bool:
        """AI 判定：该法规是否适用于原料药制药工厂的安全/环保管理。

        返回 True=相关（放行），False=不相关（过滤）。
        带进程内缓存，相同 title 不重复调用 AI。
        """
        cache_key = title.strip()
        if cache_key in self._INDUSTRY_CHECK_CACHE:
            return self._INDUSTRY_CHECK_CACHE[cache_key]

        # 截断输入
        context = f"标题: {title}"
        if summary:
            context += f"\n摘要: {summary[:300]}"

        try:
            ai = await self._get_ai_service()
            response = await ai.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一名原料药（化学合成+发酵）制药工厂的安全环保法规专员。"
                            "你的任务是判断给定的法规/标准标题是否可能适用于该工厂的安全管理或环境保护工作。\n\n"
                            "判定为【是】的情况：\n"
                            "- 通用安全：安全生产、消防防火、职业病防治、应急预案、事故调查、"
                            "危险化学品、特种设备、压力容器、锅炉、防爆电气、有限空间、"
                            "动火/高处/吊装等特殊作业、劳动防护用品（PPE/个体防护）\n"
                            "- 环境保护：排污许可、废水/废气/固废、VOCs、清洁生产、环境影响评价、"
                            "危险废物、噪声污染\n"
                            "- 制药工业、原料药、化学合成、发酵相关的生产/质量/设备安全标准\n"
                            "- 通用工业设备安全：机械、电气、计量、包装、焊接、涂装、储运\n\n"
                            "判定为【否】的情况（即使标题含\"安全/防护/标准/规范\"等字眼也要否定）：\n"
                            "- 农业/种植/林业：种子、种苗、菌种、苗木、造林、粮食作物、果蔬、花卉、林业\n"
                            "- 畜牧/兽医/渔业/水产：畜禽、兽医、动物检疫、生猪、牛、羊、羊毛、山羊绒、"
                            "冷冻精液、饲料、兽药、养殖、水产、渔\n"
                            "- 医疗器械/医用：外科植入物、植入物、医疗器械、医用耗材、齿科、骨科、"
                            "体外诊断、心血管、人工器官\n"
                            "- 食品/饮料/烟草：食品、饮料、调味品、乳制品、罐头、烟草\n"
                            "- 体育/健身/玩具/文体：运动服装、体育器材、健身器械、玩具\n"
                            "- 养老/民生/社会服务：养老机构、老年人、社会福利\n"
                            "- 核电/军工/航空/航天/船舶/铁路/道路/桥梁/水利/农业机械等非工业安全行业\n"
                            "- 其他行业专属标准（即使涉及环境保护/污染控制也属【否】）：纺织、印染、"
                            "造纸、皮革、电子电器、废光伏、矿山、矿区、石油天然气开采、船舶、汽车、"
                            "食品加工、农业等特定行业的生产/排放/污染控制标准\n"
                            "- 仅适用于特定地域或特定地理对象的公告/标准（某条河流、流域、库区、水库、"
                            "湖泊、倾倒区、远海，或其他省市地方标准）\n"
                            "- 检测/分析类方法标准：检测对象与本厂排放、职业危害、生产过程无关"
                            "（如土壤/水体农药残留、藻毒素、水生生物、物种调查、环境背景监测、"
                            "特定行业仪器技术要求）\n"
                            "- 工作通知、人事任免、表彰、报告、决算等非法规文档\n\n"
                            "判定要点：本厂为化工原料药（化学合成+发酵）工厂，标准必须能直接适用于"
                            "本厂的安全管理、职业健康、污染物（废水/废气/固废/VOCs）排放控制或药品生产"
                            "才为【是】；仅对\"污水处理\"\"安全生产\"\"环境保护\"等泛词匹配、但适用对象"
                            "为其他行业或特定地域的，一律【否】\n\n"
                            "仅回答一个汉字：是 或 否"
                        ),
                    },
                    {"role": "user", "content": context},
                ],
                temperature=0.0,
                max_tokens=16,
            )
            # AI 可能返回: "是" / "否" / true / {"result": "是"} / {"applicable": true} / {"是": true} 等
            text = response.strip()
            # 尝试 JSON 解析
            try:
                data = _json.loads(text)
                if isinstance(data, dict):
                    # 兼容中文键响应（模型常输出 {"是": true} / {"否": true} / {"相关": true} / {"不相关": true}）
                    cn_key = next((k for k in ("是", "相关", "否", "不相关") if k in data), None)
                    if cn_key is not None:
                        cn_val = data[cn_key]
                        if isinstance(cn_val, bool):
                            result = cn_val
                        elif isinstance(cn_val, str):
                            result = "是" in cn_val or "相关" in cn_val
                        else:
                            result = False
                        # {"否": true} / {"不相关": true} 表示否定，翻转结果
                        if cn_key in ("否", "不相关"):
                            result = not result
                    else:
                        val = data.get("result") or data.get("applicable") or data.get("relevant")
                        if isinstance(val, bool):
                            result = val
                        elif isinstance(val, str):
                            result = "是" in val
                        else:
                            result = False
                else:
                    # JSON 裸布尔值 true/false
                    if isinstance(data, bool):
                        result = data
                    else:
                        result = "是" in str(data)
            except _json.JSONDecodeError:
                # 非 JSON：直接判断
                result = ("是" in text or "相关" in text) and "否" not in text and "不相关" not in text
        except Exception:
            logger.exception(
                "AI 行业相关性判定失败，降级过滤（fail-closed）: %s", title,
            )
            # 失败时过滤而非放行：避免 AI 偶发故障把无关法规误写入知识库。
            # 被过滤的条目未入库，下周预去重不会跳过，会自动重新判定并恢复。
            result = False

        self._INDUSTRY_CHECK_CACHE[cache_key] = result
        if not result:
            logger.info("AI 判定行业不相关: %s", title[:80])
        return result

    async def compare_with_previous(
        self,
        new_item: CrawledRegulation,
        old_title: str,
        old_publish_date: str = "",
        old_summary: str = "",
    ) -> CrawledRegulation:
        """对比新旧法规，填充 comparison_summary 和 related_old_title。

        原地修改传入的 CrawledRegulation 并返回。
        """
        new_item.related_old_title = old_title

        try:
            ai = await self._get_ai_service()
            response = await ai.chat(
                messages=[
                    {"role": "system", "content": COMPARE_SYSTEM_PROMPT},
                    {"role": "user", "content": COMPARE_USER_TEMPLATE.format(
                        new_title=new_item.title,
                        new_publish_date=new_item.publish_date or "未知",
                        new_summary=new_item.core_summary or new_item.raw_text or "无",
                        old_title=old_title,
                        old_publish_date=old_publish_date or "未知",
                        old_summary=old_summary or "无",
                    )},
                ],
                response_format="json_object",
                temperature=0.1,
                max_tokens=1024,
            )
            data = _json.loads(response)
        except Exception:
            logger.exception("法规对比失败: new=%s old=%s", new_item.title, old_title)
            return new_item

        new_item.comparison_summary = (data.get("comparison_summary") or "").strip() or None
        return new_item


class RegexExtractor:
    """正则回退提取器：不依赖 AI，纯模式匹配。"""

    def extract(
        self,
        raw_text: str,
        source_url: str = "",
        source_type: str = "",
    ) -> CrawledRegulation | None:
        """从文本中用正则提取法规字段。"""
        if not raw_text:
            return None

        title = self._extract_title(raw_text)
        if not title:
            return None

        return CrawledRegulation(
            title=title,
            document_number=self._extract_doc_number(raw_text),
            publish_date=self._extract_date(raw_text),
            implementation_date=None,
            issuing_authority=self._extract_authority(raw_text),
            regulation_level=None,
            status=None,
            source_url=source_url,
            source_type=source_type,
            raw_text=raw_text[:8000],
        )

    @staticmethod
    def _extract_title(text: str) -> str | None:
        for pattern in TITLE_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return m.group(1) if "《" in pattern else m.group(0)
        return None

    @staticmethod
    def _extract_doc_number(text: str) -> str | None:
        for pattern in DOC_NUMBER_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return m.group(0)
        return None

    @staticmethod
    def _extract_date(text: str) -> str | None:
        m = DATE_PATTERN.search(text)
        if m:
            y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
            return f"{y}-{mo}-{d}"
        return None

    @staticmethod
    def _extract_authority(text: str) -> str | None:
        """尝试提取发布机关。"""
        patterns = [
            r"([一-龥]{2,10}(?:部|委员会|总局|局|办公厅|办公室|人民政府))",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m.group(1)
        return None
