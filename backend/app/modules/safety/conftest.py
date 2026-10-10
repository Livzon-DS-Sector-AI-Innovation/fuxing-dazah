"""安全模块 in-module 测试公共夹具。

仅在显式收集 app/modules/safety/**/tests 时生效（pyproject testpaths=tests
不含本目录）。与 backend/tests/conftest.py 保持同款防御：
安全模块应用配置中心 DB 层 stub 为空（autouse）。

生效优先级 env > DB 活行 > 代码默认：stub DB 层保证「未显式 setenv 的键」
在测试里恒走 env/代码默认，不被本地 dev 库（可能已被启动播种写入真实值）
的行污染——误发事故教训的防御层。需要 DB 层行为的测试自行覆写本 stub。
"""

from __future__ import annotations

import pytest

from app.modules.safety.app_config.store import store as _safety_app_config_store


@pytest.fixture(autouse=True)
def safety_app_config_db_stub(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_safety_app_config_store, "_fetch_rows", lambda: {})
    _safety_app_config_store.invalidate()
    yield
