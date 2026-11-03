"""Super-agent 平台底座 —— 统一事件入口 / 两级研判 / 任务域 / 副作用队列 / Watchdog。

设计权威：docs/DESIGN-SuperAgent底座-一期平台基座设计-20261102.md
一期红线：现有应用零改动（仅 §6 三触点）、旁路上线、三冒烟验收。

分层（切片落位）：
- ``sources``   事件层：Source 插件 / Trigger 落库幂等 / 读位 cursor / Fast Path（1a）
- ``ingest``    事件入库服务（幂等 / disposition / Thread / cursor 事务推进）（1a）
- ``effects``   副作用层：effects 先存后做 + outbox 保序 + 健康认领制（1a）
- ``tasks``     任务域：agent_tasks / 阶段纯函数推导 / 订阅直通（1b）
- ``policy``    研判与策略：Policy 版本化 / Gate / 规则引擎 / observe-auto（1c）
- ``watchdog``  实质进展巡检 + DM 告警（1c）
- ``runtime``   调度引擎接线（TaskGenerator 注册 + bootstrap）
- ``api``       REST 观测面（/api/v1/platform/superagent/*）

进程模型：运行于现有 backend 进程，复用 SchedulerEngine（不新起裸 asyncio 循环）。
"""

from app.platform.superagent.sources import (
    PollResult,
    Source,
    SourceRegistry,
    TriggerDraft,
)

__all__ = ["PollResult", "Source", "SourceRegistry", "TriggerDraft"]
