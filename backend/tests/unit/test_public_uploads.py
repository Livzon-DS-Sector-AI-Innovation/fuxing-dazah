"""公共 /uploads 静态挂载：私有模块目录必须 404，普通目录照常可读。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.main import _PublicUploads

SCOPE: dict[str, object] = {
    "type": "http",
    "method": "GET",
    "path": "/uploads",
    "headers": [],
}


def _mount(root: Path) -> _PublicUploads:
    return _PublicUploads(directory=str(root))


def _write(root: Path, *parts: str) -> None:
    target = root.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")


@pytest.mark.parametrize("module", ["qa", "feedback"])
async def test_private_module_file_not_served(tmp_path: Path, module: str) -> None:
    """QA 原件与反馈截图只能走带权限的代理接口。"""
    _write(tmp_path, module, "secret.png")
    response = await _mount(tmp_path).get_response(f"{module}/secret.png", SCOPE)
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["public/../feedback/secret.png", "public/../qa/secret.png"])
async def test_dotdot_cannot_bypass(tmp_path: Path, path: str) -> None:
    _write(tmp_path, "feedback", "secret.png")
    _write(tmp_path, "qa", "secret.png")
    response = await _mount(tmp_path).get_response(path, SCOPE)
    assert response.status_code == 404


async def test_public_dir_still_served(tmp_path: Path) -> None:
    _write(tmp_path, "work-orders", "photo.png")
    response = await _mount(tmp_path).get_response("work-orders/photo.png", SCOPE)
    assert response.status_code == 200
