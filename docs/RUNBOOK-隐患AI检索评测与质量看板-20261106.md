# RUNBOOK — 隐患 AI 检索评测与质量看板运营

> 建立：2026-11-06（P1-4 D5）｜ 维护：安全工程中心
> 适用范围：① 隐患 AI 识别链路（`hazard_identification`）的检索/引用质量评测与日常巡检。
> 关联设计：`docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md` §3.3-F；P1-1 spec `.scratch/hazard-retrieval-quality/spec.md`；P1-4 spec `.scratch/hazard-quality-dashboard/spec.md`。

---

## 1. 触发时机

以下任一变更合入后，跑一次完整评测流（§3）并落档（§4）：

| 变更类型 | 例子 | 必跑 |
|---|---|---|
| 检索行为 | 多路开关/参数（`SAFETY_HAZARD_MULTI_QUERY_ENABLED` / `TOP_K` / `CANDIDATES` / `LLM_REWRITE`）、retriever 改动 | ✅ 全流程 |
| prompt / 模型 | 判定依据 prompt、few-shot、模型/温度切换 | ✅ replay 30d + 基线对照 |
| KB 内容 | 补录新法规（`ingest_regulation_doc.py`）、文档归档 | ✅ 快照重评 + 探针 |
| 例行巡检 | 每周/每两周看一次质量趋势 | 看板即可（§5），无需脚本 |

## 2. 口径速查（引用数字前必读）

| 口径 | 定义 | 出处 |
|---|---|---|
| **三套 JSON 合法率不可互比** | ① 审计 `extra.json_valid`（原文直接 `json.loads`，不剥围栏）② replay「现状」（剥围栏后解析）③ replay「修复后」（本地修复链救援后再解析） | `scripts/hazard_ai_quality_replay.py` 头部「口径说明」 |
| **占位率两口径** | 旧 P0-A `placeholder_rate` = 精确占位标记 / **全量 calls**；新 C2 `placeholder_variant_rate` = 占位变体（含精确）/ **有证据调用** | `quality_metrics.analyze_rows` docstring |
| **硬底线** | 引用单元可验证率 ≥95%（P0-C 基线 95.7%）；GT genuine 误拒/误收 = 0 | `quality_metrics.UNIT_VERIFIED_FLOOR` |
| **看板 = replay 同源** | 看板指标由 `quality_metrics` 纯函数计算（与 replay 唯一事实源）；同数据集数字逐字段一致 | `quality_dashboard.build_quality_dashboard` |
| **死信水位** | Redis 失败账本 `safety:hazard:ai:dead_letters`（第 5 次失败进入）；`count=null` 表示账本读取失败、水位未知 | `failure_ledger.list_dead_letters` |

## 3. 评测命令流（cwd = `backend/`）

### 3.1 快照构建（KB/审计口径变化时）

```bash
# 只读：审计 SELECT + /tmp 历史样本 → 评测快照（跑前先报条数）
.venv/bin/python scripts/hazard_retrieval_eval.py --build-snapshot
# 产物：评测快照 jsonl（固化到 .scratch/<feature>/eval/snapshot.jsonl，不依赖 /tmp）
```

### 3.2 双策略 recall 评测（单路基线 vs 多路）

```bash
# 全量（success_gt + failure_57）
.venv/bin/python scripts/hazard_retrieval_eval.py \
  --snapshot .scratch/hazard-retrieval-quality/eval/snapshot.jsonl \
  --out .scratch/<feature>/evidence/retrieval-eval.md \
  --dump .scratch/<feature>/evidence/dump-eval.json

# 只测失败样本复测（KB 补录后）
.venv/bin/python scripts/hazard_retrieval_eval.py \
  --snapshot .scratch/hazard-retrieval-quality/eval/snapshot.jsonl \
  --source failure_57 \
  --out .scratch/<feature>/evidence/retrieval-eval-failure57.md
```

### 3.3 基线对照（P0-C 硬底线）

```bash
.venv/bin/python scripts/hazard_ai_quality_replay.py --days 30 \
  --out .scratch/<feature>/evidence/replay-30d.md
# Markdown 末尾自带「P0-C 基线对照」表（JSON 合法率/单元可验证率/闸门/GT genuine）
```

### 3.4 KB 补录（需用户确认）

```bash
# 演练（只产出预处理文本，不上传）
.venv/bin/python scripts/ingest_regulation_doc.py \
  --file <法规.pdf> --title "《GB 30871-2022 危险化学品企业特殊作业安全规范》" \
  --probe "受限空间作业未办作业票" --probe "动火作业安全管理" --dry-run

# 真实上传（黄色操作：先向用户呈报预处理样例，确认后加 --confirm）
.venv/bin/python scripts/ingest_regulation_doc.py \
  --file <法规.pdf> --title "《GB 30871-2022 危险化学品企业特殊作业安全规范》" \
  --probe "受限空间作业未办作业票" --probe "动火作业安全管理" --confirm
```

补录后顺序：探针验证（脚本内置）→ §3.2 failure_57 复测（improved 重算）→ §3.3 硬底线复测。

## 4. 报告落档惯例

- 位置：`.scratch/<feature>/evidence/`（`.scratch` 不入库，作为本机验收证据）。
- 命名：`retrieval-eval-<scope>.md` / `replay-<window>d.md` / `gb30871-ingest.md`。
- 报告必含：数据集条数、跑的日期、与上一版的对照（改善/回退逐条），达不到目标时写根因不静默（P1-1 先例：improved=0 → 根因 KB 缺法规）。

## 5. 质量看板（日常巡检入口）

- 页面：`/safety/ai-quality`（菜单「隐患治理 · AI 识别质量」），默认 30d 可切 7d。
- 指标：JSON 修复后合法率 / 闸门通过率 / 引用单元可验证率（硬底线 ≥95%）/ 占位变体率 / 多路开启率 / 死信水位 + P0-C 基线对照表 + 按日趋势。
- 数据链：实时聚合（`GET /api/v1/safety/hazard-quality/dashboard`），与 replay 同口径；窗口调用量与 P0-C 基线（505 calls）不同量时基线行显示「窗口不同·不可比」。
- 越线处置：看板只做页面呈现，不推送；发现回退/死信积压 → 按 §3 跑评测定位，必要时关多路开关热回滚（app_config，热生效）。

## 6. GB 30871 现状（2026-11-06，P1-4 T04 调查）

GB 30871 不在 ragplus 任何知识库（文件名疑似 `W020250513627803530871.pdf` 实为《海洋石油专业设备检测检验通则》，尾号巧合）。**补录挂起转遗留**：拿到真 PDF 后按 §3.4 执行闭环。调查全记录与 failure_57 复测固化：`.scratch/hazard-quality-dashboard/evidence/gb30871-investigation.md`。
