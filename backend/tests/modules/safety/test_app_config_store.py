"""应用配置中心（app_config）store/registry 单测。

覆盖：注册表完整性、生效优先级（env > DB 活行 > registry 默认——env 优先是
刻意设计，保证 monkeypatch.setenv 测试隔离语义零回归）、类型解析、写校验、
secret 脱敏、播种幂等（db_session 事务回滚隔离）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.modules.safety.app_config import registry
from app.modules.safety.app_config.store import AppConfigStore, _mask_secret, store
from app.modules.safety.models import AppConfigAudit, AppConfigEntry


def _stub_db(monkeypatch: pytest.MonkeyPatch, rows: dict[str, str]) -> None:
    """把 DB 层 stub 为固定行集合并失效缓存（纯逻辑测试不触真实 DB）。"""
    monkeypatch.setattr(store, "_fetch_rows", lambda: dict(rows))
    store.invalidate()


class TestRegistry:
    """注册表完整性（条目数断言沿用 bitable registry 惯例）。"""

    def test_key_unique_and_count(self):
        # 新增/删除键时同步更新此数（防 dict 推导静默覆盖与意外丢键）
        assert len(registry.REGISTRY) == 82
        assert len(registry.iter_items()) == 82

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="未知配置键"):
            registry.get_item("SAFETY_NOT_EXIST")

    def test_chat_id_keys_are_str(self):
        for item in registry.iter_items():
            if item.category == "chat_id":
                assert item.type == "str"

    def test_secret_items_masked_flag(self):
        for key in (
            "SAFETY_PLATFORM_USERNAME",
            "SAFETY_PLATFORM_PASSWORD_MD5",
            "SAFETY_PLATFORM_AUTH_BASIC",
            "SAFETY_REGULATION_CRAWLER_WEBHOOK_SECRET",
        ):
            assert registry.REGISTRY[key].secret is True


class TestPrecedence:
    """生效优先级：env（非空）> DB 活行 > registry 默认。"""

    def test_env_beats_db(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED", "false")
        _stub_db(monkeypatch, {"SAFETY_FIRE_ALARM_DAILY_DM_ENABLED": "true"})
        assert store.get_bool("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED") is False

    def test_db_when_env_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED", raising=False)
        _stub_db(monkeypatch, {"SAFETY_FIRE_ALARM_DAILY_DM_ENABLED": "true"})
        assert store.get_bool("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED") is True

    def test_registry_default_when_both_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED", raising=False)
        _stub_db(monkeypatch, {})
        assert store.get_bool("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED") is False

    def test_empty_env_value_treated_as_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED", "")
        _stub_db(monkeypatch, {"SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED": "true"})
        assert store.get_bool("SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED") is True

    def test_db_empty_value_row_ignored(self, monkeypatch: pytest.MonkeyPatch):
        # 空值行由 SQL 层过滤；此处防御 dict 带入空值时的行为
        monkeypatch.delenv("SAFETY_HAZARD_POLL_BATCH_LIMIT", raising=False)
        _stub_db(monkeypatch, {"SAFETY_HAZARD_POLL_BATCH_LIMIT": ""})
        assert store.get_int("SAFETY_HAZARD_POLL_BATCH_LIMIT") == 200

    def test_unregistered_key_read_is_permissive(self, monkeypatch: pytest.MonkeyPatch):
        # gates 拼名读取的宽容语义：未注册键不抛错（env/DB 均无 → None）
        monkeypatch.setenv("SAFETY_UNIT_TEST_TMP_KEY", "1")
        assert store.get_raw("SAFETY_UNIT_TEST_TMP_KEY") == "1"
        monkeypatch.delenv("SAFETY_UNIT_TEST_TMP_KEY", raising=False)
        _stub_db(monkeypatch, {})
        assert store.get_raw("SAFETY_UNIT_TEST_TMP_KEY") is None


class TestTypedGetters:
    """类型解析（bool 真值集 / int 下限与回退 / str 默认与 strip）。"""

    def test_bool_truthy_set(self, monkeypatch: pytest.MonkeyPatch):
        _stub_db(monkeypatch, {})
        for raw in ("1", "true", "Yes", "ON"):
            monkeypatch.setenv("SAFETY_HAZARD_CATCHUP_ENABLED", raw)
            assert store.get_bool("SAFETY_HAZARD_CATCHUP_ENABLED") is True, raw
        monkeypatch.setenv("SAFETY_HAZARD_CATCHUP_ENABLED", "garbage")
        assert store.get_bool("SAFETY_HAZARD_CATCHUP_ENABLED") is False

    def test_int_minimum_enforced(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_HAZARD_POLL_INTERVAL_SECONDS", raising=False)
        _stub_db(monkeypatch, {"SAFETY_HAZARD_POLL_INTERVAL_SECONDS": "10"})
        # 低于 minimum=60 时取 max(60, 解析值) —— gates.int_env 同款语义
        assert store.get_int("SAFETY_HAZARD_POLL_INTERVAL_SECONDS", 300, minimum=60) == 60

    def test_int_parse_failure_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_HAZARD_POLL_BATCH_LIMIT", raising=False)
        _stub_db(monkeypatch, {"SAFETY_HAZARD_POLL_BATCH_LIMIT": "abc"})
        assert store.get_int("SAFETY_HAZARD_POLL_BATCH_LIMIT", 200) == 200

    def test_int_registry_default_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_HAZARD_POLL_CONCURRENCY", raising=False)
        _stub_db(monkeypatch, {})
        assert store.get_int("SAFETY_HAZARD_POLL_CONCURRENCY") == 3

    def test_str_default_and_strip(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_WORKTICKET_GROUP_ID", raising=False)
        _stub_db(monkeypatch, {})
        assert store.get_str("SAFETY_WORKTICKET_GROUP_ID") == "oc_d102e1a11eaaa9a1de3b41859de9d0c1"
        _stub_db(monkeypatch, {"SAFETY_WORKTICKET_GROUP_ID": "  oc_new  "})
        assert store.get_str("SAFETY_WORKTICKET_GROUP_ID") == "oc_new"


class TestEffectiveItems:
    """列表视图：来源标注 / secret 脱敏 / env-DB 冲突标记。"""

    def test_source_labels_and_conflict(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SAFETY_DAILY_DIGEST_ENABLED", "false")
        monkeypatch.delenv("SAFETY_HAZARD_CATCHUP_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_PLATFORM_PASSWORD_MD5", raising=False)
        _stub_db(
            monkeypatch,
            {
                "SAFETY_HAZARD_CATCHUP_ENABLED": "true",
                "SAFETY_DAILY_DIGEST_ENABLED": "true",  # 与 env 冲突
                "SAFETY_PLATFORM_PASSWORD_MD5": "598548c6de63bf1b44bee1aa16a6e13e",
            },
        )
        items = {i["key"]: i for i in store.effective_items()}
        assert items["SAFETY_DAILY_DIGEST_ENABLED"]["source"] == "env"
        assert items["SAFETY_DAILY_DIGEST_ENABLED"]["env_overrides_db"] is True
        assert items["SAFETY_HAZARD_CATCHUP_ENABLED"]["source"] == "db"
        assert items["SAFETY_HAZARD_CATCHUP_ENABLED"]["env_overrides_db"] is False
        assert items["SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED"]["source"] == "default"

    def test_secret_masked_in_view(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SAFETY_PLATFORM_PASSWORD_MD5", raising=False)
        _stub_db(monkeypatch, {"SAFETY_PLATFORM_PASSWORD_MD5": "abcdef123456"})
        items = {i["key"]: i for i in store.effective_items()}
        assert items["SAFETY_PLATFORM_PASSWORD_MD5"]["value"] == "****3456"


class TestValidateValue:
    """写校验（_validate_value / get_item）。"""

    def test_bool_normalize(self):
        info = registry.REGISTRY["SAFETY_HAZARD_CATCHUP_ENABLED"]
        assert store._validate_value(info, "1") == "true"
        assert store._validate_value(info, "FALSE") == "false"
        with pytest.raises(ValueError):
            store._validate_value(info, "maybe")

    def test_int_minimum(self):
        info = registry.REGISTRY["SAFETY_HAZARD_POLL_INTERVAL_SECONDS"]
        assert store._validate_value(info, "90") == "90"
        with pytest.raises(ValueError):
            store._validate_value(info, "30")
        with pytest.raises(ValueError):
            store._validate_value(info, "abc")

    def test_int_ttl_allows_zero(self):
        info = registry.REGISTRY["SAFETY_OH_DIRECT_CACHE_TTL_SECONDS"]
        assert store._validate_value(info, "0") == "0"

    def test_chat_id_prefix_and_off(self):
        plain = registry.REGISTRY["SAFETY_FIRE_ALARM_ANALYSIS_CHAT_ID"]
        assert store._validate_value(plain, "oc_abc") == "oc_abc"
        assert store._validate_value(plain, "") == ""
        with pytest.raises(ValueError):
            store._validate_value(plain, "off")  # 不支持 off 哨兵
        with pytest.raises(ValueError):
            store._validate_value(plain, "not-an-id")
        extra = registry.REGISTRY["SAFETY_CHEMICAL_DAILY_EXTRA_CHAT_ID"]
        assert store._validate_value(extra, "off") == "off"

    def test_open_id_and_notify_users(self):
        bot = registry.REGISTRY["SAFETY_FEISHU_BOT_OPEN_ID"]
        assert store._validate_value(bot, "ou_abc") == "ou_abc"
        with pytest.raises(ValueError):
            store._validate_value(bot, "oc_abc")
        users = registry.REGISTRY["SAFETY_REGULATION_CRAWLER_NOTIFY_USERS"]
        assert store._validate_value(users, "ou_a, ou_b") == "ou_a, ou_b"
        with pytest.raises(ValueError):
            store._validate_value(users, "ou_a,oc_b")

    def test_str_length_cap(self):
        info = registry.REGISTRY["SAFETY_PHOENIX_ENDPOINT"]
        with pytest.raises(ValueError):
            store._validate_value(info, "x" * 1025)


class TestMask:
    def test_mask_secret(self):
        assert _mask_secret("") == ""
        assert _mask_secret("ab") == "****"
        assert _mask_secret("abcd1234") == "****1234"


class TestWriteAndSeed:
    """写路径 + 播种（db_session 事务回滚隔离，不落库）。"""

    _USED_KEYS = (
        "SAFETY_HAZARD_CATCHUP_ENABLED",
        "SAFETY_HAZARD_POLL_BATCH_LIMIT",
        "SAFETY_HAZARD_POLL_CONCURRENCY",
        "SAFETY_PLATFORM_PASSWORD_MD5",
    )

    @pytest.fixture(autouse=True)
    async def clean_config_rows(self, db_session):
        """删除本类用到的键的既有行与审计行（含软删），防本地库启动播种
        落库的行/审计与测试 INSERT 撞唯一键或污染断言
        （uq_app_config_entries_key 只排除软删行；审计表 append-only，
        测试内删除走事务回滚，不影响库内历史）。"""
        await db_session.execute(
            delete(AppConfigEntry).where(AppConfigEntry.key.in_(self._USED_KEYS))
        )
        await db_session.execute(
            delete(AppConfigAudit).where(AppConfigAudit.key.in_(self._USED_KEYS))
        )
        await db_session.flush()
        store.invalidate()
        yield

    async def test_set_value_creates_row_and_audit(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("SAFETY_HAZARD_CATCHUP_ENABLED", raising=False)
        view = await store.set_value(
            db_session,
            "SAFETY_HAZARD_CATCHUP_ENABLED",
            "true",
            operator_name="tester",
        )
        assert view["source"] == "db"
        assert view["value"] == "true"
        row = (
            await db_session.execute(
                select(AppConfigEntry).where(
                    AppConfigEntry.key == "SAFETY_HAZARD_CATCHUP_ENABLED"
                )
            )
        ).scalars().first()
        assert row is not None and row.value == "true"
        audit = (
            await db_session.execute(
                select(AppConfigAudit).where(
                    AppConfigAudit.key == "SAFETY_HAZARD_CATCHUP_ENABLED"
                )
            )
        ).scalars().first()
        assert audit is not None and audit.action == "enable"

    async def test_set_value_unknown_key(
        self, db_session
    ):
        with pytest.raises(ValueError, match="未知配置键"):
            await store.set_value(db_session, "SAFETY_NOT_EXIST", "1")

    async def test_set_value_masks_secret_in_audit(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("SAFETY_PLATFORM_PASSWORD_MD5", raising=False)
        await store.set_value(
            db_session, "SAFETY_PLATFORM_PASSWORD_MD5", "abcdef123456"
        )
        audit = (
            await db_session.execute(
                select(AppConfigAudit).where(
                    AppConfigAudit.key == "SAFETY_PLATFORM_PASSWORD_MD5"
                )
            )
        ).scalars().first()
        assert audit is not None
        assert audit.after_json["value"] == "****3456"
        assert "abcdef123456" not in str(audit.after_json)

    async def test_seed_only_missing_and_idempotent(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        # 既有行 + env 有值 → 不覆盖；无行 + env 有值 → 播种；无 env → 跳过
        db_session.add(
            AppConfigEntry(key="SAFETY_HAZARD_CATCHUP_ENABLED", value="false")
        )
        await db_session.flush()
        monkeypatch.setenv("SAFETY_HAZARD_CATCHUP_ENABLED", "true")
        monkeypatch.setenv("SAFETY_HAZARD_POLL_BATCH_LIMIT", "250")
        monkeypatch.delenv("SAFETY_HAZARD_POLL_CONCURRENCY", raising=False)

        created = await store.seed_from_env(db_session)
        assert created >= 1
        catchup = (
            await db_session.execute(
                select(AppConfigEntry).where(
                    AppConfigEntry.key == "SAFETY_HAZARD_CATCHUP_ENABLED"
                )
            )
        ).scalars().first()
        assert catchup.value == "false"  # only-missing，不覆盖既有行
        batch = (
            await db_session.execute(
                select(AppConfigEntry).where(
                    AppConfigEntry.key == "SAFETY_HAZARD_POLL_BATCH_LIMIT"
                )
            )
        ).scalars().first()
        assert batch is not None and batch.value == "250"
        assert batch.note == "启动播种自 env（迁移基线）"

        # 幂等：二次播种不再新增（在既有行集基础上 created 与首播新增集合相同）
        created2 = await store.seed_from_env(db_session)
        assert created2 < created  # 上一轮播种的键已存在，不再重复

    async def test_disabled_row_occupies_key_and_seed_skips(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        # 停用行（enabled=false）仍占用键位（部分唯一索引只排除软删行）：
        # 播种不覆盖、不另起新行；停用语义 = 整行不生效，读路径回落 env/默认
        db_session.add(
            AppConfigEntry(key="SAFETY_HAZARD_POLL_BATCH_LIMIT", value="200", enabled=False)
        )
        await db_session.flush()
        monkeypatch.setenv("SAFETY_HAZARD_POLL_BATCH_LIMIT", "300")
        await store.seed_from_env(db_session)
        rows = (
            (
                await db_session.execute(
                    select(AppConfigEntry).where(
                        AppConfigEntry.key == "SAFETY_HAZARD_POLL_BATCH_LIMIT"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].value == "200" and rows[0].enabled is False
        # created 可能含其他键（本会话独占回滚事务，无并行写），与本断言无关


class TestStoreSingleton:
    def test_module_singleton(self):
        from app.modules.safety.app_config.store import store as s

        assert s is store
        assert isinstance(store, AppConfigStore)
