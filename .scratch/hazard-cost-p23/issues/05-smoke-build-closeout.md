# 05: G3 四链灰度冒烟 + build 收口 + 提交收口

**What to build:** P2-2 Thread 留痕真机验证：热开 SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED → ①②⑤轮询 + 危险源辨识流各真实触发一轮（每链 ≤5 条，真 Bitable 写回前向用户确认）→ triggers 过滤端点与 /threads/{thread_key}/history 逐记录验证 ①②③⑤ 与辨识 Task 全历史 → curl 证据贴档 → 关开关。next build 补验（与用户约 dev:3000 停窗口）。3 commit 按 ticket 边界收口（不 push）。

**Blocked by:** 01、02、03、04（C3 收口顺序；冒烟本身独立于 token 工作但证据同档）

**Status:** ready-for-agent

- [ ] 四链各触发一轮，每链 ≤5 条，真写回前确认（黄色操作）
- [ ] /threads/{thread_key}/history 聚合验证 ①②③⑤ 与辨识 Task 全历史；curl 贴 .scratch/hazard-cost-p23/evidence/
- [ ] 冒烟后 trace 开关关闭，常开与否交用户拍板
- [ ] next build 零错误（窗口先约）；全量测试对比基线 diff 为空
- [ ] 3 commit（C1=01 / C2=02+03 / C3=05 含 04 证据）不 push，等用户指示
