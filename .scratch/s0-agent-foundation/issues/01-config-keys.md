# 01 — WAREHOUSE_* 配置键进 core/config.py

**What to build:** 仓储飞书应用凭证、4 个测试版 Base token、Agent 模型三键与超时，作为 Settings 字段可被 warehouse 模块读取。纯字段声明、默认空串、零逻辑——对齐 METER_AI_*/SAFETY_FEISHU_* 既有模式。值已在 `.env.development` 中就位，本票不改 env。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `core/config.py` Settings 新增：WAREHOUSE_FEISHU_APP_ID/APP_SECRET、WAREHOUSE_FEISHU_BITABLE_MATERIAL/GMP/PROD/SALES_APP_TOKEN、WAREHOUSE_AGENT_BASE_URL/API_KEY/MODEL/TIMEOUT（默认空串；TIMEOUT 默认 120）
- [ ] 不动 settings.check() 的必填校验（WAREHOUSE_* 为可选键）
- [ ] live 验证：实例化 Settings 能从 .env.development 读到非空值（断言物料 token == LmuBb3 前缀、model == deepseek-v4-flash-vision-exp）
