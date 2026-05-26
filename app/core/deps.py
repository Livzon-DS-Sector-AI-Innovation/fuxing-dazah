from typing import Any

from fastapi import Request


async def get_current_user(request: Request) -> Any:
    """获取当前用户。

    Phase 1: 返回 None（无认证）
    Phase 2: 从飞书 SSO 获取用户信息
    """
    return None
