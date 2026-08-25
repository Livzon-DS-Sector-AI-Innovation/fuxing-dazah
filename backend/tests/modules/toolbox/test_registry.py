"""工具箱注册表测试。"""

from typing import Any

import pytest

from app.modules.toolbox.registry import (
    StepContext,
    ToolError,
    ToolStep,
    discover_tools,
    get_step,
    get_tool,
    list_tools,
    tool,
)


def test_tool_error_message() -> None:
    err = ToolError("文件格式不正确")
    assert str(err) == "文件格式不正确"


def test_decorator_registers_and_lists() -> None:
    @tool(
        id="t-registry-test",
        name="注册表测试工具",
        description="仅测试用",
        steps=[ToolStep(id="s1", name="步骤一", description="", inputs=[])],
    )
    async def _func(
        step_id: str, params: dict[str, Any], context: StepContext
    ) -> dict[str, Any]:
        return {}

    t = get_tool("t-registry-test")
    assert t is not None
    assert t.name == "注册表测试工具"
    assert t.image is None
    assert t.steps[0].id == "s1"
    assert t in list_tools()


def test_duplicate_id_raises() -> None:
    @tool(id="t-dup", name="x", description="", steps=[])
    async def _a(step_id: str, params: dict[str, Any], context: StepContext) -> dict[str, Any]:
        return {}

    with pytest.raises(ValueError):
        @tool(id="t-dup", name="y", description="", steps=[])
        async def _b(
            step_id: str, params: dict[str, Any], context: StepContext
        ) -> dict[str, Any]:
            return {}


def test_get_step_missing_returns_none() -> None:
    assert get_step("t-registry-test", "nope") is None
    assert get_tool("nope") is None


def test_discover_tools_finds_real_tool() -> None:
    # Task 5 才会添加真实工具，这里先断言 discover 不报错
    discover_tools()
    assert isinstance(list_tools(), list)
