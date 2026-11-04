# 安全模块飞书机器人 Agent 全能力实测验收报告

- **日期**：2026-10-29 10:05 – 11:07（北京时间）
- **环境**：后端 http://127.0.0.1:8000（.env.development）｜前端 http://localhost:3000（browser-use 驱动 IAB，正常水合）
- **入口**：/safety/agent-chat → POST /api/v1/safety/agent/chat/stream（SSE）
- **口径**：名册 106 工具（查询 56 + 写 50），三级角色 creator 106 / manager 90 / viewer 55（策略表实测 106/90/55 与简报一致）
- **身份**：creator=许康福（真实行）；manager=郭继龙(测试)（`identity.users` 造行 `ou_test_guojilong`/`guojilong`/发酵一部，引用既有 `guojilong→manager` 绑定）；viewer=测试访客(未绑定)（`ou_test_viewer`，无 agent_user_roles 行 → role=None）
- **造行方案（已执行，幂等，保留供回归）**：仅向 `identity.users` 插 2 行（employee_no=TEST-GL-001 / TEST-VIEWER-001，name 含「测试」标记）；**未插入/修改任何 agent_user_roles 行**。收尾核验：manager 52 / creator 4 与测前一致。
- **工具命中来源**：safety.ai_call_audits（scenario=agent_tool_call，每调用一行含 tool_name/args/role/status）按时间窗对账；会话/确认卡状态取自 agent_pending_actions。
- **红线执行情况**：除白名单测试群真确认因缺陷被安全阻断（见发现 #6，遗留 pending 卡已用 approved=false 干净取消）外，所有写操作停在确认卡或取消；update_chemical_inventory 唯一走到工具执行的用例（B09d）命中部门校验拒绝、零写入；未向任何真实群/真人发送内容；未 commit、未改业务代码。

---

## 一、A 组 · 查询面（30 例，creator）

| 编号 | 问法 | 路由命中工具（审计对账） | 预期 | 实际 | 结论 | 截图 |
|---|---|---|---|---|---|---|
| A01 | 灭火器什么时候到期？ | query_facility_ledgers ×2 | 到期清单 | 在用1331条/已到期4/30天内3，含部门责任人表 | ✅通过 | A01.png |
| A02 | 锅炉现在压力多少？ | query_telemetry_latest ×2 | 遥测读数 | 0条，如实说明未接入并给建议（采集默认关属实） | ✅通过 | A02.png |
| A03 | 最近有哪些变更？ | query_ehs_changes ×8 | 变更清单（曾补盲词） | 10月26条，按审批状态分表 | ✅通过 | A03.png |
| A04 | 7月10日有哪些隐患？ | query_hazards ×5 + query_hazard_stats | 日期过滤 | 当日1条明细+整月262条上下文 | ✅通过 | A04.png |
| A05 | 一部有哪些消防报警？ | query_fire_alarms ×13 | 报警清单 | 13次分页调用后合成挂死>6min，手动停止 | ❌挂死 | A05.png |
| A06 | 外审隐患没关的有几条？ | query_hazards ×2 (source=external) | 外审未关数 | 12条/未关5条+明细 | ✅通过 | A06.png |
| A07 | 谁有违章记录？ | query_training_behavior ×3 | 违章名单 | 42条全部三违回流、人员待补录，如实说明 | ✅通过 | A07.png |
| A08 | 外来人员保险到期的有哪些？ | query_visitor_insurance ×1 | 到期预警 | 3家过期在厂7人+临期清单 | ✅通过 | A08.png |
| A09 | 今天安全状况怎么样？ | （query_overview 未返回） | 驾驶舱总览 | 聚合>4min无产出（Bitable 2402条大拉取），手动停止 | ❌超时 | A09.png |
| A10 | 危化品库存趋势和异动分析一下 | query_chemical_trend ×3 + analyze_chemical_risk ×8 + query_chemical_inventory ×2 | 趋势/异动 | 13次工具调用后合成挂死 | ❌挂死 | A10.png |
| A11 | 今年的职业危害因素监测结果怎么样？ | query_oh ×6 | 监测结果 | 台账0条，如实报告不估算+补录建议 | ✅通过 | A11.png |
| A12 | MSDS查一下乙醇 | query_msds ×1 | SDS信息 | 2条记录（重复）+完整危险性表 | ✅通过 | A12.png |
| A13 | 今天的特殊作业日报 | （无工具调用） | 日报 | 路由后主模型首调挂死 | ❌挂死 | A13.png |
| A14 | 仓储物料库存现在还有多少？ | query_stock ×1 | 库存总量 | 1500批次仅返前10条，诚实说明无法汇总（单位不一） | ✅通过 | A14.png |
| A15 | 标准符合性达标情况怎么样？ | （无工具调用） | S1达标视图 | 主模型首调挂死 | ❌挂死 | A15.png |
| A16 | 相关方准入情况怎么样？ | query_contractor_admissions ×8 | 准入概况 | 112条+月度趋势+明细 | ✅通过 | A16.png |
| A17 | 持证预警有哪些人？ | query_cert_warnings ×11 | 预警名单 | 559条：逾期118/紧急6/重点41 | ✅通过 | A17.png |
| A18 | 应急演练记录有哪些？ | query_drills ×1 | 演练记录 | 79条+最近明细 | ✅通过 | A18.png |
| A19 | 防爆电气设备安装有哪些标准要求？ | knowledge_search ×2 | 知识库+引用 | GB50257/AQ3009 条目化回答带[N]标记；**无引用来源区块** | ⚠️通过(缺陷#10) | A19.png |
| A20 | 最近的关键风险作业有哪些？ | query_key_risk_ops ×6 | 风险作业 | 42条，今日在办6条明细 | ✅通过 | A20.png |
| A21 | 报备单待审批的有多少？ | query_special_operation_reports ×3 | 待审批数 | 0条+数据源差异说明 | ✅通过 | A21.png |
| A22 | 特种设备台账有哪些？ | query_facility_ledgers | 台账清单 | 如实说明特种设备/安全附件未接入，给接入状态表 | ✅通过 | A22.png |
| A23 | 设施校验任务现在什么情况？ | query_facility_tasks ×9 | 任务闭环 | 10条：逾期4/未闭环7，逾期表在前 | ✅通过 | A23.png |
| A24 | 中控最新报警有哪些？ | query_central_alarms | 最新报警 | 当日凌晨7条含时间岗位内容 | ✅通过 | A24.png |
| A25 | 隐患辨识在办的有哪几条？ | query_hazard_identifications ×6 | 在办清单 | 无「在办」状态→核实draft 323/completed 271 | ✅通过 | A25.png |
| A26 | 今年职业健康体检做了几批？ | query_oh_exams ×3 **failed** + query_oh ×3 + query_oh_persons ×1 **failed** | 体检批次 | 工具 AttributeError: exam_no，agent 如实报错 | ⚠️工具bug(#4) | A26.png |
| A27 | 最近的培训记录有哪些？ | query_training_behavior ×2 | 培训记录 | 1条未开始+法定缺口说明 | ✅通过 | A27.png |
| A28 | 本月新收录了哪些法规？ | query_latest_regulations ×1 | 法规收录 | 20条前11明细 | ✅通过 | A28.png |
| A29 | 消防器材都有哪些种类和数量？ | query_facility_ledgers ×27 | 种类统计 | 27次调用后合成挂死 | ❌挂死 | A29.png |
| A30 | 承包商在册人员有多少？ | query_contractor_workers ×1 | 在册人数 | 414人/30家+特种88+保险覆盖12% | ✅通过 | A30.png |

**A 组小结**：通过 23/30（76.7%）；挂死 5（A05/A10/A13/A15/A29）+ 极慢聚合 1（A09）；工具 bug 1（A26，agent 行为正确）。正常用例时延 5–30s，中位 ~10s。

## 二、B 组 · 写操作确认流（9 流程）

| 编号 | 问法/身份 | 命中工具 | 预期 | 实际 | 结论 | 截图 |
|---|---|---|---|---|---|---|
| B01 | 催办逾期灭火器责任人（creator） | query_facility_tasks | 说明催办范围 | 主动说明 send_hazard_urge 仅覆盖隐患台账，给3个替代方案 | ✅合理拒绝 | B01.png |
| B01b | 追问：催办真实未关闭隐患（同会话） | send_hazard_urge（record_id=reczz28P628yf54s） | 确认卡→取消 | 📋卡出（多轮上下文正确）→取消→「未发送任何消息」 | ✅通过 | B01b.png/B01b-cancel.png |
| B02/B02b | 导出本月隐患报表 | export_hazard_report(date_from/to, source=internal) | 卡→取消 | 首轮文本方案→回复确认→📋卡出→取消成功 | ✅通过 | B02.png/B02b.png/B02b-cancel.png |
| B03 | 冻结本季度标准符合性快照 | freeze_standard_check(date='2026-10-29') | 卡→取消 | 📋卡出5s→取消→给出Q3终版/按今天二选一 | ✅通过 | B03.png/B03-cancel.png |
| B04 | 把待审批的报备单审批通过 | query_special_operation_reports ×2 | creator可审批 | 0条待审批，如实无对象 | ✅通过(无对象) | B04.png |
| B05a/b | 中控日报推送到白名单群 | ~~push_report_to_chat~~ → generate_alarm_report | push卡 | **误配**：出的是 generate_alarm_report（无 chat_id） | ❌误配(#5) | B05.png/B05b.png |
| B05c | 点名 push_report_to_chat 重试 | **push_report_to_chat(report_kind=alarm, scope=central, chat_id=oc_726a9…99dd)** | 白名单真确认 | 📋卡出且 chat_id 正确入卡；**但确认必投业务总卡（#6）**→未确认，pending 已安全取消 | ⛔被缺陷阻断(#6) | B05c.png |
| B05d | 改走督办通报推送白名单群 | send_hazard_supervision_bulletin(chat_id=白名单) | 备选真确认 | 卡出且 chat_id 入卡；同因 #6 取消 | ⛔同上 | B05d.png/B05d-cancel.png |
| B06 | 把隐患督办通报推送到群里 | generate_supervision_bulletin ×2 | 系统确认卡 | 方案完整但**文本征集确认、未出卡**；引用来源区块泄漏原始HTML表格+RAG串台 | ⚠️不一致(#7/#10) | B06.png |
| B07 | 把今天最新那条中控报警处置掉 | ~~resolve~~ → generate_alarm_report | 处置卡 | **误配**出日报卡→取消后 agent 补充「中控无处置流程，遥测才有」 | ⚠️误配(#5) | B07.png/B07-cancel.png |
| B08/b/c | 提交辨识草稿 HI-cvu8jaRpJTr9 进AI流转 | submit_hazard_identification(ref=HI-…) | 卡→取消 | 首轮文本方案；**裸「确认」脱轨（#7/#8/#9 复合）**；带上下文短语→📋卡出→取消 | ✅通过(留发现) | B08.png/B08b.png/B08c.png/B08c-cancel.png |
| B09/a-d | manager 跨部门改危化品库存（发酵一部改 aimo 子表乙醇） | update_chemical_inventory(department='aimo', quantity=500) | 部门拒绝 | 三轮预拒绝解释→坚持后📋卡出→**确认执行→「写入仅限本部门：目标[艾默]与发酵一部不匹配」，零写入** | ✅通过 | B09.png~B09d-confirm.png |

**B 组小结**：确认卡机制本体可靠（7 张卡参数全部正确展示、取消路径 7/7 干净、部门校验拒绝先于写入）。问题集中在路由误配（2 例）与推送类工具的 chat_id 缺陷。

## 三、C 组 · 权限矩阵抽查

| 编号 | 问法 | 身份 | 预期 | 实际 | 结论 | 截图 |
|---|---|---|---|---|---|---|
| C1m | 催办酸碱罐区隐患 | manager | 可达写流程 | 定位+催办方案（文本）+主动建议连带催办4条内部隐患，无权限拒绝 | ✅通过 | C1m.png |
| C2m | 把待审批的报备单审批通过 | manager | **应被拒** | 0条+「审批仅限报备单创建者本人」软拒绝（agent 预拦截，未触达硬权限层） | ✅通过(软拒) | C2m.png |
| C3 | 灭火器什么时候到期？ | viewer(未绑定) | 查询被拒 | 「权限不足…query_facility_ledgers 调用被拒」+绑定建议；审计 denied 行坐实 | ✅通过=发现#1 | C3.png |
| C1v | 催办一下那条隐患的责任人 | viewer(未绑定) | 写被拒+说明 | 「权限不足（角色 None 无权调用 query_hazards）」+完整解释 | ✅通过 | C1v.png |
| — | 今天安全状况怎么样 | 匿名(API探针) | 全拒 | role=None 全拒，session.role=None | ✅=发现#1 | （API 证据，审计 02:01:29 denied 行） |

**矩阵结论**：三档权限边界与 ROLE_TOOL_POLICY 完全一致；creator 独有工具（freeze/approve/submit辨识）manager 均不可达；manager 写面可达；未绑定 web 身份全拒（deny-by-default 生效）。

## 四、D 组 · 会话功能

| 编号 | 场景 | 预期 | 实际 | 结论 | 截图 |
|---|---|---|---|---|---|
| D1 | /new 清上下文（暗号测试） | 新会话不知暗号 | 会话上下文已清，但**跨会话记忆系统回放了暗号**（agent 坦承来自记忆条目） | ⚠️发现#9 | D1.png |
| D2 | 多轮追问（A04→只看未关？/B01→换隐患台账/B02→确认导出） | 带上下文 | 三处多轮上下文全部正确继承 | ✅通过 | 并入 A04/B01b/B02b 截图 |
| D3/D4 | 确认/取消按钮路径 | 确认执行/取消留痕 | 取消 7/7：toast「操作已取消」+pending→rejected+agent 后续话术；确认 1/1（B09d 部门拒绝）；API 取消路径亦验证（B05c 遗留卡） | ✅通过 | 各 *-cancel.png / B09d-confirm.png |

---

## 五、发现的问题清单（只记录，未修复）

**总账口径：11 缺陷 + 9 数据质量注记 + 1 环境注记 = 21 项；11 个失败/注记用例收敛到 #2/#3/#4/#5/#6/#9 六个病根；#1 是唯一测试全绿但影响面最大的 P0；#7/#8/#10/#11 来自通过的用例。**

| # | 严重度 | 问题（病根） | 测试症状（表象） | 影响 |
|---|---|---|---|---|
| 1 | P0 | web 链路 role=None 无 viewer 兜底（与飞书链路不一致） | C3/C1v 查询与写全拒（权限测试通过，暴露设计差异） | 1300+ 未绑定员工 web 端不可用 |
| 2 | P0 | 主模型 LLM 调用间歇挂死、无超时 | A05/A10/A29（扇出后合成挂）、A13/A15（首调挂）共 5 例失败；僵尸轮 >22min | 挂死率 17%，可用性最大杀手 |
| 3 | P0 | push_report_to_chat 显式 chat_id 被速递总卡开启时的执行端无视 | B05c/d 真确认被阻断（确认必误投业务总卡） | 指定群推送不可用 + 误投风险 |
| 4 | P1 | query_oh_exams / query_oh_persons `AttributeError: exam_no` | A26 查不出（agent 如实报错），审计 failed×4 | OH 两条查询链路损坏 |
| 5 | P1 | 「推送日报」「处置报警」误配 generate_alarm_report | B05a/b（丢 chat_id）、B07（处置变生成日报） | 写意图与工具错位 |
| 6 | P1 | query_overview 交互聚合无优化无进度 | A09 >4min 无产出（2402 条大拉取） | 总览口语问法不可用 |
| 7 | P1 | 写确认两套模式并存 + 裸「确认」脱轨 | B06/B08/C1m 首轮文本确认无卡；B08b 裸「确认」只挂 4 工具+记忆串扰 | 须复述完整上下文才能确认 |
| 8 | P1 | 取消后同会话追问 `UserError: unprocessed tool calls` | B05d 首试报废须 /new | 取消破坏会话连续性 |
| 9 | P2 | /new 只清会话、跨会话记忆回放 | D1 暗号回放；B08b 引用 B06 旧数字（#7 串扰源） | 「清空」≠遗忘，敏感内容留存 |
| 10 | P2 | RAG 引用呈现双缺陷 | A19 无引用区块；B06 倒灌无关文档原始 HTML（串台+未转义） | 引用可信度受损 |
| 11 | P2 | 仓储库存工具单次仅返 10 条无聚合 | A14 1500 批次只回 10 条 | 库存总量类问题给不出总数 |

**数据质量注记（9 条，agent 如实上报，非 agent 缺陷）**：锅炉遥测 0 条（采集默认关）｜OH 监测台账 0 条（含岗位危害因素）｜培训计划仅 1 条未开始｜违章档案 42 条人员字段全空｜MSDS 乙醇重复 2 条｜平台报备单 0 条｜外来人员保险覆盖率仅 12%｜特种设备+安全附件台账未接入｜辨识草稿积压 323 条未提交

**环境注记（1 条，非产品缺陷）**：IAB webview 重载后约 1 分钟内点击/键盘事件不可达（页内 JS `.click()` 兜底；真实浏览器用户不受影响）。

---

### 分级详述

**P0/高优先级**
1. **web 链路 role=None 无 viewer 兜底（渠道行为不一致）**：飞书链路未绑定者兜 viewer（55 只读工具），web 链路 `_build_deps`→`get_user_role` 返回 None→`allowed_tools(None)=∅` 全拒（含所有查询）。影响：所有未配 agent_user_roles 的员工（当前仅 56 人绑定，全厂 1400 人）在 web 端机器人完全不可用。证据：C3/C1v 截图+审计 4 行 denied+API 探针；代码 `business_agent/session_store.py:280`、`core/permissions.py:443`。
2. **主模型 LLM 调用间歇挂死、无超时兜底**：5 例（A05/A10/A29 为多工具扇出后合成挂；A13/A15 为路由后首调挂），挂死率 5/30≈17%。前端永远「正在处理」无错误提示，仅能手动停止且停止只断前端（服务端僵尸轮持续，A05 僵尸>22min）。后端日志在挂死窗口零输出（纯等待 provider）。正常轮主模型 6.5–29s、路由器稳定 ~400ms。
3. **push_report_to_chat「指定群」缺陷（白名单真确认被阻断）**：路由可达且 chat_id 正确入卡（B05c 证据），但三类报表执行端在速递总卡开启时**全部无视显式 chat_id**（supervision→`send_bulletin` digest 分支；alarm→`generate_daily_report` digest 分支；daily_op 同族）——确认会把内容误投到真实业务总卡。结论：「推送到指定群」当前实际不可用。代码 `hazard_direct/bulletin.py:415-426`、`central_alarm/service.py:505-510`。

**P1/中优先级**
4. **OH 两查询工具损坏**：query_oh_exams（3 次 failed）、query_oh_persons（1 次 failed）均 `AttributeError: exam_no`（A26，审计 failed 行）。体检批次/人员职业健康台账两条查询链路坏。
5. **路由误配 2 例**：「处置报警」→generate_alarm_report（应 resolve_telemetry_alarm 或先澄清）；「推送日报到指定群」首轮→generate_alarm_report（丢 chat_id）。
6. **query_overview 交互式聚合不可用**：单轮 Bitable 拉取 2402+ 条、>4min 无返回无进度反馈（A09）。
7. **写操作确认交互不一致 + 裸「确认」脱轨**：系统确认卡（urge/export/freeze/submit/chemical/push）与文本征集确认（督办通报/辨识首轮/催办首轮）两套并存；裸「确认」回复时路由仅挂载 4 个设施域工具，叠加跨会话记忆注入（引用了无关督办数字），确认意图完全脱轨（B08b）——用户必须复述完整上下文短语才能走通。
8. **取消后同会话追问报错报废**：`UserError: Cannot provide a new user prompt when the message history contains unprocessed tool calls`（B05d 首试），须 /new 才能恢复。

**P2/低优先级**
9. **/new ≠ 遗忘**：会话上下文清空，但记忆提取已把内容持久化并在新会话注入（D1 暗号回放；B08b 引用 B06 数字）。功能按设计工作，但与「清空对话」的用户预期有落差，且含敏感信息的对话会留存记忆。
10. **RAG 引用呈现两缺陷**：A19 正文带[N]标记但「引用来源」区块缺失（sources 空提取）；B06 区块渲染了无关文档（数据交换规范）的原始 HTML 表格（未转义+检索串台）。
11. **仓储库存工具单次仅返 10 条且无聚合能力**（A14，agent 诚实说明局限——单位不一不可加总）。

**数据质量注记（agent 如实上报，非 agent 缺陷）**：锅炉遥测 0 条（采集默认关）；2026 职业危害监测台账 0 条；培训计划仅 1 条未开始；违章档案 42 条人员字段全空；MSDS 乙醇重复 2 条；平台报备单 0 条；外来人员保险覆盖率仅 12%（81% 报备未填保险有效期）；特种设备+安全附件台账未接入（A22）；辨识草稿积压 323 条未提交（A25）。

**环境注记（不计入产品缺陷）**：IAB webview 重载后约 1 分钟内 click/keydown 事件不可达（Playwright 点击超时、原生 Enter 无效），需页内 `element.click()` 兜底——与既往「IAB 水合挂死」家族同源，真实浏览器用户不受影响。

## 六、汇总

- **通过率**：A 组 23/30（76.7%）；B 组确认卡机制 7/7 出卡、取消 7/7、误配 2；C 组 4/4+探针；D 组 3/4（/new 部分通过）。全量 47 个可判定用例（A30+B9 流程+C4+D4），**宽松口径 38 通过（80.9%）、严格口径 36 通过（76.6%，见下）**；未通过项零「错误回答」——全部是挂死/超时/工具损坏/路径被阻断，agent 无一编造数据。
- **未通过清单（严格口径 11 项；B05 四个子步骤在宽松口径折算 1 个流程失败）**：

  | 用例 | 归类 | 根因 |
  |---|---|---|
  | A05/A10/A29 | LLM 合成挂死（13~27 次工具调用后） | 发现 #2 |
  | A13/A15 | LLM 首调挂死（零工具调用） | 发现 #2 |
  | A09 | query_overview 聚合 >4min 无返回 | 发现 #6 |
  | A26 | query_oh_exams/query_oh_persons AttributeError（agent 如实报错） | 发现 #4 |
  | B05a/b | 出卡工具误配 generate_alarm_report（chat_id 丢失） | 发现 #5 |
  | B05c/d | 卡片正确但确认必误投业务总卡，白名单真确认被阻断 | 发现 #3 |
  | B07 | 「处置报警」误配 generate_alarm_report | 发现 #5 |
  | D1 | /new 清了会话但跨会话记忆回放暗号，部分达成 | 发现 #9 |

- **带缺陷注记但计入通过（严格口径剔除的 3 项）**：A19（回答正确、引用来源区块缺失 #10）、B06（方案正确、文本确认未出系统卡 + RAG 串台泄漏 #7/#10）、B05a/b 取消路径本身。
- **根因集中度**：11 个未通过/注记项收敛到 5 个根因（#2 LLM 挂死、#5 路由误配、#3 chat_id 缺陷、#4 OH 工具 bug、#9 记忆行为）；仅修复 #2 即可将通过率恢复至 ~93%。
- **路由未命中清单**：无完全未命中域；「变更」补盲词有效（A03）；A13/A15 因挂死无法判定路由结果；「处置报警」「推送日报」两处语义误配（#5）。
- **与飞书侧行为差异**：①未绑定身份 web 全拒 vs 飞书兜 viewer（#1）；②web 匿名可用（role=None 全拒）vs 飞书必有 sender；③web 端导出/文件回传走 base64 降级、办公室创建工具带 Web 降级提示（代码层确认，未实测）；④其余查询/确认流行为与飞书侧同构（同 run_turn/权限/审计链）。
- **测试资产（保留）**：identity.users 两行测试身份（TEST-GL-001 manager / TEST-VIEWER-001 未绑定）；token 铸法见报告头部；61 张截图与 /tmp/*-snapshot.txt 快照。
- **建议修复顺序**：#2 LLM 超时+前端错误提示（可用性根基）→ #1 web viewer 兜底（覆盖面）→ #3/#5 推送路由与 chat_id（写面正确性）→ #4 OH 工具 bug → #7/#8 确认交互统一与会话恢复。

---

*报告由 ZCode 自动化验收生成；所有结论可由 screenshots/ 与 safety.ai_call_audits（2026-10-29 02:05–03:07 UTC 窗口）复核。*
