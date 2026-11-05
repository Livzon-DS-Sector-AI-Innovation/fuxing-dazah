"""五金库 superagent 接入（二期 M6，设计 §九 9.2/9.3）。

- scan_source：hardware_alert_scan 事件源（cron 门控+五类事件扫描+digest/
  plan 定时触发，external_id 幂等=白名单∪闭环去重）
- rule：三规则按 payload.event_type 分流到三执行器
- executors：确定性函数执行器（催办卡/日速递/计划草案）——只产推送/草案/
  催办卡，零动账（放权红线 §9.3）
- bridge：kind+executor 注册（幂等；register_hardware_tasks 一并挂载）
"""
