"""R3 运维自愈（告警自修复）—— Super-agent 底座第三应用。

设计：docs/DESIGN-SuperAgent-R3运维自愈-告警自修复-20261110.md
（S1 信号层 / S2 诊断执行器 / S3 修复层 / S4 观测 REST，拍板 7 点全按推荐）。

链路：扫描源+rag 直投 → Trigger（结构化幂等）→ rule r3_ops_failure
（组合 Policy，accept_mode 沿用现行）→ 执行器 r3_ops_heal 三段
（证据采集→LLM 归因→处方四道闸）→ 修复 effects（repair_mode 闸）→
四形态卡 → 关单双条件（恢复验证 ∧ 收口卡送达）。

红线：既有告警/调度/探活链零改动；scheduler_job_runs / task_run_log /
agent_effects 只读；LLM 输出永不直接执行；L3 动作永不注册。
"""
