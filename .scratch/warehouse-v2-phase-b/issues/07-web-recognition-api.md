# 07: 快速登记后端（上传+识别建稿）

**What to build:** 不开飞书也能录入：POST /warehouse/agent/uploads（multipart 图片上传，存 uploads/ 或 MinIO，返回引用 id，限大小/类型）；POST /warehouse/agent/recognition（body {upload_id}）→ 复用既有 pipeline（recognizer→aligner）创建 WarehouseAgentDraft（status=aligned，source='web'，created_by=登录用户）→ GET /warehouse/agent/drafts/{id}（草稿详情含置信度，供确认页渲染）→ 提交复用既有 submit 流程（draft→pending_confirm→confirmed→submitted 写回 Bitable）。迁移：warehouse_agent_drafts 增加 source 列（默认 feishu）。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] source 列迁移空库可执行
- [ ] 上传测试：类型/大小校验、返回引用
- [ ] recognition 测试：mock 识别结果 → draft 创建 status=aligned、source=web
- [ ] 提交走既有 submit（复用既有测试模式）；403/422 边界
