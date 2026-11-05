"""T04 导出 + Agent 查询读口径（B2 导出/Agent）单测（RED 先行）。

覆盖 spec S6：
- ``hazard_action_tools._internal_export_rows`` 等级列 = effective_level
  （人工优先，修正原 AI 优先）；
- ``read_tools.query_hazards`` 内部 items 返回 effective 等级/类型/类别 +
  source；mismatch 时附 ``ai_hazard_level``（AI 原始 EN 供对比）；
  外部来源不带这些字段；工具参数不变。

视图均用 ``bitable_repo.to_view`` 从 fake Bitable 记录构造；网络层
（``bitable_repo.query_hazards`` / ``external_audit.fetch_external_audit``）
monkeypatch 掉，不开网络。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent.tools import hazard_action_tools, read_tools
from app.modules.safety.service.hazard_direct import bitable_repo

_CHECK_MS = int(datetime(2026, 10, 27, 1, 30, tzinfo=UTC).timestamp() * 1000)


def _view(
    no: str,
    *,
    manual_level: object = None,
    ai_level: object = None,
    manual_type: object = None,
    ai_type: object = None,
    manual_category: object = None,
    ai_category: object = None,
) -> bitable_repo.HazardView:
    fields: dict[str, object] = {
        bitable_repo.F_NO: f"HZ-{no}",
        bitable_repo.F_DESC: f"描述{no}",
        bitable_repo.F_DATE: _CHECK_MS,
        bitable_repo.F_RECTIFY_STATUS: "未关闭",
    }
    if manual_level is not None:
        fields[bitable_repo.F_LEVEL_MANUAL] = manual_level
    if ai_level is not None:
        fields[bitable_repo.F_LEVEL_AI] = ai_level
    if manual_type is not None:
        fields[bitable_repo.F_TYPE_MANUAL] = manual_type
    if ai_type is not None:
        fields[bitable_repo.F_TYPE_AI] = ai_type
    if manual_category is not None:
        fields[bitable_repo.F_CATEGORY_MANUAL] = manual_category
    if ai_category is not None:
        fields[bitable_repo.F_CATEGORY_AI] = ai_category
    return bitable_repo.to_view({"record_id": f"rec-{no}", "fields": fields})


def _ctx() -> Any:
    """工具函数只摸 ctx.deps；查询链路已 mock，不需要 DB/身份。"""
    return SimpleNamespace(
        deps=SimpleNamespace(db=None, chat_id=None, role="creator", person=None)
    )


# ═══════════════════════════════════════════════════════════════
# S6a：Excel 导出行等级列 = effective_level
# ═══════════════════════════════════════════════════════════════


class TestInternalExportRowsEffectiveLevel:
    def test_human_level_wins_over_ai(self) -> None:
        rows = hazard_action_tools._internal_export_rows(
            [_view("A", manual_level="较大隐患", ai_level="一般隐患")]
        )
        assert rows[0][4] == "serious"  # 旧实现给 AI 的 general
        assert rows[0][0] == "HZ-A"

    def test_ai_fallback_level(self) -> None:
        rows = hazard_action_tools._internal_export_rows(
            [_view("B", ai_level="重大隐患")]
        )
        assert rows[0][4] == "major"

    def test_empty_level_is_blank(self) -> None:
        rows = hazard_action_tools._internal_export_rows([_view("C")])
        assert rows[0][4] == ""


# ═══════════════════════════════════════════════════════════════
# S6b：Agent query_hazards 内部 items 返回 effective 口径
# ═══════════════════════════════════════════════════════════════


class TestQueryHazardsEffectiveItems:
    def _patch_query(
        self, monkeypatch: pytest.MonkeyPatch, views: list[bitable_repo.HazardView]
    ) -> None:
        async def _fake_query(
            client: Any, **kwargs: Any
        ) -> tuple[list[bitable_repo.HazardView], int]:
            return views, len(views)

        monkeypatch.setattr(
            "app.modules.safety.service.hazard_direct.bitable_repo.query_hazards",
            _fake_query,
        )

    async def test_human_first_with_ai_hint_on_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_query(
            monkeypatch,
            [
                _view(
                    "A",
                    manual_level="较大隐患",
                    ai_level="一般隐患",
                    manual_type="物的不安全状态",
                    ai_type="人的不安全行为",
                    manual_category="设备设施",
                    ai_category="应急管理",
                )
            ],
        )
        result = await read_tools.query_hazards(_ctx())
        item = result["items"][0]
        assert item["hazard_level"] == "serious"
        assert item["hazard_level_source"] == "human"
        assert item["hazard_type"] == "unsafe_condition"
        assert item["hazard_category"] == "equipment"
        # mismatch：附带 AI 原始 EN 值供 Agent 说明「AI 建议」
        assert item["ai_hazard_level"] == "general"

    async def test_ai_fallback_no_ai_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_query(
            monkeypatch,
            [_view("B", ai_level="重大隐患", ai_type="管理的缺陷", ai_category="应急管理")],
        )
        result = await read_tools.query_hazards(_ctx())
        item = result["items"][0]
        assert item["hazard_level"] == "major"
        assert item["hazard_level_source"] == "ai"
        assert item["hazard_type"] == "management_defect"
        assert item["hazard_category"] == "emergency_mgmt"
        assert "ai_hazard_level" not in item  # 无 mismatch 不附加

    async def test_no_effective_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_query(monkeypatch, [_view("C")])
        result = await read_tools.query_hazards(_ctx())
        item = result["items"][0]
        assert item["hazard_level"] is None
        assert item["hazard_level_source"] is None
        assert item["hazard_type"] is None
        assert item["hazard_category"] is None
        assert "ai_hazard_level" not in item

    async def test_external_items_do_not_carry_effective_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.safety.service.hazard_direct.external_audit import (
            ExternalAuditView,
        )

        async def _fake_fetch() -> list[Any]:
            return [
                ExternalAuditView(
                    record_id="e1",
                    seq=1,
                    description="罐区围堰破损",
                    plan="限期修复",
                    departments=["生产部"],
                    closed=False,
                    in_progress=False,
                    checked_at=date(2026, 10, 10),
                    target_date=date(2026, 11, 10),
                    responsible=[("张三", "ou_zs")],
                )
            ]

        monkeypatch.setattr(
            "app.modules.safety.service.hazard_direct.external_audit.fetch_external_audit",
            _fake_fetch,
        )
        result = await read_tools.query_hazards(_ctx(), source="external")
        item = result["items"][0]
        assert "hazard_level" not in item
        assert "hazard_level_source" not in item
        assert "ai_hazard_level" not in item
