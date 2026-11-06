# AI 隐患识别插件 (AI Hazard Identification Plugin)

基于《AI隐患识别工作流设计方案》，将多模态 AI 分析能力封装为**独立、可测试、可复现**的隐患识别引擎。

## 架构概览

```
ai_hazard_identification/
├── __init__.py      # 公开 API，统一导出
├── plugin.py        # 核心引擎：四阶段识别流程
├── prompts.py       # Prompt 模板 + 规则体系 + DB 种子配置
├── rules.py         # 规则引擎：输出验证 + 自动修正
├── schemas.py       # Pydantic v2 数据模型（输入/输出/配置）
├── README.md        # 本文档
└── tests/
    ├── test_plugin.py   # 44 个测试用例
    └── fixtures/        # 测试图片（待添加）
```

## 快速开始

### 独立测试（不依赖数据库/飞书）

```python
from app.modules.safety.ai_hazard_identification import (
    AIHazardIdentifier,
    HazardIdentificationInput,
)

# 创建 AI 服务（任意 OpenAI-compatible 接口）
from app.platform.integrations.ai.client import AIService
ai = AIService(
    api_key="sk-xxx",
    base_url="https://api.deepseek.com",
    model="deepseek-flash",
)

# 实例化插件
plugin = AIHazardIdentifier(ai)

# 执行识别
result = await plugin.identify(HazardIdentificationInput(
    hazard_no="HZ-2026-0001",
    description="防爆电箱备用引入口未封堵，箱内积尘严重",
    department="生产部",
    location="合成车间一楼",
    defect_photos=["https://..."],  # 可选
))

print(result.key_defect)          # 隐患描述（AI）
print(result.hazard_type)         # unsafe_condition
print(result.hazard_category)     # instrument_electrical
print(result.hazard_level)        # major
print(result.rectification_suggestion.immediate)  # 立即措施
print(result.major_hazard_basis)  # 通用判定依据（引用本轮知识库条文；无对应条文时为空字符串）
```

### 运行测试

```bash
uv run pytest app/modules/safety/ai_hazard_identification/tests/ -v
```

## 六大 AI 输出字段

| # | 字段 | 类型 | 示例 |
|---|------|------|------|
| 1 | `key_defect` | 文本 (≤200字) | "防爆电箱备用引入口未使用防爆堵头封堵，箱内积尘严重..." |
| 2 | `hazard_type` | 枚举 (4值) | `unsafe_condition` (物的不安全状态) |
| 3 | `hazard_category` | 枚举 (13值) | `instrument_electrical` (仪表+电气) |
| 4 | `hazard_level` | 枚举 (3值) | `major` (重大隐患) |
| 5 | `rectification_suggestion` | 对象 (3层) | `{immediate, short_term, long_term}` |
| 6 | `major_hazard_basis` | 文本 | 通用判定依据（非重大专属）：引用支撑本次结论的法规条款；major 级别应引用《重大隐患判定标准》对应条款，非重大不得强行引用；无对应条文时为空字符串 |

### 判定依据（`major_hazard_basis`）口径

`major_hazard_basis` 是**通用判定依据**，承载支撑本次识别结论（描述/分类/级别）的法规/标准条款，**不是「重大隐患专属依据」**，general / serious / major 三个级别都要填写：

- **级别一致性**：`hazard_level=major` 时应引用《重大隐患判定标准（试行）》对应条款；非 major 引用支撑该级别判定的标准条款即可，不得为凑条款强行引用重大标准；隐患级别仍以「①停产整改判断」为最高权威。
- **来源约束**：引用必须逐字来自本轮注入的「法规知识库」检索片段，不得凭训练记忆引用知识库中未出现的法规名/条号，不得概括/改写/编造。
- **格式**：`《法规/标准名称》第X条：'条文原文'`（标准号写法如 `GB 30871-2022 第5.1条：'……'` 可容忍）。
- **无对应条文**：知识库确无对应条文时输出**空字符串**，不写占位文案进表；由质量闸门按 `empty_basis` 拦截转人工（插件 schema 已放宽为 `min_length=0`）。

### 枚举值速查

**隐患分类 (hazard_type)**:
| 值 | 含义 |
|----|------|
| `unsafe_action` | 人的不安全行为 |
| `unsafe_condition` | 物的不安全状态 |
| `environmental` | 环境的不安全因素 |
| `management_defect` | 管理的缺陷 |

**隐患级别 (hazard_level)**:
| 值 | 含义 |
|----|------|
| `general` | 一般隐患 |
| `serious` | 较大隐患 |
| `major` | 重大隐患 |

**隐患类别 (hazard_category)** — 13 个值：`equipment`, `hazardous_storage`, `emergency_mgmt`, `instrument_electrical`, `lightning_antistatic`, `occupational_health`, `violation_operation`, `six_s`, `label_signage`, `process_mgmt`, `contractor_defect`, `documentation`, `special_operation`

## 可复现性设计

插件通过以下 4 个机制保证输出**一致、可复现**：

1. **低温参数 (temperature=0.05)**：最大化输出确定性
2. **Few-shot 示例**：4 个标准案例覆盖全部 4 种隐患分类，指导 AI 输出风格统一
3. **Expected Keys 校验**：AI 返回后立即校验 6 个必填字段是否完整
4. **规则引擎后处理**：10+ 条验证规则 + 自动修正，确保枚举值合法、格式规范、引用真实

## 配置方式

### 方式一：DB 动态配置（推荐）

通过前端 AI 工作流配置界面管理 Prompt，或调用 `get_db_seed_config()` 获取初始配置写入 `ai_workflow_configs` 表：

```python
from app.modules.safety.ai_hazard_identification import get_db_seed_config

config = get_db_seed_config()
# 写入 DB:
await repo.create_ai_workflow_config(config)
```

配置写入后，插件自动从 DB 读取（`module_code="hazard"`）。

### 方式二：硬编码 Fallback

未配置 DB 时插件使用 `prompts.py` 中的硬编码模板，保证离线可用。

### 运行时配置

```python
from app.modules.safety.ai_hazard_identification import PluginConfig

config = PluginConfig(
    temperature=0.05,       # 低温度 = 高复现
    strict_mode=True,        # 验证失败时抛异常
    enable_vision=True,      # 启用多模态
    enable_reasoning=False,  # 不输出推理过程（省 token）
)
plugin = AIHazardIdentifier(ai, config=config)
```

## 质量保障

### 规则引擎验证

RuleEngine 在 AI 输出后自动执行：

- ✅ 枚举值合法性（4+13+3）
- ✅ 描述长度 (key_defect ≥10, basis ≥20)
- ✅ 整改建议三层结构 + 泛泛表述检测
- ✅ 判定依据法规引用检测
- ⚠️  分类-类别逻辑一致性
- ⚠️  输入-输出关键词重叠率

### 自动修正

`auto_correct()` 自动处理：
- 去除首尾空白
- 填充空的整改建议层

## 更新与扩展

### 修改 Prompt 模板

编辑 `prompts.py` 中的 `WORK_RULES` 或 `OUTPUT_FORMAT`，然后重新运行测试确认。

### 新增隐患分类/类别

1. 更新 `schemas.py` 中的 Enum
2. 更新 `prompts.py` 中的规则描述
3. 更新 `rules.py` 中的 `TYPE_CATEGORY_COMPATIBILITY`
4. 运行 `pytest` 确认所有测试通过

### 替换 AI 模型

```python
ai = AIService(
    api_key="sk-xxx",
    base_url="https://api.openai.com/v1",
    model="gpt-4o",  # 换模型
)
plugin = AIHazardIdentifier(ai)
```

### 添加新测试用例

在 `tests/fixtures/` 中放置测试图片，在 `test_plugin.py` 中添加对应测试。

## 集成到平台

见父级 `service/safety.py` 中的 `_generate_hazard_ai_output()` — 该方法是此插件的 DB-aware wrapper。

平台集成调用链：
```
POST /api/v1/safety/hazards/{id}/ai/run/1
  → SafetyService.run_hazard_ai_script()
    → AIHazardIdentifier.identify()
      → RuleEngine.validate()
      → auto_correct()
```

## 文件清单

| 文件 | 行数 | 用途 |
|------|------|------|
| `schemas.py` | 197 | 输入/输出 Pydantic 模型 |
| `prompts.py` | 443 | Prompt 模板 + 规则文本 + DB 种子 |
| `rules.py` | 405 | 规则引擎 + 自动修正 |
| `plugin.py` | 520 | 核心引擎（四阶段流程） |
| `citations.py` | 135 | 引用/占位判定纯函数（唯一事实源） |
| `citation_evidence.py` | 565 | 引用来源可验证纯函数（C2，零 IO） |
| `tests/test_plugin.py` | 615 | 44 个测试（6 组） |
