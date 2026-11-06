# 五金库上线部署检查清单（2026-11-06，随 A3 交付）

> 适用：把五金库模块从本地 dev 部署到生产服务器。逐项打勾，全部 ✅ 才可宣布上线。
> 生产服务器无本地文件与本地数据（CLAUDE.md 口径），生产库与开发库数据不同。

## 0. 前置确认

- [ ] 代码版本：`feature/warehouse-module` 最新（含 516b92b0 冒烟修复与品类词护栏）
- [ ] 生产服务器 Python 3.12 + backend `.venv` 依赖就绪
- [ ] 前端构建：`pnpm build`（/warehouse/hardware 七页 + 菜单「五金库」组）
- [ ] 生产 PostgreSQL 可达，目标库 schema `warehouse` 存在

## 1. 数据库迁移（按序执行，共 12 个）

```
b2f6d8e0a4c1  一期 7 表          c4a8e2f6b0d3  场景种子(receipt)
d8e2f6a4b8c1  二期 M4 三表      e9f4a8c2d6e5  二期 M5 两表
f2a8c4e6d9b3  场景种子(plan)    g4c6e8f0a2b5  superagent 源种子(enabled=false)
a7b3c9d1e2f4  三期 M7 报废+初筛 b8c4d6e2f7a3  M8 对账列
c9d5e7f3a8b6  M9 auto 列        d1e2f4a6b8c5  运行键种子
```

执行：`alembic upgrade head`；校验：`alembic current` 指向 d1e2f4a6b8c5 且 12 表齐全（`hardware_*`）。

## 2. `.env` 生产键（五金库相关全表）

| 键 | 生产建议值 | 说明 |
|---|---|---|
| `HARDWARE_APPROVAL_CHANNEL` / `HARDWARE_APPROVAL_CODE` | `manual` / 空 | 领料审批：定义到位后切 `feishu`+code（业务部门在办） |
| `HARDWARE_APPROVAL_USER_KEY` | `user_id` | 默认即可 |
| `HARDWARE_SCRAP_APPROVAL_CHANNEL` / `HARDWARE_SCRAP_APPROVAL_CODE` | `manual` / 空 | 报废审批同上 |
| `HARDWARE_OCR_AUTO_DIRECT_ENABLED` | `false` | **M9 默认关**（≥1 个月置信数据后评估） |
| `HARDWARE_OCR_AUTO_DIRECT_MIN_CONFIDENCE` | `0.9` | 开启时的阈值 |
| `WAREHOUSE_TEST_CHAT_ID` | 测试群 chat_id | 兜底目标；**生产上线初期建议先指测试群** |
| `WAREHOUSE_HARDWARE_ALERT_CHAT_ID` | 空或催办群 | 催办卡专用群（空=回退测试群） |
| `SUPERAGENT_ENABLED` | `true`（启用事件源时） | 底座总开关；不启用事件源可 `false` |
| ERP 列映射 `hardware_erp_column_mapping` | 不配（默认） | 样例文件到位后管理端运行参数页配置 |

## 3. 数据初始化

- [ ] **492 项清单导入**：上传 `docs/assets/hardware_store/五金库物资清单-20261103.xlsx`（管理端导入或 `python -m app.modules.warehouse.hardware.importer <file>`）；code 留空属正常
- [ ] **库位建档**：按实际库房建 `hardware_locations`（dev 参考样板 4 行：平台下/平台上货架分区）
- [ ] **⚠️ 推送任务 DB 播种（防真发卡）**：真发卡事故教训——`push_tasks` 无 DB 行=注册表默认 enabled。生产开服前，把五金推送任务（hardware_direct_pickup / hardware_stale_list / env_remind / digest 族等，见 push_center 注册表）**逐一插 DB 行并指向正确群**（初期建议 enabled=false 或指测试群），确认无误再逐个开
- [ ] **SUPERAGENT 源**：`agent_sources` 里 `warehouse.hardware_alert_scan` 迁移播种为 enabled=false——按需启用（启用步骤见 §6 冒烟③）

## 4. 权限绑定（`warehouse:hardware:*` → 人员）

权限码已注册（`warehouse/permissions.py`）。绑定模式沿用平台身份表，最小集合：

| 角色 | 权限码 | 谁（业务部门给名单） |
|---|---|---|
| 仓管员 | `hardware:` 全组（inbound/requisition:issue/stocktake/material:manage/scrap…） | 待名单 |
| 车间办事员 | `stock:read` + `requisition:create` | 待名单 |
| 部门主管 | + `requisition:approve` | 待名单 |
| 财务 | `stock:read` + `stocktake:read` + `reports:read` | 待名单 |

## 5. 历史数据口径（已定案，勿变更）

- **零库存纯增量**（P4）：上线即空账，库存从入库单累计；存量实物靠首次全面盘点盘盈入账（盘点台 take_type=calibration）
- 历史纸档/ERP 存量**不回填**（对齐安全模块口径）

## 6. 上线冒烟（演练脚本已随库，生产可直接复用）

```bash
# ① 匹配真库抽查（应 8/9 命中 + 1 护栏拒配）
./.venv/bin/python -m scripts.hardware_golive_exercise match
# ② 领料全链 3 单 + 超卖闸（五行库存数字全对即过）；验完清理
./.venv/bin/python -m scripts.hardware_golive_exercise requisition
./.venv/bin/python -m scripts.hardware_golive_exercise cleanup
# ③ SUPERAGENT 启用链（可选，需 .env SUPERAGENT_ENABLED=true + 源置 enabled + 重启）
#    验证：五类事件卡到指定群、同事件二次触发不重复、digest 数字与流水一致
# ④ 真实送货单 OCR 一张（`scripts.hardware_ocr_smoke.py`）+ 入库台 UI 确认一单
# ⑤ 领用中心真人发起 1 单 → 主管确认 → 发料台发料 → 库存页数字核对
```

## 7. 回滚口径

- 代码：单分支直推，回滚=回退部署版本（迁移 downgrade 均已实现，但**生产有数据后慎用 downgrade**——优先只回代码不动表）
- 开关熔断：`SUPERAGENT_ENABLED=false`（事件源全停）/ `HARDWARE_OCR_AUTO_DIRECT_ENABLED=false`（自动入账停）/ 推送任务逐行 DB 关
