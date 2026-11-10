# 02: 检索截断器 + ①主链接入

**What to build:** ①隐患 AI 识别主链注入给插件的知识库文本按 per-chunk 句子边界截断（上限可配、默认 350 字、0=关闭），含「第X条」或法规引用的行永不丢弃；检索 chunks 集合与引用证据对象完全不变，质量闸门/引用校验输入语义零变化。仅接①主链。

**Blocked by:** None（与 01 功能独立；同属 commit C2 故实现顺序在 01 后）

**Status:** ready-for-agent

- [ ] S2 纯函数测试：截断点必在句末标点后；条号行（第X条/第X.X条）与书名号行保留；短 chunk 不变；0=off 原样返回；重建格式与既有 build_markdown 一致（元数据行完整）
- [ ] S1 wiring 测试：截断开启时 plugin 收到的 knowledge_context 为压缩文本、CitationEvidence 仍从完整 chunks 构建；开关 0 时原 markdown 透传
- [ ] registry 新键（int，默认 350，0=off，热生效）走 commit-tree 流水线
- [ ] 判定/写回语义零变化：质量闸门与引用强校验的输入对象不变（断言级验证）
- [ ] ruff/mypy 无新增错误；测试全 fake
