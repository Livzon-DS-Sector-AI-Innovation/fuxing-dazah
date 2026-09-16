# 05: 对账 schema + 引擎

**What to build:** 库存台账对账（真实 Bitable 比对）：sync_check_runs（发起人/状态 running|completed|failed/total/四态计数/耗时）与 sync_check_results（run 关联/status: missing_in_feishu|mismatch|missing_local/material·batch 冗余/local_qty/feishu_qty/feishu_record_id/detail JSONB）迁移；reconciliation.py 引擎——本地 stocks 按 (material_code, batch_no) 聚合 ↔ WarehouseBitableAdapter.query_records("material_stock") 分页拉全量，按（物料编码+批次）匹配分四态（match/missing_in_feishu/mismatch/missing_local），仅差异行落 results；飞书 API 异常整体失败（run=failed 不落半截）；POST /reconciliation/run（权限 reconciliation:run，仅手动）、GET /reconciliation/runs 分页、GET /reconciliation/runs/{id}/results?status 分页（权限 reconciliation:read）。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 迁移空库可执行
- [ ] 四态分类测试：monkeypatch adapter 返回构造的飞书行 → 断言分类与落库（match 行不落明细，仅计数）
- [ ] 失败测试：adapter 抛错 → run=failed 且无 results
- [ ] 权限键注册（reconciliation:read/run）
