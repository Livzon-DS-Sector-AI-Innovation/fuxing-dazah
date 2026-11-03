"""核心管线测试：真实样本全流程（三关）、前置检查 fail-loud、校验器抓错能力。

fixture 为真实 Empower 荧光报告（图谱/BSA线性），内置锁定术语完全覆盖，
无需调用 LLM——顺带守护内置术语表的完整性。"""

from pathlib import Path
from typing import cast

import pymupdf
import pytest

from app.modules.toolbox.tools.chromatogram_translate._core import terms as terms_mod
from app.modules.toolbox.tools.chromatogram_translate._core.geometry import (
    page_geometry,
)
from app.modules.toolbox.tools.chromatogram_translate._core.pipeline import (
    translate_file,
)
from app.modules.toolbox.tools.chromatogram_translate._core.profiles import EMPOWER_CN
from app.modules.toolbox.tools.chromatogram_translate._core.verify import verify_output

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def terms() -> dict[str, str]:
    merged, _ = terms_mod.merged_terms()
    return merged


def make_no_text_pdf(path: Path) -> Path:
    """只有绘图没有文字的 PDF（模拟矢量轮廓打印件）"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(80, 80, 500, 300), color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    return path


def make_english_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Pure English document, nothing to translate.")
    doc.save(str(path))
    doc.close()
    return path


class TestRealSample:
    def test_translate_ok_and_gates_pass(self, terms, tmp_path):
        """真实样本：翻译成功、三关全过、产物可打开且含英文表头。"""
        r = translate_file(FIXTURES / "sample_bsa.pdf", terms)
        assert r.status == "ok", r.error
        assert r.pages == 1
        assert r.output
        out = pymupdf.open("pdf", r.output)
        text = out[0].get_text()
        assert "Peak Results" in text
        assert "Retention" in text and "(µV*sec)" in text
        assert "Report User: Yang Yalin (Yang Yalin)" in text
        # 三关独立复核（translate_file 内部已验，这里再证一次）
        src = pymupdf.open(FIXTURES / "sample_bsa.pdf")
        vr = verify_output(src, out)
        assert vr.ok, vr.hard_errors

    def test_blank_sample_ok(self, terms):
        """空白溶剂样本（无峰行、表结构不同）同样全绿。"""
        r = translate_file(FIXTURES / "sample_blank.pdf", terms)
        assert r.status == "ok", r.error

    def test_geometry_detects_table_and_chart(self):
        doc = pymupdf.open(FIXTURES / "sample_bsa.pdf")
        charts, tables = page_geometry(doc[0], EMPOWER_CN)
        assert tables, "表区未检出"
        assert len(tables[0]["edges"]) >= 6, "列边界数量异常"
        assert charts, "图区未检出"

    def test_output_data_untouched(self, terms):
        """数据零改动：关键数字串在译后逐个在场。"""
        r = translate_file(FIXTURES / "sample_bsa.pdf", terms)
        assert r.status == "ok"
        out = "\n".join(cast(str, pg.get_text()) for pg in pymupdf.open("pdf", r.output))
        for token in ("3816662", "3245133", "571529", "85.03", "10.883", "20260820"):
            assert token in out, f"数字 {token} 丢失"


class TestPrechecks:
    def test_no_text_layer_fails_loudly(self, terms, tmp_path):
        p = make_no_text_pdf(tmp_path / "vector_only.pdf")
        r = translate_file(p, terms)
        assert r.status == "failed"
        assert "文本层" in r.error
        assert r.output is None, "失败文件绝不出产物"

    def test_english_only_skipped(self, terms, tmp_path):
        p = make_english_pdf(tmp_path / "english.pdf")
        r = translate_file(p, terms)
        assert r.status == "skipped"
        assert "未检测到中文内容" in r.error

    def test_missing_terms_fail_not_silent(self, tmp_path):
        """缺词条时明确失败，绝不带原文中文输出。"""
        r = translate_file(FIXTURES / "sample_bsa.pdf", {"名称": "Name"})
        assert r.status == "failed"
        assert "词条缺失" in r.error
        assert r.output is None

    def test_broken_pdf_fails(self, terms, tmp_path):
        p = tmp_path / "broken.pdf"
        p.write_bytes(b"%PDF-1.7 not really a pdf")
        r = translate_file(p, terms)
        assert r.status == "failed"


class TestVerifier:
    def test_catches_digit_loss(self, tmp_path):
        """校验器能抓住数字丢失（曾真实发生的回归类型）。"""
        src = pymupdf.open()
        src.new_page().insert_text((72, 100), "RT 23.717 area 13225")
        out = pymupdf.open()
        out.new_page().insert_text((72, 100), "RT 23.717 area 1322")  # 丢一位
        vr = verify_output(src, out)
        assert not vr.ok
        assert "数字串多重集不一致" in vr.hard_errors[0]

    def test_catches_residual_cjk(self):
        src = pymupdf.open()
        src.new_page().insert_text((72, 100), "保留时间 1.0", fontname="china-s")
        out = pymupdf.open()
        out.new_page().insert_text(
            (72, 100), "Retention 1.0 保留时间", fontname="china-s"
        )
        vr = verify_output(src, out)
        assert not vr.ok
        assert "残留中文" in vr.hard_errors[0]

    def test_clean_pair_passes(self):
        src = pymupdf.open()
        src.new_page().insert_text((72, 100), "面积 100", fontname="china-s")
        out = pymupdf.open()
        out.new_page().insert_text((72, 100), "Area 100")
        vr = verify_output(src, out)
        assert vr.ok


class TestTerms:
    def test_parse_glossary_csv(self):
        t, w = terms_mod.parse_glossary_csv(
            "中文术语,English\n新峰名,New Peak\n坏行\nenglish,English\n"
        )
        assert t == {"新峰名": "New Peak"}
        assert len(w) == 2  # 坏行 + 纯英文行

    def test_glossary_overrides_builtin(self):
        merged, _ = terms_mod.merged_terms("色谱图,Plot")
        assert merged["色谱图"] == "Plot"
        assert merged["名称"] == "Name"  # 内置其余不受影响

    def test_collect_missing(self):
        terms = dict(terms_mod.BUILTIN_TERMS)
        need = terms_mod.collect_missing(["溶剂1.dx", "全新物质"], terms)
        assert "全新物质" in need
        assert "溶剂" not in need  # 段级已覆盖
