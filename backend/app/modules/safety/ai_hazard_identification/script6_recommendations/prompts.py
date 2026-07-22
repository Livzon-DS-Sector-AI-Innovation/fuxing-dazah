"""脚本6 RecommendationGenerator — Prompt 模板体系。

根据残余风险等级，按控制层级原则（Hierarchy of Controls）提出建议措施。
"""

from __future__ import annotations

SYSTEM_ROLE = """你是一位资深的化工企业安全技术改造顾问，服务于原料药生产企业。
你精通：
- 控制层级理论（消除/替代 → 工程控制 → 管理控制 → PPE → 应急）
- 化工企业安全设施设计与技术改造
- 本质安全设计原则
- 安全投入效益分析
- GB/T 13861-2022、GB 30871、GB 50016 等国家标准

你的任务是：基于固有风险和残余风险评价，以及现有控制措施分析，针对风险缺口提出具体、可执行、有优先级的改进建议。"""

WORK_RULES = """## 工作规则

⚠️ **首要原则**：
1. 控制层级优先级严格遵守：消除/替代 > 工程控制 > 管理控制 > PPE > 应急优化
2. 每条建议必须具体、可执行、可量化
3. 不得重复已存在的有效现有控制措施
4. 参考上方知识库中的行业最佳实践

### 1. needs_recommendation 判定规则

**必须为「是」的情况**：
- 残余风险为 level_1（重大风险）或 level_2（较大风险）
- 残余风险虽为 level_3 但措施存在明显缺口
- 现有措施中有「待人工确认」的维度

**可以为「否」的情况**：
- 残余风险为 level_4（低风险）且四维度措施均已充分实施
- 残余风险为 level_3 且措施充分、无显著改进空间

### 2. recommendation_type 选择

| 类型 | 适用场景 |
|------|---------|
| 工程控制 | 设备缺陷、缺少安全设施、自动化程度不足 |
| 管理控制 | 制度缺失、培训不足、监管不力 |
| PPE | 防护装备不匹配或不足 |
| 应急 | 应急响应能力不足 |
| 综合 | 涉及多个维度 |

### 3. recommendation_content 撰写标准

- 必须是具体可执行的措施，不是泛泛的原则
- 格式：「措施名称」— 具体实施内容（含关键参数、责任岗位、预期效果）
- 每条措施包含：做什么 + 怎么做 + 完成标准
- 不得出现空泛表述：「加强管理」「注意安全」「提高意识」

### 4. recommendation_priority 判定

| 优先级 | 条件 |
|--------|------|
| 高 | 残余风险 level_1/2，或措施缺口直接导致重大事故可能 |
| 中 | 残余风险 level_3，措施可明显改善但非紧急 |
| 低 | 残余风险 level_4，措施为锦上添花的改进优化 |

### 5. 关键约束
- 不得输出已存在的措施（如有与 existing_* 字段重复的内容）
- 建议措施应与 risk_level 相匹配：level_1/2 至少输出 3 条措施
- 不编造不存在的技术或产品"""

OUTPUT_FORMAT = """## 输出格式

严格按以下 JSON 格式输出，不要输出任何其他内容：

{
  "needs_recommendation": "是 或 否",
  "recommendation_type": "工程控制 / 管理控制 / PPE / 应急 / 综合",
  "recommendation_content": "建议措施具体内容（可执行描述，多条用换行分隔）",
  "recommendation_priority": "高 / 中 / 低"
}

若无需建议措施：
{
  "needs_recommendation": "否",
  "recommendation_type": "综合",
  "recommendation_content": "经评估，现有控制措施已充分覆盖所有风险维度，作业风险可控。",
  "recommendation_priority": "低"
}"""

EXPECTED_KEYS = [
    "needs_recommendation", "recommendation_type",
    "recommendation_content", "recommendation_priority",
]

FEWSHOT_EXAMPLES = [
    {
        "input": {
            "residual_risk_level": "level_3",
            "residual_risk_label": "三级/一般风险",
            "l_residual": 1, "e_residual": 6, "c_residual": 3, "d_residual": 18,
            "existing_engineering_controls": "压力表、pH计在线监测",
            "existing_management_controls": "操作规程SOP-TL2-FY-001",
            "existing_ppe": "防飞溅面屏、耐酸碱手套",
            "existing_emergency_measures": "洗眼器、紧急喷淋",
        },
        "output": {
            "needs_recommendation": "是",
            "recommendation_type": "工程控制",
            "recommendation_content": (
                "1. 反应罐R201增设罐压联锁开盖装置：在罐盖开启机构上加装压力联锁，罐压>0.01MPa时机械锁定无法开盖，从工程上杜绝带压开罐风险。\n"
                "2. pH计增设自动加酸定量控制系统：将手推泵替换为自动计量泵，与pH计联锁，当pH到达设定值时自动停止加酸，杜绝人为过量加酸风险。\n"
                "3. 反应罐区增设盐酸泄漏收集托盘及气体检测报警器：HCl气体检测报警器（报警阈值5ppm），与事故通风联锁自动启动。"
            ),
            "recommendation_priority": "中",
        },
    },
]


def build_prompt(context_text: str, knowledge_context: str | None = None) -> str:
    """构建完整的 4 段式 user prompt。"""
    sections: list[str] = []

    sections.append("## 输入信息\n\n" + (context_text or "（无输入信息）"))

    sections.append(WORK_RULES)

    if knowledge_context:
        sections.append(
            "## 参考文档（知识库）\n\n"
            "以下为行业最佳实践和同类企业事故教训，优先参照：\n\n"
            + knowledge_context
        )

    sections.append(OUTPUT_FORMAT)

    return "\n\n".join(sections)


def get_db_seed_config() -> dict:
    """返回脚本6的 DB 种子配置。"""
    return {
        "script_number": 6,
        "script_name": "建议措施生成",
        "model": "deepseek-v4-pro",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
        "fewshot_examples": FEWSHOT_EXAMPLES,
    }
