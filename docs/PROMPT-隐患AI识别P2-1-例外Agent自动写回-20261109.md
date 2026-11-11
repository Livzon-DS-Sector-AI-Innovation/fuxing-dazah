使用 feature-flow 技能，按完整流程开发「隐患 AI 识别 P2-1：例外复核 Agent auto 升格 + 重大隐患写前人工确认 + rescued 反馈闭环」。 仓库：/Users/cheris/Agent work/fuxing-dazah（路径含空格）。 参数建议：--feature hazard-exception-auto。

【前置状态（必读）】

P1-3 已 3-commit 落库（0a36db15 服务层 / 662ab885 接入与落点 / d4d2b862 skills 化，未 push）；工作树仍有他人未提交 WIP（宣传函会话：registry/tool_selector/core.permissions/executor/bot_handler/office_tools；②-b/②-c：review.py/bulletin/config 等；fire_inspection；仓储菜单前端）——动前 git diff 复核，只加自己 hunk，冲突先报告；严禁 revert/stash/提交无关文件。共享文件选择性暂存走 commit-tree 流水线（P1-3 先例：临时 GIT_INDEX_FILE 构造 HEAD+mine，update-ref 后 git reset --mixed 重同步主 index）。
P1 全阶段完成（P1-1 检索质量/P1-2 字段治理/P1-3 例外复核 observe/P1-4 质量看板）。
P1-3 遗留（顺带收口，不新开特性）：next build 补验（dev:3000 与 build 互杀 .next，需 dev 停窗口，与 P1-2/P1-4 欠账一起）；用户按 docs/GOVERNANCE-隐患登记 表字段处置清单-20261106.md 执行人工操作后通知工程侧复核列数 50→44；GB 30871 等真 PDF 后按 RUNBOOK §3.4 补录；**真机灰度未做**——群内「复核死信」跑出 rescued 率前不开 auto。
已交付基座（勿重做）：P1-3 observe 全链（exception_reviewer 服务层单接缝 run_exception_review/五工具/入口工具 review_hazard_exceptions/observe 确认卡/看板例外复核 Tab/定时任务默认关/app_config 三护栏键 3·8·20/golden 12 条零漂移锁）；superagent Policy（MODE_OFF/OBSERVE/AUTO，explicit 任何模式受理、inferred 在 observe 只记 would_accept、auto 才开任务、人工转正 resolve_decision）；business_agent PendingAction 确认流（requires_approval→确认卡→resume 时二次权限校验）；field_authority writer_whitelist/assert_write_allowed；P1-2 CAS 写前回读；P0 门禁（降级不写回/占位不写回/JSON 修复重试）。
需求来源：docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §3.3-B、§4.3 方案B（先 observe 后 auto）、§4.4（「权限/写确认：重大隐患/低置信写回前人工确认」）、§4.7 P2 验收行（人工复核率<10%；重大误判 0）、§5 P2-1 行、§6 风险3（重大隐患确认需合规拍板）。
仓库根 AGENTS.md、CLAUDE.md、CLAUDE.local.md 与 backend/AGENTS.md、backend/CLAUDE.md。CLAUDE.local.md：只能在 feature/warehouse-module 工作，禁止新建/切换分支。

【已拍板决策（设计文档+P1-3 定案，质询不重复问）】

P1-3 拍板8：observe→auto 升格点在 P2-1 接 Policy。
P1-3 拍板9：rescued 人工反馈（有用/没用覆盖程序判定）留本期加。
人工列唯一权威原则在 auto 期依然成立：**auto 写回目标=AI 列（候选证据列）**，人工列绝写（field_authority writer_whitelist 断言复用，测试钉死）。
①识别主链 prompt/行为零变化（golden 12 条字节锁不得破）。
P1-3 拍板6 成本护栏延续（3/8/20，app_config 可调）。
observe 期行为零回归：P1-3 全部测试必须原样绿。

【需业务确认（Step 1 质询必答清单，逐项给选项）】

auto 升格门槛：rescued≥60% 观察多少天（7/14/30）后人工开 / 无门槛纯开关灰度 / 两者结合（开关+看板达标提示）；
auto 写回范围：仅 rescued=true 且 proposed_action=adopt_ai / 全部 adopt_ai（rescued=false 也写但标注待验） / 分级（general 自动写、serious+major 必人工确认）（推荐）；
重大隐患确认口径：hazard_level=major 或 proposed_action=escalate 触发必确认（PendingAction 卡）——确认后由系统写 AI 列 / 人确认即视为终审只留痕；
写回冲突语义：沿用 P1-2 CAS（写前回读目标 AI 列与人工列，被并发修改则放弃）——冲突后动作：只留报告 / 自动重复核一次再放弃；
Policy 接入方式：superagent AgentPolicy 插 hazard_exception_review 的 observe/auto 策略行（get_current_policy 驱动，R1 播种先例） / 延续 app_config 独立开关 / Policy 行+开关双闸（注意双源一致性代价）；
rescued 反馈闭环：卡加「有用/没用」按钮人工改判（人工>程序）；历史报告可否改判（Redis 报告更新）；
死信闭环：auto 写回成功后自动 record_success 清死信（记录离开例外池与重试队列）——是否连带清 observe 报告；
看板新指标：auto 写回数/确认等待数/人工复核率（分母口径）/人工改判数——进既有「例外复核」Tab 还是独立 Tab。

【本次范围（§4.3-B auto + §4.4 写确认 + P1-3 遗留拍板）】

F1 写回执行器：propose_writeback 升格为真写工具（requires_approval 走 PendingAction 确认流）；写目标=AI 列白名单六列（隐患描述（AI）/隐患级别（AI）/隐患分类（AI）/隐患类别（AI）/隐患判定依据（AI）/整改建议（AI））；writer_whitelist 断言 + CAS 写前回读 + 写前过 P0 同款输出闸门口径（占位/引用不可验证不写）。
F2 auto 模式（Policy 驱动）：auto 下 rescued 且 adopt_ai 且 general 级直接进写队列（后台执行+结果卡）；major/escalate 强制人工确认；observe 档行为与 P1-3 完全一致。
F3 重大隐患人工确认流：复用 PendingAction（方案复述→确认执行→resume 二次权限校验→写回→终态卡）；确认人=creator。
F4 rescued 反馈闭环：observe/确认卡加「有用/没用」按钮；人工改判覆盖程序判定并回写 Redis 报告；看板 rescued 口径=程序判定×人工改判。
F5 死信闭环与指标：写回成功 record_success 清死信；看板例外复核 Tab 增 auto 维度（写回数/确认等待/人工复核率/改判数）。
F6 灰度与回退：auto 默认 off；observe 永远可回退且行为不变。

【硬性边界】

后端改动限 safety 模块（含 tests）+ business_agent 体系；superagent Policy 接入走既有扩展点（superagent_bridge 播种先例），动 platform/ 平台文件先问。
人工列绝写（writer_whitelist 断言+单测钉死）；不改 P0 门禁/P1-1 检索/P1-2 CAS 口径/P1-4 既有端点行为/①主链 prompt。
observe 零回归（P1-3 测试原样绿）；无 DB 迁移优先（auto 写回留痕若需 PG 存储先出方案质询）；无新依赖。
测试全 fake（PendingAction fake/写路径 fake/Policy fake）；真实写回验证先问且限量（跑前报条数）。
黄色操作先确认；红色操作（push/发布/删数据）不做；不新建/切换分支；只提交本窗口 hunk；不 push。

【验收/测试】

F1-F6 每项有单测：写白名单断言（只允许 AI 列六列，人工列混入立即抛）、CAS 冲突放弃路径、major/escalate 无确认零写、auto 队列执行与结果卡、Policy observe/auto 两档行为、反馈改判（人工>程序）口径、死信清理、observe 零回归。
全量：pytest tests/modules/safety + ai_hazard_identification/tests，与开工父 commit 干净快照对比 0 新增失败；ruff/mypy 窗口 0 新增；前端 tsc（next build 与欠账一起在 dev 停窗口补）。
提交前给：变更文件清单、验证命令与结果、逐项验收、遗留风险、WIP touched 说明；用户确认后提交（粒度质询定）、不 push。

【流程】

Step 1 质询至少覆盖：上述业务确认 8 项、auto 写回失败重试语义（写失败是否回 observe 池）、与记录级 Thread（§4.5 bitable:hazard:<record_id>）的关系是否本期挂、测试接缝、提交粒度；
Step 2 spec 写 .scratch/hazard-exception-auto/spec.md，先定测试接缝并确认；
Step 3 垂直切片 tickets（2-4h/个，标 Blocked by 与验收），先确认粒度；
Step 4 TDD（先 RED）；Step 5 双轴审查（Standards/Spec 并行）；Step 6 用户确认后提交（不 push）。
