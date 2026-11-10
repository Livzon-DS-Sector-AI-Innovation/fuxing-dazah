# 04: Token 双层度量

**What to build:** Token -30% 冲刺的量化证据：①确定性层——离线脚本对同批样本描述组装完整 prompt（压缩开/关 × fewshot 新/旧四象限），用 tiktoken 计量输出前后对比表；②真机层——限量 ≤5 条真实轮询后 ai_call_audits（scenario=hazard_identification）input_tokens 均值与基线（近 30 天均值 8.75k）对比。降幅 ≥28% 达标、≥30% 冲刺完成。

**Blocked by:** 02、03（真机口径需截断与 fewshot 均在位）

**Status:** ready-for-agent

- [ ] 离线度量脚本产出四象限对比表（贴 .scratch/hazard-cost-p23/evidence/）
- [ ] 真机 ≤5 条轮询（真 Bitable 写回为黄色操作，执行前向用户确认）
- [ ] ai_call_audits 前后均值对比 SQL/curl 证据贴档
- [ ] 达标判定结论明确（≥28% 达标 / ≥30% 冲刺 / <28% 回到调参）
