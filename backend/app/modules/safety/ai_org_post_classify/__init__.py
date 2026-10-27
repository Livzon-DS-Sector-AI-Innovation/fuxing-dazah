"""AI 岗位族归类插件（#4）——包出口。

场景键：org_post_classify（ai_config/scenario_registry 注册，text/system）。
产物是归类行（source='ai'，人工确认/修正置 manual 后成资产）。
"""

from app.modules.safety.ai_org_post_classify.plugin import (
    OrgPostClassifyError,
    OrgPostClassifyPlugin,
)
from app.modules.safety.ai_org_post_classify.schemas import PostFamilyItem

__all__ = [
    "OrgPostClassifyError",
    "OrgPostClassifyPlugin",
    "PostFamilyItem",
]
