"""工具箱临时文件存储：文件系统，无数据库。

- 上传文件与工具产出文件统一落在系统临时目录下按 execution_id 分目录。
- 扩展名白名单，其余回退 .bin。
- 惰性清理：maybe_cleanup() 按小时节流扫描删除超龄执行目录。
"""

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

EXEC_DIR_ROOT = Path(tempfile.gettempdir()) / "toolbox"
# 文件保留两倍会话 TTL，覆盖会话续期期间目录不被误删
MAX_AGE_SECONDS = 48 * 3600
_CLEANUP_INTERVAL_SECONDS = 3600

_ALLOWED_SUFFIXES = {".docx", ".png", ".jpg", ".jpeg", ".pdf", ".csv", ".txt", ".json"}


def exec_dir(execution_id: str) -> Path:
    d = EXEC_DIR_ROOT / execution_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in _ALLOWED_SUFFIXES else ".bin"


def save_upload(execution_id: str, filename: str, data: bytes) -> tuple[str, Path]:
    """落盘上传/产出文件，返回 (file_id, 落盘路径)。"""
    file_id = uuid.uuid4().hex
    path = exec_dir(execution_id) / f"{file_id}{_safe_suffix(filename)}"
    path.write_bytes(data)
    return file_id, path


def resolve_file(execution_id: str, file_id: str) -> Path | None:
    d = EXEC_DIR_ROOT / execution_id
    if not d.exists():
        return None
    matches = [p for p in d.iterdir() if p.stem == file_id]
    return matches[0] if matches else None


def touch_exec_dir(execution_id: str) -> None:
    """刷新执行目录 mtime：会话每次被使用即续期，防止清理器误删活跃会话的文件。

    会话 TTL 由 Redis 在每次步骤执行时续期，但目录 mtime 只在写入文件时更新；
    纯文本步骤（如「配置字段」重跑）会让目录超过 MAX_AGE_SECONDS 而被删除。
    """
    d = EXEC_DIR_ROOT / execution_id
    if d.is_dir():
        os.utime(d)


def cleanup_stale(max_age_seconds: int = MAX_AGE_SECONDS) -> int:
    if not EXEC_DIR_ROOT.exists():
        return 0
    now = time.time()
    removed = 0
    for d in EXEC_DIR_ROOT.iterdir():
        if not d.is_dir():
            continue
        try:
            if now - d.stat().st_mtime > max_age_seconds:
                shutil.rmtree(d)
                removed += 1
        except OSError:
            continue
    return removed


_last_cleanup = 0.0


async def maybe_cleanup() -> None:
    """节流清理：距上次不足 1 小时直接跳过；rmtree 放线程池避免阻塞事件循环。"""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup = now
    await asyncio.to_thread(cleanup_stale)
