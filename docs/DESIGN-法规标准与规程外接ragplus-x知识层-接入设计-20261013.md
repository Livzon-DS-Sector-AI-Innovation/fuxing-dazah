# 法规标准与规程外接 ragplus-x（知识层接入·切换+退役）设计方案

> 日期：2026-10-13（v2，重写：本机直切+原 RAG 系统退役口径）
> 代码基线：fuxing-dazah @ a231ce70（feature/warehouse-module，Web 3.0 三期已收官）
> 外部依赖：ragplus-x @ 工作区 `~/Agent work/ragplus-x`（企业安全知识底座，RAGFlow v0.27.2 引擎，:8085，本机已服役）
> **v2 口径（2026-10-13 用户拍板）**：dazah 与 ragplus-x 都在本地运行，**直接切换过去，原 dazah RAG 系统退役**——不做长期双路径并存。分两期执行：一期切换（壳换芯，可回退），二期退役（删代码冻表）。
> 体系定位：知识层=ragplus-x，业务/执行层=dazah 安全模块，本方案是两层间第一个正式接口。

---

## 0. 一句话定位

S2「法规标准与规程」（连带 MSDS 知识检索）的解析、分块、向量化、检索全部改由 ragplus-x 承载；dazah 侧**检索入口壳保留、内核替换**（10+ 消费方零改动一次切换），本地 RAG 检索/入库管线在验证后删除、相关表冻结。台账与业务编排（爬虫、Bitable 清单、新旧比对）不动。

## 1. 现状盘点（v2 逐点核实）

### 1.1 检索消费面——收敛度极高，壳替换可行

全部检索消费经三个壳（`knowledge/` 包外零散引用仅 3 处、且都在壳内）：

| 壳 | 消费方 | 引用点 |
|---|---|---|
| `query_service.run_knowledge_chat` | /knowledge/chat API、飞书知识 bot、Agent `knowledge_search` | api/info_query.py、feishu/knowledge_bot_handler.py、business_agent/tools/read_tools.py |
| `retriever.HybridRetriever` | SOP AI 法规参考包 | service/sop_ai/_knowledge.py |
| `retriever.SafetyKnowledgeRetriever` | 6 处 AI 管线"法规依据"检索 | hazard_identification_runner、special_operation_daily_report、hazard、emergency_drill、fire_alarm/analyst、hazard_direct/ai_analysis |

→ **把这两个类 + query_service 的检索内核换成 ragplus 调用，全部消费方一次生效、零改动。**

### 1.2 入库面

- `knowledge_bitable_handler`：Bitable 法规清单事件 → 附件下载 → 切片 → 向量化 → `knowledge_articles`+`regulation_chunks`（本地库现为 0 行；生产库有存量）
- `msds_indexer.sync_msds_document_to_knowledge`：MSDS 台账 → 文章+chunks（被 service/msds.py 调用）
- 本地 chunk/embedding 基础设施同时被 **Agent 长期记忆**依赖（business_agent → memory/store+retriever → `EmbeddingService`）——**embedding_service 不能退役**（见 §4）

### 1.3 ragplus-x 接口面（已实测）

- 检索：`POST /api/v1/retrieval`（高亮+重排，条款级命中）；`GET /api/v1/datasets[/documents]`
- 问答全托管：`POST /v1/chat/completions`（model=`ragplus-kb:{id}`）；MCP `search_kb/kb_chat`
- 入库：文件管理 API（上传→添加至库→批量解析→4s 轮询→失败重试）
- 鉴权：Bearer `ragflow-xxx` Token；本机 `http://localhost:8085`

## 2. 分工边界（终态）

| 职责 | 归属 |
|---|---|
| 法规发现（爬虫）、台账（Bitable 清单/版本/比对/审批） | dazah（不动） |
| 原文解析/分块/向量化/检索/溯源 | **ragplus-x**（唯一知识引擎） |
| 消费面（Agent 工具/问答 bot/S2 页/SOP AI/AI 管线依据） | dazah，检索经壳→ragplus |
| MSDS 知识检索 | ragplus-x `MSDS` 库（msds_indexer 链路退役） |
| Agent 长期记忆向量化 | dazah `embedding_service`（**保留**，ragplus 不暴露嵌入 API） |
| SOP/Drive 文档下载解析（document_loader/parser） | dazah（**保留**，与 RAG 无关） |
| 清单类查询（query_latest_regulations 等） | dazah Bitable 直读（不经知识层） |

## 3. 切换架构：壳保留、芯替换

```
消费方（Agent/bot/页面/SOP AI/6 处 AI 管线）—— 零改动
        │ 接口不变
        ▼
retriever.HybridRetriever / SafetyKnowledgeRetriever / query_service（壳）
        │ 内核二选一：SAFETY_RAGPLUS_SEARCH_ENABLED（app_config，默认关）
        ├─ true  → RagplusClient → POST /api/v1/retrieval（:8085）
        │          归一化 hits[{content, doc_name, 条款/页定位, score}]
        │          超时/重试；不可用→显式报错话术（不静默空结果）
        └─ false → 旧三层管线（一期保留作回退路径；二期删除）
```

- 通道形态：**REST retrieval + dazah 自有 AI 组装**——ai_call_audits 审计、禁语护栏、输出契约全不变；ragplus 只出命中。kb_chat 全托管不用（绕过审计，且问答质量链路已就绪）。
- 引用溯源：hit 归一化带 `法规名+条款定位+片段`，bot 卡片与 AI 管线"依据条款"字段渲染同构。
- 开关只有一个总闸 `SAFETY_RAGPLUS_SEARCH_ENABLED`（本机直切场景，无灰度矩阵）；回退=关开关+重启（一期内有效）。

## 4. 退役边界（二期删除清单，逐件核实）

| 处置 | 文件/组件 | 说明 |
|---|---|---|
| **删除** | retriever.py 三层检索内核、bm25.py、reranker.py、llm_retriever.py、entity_extractor.py、entity_extractor_rule.py、graph_retriever.py、term_dictionary.json | 壳（两类）保留，内核删 |
| **删除** | vector_store.py、chunker.py、chunk_service.py、msds_indexer.py | 法规 chunks 的索引与入库；记忆向量存 DB JSON，不经 vector_store |
| **删除** | graph_builder.py（图谱构建）；graph_service/graph_api/前端 graph 页按 Q3 处置 | 图谱是三层检索的 Layer1，检索职能消失 |
| **删除** | knowledge_bitable_handler 的切片向量化段 | 改为"附件上传 ragplus"（§5） |
| **保留** | embedding_service.py + cosine_similarity | **Agent 长期记忆依赖**（business_agent → memory → EmbeddingService）；ai_config `embedding` 场景随之保留 |
| **保留** | query_service AI 组装、knowledge_card、cache.py、web_search、document_loader/document_parser | 检索走新内核；其余职能不变 |
| **冻结** | 表：regulation_chunks、knowledge_graph_nodes/edges（不删数据）；knowledge_articles 镜像字段写入按清单消费者核对后停 | 冻结说明落档 |
| **下线** | ai_config `rerank` 场景（重排由 ragplus 引擎承担） | `embedding` 场景保留 |

## 5. 入库与同步管道（dazah → ragplus-x）

1. **存量全量入库**（一期）：`scripts/tmp/ragplus_bulk_ingest.py`——Bitable 法规清单全量拉取→下载附件 PDF→ragplus 文件管理 API 上传→加入`安全法规标准`库→批量解析→轮询就绪；失败清单落档人工重传。幂等映射表 `ragplus_doc_map`（平台 DB：domain/biz_key[法规编号]↔dataset_id/document_id/version/status）。
2. **增量**（一期）：knowledge_bitable_handler 重写——事件后**只做**：镜像字段写入（若仍有清单消费者，核对后可停）+ 附件上传 ragplus + 映射登记。**修订/替代**（爬虫删旧写新）→ ragplus 删旧文档+传新文档（版本对齐，检索无旧版残留）；**废止**→移入`已废止`归档库（溯源可回放）。
3. **MSDS**（一期一并做）：msds.py 摘除 `sync_msds_document_to_knowledge` 调用；存量 MSDS 文档批量入 ragplus `MSDS` 库；S9 的 MSDS 问答自此走 ragplus。
4. **操规**（二期）：SOP 源文档（飞书 Drive）存量入`操作规程`库；SOP AI 生成新版同步上传。

## 6. 验收口径

- **切换验收（一期出口）**：开关打开后，Agent knowledge_search、知识 bot、S2 页语义检索、SOP AI 参考包、6 处 AI 管线依据检索**逐项真机过一遍**（本地 ragplus 已服役，法规库有实测数据）；检索返回必带法规名+条款定位；ragplus 停机时消费方得到显式报错而非空结果；关开关回退旧链路行为一致（本地空索引属预期）。
- **退役验收（二期出口）**：删除清单内代码全删、壳接口签名不变、全部消费方回归绿（pytest 基线 4 败既有 + 前端 vitest 全绿）；表冻结说明落档；`rerank` 场景下线；Agent 记忆功能回归（embedding_service 保留验证）。
- **质量抽检**：10 个真实业务问题（隐患定级依据/特殊作业条款/MSDS 应急处置等），ragplus 命中与生产旧链路已知答案对比，条款级命中率与耗时（P95<2s）落档。

## 7. 分期

| 期 | 内容 | 出口 |
|---|---|---|
| **一期：切换** | RagplusClient + 三壳内核替换（开关默认关）+ 存量法规/MSDS 入库 + handler 增量重写 + 本机开关打开全量切换 | §6 切换验收全过 |
| **二期：退役** | 删除清单执行 + 表冻结 + rerank 场景下线 + 操规库入库 + graph 处置（Q3） | §6 退役验收全过 |

## 8. 决策点

| # | 决策 | 建议 |
|---|---|---|
| Q1 | 知识图谱（graph_builder/表/前端 graph 页）处置 | 随检索层退役——graph 构建停、表冻结、前端 graph 页退役（子页不在主菜单，成本低）；若要保留图谱浏览则只留只读页，构建链路仍删 |
| Q2 | 生产切换节奏 | 本机验证一期后，Windows 生产机执行同样两步；生产 regulation_chunks 有存量、入库脚本按映射表幂等（已入跳过）；ragplus-x 需先在生产内网部署（Q2 变成生产前置任务，不再阻塞本机） |
| Q3 | knowledge_articles 镜像字段是否停写 | 一期盘点清单 API/页面的真实消费者后定：清单查询已直读则停写、表冻结 |
| Q4 | ragplus-x 后续高可用 | 单机 Docker 属演示拓扑；知识层成为唯一检索源后，其可用性=全部 AI 管线的可用性，建议二期后评估（备份/重启策略即可满足当前规模，暂不引入集群） |
