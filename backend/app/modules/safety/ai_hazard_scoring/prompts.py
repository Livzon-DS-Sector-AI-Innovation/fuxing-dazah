"""AI隐患评分 — prompt 构建。

制度锚定三件套：§10.3 档位表（17 档全文）、13 类别×附件四/五对照精简表、
附件一/AQ3067 重大隐患判定条目号索引。上下文不含上报人身份（评分主体=隐患本身）。
"""

from __future__ import annotations

from app.modules.safety.ai_hazard_scoring.schemas import HazardScoringInput

SYSTEM_ROLE = (
    "你是化工企业的隐患风险评分专家。你的唯一任务：依据给定的制度档位表，"
    "对一条隐患选择 L/E/C/X 四个维度的档位、公司风险等级 H/M/L，"
 "并对照重大隐患判定标准给出命中条目。"
    "严格约束：只能从档位表列出的档位中选择，禁止自创档位或分值；"
    "禁止输出总分（总分由系统计算）；每维给一句 ≤60 字理由；"
    "排查难度 X 指「该隐患被日常排查发现的难易」，越难发现分值越高。"
    "只输出 JSON，不输出任何其他文字。"
)

# ── 制度 §10.3 档位表（原文，17 档）──
LECX_TABLE = """【打分档位表（制度 §10.3，唯一权威）】
L 造成事故的可能性：非常可能2 / 可能1.5 / 可能性小1
E 工作人员接触隐患频率：连续接触2 / 每天几次接触1.8 / 每周接触1.6 / 每月接触1.4 / 每年接触1.2 / 很少接触1
C 可能造成事故的后果：灾难25 / 非常严重22 / 严重20 / 一般18 / 轻微15
X 排查难度（被日常排查发现的难易）：难1 / 较难0.99 / 一般0.98
综合得分 D=L×E×C×X 由系统计算，你不要输出。"""

# ── 13 类别 × 附件四/五典型条目对照（每类 ≤6 条，标注典型 band）──
CATEGORY_BAND_TABLE = """【风险等级对照表（附件四/五精简，按隐患类别）】
- 设备设施(equipment)：淘汰设备H；安全设施超期未校验H；设备异响异常振动H；探头/阻火器失效M；防护罩脱落M；静电跨接L
- 危化储存(hazardous_storage)：禁忌危化品混放H；超量超品种M；存放不符防腐防漏M
- 应急管理(emergency_mgmt)：消防设施设计不足M；灭火器/洗眼器缺维护M；应急通道堵塞M
- 仪表+电气(instrument_electrical)：防爆区域设备失爆H；非防爆设备无控制H；接地搭接串接M
- 防雷防静电(lightning_antistatic)：无静电释放装置M；静电接地故障M；跨接缺失L
- 职业健康+劳保(occupational_health)：未正确佩戴PPE M；LEV未有效使用M；照度不足L
- 三违作业(violation_operation)：惰性化不到位H；试压试漏不到位H；无证特种作业H；溶剂废液混装H；双人复核不到位M
- 6S(six_s)：未定置定位存放L；地面湿滑L
- 标签标识(label_signage)：安全警示标志缺失M；标签张贴错误M；提示标志缺失L
- 工艺管理(process_mgmt)：擅自更改工艺H；未经评估带压紧固H；超温超压超液位H；变更未评估即执行H
- 承包商缺陷(contractor_defect)：资质不符M；危化车辆三证不齐M；车辆无阻火器H
- 内页资料(documentation)：新员工未三级培训独立上岗H；特种作业未持证H；JHA缺失M；记录不齐M
- 特殊作业(special_operation)：作业票原则性错误H；动火等措施不到位M；未气体分析H
定 band 时优先按此表条目对号，并引用条目（如「附件五·安全操作·静电控制M」）。"""

# ── 附件一（试行20条）+ AQ3067 判定条目号索引（每条 ≤30 字）──
MAJOR_CLAUSES_INDEX = """【重大隐患判定条目索引（命中时引用条目号）】
附件一（化工重大隐患判定试行）：一 负责人/安管未考核合格；二 特种作业未持证；三 两重点一重大防护距离不符；四 重点工艺未自动化/无紧急停车；五 一二级重大危险源罐区无紧急切断/剧毒液化气无SIS；六 全压力式液化烃储罐未设注水；七 液化烃液氨液氯充装未用万向管道；八 剧毒/硫化氢管道穿越厂外公共区域；九 架空电力线路穿越生产区不符；十 在役装置未正规设计未诊断；十一 使用淘汰工艺设备；十二 可燃有毒场所未设检测报警/防爆电气不符；十三 控制室机柜间防火防爆不符；十四 未双重电源/自控无UPS；十五 安全阀爆破片未投用；十六 未建全员责任制/隐患排查制度；十七 未制定操作规程和工艺指标；十八 特殊作业制度未建或未执行；十九 新工艺未经试验直投/未做反应安全风险评估；二十 危化品未分区分类/超量/混放
AQ 3067 判定准则（按类引用）：重点从业人员 / 设计与规划 / 工艺技术 / 设备设施 / 生产运行 / 作业安全 / 安全管理"""

OUTPUT_FORMAT = """【输出 JSON 契约（键名严格一致，档位用中文原文）】
{
  "likelihood": "非常可能|可能|可能性小",
  "likelihood_reason": "≤60字",
  "exposure": "连续接触|每天几次接触|每周接触|每月接触|每年接触|很少接触",
  "exposure_reason": "≤60字",
  "consequence": "灾难|非常严重|严重|一般|轻微",
  "consequence_reason": "≤60字",
  "difficulty": "难|较难|一般",
  "difficulty_reason": "≤60字",
  "band": "H|M|L",
  "band_basis": "附件四/五条目引用，≤60字",
  "major_hazard": {"hit": true|false, "clauses": ["附件一·十二", ...]},
  "summary": "综合评语，≤80字"
}"""

FEWSHOT_EXAMPLE = """【示例（仅示范格式与引用方式，禁止照抄档位）】
隐患：罐区可燃气体报警器被塑料袋包裹防尘
{"likelihood": "可能", "likelihood_reason": "探头被遮蔽后泄漏不能报警，点火源在罐区常态存在",
 "exposure": "每天几次接触", "exposure_reason": "罐区为巡检必经路线，操作工每天多次经过",
 "consequence": "非常严重", "consequence_reason": "可燃气体泄漏聚积无法预警，可致火灾爆炸",
 "difficulty": "一般", "difficulty_reason": "包裹物目视可见，日常巡检容易发现",
 "band": "H", "band_basis": "附件一·十二 可燃气体场所检测报警装置失效",
 "major_hazard": {"hit": true, "clauses": ["附件一·十二", "AQ 3067·设备设施"]},
 "summary": "报警功能被人为屏蔽属重大隐患判定情形，须立即拆除包裹并核查探头校验期。"}"""

# 描述送入 prompt 前的截断长度（防上下文膨胀）
_DESC_LIMIT = 800
_TRUNCATION_NOTICE = "（描述过长已截断）"


def build_context_text(input_data: HazardScoringInput) -> str:
    """评分上下文（隐患本身 + ①轮识别结论；不含上报人身份）。"""
    desc = input_data.description or ""
    if len(desc) > _DESC_LIMIT:
        desc = desc[:_DESC_LIMIT] + _TRUNCATION_NOTICE
    lines = [
        f"隐患编号：{input_data.hazard_no or '（无）'}",
        f"隐患描述：{desc}",
    ]
    if input_data.key_defect:
        lines.append(f"规范化描述（AI识别）：{input_data.key_defect}")
    if input_data.hazard_category:
        lines.append(f"隐患类别：{input_data.hazard_category}")
    if input_data.hazard_type:
        lines.append(f"隐患分类：{input_data.hazard_type}")
    if input_data.hazard_level:
        lines.append(f"隐患级别（AI）：{input_data.hazard_level}")
    if input_data.major_hazard_basis:
        lines.append(f"判定依据（AI）：{input_data.major_hazard_basis}")
    if input_data.department:
        lines.append(f"所在/责任部门：{input_data.department}")
    if input_data.inspection_category:
        lines.append(f"检查类别：{input_data.inspection_category}")
    return "\n".join(lines)


def build_full_prompt(context_text: str) -> str:
    """完整 user prompt：上下文 + 三件套锚定 + 契约 + few-shot。"""
    return "\n\n".join(
        [
            "请对以下隐患进行风险评分。",
            context_text,
            LECX_TABLE,
            CATEGORY_BAND_TABLE,
            MAJOR_CLAUSES_INDEX,
            OUTPUT_FORMAT,
            FEWSHOT_EXAMPLE,
        ]
    )


def get_expected_keys() -> list[str]:
    """chat_parsed 的 expected_keys 契约（与 OUTPUT_FORMAT 一致）。"""
    return [
        "likelihood", "likelihood_reason",
        "exposure", "exposure_reason",
        "consequence", "consequence_reason",
        "difficulty", "difficulty_reason",
        "band", "band_basis",
        "major_hazard", "summary",
    ]
