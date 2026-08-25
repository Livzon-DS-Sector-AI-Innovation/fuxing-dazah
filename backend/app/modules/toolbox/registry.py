"""工具箱工具注册表：装饰器声明 + tools/ 目录扫描。

每个工具一个 .py 文件，用 @tool 装饰器声明步骤与输入，
本模块在启动时扫描 tools/ 目录完成注册。不涉及数据库。
"""

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 声明式定义 ──


@dataclass(frozen=True)
class ToolInput:
    """工具输入声明。type: file / text / textarea / boolean / number / select / month / date。

    show_when=(key, value)：当同步骤中 key 字段的值为 value 时该输入才显示（如日期字段跟随核对方式）。
    """

    key: str
    label: str
    type: str
    accept: str | None = None
    required: bool = False
    multiple: bool = False
    default: Any = None
    placeholder: str | None = None
    options: list[str] | None = None
    from_step: str | None = None
    from_key: str | None = None
    show_when: tuple[str, str] | None = None


@dataclass(frozen=True)
class ToolStep:
    id: str
    name: str
    description: str
    inputs: list[ToolInput] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigField:
    """工具配置表单字段声明（驱动前端配置页动态渲染）。

    key 为点路径（如 feishu.app_id），前端拆分为嵌套表单路径。
    type: text / password / number。
    """

    key: str
    label: str
    type: str
    section: str = ""
    required: bool = False


@dataclass
class Tool:
    id: str
    name: str
    description: str
    image: str | None
    steps: list[ToolStep]
    func: Callable[..., Awaitable[dict[str, Any]]]
    config_schema: list[ConfigField] = field(default_factory=list)


@dataclass
class StepContext:
    """步骤执行上下文（api 层组装后传入工具函数）。"""

    execution_id: str
    user_id: str
    prev_outputs: dict[str, Any]
    file_paths: dict[str, list[str]]  # input_key -> 本地绝对路径列表（单文件也是单元素列表）
    output_dir: Path  # 工具产出文件目录（已创建）
    config: dict[str, Any] | None = None  # 工具配置 JSON（声明 config_schema 时由 api 层从数据库加载）


class ToolError(Exception):
    """工具执行中的预期内错误，消息直接透传给用户。"""


# ── 注册表 ──

_REGISTRY: dict[str, Tool] = {}
_discovered = False

# 工具图片静态挂载前缀：main.py 挂载与 api.py 生成 URL 共用，改挂载路径只动这里
TOOL_IMAGE_URL_PREFIX = "/toolbox-tools"


def tool(
    *,
    id: str,
    name: str,
    description: str,
    image: str | None = None,
    steps: list[ToolStep],
    config_schema: list[ConfigField] | None = None,
) -> Callable[
    [Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]
]:
    """装饰器：声明并注册一个工具。工具函数签名：

    async def run(step_id: str, params: dict, context: StepContext) -> dict

    config_schema 声明工具配置表单字段（点路径 + 中文标签 + 类型 + 分组），
    前端配置页据此动态渲染；声明 config_schema 即启用配置读写（存储于数据库）。
    """

    def deco(func: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[dict[str, Any]]]:
        if id in _REGISTRY:
            raise ValueError(f"tool id 重复: {id}")
        _REGISTRY[id] = Tool(
            id=id, name=name, description=description,
            image=image, steps=list(steps), func=func,
            config_schema=list(config_schema or []),
        )
        return func

    return deco


def discover_tools() -> None:
    """扫描 tools/ 包，import 每个工具包触发装饰器注册（进程内一次）。

    工具以 python 包形式登记：tools/<tool>/__init__.py（工具声明在包内，
    包内辅助模块用下划线前缀，如 attendance_check/_core.py）。
    """
    global _discovered
    if _discovered:
        return
    tools_dir = Path(__file__).parent / "tools"
    for path in sorted(tools_dir.glob("*/__init__.py")):
        if path.parent.name.startswith("_"):
            continue
        importlib.import_module(f"{__package__}.tools.{path.parent.name}")
    # 全部导入成功后才置位：某个工具包 import 失败时下次请求可重试，
    # 而不是把空注册表永久固化到进程结束。
    _discovered = True


def list_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def get_tool(tool_id: str) -> Tool | None:
    return _REGISTRY.get(tool_id)


def get_step(tool_id: str, step_id: str) -> ToolStep | None:
    t = _REGISTRY.get(tool_id)
    if not t:
        return None
    for s in t.steps:
        if s.id == step_id:
            return s
    return None
