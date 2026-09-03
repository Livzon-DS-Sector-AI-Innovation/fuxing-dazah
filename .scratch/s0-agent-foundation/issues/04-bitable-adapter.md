# 04 — warehouse bitable 适配器（写契约 + 字段映射）

**What to build:** 两个文件（均在 `app/modules/warehouse/`）：
① `bitable_schema.py`——核心表元数据常量：表标识（base_token 键名+table_id）、字段清单（名称/类型码/单选选项集）、写入目标表映射。数据源 `base_scan/` 摸底结果（物料系统测试版 LmuBb3 的 table_id 与工作版不同，以测试版为准）。提供选项集校验函数。
② `bitable_adapter.py`——warehouse 凭证下的读写封装：`query_records(table_key, filter_json?, field_names?, limit?)` / `get_record` / `create_record(table_key, fields)` / `delete_record(record_id)` / `list_table_fields`（带 TTL 缓存）。底层调 `platform/integrations/feishu/bitable.py`（传 WAREHOUSE_FEISHU_APP_ID/SECRET，platform 文件零改动）。写前契约校验：字段名必须在该表 schema 内、单选值必须字符串且在选项集内、lookup/formula/created_by 等只读类型拒写；错误码分类抛出（91403 权限 / 1254045 字段名 / 1254062 选项值 / 1254291 并发）。

**Blocked by:** 01 — WAREHOUSE_FEISHU_* 配置键。

**Status:** done

- [x] live 测试（真实测试版 Base）：对成品销售-测试版 10月汇总表（tbl2ANgtopqvgvbr）create→get→delete 往返成功（写后必清理）
- [x] live 测试：单选字符串写入成功（品名=硫酸黏菌素）；非法选项值被校验器拦截（未发请求）；只读字段被拒写
- [x] live 测试：query_records 带过滤查询库存明细类表返回记录
- [x] 错误分类：构造非法字段名请求 → 抛 1254045 分类异常（真实 Base 验证）
- [x] 字段映射常量覆盖：物料入库总账/出库总账/库存明细、GMP 入库/出库、成品出库台账、销售明细（7 张核心表）

## Comments

- 2026-09-03 实现完成，连续 3 轮全量 6/6 live PASSED。
- 查询实现选型：`query_records` 走 POST `records/search`（结构化 filter_json）；实测该接口必须携带 JSON body（无条件时传空对象，缺 body 返 9499）。filter 条件 value 须为数组。
- 错误码保留方式：platform 的 FeishuAPIError 只把 code 放在 message 文本里（`...code=<n> msg=...`），adapter 用正则解析保留到 `WarehouseBitableError.code`（platform 文件零改动）。
- `refresh_table_fields` 解析需从 `property.options` 取单选选项（飞书原生结构），兼容顶层 `options`（base_scan 快照形态）；TTL 300s 运行时缓存优先于静态快照参与写前校验。
- **偏差 1**（readonly 测试字段）：7 张表快照中无 created_time(1001) 类型字段，只读拒写改用 gmp_outbound「创建人」(created_user 1003) 与 material_receipt「应出报日期..」(formula 20) 验证，同属只读类型集合。
- **偏差 2**（1254045 测试字段集）：任务原样 fields 伴写单选「物料名称」="硫酸"，但测试版该字段有重复选项（V1.0-5 已知坑，任何值均 1254062），飞书"先查字段名还是先查选项值"是非确定行为（实测两种顺序都出现，曾致断言间歇失败）——改为只写不存在字段，1254045 确定。物料名称写入走 S2 降级方案。
- **偏差 3**（单选读取形态）：设计文档说单选读取返回数组，实测 sales_detail「品名」回读为纯字符串；适配器读取原样透传（不转换），断言兼容两种形态。
- 常量快照的已知局限：base_scan 抓取的物料入库总账「物料名称」仅含 50 个选项（DIGEST 记载 391，疑似抓取时飞书截断），物料入库总账测试版坐标为 LmuBb3/tbliBlofs19qM8sg（字段数据取自工作版 BG4Eb 同构 JSON）；运行时经 `refresh_table_fields` 拉全量可补，未收录字段名校验时放行不误杀。
- gmp_outbound「领用品种」「领用部门」在测试版 Base 选项集为空（快照记为空 tuple，校验放行交 Base 侧）。
