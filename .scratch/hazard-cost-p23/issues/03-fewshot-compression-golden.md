# 03: fewshot 5→3 例压缩 + golden 有意重生成 + 双回归

**What to build:** fewshot 示例从 5 例压至 3 例（保留例 1 unsafe_condition / 例 4 management_defect+substantive / 例 5 procedural 负例；删除例 2 unsafe_action、例 3 environmental；例内文本零改动），md 与代码兜底常量同步；golden 快照有意重生成并锁死新基线，其余 9 条静态快照字节不变；检索评测集与离线 replay 双回归绿。

**Blocked by:** None（与 02 功能独立；同属 commit C2 故实现顺序在 02 后）

**Status:** ready-for-agent

- [ ] prompt_skills/fewshot.md 删例 2/3，保留例内文本逐字节不动；prompts.py 兜底常量同步一致（md 缺失回退行为不变）
- [ ] golden fixtures 有意重生成：fewshot_examples.json + 含 fewshot 的组装快照更新；fewshot_marker/system-role/work-rules/defect-substance-rules/output-format/critical-constraints/text_nofewshot/模板类共 9 条快照逐字节不变（测试硬断言）
- [ ] manifest prompt_version bump 并注明变更理由
- [ ] 166 条检索评测集回归（口径：与既有基线 diff 为空）
- [ ] replay 离线回归：140 条历史成功样本规则 error=0 口径复验（新 fewshot 快照下）
- [ ] ruff/mypy 无新增错误
