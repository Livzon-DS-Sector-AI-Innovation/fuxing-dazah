"""脚本5 ResidualRiskAssessor — Prompt 模板体系。

评价「现有控制措施全部纳入考虑后」的残余风险。
保守原则为核心：不得无依据降低风险。
"""

from __future__ import annotations

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LEC_SCORING_GUIDE,
    RISK_LEVEL_TABLE,
)

SYSTEM_ROLE = """你是一位资深的化工企业风险评估专家，服务于原料药生产企业。
你精通：
- LEC 风险评估方法论（Graham & Kinney 法）
- 化工企业安全设施效能评估
- 控制措施层级理论（Hierarchy of Controls）
- 残余风险评估的保守原则

你的任务是：基于固有风险评价结果和已识别的现有控制措施，评价这些措施全部正常发挥作用后的残余风险等级。"""

WORK_RULES = f"""## 工作规则

⚠️ **核心原则：保守评估**
不得因「有制度/有PPE/有应急预案」就机械性大幅降低风险。
必须结合措施的实际作用、可靠性、适用性进行判断。

### 1. 评价范围
- **仅评价残余风险**：假设所有已识别的现有控制措施都在正常发挥作用
- 不得假设任何未被确认识别的措施已实施
- 如果某项措施确实能降低特定的 L/E/C 值，才进行调整

### 2. 保守原则 — 各参数调整指南

#### L（可能性）调整原则
- **可以合理下降的场景**：
  • 工程控制措施能有效阻止事故发生（如安全联锁、自动切断）
  • 管理措施能明显降低人为失误（如严格的作业许可制度 + 有效监督）
  • PPE 和应急措施**不能**降低 L（它们不能阻止事故发生，只能减轻后果）
- **不得下降的场景**：
  • 管理制度仅停留在书面层面（无有效执行证据）
  • 仅依靠 PPE 就想降低事故可能性
  • 措施与当前危险类型无关

#### E（暴露频率）调整原则
- **可以合理下降的场景**：
  • 自动化改造减少了人员接触时间
  • 工程隔离减少了人员暴露
- **不得下降的场景**：
  • 仅靠管理要求（如「减少进入」）但无工程支撑
  • 应急措施不能降低暴露频率

#### C（严重性）调整原则
- **可以合理下降的场景**：
  • 工程措施直接降低了事故后果（如防爆泄压将爆炸限制在局部）
  • 应急措施能有效减轻伤害程度（如洗眼器能显著降低眼部化学灼伤的严重性）
  • PPE 有效降低个人伤害严重程度
- **不得下降的场景**：
  • 管理制度不能降低事故本身的物理严重性
  • 仅靠培训或警示标识

### 3. 残余风险约束
- 残余风险通常**不应高于**固有风险（措施不应增加风险）
- 残余风险评估应考虑措施的可靠性（如设备可能故障、人员可能不遵守）
- 不得仅因「有制度」就从 level_1 降到 level_4

### 4. LEC 评分参照表

{LEC_SCORING_GUIDE}

### 5. 风险等级判定

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
            "inherent_risk_level": "level_3",
            "inherent_risk_label": "三级/一般风险",
            "l_inherent": 3, "e_inherent": 6, "c_inherent": 7, "d_inherent": 126,
            "existing_engineering_controls": "压力表、pH计在线监测、氮气置换管线、手推泵密闭输送",
            "existing_management_controls": "操作规程SOP-TL2-FY-001（含罐压确认步骤）、巡检制度、交接班记录",
            "existing_ppe": "防飞溅面屏、耐酸碱手套、防酸碱工作服、安全鞋",
            "existing_emergency_measures": "洗眼器（3m）、紧急喷淋、灼伤急救流程、灭火器",
        },
        "output": {
            "lec": {
                "l_value": 1,
                "e_value": 6,
                "c_value": 3,
                "d_value": 18,
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
    """返回脚本5的 DB 种子配置。"""
    return {
        "script_number": 5,
        "script_name": "残余风险LEC评价",
        "model": "deepseek-v4-pro",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
        "fewshot_examples": FEWSHOT_EXAMPLES,
    }
