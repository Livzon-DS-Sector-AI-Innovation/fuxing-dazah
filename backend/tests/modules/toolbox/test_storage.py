"""工具箱临时文件存储测试。"""

import os
import time
from pathlib import Path

import pytest

from app.modules.toolbox import storage


def test_exec_dir_root_under_uploads() -> None:
    """上传文件根目录位于项目 uploads/toolbox（不在系统临时目录）。"""
    assert storage.EXEC_DIR_ROOT == Path("uploads") / "toolbox"


@pytest.fixture
def exec_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(storage, "EXEC_DIR_ROOT", tmp_path)
    return tmp_path


def test_save_and_resolve_upload(exec_root: Path) -> None:
    fid, path = storage.save_upload("exec-1", "报告.docx", b"fake-docx-bytes")
    assert fid
    assert path.exists()
    assert path.read_bytes() == b"fake-docx-bytes"
    assert path.suffix == ".docx"
    p = storage.resolve_file("exec-1", fid)
    assert p == path


def test_resolve_missing_file_returns_none(exec_root: Path) -> None:
    assert storage.resolve_file("exec-2", "no-such-id") is None


def test_save_upload_dodgy_extension_falls_back(exec_root: Path) -> None:
    fid, path = storage.save_upload("exec-3", "恶意.exe", b"x")
    assert path.suffix == ".bin"
    assert storage.resolve_file("exec-3", fid) == path


def test_save_upload_keeps_xlsx_extension(exec_root: Path) -> None:
    """打卡核对等工具上传的 .xlsx 必须保留扩展名（openpyxl 依赖后缀识别格式）。"""
    fid, path = storage.save_upload("exec-4", "请假登记.xlsx", b"x")
    assert path.suffix == ".xlsx"
    assert storage.resolve_file("exec-4", fid) == path


def test_cleanup_stale_removes_old_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "EXEC_DIR_ROOT", tmp_path)
    old_dir = tmp_path / "old-exec"
    old_dir.mkdir()
    (old_dir / "f.bin").write_bytes(b"x")
    old_time = time.time() - 2 * 86400
    os.utime(old_dir / "f.bin", (old_time, old_time))
    os.utime(old_dir, (old_time, old_time))
    fresh_dir = tmp_path / "fresh-exec"
    fresh_dir.mkdir()
    (fresh_dir / "f.bin").write_bytes(b"x")

    removed = storage.cleanup_stale()
    assert removed == 1
    assert not old_dir.exists()
    assert fresh_dir.exists()


async def test_maybe_cleanup_throttled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """节流：1 小时内第二次调用直接跳过（rmtree 不重复执行）。"""
    monkeypatch.setattr(storage, "EXEC_DIR_ROOT", tmp_path)
    monkeypatch.setattr(storage, "_last_cleanup", time.monotonic())  # 刚清理过

    calls: list[int] = []

    def fake_cleanup() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(storage, "cleanup_stale", fake_cleanup)

    await storage.maybe_cleanup()
    assert calls == []  # 节流命中，未执行清理
