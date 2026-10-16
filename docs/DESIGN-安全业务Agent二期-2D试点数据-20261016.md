# DESIGN-安全业务Agent二期-2D试点数据-20261016

> 2-D 域 Agent 试点（URS 委派式 vs 挂载式）对比数据与结论落档。
> 依据：两期实施计划二期 2-D；spec `.scratch/safety-agent-optimization-p2/spec.md`。
> 数据采集脚本：`backend/scripts/tmp/compare_urs_delegation.py`（真模型真库）。

## 一、试点机制（已落地）

- 开关：`SAFETY_AGENT_URS_DELEGATION`（app_config feature_flag，默认**关**=挂载式）。
- 开：路由命中 urs 域 → 挂「核心兜底 15 + delegate」；URS 9 工具由域子 Agent 持有
  （域专属 prompt `business_agent/domain_prompts/urs.md`，缓存 key=配置指纹+prompt mtime）。
- 挂起传播：子 Agent 写请求经 delegate 透传 → executor 合成 ToolCallPart →
  完全复用既有 pending action → 用户确认 → resume → 权限再校验 → 执行 → 审计链路
  （确认门/ROLE_TOOL_POLICY/审计恒在 orchestrator 与管道层，域 Agent 不复制）。
- 关：挂载式整域 9 工具（一期行为），一键回退零代码。

## 二、端到端冒烟（2026-10-16，本机真模型真库）

| 项 | 结果 |
|---|---|
| 路由（委派开） | rule 层命中 urs 域，挂载 16 工具（核心 15 + delegate），无 URS 域工具 ✓ |
| 端到端问答 | 「查一下最近的 URS 审核记录」→ 回答含 `total = 0` 的工具派生数据；该数据在委派模式下**仅能**经 delegate → 域子 Agent → query_urs_records 链路获得 → 委派链路（orchestrator→delegate→域 Agent→工具→审计）全链路跑通 ✓ |
| 单元/一致性 | test_agent_delegation.py 12 项 + 四重一致性 + 20 问回归全绿 ✓ |
| 回退路径 | 开关关 → 路由恢复挂载式 9 工具（test_routing_off_keeps_mounted_urs_tools 钉死）✓ |

## 三、对比数据（待采集——部署后跑脚本回填）

采集方法：`cd backend && PYTHONPATH=. uv run python scripts/tmp/compare_urs_delegation.py`
（自动开关两态各跑一遍并复位；输出延迟/工具选择/tokens 对比表 +
`.scratch/safety-agent-optimization-p2/delegation_data.json`）。

| 问句 | 模式 | 延迟 ms | 工具选择正确 | tokens | 备注 |
|---|---|---|---|---|---|
| （跑脚本后回填） | | | | | |

## 四、结论与建议（数据回填后拍板）

- 若委派式延迟 P50 不劣化且工具选择正确率 ≥ 挂载式 → 可考虑扩大（下一个候选：
  办公写域——低频独立，A1 原案第二域）。
- 若延迟显著劣化（多一跳 LLM 轮次）且正确率无增益 → 停在试点，URS 回退挂载式
  （关开关即可），域 Agent 资产保留（get_domain_agent + delegate 机制已验证）。
- 决策依据另参：一期路由实测数据（生产 ai_call_audits.extra.routing，部署后回看）。

## 五、已知边界（试点口径）

- 子 Agent 一次透传**一个**写请求（多写请求场景拆多轮，URS 工作流通常单写）。
- 确认后的写执行在 orchestrator 挂载面执行（resume 复用），不经域 Agent——
  这是方案 Y 的刻意取舍（最小侵入，确认门/审计零变动）。
