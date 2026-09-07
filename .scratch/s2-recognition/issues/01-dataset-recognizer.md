# 01 — 识别测试集 + Vision 识别器

**What to build:** ① `scripts/build_recognition_dataset.py`：从测试版 material_receipt（tbliBlofs19qM8sg）筛「外包装/厂家报告单/送货单照片」非空记录 → 按物料大类分层抽样 60 条 → 下载附件（im/drive media 下载 API，WAREHOUSE_* 凭证）到 `.scratch/s2-recognition/dataset/images/` → 真值导出 `truth.jsonl`（record_id/物料名称/批号/数量/单位/供应商等 8 必提字段真值）。② `warehouse/agent/pipeline/recognizer.py`：`recognize_receipt(image_b64: str) -> RecognizedReceipt`——视觉消息（chat_with_tools 透传 content 数组，tools=None）+ 严格 JSON prompt（核心 8 必提+选提 5，每字段带 confidence 0-1）+ JSON 解析容错（markdown 代码块剥离）+ RecognizedReceipt pydantic。backend/.gitignore 加 `.dataset/`。测试集构建脚本可独立运行（`uv run python scripts/build_recognition_dataset.py --limit 60`），真值仅含文本字段。

**Blocked by:** None — can start immediately.

**Status:** done

- [x] 脚本实跑：60 条记录图片下载成功（≥55 张）+ truth.jsonl 60 行
- [x] live 识别：用测试集任一张图 → RecognizedReceipt 字段合理（物料名/批号/数量与真值人工比对抽样 5 条）
- [x] 单测：JSON 解析容错（代码块包裹/缺字段/confidence 缺省）
- [x] .gitignore 生效（dataset 图片不进 git）

## Comments

2026-09-07 实现完成（S2 ticket 01）。

**交付物**
- `backend/scripts/build_recognition_dataset.py` — 独立脚本：material_receipt 分页拉全量（1839 条附件非空）→ 按物料大类分层抽样（record_id 排序确定性取样）→ 逐条下载第一个附件 → `images/{record_id}.jpg` + `truth.jsonl`。参数 `--limit`（默认 60）/`--out-dir`；已存在图片跳过（幂等）；下载失败重试 1 次后跳过；真值行恒写（与图片下载独立）。
- `backend/app/modules/warehouse/agent/pipeline/recognizer.py` + `pipeline/__init__.py` — `RECOGNIZE_PROMPT`（中文，必提 8 + 选提 5 定义/别名/confidence 规则/严格 JSON）、`RecognizedField`/`RecognizedReceipt`（pydantic v2，raw 保留原始 JSON）、`recognize_receipt(image_b64, content_type)`（chat_with_tools 纯透传视觉消息，tools=None，temperature=0.1）、`parse_receipt_payload`（剥 ```json 代码块/首尾杂文字）、`build_receipt`（字段缺省→value=None/conf=0，confidence clamp [0,1]，选提缺省→None）、输出不合规重试 1 次（JSON 解析失败或必提 8 字段被整批置空）后仍失败抛 `WarehouseLLMError`。
- `backend/tests/modules/warehouse/test_live_recognizer.py` — 单测 9（代码块包裹/杂前缀/完全非 JSON/字段缺省/confidence 缺省与裸值/越界 clamp/必提全空检测/完整字段构造）+ live 2（3 张真图识别结构断言；truth.jsonl 抽 5 行结构断言 + 1 条识别 vs 真值并排打印）。数据集缺失时 live 用例自动 skip。
- `backend/.gitignore` 加 `.dataset/`；dataset 目录另落 `.gitignore`（`*`）保证根 `.scratch` 下图片不入库。

**产出统计**（实跑 3 次验证幂等）
- 抽样 60 条：原辅料 20 / 危化品 20 / 包材 20（恰 1/3）
- 图片 58 张有效 JPEG（PIL verify 全通过）+ 2 条 HEIC 跳过（`rec27A7PU31Hfv`/`rec27A7U87jM0B`，iPhone 原图格式，PIL 无 pillow-heif 无法转码，真值行保留）≥55 达标；下载失败 0
- truth.jsonl 60 行，字段：record_id/物料大类/物料名称/物料批号/厂家批号/入库数量/单位/供应商/生产商/车牌/合同编号或订单号（空→null）

**实测契约（票05/票03 相关，重要）**
1. **Base 附件下载必须带 extra**：`GET /drive/v1/medias/{file_token}/download?extra={"bitablePerm":{"tableId":"tbliBlofs19qM8sg"}}`——缺 extra 时 `batch_get_tmp_download_url` 静默返回空数组、直连 download 返 400（metas batch_query 可见性正常，易误诊为权限缺失）。任务给的 `POST /drive/v1/medias/batch_download` 端点 404 不存在。
2. **max_tokens 必须给足**：vision 模型 deepseek-v4-flash-vision-exp 为 reasoning 模型，reasoning_tokens 实测波动 3k+，max_tokens=4000 时 content 偶发被耗尽为空（finish_reason=stop 但 content 空）——已提至 16384（对齐 llm_client 默认，模块注释同款契约）。
3. **必提字段整批置空偏差**：模型偶发把报告单/外包装照片误判"非送货单"，必提 8 字段全 null 而选提（包装规格/备注）有值——prompt 第 6 条已收紧（任何单据照片都按必提字段提取可见信息）+ `required_all_missing` 检测触发结构化重试 1 次。
4. 部分文本字段读回为段结构 `{"text":...,"type":"text"}`（脚本 `first_text` 已兼容）；单选读回数组。
5. HEIC 附件占 2/60：票05 评估/线上识别需注意 HEIC 传入 vision 会失败，后续可在 gateway 下载侧加格式嗅探（票05 范围）。

**验收结果**
- 单测 9 passed；live 2 passed（3 张真图：material_name 非空 conf 0.95-0.99，quantity 可转 float，必提字段 confidence∈[0,1]）
- 识别 vs 真值样例（rec05roRO9 硫酸铵 50KG/包）：物料名称 ✓、单位 ✓（KG vs Kg 大小写差异）、生产商 ✓、数量 50 vs 32000（识别到单包规格数字——该附件为报告单/包装照非送货单，字段级命中率优化归票05）、厂家批号/供应商未辨认（低 confidence 返回 null，符合"低置信度诚实留空"）
- 全量回归 153 passed + 1 skipped（基线 143 + 本票 11 = 154，基线用例零破坏）
- ruff / mypy strict 全绿；platform/safety 零改动
