"""鉴权依赖强制执行回归测试（2026-11-13 P0 防复发守卫）。

背景：`_user: Any = RequireUser` 写法使 FastAPI 不执行鉴权依赖——参数注解
``Any`` 覆盖了 ``Annotated[User, Depends(...)]`` 的依赖元数据，FastAPI 将其
降级为普通默认值参数（真机实测：无 token 请求返回 200 而非 401）。

正确写法是把 Annotated 用作注解本身（``_user: RequireUser``，无默认值）。
本文件两层守卫：
1. 最小 app 复现两种写法的行为差异（语义锚）；
2. 真路由扫描：断言仓库内不再出现 ``: Any = RequireUser/Admin`` 形态
   （源码文本扫描，防新增端点再犯）。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from typing import Annotated, Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
#: 禁止形态（参数注解写 Any 且默认值是 RequireX Annotated 别名）
_BAD_PATTERN = re.compile(r":\s*Any\s*=\s*(?:RequireUser|RequireAdmin)\b")


def _deny() -> None:
    from fastapi import HTTPException

    raise HTTPException(status_code=401, detail="未登录")


#: 模块级依赖别名（Annotated 作注解时 FastAPI 才执行依赖）
_DenyDep = Annotated[str, Depends(_deny)]


def _make_app(bad_style: bool) -> FastAPI:
    """构造最小 app 复现/对照两种参数写法。

    注意：依赖别名必须在模块级定义（本文件开了 ``from __future__ import
    annotations``，函数局部注解名 get_type_hints 解析不到会退化成普通参数）。
    """
    app = FastAPI()

    if bad_style:
        @app.get("/probe")
        def probe(user: Any = _DenyDep) -> dict:  # type: ignore[assignment]
            return {"ok": True}

    else:
        @app.get("/probe")
        def probe(user: _DenyDep) -> dict:
            return {"ok": True}

    return app


class TestAnnotatedAuthSemantics:
    """语义锚：两种写法的鉴权行为差异（修复依据）。"""

    def test_bad_style_skips_dependency(self) -> None:
        # ``: Any = RequireX`` 依赖不执行 → 200（缺陷形态，钉死证据）
        client = TestClient(_make_app(bad_style=True))
        resp = client.get("/probe")
        assert resp.status_code == 200

    def test_annotated_style_enforces_dependency(self) -> None:
        # ``: RequireX``（Annotated 作注解）依赖执行 → 401
        client = TestClient(_make_app(bad_style=False))
        resp = client.get("/probe")
        assert resp.status_code == 401


class TestNoBadAuthStyleInRepo:
    """源码扫描：仓库内不再允许 ``: Any = RequireUser/Admin`` 形态。"""

    def test_no_any_annotated_auth_defaults(self) -> None:
        app_root = BACKEND_ROOT / "app"
        offenders: list[str] = []
        for path in app_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _BAD_PATTERN.search(line):
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{lineno}")
        assert not offenders, (
            "发现鉴权依赖失效写法（: Any = RequireX，FastAPI 不执行该依赖）"
            "——请改为 Annotated 注解式（xxx: RequireX）：\n" + "\n".join(offenders)
        )


class TestRealAppEndpointsEnforced:
    """端点级回归（spec Ticket01）：真实 app 上无 token → 401。

    注：不覆写 get_current_user（真实链路）；admin 过闸由
    tests/platform/superagent/test_r3_ops_selfheal_api_db.py 的
    RequireAdmin 权限 stub 用例覆盖。
    """

    def test_ops_selfheal_list_requires_token(self) -> None:
        from app.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/safety/ops-selfheal/tickets")
        assert resp.status_code == 401, resp.text

    def test_extend_window_requires_token(self) -> None:
        from app.main import app

        client = TestClient(app)
        resp = client.post("/api/v1/safety/ops-selfheal/tickets/x/extend-window",
                           json={})
        assert resp.status_code == 401, resp.text
