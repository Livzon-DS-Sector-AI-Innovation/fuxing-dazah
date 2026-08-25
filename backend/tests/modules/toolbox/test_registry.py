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
    discover_tools()
    ids = {t.id for t in list_tools()}
    assert "attendance-check" in ids
    t = get_tool("attendance-check")
    assert t is not None
    assert t.name == "打卡核对"
    assert [s.id for s in t.steps] == ["check", "dedupe", "write"]


def test_tool_config_schema_declared() -> None:
    """工具以声明式 config_schema 描述配置表单：点路径 key + 中文标签 + 类型 + 分组。"""
    discover_tools()
    t = get_tool("attendance-check")
    assert t is not None
    schema = t.config_schema
    assert [f.key for f in schema] == [
        "feishu.app_id",
        "feishu.app_secret",
        "bitable.app_token",
        "bitable.shift_table_id",
        "bitable.schedule_table_id",
        "bitable.whitelist_table_id",
        "bitable.attendance_result_table_id",
        "bitable.duty_app_token",
        "bitable.duty_table_id",
        "bitable.actual_clock_table_id",
        "offset_minutes",
        "overtime_gap_minutes",
    ]
    secret = schema[1]
    assert secret.label == "飞书应用密钥"
    assert secret.type == "password"
    assert secret.section == "飞书应用"
    assert schema[10].type == "number"
    assert schema[10].section == "核对参数"
