"""仓库模块 AI 配置中心（镜像 safety/ai_config 范式）。

- registry：agent / agent_backup 双 profile 的代码唯一事实源（migration 播种源 + 运行时兜底）；
- scenario_registry：agent_chat / receipt_recognition 场景元数据；
- store / scenario_store：回退链 DB 活行 → env → registry 默认，缓存 TTL 60s；
- resolver：读链封装（含真实 api_key，仅内部使用）。

仓库模块为单模型位（视觉+文本同一模型），与 safety 的 5 profile 结构不同。
"""

from app.modules.warehouse.ai_config.exceptions import ScenarioDisabledError

__all__ = ["ScenarioDisabledError"]
