"""工具箱工具配置读写端点测试。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.toolbox import api
from tests.modules.toolbox.conftest import FakeRedis


@pytest.fixture
def client(fake_redis: FakeRedis, fake_user: SimpleNamespace) -> AsyncClient:
    """测试应用：挂 toolbox router，注入 FakeRedis 与假用户。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.router)

    async def fake_user_dep() -> SimpleNamespace:
        return fake_user

    async def fake_redis_dep() -> FakeRedis:
        return fake_redis

    app.dependency_overrides[api.get_current_user] = fake_user_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.get_redis] = fake_redis_dep  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def fake_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把配置路径解析重定向到临时目录（tools/<包名>/config.json）。"""
    pkg_dir = Path(tmp_path) / "attendance_check"
    pkg_dir.mkdir(exist_ok=True)

    def _config_path(tool_id: str) -> Path:
        return Path(tmp_path) / tool_id.replace("-", "_") / "config.json"

    monkeypatch.setattr(api, "_config_path", _config_path)
    return tmp_path


CONFIG = {
    "feishu": {"app_id": "cli_test", "app_secret": "secret"},
    "bitable": {"app_token": "tok", "attendance_result_table_id": "tbl1"},
    "offset_minutes": 180,
    "overtime_gap_minutes": 60,
}


async def test_get_config_returns_file_content(client: AsyncClient, fake_config_dir: Path) -> None:
    import json

    (fake_config_dir / "attendance_check" / "config.json").write_text(
        json.dumps(CONFIG), encoding="utf-8"
    )
    resp = await client.get("/tools/attendance-check/config")
    assert resp.status_code == 200
    assert resp.json()["data"] == CONFIG


async def test_get_config_missing_file_404(client: AsyncClient, fake_config_dir: Path) -> None:
    resp = await client.get("/tools/attendance-check/config")
    assert resp.status_code == 404


async def test_put_config_updates_file(client: AsyncClient, fake_config_dir: Path) -> None:
    import json

    path = fake_config_dir / "attendance_check" / "config.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")

    new_config = {**CONFIG, "offset_minutes": 60}
    resp = await client.put("/tools/attendance-check/config", json=new_config)
    assert resp.status_code == 200
    assert json.loads(path.read_text(encoding="utf-8")) == new_config


async def test_put_config_invalid_json_400(client: AsyncClient, fake_config_dir: Path) -> None:
    import json

    path = fake_config_dir / "attendance_check" / "config.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")

    resp = await client.put(
        "/tools/attendance-check/config",
        content=b"{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    # 原文件未被破坏
    assert json.loads(path.read_text(encoding="utf-8")) == CONFIG


async def test_put_config_non_object_400(client: AsyncClient, fake_config_dir: Path) -> None:
    import json

    path = fake_config_dir / "attendance_check" / "config.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")

    resp = await client.put("/tools/attendance-check/config", json=[1, 2, 3])
    assert resp.status_code == 400
    assert json.loads(path.read_text(encoding="utf-8")) == CONFIG


async def test_put_config_missing_file_404(client: AsyncClient, fake_config_dir: Path) -> None:
    resp = await client.put("/tools/attendance-check/config", json=CONFIG)
    assert resp.status_code == 404
