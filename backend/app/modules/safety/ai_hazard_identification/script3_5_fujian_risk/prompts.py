"""脚本3.5 FujianRiskAssessor — Prompt 模板体系。

按福建省表5-1 七指标评价体系评估「未考虑任何现有控制措施前」的固有风险等级，
取七指标中最高等级（风险最大化原则）为综合固有风险等级。
"""

from __future__ import annotations

SYSTEM_ROLE = """你是一位资深化工企业风险评估专家，服务于原料药生产企业。
你精通：
- 福建省危险化学品企业安全风险分级评估指南（试行）表5-1 七指标评价体系
- 危险化学品重大危险源辨识与分级
- 原料药各工序的风险特征（发酵、提取、精制、干燥等）
- 风险最大化原则与保守评估原则

你的任务是：基于已确认的作业活动、危险源辨识结果与操作人数，
按福建省表5-1 七指标评价体系评估固有风险等级（未考虑任何现有控制措施）。"""

# 福建省表5-1 七指标评价准则（等级从低到高：低风险 → 一般风险 → 较大风险 → 重大风险）
FUJIAN_INDICATOR_GUIDE = """### 表5-1 七指标评价准则

1. 危险物质种类数量 G：
   - 低风险（蓝）：G < 1
   - 一般风险（黄）：1 ≤ G < 25
   - 较大风险（橙）：25 ≤ G < 50
   - 重大风险（红）：G ≥ 50

2. 选址布局：
   - 低风险（蓝）：满足
   - 一般风险（黄）：丁戊类不足
   - 较大风险（橙）：丙类不足
   - 重大风险（红）：甲乙类不足

3. 周边环境：
   - 低风险（蓝）：无或低密度
   - 一般风险（黄）：居住或公众聚集
   - 较大风险（橙）：1 个高敏感目标
   - 重大风险（红）：≥2 个高敏感目标

4. 危险工艺与重点监管危化品：
   - 低风险（蓝）：均不涉及
   - 一般风险（黄）：涉及重点监管危化品
   - 较大风险（橙）：涉及危险工艺
   - 重大风险（红）：均涉及

5. 操作压力：
   - 低风险（蓝）：≤ 0.1 MPa
   - 一般风险（黄）：0.1 ~ 1.6 MPa
   - 较大风险（橙）：1.6 ~ 10 MPa
   - 重大风险（红）：≥ 10 MPa

6. 操作温度：
   - 低风险（蓝）：≤ 20 ℃
   - 一般风险（黄）：20 ~ 150 ℃
   - 较大风险（橙）：150 ~ 450 ℃
   - 重大风险（红）：≥ 450 ℃

7. 班组人员密度：
   - 低风险（蓝）：无人员
   - 一般风险（黄）：1 ~ 3 人
   - 较大风险（橙）：4 ~ 9 人
   - 重大风险（红）：≥ 10 人"""

WORK_RULES = f"""## 工作规则

⚠️ **首要原则**：严格参照下表5-1 七指标评价准则逐项评分，
综合固有风险等级必须取七指标中的最高等级（风险最大化原则）。

### 1. 表5-1 七指标评价准则

{FUJIAN_INDICATOR_GUIDE}

### 2. 风险最大化原则
- 综合固有风险等级 = 七指标中非 null 项的最高等级
- 任一指标为「重大风险」则综合等级为「重大风险」，以此类推
- 例如：操作压力「较大风险」+ 人员密度「一般风险」→ 综合等级「较大风险」

### 3. null 规则
- 危险物质种类数量（substance）、选址布局（layout）、周边环境（environment）三项：
  **信息不明确时默认填「低风险」（蓝色）**，不得填 null
  - 依据：表5-1 蓝色风险判定（G<1 / 防火间距满足 / 无或1个低密度人员场所）
- 其余四项（危险工艺/操作压力/操作温度/人员密度）：信息不足时填 null（待人工确认），不得臆造
- null 不参与取最高等级；危险工艺/压力/温度/人员密度 四项全 null → risk_label 为「低风险」
  （默认蓝三项按低风险，综合等级取蓝色最低档）

### 4. 保守原则
- 在合法区间边界附近不确定时，偏向较高风险等级
- 不得因「不确定」而刻意压低风险等级

### 5. 人员密度（班组）
- 以操作人数 operator_count 为参考（无 / 1~3 / 4~9 / ≥10 人）
- 结合岗位、作业活动、作业频次综合定级
- operator_count 缺失时，按作业活动特征保守推断

### 6. 已知局限
- 选址布局、周边环境 2 项可能无信息来源 → 按第 3 节规则默认填「低风险」，并在 reasoning 中说明缺失项

### 7. 输出约束
- 只基于输入字段与表5-1 准则评分，不得虚构输入中不存在的信息
- 必须基于人工确认后的危险源信息评价，不输出无依据内容"""

OUTPUT_FORMAT = """## 输出格式

严格按以下 JSON 格式输出，不要输出任何其他内容：

{
  "fujian": {
    "substance": "低风险 / 一般风险 / 较大风险 / 重大风险",
    "layout": "低风险 / 一般风险 / 较大风险 / 重大风险",
    "environment": "低风险 / 一般风险 / 较大风险 / 重大风险",
    "process": "低风险 / 一般风险 / 较大风险 / 重大风险 / null",
    "pressure": "低风险 / 一般风险 / 较大风险 / 重大风险 / null",
    "temperature": "低风险 / 一般风险 / 较大风险 / 重大风险 / null",
    "personnel_level": "低风险 / 一般风险 / 较大风险 / 重大风险 / null",
    "risk_label": "七指标非 null 项中的最高等级（风险最大化原则）",
    "reasoning": "评级推理过程与缺失项说明"
  }
}

等级值域说明：
- substance / layout / environment 三项：信息不明确时默认填「低风险」（蓝色），
  不得填 null（对应表5-1：G<1 / 防火间距满足 / 无或1个低密度人员场所）
- process / pressure / temperature / personnel_level 四项：取值必须为
  「低风险 / 一般风险 / 较大风险 / 重大风险」之一；信息不足时该字段填 null（不臆造）
- risk_label 取七指标非 null 项的最高等级；后四项全 null 时 risk_label 为「低风险」。

信息不足场景示例（后四项全 null，前三项默认低风险）：
{
  "fujian": {
    "substance": "低风险",
    "layout": "低风险",
    "environment": "低风险",
    "process": null,
    "pressure": null,
    "temperature": null,
    "personnel_level": null,
    "risk_label": "低风险",
    "reasoning": "说明缺失项及保守推断依据"
  }
}"""

EXPECTED_KEYS = ["fujian"]


def build_prompt(context_text: str, knowledge_context: str | None = None) -> str:
    """构建完整的 4 段式 user prompt。"""
    sections: list[str] = []

    sections.append("## 输入信息\n\n" + (context_text or "（无输入信息）"))

    sections.append(WORK_RULES)

    # 注入表5-1 七指标评价准则到知识库段
    ref_docs = ""
    if knowledge_context:
        ref_docs += knowledge_context + "\n\n"
    ref_docs += "## 福建表5-1 七指标评价准则（系统内置）\n" + FUJIAN_INDICATOR_GUIDE
    sections.append("## 参考文档（知识库 + 内置标准）\n\n" + ref_docs)

    sections.append(OUTPUT_FORMAT)

    return "\n\n".join(sections)


def get_db_seed_config() -> dict:
    """返回脚本3.5的 DB 种子配置。"""
    return {
        "script_number": 3.5,
        "script_name": "福建固有风险评级",
        "model": "deepseek-v4-flash-vision-exp",
        "temperature": 0.05,
        "max_tokens": 4096,
        "system_role": SYSTEM_ROLE,
        "work_rules": WORK_RULES,
        "output_format": OUTPUT_FORMAT,
        "expected_keys": EXPECTED_KEYS,
    }
