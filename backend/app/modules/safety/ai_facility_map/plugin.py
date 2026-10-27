"""AI 地点→分区建议映射插件 — 核心引擎（#2）。

用法:
    from app.modules.safety.ai_facility_map import FacilityMapSuggestPlugin

    plugin = FacilityMapSuggestPlugin(ai_service)  # create_ai_service("text")
    suggestions = await plugin.suggest([("212罐", 23), ("新罐区", 5)])

场景键：facility_map_suggest（temp 0.1 低温批量判定）。产物是建议清单：
dist_id 校验必须落在 64 分区内（否则置 None），medium 归一 mid，text
回显必须与输入原文一致（防 AI 改写串行）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.modules.safety.ai_facility_map.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.safety.ai_facility_map.schemas import (
    CONFIDENCE_MID,
    VALID_CONFIDENCE,
    DistrictSuggestion,
)
from app.modules.safety.service.facility_map.district_names import DISTRICT_IDS

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = ["suggestions"]

# AI 可能输出 medium（后端既有 vision 链口径），统一归一为 mid
_CONFIDENCE_ALIASES = {"medium": CONFIDENCE_MID, "中": CONFIDENCE_MID}

# 模型回显 text 时可能带上的输入行装饰（编号前缀/频次后缀），剥掉再匹配
_ECHO_NOISE = (
    (re.compile(r"（近段出现 \d+ 次）$"), ""),
    (re.compile(r"^\d+[.、]\s*"), ""),
)


def _normalize_echo(text: str) -> str:
    cleaned = text.strip()
    for pattern, repl in _ECHO_NOISE:
        cleaned = pattern.sub(repl, cleaned).strip()
    return cleaned


class FacilityMapSuggestError(Exception):
    """建议批生成失败（AI 调用或输出解析）。"""


class FacilityMapSuggestPlugin:
    """待映射地点文本批 → 分区建议清单（每批 ≤20 条）。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def suggest(
        self, items: list[tuple[str, int]]
    ) -> list[DistrictSuggestion]:
        if not items:
            return []
        prompt = build_user_prompt(items)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=_EXPECTED_KEYS,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("地点→分区建议 AI 调用失败（%d 条批）: %s", len(items), e)
            raise FacilityMapSuggestError(f"AI 调用失败: {e}") from e
        return self._parse_output(raw, known_texts=[t for t, _ in items])

    @staticmethod
    def _parse_output(
        raw: Any, *, known_texts: list[str]
    ) -> list[DistrictSuggestion]:
        if not isinstance(raw, dict):
            raise FacilityMapSuggestError(f"AI 输出非 dict: {type(raw).__name__}")
        rows = raw.get("suggestions") or []
        if not isinstance(rows, list):
            raise FacilityMapSuggestError("AI 输出 suggestions 非数组")
        known = set(known_texts)
        out: list[DistrictSuggestion] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = _normalize_echo(str(row.get("text") or ""))
            if not text or text not in known:
                continue  # 回显与输入不一致（改写/幻觉行）丢弃
            dist_id = row.get("dist_id")
            dist_id = str(dist_id).strip() if dist_id is not None else ""
            if dist_id and dist_id not in DISTRICT_IDS:
                dist_id = ""  # 幻觉 distId 不入表
            confidence = str(row.get("confidence") or "").strip().lower()
            confidence = _CONFIDENCE_ALIASES.get(confidence, confidence)
            if confidence not in VALID_CONFIDENCE:
                confidence = "low"
            reason = str(row.get("reason") or "").strip()[:512]
            out.append(DistrictSuggestion(
                text=text,
                dist_id=dist_id or None,
                confidence=confidence,
                reason=reason,
            ))
        return out
