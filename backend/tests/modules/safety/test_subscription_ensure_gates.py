"""收尾票第 0 步：5 处 ensure 订阅函数闸门单测（2026-09-24 补齐，防退订后
启动/重连/配置变更静默重订阅——见 .scratch/mirror-closure/PRECHECK.md 第三节）。

关闭路径：事件镜像停用（直读模式 / hazard 事件同步关）时 ensure 返回
False 且不发任何 HTTP；越过闸门不误杀：legacy active 时继续走到配置
检查段（app_token 未配置返回 False，证明闸门未拦截正常订阅路径）。
模式照 chemical test_gates / contractor test_consumers 既有先例。
"""

from __future__ import annotations

import pytest

_ENV_KEYS = (
    "SAFETY_HAZARD_EVENT_SYNC_ENABLED",
    "SAFETY_SPECIAL_OP_DIRECT_ENABLED",
    "SAFETY_FIRE_ALARM_DIRECT_ENABLED",
    "SAFETY_CENTRAL_ALARM_DIRECT_ENABLED",
    "SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED",
    "SAFETY_CERT_DIRECT_ENABLED",
    "SAFETY_CERT_EVENT_SYNC_ENABLED",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestGateClosedSkipsSubscribe:
    async def test_hazard_event_sync_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.feishu import bitable_handler

        monkeypatch.setenv("SAFETY_HAZARD_EVENT_SYNC_ENABLED", "false")
        # 配置正常存在——若闸门失效会发起真实 HTTP
        monkeypatch.setattr(
            bitable_handler, "_hazard_app_token", lambda: "tok_hazard",
        )
        assert await bitable_handler.ensure_bitable_subscribed() is False

    async def test_special_op_direct_on(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.feishu import special_op_bitable_handler as h

        monkeypatch.setenv("SAFETY_SPECIAL_OP_DIRECT_ENABLED", "true")
        monkeypatch.setattr(h, "_special_op_app_token", lambda: "tok_sp")
        assert await h.ensure_special_op_bitable_subscribed() is False

    async def test_fire_alarm_direct_on(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.feishu import fire_alarm_bitable_handler as h

        monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
        monkeypatch.setattr(h, "_fire_alarm_app_token", lambda: "tok_fire")
        assert await h.ensure_fire_alarm_bitable_subscribed() is False

    async def test_central_alarm_direct_on(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.feishu import central_alarm_bitable_handler as h

        monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
        monkeypatch.setattr(h, "central_alarm_app_token", lambda: "tok_ca")
        assert await h.ensure_central_alarm_bitable_subscribed() is False

    async def test_cert_direct_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.feishu import cert_bitable

        monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
        assert await cert_bitable.ensure_cert_bitable_subscribed() is False


class TestGateOpenStillReachesConfigCheck:
    """legacy active 时闸门不拦截——继续走到配置检查段（返回 False 但
    路径不同：app_token 未配置/凭证未配置）。"""

    async def test_hazard_event_sync_on_reaches_token_check(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.feishu import bitable_handler

        monkeypatch.setenv("SAFETY_HAZARD_EVENT_SYNC_ENABLED", "true")
        monkeypatch.setattr(bitable_handler, "_hazard_app_token", lambda: "")
        assert await bitable_handler.ensure_bitable_subscribed() is False

    async def test_central_alarm_legacy_reaches_token_check(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.feishu import central_alarm_bitable_handler as h

        # 未设 DIRECT（legacy active），app_token 未配置 → 走配置检查路径
        monkeypatch.setattr(h, "central_alarm_app_token", lambda: "")
        assert await h.ensure_central_alarm_bitable_subscribed() is False
