"""system-prompt 分节组装（S4）。

替代散在 executor / loader / MemoryInjector 三处的隐式 prompt 拼接，改为按节组装：

- ``persona``（agent.md 全文，静态）
- ``runtime_date``（每轮动态日期）
- ``user_context``（当前用户身份/角色/部门）
- ``memories``（检索到的相关记忆）
- ``tool_catalog``（当前角色可见工具目录，替代 tool_selector 关键词选子集）

``assemble(sections, deps, context)`` 按 ``order`` 升序渲染、过滤空节、以 ``\\n\\n`` 拼接，
顺序确定、各节可独立开启/关闭（US6）。

注入策略：``persona`` 节仍走 ``loader.load_instructions()``（在 agent.md 原文基础上拼接动态
date_hint，保留入口兼容）；本模块的 ``RuntimeDateSection`` 单独渲染动态日期，供 user message
前缀注入（与现状 ``MemoryInjector`` 前缀注入位置一致，前缀缓存友好）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.modules.safety.business_agent.core.permissions import allowed_tools

if TYPE_CHECKING:
    from app.modules.safety.business_agent.schemas import SafetyDeps

# 角色中文标签（迁自 memory/injector.py 的 _ROLE_LABELS，保持展示一致）
_ROLE_LABELS: dict[str, str] = {
    "safety_admin": "安全管理员",
    "dept_leader": "部门负责人",
    "inspector": "检查人员",
    "viewer": "只读用户",
}

_APP_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai


def _role_display(role: str | None) -> str:
    """将角色 slug 转为人可读的中文标签；None/未知回退为角色自带。"""
    if role is None:
        return "未授权"
    return _ROLE_LABELS.get(role, role)


def _render_runtime_date(now: datetime) -> str:
    """渲染当前日期/星期/本周（逻辑迁自 loader.load_instructions 的 date_hint）。"""
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    this_month = now.strftime("%Y年%m月")
    this_week = now.isocalendar()[1]
    today_str = now.strftime("%Y-%m-%d")
    return (
        "# 系统信息\n\n"
        f"当前日期：{now.strftime('%Y年%m月%d日')} "
        f"（{today_str}，"
        f"星期{weekday_names[now.weekday()]}，"
        f"第{this_week}周）。"
        f"\n用户提到\"本月\"即指 {this_month}，"
        f"\"本周\"即指第{this_week}周，"
        f"\"今天\"即指 {today_str}。"
    )


@dataclass
class PromptSection:
    """system-prompt 的一节。

    ``render`` 返回非空字符串表示本节参与拼接；空字符串表示本节跳过。
    """

    name: str
    order: int  # 越小越靠前

    def render(self, deps: SafetyDeps, context: dict | None = None) -> str:
        """渲染本节文本；空字符串表示本节跳过。子类覆盖。"""
        raise NotImplementedError


@dataclass
class PersonaSection(PromptSection):
    """人设节：极简一行（agent.md 全文已由 agent.py 的 load_instructions() 注入 system）。"""

    name: str = "persona"
    order: int = -100

    def render(self, deps: SafetyDeps, context: dict | None = None) -> str:
        # agent.md 已作为 system instructions 注入（agent.py:65 load_instructions()），
        # 此处不再重复渲染全文（旧实现把 agent.md 拼进 user 前缀，浪费 token 并污染
        # 工具意图判定）。保留该节仅用于给模型人设定位。
        return "你是安全知识助手"


@dataclass
class RuntimeDateSection(PromptSection):
    """运行时日期节：当前日期/星期/本周（每轮动态）。"""

    name: str = "runtime_date"
    order: int = -50
    _now: datetime | None = field(default=None, repr=False, compare=False)

    def render(self, deps: SafetyDeps, context: dict | None = None) -> str:
        now = self._now or datetime.now(_APP_TZ)
        return _render_runtime_date(now)


@dataclass
class UserContextSection(PromptSection):
    """用户上下文节：当前用户 | 角色 | 部门（来自 SafetyDeps.person/role）。

    逻辑迁自 ``MemoryInjector.build_user_context``。
    """

    name: str = "user_context"
    order: int = 0

    def render(self, deps: SafetyDeps, context: dict | None = None) -> str:
        person = deps.person
        if person is None:
            return ""

        parts: list[str] = []
        if person.name:
            parts.append(f"当前用户：{person.name}")
        if deps.role:
            parts.append(f"角色：{_role_display(deps.role)}")
        if person.department:
            parts.append(f"部门：{person.department}")

        if not parts:
            return ""
        return "[系统上下文] " + " | ".join(parts)


@dataclass
class MemoriesSection(PromptSection):
    """相关记忆节：渲染检索到的记忆列表。

    memories 来自 ``context["memories"]``（list[str]，由 S5 core/memory.py 检索）。
    空列表返回空串（本节跳过）。本节只做渲染接口，实际检索在 S5。
    """

    name: str = "memories"
    order: int = 50

    def render(self, deps: SafetyDeps, context: dict | None = None) -> str:
        memories = (context or {}).get("memories") or []
        if not memories:
            return ""
        lines = ["相关记忆："]
        for i, m in enumerate(memories, start=1):
            content = getattr(m, "content", str(m))
            lines.append(f"  {i}. {content}")
        return "\n".join(lines)


@dataclass
class ToolCatalogSection(PromptSection):
    """工具目录节：当前角色可见工具名列表（来自 ``permissions.allowed_tools``）。

    role=None 返回空串（无工具可见，提示模型无法调用任何工具）。
    """

    name: str = "tool_catalog"
    order: int = 100

    def render(self, deps: SafetyDeps, context: dict | None = None) -> str:
        if deps.role is None:
            return ""
        tools = allowed_tools(deps.role)
        if not tools:
            return ""
        # 保持顺序稳定：排序输出，避免 set 迭代顺序不确定影响 assemble 稳定
        names = ", ".join(sorted(tools))
        return f"可用工具：{names}"


# ── 默认五节清单（顺序稳定；调用方可自定义节列表或以切片开关某节） ──
ALL_SECTIONS: list[PromptSection] = [
    PersonaSection(),
    RuntimeDateSection(),
    UserContextSection(),
    MemoriesSection(),
    ToolCatalogSection(),
]


def assemble(
    sections: list[PromptSection],
    deps: SafetyDeps,
    context: dict | None = None,
) -> str:
    """按 ``order`` 升序渲染各节，过滤空串，以 ``\\n\\n`` 拼接成 prompt 前缀。

    返回空串表示所有节均跳过（调用方按空串处理不拼接前缀）。
    """
    rendered: list[str] = []
    for sec in sorted(sections, key=lambda s: s.order):
        text = sec.render(deps, context)
        if text:
            rendered.append(text)
    return "\n\n".join(rendered)
