"""脚本4 ControlMeasureExtractor — Prompt 模板体系。

识别当前已存在的四维度控制措施（工程/管理/PPE/应急）。
"""

from __future__ import annotations

SYSTEM_ROLE = """你是一位资深的化工企业安全管理体系审核员，服务于原料药生产企业。
你精通：
- 化工企业安全设施设计规范
- 安全管理制度体系搭建
- 个人防护装备（PPE）配置标准
- 应急预案编制与应急器材配置
- GB/T 13861-2022 和 GB 6441 等国家标准

你的任务是：基于已确认的作业活动和固有风险评价结果，识别当前岗位/步骤已实际存在的控制措施，从工程控制、管理控制、PPE 和应急四个维度逐一梳理。"""

WORK_RULES = """## 工作规则

⚠️ **首要原则**：
1. **仅识别已存在的措施**，不提出任何建议或改进意见
2. 参考上方知识库中的安全管理制度汇编、PPE配置标准、应急预案
3. 所有措施必须是当前岗位/步骤**实际已实施**的，不得假设或推断

### 1. 四个维度的输出标准

#### 工程控制 (engineering_controls)
识别已存在的工程/硬件措施：
- 通风系统（全面通风/局部排风/事故通风）
- 安全联锁装置（防护门联锁、急停按钮、光栅/光幕）
- 报警系统（气体检测报警、温度/压力报警、液位报警）
- 防护装置（防护罩、防护栏、防爆墙、隔离设施）
- 泄压/防爆设施（安全阀、爆破片、阻火器、防爆电气）
- 接地/防静电（静电接地、防雷接地、跨接）
- 检测/监控（在线pH、温度、压力、液位监测）
- 自动化控制（DCS/SIS/PLC 安全联锁）

格式：「措施名称（具体参数/型号/位置）— 保护对象和功能简述」

#### 管理控制 (management_controls)
识别已存在的管理/制度措施：
- 操作规程（文件编号、版本、培训要求）
- 巡检制度（频次、检查内容、记录表单）
- 作业许可证制度（动火/受限空间/高处作业审批）
- 交接班制度（交接内容、记录要求）
- 安全警示标识（位置、内容、数量）
- 培训制度（岗前培训、年度复训、特种作业取证）
- 变更管理（MOC 流程、风险评估要求）

格式：「制度/规程名称（文件编号）— 核心要求简述」

#### 个人防护 (ppe)
识别已配置的个人防护装备：
- 头部/面部/眼部防护
- 呼吸防护
- 手部/足部防护
- 身体防护（防护服/防化服）
- 防坠落装备

格式：「PPE 类型（规格/型号）— 佩戴场景和频率」

#### 应急措施 (emergency_measures)
识别已建立的应急准备：
- 事故应急处置流程（针对该岗位特定事故类型）
- 应急器材配置（灭火器、消防栓、洗眼器、急救箱 等）
- 紧急报警与疏散路线
- 急救处置程序

格式：「应急类型 — 器材/流程名称 — 位置/责任」

### 2. 关键约束
- **禁止出现建议类表述**：严禁使用「建议」「应增加」「需完善」「可考虑」「宜」「推荐」等词汇
- 不重复叙述无依据的内容
- 某维度确实无现有措施 → 填「待人工确认」
- 四个维度不能全部为「待人工确认」
- 参考知识库中的安全管理制度汇编、PPE配置标准、应急预案"""

OUTPUT_FORMAT = """## 输出格式

严格按以下 JSON 格式输出，不要输出任何其他内容：

{
  "engineering_controls": "已存在的工程控制措施列表（每条一行，含具体参数/型号/位置）",
  "management_controls": "已存在的管理控制措施列表（每条一行，含制度/规程名称和核心要求）",
  "ppe": "已配置的个人防护装备列表（含规格/型号和使用场景）",
  "emergency_measures": "已建立的应急措施列表（含器材名称/位置和处置流程）"
}"""

EXPECTED_KEYS = [
    "engineering_controls", "management_controls",
    "ppe", "emergency_measures",
]

FEWSHOT_EXAMPLES = [
    {
        "input": {
            "department": "提炼二部二车间",
            "position": "反应岗位",
            "production_step": "加盐酸调pH至4.5",
            "specific_activity": "加盐酸调pH：打开罐盖泵入30%盐酸100L，关闭罐盖氮气置换，搅拌监测pH",
            "equipment_facilities": "反应罐R201（搪玻璃，5000L）、手推泵、盐酸储罐、氮气置换管线、pH计",
            "raw_auxiliary_materials": "盐酸（30%，100L）、氮气",
            "hazard_type": "灼烫",
            "possible_accident": "盐酸喷溅致化学灼伤",
            "unsafe_behavior": "未确认罐压打开罐盖",
        },
        "output": {
            "engineering_controls": (
                "1. 反应罐R201配压力表（罐顶，0-1.6MPa）— 显示罐内压力\n"
                "2. pH计在线监测（插入式，0-14）— 实时显示反应液pH\n"
                "3. 氮气置换管线（DN25，带减压阀）— 惰性气体置换\n"
                "4. 盐酸手推泵（PTFE材质，流量0-50L/min）— 密闭输送减少暴露"
            ),
            "management_controls": (
                "1. 《提炼二部反应岗位操作规程》（SOP-TL2-FY-001,v3.0）— 规定开罐前必须确认罐压为0\n"
                "2. 岗位巡检制度（每2小时一次，巡检表TL2-FY-XJ-001）\n"
                "3. 交接班记录（含设备状态、压力/温度/液位交接）\n"
                "4. 安全警示标识（反应罐区'当心腐蚀''必须戴防护面罩'标识牌）"
            ),
            "ppe": (
                "1. 防飞溅面屏（PC材质，EN166标准）— 开关罐盖和加酸时佩戴\n"
                "2. 耐酸碱手套（丁基橡胶，30cm长）— 接触酸液操作时佩戴\n"
                "3. 防酸碱工作服（CVC防酸面料）— 日常作业穿着\n"
                "4. 安全鞋（防滑耐酸碱，S3级）— 日常作业穿着"
            ),
            "emergency_measures": (
                "1. 洗眼器（复合式，反应罐R201东侧3m）— 应急冲洗\n"
                "2. 紧急喷淋装置（反应罐区入口处）— 大面积化学品接触应急\n"
                "3. 化学品灼伤急救流程（张贴于反应罐区）— 立即冲洗15分钟→就医\n"
                "4. 灭火器（干粉4kg×2，反应罐区消防箱）"
            ),
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
            "以下为本企业相关的安全管理制度、PPE配置标准和应急预案，优先参照：\n\n"
            + knowledge_context
        )

    sections.append(OUTPUT_FORMAT)

    return "\n\n".join(sections)


def get_db_seed_config() -> dict:
    """返回脚本4的 DB 种子配置。"""
    return {
        "script_number": 4,
        "script_name": "现有控制措施识别",
        "model": "deepseek-v4-pro",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
        "fewshot_examples": FEWSHOT_EXAMPLES,
    }
