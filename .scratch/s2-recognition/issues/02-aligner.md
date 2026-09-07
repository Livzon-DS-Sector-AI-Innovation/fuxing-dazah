# 02 — 主数据对齐器

**What to build:** `warehouse/agent/pipeline/aligner.py`——`align_receipt(recognized: RecognizedReceipt) -> AlignedReceipt`。主数据源：material_master 表（tblTcAG2qQWGa5R3）全量拉取记录级缓存（TTL 300s，~602 条：物料名称/代码/级别/规格/大类/细分类/单位/生产商/ERP编码）。匹配策略（对 recognized.物料名称 + 生产商/规格辅助）：ERP编码精确 > 名称归一化精确（去空格/全半角/大小写）> 前缀 > difflib ratio≥0.6 模糊。输出：标准化物料名称（Base 单选合法值）/代码/物料大类/细分类/单位建议 + match_confidence（exact/prefix/fuzzy/none）+ 全字段置信度合并。未命中 → aligned.物料名称=原文+match_confidence=none（不阻塞）。draft 状态 created→aligned 落库。

**Blocked by:** 01。

**Status:** done

- [x] 单测：四级匹配各命中样例；归一化（全半角/空格）；未命中 none
- [x] live：测试集 60 条真值物料名 → 对齐命中率 ≥95%（脚本统计）
- [x] aligned 落库（drafts.aligned JSONB 含标准名/代码/置信度）

## Comments

2026-09-07 实现完成（S2 ticket 02）。

**交付物**
- `backend/app/modules/warehouse/agent/pipeline/aligner.py` + `pipeline/__init__.py` re-export——`MaterialMasterEntry`（frozen dataclass：name/code/level/spec/category/sub_category/unit/manufacturer/supplier/erp_code）、`AlignedReceipt`（recognized 原样保留 + aligned dict + match_confidence + match_detail）、`normalize_name`（NFKC 全角→半角 + 去全部空白 + casefold，吸收"硫　酸"/全角逗号括号/大小写差异）、`match_material`（纯函数四级匹配：exact 归一化精确 → prefix 双向（识别名是主数据名前缀=forward 优先，主数据名是识别名前缀=reverse，方向记入 detail 供下游区分置信）→ fuzzy（difflib ratio ≥0.6 取最高，同 ratio 辅助分择优）→ none；多候选并列时生产商(+2)/供应商(+1) tie-break）、`_norm_cell`/`_norm_cell_join`（读回值形态规范化：单选数组/富文本分段 `{"text":...}`/类型包裹，query.py `_cell_list` 同款契约）、`get_master_entries`（模块级缓存 TTL 300s，参照 bitable_schema `_runtime_fields_cache` 模式；`_now`/`_adapter` 模块级可 monkeypatch 注入）、`align_receipt`（未命中 aligned.material_name 保留识别原文）、`align_batch(dataset_dir)`（truth.jsonl 批量评估，返回 {total, exact, prefix, fuzzy, none, hit_rate, misses}，hit_rate=(exact+prefix+0.5×fuzzy)/total）。
- `backend/app/modules/warehouse/agent/repository.py`——新增 `update_agent_draft_aligned(db, draft_id, aligned, status="aligned")`（最小对接：覆盖 aligned JSONB + 迁移 status；草稿不存在/已软删返回 None；票03 状态机接手后可重构）。
- `backend/tests/modules/warehouse/test_live_aligner.py`——单测 14（归一化全半角/空格/大小写；exact/prefix forward/prefix reverse/fuzzy≥0.6/fuzzy<0.6→none/空名→none；exact 与 prefix 多候选生产商 tie-break；align_receipt 集成 aligned 字段/未命中保留原文/空名；TTL 注入时钟复用+过期刷新；align_batch 报表公式）+ live 3（真主数据分页拉取 ≥500 断言；truth.jsonl 60 条批量评估命中率断言 + none/fuzzy 明细打印；truth 首条 RecognizedReceipt→align_receipt 全链路）。

**主数据实测契约（票03/04 相关）**
1. material_master 实拉 **602 条**（2 页 500+102），与 spec ~602 一致；物料名称读回恒为 str；飞书规格/物料细分类为数组；ERP编码为富文本分段 `[{"text":...,"type":"text"}]`；级别/代码/单位换算/生产商/供应商为 str；无独立"单位"字段，unit_suggestion 取自"单位换算"（值形态如 吨/L）。
2. 同名物料存在多条记录（如"硫酸"×3、"乙醇"×2，不同代码/级别/生产商）——exact/prefix 多候选时用识别的生产商/供应商 tie-break；无辅助信息时保持主数据记录序（首个），卡片人工核对兜底。
3. 命中率 100% 的原因：truth.jsonl 的物料名源自入库总账，与主数据同一套物料字典，60 个去重名全部 exact 命中（含超长化学名 4-（5-（3,5-二氯苯基）…空格/全半角差异被 normalize_name 吸收）；prefix/fuzzy/none 路径由单测假数据覆盖。

**验收结果**
- 单测 14 passed；live 3 passed；本票共 17 passed——`test_live_master_fetch`：602 条（有名称 602/有代码 601）；`test_live_align_batch_hit_rate`：**total=60 exact=60 prefix=0 fuzzy=0 none=0 hit_rate=100.00% ≥95% 验收线**（无未命中清单，零调优轮次）
- `update_agent_draft_aligned` 真 DB 验证：created→aligned、aligned JSONB 写读一致、不存在 draft 返回 None，测试记录已删
- 全量回归 **170 passed + 1 skipped**（基线 153 + 本票 17，零破坏）
- ruff/mypy strict：本票文件全绿；既有偏差 1 处——`repository.py:205` `list_actionable_drafts` 函数内 import 排序 I001（HEAD 即存在，非本票引入，未顺手修改）
- platform/safety 零改动；无 DB schema/依赖/权限变更
