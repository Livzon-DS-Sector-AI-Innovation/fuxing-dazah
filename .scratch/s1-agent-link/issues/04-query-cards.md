# 04 — 查询结果卡片渲染（第一批·链路）

**What to build:** `warehouse/agent/cards.py`——查询结果 → 飞书交互卡片的渲染器：库存卡片（批号/数量/库位/三态列）、物料卡片、流水汇总卡片、报告清单卡片；占位卡片与结果卡片替换（更新原卡片 message_id）；markdown 表格渲染（飞书 lark_md）。工具返回结构化数据 → 卡片元素。渲染失败降级为纯文本。

**Blocked by:** 03。

**Status:** done (2026-09-04, agent 实现 + 全部验收通过)

- [x] dry-run 测试：query_stock 结果渲染卡片 JSON 断言（字段/行数/空结果态）
- [x] 主接缝联测：问库存 → 收到的就是渲染后的卡片（非纯文本）
- [x] 空结果/超长列表（>10 条）卡片有「共 N 条」摘要与分页提示

## Comments

**实现文件（2026-09-04）**

- `backend/app/modules/warehouse/agent/cards.py`（新增）— Reply → 飞书交互卡片渲染器：
  - `render_reply_card(reply, session=None)` 主入口：Reply.data = `{"tool": 工具名, "result": 结果 dict}`（runner 工具循环填充）命中 4 个查询工具 → 专用卡片；无 data/未知工具/result 非 dict → `render_text_card`（「仓储助手」文本卡片，即票02 行为）；**渲染任何异常捕获降级文本卡片，永不抛错中断回复**。session 参数预留（S2 卡片 patch）
  - `render_stock_card`：表头行「物料｜批号｜剩余数量｜单位｜库位｜三态」+ 序号数据行（剩余数量加粗、三态带 ✅/⚠️/❌ 标记），LLM 文字回复保留卡片顶部（截断 600 字），note 呈现为 ℹ️ 元素；空结果友好态（「未查询到…」不渲染空表格）；total>展示数 → 「……共 N 条，回复「更多」查看」（S1 不做真分页仅提示）
  - `render_material_card`：单条记录块式全字段（代码/级别/生产商/免检/复验期/包装规格/单位换算），多条行式精选列表格
  - `render_movements_card`：按方向分节（📥 入库汇总/📤 出库汇总，聚合数字 top10 + 「共 M 种物料」）+ 方向明细表（通用表格：列=记录键序）
  - `render_report_card`：dead → 「📋 呆料批次清单」orange / unqualified → 「🚫 不合格物料汇总」red，明细行式表格
  - 卡片为旧版 interactive 结构（config/header/elements，与 gateway._build_card 同构），notification.send_card/send_card_to_user 直接可发；单元格统一 `_clean` 清洗（去 markdown 特殊字符/换行、超长截断、空值显示 -，防排版破坏与卡片超 30KB）；LLM 总结文本只截断不清洗（保留 markdown 原貌）
- `backend/app/modules/warehouse/agent/runner.py`（最小改动）— `Reply` 新增可选字段 `data: dict | None = None`（不破坏票02/03 断言 Reply.text 的测试）；工具循环里记录**最后一次成功**（无 error 键）的工具名+原始结果到 reply.data；MAX_TURNS 兜底话术时清空 data（不携带数据卡片）；`_run_tool` 返回值增加 `result` 键
- `backend/app/modules/warehouse/agent/gateway.py`（2 行 diff）— 结果卡片 `_build_reply_card(reply.text)` → `render_reply_card(reply)`（+1 import），删除仅此一处使用的 `_build_reply_card`；占位/图片引导/错误卡片不动

**测试摘要（`tests/modules/warehouse/test_live_cards.py`，23 测试全 PASSED）**

单测（dry-run，20 条）：

1. test_stock_card_structure：表头行精确断言 `物料｜批号｜剩余数量｜单位｜库位｜三态`，数据行含批号 10228-251001/库位/三态标记/加粗数量，LLM 总结在卡片顶部
2. test_stock_card_empty_state：total=0 → 「未查询到」友好态，无表头
3. test_stock_card_truncation_hint：12 条/total=23 → 「共 23 条」+「更多」提示，第 11 条起截断
4. test_stock_card_note_shown：工具 note（拉取上限说明）呈现 ℹ️ 元素
5-6. test_material_card_*：单条块式（10103/活性炭/chemviron/复验期）+ 多条表格（含表头）
7. test_movements_card_summary_and_detail：入库/出库汇总节（乙醇 1100810 Kg）+ 明细批号 10407-250901 + 领用部门
8. test_report_card_title_by_type：dead → 标题含「呆料」（SRM25122907/16#旧原料库一），unqualified → 含「不合格」（电导率/返工）
9-10. test_reply_without_data_falls_back_to_text_card / test_render_text_card_is_gateway_compatible：无 data/未知工具/result=None → 仓储助手文本卡片；render_text_card 产出旧版 interactive 结构
11. test_malformed_data_degrades_without_raising（9 组 parametrize）：data=None/"garbage"/result None/缺 records/records 非列表/元素均非 dict/result 缺失/movements summary 畸形/report records 畸形 → 全部降级文本卡片不抛
12. test_none_field_values_render_tolerantly：字段值 None/total 类型异常 → 容错渲染专用卡片（单元格显示 -）
13. test_oversized_cell_values_are_clamped：5000 字符字段值/总结 → 截断清洗，卡片 JSON < 30KB

live 主接缝（2 条，gateway.handle_im_message 真事件，发送 dry-run 捕获）：

14. test_live_stock_query_renders_dedicated_stock_card：「硫酸还有多少放行的」→ 结果卡片标题 `📦 库存查询`（非「仓储助手」），含表头行与真实批号（预查放行硫酸 total=95，如 10228-251001）
15. test_live_dead_report_renders_report_card：「查一下呆料清单」→ 结果卡片标题 `📋 呆料批次清单`，含真实呆料物料（预查 total=1：无水乙酸钠）

**渲染防御口径（实现决策）**

- 结构畸形（records 缺失/非列表/无 dict 元素、movements summary/records 非列表）→ 渲染器抛 ValueError → render_reply_card 捕获降级文本卡片（不静默渲染坏数据）
- 值畸形（单元格 None/超长、total 类型异常、note 异常）→ 渲染器容错（清洗/截断/显示 -），正常产出专用卡片
- 单元格清洗不含 `#`（库位「24#仓库」「16#旧原料库」是有效字符；换行已清洗且数据行有序号前缀，# 不会落在行首触发标题语法）

**质量**

- warehouse 全量回归 **98 passed**（票03 的 75 + 本票 23），145s；ruff（4 文件）0 告警；mypy strict（agent/ 10 文件）Success
- platform/safety 零改动；config/models/adapter 零改动
- gateway diff（完整）：gateway.py +1 import 行（`from app.modules.warehouse.agent.cards import render_reply_card`）、-5 行（删 `_build_reply_card` 函数）、结果卡片调用 `_build_reply_card(reply.text)` → `render_reply_card(reply)`，其余零改动
