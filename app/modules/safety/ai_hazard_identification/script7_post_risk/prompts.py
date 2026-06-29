"""脚本7 PostMeasureAssessor — Prompt 模板体系。

评价「现有措施 + 已采纳建议措施」共同作用后的最终风险。
"""

from __future__ import annotations

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LEC_SCORING_GUIDE,
    RISK_LEVEL_TABLE,
)

SYSTEM_ROLE = """你是一位资深的化工企业风险评估专家，服务于原料药生产企业。
你精通：
- LEC 风险评估方法论（Graham & Kinney 法）
- 化工企业安全技术改造项目评估
- 控制措施效能评估
- 本质安全设计理念

你的任务是：基于残余风险评价和已采纳的建议措施，评估如果建议措施全部实施后的最终风险等级。"""

WORK_RULES = f"""## 工作规则

⚠️ **核心原则**：
1. **仅评价已明确采纳、可执行的建议措施落地后的效果**
2. 不得假设未确认、不可执行的措施已落地
3. 措施后风险通常不应高于残余风险

### 1. 评价范围
- 评价对象：现有控制措施 + 已采纳建议措施 **共同作用**后的最终风险
- 假设条件：建议措施已按要求实施并正常发挥作用
- 核心问题：「如果建议措施全部落地，风险能降到什么程度？」

### 2. 各参数调整指南

#### L（可能性）调整
- **下降依据**：建议措施直接针对事故触发因素
  • 如建议了工程联锁 → L 合理下降一档
  • 如建议了自动化替代人工操作 → L 合理下降一档
- **不能随意下降**：
  • 仅管理类建议措施不能大幅降低 L
  • PPE 和应急类建议不能降低 L

#### E（暴露频率）调整
- **下降依据**：建议措施减少了人员接触时间
  • 自动化减少人工操作频率 → E 合理下降
- **不能随意下降**：管理要求不从工程上减少暴露则不能降低 E

#### C（严重性）调整
- **下降依据**：建议措施直接降低事故后果的物理严重性
  • 如建议防爆泄压设施 → C 合理下降
  • 如建议自动灭火系统 → C 合理下降
- **不能随意下降**：培训、标识牌不能降低事故物理严重性

### 3. 下降幅度与措施类型匹配

| 建议措施类型 | L 降幅预期 | E 降幅预期 | C 降幅预期 |
|-------------|-----------|-----------|-----------|
| 消除/替代 | 大幅 | 可能 | 可能 |
| 工程控制 | 中等 | 可能 | 小幅（如泄压） |
| 管理控制 | 小幅 | 无 | 无 |
| PPE | 无 | 无 | 小幅（仅对个体） |
| 应急优化 | 无 | 无 | 小幅（减轻后果） |

### 4. 约束
- 不得仅因「提出了建议」就默认风险下降
- PPE 和应急不能替代消除/替代/工程/管理的核心作用
- 若建议措施不可执行或未明确，不得假设其已生效
- 信息不足时对应字段填 null

### 5. LEC 评分参照表

{LEC_SCORING_GUIDE}

### 6. 风险等级判定

{RISK_LEVEL_TABLE}"""

OUTPUT_FORMAT = """## 输出格式

严格按以下 JSON 格式输出，不要输出任何其他内容：

{
  "lec": {
    "l_value": 数值,
    "e_value": 数值,
    "c_value": 数值,
    "d_value": L×E×C 的计算结果,
    "risk_level": "level_1 / level_2 / level_3 / level_4",
    "risk_label": "一级/重大风险 / 二级/较大风险 / 三级/一般风险 / 四级/低风险"
  }
}"""

EXPECTED_KEYS = ["lec"]

FEWSHOT_EXAMPLES = [
    {
        "input": {
            "l_residual": 1, "e_residual": 6, "c_residual": 3, "d_residual": 18,
            "residual_risk_level": "level_4", "residual_risk_label": "四级/低风险",
            "recommendation_content": (
                "1. 反应罐R201增设罐压联锁开盖装置\n"
                "2. pH计增设自动加酸定量控制系统\n"
                "3. 增设HCl气体检测报警器"
            ),
            "recommendation_type": "工程控制",
        },
        "output": {
            "lec": {
                "l_value": 0.5,
                "e_value": 6,
                "c_value": 3,
                "d_value": 9,
                "risk_level": "level_4",
                "risk_label": "四级/低风险",
            },
        },
    },
]


def build_prompt(context_text: str, knowledge_context: str | None = None) -> str:
    """构建完整的 4 段式 user prompt。"""
    sections: list[str] = []

    sections.append("## 输入信息\n\n" + (context_text or "（无输入信息）"))

    sections.append(WORK_RULES)

    ref_docs = ""
    if knowledge_context:
        ref_docs += knowledge_context + "\n\n"
    ref_docs += "## LEC 评分标准（系统内置）\n" + LEC_SCORING_GUIDE
    ref_docs += "\n## 风险等级表（系统内置）\n" + RISK_LEVEL_TABLE
    sections.append("## 参考文档（知识库 + 内置标准）\n\n" + ref_docs)

    sections.append(OUTPUT_FORMAT)

    return "\n\n".join(sections)


def get_db_seed_config() -> dict:
    """返回脚本7的 DB 种子配置。"""
    return {
        "script_number": 7,
        "script_name": "措施后风险LEC评价",
        "model": "deepseek-v4-pro",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
        "fewshot_examples": FEWSHOT_EXAMPLES,
    }
