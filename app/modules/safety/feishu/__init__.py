"""安全模块专属飞书集成。

使用独立的飞书应用凭证（SAFETY_FEISHU_APP_ID / SAFETY_FEISHU_APP_SECRET），
与全局 platform/integrations/feishu 完全隔离，不影响其他模块。
"""

from app.modules.safety.feishu.bitable_id_mapper import (
    get_bitable_open_id,
    get_bitable_person_value,
    get_user_id_by_bitable_open_id,
)
from app.modules.safety.feishu.catch_up import (
    diagnose_missed_records,
    recover_unprocessed_records,
)
from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)
from app.modules.safety.feishu.identity_resolver import (
    IdentityResolver,
    ResolvedPerson,
)

__all__ = [
    "diagnose_missed_records",
    "recover_unprocessed_records",
    "get_bitable_open_id",
    "get_bitable_person_value",
    "get_user_id_by_bitable_open_id",
    "get_safety_feishu_client",
    "get_safety_tenant_token",
    "IdentityResolver",
    "ResolvedPerson",
]
