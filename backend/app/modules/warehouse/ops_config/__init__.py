"""仓库模块运营配置（ops_config）。

- runtime_registry：Agent 运行参数键注册表（类型/范围/env 兜底的代码唯一事实源）；
- scheduler_registry：定时任务/告警目标行注册表（只能改值不能新增 job）；
- runtime_store / scheduler_store：随票 04 / 07 落地。
"""
