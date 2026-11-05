"""AI隐患评分插件 — 核心引擎。

对标 ai_rectification_review / ai_hazard_identification 的插件模式：
低温度 0.05 + chat_parsed 强类型解析 + rules 校验（非法档位抛 ScoringError，
调用方⑤轮语义=不写任何列、下轮重试）。总分由 rules.compute_total 计算，
AI 不参与算术。
"""

from __future__ import annotations

import logging
import time

from app.modules.safety.ai_hazard_scoring.prompts import (
    SYSTEM_ROLE,
    build_context_text,
    build_full_prompt,
    get_expected_keys,
)
from app.modules.safety.ai_hazard_scoring.rules import (
    ScoringError,
    validate_output,
)
from app.modules.safety.ai_hazard_scoring.schemas import (
    HazardScoringInput,
    HazardScoringOutput,
    PluginConfig,
)

logger = logging.getLogger(__name__)


class AIHazardScorer:
    """AI隐患评分器 — 稳定、可复现、可独立测试。

    用法:
        from app.modules.safety.service.config import create_ai_service
        ai_service = create_ai_service("text")
        scorer = AIHazardScorer(ai_service)
        output = await scorer.score(input_data)   # HazardScoringOutput
        total = compute_total(output)             # 代码算总分
    """

    def __init__(
        self,
        ai_service,
        config: PluginConfig | None = None,
    ) -> None:
        self.ai_service = ai_service
        self.config = config or PluginConfig()

    async def score(self, input_data: HazardScoringInput) -> HazardScoringOutput:
        """执行评分：AI 选档位 → rules 校验 → 强类型输出。

        Raises:
            ScoringError: AI 调用失败或输出档位非法。
        """
        start = time.monotonic()
        context = build_context_text(input_data)
        prompt = build_full_prompt(context)
        messages = [
            {"role": "system", "content": SYSTEM_ROLE},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=get_expected_keys(),
                temperature=self.config.temperature,
            )
        except ScoringError:
            raise
        except Exception as exc:
            logger.error("评分 AI 调用失败: %s", exc)
            raise ScoringError(f"AI 调用失败: {exc}") from exc

        output = validate_output(raw)
        elapsed = time.monotonic() - start
        logger.info(
            "评分完成 — hazard_no=%s L=%s E=%s C=%s X=%s band=%s hit=%s elapsed=%.2fs",
            input_data.hazard_no,
            output.likelihood.value, output.exposure.value,
            output.consequence.value, output.difficulty.value,
            output.band.value, output.major_hazard.hit, elapsed,
        )
        return output
