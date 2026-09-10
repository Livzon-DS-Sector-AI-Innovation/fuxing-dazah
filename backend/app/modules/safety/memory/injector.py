"""记忆注入适配层 —— 将用户上下文和相关记忆注入 Agent 对话。

设计原则：
  - Phase 1：静态用户上下文（name/role/department），不涉及记忆检索
  - Phase 2-3：扩展到语义记忆检索结果注入
  - 注入到 user message 前缀（前缀缓存友好，不修改共享 agent 对象）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.safety.business_agent.schemas import SafetyDeps

# ── 角色中文标签 ──
_ROLE_LABELS: dict[str, str] = {
    "safety_admin": "安全管理员",
    "dept_leader": "部门负责人",
    "inspector": "检查人员",
    "viewer": "只读用户",
}


def _role_display(role: str | None) -> str:
    """将角色 slug 转为人可读的中文标签。"""
    if role is None:
        return "未授权"
    return _ROLE_LABELS.get(role, role)


class MemoryInjector:
    """将用户上下文和记忆注入 Agent 对话。"""

    # ── Phase 1：静态用户上下文 ──

    @staticmethod
    def build_user_context(deps: SafetyDeps) -> str:
        """从 SafetyDeps 构建用户上下文文本（无 LLM 调用，无 DB 查询）。

        注入到 user message 前缀，让模型在不修改 system prompt 的前提下
        了解当前用户的基本信息。

        Returns:
            用户上下文文本，形如：
            "[系统上下文] 当前用户：佘祥辉 | 角色：安全管理员 | 部门：原料药生产部"
            若 deps.person 为 None，返回空字符串。
        """
        if deps.person is None:
            return ""

        parts: list[str] = []
        if deps.person.name:
            parts.append(f"当前用户：{deps.person.name}")
        if deps.role:
            parts.append(f"角色：{_role_display(deps.role)}")
        if deps.person.department:
            parts.append(f"部门：{deps.person.department}")

        if not parts:
            return ""

        return "[系统上下文] " + " | ".join(parts)

    # ── Phase 3（规划）：记忆上下文注入 ──

    @staticmethod
    def inject_memory_context(
        user_message: str,
        memories: list | None = None,
        user_context: str = "",
    ) -> str:
        """将用户上下文和相关记忆注入到 user message 前缀。

        DEPRECATED：S4 ``core/prompt.py`` 分节组装后，「memories + user_context」已迁至
        ``assemble(ALL_SECTIONS, deps, context)`` 统一前缀注入（\\n\\n 分隔）。本方法保留
        兼容期（避免未更新调用方不 404），不再承担新的注入职责。

        注入顺序：用户上下文 → 相关记忆 → 分隔线 → 原始消息

        Args:
            user_message: 用户原始输入
            memories: 检索到的相关记忆列表（Phase 3 启用）
            user_context: build_user_context() 的输出

        Returns:
            增强后的完整消息文本。
        """
        parts: list[str] = []

        if user_context:
            parts.append(user_context)

        if memories:
            lines = ["相关记忆："]
            for m in memories:
                content = getattr(m, "content", str(m))
                lines.append(f"  - {content}")
            parts.append("\n".join(lines))

        if not parts:
            return user_message

        parts.append("---")
        parts.append(user_message)
        return "\n".join(parts)
