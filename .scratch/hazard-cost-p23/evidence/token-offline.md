# P2-3 离线 token 四象限度量（①主链 text 模式，不含图片 URI；终稿=默认200，调参轨迹见 token-tuning-trail.md）

- 样本：30 条真实隐患描述（snapshot.jsonl，真实 ragplus 检索）
- 截断上限：200 字/chunk；知识段字符 p50=3954
- 计量：tiktoken（estimate_tokens）

| 象限 | 均值 tokens | p50 tokens | 相对 A 降幅 |
|---|---|---|---|
| A 旧fewshot+全量知识（P2-3 前基线） | 13074 | 12886 | -0.0% |
| B 旧fewshot+截断知识 | 10618 | 10600 | -18.8% |
| C 新fewshot+全量知识 | 11526 | 11338 | -11.8% |
| D 新fewshot+截断知识（新默认） | 9070 | 9052 | -30.6% |

**结论：D/A = 69.4%，总降幅 30.6% —— ✅ ≥30% 冲刺达成**

> 注：视觉模式图片 URI token（~970/张）不在本次优化面，未计入；
> 真机口径见 evidence/token-realtime.md（ai_call_audits 前后对比）。
