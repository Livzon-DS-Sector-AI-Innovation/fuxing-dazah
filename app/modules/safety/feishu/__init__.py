"""安全模块专属飞书集成。

使用独立的飞书应用凭证（SAFETY_FEISHU_APP_ID / SAFETY_FEISHU_APP_SECRET），
与全局 platform/integrations/feishu 完全隔离，不影响其他模块。
"""

from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)

__all__ = [
    "get_safety_feishu_client",
    "get_safety_tenant_token",
]
