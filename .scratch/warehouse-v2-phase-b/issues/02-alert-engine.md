# 02: 异常检测引擎与端点

**What to build:** 系统每日自动扫描并生成异常记录，管理员可手动触发、按类型/状态查询、标记已处理：规则纯函数（低库存/零库存/呆滞 idle_days/临期 expiry_days，阈值读 alert_rules）→ 扫描编排 upsert alert_records（open 幂等刷新，resolved 不复活）→ 定时任务（凌晨窗口守卫+互斥，模式同分期A 快照）+ POST /intelligence/scan 手动触发；GET /intelligence/alerts（分页筛选）、POST /intelligence/alerts/{id}/resolve；GET /intelligence/alerts/summary?rule_key= 返回 AI 解读（llm_client 白名单校验，异常降级规则模板文案，场景 key 注册 ai_config）。

**Blocked by:** 01 (预警数据底座)

**Status:** done

- [x] 规则测试：各类型造数→扫描→alert_records 断言（含阈值生效）
- [x] 幂等：重复扫描不重复建记录；手动 resolved 不复活（条件仍在）；系统自动解决的条件再现时重开
- [x] 手动触发 + 分页筛选 + resolve 路由测试
- [x] AI 解读降级路径测试（假 llm 抛错→规则文案，source=fallback）
- [x] mypy/ruff 零新增

> 备注：扫描任务 INTELLIGENCE_SCAN_TASK 每日 00:45（同窗口守卫），main.py 注册；呆滞/临期阈值从 alert_rules 读取。
