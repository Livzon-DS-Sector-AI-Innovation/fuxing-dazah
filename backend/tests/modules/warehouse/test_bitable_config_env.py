"""Bitable 环境坐标组测试（V3.0 分期D Ticket 01，§3.3 生产版切换准备）。

接缝：store 构造函数 row_loader / env_row_loader 注入 + runtime_store 打桩
（沿 test_push_center / 既有连接 store 测试模式）。核心回归保障：
**test 模式且无环境行时 resolve 行为与历史逐字节一致**。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_config.store import (
    ENV_PROD,
    ENV_TEST,
    BitableConfigStore,
    current_env_mode,
)
from app.modules.warehouse.models import BitableConfigAudit


@dataclass
class StubEnvRow:
    """模拟 bitable_env_connections 活行。"""

    table_key: str
    env: str
    base_token: str | None = None
    table_id: str | None = None
    enabled: bool = True
    note: str | None = None
    is_deleted: bool = False


@dataclass
class StubConnectionRow:
    """模拟既有 bitable_connections 活行。"""

    table_key: str
    base_token: str | None = None
    table_id: str | None = None
    enabled: bool = True
    note: str | None = None
    is_deleted: bool = False


def _make_store(
    rows: dict[str, StubConnectionRow] | None = None,
    env_rows: dict[tuple[str, str], StubEnvRow] | None = None,
) -> BitableConfigStore:
    return BitableConfigStore(
        row_loader=lambda key: (rows or {}).get(key),
        env_row_loader=lambda key, env: (env_rows or {}).get((key, env)),
    )


def _patch_env_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    from app.modules.warehouse.ops_config.runtime_store import (
        runtime_store as _runtime_store,
    )

    monkeypatch.setattr(_runtime_store, "get_value", lambda key: mode)


def _patch_env_token(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), key, value, raising=False)


class TestCurrentEnvMode:
    def test_default_test(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.warehouse.ops_config.runtime_store import (
            runtime_store as _runtime_store,
        )

        def _raise(key: str) -> str:
            raise RuntimeError("db down")

        monkeypatch.setattr(_runtime_store, "get_value", _raise)
        assert current_env_mode() == ENV_TEST

    def test_illegal_value_failsafe_test(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_env_mode(monkeypatch, "staging")
        assert current_env_mode() == ENV_TEST

    def test_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_env_mode(monkeypatch, "prod")
        assert current_env_mode() == ENV_PROD


class TestResolveChain:
    def test_test_mode_without_env_row_matches_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回归保障：test 模式无环境行 = 历史行为（既有行 → env → 快照）。"""
        _patch_env_mode(monkeypatch, ENV_TEST)
        _patch_env_token(
            monkeypatch, "WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN", "tok_env"
        )
        store = _make_store(
            rows={
                "material_receipt": StubConnectionRow(
                    table_key="material_receipt", base_token="tok_legacy"
                )
            }
        )
        resolved = store.resolve("material_receipt")
        assert resolved.base_token == "tok_legacy"
        assert resolved.token_source == "db"
        assert resolved.table_id == "tbliBlofs19qM8sg"
        assert resolved.table_id_source == "default"
        assert resolved.enabled is True

    def test_env_row_takes_precedence_in_current_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_env_mode(monkeypatch, ENV_PROD)
        _patch_env_token(
            monkeypatch, "WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN", "tok_env"
        )
        store = _make_store(
            rows={"material_receipt": StubConnectionRow(table_key="material_receipt")},
            env_rows={
                ("material_receipt", ENV_PROD): StubEnvRow(
                    table_key="material_receipt",
                    env=ENV_PROD,
                    base_token="tok_prod",
                    table_id="tblPROD001",
                ),
            },
        )
        resolved = store.resolve("material_receipt")
        assert resolved.base_token == "tok_prod"
        assert resolved.token_source == "db_env"
        assert resolved.table_id == "tblPROD001"
        assert resolved.table_id_source == "db_env"

    def test_env_row_of_other_mode_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """prod 环境行在 test 模式下不参与解析（整行维度，不逐字段混合）。"""
        _patch_env_mode(monkeypatch, ENV_TEST)
        _patch_env_token(
            monkeypatch, "WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN", ""
        )
        store = _make_store(
            env_rows={
                ("material_receipt", ENV_PROD): StubEnvRow(
                    table_key="material_receipt",
                    env=ENV_PROD,
                    base_token="tok_prod",
                    table_id="tblPROD001",
                ),
            },
        )
        resolved = store.resolve("material_receipt")
        assert resolved.base_token == ""
        assert resolved.token_source == "default"
        assert resolved.table_id == "tbliBlofs19qM8sg"
        assert resolved.table_id_source == "default"

    def test_env_row_disabled_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境行 enabled=false = 该环境显式停用（不回退既有行/env）。"""
        _patch_env_mode(monkeypatch, ENV_PROD)
        _patch_env_token(
            monkeypatch, "WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN", "tok_env"
        )
        store = _make_store(
            rows={"material_receipt": StubConnectionRow(table_key="material_receipt")},
            env_rows={
                ("material_receipt", ENV_PROD): StubEnvRow(
                    table_key="material_receipt", env=ENV_PROD, enabled=False
                ),
            },
        )
        resolved = store.resolve("material_receipt")
        assert resolved.enabled is False

    def test_env_row_partial_fields_fall_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """环境行只填 token 时，table_id 回落快照（行内逐字段回退）。"""
        _patch_env_mode(monkeypatch, ENV_PROD)
        store = _make_store(
            env_rows={
                ("material_receipt", ENV_PROD): StubEnvRow(
                    table_key="material_receipt", env=ENV_PROD, base_token="tok_prod"
                ),
            },
        )
        resolved = store.resolve("material_receipt")
        assert resolved.base_token == "tok_prod"
        assert resolved.table_id == "tbliBlofs19qM8sg"
        assert resolved.table_id_source == "default"


class TestEnvConnectionViews:
    def test_env_view_does_not_follow_current_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """查看 prod 组坐标时不受当前模式影响（配置期预览语义）。"""
        _patch_env_mode(monkeypatch, ENV_TEST)
        store = _make_store(
            env_rows={
                ("material_receipt", ENV_PROD): StubEnvRow(
                    table_key="material_receipt",
                    env=ENV_PROD,
                    base_token="tok_prod_view",
                    table_id="tblPRODVIEW",
                ),
            },
        )
        view = store.get_env_connection_view(ENV_PROD, "material_receipt")
        # 视图按 prod 环境行解析（不随当前 test 模式）——table_id 即铁证
        assert view.table_id == "tblPRODVIEW"

    def test_env_view_masks_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_env_mode(monkeypatch, ENV_PROD)
        store = _make_store(
            env_rows={
                ("material_receipt", ENV_PROD): StubEnvRow(
                    table_key="material_receipt",
                    env=ENV_PROD,
                    base_token="L2O2bNm3SaqzdVse6q5cCi8Anbe",
                ),
            },
        )
        view = store.get_env_connection_view(ENV_PROD, "material_receipt")
        assert view.base_token.startswith("****")
        assert "L2O2bNm3" not in view.base_token

    def test_unknown_env_and_table_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_env_mode(monkeypatch, ENV_TEST)
        store = _make_store()
        with pytest.raises(ValueError, match="环境"):
            store.get_env_connection_view("staging", "material_receipt")
        with pytest.raises(ValueError, match="未知表"):
            store.get_env_connection_view(ENV_PROD, "nope")

    def test_iter_env_views_covers_all_tables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.bitable_config import registry

        _patch_env_mode(monkeypatch, ENV_PROD)
        store = _make_store()
        views = store.iter_env_connection_views(ENV_PROD)
        assert len(views) == len(registry.iter_connections())


class TestEnvWrites:
    async def test_set_env_connection_writes_audit_and_invalidates(
        self, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
    ) -> None:
        from sqlalchemy import delete, select

        _patch_env_mode(monkeypatch, ENV_TEST)
        await db_session.execute(
            delete(BitableConfigAudit).where(BitableConfigAudit.action == "update_env")
        )
        store = _make_store()
        view = await store.set_env_connection(
            db_session,
            ENV_PROD,
            "material_receipt",
            {"base_token": "L2O2bNm3PRODTOKEN99", "table_id": "tblPRODTEST1"},
            operator_name="运维",
        )
        assert view.table_id == "tblPRODTEST1"
        audits = (
            await db_session.execute(
                select(BitableConfigAudit).where(
                    BitableConfigAudit.action == "update_env",
                    BitableConfigAudit.table_key == "material_receipt",
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].after_json is not None
        assert audits[0].after_json.get("env") == ENV_PROD
        # token 脱敏落审计
        assert "PRODTOKEN99" not in (audits[0].after_json.get("base_token") or "")
        # 缓存已失效（行未提交，sync 读不可见——但缓存键被清除可验证）
        assert "material_receipt" not in store._cache  # noqa: SLF001

    async def test_set_env_mode_validates_and_audits(
        self, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
    ) -> None:
        from sqlalchemy import delete, select

        _patch_env_mode(monkeypatch, ENV_TEST)
        await db_session.execute(
            delete(BitableConfigAudit).where(BitableConfigAudit.action == "env_mode")
        )
        store = _make_store()
        applied = await store.set_env_mode(db_session, "prod", operator_name="运维")
        assert applied == ENV_PROD
        audits = (
            await db_session.execute(
                select(BitableConfigAudit).where(
                    BitableConfigAudit.action == "env_mode"
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].before_json == {"mode": ENV_TEST}
        assert audits[0].after_json == {"mode": ENV_PROD}
        with pytest.raises(ValueError, match="环境模式"):
            await store.set_env_mode(db_session, "staging")
