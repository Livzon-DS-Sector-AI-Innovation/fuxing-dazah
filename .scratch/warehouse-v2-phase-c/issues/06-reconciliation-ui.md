# 06: 对账中心前端

**What to build:** "对账中心"菜单与页面：对账运行历史表（时间/发起人/状态/四态计数）+ "发起对账"按钮（确认提示：将拉取飞书台账，耗时取决于数据量）+ 运行详情抽屉（按状态分组的差异明细表，mismatch 行本地值/飞书值并排展示）。读走 client，发起对账走 Server Actions。

**Blocked by:** 05 (对账 schema + 引擎)

**Status:** ready-for-agent

- [ ] 运行历史表与详情抽屉渲染正确（组件测试 mock）
- [ ] 发起对账按钮触发 Server Action 并刷新历史
- [ ] mismatch 行双边值并排展示
- [ ] 菜单入口生效；typecheck 零新增
