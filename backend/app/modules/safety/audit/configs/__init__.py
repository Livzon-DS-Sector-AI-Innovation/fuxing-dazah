"""外部审计缺陷接入 — 配置注册表"""

from app.modules.safety.audit.configs import (  # noqa: F401
    biz_2026h1,
    ehs_2025_1020,
    ehs_2025_1113,
    fuqing_emergency,
    jiangyin_committee,
)

# 注意：biz_2025(2025事业部EHS审计)、biz_cross_check(事业部交叉检查2026.07)
# 已按要求移除（来源链接失效），相关隐患记录也已删除。
ALL_AUDIT_TABLES: list[dict] = [
    ehs_2025_1020.AUDIT_TABLE_CONFIG,
    ehs_2025_1113.AUDIT_TABLE_CONFIG,
    fuqing_emergency.AUDIT_TABLE_CONFIG,
    jiangyin_committee.AUDIT_TABLE_CONFIG,
    biz_2026h1.AUDIT_TABLE_CONFIG,
]

AUDIT_TABLES_BY_NAME: dict[str, dict] = {t["name"]: t for t in ALL_AUDIT_TABLES}
