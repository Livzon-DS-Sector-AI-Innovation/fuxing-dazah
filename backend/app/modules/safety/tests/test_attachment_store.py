"""Ticket 02 — attachment_store 统一存储 helper 双模式测试。

- 本地模式：monkeypatch ``minio_enabled=False`` + ``monkeypatch.chdir(tmp_path)``
  把 ``uploads/`` 重定向到临时目录，验证落盘相对路径与回读；
- MinIO 模式：monkeypatch ``upload_object`` / ``get_object`` 记录调用参数，
  验证 object key 返回与下载回读；
- safe_filename 清洗（非法字符 → ``_``）与路径穿越（``..``）拒绝；
- materialize 本地路径原样返回 / MinIO key 下载到临时文件 + cleanup_temp。

与 vision 视觉链路的 MinIO 判断一致：``from app.core.storage import is_enabled as minio_enabled``。
"""

import os
from pathlib import Path

import pytest

import app.modules.safety.attachment_store as store


@pytest.fixture(autouse=True)
def _isolate_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """所有用例把 CWD 重定向到 tmp_path，避免读写真实 uploads/。"""
    monkeypatch.chdir(tmp_path)


def _write_local(rel_path: str, data: bytes, tmp_path: Path) -> Path:
    """在 tmp_path/uploads 下按相对路径（safety/... 或 uploads/safety/...）落一个文件。"""
    full = tmp_path / "uploads" / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full


class TestStoreBytesLocalMode:
    def test_returns_relative_path_and_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        result = store.store_bytes("hazard", "photo.jpg", b"abc", content_type="image/jpeg")

        assert result == os.path.join("safety", "hazard", "photo.jpg")
        assert (tmp_path / "uploads" / "safety" / "hazard" / "photo.jpg").read_bytes() == b"abc"
        # 双路径回读：相对路径 / 带 uploads/ 前缀
        assert store.read_bytes(result) == b"abc"
        assert store.read_bytes(os.path.join("uploads", *result.split(os.sep))) == b"abc"
        assert store.exists(result) is True

    def test_safe_filename_cleans_illegal_chars(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        result = store.store_bytes("hazard", "a b?c/d:e*f.txt", b"x")

        assert result == os.path.join("safety", "hazard", "a_b_c_d_e_f.txt")
        assert (tmp_path / "uploads" / "safety" / "hazard" / "a_b_c_d_e_f.txt").exists()
        # 路径穿越片段被清洗后不再越界
        assert store.read_bytes("safety/hazard/a_b_c_d_e_f.txt") == b"x"

    def test_rejects_dotdot_filename(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        with pytest.raises(ValueError):
            store.store_bytes("hazard", "..", b"x")

    def test_rejects_empty_and_dot_filename(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        with pytest.raises(ValueError):
            store.store_bytes("hazard", "", b"x")
        with pytest.raises(ValueError):
            store.store_bytes("hazard", ".", b"x")

    def test_rejects_dotdot_subdir(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        with pytest.raises(ValueError):
            store.store_bytes("../evil", "x.txt", b"x")
        with pytest.raises(ValueError):
            store.store_bytes("hazard/../../x", "x.txt", b"x")


class TestStoreBytesMinioMode:
    def test_returns_key_and_records_upload(self, monkeypatch):
        calls: list[tuple[str, str, bytes, int, str]] = []

        def fake_upload(
            module: str, object_key: str, data: bytes, length: int, content_type: str
        ) -> str:
            calls.append((module, object_key, data, length, content_type))
            return object_key

        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "upload_object", fake_upload)

        result = store.store_bytes("hazard", "report.pdf", b"pdf", content_type="application/pdf")

        assert result == "hazard/report.pdf"
        assert calls == [("safety", "hazard/report.pdf", b"pdf", 3, "application/pdf")]

    def test_safe_filename_applied_in_minio_mode(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "upload_object", lambda module, key, *a, **k: key)

        assert store.store_bytes("hazard", "a/b?.txt", b"x") == "hazard/a_b_.txt"

    def test_default_content_type(self, monkeypatch):
        calls: list[tuple] = []
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "upload_object", lambda *a: (calls.append(a) or a[1]))

        store.store_bytes("hazard", "f.bin", b"x")

        assert calls[0][4] == "application/octet-stream"


class TestReadBytes:
    def test_falls_back_to_minio_when_local_missing(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "get_object", lambda module, key: (b"remote-data", "application/octet-stream"))

        assert store.read_bytes("hazard/photo.jpg") == b"remote-data"

    def test_returns_none_when_missing_everywhere(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "get_object", lambda module, key: None)

        assert store.read_bytes("hazard/nope.jpg") is None

    def test_local_takes_priority_over_minio(self, tmp_path, monkeypatch):
        _write_local("safety/hazard/photo.jpg", b"local", tmp_path)
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "get_object", lambda module, key: (b"remote", "image/jpeg"))

        assert store.read_bytes("safety/hazard/photo.jpg") == b"local"

    def test_legacy_uploads_prefix_path(self, tmp_path, monkeypatch):
        _write_local("safety/hazard/old.jpg", b"old", tmp_path)
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        assert store.read_bytes("uploads/safety/hazard/old.jpg") == b"old"
        assert store.exists("uploads/safety/hazard/old.jpg") is True

    def test_read_bytes_none_when_local_missing_and_minio_disabled(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: False)

        assert store.read_bytes("safety/hazard/ghost.jpg") is None
        assert store.exists("safety/hazard/ghost.jpg") is False


class TestMaterialize:
    def test_local_path_returned_as_is(self, tmp_path, monkeypatch):
        f = _write_local("safety/hazard/x.pdf", b"pdf", tmp_path)
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "get_object", lambda module, key: (b"remote", "application/pdf"))

        result = store.materialize("safety/hazard/x.pdf", suffix=".pdf")

        assert result == f
        assert result.read_bytes() == b"pdf"

    def test_minio_key_downloaded_to_temp_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "get_object", lambda module, key: (b"remote", "application/pdf"))

        result = store.materialize("hazard/x.pdf", suffix=".pdf")

        assert result is not None
        assert result.exists()
        assert result.read_bytes() == b"remote"
        assert result.suffix == ".pdf"
        # 临时文件落在系统临时目录，不污染 uploads/
        assert tmp_path not in result.parents
        store.cleanup_temp(result)
        assert not result.exists()

    def test_returns_none_when_missing(self, monkeypatch):
        monkeypatch.setattr(store, "minio_enabled", lambda: True)
        monkeypatch.setattr(store, "get_object", lambda module, key: None)

        assert store.materialize("hazard/nope.pdf") is None
