# 08: 快速登记前端

**What to build:** "快速登记"页面（/warehouse/quick-register，菜单入口）：①上传区（点击/拖选图片，类型与大小前端校验）②提交后进入草稿确认页：左侧单据原图、右侧识别结果表（物料/数量/批次等，低置信度行标黄）③逐行可改 → 提交（走既有确认/提交流程）→ 成功回执与看板刷新。读走 lib/api client，写走 Server Actions。

**Blocked by:** 07 (快速登记后端)

**Status:** done

- [x] 上传→识别→确认→提交全链路组件测试（mock lib/api 与 actions）
- [x] 低置信度行标黄样式正确
- [x] 菜单入口"快速登记"生效
- [ ] typecheck/lint 零新增
