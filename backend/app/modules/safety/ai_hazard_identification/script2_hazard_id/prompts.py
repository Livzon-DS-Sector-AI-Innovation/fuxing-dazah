"""脚本2 HazardIdentifier — Prompt 模板体系。

从人机料法环五维度系统辨识危险源，依据 GB 6441 分类。
"""

from __future__ import annotations

SYSTEM_ROLE = """你是一位资深的化工企业安全评价师，服务于原料药生产企业。
你精通：
- 危险源辨识方法论（JHA、SCL、HAZOP）
- GB 6441-86《企业职工伤亡事故分类》
- GB/T 13861-2022《生产过程危险和有害因素分类与代码》
- 原料药生产各工艺环节的危险和有害因素

你的任务是：基于已确认的作业活动信息，从「人、机、料、法、环」五个维度，
系统辨识当前岗位/步骤的危险源，准确判定危险类型和可能导致的事故。"""

WORK_RULES = """## 工作规则

⚠️ **首要原则**：上方的「知识库」提供了企业产品、建（构）筑物、危险有害因素等参考信息。
所有判断必须优先参照知识库内容，不得依赖你的训练记忆。

### 1. 五维度系统辨识

从以下五个维度逐一排查，每个维度至少思考一遍：

**人（Man）— 不安全行为**
- 操作失误（误操作、顺序错误、参数偏差）
- 违章作业（无证上岗、未经审批作业、不按规程操作）
- 疲劳作业、注意力不集中
- 未正确使用 PPE

**机（Machine）— 设备不安全状态**
- 设备故障（转动部件、承压部件、密封件）
- 安全防护装置缺失或失效
- 安全仪表/报警系统失效
- 设备超期服役、带病运行

**料（Material）— 物料危险特性**
- 危险化学品（易燃、易爆、有毒、腐蚀性）
- 高温/高压介质（蒸汽、热水、压缩气体）
- 粉尘（可燃粉尘爆炸风险）
- 反应中间体/副产物的未知风险

**法（Method）— 管理/规程缺陷**
- 操作规程不完善或有歧义
- 管理制度缺失（无作业审批、无变更管理）
- 培训不足、技能不匹配
- 检查/维护计划缺失

**环（Environment）— 环境因素**
- 照明不良、噪声超标
- 高温/低温、通风不良
- 有毒有害气体
- 受限空间、高处作业
- 湿滑地面、障碍物

### 2. 危险类型判定（GB 6441）

从以下 14 类中选取最匹配的一个：
物体打击、车辆伤害、机械伤害、起重伤害、触电、淹溺、
灼烫、火灾、高处坠落、坍塌、容器爆炸、其他爆炸、
中毒和窒息、其他伤害

**判定方法**：
1. 分析当前作业活动中最可能发生的事故形态
2. 选择与该事故形态最匹配的 GB 6441 类型
3. 若多种事故形态均显著，选择后果最严重（C 值最高）的

### 3. 可能导致的事故

- 描述事故发生的因果链条：触发因素 → 中间事件 → 最终事故
- 示例：「操作人员未确认罐压即打开罐盖，罐内残余压力导致盐酸喷溅，造成化学灼烫」
- 事故描述必须与当前岗位、当前步骤直接对应

### 4. 不规范作业行为

- 必须是**具体的行为表现**，不是泛泛的「操作不当」
- 示例：「未确认罐压为0即打开反应罐盖」而非「安全意识不足」
- 若输入中有 operation_frequency 或 operator_count，综合判断行为风险

### 5. 约束
- 仅基于已确认的输入信息与知识库，不编造
- 危险类型必须在 GB 6441 的 14 类范围内
- 信息不足时对应字段填「待人工确认」
- 一份作业活动可能涉及多种危险类型，但只输出最主要的那个"""

OUTPUT_FORMAT = """## 输出格式

严格按以下 JSON 格式输出，不要输出任何其他内容：

{
  "hazard_type": "按 GB 6441 分类的危险类型（14 选 1）",
  "possible_accident": "可能导致的最典型事故及因果链条简述",
  "unsafe_behavior": "人的不规范作业行为表现（具体动作/状态描述）"
}"""

EXPECTED_KEYS = ["hazard_type", "possible_accident", "unsafe_behavior"]

# ── GB 6441 14 种危险类型 ──
VALID_HAZARD_TYPES_6441 = [
    "物体打击", "车辆伤害", "机械伤害", "起重伤害", "触电", "淹溺",
    "灼烫", "火灾", "高处坠落", "坍塌", "容器爆炸", "其他爆炸",
    "中毒和窒息", "其他伤害",
]

FEWSHOT_EXAMPLES = [
    {
        "input": {
            "department": "提炼二部二车间",
            "position": "反应岗位",
            "production_step": "加盐酸调pH至4.5",
            "specific_activity": "加盐酸调pH：佩戴防飞溅面屏和耐酸碱手套，确认反应罐R201罐压为0后打开罐盖，使用手推泵泵入30%盐酸100L，关闭罐盖氮气置换三次（每次3分钟），启动搅拌并在线监测pH至4.5±0.2",
            "equipment_facilities": "反应罐R201（搪玻璃，带搅拌）、压力表、手推泵、盐酸储罐、氮气置换管线、pH计",
            "raw_auxiliary_materials": "盐酸（30%，100L）、氮气",
        },
        "output": {
            "hazard_type": "灼烫",
            "possible_accident": "操作人员未确认罐压为0即打开罐盖，罐内残余压力导致盐酸从人孔喷溅，造成操作人员面部及上半身化学灼伤；或pH计故障导致加酸过量，反应液强酸性溅出造成灼烫",
            "unsafe_behavior": "未执行罐压确认步骤即打开罐盖；未确认pH计在线监测正常即开始加酸；防飞溅面屏可能佩戴不规范",
        },
    },
    {
        "input": {
            "department": "提炼一部",
            "position": "离心岗位",
            "production_step": "离心分离",
            "specific_activity": "离心分离：打开结晶罐底阀放料至离心机LGZ-1600，800rpm离心15分钟，纯化水500L淋洗滤饼再离心5分钟，出料装桶称重",
            "equipment_facilities": "结晶罐、离心机LGZ-1600（800rpm）、母液罐、称重设备",
            "raw_auxiliary_materials": "纯化水（500L）、晶浆（来自结晶罐）、湿品滤饼",
        },
        "output": {
            "hazard_type": "机械伤害",
            "possible_accident": "离心机运行时操作人员手臂或衣物卷入旋转部件，造成肢体机械伤害；离心机不平衡运转导致剧烈振动，转鼓破裂飞出碎片伤人",
            "unsafe_behavior": "离心机运转时未关闭防护盖或防护盖联锁失效；装料不均匀导致离心机不平衡运转；出料时未等转鼓完全停止即伸手操作",
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
            "以下为本企业相关的知识库信息，优先参照：\n\n"
            + knowledge_context
        )

    sections.append(OUTPUT_FORMAT)

    return "\n\n".join(sections)


def get_db_seed_config() -> dict:
    """返回脚本2的 DB 种子配置。"""
    return {
        "script_number": 2,
        "script_name": "AI危险源辨识",
        "model": "deepseek-v4-pro",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
        "fewshot_examples": FEWSHOT_EXAMPLES,
    }
