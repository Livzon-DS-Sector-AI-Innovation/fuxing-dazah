# 安全 Agent 验收缺陷修复日志（fix-plan.md 实施）

实施：2026-10-29，ZCode。分支 feature/warehouse-module（唯一分支直提直推）。
修复计划：`fix-plan.md`；验收基线：`report.md`（47 用例 11 缺陷）。

## 拍板点处置

开工前 4 个拍板点用户未应答，按任务指示「不空等」全部采用 fix-plan 建议案：

| 拍板点 | 采用 |
|---|---|
| #1 匿名 web 口径 | 登录未绑定→viewer；匿名（无 cookie）→全拒 |
| #3 显式群与总卡 | 点名群只发点名群，不双写总卡 |
| #2/#6 超时档位 | LLM 120s / 轮次 150s / 工具 120s / overview 单域 30s |
| #9 记忆 | 默认保留注入 + 新增 /forget |

## 测试基线与判罚

- 全量基线 R1（批次①改码后）：64 failed / 3606 passed / 11 skipped / 3 errors
- 批次①收口全量：63 failed（diff R1：facility_dispatch 一次 flaky，单跑绿；2 个 test_live_* 转绿）
- 批次②-⑤收口全量：65 failed（diff：+3 个 `test_live_*`——gmp/mcp/cards，真实外呼+LLM 行为漂移型 flap，R1 与批次①之间本就互跳，仓库域，与本改无关；facility_dispatch 本轮绿）
- **结论：无代码回归**。预存红家族见 R1（production 8 / domain_pages 2 / facility_map 3 / overview 3（数据污染，git stash 对照已证预存）/ regulation_ingest 3 / warehouse 若干 live 类等）
- overview 3 红经 stash 对照证实未改动代码时同样失败（training-behavior 违章 42 条数据污染）

## 批次① 稳定性（#2+#6+#8）——commit 9097fcbe

**改动**
- `business_agent/agent.py`：AgentRuntimeConfig 增 timeout（ai_config registry 默认 120 接线、指纹并入）；`_build_agent` 显式 `httpx.AsyncClient(Timeout(120, connect=5))` 传入 DeepSeekProvider（openai SDK 默认 read 600s 是挂死根因）
- `business_agent/executor.py`：run_turn/resume 两处 `_agent_run` 外包 `asyncio.wait_for(timeout+30s)`——TimeoutError 单独分支（友好话术+failed 审计；resume 超时话术防重复发起）；`_has_unprocessed_write_call` pending 守门
- `core/pipeline.py`：execute_tool 工具层 120s 超时（顺带兜慢工具）
- `service/overview.py`：`_run` 单域 30s 超时降级
- **#8 深挖根治——web 会话断链**：`session_store.get_or_create_session` 支持 chat_id 为 UUID 时按行 id 回查 + `api/business_agent.py` 会话解析后把 `deps.session_id` 对齐真实行 id。修复前：web 前端回传行 id 但查行按 chat_id（首轮随机串）→ 每轮新建空会话行、上下文断链、首轮事件孤儿化（守门/UserError 的真实土壤）
- `frontend/.../AgentChat.tsx`：fetch AbortController + 160s 计时（看门狗 150s+余量）；/stop 真正中断 fetch
- 测试：`test_agent_acceptance_fixes.py` 前 11 钉子全绿

**真机**：正常问答 11.5s 无回归；B05d 出卡→不点→新消息=⚠️守门话术（原 UserError 报废）；取消→同会话追问续链正常。

## 批次② 权限面（#1）——commit 1f97dbcd

- `api/business_agent.py _build_deps`：feishu_user_id 非空 → role 兜底 viewer（绑定角色者不受影响）；匿名保持 None 全拒
- 真机：TEST-VIEWER-001「灭火器什么时候到期」10.2s 真实作答（C1v 转绿）；匿名直调角色 None 全拒（C3 维持）

## 批次③ 推送正确性（#3+#5）——commit 9171e20c

- **#3 关键侦查修正**：fix-plan 假设「值守轮询不带 chat_id」不成立——实测值守轮询带 `digest_chat_id()`、四个定时任务在 scheduler_task_configs 均配 `target_chat_id=oc_f055…`，service 层按「chat_id 非空直发」会翻掉全部定时链。改**工具层方案**：`push_report_to_chat` 收到显式 chat_id 时 supervision=build_bulletin+send_group_card 直发、alarm=generate_daily_report(push=False)+直发，绕开 service digest 分支；定时链路（不带显式目标）零字节不变
- **#5**：`generate_alarm_report` docstring 钉死「仅生成报告内容」+推送/处置消歧三行；`push_report_to_chat` docstring 强化「显式群必选」
- 真机：B05a 一轮 3.2s 直出 push_report_to_chat 卡（chat_id 入卡）；**B05c 白名单真确认**：测试群 oc_726a…收到消防日报卡（2 条报警）+ 速递总卡 fire/central 格仍空、hazard_bulletin 6187 字不变（点名不双写 ✓）

## 批次④ 数据正确性（#4）——commit caf61c6a

- `read_tools.py`：`_oh_field`（直读 OhRowView.mapped 缺键→default / 镜像 ORM getattr）+`_oh_date`；query_oh_exams / query_oh_persons 全字段对齐
- 真机：A26「这个月有多少人体检」7.3s 如实作答（0 人/336 条无体检日期行——正是原 AttributeError 崩溃行）

## 批次⑤ 体验（#7→#10→#9→#11）——commit 5b8ca149

- **#7 粘性路由**：裸肯定/否定白名单（≤6 字精确匹配）→ 沿用上一轮用户消息路由口径（审计 sticky=true）；`_previous_user_message` 剥 S4 前缀、跳过 resume 轮空合成 prompt 与裸词自身。真机：取消卡后裸「好的」sticky=true（hazard 域）直出 send_hazard_supervision_bulletin 系统卡
- **#7 确认统一**：agent.md 规则1重写「写操作直接触发确认卡」（原「先复述后执行」正是文本征集确认病根）+规则12「无对应工具先澄清」（#5）；压缩后 8185B 守住 8KB。真机：B08 首轮直出 submit_hazard_identification 卡（原文本方案）
- **#10**：`_extract_knowledge_sources` structured_content 失败回退解析 part.content JSON（A19 空 sources）+ 无 sources 打 debug；`_clean_snippet` strip HTML+压空白+120 字截断（B06 表格倒灌）。真机：受限空间氧含量问 sources=3、chunk 121 字无 HTML
- **#9 /forget**：`POST /agent/memories/forget` 软删当前用户全部记忆 + 前端指令二次确认弹窗 + /help 记忆留存提示。真机 D1：暗号回放→forget 删 116 条→新会话失忆 ✓（**验证后已按时间戳恢复 119 行真实记忆**，含验收期暗号；测试新增「菠萝披萨」一条留存无害）
- **#11**：warehouse `query_stock` 增 `summary` 参数——物料×单位聚合（总数量/批次数/物料数，前 50）；安全侧 wrapper 透传+docstring 钉死「总量问题置 true」。真机 A14：1500 批次/252 物种聚合表（原只回 10 条明细）

## 统一回归清单复测（2026-10-29 真机，creator=许康福）

| 项 | 结果 | 实测 |
|---|---|---|
| A05 消防报警清单 | ✅ 45s 答案（52 条分部） | 原 >6min 挂死 |
| A09 安全总览 | ✅ 36s 答案 | 原 >4min 无产出 |
| A10 危化品趋势异动 | ✅ 23s 答案 | 原 13 工具挂死 |
| A13 特殊作业日报 | ✅ **150s 超时话术**（终态不再转圈） | 原首调挂死；真因 generate_daily_report 重同步+AI 超 150s，按拍板档位起步、后续按审计分位调 |
| A15 标准符合性 | ✅ 127s 答案（55 条/50%） | 原首调挂死 |
| A29 消防器材统计 | ✅ 68s 答案（1331 条分种） | 原 27 调用挂死 |
| B05c 白名单真确认 | ✅ 测试群收到卡+总卡三格零变化 | 见批次③ |
| B07 处置误配 | ✅ 首轮澄清（中控无处置工具，不再误配 generate_alarm_report） | |
| B08/b 首轮出卡 | ✅ 一轮直出 submit_hazard_identification 卡 | 原文本方案 |
| B08b 裸「确认」 | ✅ 卡未点=守门话术；取消后=sticky 路由+系统卡 | 原脱轨 facilities |
| B05d 序列 | ✅ 守门→取消→追问续链 | |
| C3/C1v viewer | ✅ 兜 viewer 答疑/匿名全拒 | |
| A26 OH 工具 | ✅ 不崩、如实作答 | |
| A19/B06 引用 | ✅ sources 3 条、chunk 清洗无 HTML | |
| D1 /new+/forget | ✅ 回放→清除→失忆（真实记忆已恢复） | |
| A14 库存总量 | ✅ 聚合概览 | |
| B02 导出卡→取消 | ✅ 一轮出卡→取消干净（本月 207 条） | |
| B01/B03 | ✅ 同机制覆盖（本日 5 次出卡×取消全干净） | |
| B09 部门拒绝路径 | ⏭️ 未实跑：creator 不走部门校验=真执行会真写（违反红线）；守卫代码本次零改动，卡+确认链已验 | |
| 定时链路 | ✅ service 层零字节改动（工具层方案）；B05c 后总卡三格逐字节不变；周四 13:00 督办+值守轮询路径未触碰 | |

## 遗留与观察项

1. **A13 类重报表轮次超 150s**：按拍板档位起步；观察 ai_call_audits 分位再调（fix-plan 原口径）
2. **RAG 检索串台**（B06 检索到平台对接文档）：fix-plan 观察项，ragplus 侧调参/业务域过滤，未动
3. **agent.md 8185B/8192B**：仅 7B 余量，后续加准则必须先压缩
4. **B09 精确复测**需 manager+部门身份的测试绑定（不动现有绑定的红线内未做）
5. 验收数据质量注记 9 条（锅炉遥测 0 条等）为业务动作，不在本任务范围（fix-plan「数据质量注记处置」表）

## Commit 清单

- 9097fcbe 批次①稳定性
- 1f97dbcd 批次②权限面
- 9171e20c 批次③推送正确性
- caf61c6a 批次④数据正确性
- 5b8ca149 批次⑤体验（含②③④⑤全部钉子测试 28 个）
