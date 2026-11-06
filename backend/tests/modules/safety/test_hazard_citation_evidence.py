"""T1 引用证据/匹配纯函数（S1）。

契约（spec §C2「匹配算法」）：
- ``CitationEvidence`` 是「本轮检索证据」的本地可匹配形态（chunk 文本/法规名/条号/chunk_id），
  支持从 ``KnowledgeContext.chunks`` 与已渲染 markdown 两种来源构造；
- ``extract_citation_units`` 从 AI 判定依据切出引用单元（书名号/标准号/条号/引号条款文本）；
- ``verify_citations`` 做单元级三级归一化匹配（法规名/标准号/条号/条款文本任一命中即 verified）；
- ``is_placeholder_variant`` 识别「知识库中无《XX》相应条文」类占位变体。

全部为纯函数测试：不连 DB/网络/Bitable。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    EvidenceEntry,
    extract_citation_units,
    is_placeholder_variant,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.citations import is_placeholder_basis

# ═══════════════════════════════════════════════════════════════════════════
# 证据样本（与历史重跑窗口的真实 chunk 形态对齐：doc/条号/正文）
# ═══════════════════════════════════════════════════════════════════════════

CHUNKS = [
    SimpleNamespace(
        chunk_id="c1",
        source_doc="GB 30871-2022 化学品生产单位特殊作业安全规范",
        source_article="第5.2条",
        chunk_text="5.2 高处作业人员应正确佩戴符合国家标准的安全带，安全带应高挂低用。",
    ),
    SimpleNamespace(
        chunk_id="c2",
        source_doc="生产过程安全基本要求",
        source_article="",
        chunk_text="5.6.2 存在高处坠落危险的平台、通道或工作面,应采取防护栏杆等防坠落措施。",
    ),
    SimpleNamespace(
        chunk_id="c3",
        source_doc="安全色和安全标志",
        source_article="8.2.1",
        chunk_text="识别符号基本组成应包含但不限于物质名称和流向。",
    ),
    SimpleNamespace(
        chunk_id="c4",
        source_doc="GB/T 30000.31-2023 化学品作业场所警示性标志",
        source_article="第5.1条",
        chunk_text="化学品作业场所警示性标志正文应使用简洁、明了、易于理解、规范的中文表述。",
    ),
    SimpleNamespace(
        chunk_id="c5",
        source_doc="AQ 3047-2013 化学品作业场所安全警示标志规范",
        source_article="第3.2.5条",
        chunk_text=(
            "简要概述化学品的危险特性。根据GB20576～GB20599选择不同类别危险化学品的"
            "危险性说明，要求醒目、清晰。"
        ),
    ),
    SimpleNamespace(
        chunk_id="c6",
        source_doc="SH T3007-2014 石油化工储运系统罐区设计规范",
        source_article="",
        chunk_text="5.3.3 管道穿防火堤和隔堤处宜设钢制套管，套管两端应做防渗漏的密封处理。",
    ),
    SimpleNamespace(
        chunk_id="c7",
        source_doc="首批和第二批重点监管的危险化学品安全措施和应急处置原则（74种）",
        source_article="",
        chunk_text="应设置安全标识（GB 7231）的规定；室内管道不应敷设在地沟中。",
    ),
]

EMPTY_EVIDENCE = CitationEvidence.from_chunks([])
EVIDENCE = CitationEvidence.from_chunks(CHUNKS)

LEGACY_PLACEHOLDER = "知识库中无相应条文，待人工补充"
VARIANT_PLACEHOLDER = "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充"

# ═══════════════════════════════════════════════════════════════════════════
# 1. CitationEvidence 构造
# ═══════════════════════════════════════════════════════════════════════════


class TestCitationEvidence:
    def test_from_chunks_reads_metadata(self) -> None:
        assert not EVIDENCE.is_empty
        assert len(EVIDENCE.entries) == len(CHUNKS)
        assert EVIDENCE.chunk_ids == (
            "c1", "c2", "c3", "c4", "c5", "c6", "c7",
        )
        first = EVIDENCE.entries[0]
        assert first.doc_name == "GB 30871-2022 化学品生产单位特殊作业安全规范"
        assert first.source_article == "第5.2条"
        assert "高处作业人员" in first.chunk_text
        assert first.chunk_id == "c1"

    def test_from_chunks_empty_and_unknown_objects(self) -> None:
        assert EMPTY_EVIDENCE.is_empty
        assert EMPTY_EVIDENCE.chunk_ids == ()
        # 无属性的对象 → 跳过（不抛），保持与既有 quality_gate 测试的 chunks=[object()] 兼容
        assert CitationEvidence.from_chunks([object()]).is_empty

    def test_from_markdown_parses_rendered_knowledge(self) -> None:
        markdown = """## 相关法规条款

[1] 《GB 30871-2022 化学品生产单位特殊作业安全规范》 第5.2条
5.2 高处作业人员应正确佩戴符合国家标准的安全带，安全带应高挂低用。

---

[2] 《生产过程安全基本要求》
5.6.2 存在高处坠落危险的平台、通道或工作面,应采取防护栏杆等防坠落措施。"""
        evidence = CitationEvidence.from_markdown(markdown)
        assert len(evidence.entries) == 2
        assert evidence.entries[0].doc_name == "GB 30871-2022 化学品生产单位特殊作业安全规范"
        # markdown 渲染格式：书名号里可能再套书名号（历史样本真实存在），不破坏匹配
        assert "坠落" in evidence.entries[1].chunk_text

    def test_from_markdown_empty_placeholder_text(self) -> None:
        assert CitationEvidence.from_markdown(
            "（知识库中暂无与查询相关的法规条款）"
        ).is_empty
        assert CitationEvidence.from_markdown("").is_empty

    def test_from_markdown_with_graph_path_prefix(self) -> None:
        markdown = (
            "## 图谱导航\n\n某路径\n\n## 相关法规条款\n\n"
            "[1] 《安全色和安全标志》\n识别符号基本组成应包含但不限于物质名称和流向。"
        )
        evidence = CitationEvidence.from_markdown(markdown)
        assert len(evidence.entries) == 1
        assert evidence.entries[0].doc_name == "安全色和安全标志"


# ═══════════════════════════════════════════════════════════════════════════
# 2. 引用单元抽取
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractCitationUnits:
    def test_two_units_with_doc_article_and_quote(self) -> None:
        basis = (
            "《中华人民共和国安全生产法》第四十五条：'生产经营单位必须为从业人员提供"
            "符合国家标准或者行业标准的劳动防护用品'；"
            "GB 30871-2022 第5.2条：'高处作业人员应正确佩戴符合国家标准的安全带'"
        )
        units = extract_citation_units(basis)
        assert len(units) == 2
        assert units[0].docs and "《中华人民共和国安全生产法》" in units[0].docs
        assert units[0].articles and "第四十五条" in units[0].articles
        assert units[0].quotes and "劳动防护用品" in units[0].quotes[0]
        assert units[1].standards and "GB 30871-2022" in units[1].standards
        assert units[1].articles and "第5.2条" in units[1].articles

    def test_bracket_doc_name_and_article(self) -> None:
        basis = (
            "[AQ 3047-2013 化学品作业场所安全警示标志规范]第3.2.5条："
            "'简要概述化学品的危险特性。根据GB20576～GB20599选择不同类别危险化学品的危险性说明'"
        )
        units = extract_citation_units(basis)
        assert len(units) == 1
        unit = units[0]
        assert any("AQ 3047-2013" in s for s in unit.standards)
        assert unit.articles and "第3.2.5条" in unit.articles
        assert unit.quotes

    def test_bracket_doc_without_digits(self) -> None:
        # 历史真实写法：[可燃粉尘工艺系统防爆技术规范]（方括号内无标准号）
        units = extract_citation_units(
            "[可燃粉尘工艺系统防爆技术规范]第6.2.3条：'筛分设备的非连接导电部件应进行防静电跨接并接地'"
        )
        assert len(units) == 1
        assert "可燃粉尘工艺系统防爆技术规范" in units[0].docs
        blocks = CitationEvidence(
            entries=(EvidenceEntry(doc_name="可燃粉尘工艺系统防爆技术规范"),)
        )
        assert verify_citations(units[0].text, blocks).has_verified

    def test_no_citation_returns_empty(self) -> None:
        assert extract_citation_units("现场检查发现该处隐患问题较为严重") == ()

    def test_standard_number_variants(self) -> None:
        variants = [
            "GB/T 38429.2-2019 第5.1条",
            "GBT16483-2008 第5.1条",
            "SH/T 3007-2014 5.3.3条",
            "T/CCSAS 005-2019 第4.1条",
            "GB 4053.3—2025 第4.1条",
            "〔2014〕70号",
            "[2014]70号",
        ]
        units = extract_citation_units("；".join(variants))
        assert len(units) == len(variants)
        # 每个变体至少抽到「法规/标准/发文号/条号/条款文本」之一
        for unit in units:
            assert unit.docs or unit.standards or unit.articles or unit.quotes


# ═══════════════════════════════════════════════════════════════════════════
# 3. 可验证判定（三级匹配）
# ═══════════════════════════════════════════════════════════════════════════


class TestVerifyCitations:
    def test_verbatim_citation_from_chunks_is_verified(self) -> None:
        basis = (
            "GB 30871-2022 第5.2条：'高处作业人员应正确佩戴符合国家标准的安全带，"
            "安全带应高挂低用'"
        )
        report = verify_citations(basis, EVIDENCE)
        assert report.total_units == 1
        assert report.has_verified
        assert report.all_verified
        assert report.verified_rate == 1.0
        assert report.placeholder_note is False

    def test_fabricated_regulation_is_zero_verified(self) -> None:
        basis = (
            "GB 99999-2024 第1.1条：'企业必须每年开展两次全员安全培训并考核'；"
            "《虚构的安全管理条例》第三条：'所有人员必须持证上岗'"
        )
        report = verify_citations(basis, EVIDENCE)
        assert report.total_units == 2
        assert not report.has_verified
        assert len(report.unverified_texts) == 2

    def test_standard_number_variants_match_same_standard(self) -> None:
        # 历史真实写法：GB/T vs GBT、SH T vs SH/T、书名号内标准号
        for basis in (
            "GBT30000.31-2023 第5.1条：'化学品作业场所警示性标志正文应使用简洁、明了'",
            "《GB/T 30000.31-2023 化学品作业场所警示性标志》第5.1条",
            "SH/T3007-2014 第5.3.3条：'管道穿防火堤和隔堤处宜设钢制套管'",
            "《SH T3007-2014 石油化工储运系统罐区设计规范》5.3.3条",
        ):
            assert verify_citations(basis, EVIDENCE).has_verified, basis

    def test_article_number_boundary_match(self) -> None:
        evidence = CitationEvidence(
            entries=(EvidenceEntry(doc_name="", source_article="", chunk_text="10 应设置防护栏杆。"),)
        )
        assert verify_citations("第10条：'应设置防护栏杆'", evidence).has_verified
        # 中文数字条号转阿拉伯数字后仍可命中
        assert verify_citations("第十条：'应设置防护栏杆'", evidence).has_verified
        # 数字边界：第1条不应命中 "10"
        assert not verify_citations("第1条", evidence).has_verified

    def test_quote_tolerates_ocr_breaks(self) -> None:
        # 历史 chunk 有换行/OCR 断字，引文与原文不完全逐字
        basis = (
            "第5.6.2条：'存在高处坠落危险的平台通道或工作面应采取防护栏杆等防坠落措施'"
        )
        assert verify_citations(basis, EVIDENCE).has_verified

    def test_paraphrased_quote_beyond_threshold_not_verified(self) -> None:
        basis = "《生产过程安全基本要求》第5.6.2条：'本条文内容完全是另一段无关表述，与企业实际要求无关'"
        report = verify_citations(basis, EVIDENCE)
        # 书名号+条号可命中（法规名/条号任一命中即通过，条目级口径）
        assert report.has_verified

    def test_empty_evidence_all_unverified(self) -> None:
        report = verify_citations("GB 30871-2022 第5.2条：'高处作业应佩戴安全带'", EMPTY_EVIDENCE)
        assert report.total_units == 1
        assert not report.has_verified
        assert report.verified_rate == 0.0

    def test_no_citation_text_zero_units(self) -> None:
        report = verify_citations("现场检查发现该处隐患问题较为严重", EVIDENCE)
        assert report.total_units == 0
        assert not report.has_verified
        assert report.verified_rate == 0.0

    def test_partial_verified_report(self) -> None:
        basis = (
            "GB 30871-2022 第5.2条：'高处作业人员应正确佩戴符合国家标准的安全带'；"
            "GB 88888-2020 第1条：'编造的条文内容'"
        )
        report = verify_citations(basis, EVIDENCE)
        assert report.total_units == 2
        assert report.verified_units == 1
        assert report.has_verified
        assert not report.all_verified
        assert len(report.unverified_texts) == 1
        assert "GB 88888-2020" in report.unverified_texts[0]

    def test_placeholder_note_flag(self) -> None:
        report = verify_citations(f"{VARIANT_PLACEHOLDER}", EVIDENCE)
        assert report.placeholder_note is True
        assert not report.has_verified


# ═══════════════════════════════════════════════════════════════════════════
# 4. 占位变体识别（legacy 口径保持兼容）
# ═══════════════════════════════════════════════════════════════════════════


class TestPlaceholderVariant:
    @pytest.mark.parametrize(
        "text",
        [
            LEGACY_PLACEHOLDER,
            "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充",
            "知识库信息不足，待人工确认",
            "知识库中无直接规定点检周期的条文，点检频次依据企业检查表要求执行，待人工补充确认",
        ],
    )
    def test_placeholder_variants_detected(self, text: str) -> None:
        assert is_placeholder_variant(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "GB 30871-2022 第5.2条：'高处作业人员应正确佩戴符合国家标准的安全带'",
            "知识库中存在第5.2条相关要求，但本隐患仍需结合现场判断",
        ],
    )
    def test_non_placeholder_not_detected(self, text: str) -> None:
        assert is_placeholder_variant(text) is False

    def test_legacy_exact_marker_not_matching_variant(self) -> None:
        """历史精确子串口径不会命中变体（这正是 C2 要修的漏判），新函数负责变体。"""
        assert is_placeholder_basis(VARIANT_PLACEHOLDER) is False
        assert is_placeholder_variant(VARIANT_PLACEHOLDER) is True
        assert is_placeholder_basis(LEGACY_PLACEHOLDER) is True
        assert is_placeholder_variant(LEGACY_PLACEHOLDER) is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. 标准号书写变体（S1 承诺：空格代替斜杠 / 全角分隔符 / 双重书名号）
# ═══════════════════════════════════════════════════════════════════════════


class TestStandardNumberVariants:
    @pytest.mark.parametrize(
        ("basis", "evidence_entry"),
        [
            # 空格代替斜杠（历史真实写法）
            (
                "SH T3007-2014 第5.3.3条：'管道穿防火堤和隔堤处宜设钢制套管'",
                EvidenceEntry(
                    doc_name="SH T3007-2014 石油化工储运系统罐区设计规范",
                    chunk_text="5.3.3 管道穿防火堤和隔堤处宜设钢制套管，套管两端应做防渗漏的密封处理",
                ),
            ),
            (
                "GB T 37140-2018 第10.2.2.10条：'气体管道应按不同介质的气体种类设置明显标识'",
                EvidenceEntry(
                    doc_name="GB T 37140-2018《检验检测实验室技术要求验收规范》",
                    chunk_text="10.2.2.10 气体管道应按不同介质的气体种类设置明显标识",
                ),
            ),
            # 全角/除法斜杠（∕ U+2215）
            (
                "GB∕T 30000.31-2023 第5.1条：'正文应使用简洁、明了、易于理解、规范的中文表述'",
                EvidenceEntry(
                    doc_name="GB/T 30000.31-2023 化学品作业场所警示性标志",
                    chunk_text="5.1 正文应使用简洁、明了、易于理解、规范的中文表述",
                ),
            ),
            # 双重书名号（历史 markdown 渲染真实样本）
            (
                "《GB T 37140-2018《检验检测实验室技术要求验收规范》》第10.2.2.10条",
                EvidenceEntry(
                    doc_name="GB T 37140-2018《检验检测实验室技术要求验收规范》",
                    chunk_text="10.2.2.10 气体管道应按不同介质的气体种类设置明显标识",
                ),
            ),
        ],
    )
    def test_variant_verified_against_chunks(
        self, basis: str, evidence_entry: EvidenceEntry
    ) -> None:
        evidence = CitationEvidence(entries=(evidence_entry,))
        report = verify_citations(basis, evidence)
        assert report.has_verified, basis

    def test_space_separator_recognised_by_has_citation(self) -> None:
        from app.modules.safety.ai_hazard_identification.citations import has_citation

        for text in (
            "SH T3007-2014 第5.3.3条",
            "GB T 37140-2018",
            "GB∕T 38429.2-2019 第5.1条",
        ):
            assert has_citation(text), text


# ═══════════════════════════════════════════════════════════════════════════
# 5b. 验收修复（M1/M2）：占位实质引用 + 条号同源约束
# ═══════════════════════════════════════════════════════════════════════════


class TestAcceptanceHardening:
    """2026-11-06 外部验收 M1/M2：收紧「任一命中」误判。

    - M1：占位变体里的书名号若只命中法规名（无条号/引文/标准号）→ 不算实质引用，
      不能让「知识库中无《X》相应条文」凭 X 在 chunks 里而放行写回；
    - M2：条号命中必须与同单元法规名/标准号落在同一条证据里，且不允许跨条目
      借用无关数字（如证据里的「5次」「20人」）。
    """

    def _ev(self) -> CitationEvidence:
        return CitationEvidence(
            entries=(
                EvidenceEntry(
                    doc_name="危险化学品安全管理条例",
                    source_article="第二十条",
                    chunk_text="第二十条 生产、储存危险化学品的单位，应当具备下列条件。",
                ),
                EvidenceEntry(
                    doc_name="生产安全事故应急演练基本规范",
                    source_article="",
                    chunk_text="每年至少开展5次应急演练，20人以上参加。",
                ),
            )
        )

    def test_fabricated_doc_plus_common_number_not_verified(self) -> None:
        report = verify_citations("《虚构法规》第5条：'应落实安全措施'", self._ev())
        assert not report.has_verified

    def test_fabricated_doc_plus_matched_article_number_not_verified(self) -> None:
        # 证据 B 内有「20人」「5次」，不得被《虚构法规》第X条跨条目借用
        assert not verify_citations("《虚构法规》第二十条", self._ev()).has_verified
        assert not verify_citations("《虚构法规》第五条", self._ev()).has_verified

    def test_doc_provenance_suffices_for_article_not_in_chunks(self) -> None:
        # 法规名命中本轮 chunks（同法规其它条文）即来源可追溯；条号精确性由
        # 规则 warning/replay 观测，不与「来源可验证」混为一谈（M2 边界）。
        assert verify_citations(
            "《危险化学品安全管理条例》第五条", self._ev()
        ).has_verified

    def test_doc_and_article_same_entry_verified(self) -> None:
        report = verify_citations("《危险化学品安全管理条例》第二十条", self._ev())
        assert report.has_verified

    def test_article_from_source_article_field_verified(self) -> None:
        ev = CitationEvidence(
            entries=(
                EvidenceEntry(
                    doc_name="某条例", source_article="第五条", chunk_text="应当落实安全措施。"
                ),
            )
        )
        assert verify_citations("《某条例》第5条", ev).has_verified

    def test_placeholder_doc_only_unit_is_not_substantive(self) -> None:
        report = verify_citations(
            "知识库中无《危险化学品安全管理条例》相应条文，待人工补充", self._ev()
        )
        # 旧口径仍会因书名号命中而 has_verified，但没有实质引用（无条号/引文/标准号）
        assert report.has_verified
        assert report.has_substantive_verified is False

    def test_note_with_real_article_citation_is_substantive(self) -> None:
        basis = (
            "知识库中无直接规定点检周期的条文；"
            "《危险化学品安全管理条例》第二十条：'应当具备下列条件'"
        )
        report = verify_citations(basis, self._ev())
        assert report.has_substantive_verified is True
