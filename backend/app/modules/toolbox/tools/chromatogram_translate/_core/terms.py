"""三层术语治理：内置锁定表 > 配置页 CSV > AI 补译。

内置表是两批真实报告（13 页 HPLC + 46 个荧光报告）人工验收的成果，
全部经过视觉评审；AI 补译的新词条不可信（曾把 秒→Miao、公司名→Lizhu），
必须经人工确认加入配置页术语表后才成为锁定术语。"""

from __future__ import annotations

import csv
import io

from .spans import cjk_segments, has_cjk

# 内置锁定术语（优先级最高；配置页 CSV 可覆盖）
BUILTIN_TERMS: dict[str, str] = {
    # ── 公司/抬头 ──
    "* * *  丽 珠 集 团 福 州 福 兴 医 药 有 限 公 司  * * *": "* * *  Livzon Group Fuzhou Fuxing Pharmaceutical Co., Ltd.  * * *",
    "丽珠集团福州福兴医药有限公司": "Livzon Group Fuzhou Fuxing Pharmaceutical Co., Ltd.",
    "丽珠福兴": "Livzon Fuxing",
    "企业": "Enterprise",
    # ── 峰结果表头/单位（含跨列拆分件）──
    "名称": "Name",
    "保留时间": "Retention Time",
    "面积": "Area",
    "理论塔板数": "Theoretical Plates",
    "高度": "Height",
    "拖尾因子": "Tailing Factor",
    "分离度": "Resolution",
    "拖尾因子分离度": "Tailing Factor Resolution",
    "分离度拖尾因子": "Resolution and Tailing Factor",
    "分钟": "min",
    "微伏": "µV",
    "微伏秒": "µV*sec",
    "秒": "sec",
    "峰结果": "Peak Results",
    # ── 信息区标签（含带冒号整串变体）──
    "样品信息": "Sample Information",
    "样品名称": "Sample Name",
    "样品名称:": "Sample Name:",
    "样品组名称": "Sample Set Name",
    "样品组名称:": "Sample Set Name:",
    "系统名称": "System Name",
    "系统名称:": "System Name:",
    "瓶号": "Vial Number",
    "瓶号:": "Vial Number:",
    "进样次数": "Number of Injections",
    "进样次数:": "Number of Injections:",
    "进样体积": "Injection Volume",
    "进样体积:": "Injection Volume:",
    "运行时间": "Run Time",
    "运行时间:": "Run Time:",
    "采集时间": "Acquisition Time",
    "采集时间:": "Acquisition Time:",
    "采集者": "Acquired by",
    "采集者:": "Acquired By:",
    "采集方法组": "Acquisition Method Set",
    "采集方法组:": "Acquisition Method Set:",
    "处理方法": "Treatment Method",
    "处理方法:": "Processing Method:",
    "处理时间": "Treatment Time",
    "处理时间:": "Processing Time:",
    "通道名称": "Channel Name",
    "通道名称:": "Channel Name:",
    "处理通道注释": "Processing Channel Comment",
    "处理通道注释:": "Processing Channel Comment:",
    "项目名称": "Project Name",
    "项目名称:    方法确认或验证\\达托霉素": "Project Name:    Method Qualification or Validation\\Daptomycin",
    "方法确认或验证": "Method Qualification or Validation",
    # ── 页脚 ──
    "报告用户": "Report User",
    "报告方法": "Report Method",
    "页码": "Page Number",
    "共计": "Total",
    "页码: 1 (共计 1)": "Page: 1 (Total 1)",
    "报告方法:  丽珠福兴": "Report Method:  Livzon Fuxing",
    "报告用户:  杨雅琳 (杨雅琳)": "Report User:  Yang Yalin (Yang Yalin)",
    # ── 图区/标题 ──
    "色谱图": "Chromatogram",
    "自动标尺色谱图": "Auto-Scaled Chromatogram",
    # ── 峰名（药学术语，AI 常译错，全部锁定）──
    "达托霉素": "Daptomycin",
    "脱水达托霉素": "Anhydrodaptomycin",
    "内酯水解物": "Lactone Hydrolysate",
    "杂质": "Impurity",
    "异构体": "Isomer",
    "溶剂": "Solvent",
    "标准": "Standard",
    "空白": "Blank",
    "空白-2": "Blank-2",
    "空白-3": "Blank-3",
    "标准1": "Standard 1",
    "标准2": "Standard 2",
    "标准-60h": "Standard-60h",
    "达托霉素HCP—企业": "Daptomycin HCP—Enterprise",
    "达托霉素—企业—": "Daptomycin—Enterprise—",
    "达托霉素总蛋白质": "Daptomycin Total Protein",
    "达托霉素总蛋白质—企业": "Daptomycin Total Protein—Enterprise",
    "达托霉素总蛋白质—企业—13225": "Daptomycin Total Protein—Enterprise—13225",
    "达托霉素总蛋白质柱温减少": "Daptomycin Total Protein Column Temp Decrease",
    "达托霉素总蛋白质柱温减少13225": "Daptomycin Total Protein Column Temp Decrease 13225",
    "达托霉素总蛋白质柱温增加": "Daptomycin Total Protein Column Temp Increase",
    "达托霉素总蛋白质柱温增加13225": "Daptomycin Total Protein Column Temp Increase 13225",
    "达托霉素总蛋白质流速减少": "Daptomycin Total Protein Flow Rate Decrease",
    "达托霉素总蛋白质流速减少13225": "Daptomycin Total Protein Flow Rate Decrease 13225",
    "达托霉素总蛋白质流速增加": "Daptomycin Total Protein Flow Rate Increase",
    "达托霉素总蛋白质流速增加13225": "Daptomycin Total Protein Flow Rate Increase 13225",
    "浓度水平标准": "Concentration Level Standard",
    "50%浓度水平标准-1": "50% Concentration Level Standard-1",
    "100%浓度水平标准-1": "100% Concentration Level Standard-1",
    "150%浓度水平标准-1": "150% Concentration Level Standard-1",
    "200%浓度水平标准-1": "200% Concentration Level Standard-1",
    "50%标准+DT2512001-1": "50% Standard+DT2512001-1",
    "100%标准+DT2512001-1": "100% Standard+DT2512001-1",
    "100%标准+DT2512001-45h": "100% Standard+DT2512001-45h",
    "150%标准+DT2512001-1": "150% Standard+DT2512001-1",
    # ── 破坏试验 ──
    "酸破坏": "Acid Degradation",
    "酸破坏空白": "Acid Degradation Blank",
    "碱破坏": "Base Degradation",
    "碱破坏空白": "Base Degradation Blank",
    "光照破坏": "Light Degradation",
    "加热破坏": "Heat Degradation",
    "氧化破坏": "Oxidative Degradation",
    "氧化破坏空白": "Oxidative Degradation Blank",
    # ── 人名（拼音）──
    "姜滨": "Jiang Bin",
    "蔡珊梅": "Cai Shanmei",
    "杨雅琳": "Yang Yalin",
    "汤钰芳": "Tang Yufang",
    "桑婉婧": "Sang Wanjing",
}


def parse_glossary_csv(text: str) -> tuple[dict[str, str], list[str]]:
    """配置页 CSV（每行「中文,English」，首行可为表头）→ (术语表, 解析告警)"""
    terms: dict[str, str] = {}
    warnings: list[str] = []
    reader = csv.reader(io.StringIO(text.strip()))
    for i, row in enumerate(reader, 1):
        if not row or not any(c.strip() for c in row):
            continue
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            warnings.append(f"第 {i} 行格式不符（应为 中文,English），已跳过")
            continue
        zh, en = row[0].strip(), row[1].strip()
        if not has_cjk(zh):
            warnings.append(f"第 {i} 行「{zh}」不含中文，已跳过")
            continue
        if i == 1 and zh in ("中文", "中文术语", "原文"):
            continue  # 表头
        terms[zh] = en
    return terms, warnings


def merged_terms(glossary_csv: str = "") -> tuple[dict[str, str], list[str]]:
    """内置锁定术语 + 配置页 CSV（后者可覆盖内置）。"""
    terms = dict(BUILTIN_TERMS)
    warnings: list[str] = []
    if glossary_csv.strip():
        override, warnings = parse_glossary_csv(glossary_csv)
        terms.update(override)
    return terms, warnings


def collect_missing(all_spans: list[str], terms: dict[str, str]) -> list[str]:
    """跨文件收集缺失词条（整串与中文段两级；混合串按段译）。
    整串已命中的不再逐段收集——渲染时整串优先，逐段收集只会把间隔式
    标题拆成单字噪声（试验期 词条表被拼音单字污染的根源）。"""
    need: set[str] = set()
    for text in all_spans:
        if not has_cjk(text):
            continue
        t = text.strip()
        if t in terms:
            continue
        need.add(t)
        need.update(seg for seg in cjk_segments(t) if seg not in terms)
    return sorted(need)
