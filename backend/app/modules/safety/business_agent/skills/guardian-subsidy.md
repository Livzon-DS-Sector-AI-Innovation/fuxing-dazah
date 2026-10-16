---
name: guardian-subsidy
description: 监护补贴计算与确认话术。当用户要整理/统计某部门某月的监护人补贴时加载。
---

## 步骤

1. 先调用 `preview_guardian_subsidy`（只读；参数：dept_keyword 部门关键词 + year + month）。**不要直接生成 Excel**。
2. 部门词为**包含匹配**（说「环保」即可命中「环保工程中心」）；未命中时工具返回候选部门清单（need_department_selection=true），向用户展示候选让其选择，不要瞎猜。
3. 预览返回后，向用户展示补贴清单并**原样引述** `confirm_suggestion` 话术（含「确认无误请回复『确认计算』」提示）。
4. 用户回复「确认计算」（或明确同意）后，才调用 `generate_guardian_subsidy` 生成 Excel 并回传会话；Web 渠道返回降级提示时，引导用户去飞书使用。

## 输出格式

- 预览展示：监护人名单（A证/B证）、计入补贴的作业票数、待核对与跳过张数，按工具返回字段呈现，禁止编造。
- 无证监护人按 A 证计入金额并进 unmatched 待核对名单（工具已处理，向用户说明即可）。
- 确认话术直接引述 `confirm_suggestion`，不要改写关键指令词「确认计算」。
