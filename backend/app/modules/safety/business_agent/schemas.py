"""业务 Agent 的依赖对象、数据模型与 API 契约。

- ``SafetyDeps``：注入 Pydantic AI ``RunContext`` 的依赖（db / 当前用户 / 角色 / 会话）。
  工具函数通过 ``ctx.deps`` 拿到 db 和当前用户身份 → 承载「身份 + 权限」贯穿每次工具调用。
- ``PendingActionData`` / ``PendingActionStatus``：写操作挂起为「待确认动作」的载体。
- ``AgentChatRequest`` / ``AgentChatResponse``：Web 入口 API 契约。

本文件不 import pydantic-ai，仅用 dataclass + Pydantic v2；SafetyDeps 只是普通 dataclass，
供 ``agent.py`` 以 ``deps_type=SafetyDeps`` 使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.safety.feishu.identity_resolver import ResolvedPerson
    from app.modules.safety.feishu.office_client import FeishuOfficeClient


# ═══════════════════════════════════════════════════════════════
# 依赖注入对象（RunContext.deps）
# ═══════════════════════════════════════════════════════════════


@dataclass
class SafetyDeps:
    """注入 Pydantic AI RunContext 的依赖。

    Attributes:
        db: 当前请求的异步 DB 会话（工具用它调各业务 service）
        person: 已识别的当前用户（None 表示未识别到身份 → 应拒绝一切工具）
        role: 当前用户的固定角色（见 permissions.py；None/未知 → deny-by-default）
        session_id: 会话 ID（用于会话历史与 PendingAction 归属）
        channel: 入口渠道（web / feishu），写入 AI 调用审计
        office_client: 飞书办公客户端（测试注入用；None = 工具层用默认真实实现）
        chat_id: 飞书会话 chat_id（web 渠道为 None）；工具用于把生成文件回传到当前会话，None 时降级提示
    """

    db: AsyncSession
    person: ResolvedPerson | None
    role: str | None
    session_id: str
    channel: str | None = None
    office_client: FeishuOfficeClient | None = None
    chat_id: str | None = None


# ═══════════════════════════════════════════════════════════════
# 待确认动作（写操作挂起）
# ═══════════════════════════════════════════════════════════════


class PendingActionStatus(StrEnum):
    PENDING = "pending"        # 已生成方案，等待用户确认
    CONFIRMED = "confirmed"    # 用户已确认，待执行
    EXECUTED = "executed"      # 已执行成功
    REJECTED = "rejected"      # 用户取消
    FAILED = "failed"          # 执行失败
    EXPIRED = "expired"        # 超时未确认


class PendingActionData(BaseModel):
    """一次挂起的写操作方案。"""

    tool_name: str = Field(description="将要执行的写工具名（见 permissions.py）")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="工具调用参数"
    )
    summary: str = Field(description="面向用户的执行方案复述（人类可读）")
    status: PendingActionStatus = PendingActionStatus.PENDING


# ═══════════════════════════════════════════════════════════════
# Web 入口 API 契约
# ═══════════════════════════════════════════════════════════════


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, description="用户输入")
    session_id: str | None = Field(
        default=None, description="会话 ID；为空则新建会话"
    )


class AgentChatResponse(BaseModel):
    session_id: str
    answer: str = Field(description="Agent 的自然语言回复")
    pending_action_id: str | None = Field(
        default=None,
        description="若本轮产生了待确认的写操作，返回其 ID；前端据此弹确认框",
    )
    pending_action: PendingActionData | None = None
