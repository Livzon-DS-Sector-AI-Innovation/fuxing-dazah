"""Ticket 05 — resolve_photo_urls MinIO 分支测试。

- MinIO 模式：本地全部 miss 时按 object key（去除 uploads/ 前缀）经
  ``get_object("safety", key)`` 取字节 → encode_image_for_vision → data URI；
- 本地文件优先于 MinIO（本地命中时不调 get_object）；
- 全部 miss / 非图片扩展名 → 跳过并返回空。
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image as PILImage

from app.modules.safety.vision import utils as vision_utils


@pytest.fixture(autouse=True)
def _isolate_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """所有用例把 CWD 重定向到 tmp_path，避免命中真实 uploads/ 下的文件。"""
    monkeypatch.chdir(tmp_path)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _write_local(rel_path: str, data: bytes, tmp_path: Path) -> Path:
    full = tmp_path / "uploads" / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full


def _fail_if_called(module: str, object_key: str):
    raise AssertionError(f"MinIO 不应被调用: {module}/{object_key}")


class TestResolvePhotoUrlsMinioBranch:
    def test_minio_key_read_as_data_uri(self, tmp_path, monkeypatch):
        png = _png_bytes()
        calls: list[tuple[str, str]] = []

        def fake_get_object(module: str, object_key: str):
            calls.append((module, object_key))
            return (png, "image/png")

        monkeypatch.setattr(vision_utils, "minio_enabled", lambda: True)
        monkeypatch.setattr(vision_utils, "get_object", fake_get_object)

        result = vision_utils.resolve_photo_urls(json.dumps(["hazard/photo.png"]))

        assert len(result) == 1
        assert result[0].startswith("data:image/jpeg;base64,")
        assert calls == [("safety", "hazard/photo.png")]

    def test_legacy_uploads_prefix_stripped_before_get_object(self, tmp_path, monkeypatch):
        png = _png_bytes()
        calls: list[str] = []
        monkeypatch.setattr(vision_utils, "minio_enabled", lambda: True)
        monkeypatch.setattr(
            vision_utils,
            "get_object",
            lambda module, key: (calls.append(key) or (png, "image/png")),
        )

        result = vision_utils.resolve_photo_urls(json.dumps(["uploads/safety/hazard/old.png"]))

        # MinIO object key 不带 safety/ 段：uploads/safety/hazard/x.png → hazard/x.png
        assert result and result[0].startswith("data:image/jpeg;base64,")
        assert calls == ["hazard/old.png"]

    def test_local_file_takes_priority_over_minio(self, tmp_path, monkeypatch):
        _write_local("safety/hazard/photo.png", _png_bytes(), tmp_path)
        monkeypatch.setattr(vision_utils, "minio_enabled", lambda: True)
        monkeypatch.setattr(vision_utils, "get_object", _fail_if_called)

        result = vision_utils.resolve_photo_urls(json.dumps(["safety/hazard/photo.png"]))

        assert result and result[0].startswith("data:image/jpeg;base64,")

    def test_missing_everywhere_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vision_utils, "minio_enabled", lambda: True)
        monkeypatch.setattr(vision_utils, "get_object", lambda module, key: None)

        result = vision_utils.resolve_photo_urls(json.dumps(["hazard/ghost.png"]))

        assert result == []

    def test_non_image_extension_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vision_utils, "minio_enabled", lambda: True)
        monkeypatch.setattr(vision_utils, "get_object", _fail_if_called)

        result = vision_utils.resolve_photo_urls(json.dumps(["hazard/notes.txt"]))

        assert result == []

    def test_minio_disabled_missing_local_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vision_utils, "minio_enabled", lambda: False)

        result = vision_utils.resolve_photo_urls(json.dumps(["hazard/photo.png"]))

        assert result == []
