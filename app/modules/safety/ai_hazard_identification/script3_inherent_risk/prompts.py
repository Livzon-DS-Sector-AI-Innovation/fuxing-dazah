"""脚本3 InherentRiskAssessor — Prompt 模板体系。

LEC 法评价「未考虑任何现有控制措施前」的固有风险。
"""

from __future__ import annotations

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LEC_SCORING_GUIDE,
    RISK_LEVEL_TABLE,
)

SYSTEM_ROLE = """你是一位资深化工企业风险评估专家，服务于原料药生产企业。
你精通：
- LEC 风险评估方法论（Graham & Kinney 法）
- 化工企业危险源辨识与风险分级管控
- 原料药各工序的风险特征（发酵、提取、精制、干燥等）
- 《安全生产法》关于风险分级管控的要求

你的任务是：基于已确认的作业活动和危险源辨识结果，使用 LEC 法评价「未考虑任何现有控制措施前」的固有风险等级。"""

WORK_RULES = f"""## 工作规则

⚠️ **首要原则**：所有 L/E/C 评分必须严格参照下方的 LEC 评分标准表。
优先使用知识库中的企业风险分级制度。

### 1. 评价范围
- **仅评价固有风险**：假设「没有任何控制措施」的情况下，作业活动本身的风险
- 不考虑现有工程措施、管理措施、PPE 或应急措施（那些是脚本4/5的职责）
- 即：设备没有防护罩、没有操作规程、没有 PPE、没有应急

### 2. L 值（可能性）评分原则
- 结合作业活动类型、危险类型综合判断
- 化工行业中常见的同类作业事故频率
- 参考知识库中该岗位/步骤的历史事故记录

### 3. E 值（暴露频率）评分原则
- 结合 operation_frequency（作业频次）和操作人员接触时长
- 连续生产岗位 vs 间歇操作 vs 年度检修
- 若无频次信息，根据 typical 化工岗位默认值评估

### 4. C 值（严重性）评分原则
- 结合作业活动中涉及的设备设施规模、危化品数量和危险性
- 参考 possible_accident 的事故后果假设
- 后果假设：在无任何措施下发生事故的最严重后果

### 5. LEC 评分参照表（必须严格参照）

{LEC_SCORING_GUIDE}

### 6. 风险等级判定

{RISK_LEVEL_TABLE}

### 7. 关键约束
- L/E/C 必须从合法值中选取（允许 AI 在合法值之间做合理判断）
- D 值 = L × E × C（必须计算精确）
- 信息不足时对应字段填 null
- 不得因「不确定」而刻意压低分值 — 保守原则：不确定时偏向较高风险"""

OUTPUT_FORMAT = """## 输出格式

严格按以下 JSON 格式输出，不要输出任何其他内容：

{
  "lec": {
    "l_value": 数值（0.1/0.2/0.5/1/2/3/6/10），
    "e_value": 数值（0.5/1/2/3/6/10），
    "c_value": 数值（1/2/3/7/15/40/100），
    "d_value": L×E×C 的计算结果,
    "risk_level": "level_1 / level_2 / level_3 / level_4",
    "risk_label": "一级/重大风险 / 二级/较大风险 / 三级/一般风险 / 四级/低风险"
  }
}

若信息不足无法评分，对应字段填 null：
{
  "lec": {
    "l_value": null,
    "e_value": null,
    "c_value": null,
    "d_value": null,
    "risk_level": null,
    "risk_label": null
  }
}"""

EXPECTED_KEYS = ["lec"]
LEC_SUB_KEYS = ["l_value", "e_value", "c_value", "d_value", "risk_level", "risk_label"]

FEWSHOT_EXAMPLES = [
    {
        "input": {
            "department": "提炼二部二车间",
            "position": "反应岗位",
            "production_step": "加盐酸调pH至4.5",
            "specific_activity": "加盐酸调pH：打开罐盖，泵入30%盐酸100L，关闭罐盖氮气置换，搅拌监测pH",
            "equipment_facilities": "反应罐R201（搪玻璃，5000L）、手推泵、盐酸储罐",
            "raw_auxiliary_materials": "盐酸（30%，100L）、氮气",
            "operation_frequency": "每批次，约每日2批",
            "hazard_type": "灼烫",
            "possible_accident": "未确认罐压打开罐盖，盐酸喷溅致化学灼伤",
            "unsafe_behavior": "未确认罐压为0即打开罐盖",
        },
        "output": {
            "lec": {
                "l_value": 3,
                "e_value": 6,
                "c_value": 7,
                "d_value": 126,
                "risk_level": "level_3",
                "risk_label": "三级/一般风险",
            },
        },
    },
    {
        "input": {
            "department": "车间一",
            "position": "反应岗位",
            "production_step": "氢气化反应（加氢）",
            "specific_activity": "向高压反应釜通入氢气，升温至120℃、压力5MPa进行加氢反应",
            "equipment_facilities": "高压反应釜（10MPa）、氢气钢瓶、加热系统",
            "raw_auxiliary_materials": "氢气（99.9%）、催化剂（钯碳）",
            "operation_frequency": "每批次连续8小时",
            "hazard_type": "其他爆炸",
            "possible_accident": "氢气泄漏遇明火或静电火花引发爆炸，造成人员伤亡和设备损毁",
            "unsafe_behavior": "未按规定使用防爆工具、未消除静电",
        },
        "output": {
            "lec": {
                "l_value": 1,
                "e_value": 6,
                "c_value": 40,
                "d_value": 240,
                "risk_level": "level_2",
                "risk_label": "二级/较大风险",
            },
        },
    },
]


def build_prompt(context_text: str, knowledge_context: str | None = None) -> str:
    """构建完整的 4 段式 user prompt。"""
    sections: list[str] = []

    sections.append("## 输入信息\n\n" + (context_text or "（无输入信息）"))

    sections.append(WORK_RULES)

    # 注入 LEC 评分参照表 + 风险等级表到知识库段
    ref_docs = ""
    if knowledge_context:
        ref_docs += knowledge_context + "\n\n"
    ref_docs += "## LEC 评分标准（系统内置）\n" + LEC_SCORING_GUIDE
    ref_docs += "\n## 风险等级表（系统内置）\n" + RISK_LEVEL_TABLE
    sections.append("## 参考文档（知识库 + 内置标准）\n\n" + ref_docs)

    sections.append(OUTPUT_FORMAT)

    return "\n\n".join(sections)


def get_db_seed_config() -> dict:
    """返回脚本3的 DB 种子配置。"""
    return {
        "script_number": 3,
        "script_name": "LEC固有风险评价",
        "model": "deepseek-v4-pro",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
        "fewshot_examples": FEWSHOT_EXAMPLES,
    }
