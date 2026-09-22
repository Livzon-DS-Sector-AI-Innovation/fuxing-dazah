"""危化品库存直读包（chemical_inventory-direct，批次一-3）。

开关三件（全默认关，照 gates 语义）：
- SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED       直读总开关
- SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED   Bitable 事件 → 平台库镜像
- SAFETY_CHEMICAL_INVENTORY_WRITEBACK_RISK_ENABLED 直读重算的风险列回写

本域是「写完再读」回写域（与 cert 纯只读相反）：Excel→Bitable 写入路径零改动，
写完后直读全量 → 内存重算 → 风险列回写（开关罩）→ 再直读一次做分析日报。
"""
