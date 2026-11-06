"""参考法规编号契约回归测试（2026-10-30 引用错乱事故）。

事故：正文 [N] 与卡片「📚 参考法规」列表错位——
  - RAG SYSTEM_PROMPT 曾允许按正文出现顺序重排编号；
  - 飞书卡片构建器按「正文 [N] = sources[N-1]」提取后再重编号，
    两套假设叠加后参考栏列出了与正文完全无关的文档。

契约（修复后）：
  1. 正文 [N] 锚定检索上下文编号 == sources 数组顺序（prompt/工具 docstring 锚定）；
  2. 卡片只做 [N] → sources[N-1] 映射，禁止重编号；
  3. SYSTEM_PROMPT 必须包含锚定规则与「区块外标准不得标号」禁令。
"""

from __future__ import annotations

from app.modules.safety.feishu.business_agent_bot_handler import _build_reply_card
from app.modules.safety.knowledge.query_service import SYSTEM_PROMPT


_SOURCES = [
    {"doc_title": f"文档{i}", "feishu_url": f"https://example.com/{i}"}
    for i in range(1, 7)  # 6 篇，编号 [1]~[6]
]


def _card_markdown(card: dict) -> str:
    parts = [e["content"] for e in card["body"]["elements"] if e.get("tag") == "markdown"]
    return "\n".join(parts)


def test_body_numbers_map_to_sources_without_renumber() -> None:
    """正文引用 [2][5] → 参考栏按原编号列出 sources[1]/sources[4]，不改写成 [1][2]。"""
    answer = "根据《文档2》[2] 与《文档5》[5] 的要求执行。"
    card = _build_reply_card(answer, _SOURCES)
    md = _card_markdown(card)
    assert "**[2] 文档2**" in md
    assert "**[5] 文档5**" in md
    assert "[1] 文档1" not in md  # 未被引用的不得出现
    # 正文编号保持原样（不得被重写为 [1][2]）
    assert "《文档2》[2]" in md and "《文档5》[5]" in md
    assert "《文档2》[1]" not in md


def test_citation_order_preserved_ascending() -> None:
    """参考栏按编号升序排列，与正文出现顺序无关。"""
    answer = "先说《文档4》[4]，再说《文档2》[2]。"
    card = _build_reply_card(answer, _SOURCES)
    md = _card_markdown(card)
    assert md.index("**[2] 文档2**") < md.index("**[4] 文档4**")


def test_out_of_range_citation_ignored() -> None:
    """超出 sources 数量的编号（如 6 篇时标 [9]）不进参考栏、不炸。"""
    answer = "《文档1》[1] 和某标准 [9] 的内容。"
    card = _build_reply_card(answer, _SOURCES)
    md = _card_markdown(card)
    assert "**[1] 文档1**" in md
    assert "[9]" not in md.split("参考法规")[-1]


def test_no_citation_no_reference_section() -> None:
    """正文无 [N] → 不渲染参考法规栏。"""
    card = _build_reply_card("知识库中未收录该标准。", _SOURCES)
    assert "参考法规" not in _card_markdown(card)


def test_dedupe_sources_by_title() -> None:
    """同名 source 去重后按首个位置参与映射。"""
    dup_sources = _SOURCES + [{"doc_title": "文档2", "feishu_url": "x"}]
    answer = "引用《文档2》[2]。"
    card = _build_reply_card(answer, dup_sources)
    md = _card_markdown(card)
    assert md.count("**[2] 文档2**") == 1


def test_system_prompt_anchors_numbering() -> None:
    """SYSTEM_PROMPT 必须锚定编号契约：禁止重编号、禁止给区块外标准标号。"""
    assert "禁止" in SYSTEM_PROMPT and "重新编号" in SYSTEM_PROMPT
    assert "「参考法规」区块" in SYSTEM_PROMPT
    # 区块外标准（引用清单中提及的 SH/T 等）不得标 [N]
    assert "规范性引用" in SYSTEM_PROMPT
    assert "区块之外的任何标准" in SYSTEM_PROMPT


# ── 2026-11-06 阻火器引用事故（多调用编号冲突 + 截断丢 sources + 标题前缀错位）──


# 模拟两次 knowledge_search 合并后的 sources（顺序=调用顺序：call_01 幸存者在前）
_INCIDENT_SOURCES = [
    {"doc_title": "GB50160-2008_石油化工企业设计防火标准",
     "feishu_url": "https://feishu.example/gb50160"},
    {"doc_title": "GBT20801.6-2006《压力管道规范 工业管道 第6部分安全防护》",
     "feishu_url": "https://feishu.example/20801"},
    {"doc_title": "阻火器-gb5908", "feishu_url": "https://feishu.example/gb5908"},
    {"doc_title": "油品罐区安全管理规范（征求意见稿）", "feishu_url": ""},
]

# 模型合并转述后全局重编号（[1]-[3] 来自 call_00、[4] 是 call_01 的 [1] 重编）
_INCIDENT_ANSWER = (
    "| 《压力管道规范 工业管道 第6部分 安全防护》GB/T 20801.6-2006 [1] | 5.1.1 | … |\n"
    "| 同上 [1] | 5.1.2 | … |\n"
    "| 《阻火器》GB 5908（知识库中为草案/报批稿文本）[2] | 4.3 | … |\n"
    "| 《油品罐区安全管理规范（征求意见稿）》[3] | — | … |\n"
    "| 《石油化工企业设计防火标准》GB 50160-2008 [4] | — | 未收录正文 |"
)


def test_multi_call_renumbered_citations_anchor_by_title() -> None:
    """事故主场景：模型跨两次检索全局重编号后，参考栏按文档名锚定仍正确。"""
    card = _build_reply_card(_INCIDENT_ANSWER, _INCIDENT_SOURCES)
    md = _card_markdown(card)
    # [1] → 压力管道规范（不是位置映射的 GB50160！）
    assert "**[1] GBT20801.6-2006《压力管道规范 工业管道 第6部分安全防护》**" in md
    assert "href='https://feishu.example/20801'" in md
    # [4] → GB50160（标题带前缀也能锚定），且带链接
    assert "**[4] GB50160-2008_石油化工企业设计防火标准**" in md
    assert "href='https://feishu.example/gb50160'" in md
    # [2] 无年份标准号；[3] 无 URL 不渲染链接
    assert "**[2] 阻火器-gb5908**" in md
    assert "href='https://feishu.example/gb5908'" in md
    assert "**[3] 油品罐区安全管理规范（征求意见稿）**" in md
    # 参考栏按编号升序
    assert md.index("**[1]") < md.index("**[2]") < md.index("**[3]") < md.index("**[4]")


def test_bare_number_with_multi_sources_not_mapped() -> None:
    """多 sources 时正文裸 [N]（无文档名）无法锚定 → 宁缺毋错不进参考栏。"""
    answer = "根据第 5.1.1 条 [1] 与第 4.3 条 [2] 的要求执行。"
    card = _build_reply_card(answer, _INCIDENT_SOURCES)
    assert "参考法规" not in _card_markdown(card)


def test_single_source_bare_citation_fallback() -> None:
    """仅 1 篇 source 时编号无歧义，正文裸 [1] 按位置映射兜底。"""
    single = [{"doc_title": "石油化工企业设计防火标准", "feishu_url": "https://x/1"}]
    card = _build_reply_card("依据第 5.1.1 条 [1] 的要求。", single)
    md = _card_markdown(card)
    assert "**[1] 石油化工企业设计防火标准**" in md
    assert "href='https://x/1'" in md


def test_order_sources_for_answer_cite_no() -> None:
    """Web API 用的 order_sources_for_answer：按正文编号重排并附 cite_no。"""
    from app.modules.safety.business_agent.citations import order_sources_for_answer

    ordered = order_sources_for_answer(_INCIDENT_ANSWER, _INCIDENT_SOURCES)
    assert [s.get("cite_no") for s in ordered] == [1, 2, 3, 4]
    assert ordered[0]["doc_title"].startswith("GBT20801.6")
    assert ordered[3]["doc_title"].startswith("GB50160")
