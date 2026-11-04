"""法规适用性深度分析（仅高关注项，借鉴 URS 三级适配范式）。

输入 = 法规标题 + 正文摘要（契约① content_digest）+ 企业业务画像 →
输出三级适用结论 + 理由 + 落地建议（制度/培训/时间节点）。
结果随 IngestItemResult 留痕（run.items_result）并进飞书卡片；
任何失败返回 None 降级（卡片标"分析待补"），绝不阻断收录链。
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any

logger = logging.getLogger(__name__)

APPLICABILITY_SYSTEM_PROMPT = """你是安全生产法规适用性分析专家。结合企业业务画像，判定给定法规对该企业的适用性，并给出可落地的建议。

## 判定口径（三级）
- applicable：企业须直接遵守（强制适用，业务/场所/设施在法规覆盖范围内）
- partially_applicable：部分条款适用（仅个别环节/设施/岗位涉及，需甄别执行）
- not_applicable：不适用（适用范围明确排除本企业，如其他行业专属、非本地区域法规）

## 判定依据优先级
1. 法规明示的适用范围/发文对象（正文中的"适用于…"条款）
2. 企业业务画像（行业/危化品/设备/危害因素/操规清单）
3. 无法确认时倾向 partially_applicable，并在理由中说明待确认点

## 输出格式（严格 JSON，不要输出其他内容）
{
  "applicability": "applicable | partially_applicable | not_applicable",
  "reasons": ["判定理由，≤3 条，每条 ≤80 字"],
  "suggestions": ["制度：需新建/修订哪些制度或操作规程", "培训：需对哪些人员开展什么培训", "时间：结合实施日期的建议完成节点"],
  "affected_domains": ["涉及的领域，如 危化品管理/职业健康/特种设备"]
}
"""

APPLICABILITY_USER_TEMPLATE = """请分析以下法规对本企业的适用性。

## 法规信息
- 名称：{title}

## 法规内容（已截断）
{content}

## 企业业务画像
{business_profile}
"""

_VALID_LEVELS = ("applicable", "partially_applicable", "not_applicable")
_MAX_CONTENT_CHARS = 4000
_MAX_LIST_ITEMS = 3
_MAX_ITEM_CHARS = 80


class ApplicabilityAnalyzer:
    """适用性深度分析器（LLM 调用与 AIExtractor 同源：create_ai_service）。"""

    def __init__(self) -> None:
        self._ai_service = None  # 延迟初始化，避免提前触发环境变量校验

    async def _get_ai_service(self) -> Any:
        if self._ai_service is None:
            from app.modules.safety.service.config import create_ai_service

            self._ai_service = create_ai_service("text")
        return self._ai_service

    async def analyze(
        self, title: str, content: str, business_profile: str,
    ) -> dict[str, Any] | None:
        """单条法规适用性分析；失败/坏输出返回 None（调用方降级）。"""
        if not (content and content.strip()):
            content = f"标题: {title}"
        truncated = content[:_MAX_CONTENT_CHARS]
        try:
            ai = await self._get_ai_service()
            response = await ai.chat(
                messages=[
                    {"role": "system", "content": APPLICABILITY_SYSTEM_PROMPT},
                    {"role": "user", "content": APPLICABILITY_USER_TEMPLATE.format(
                        title=title or "(未提供)",
                        content=truncated,
                        business_profile=business_profile or "(未提供)",
                    )},
                ],
                response_format="json_object",
                temperature=0.0,
                max_tokens=1024,
            )
            data = _json.loads(response)
        except Exception:
            logger.exception("适用性分析调用失败: title=%s", title)
            return None
        return self._normalize(data)

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any] | None:
        """输出清洗：三级值钳制 + 列表截断；无效整体弃用。"""
        level = str(data.get("applicability") or "").strip()
        if level not in _VALID_LEVELS:
            return None

        def _clean_list(key: str) -> list[str]:
            raw = data.get(key)
            if not isinstance(raw, list):
                return []
            items = [str(x).strip()[:_MAX_ITEM_CHARS] for x in raw if str(x).strip()]
            return items[:_MAX_LIST_ITEMS]

        return {
            "applicability": level,
            "reasons": _clean_list("reasons"),
            "suggestions": _clean_list("suggestions"),
            "affected_domains": _clean_list("affected_domains"),
        }
