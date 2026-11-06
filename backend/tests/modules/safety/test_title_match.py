"""title_match 归一化标题匹配单元测试（2026-11-06 阻火器引用事故）。

事故中同一部法规在三处命名各不相同（ragplus 前缀名 / 表内标题 / 正文
书名号+号在外），精确全等全部失配。此处锁定双键（标准号+归一化名称）
匹配行为。
"""

from __future__ import annotations

from app.modules.safety.knowledge.title_match import (
    extract_std_key,
    normalize_name,
    titles_match,
)


class TestExtractStdKey:
    def test_std_with_year_and_slash(self) -> None:
        assert extract_std_key("GB/T 20801.6-2006 压力管道规范") == "GBT20801.6"

    def test_std_prefix_underscore(self) -> None:
        assert extract_std_key("GB50160-2008_石油化工企业设计防火标准") == "GB50160"

    def test_std_outside_book_title(self) -> None:
        # 正文格式：标准号在书名号外（锚文本拼接后的形态）
        assert extract_std_key("石油化工企业设计防火标准GB 50160-2008") == "GB50160"

    def test_std_without_year(self) -> None:
        assert extract_std_key("阻火器-gb5908") == "GB5908"
        assert extract_std_key("《阻火器》GB 5908") == "GB5908"

    def test_year_insensitive(self) -> None:
        assert extract_std_key("GB 50016-2014") == extract_std_key("GB50016-2025")

    def test_body_fragment_not_matched(self) -> None:
        # 正文碎片（分册号/分级代号）不得误命中标准号
        assert extract_std_key("第6部分") == ""
        assert extract_std_key("IIIA1～IIC 七级") == ""
        assert extract_std_key("压降≤0.3kPa") == ""

    def test_empty(self) -> None:
        assert extract_std_key("") == ""
        assert extract_std_key("石油化工企业设计防火标准") == ""

    def test_unicode_slash(self) -> None:
        # 知识库存在 U+2215 除号斜杠（SH∕T3007），须归一为 ASCII 斜杠再提取
        assert extract_std_key("SH∕T3007-2014石油化工储运系统罐区设计规范") == "SHT3007"
        assert titles_match("SH/T 3007-2014 储运系统罐区设计规范", "SH∕T3007-2014石油化工储运系统罐区设计规范")


class TestNormalizeName:
    def test_prefix_stripped(self) -> None:
        assert (
            normalize_name("GB50160-2008_石油化工企业设计防火标准")
            == normalize_name("石油化工企业设计防火标准")
            == "石油化工企业设计防火标准"
        )

    def test_brackets_and_spaces_removed(self) -> None:
        assert normalize_name("《阻火器》GB 5908") == "阻火器"


class TestTitlesMatch:
    def test_prefix_vs_plain(self) -> None:
        assert titles_match(
            "GB50160-2008_石油化工企业设计防火标准", "石油化工企业设计防火标准"
        )

    def test_anchor_vs_kb_title(self) -> None:
        # 正文锚文本（名称+号在外）vs knowledge_articles 标题（号+书名号）
        assert titles_match(
            "压力管道规范 工业管道 第6部分 安全防护GB/T 20801.6-2006",
            "GBT20801.6-2006《压力管道规范 工业管道 第6部分安全防护》",
        )

    def test_no_year_std(self) -> None:
        assert titles_match("阻火器-gb5908", "《阻火器》GB 5908")

    def test_same_std_different_editions_match(self) -> None:
        # 同号不同年份视为同部（链接指向任一版可接受）
        assert titles_match(
            "GB 50016-2014 建筑设计防火规范", "《建筑设计防火规范》GB 50016-2025"
        )

    def test_guide_not_confused_with_standard(self) -> None:
        # 实施指南（2020801）≠ 原标准（20801.6）：标准号不等即不匹配
        assert not titles_match(
            "GBT2020801-2006《压力管道规范-工业管道》实施指南",
            "GBT20801.6-2006《压力管道规范 工业管道 第6部分安全防护》",
        )

    def test_different_docs_dont_match(self) -> None:
        assert not titles_match(
            "油品罐区安全管理规范（征求意见稿）", "石油化工储运系统设计规范"
        )

    def test_containment_round(self) -> None:
        # 互含轮：短边 ≥4 字符才允许
        assert titles_match("建筑设计防火规范", "GB50016-2014《建筑设计防火规范》(2018年版)")
        assert not titles_match("规范", "建筑设计防火规范")

    def test_strict_round_rejects_containment(self) -> None:
        assert not titles_match(
            "建筑设计防火规范", "GB50016-2014《建筑设计防火规范》(2018年版)",
            containment=False,
        )
