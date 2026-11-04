"""批号代号识别（_match_docs_by_batch_code）纯函数测试。"""

from app.modules.quality.models import QualityStandardDocument
from app.modules.quality.service import TestTaskService


def _doc(code: str | None) -> QualityStandardDocument:
    return QualityStandardDocument(file_no="SOP.02.0000.000", product_name="产品", product_code=code)


def test_match_prefix_returns_code_and_docs():
    docs = [_doc("HAF"), _doc("HAA")]
    code, matched = TestTaskService._match_docs_by_batch_code(docs, "HAF2608001B")
    assert code == "HAF"
    assert [d.product_code for d in matched] == ["HAF"]


def test_longest_prefix_wins():
    docs = [_doc("HA"), _doc("HAF")]
    code, matched = TestTaskService._match_docs_by_batch_code(docs, "HAF2608001B")
    assert code == "HAF"
    assert [d.product_code for d in matched] == ["HAF"]


def test_case_insensitive_and_whitespace():
    docs = [_doc("HAF")]
    code, _ = TestTaskService._match_docs_by_batch_code(docs, " haf2608001b ")
    assert code == "HAF"


def test_no_match_returns_empty():
    docs = [_doc("HAF"), _doc("HAA")]
    code, matched = TestTaskService._match_docs_by_batch_code(docs, "XYZ2608001B")
    assert code is None
    assert matched == []


def test_docs_without_code_ignored():
    docs = [_doc(None), _doc("HAF")]
    code, matched = TestTaskService._match_docs_by_batch_code(docs, "HAF2608001B")
    assert code == "HAF"
    assert [d.product_code for d in matched] == ["HAF"]
