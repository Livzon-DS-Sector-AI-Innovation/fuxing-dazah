"""记忆提取器 —— 从对话中提取结构化记忆。

DEPRECATED（S5 ``core/memory.py core.memory.extract_from_events`` 从事件流取数提取、
``extract_and_save`` 用例走 store 覆盖式 upsert）：本模块的 ``extract`` 逻辑被 core 层复用
（不改 LLM prompt），``extract_and_save`` 不再承担新写入职责（冲突合并改走
``core.memory.merge_on_conflict``）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from app.modules.safety.memory.schemas import MemoryExtractionResult, MemoryFact

if TYPE_CHECKING:
    from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

# ── 提取 system prompt（固定不变 → 前缀缓存友好）─────────────────

_EXTRACTION_SYSTEM_PROMPT = """你是记忆提取器，从用户与安全助手的对话中提取值得跨会话保存的信息。

## ⚠️ 不要提取系统已知信息

系统每次对话自动注入用户身份（姓名、部门、角色），以下内容**禁止提取**：
- ❌ "用户姓名：XXX" → 系统已知
- ❌ "用户部门：XXX" → 系统已知
- ❌ "用户角色：XXX" → 系统已知
- ❌ "用户是XXX，属于XXX部门" → 纯冗余

## 记忆类型

- **episode**（最有价值，每轮至少 1 条）：具体操作或查询。
  如"查询了防爆电气法规""查看了原料药生产部近一周隐患""创建了动火作业预案"
- **preference**（从行为推断）：用户偏好或习惯。
  如"默认关注原料药生产部""查询隐患时偏好看待整改状态"
- **fact**（身份之外的重要事实）：用户透露的非身份信息。
  如"负责3号车间""正在进行GMP认证""下月有外部审计"
- **workflow**（跨多轮确认）：反复出现的操作模式。
  如"每月初检查防爆电气""每次查完隐患都导出报告"

## 输出规则

1. 每轮对话**至少提取 1 条 episode**（用户做了什么操作/查询了什么）
2. 每条记忆必须独立可理解——不要依赖对话上下文。
3. 记忆内容不要写"用户"开头，直接描述行为：❌"用户查询了防爆电气" → ✅"查询过防爆电气法规"
4. confidence: 显式操作 → 1.0；推断偏好 → 0.7-0.8
5. importance: 偏好 → 0.8；重要事实 → 0.7-0.9；操作记录 → 0.5-0.7
6. 没有值得保存的信息时返回空 facts 数组。
7. 不要编造或猜测——只提取对话中确实出现或明确可推断的信息。

## 输出格式

{"facts": [{"memory_type": "...", "content": "...", "confidence": 0.9, "importance": 0.8}]}"""


class MemoryExtractor:
    """从对话中提取结构化记忆。

    用法::

        extractor = MemoryExtractor()
        facts = await extractor.extract(user_message, agent_reply, deps)
        # → list[MemoryFact]（可能为空）
    """

    # ── 单例缓存 ──
    _embedder: object | None = None

    async def _get_embedder(self):
        """获取 EmbeddingService 单例（懒加载）。"""
        if self._embedder is None:
            from app.modules.safety.knowledge.embedding_service import EmbeddingService
            self._embedder = EmbeddingService()
        return self._embedder

    # ── 公共接口 ──

    async def extract(
        self,
        user_message: str,
        agent_reply: str,
        deps: SafetyDeps,
    ) -> list[MemoryFact]:
        """从一轮对话中提取候选记忆。

        不访问数据库，只做 LLM 提取 + 基本的合理性过滤。

        Returns:
            MemoryFact 列表；提取失败或无可保存内容时返回空列表。
        """
        if not deps.person or not deps.person.user_id:
            return []

        try:
            from app.modules.safety.service.config import create_ai_service

            ai_service = create_ai_service("text")

            # 构建 user prompt（对话内容放这里 → 前缀缓存友好）
            user_context = f"用户：{deps.person.name}"
            if deps.person.department:
                user_context += f"（{deps.person.department}）"
            if deps.role:
                user_context += f" [角色: {deps.role}]"

            user_prompt = (
                f"{user_context}\n\n"
                f"用户消息：{user_message[:500]}\n"
                f"助手回复：{agent_reply[:500]}\n\n"
                f"请从以上对话中提取值得长期保存的记忆。"
            )

            try:
                parsed = await ai_service.chat_parsed(
                    messages=[
                        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    expected_keys=["facts"],
                    temperature=0.1,
                )
            finally:
                await ai_service.close()

            result = MemoryExtractionResult.model_validate(parsed)
            valid_facts = self._filter_facts(result.facts)
            if valid_facts:
                logger.debug(
                    "Memory extraction: %d facts from user=%s",
                    len(valid_facts), deps.person.name,
                )
            return valid_facts

        except Exception:
            logger.debug("Memory extraction failed, skipping", exc_info=True)
            return []

    def _filter_facts(self, facts: list[MemoryFact]) -> list[MemoryFact]:
        """过滤低质量记忆。"""
        kept = []
        for f in facts:
            if not f.content or len(f.content.strip()) < 3:
                continue
            if f.memory_type not in ("fact", "preference", "episode", "workflow"):
                continue
            if f.confidence < 0.5:
                continue
            f.content = f.content.strip()
            kept.append(f)
        return kept

    # ── 提取 + 存储（供 executor 异步调用）──

    async def extract_and_save(
        self,
        user_message: str,
        agent_reply: str,
        deps: SafetyDeps,
        *,
        source_session_id: UUID | None = None,
        source_message_id: UUID | None = None,
    ) -> int:
        """提取事实 → 生成 embedding → 去重 → 保存到 agent_memories。

        使用独立 DB session 写入，失败不影响主业务。

        Returns:
            成功保存的记忆条数。
        """
        if not deps.person or not deps.person.user_id:
            return 0

        # 审计归因：整个记忆提取管线（LLM 提取 + embedding 去重）归入 memory_extraction
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="memory_extraction",
            session_id=deps.session_id or None,
            channel=deps.channel,
            user_name=deps.person.name if deps.person else None,
        ):
            facts = await self.extract(user_message, agent_reply, deps)
            if not facts:
                return 0

            user_id = deps.person.user_id

            try:
                from app.core.database import async_session_factory
                from app.modules.safety.memory.store import MemoryStore

                embedder = await self._get_embedder()

                async with async_session_factory() as db:
                    store = MemoryStore(db)
                    saved = 0

                    for fact in facts:
                        try:
                            # 生成 embedding（供去重 + 后续语义检索）
                            embedding = await embedder.embed(fact.content)
                        except Exception:
                            logger.debug("Embedding failed for memory, using None", exc_info=True)
                            embedding = None

                        memory = await store.upsert(
                            user_id=user_id,
                            memory_type=fact.memory_type,
                            content=fact.content,
                            embedding=embedding,
                            importance=fact.importance,
                            confidence=fact.confidence,
                            source_session_id=source_session_id,
                            source_message_id=source_message_id,
                        )
                        if memory:
                            saved += 1

                    if saved:
                        await db.commit()
                        logger.info(
                            "Memory saved: %d facts for user=%s", saved, deps.person.name,
                        )
                    return saved

            except Exception:
                logger.exception("Memory extract_and_save failed")
                return 0
