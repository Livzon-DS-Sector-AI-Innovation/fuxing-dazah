# 03 — warehouse 内 LLM 客户端（tool calling + reasoning 契约）

**What to build:** `app/modules/warehouse/agent/llm_client.py`——WarehouseLLMClient，直连 DeepSeek 兼容网关。不触碰 `platform/integrations/ai/client.py`（用户拍板：platform 逻辑零改动）。接口：`chat_with_tools(messages, tools, tool_choice="auto", temperature=0.1, max_tokens=16384) -> AssistantMessage`（dataclass/pydantic：content、tool_calls[{id,name,arguments_json}]、reasoning_content、finish_reason、usage）。实现要点：httpx.AsyncClient 注入式构造（便于测试替换）；瞬时错误（5xx/网络）指数退避重试≤3；reasoning_content 透传提取；tools 为 None 时等价普通对话。配置读 Settings 的 WAREHOUSE_AGENT_*。

**Blocked by:** 01 — WAREHOUSE_AGENT_* 配置键。

**Status:** done

- [x] live 测试（真实 DeepSeek API）：带 tools 发起「查硫酸库存」→ 返回 tool_calls（函数名+JSON 参数正确）
- [x] live 测试：tool 结果回填后第二轮返回终局 content（非空）；无 tools 的普通对话正常
- [x] live 测试：reasoning 契约——max_tokens 充足时 content 非空；响应 reasoning_content 可提取
- [x] 错误路径单测（mock httpx）：5xx 重试 3 次后抛明确异常

## Comments

- 2026-09-03 实现完成，8/8 测试 PASSED（4 live + 4 mock），ruff 无新增告警。
  - live 实测：`query_stock({'keyword': '硫酸'})` finish_reason=tool_calls；回填后终局回复非空且无 tool_calls；max_tokens=2000 时 content 非空（usage.completion_tokens_details.reasoning_tokens=46，reasoning_content 成功透传）。
- 新增文件：`app/modules/warehouse/agent/__init__.py`、`app/modules/warehouse/agent/llm_client.py`、`tests/modules/warehouse/test_live_llm_client.py`。未触碰 platform/、core/。
- 契约落实：请求体不传 response_format（mock 用例断言请求体）；tools=None 时不传 tools/tool_choice 字段；arguments JSON 解析失败保留原始串至 `arguments_raw`；4xx 抛 `WarehouseLLMError(status_code, response_snippet)` 不重试；5xx/网络瞬时错误指数退避重试。
- 语义说明：MAX_RETRIES=3 按 meter `AI_MAX_RETRIES` 同义实现——总尝试次数上限 3（即最多 2 次退避重试），耗尽后抛 WarehouseLLMError；异常消息措辞「已尝试 3 次」以区别于重试次数。若需字面「重试 3 次」（4 次请求），改 MAX_RETRIES 常量即可。
- 429 未纳入重试集合：票面明确「4xx 不重试直接抛」，故 rate-limit 也即时抛错（meter 先例中 429 可重试，此处按票面从紧；S1 Runner 如需可放宽）。
- 构造器支持 `transport`（httpx.MockTransport 注入）与 `retry_backoff`（测试提速）注入，mock 用例显式传 base_url/api_key/model，完全不依赖 env。
