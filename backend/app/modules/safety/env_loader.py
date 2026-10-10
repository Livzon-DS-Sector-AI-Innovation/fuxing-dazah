"""安全模块 .env 加载器（全模块唯一入口）。

安全模块 historically 绕过全局 Settings，各自在 import 时手动
``load_dotenv(.env.{APP_ENV}, override=True)``（feishu/client、bitable_client、
workticket_review/*、business_agent/agent、knowledge/reranker 懒加载共 6 处，
路径计算与文件名各不相同）。本模块收敛为单一实现：

- 进程内幂等（首个调用者生效，后续调用 no-op）；
- ``override=True`` 语义保留（.env 文件值覆盖进程预置 env，与历史行为一致；
  测试期 monkeypatch.setenv 发生在 import 之后，不受影响）；
- 文件名按 ``APP_ENV``（默认 development）；reranker 旧实现硬编码
  .env.development 且忽略 APP_ENV，属缺陷，随本次收敛一并修复。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_LOADED = False


def load_safety_env() -> None:
    """加载 backend/.env.{APP_ENV}（幂等；文件不存在时 no-op）。"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    # env_loader.py → safety/ → modules/ → app/ → backend/
    backend_root = Path(__file__).resolve().parents[3]
    env_path = backend_root / f".env.{os.getenv('APP_ENV', 'development')}"
    if env_path.exists():
        load_dotenv(env_path, override=True)
