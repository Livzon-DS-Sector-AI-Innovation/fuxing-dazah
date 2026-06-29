"""脚本1 AttachmentParser — 附件解析 Plugin。

对标 AIHazardIdentifier 的 4-phase pipeline：
  阶段一：预处理 — 检查附件文本可用性
  阶段二：AI 分析 — 调用文本 AI 提取作业信息
  阶段三：解析验证 — AttachmentRuleEngine + auto_correct
  阶段四：输出 — AttachmentOutput

用法:
    from app.modules.safety.ai_hazard_identification.script1_attachment import AttachmentParser

    plugin = AttachmentParser(ai_service, config, knowledge_context)
    output = await plugin.identify(AttachmentInput(
        department="提炼二部", position="反应岗位",
        production_step="加盐酸调pH", attachment_text="...",
    ))
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.modules.safety.ai_hazard_identification._base import (
    BasePlugin,
    PluginError,
)
from app.modules.safety.ai_hazard_identification.schemas import PluginConfig
from app.modules.safety.ai_hazard_identification.script1_attachment.prompts import (
    EXPECTED_KEYS,
    SYSTEM_ROLE,
    build_prompt,
)
from app.modules.safety.ai_hazard_identification.script1_attachment.rules import (
    AttachmentRuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.script1_attachment.schemas import (
    AttachmentInput,
    AttachmentOutput,
)

logger = logging.getLogger(__name__)


class AttachmentParser(BasePlugin[AttachmentInput, AttachmentOutput]):
    """脚本1: 附件解析 Plugin。

    从 SOP/操作规程附件文本中提取：
    - specific_activity: 具体作业活动
    - equipment_facilities: 设备设施
    - raw_auxiliary_materials: 原辅料
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        super().__init__(ai_service, config, knowledge_context)
        self.rule_engine = AttachmentRuleEngine()

    # ═══════════════════════════════════════════════════════════
    # 阶段一：预处理
    # ═══════════════════════════════════════════════════════════

    async def _preprocess(self, input_data: AttachmentInput) -> None:
        """检查附件文本可用性。"""
        if not input_data.attachment_text:
            logger.info(
                "[AttachmentParser] 附件文本为空 — 将要求 AI 输出「待人工确认」"
            )
        elif len(input_data.attachment_text) < 50:
            logger.warning(
                "[AttachmentParser] 附件文本过短（%d 字符），可能提取不充分",
                len(input_data.attachment_text),
            )
        else:
            logger.info(
                "[AttachmentParser] 附件文本长度: %d 字符",
                len(input_data.attachment_text),
            )

    # ═══════════════════════════════════════════════════════════
    # 子类必须实现
    # ═══════════════════════════════════════════════════════════

    def _get_system_role(self) -> str:
        return SYSTEM_ROLE

    def _build_prompt(
        self, input_data: AttachmentInput, context_text: str,
    ) -> str:
        return build_prompt(context_text, self.knowledge_context)

    def _get_expected_keys(self) -> list[str]:
        return EXPECTED_KEYS

    def _parse_output(self, raw: dict) -> AttachmentOutput:
        """将 AI 返回的字典解析为强类型输出。"""
        try:
            return AttachmentOutput(
                specific_activity=raw.get("specific_activity", "待人工确认"),
                equipment_facilities=raw.get("equipment_facilities", "待人工确认"),
                raw_auxiliary_materials=raw.get("raw_auxiliary_materials", "待人工确认"),
            )
        except (PydanticValidationError, KeyError, TypeError) as e:
            raise PluginError(
                f"[AttachmentParser] AI 输出解析失败: {e}"
            ) from e

    def _validate(
        self, input_data: AttachmentInput, output: AttachmentOutput,
    ) -> list[str]:
        """使用 AttachmentRuleEngine 验证输出。"""
        return self.rule_engine.validate(input_data, output)

    # ═══════════════════════════════════════════════════════════
    # 自动修正
    # ═══════════════════════════════════════════════════════════

    def _auto_correct(self, output: AttachmentOutput) -> AttachmentOutput:
        """去除空白、保障非空字段。"""
        return auto_correct(output)
