# 05: Agent Web 网关（HTTP/SSE）

**What to build:** Web 端获得与飞书侧同等能力的对话通道：POST /api/v1/warehouse/agent/chat/stream（登录用户鉴权，body {message, session_id?}）——复用现有 Runner（工具循环/审计/技能/确认门）、会话按 web:{user_id} 维度隔离；返回 SSE 事件流：accepted → stage（正在调用 xxx）→ tool_call/tool_result → message（完整回复文本，前端做打字机）→ finished/error，带 sequence 与心跳；LLM token 级流式需重构 Runner（本次不做，事件流先行，票据备注说明）。场景熔断（agent_chat 停用时 503 友好错误）。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] SSE 事件序列路由测试（mock Runner：accepted/stage/message/finished 顺序与 sequence 递增）
- [ ] 鉴权测试：未登录 401；场景停用 503
- [ ] 会话隔离测试：web 会话与飞书会话互不可见（web:{user_id} 键）
- [ ] mypy/ruff 零新增
