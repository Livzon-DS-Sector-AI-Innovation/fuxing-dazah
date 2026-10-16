"""2-E 消费侧：安全 agent 挂仓储 4 查询工具（直接 import 适配）。

接缝：
- 路由：仓储话术命中 warehouse 域（按需挂载，不进常驻集）
- 适配函数：参数透传仓储纯查询函数（monkeypatch 模拟返回）
- 权限：四角色可用（只读），TOOL_KIND=False
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_warehouse_routing_on_demand() -> None:
    from app.modules.safety.business_agent.tool_selector import route_message
    from app.modules.safety.business_agent.tools.registry import RESIDENT_TOOLS

    decision = route_message("仓库里乙醇还有多少库存")
    assert "warehouse" in decision.domains
    assert {"query_stock", "query_material"} <= set(decision.tool_names)
    # 按需挂载：不进常驻集（与一期减法精神一致）
    assert not {"query_stock", "query_material"} & set(RESIDENT_TOOLS)


def test_warehouse_tools_kind_and_permissions() -> None:
    from app.modules.safety.business_agent.core.permissions import (
        KNOWN_ROLES,
        allowed_tools,
    )
    from app.modules.safety.business_agent.tools.registry import (
        _FUNC_BY_NAME,
        TOOL_KIND,
    )

    names = {"query_stock", "query_material", "query_movements", "query_report"}
    assert names <= set(_FUNC_BY_NAME)
    for name in names:
        assert TOOL_KIND[name] is False
    for role in KNOWN_ROLES:
        assert names <= allowed_tools(role)


def test_warehouse_adapter_passthrough(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import warehouse_query_tools
    from app.modules.warehouse.agent.tools import query as warehouse_query

    calls: list[dict] = []

    async def fake_stock(*, keyword=None, qc_status=None, expiring_days=None):
        calls.append({"kw": keyword, "qc": qc_status})
        return {"total": 1, "records": [{"物料名称": "乙醇"}]}

    monkeypatch.setattr(warehouse_query, "query_stock", fake_stock)

    ctx = SimpleNamespace(deps=SimpleNamespace(role="viewer"))
    out = asyncio.run(
        warehouse_query_tools.query_stock(ctx, keyword="乙醇", qc_status="放行")
    )
    assert out["total"] == 1
    assert calls == [{"kw": "乙醇", "qc": "放行"}]

    # 空串参数归一为 None（仓储实现核口径）
    out2 = asyncio.run(warehouse_query_tools.query_stock(ctx))
    assert calls[-1] == {"kw": None, "qc": None}
    assert out2["total"] == 1
