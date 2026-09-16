# 04: 报表中心前端 + NL 导出

**What to build:** "报表中心"一级菜单与页面：①出入库月报 Tab（月份选择器 + 汇总卡 + 明细表 + 导出按钮）；②周转率排行 Tab（升/降序切换）；③消耗排名 Tab；④当前库存报表 Tab；⑤晨报 Tab（历史列表 + 详情）。NL 导出卡片：输入自然语言 → POST /reports/nl-export（LLM 解析筛选条件→Excel 流）→ 失败降级当前筛选导出并提示。后端补 POST /reports/nl-export（LLM 白名单解析 + Excel 流）。

**Blocked by:** 01 (出入库月报 + Excel 导出), 02 (周转率/消耗排名/库存报表), 03 (每日晨报)

**Status:** ready-for-agent

- [ ] 四报表 Tab + 晨报 Tab 渲染正确（组件测试三态）
- [ ] 各报表导出按钮触发下载（mock fetch 断言）
- [ ] NL 导出：成功下载 + 解析失败降级提示（测试覆盖两路径）
- [ ] 菜单入口生效；typecheck/lint 零新增
