"""推送订阅中心（V3.0 分期A）：registry / store / generators / engine。

架构（spec Implementation Decisions）：
- 单泵轮询：平台引擎只注册一个 interval tick，tick 内读 DB 推送任务配置
  判断到期并执行，配置即生效；
- 内容生成器复用既有聚合函数，纯模板数据卡（清单类附 LLM 摘要，Ticket 03）；
- 全部写路径走 notification 发送件（dry_run 注入口）+ PushLog 落库。
"""
