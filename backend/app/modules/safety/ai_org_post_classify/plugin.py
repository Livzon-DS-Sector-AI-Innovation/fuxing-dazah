"""AI 岗位族归类插件 — 核心引擎（#4）。

用法:
    from app.modules.safety.ai_org_post_classify import OrgPostClassifyPlugin

    plugin = OrgPostClassifyPlugin(ai_service)  # create_ai_service("text")
    items = await plugin.classify(["1#冻干线冻干出料操作工", "QC化验员"])

场景键：org_post_classify（temp 0.1 低温批量判定）。family 越界（不在九族
枚举）丢弃该行（服务层按未返回落「其他/low」不覆盖已有行——未返回行
保持原状，下轮重跑再判）；medium 归一 mid；post_name 回显必须与输入一致。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.ai_org_post_classify.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.safety.ai_org_post_classify.schemas import (
    CONFIDENCE_MID,
    VALID_CONFIDENCE,
    PostFamilyItem,
)
from app.modules.safety.models.org_post_families import POST_FAMILIES

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = ["items"]
_VALID_FAMILIES = frozenset(POST_FAMILIES)
_CONFIDENCE_ALIASES = {"medium": CONFIDENCE_MID, "中": CONFIDENCE_MID}


class OrgPostClassifyError(Exception):
    """岗位归类批生成失败（AI 调用或输出解析）。"""


class OrgPostClassifyPlugin:
    """唯一岗位名批 → 九族归类清单（每批 ≤30 条）。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def classify(self, post_names: list[str]) -> list[PostFamilyItem]:
        if not post_names:
            return []
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(post_names)},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=_EXPECTED_KEYS,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("岗位族归类 AI 调用失败（%d 条批）: %s", len(post_names), e)
            raise OrgPostClassifyError(f"AI 调用失败: {e}") from e
        return self._parse_output(raw, known_names=post_names)

    @staticmethod
    def _parse_output(
        raw: Any, *, known_names: list[str]
    ) -> list[PostFamilyItem]:
        if not isinstance(raw, dict):
            raise OrgPostClassifyError(f"AI 输出非 dict: {type(raw).__name__}")
        rows = raw.get("items") or []
        if not isinstance(rows, list):
            raise OrgPostClassifyError("AI 输出 items 非数组")
        known = set(known_names)
        out: list[PostFamilyItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("post_name") or "").strip()
            family = str(row.get("family") or "").strip()
            if not name or name not in known:
                continue  # 回显与输入不一致（改写/幻觉行）丢弃
            if family not in _VALID_FAMILIES:
                continue  # 越界族丢弃（服务层按未返回处理）
            confidence = str(row.get("confidence") or "").strip().lower()
            confidence = _CONFIDENCE_ALIASES.get(confidence, confidence)
            if confidence not in VALID_CONFIDENCE:
                confidence = "low"
            out.append(PostFamilyItem(
                post_name=name,
                family=family,
                confidence=confidence,
                note=str(row.get("note") or "").strip()[:512],
            ))
        return out
