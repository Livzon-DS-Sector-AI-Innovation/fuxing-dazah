# P2-3 离线 token 四象限度量（①主链 text 模式，不含图片 URI）

- 样本：30 条真实隐患描述（snapshot.jsonl，真实 ragplus 检索）
- 截断上限：250 字/chunk；知识段字符 p50=3954
- 计量：tiktoken（estimate_tokens）

| 象限 | 均值 tokens | p50 tokens | 相对 A 降幅 |
|---|---|---|---|
| A 旧fewshot+全量知识（P2-3 前基线） | 13074 | 12886 | -0.0% |
| B 旧fewshot+截断知识 | 10960 | 11028 | -16.2% |
| C 新fewshot+全量知识 | 11526 | 11338 | -11.8% |
| D 新fewshot+截断知识（新默认） | 9412 | 9480 | -28.0% |

**结论：D/A = 72.0%，总降幅 28.0% —— ✅ ≥28% 达标**

> 注：视觉模式图片 URI token（~970/张）不在本次优化面，未计入；
> 真机口径见 evidence/token-realtime.md（ai_call_audits 前后对比）。
