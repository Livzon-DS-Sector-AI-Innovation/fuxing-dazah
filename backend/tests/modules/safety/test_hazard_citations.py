"""A4-a 引用判定同源 — citations 纯函数 + RuleEngine 口径回归（ticket 03）。

覆盖：
- 引用正则表驱动：书名号《》、标准号（GB/AQ/HG/SH/JGJ/JGJT/TSG/DL/JB/CJJ/
  TCCSAS/DBxx 等及其 /T、T、全角斜杠、下划线变体）、〔YYYY〕N号、[YYYY]N号、
  第X条/第X.X条/X.X条；
- 占位文案判定（与 2026-11-05 197 条历史重跑脚本口径一致）；
- RuleEngine._validate_basis 改用 citations.has_citation 后：合法引用格式不再误杀、
  无任何引用仍报 error、依据 <20 字仍报 error、「无第X条」保持 warning；
- auto_correct：key_defect 超 200 字自动截断（字段级容错）；
- 140 条历史成功输出抽样回归：新引用口径下规则 error = 0。

历史样本来源：2026-11-05 缺口重跑 `/tmp/rerun_results.jsonl`（197 条记录 =
140 success / 57 failed，全量重跑结果见 spec A4 验收）。此处抽样覆盖每种引用
格式与边界（含 `GBT`、`SHT`、`T/CCSAS`、`〔YYYY〕N号`、仅条文号等真实写法）。
"""

from __future__ import annotations

import pytest

from app.modules.safety.ai_hazard_identification.citations import (
    CITATION_RE,
    PLACEHOLDER_BASIS_MARKERS,
    has_citation,
    is_placeholder_basis,
)
from app.modules.safety.ai_hazard_identification.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.schemas import (
    HazardCategoryEnum,
    HazardIdentificationInput,
    HazardIdentificationOutput,
    HazardLevelEnum,
    HazardTypeEnum,
    RectificationSuggestion,
)

# ═══════════════════════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════════════════════

VALID_OUTPUT_DICT = {
    "key_defect": "防爆电箱接线口未用堵头封堵，箱内积尘严重，存在爆炸风险",
    "hazard_type": "unsafe_condition",
    "hazard_category": "instrument_electrical",
    "hazard_level": "major",
    "rectification_suggestion": {
        "corrective": "立即加装防爆堵头，使用吸尘器清理箱内积尘，一周内排查全区域所有防爆电箱确保封堵完好",
        "preventive": "修订防爆设备巡检制度，将封堵检查纳入周检，建立防爆设备全生命周期台账",
    },
    "major_hazard_basis": (
        "《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准》第十条："
        "爆炸危险场所未按国家标准安装使用防爆电气设备；GB 3836.1-2010 第15章"
    ),
    "defect_substance": "substantive",
    "defect_substance_reasoning": "电箱引入口未封堵可直接导致粉尘进入电箱引发短路或爆炸（1步物理必然），推断链短且每步为物理必然，属实质缺陷",
}


def make_input(description: str = "防爆电箱堵头缺失") -> HazardIdentificationInput:
    return HazardIdentificationInput(description=description, department="生产部")


def make_output(**overrides: object) -> HazardIdentificationOutput:
    data = {**VALID_OUTPUT_DICT, **overrides}
    return HazardIdentificationOutput(**data)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# 1. citations 契约 & 引用判定
# ═══════════════════════════════════════════════════════════════════════════

# 表驱动：必须判为「有法规引用」的文本
CITATION_TEXTS = [
    # 书名号
    "《中华人民共和国安全生产法》第四十五条",
    "《消防法》第十六条",
    "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充",
    # 标准号：国标
    "GB 30871",
    "GB 30871-2022",
    "GB/T 38429.2-2019",
    "GB/T13861-2022",
    "GB 4053.3—2025",
    "GB50073-2013洁净厂房设计规范",
    "GB_T 18442.6-2019",
    # 标准号：行标/团标/地标（含 /T 与无斜杠 T、字母代号变体）
    "AQ 3025-2008",
    "AQ 3047-2013",
    "AQ/T 9007-2019",
    "AQ/T9007",
    "AQT 9007",
    "HG 30011-2013",
    "HG/T 20570.2-1995",
    "SH/T 3505-1999",
    "JGJT46-2024",
    "JGJ 46-2005",
    "TSG 21-2016",
    "TSG D7005-2018",
    "TSG T5002-2017",
    "TSG ZF001-2006",
    "DL 5027-2015",
    "DL/T 5027-2015",
    "JB/T 4730",
    "CJJ 51-2016",
    "CJJ/T 51-2016",
    "TCCSAS005-2019",
    "T/CCSAS 005-2019",
    "DB11/T 1234-2020",
    # 标准号的历史输出常见变体（无斜杠 T / 下划线 / 全角斜杠）
    "GBT 16483-2008",
    "SHT3097-2017",
    "SH∕T3007-2014",
    # 〔YYYY〕N号 / [YYYY]N号
    "安监总厅管三〔2014〕70号",
    "〔2023〕10号",
    "[2014]70号",
    # 条文号
    "第4.2.1条",
    "第5.2节",
    "第十条",
    "第一百零四条",
    "4.3条",
    "5.2 条",
]

# 表驱动：不得判为「有法规引用」的文本（避免把泛化表述当引用）
NO_CITATION_TEXTS = [
    "",
    "这是一个隐患，需要立即整改处理",
    "现场检查发现该处隐患问题较为严重，需要立即安排人员进行整改处理并复查确认",
    "符合要求，无需整改",
    "知识库中无相应条文，待人工补充",
    "知识库信息不足，待人工确认",
    # 只有标准前缀、无编号，不得判为引用
    "该企业执行 AQ 管理要求，但未给出具体标准编号",
]


class TestCitations:
    """citations.py 纯函数行为。"""

    def test_placeholder_markers_contract(self) -> None:
        """占位文案常量与历史重跑脚本口径一致（A3 质量闸门共用）。"""
        assert PLACEHOLDER_BASIS_MARKERS == (
            "知识库中无相应条文",
            "知识库信息不足",
        )

    def test_citation_re_is_pattern(self) -> None:
        """CITATION_RE 为可 search 的编译正则（A3/A4 唯一事实源）。"""
        assert hasattr(CITATION_RE, "search")

    @pytest.mark.parametrize("text", CITATION_TEXTS)
    def test_has_citation_true(self, text: str) -> None:
        assert has_citation(text) is True, f"应判为有引用: {text!r}"

    @pytest.mark.parametrize("text", NO_CITATION_TEXTS)
    def test_has_citation_false(self, text: str) -> None:
        assert has_citation(text) is False, f"不应判为有引用: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "知识库中无相应条文，待人工补充",
            "知识库信息不足，待人工确认",
            "判定依据：知识库中无相应条文，建议人工复核后补充",
            "知识库信息不足，无法给出判定依据",
        ],
    )
    def test_is_placeholder_basis_true(self, text: str) -> None:
        assert is_placeholder_basis(text) is True, f"应命中占位文案: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "《中华人民共和国安全生产法》第四十五条：生产经营单位必须为从业人员提供劳动防护用品",
            # 占位标记中间插入了书名号 → 与历史重跑口径一致，不算命中（凭引用判定兜底）
            "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充",
        ],
    )
    def test_is_placeholder_basis_false(self, text: str) -> None:
        assert is_placeholder_basis(text) is False, f"不应命中占位文案: {text!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. RuleEngine 判定依据口径
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleEngineBasis:
    """_validate_basis 与 A3 闸门同源（citations.has_citation）。"""

    def setup_method(self) -> None:
        self.engine = RuleEngine()

    @pytest.mark.parametrize(
        "basis",
        [
            "《安全生产法》第四十五条：生产经营单位必须为从业人员提供符合国家标准或行业标准的劳动防护用品，并监督、教育从业人员按照使用规则佩戴、使用",
            "GB 30871-2022 第5.2条：高处作业人员应正确佩戴符合国家标准的安全带，安全带应高挂低用",
            "JGJT46-2024 第4.2.1条：总开关电器的额定值、动作整定值应与分路开关电器的额定值、动作整定值相适应",
            "〔2014〕70号 4.3条：采购的易制毒化学品，其包装必须标明易制毒化学品的规范名称、化学分子式、成分和含量",
            "AQ 3047-2013 第3.2.5条：化学品作业场所安全警示标志应与化学品安全技术说明书的信息保持一致",
            "GB/T 13861-2022 第5.2.1条：生产过程中危险和有害因素应按导致事故的类别进行分类",
        ],
    )
    def test_basis_with_citation_passes(self, basis: str) -> None:
        result = self.engine.validate(make_input(), make_output(major_hazard_basis=basis))
        assert result.is_valid, f"合法引用仍被误杀: {result.errors}"

    def test_basis_without_citation_still_errors(self) -> None:
        basis = "现场检查发现该处隐患问题较为严重，需要立即安排人员进行整改处理并复查确认"
        result = self.engine.validate(make_input(), make_output(major_hazard_basis=basis))
        assert not result.is_valid
        assert any("法规" in e for e in result.errors)

    def test_basis_too_short_still_errors(self) -> None:
        result = self.engine.validate(
            make_input(), make_output(major_hazard_basis="这是一个很短的依据文本")
        )
        assert not result.is_valid
        assert any("过短" in e for e in result.errors)

    def test_missing_article_number_kept_as_warning(self) -> None:
        basis = (
            "GB 30871-2022 对特殊作业的管理要求：特殊作业审批手续应齐全、"
            "安全措施应全部落实、作业环境应符合安全要求"
        )
        result = self.engine.validate(make_input(), make_output(major_hazard_basis=basis))
        assert result.is_valid
        assert any("条文编号" in w for w in result.warnings)


# ═══════════════════════════════════════════════════════════════════════════
# 3. auto_correct：key_defect 超长截断
# ═══════════════════════════════════════════════════════════════════════════


def _unsafe_output_with_key_defect(key_defect: str) -> HazardIdentificationOutput:
    """绕过 schema max_length 构造超长输出（模拟 AI 原始输出超限场景）。"""
    data = {
        **VALID_OUTPUT_DICT,
        "key_defect": key_defect,
        "rectification_suggestion": RectificationSuggestion(
            **VALID_OUTPUT_DICT["rectification_suggestion"]  # type: ignore[arg-type]
        ),
    }
    return HazardIdentificationOutput.model_construct(**data)


class TestAutoCorrectKeyDefect:
    """A4 字段级容错：key_defect 超 200 字自动截断而非整条失败。"""

    def test_truncates_250_to_200(self) -> None:
        long_defect = "防" * 250
        corrected = auto_correct(_unsafe_output_with_key_defect(long_defect))
        assert len(corrected.key_defect) == 200
        assert corrected.key_defect == long_defect[:200]

    def test_keeps_exactly_200(self) -> None:
        exact = "防" * 200
        corrected = auto_correct(_unsafe_output_with_key_defect(exact))
        assert corrected.key_defect == exact

    def test_short_defect_untouched(self) -> None:
        corrected = auto_correct(_unsafe_output_with_key_defect("防爆堵头缺失"))
        assert corrected.key_defect == "防爆堵头缺失"


# ═══════════════════════════════════════════════════════════════════════════
# 4. 140 条历史成功输出抽样回归（新引用口径下规则 error = 0）
# ═══════════════════════════════════════════════════════════════════════════

# 2026-11-05 重跑窗口 140 条 success 的 major_hazard_basis 抽样（原样摘录）。
HISTORICAL_SUCCESS_BASIS_SAMPLES = [
    # 标准号 + 条文号（GB 空格 / GB/T / 全角破折号）
    "GB/T 30000.31-2023 第5.1条：'化学品作业场所警示性标志正文应使用简洁、明了、易于理解、规范的中文表述,正文内容应保持与化学品安全技术说明书的信息一致。'；GB 15258-2009 第5.1条：'标签正文应使用简捷、明了，易于理解、规范的汉字表述'",
    "GB 4053.3—2025 第4.6.5条：'安装后的平台板应平整且固定牢固，平台和防护栏杆均不应有歪斜、扭曲、变形及其他缺陷。'；GB 4053.3—2025 第4.7.1条：'平台及防护栏杆的构件应根据使用环境、设计工作年限、材料耐腐蚀性能，采取防腐蚀措施，防腐蚀设计应符合GB/T 50046的规定，防腐蚀涂装应符合GB/T 51082的规定。'",
    "GB 50457-2019第11.2.3条：'医药洁净室内的照明灯具可采用吸顶明装或嵌入顶棚安装的方式，灯具与顶棚之间应密封可靠，密封材料应能耐受洁净室的日常清洁和消毒。灯具的检修和更换应避免对洁净室环境造成不利影响。'；GB 50457-2019第11.2.2条：'药品生产区内应选用外部造型简单、密封良好、表面易于清洁消毒的照明灯具。'",
    # 书名号 + 数字章节
    "《中国制药工业EHS指南（2016版）》5.5.5：剧毒、易制爆化学品管理企业应严格执行“五双制度”……建立领用审批制度和可追踪的使用台帐。《易制爆危险化学品治安管理办法》第十四条：危险化学品生产企业、经营企业销售易制爆危险化学品，应当如实记录购买单位的名称、地址、经办人姓名、身份证号码以及所购买的易制爆危险化学品的品种、数量、用途。",
    # 方括号包裹标准名（历史输出常见写法）
    "[AQ 3047-2013 化学品作业场所安全警示标志规范]第3.2.5条：'简要概述化学品的危险特性。根据GB20576～GB20599、GB20601～GB20602，选择不同类别危险化学品的危险性说明，要求醒目、清晰。'；[AQ 3047-2013 化学品作业场所安全警示标志规范]第4.1条：'化学品作业场所安全警示标志应与化学品安全技术说明书的信息保持一致，要不断补充信息资料，若发现新的危险性，及时作出更新。'",
    "[附件2-1 《医药研发实验室危险化学品安全管理规范》]A.1.2：'未使用的实验室耗材、物品等均已得到有效清理或退库。'；[TCCSAS005-2019 化学化工实验室安全管理规范]9.7.7：'高温电器如高温马弗炉、电热烘箱等不得放置在木质或合成材料桌面上，并在电器明显处应有“高温”“防烫”“触电危险”等标识牌。'",
    # GBT / SHT 无斜杠变体（新引用口径必须覆盖，否则历史成功样本会误杀）
    "[GBT 16483-2008 化学品安全技术说明书 内容和项目顺序] A．2第1部分——化学品及企业标识：'主要标明化学品的名称，该名称应与安全标签上的名称一致'",
    "[SHT3097-2017_石油化工静电接地设计规范]5.1.9：'与地绝缘的金属部件（如法兰、胶管接头、喷嘴等），应采用铜芯软绞线跨接引出接地。'；[SHT3097-2017_石油化工静电接地设计规范]4.1.2：'需要接地的物体因疏忽而未进行接地，往往容易成为产生静电接地故障甚至静电危害的原因。'",
    # 年号文 + 数字条文号
    "[安监总厅管三〔2014〕70号 国家安全监管总局办公厅关于印发企业非药品类易制毒化学品规范化管理指南的通知]4.3条：'采购的易制毒化学品，其包装必须标明易制毒化学品的规范名称、化学分子式、成分和含量'；5.4条：'建立易制毒化学品出入库管理制度。须凭出入库单据（参见附件3、附件4）办理出入库，查验出入库易制毒化学品品种和数量，履行出入库签收手续'",
    # 仅中文条文号（无书名号/标准号）
    "[易制爆危险化学品治安管理办法]第二十八条：'易制爆危险化学品从业单位应当建立易制爆危险化学品出入库检查、登记制度，定期核对易制爆危险化学品存放情况。'；[中华人民共和国危险化学品安全法]第一百零四条：'生产、储存、使用剧毒化学品、易制爆危险化学品的单位不如实记录其生产、储存、使用的剧毒化学品、易制爆危险化学品的品种、数量、流向'由公安机关责令限期改正并处罚款。",
    # 历史成功样本中「知识库中无《…》相应条文」写法（占位标记被书名号打断 → 由引用判定兜底通过）
    "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充",
]


class TestHistoricalSuccessRegression:
    """140 条历史成功样本抽样：新引用口径下规则 error = 0（A4 验收）。"""

    def setup_method(self) -> None:
        self.engine = RuleEngine()

    @pytest.mark.parametrize(
        "basis",
        HISTORICAL_SUCCESS_BASIS_SAMPLES,
        ids=[f"sample-{i}" for i in range(len(HISTORICAL_SUCCESS_BASIS_SAMPLES))],
    )
    def test_history_success_has_no_rule_errors(self, basis: str) -> None:
        result = self.engine.validate(make_input(), make_output(major_hazard_basis=basis))
        assert result.errors == [], f"历史成功样本被新规则误杀: {result.errors}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. 与既有 test_plugin 规则用例口径一致的冒烟：合法完整输出仍通过
# ═══════════════════════════════════════════════════════════════════════════


def test_valid_output_passes_rule_engine() -> None:
    result = RuleEngine().validate(make_input(), make_output())
    assert result.is_valid, result.errors


# 枚举引用（保证测试数据与 schema 枚举同步，避免未来枚举改动后静默失真）
def test_fixture_enums_are_canonical() -> None:
    output = make_output()
    assert output.hazard_type == HazardTypeEnum.UNSAFE_CONDITION
    assert output.hazard_category == HazardCategoryEnum.INSTRUMENT_ELECTRICAL
    assert output.hazard_level == HazardLevelEnum.MAJOR
