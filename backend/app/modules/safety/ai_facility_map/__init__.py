"""AI 地点→分区建议映射插件（#2）——包出口。

场景键：facility_map_suggest（ai_config/scenario_registry 注册，text/system）。
产物是建议（dist_id 可空，允许无法判断不硬配），人工确认后才写
location_district_map——AI 不直接落映射资产。
"""

from app.modules.safety.ai_facility_map.plugin import (
    FacilityMapSuggestError,
    FacilityMapSuggestPlugin,
)
from app.modules.safety.ai_facility_map.schemas import DistrictSuggestion

__all__ = [
    "DistrictSuggestion",
    "FacilityMapSuggestError",
    "FacilityMapSuggestPlugin",
]
