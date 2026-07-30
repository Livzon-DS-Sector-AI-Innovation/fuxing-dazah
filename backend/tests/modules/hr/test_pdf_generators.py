"""PDF 生成器测试：Offer + 离职证明"""

from io import BytesIO

import pytest

from app.modules.hr.offer_generator import (
    _generate_offer_pdf_fallback,
    generate_offer_html,
    generate_offer_pdf,
)
from app.modules.hr.termination_certificate_generator import (
    _generate_termination_certificate_pdf_fallback,
    generate_termination_certificate_html,
    generate_termination_certificate_pdf,
)


class TestOfferPdf:
    def test_generate_html_contains_chinese(self):
        """HTML 包含中文内容和字体引用"""
        html = generate_offer_html(
            name="张三", position="工程师", department="技术部",
            base_salary="8000", salary_range="8000-12000",
        )
        assert "张三" in html
        assert "工程师" in html
        # 字体引用存在
        assert "@font-face" in html
        assert "NotoSansSC" in html
        # 公司名存在
        assert "丽珠集团" in html

    def test_generate_html_with_minimal_params(self):
        """最少参数也能正常生成 HTML"""
        html = generate_offer_html(name="测试", position="岗位")
        assert "测试" in html
        assert "岗位" in html

    def test_generate_pdf_fallback_returns_bytes(self):
        """fpdf2 兜底返回有效 PDF 字节"""
        buf = _generate_offer_pdf_fallback(
            name="李四", position="操作工", department="生产部",
        )
        assert isinstance(buf, BytesIO)
        data = buf.read()
        assert len(data) > 1000  # 至少 1KB
        assert data[:5] == b"%PDF-"  # PDF magic number

    def test_generate_pdf_main_path_returns_bytes(self):
        """generate_offer_pdf 走主流/兜底都能返回 PDF（降级到 fpdf2 也 OK）"""
        buf = generate_offer_pdf(
            name="王五", position="QA", department="质量部",
            base_salary="6000", salary_range="6000-9000",
            report_date="2026-08-01", medical_date="2026-07-30",
        )
        assert isinstance(buf, BytesIO)
        data = buf.read()
        assert len(data) > 1000
        assert data[:5] == b"%PDF-"

    def test_generate_pdf_with_all_fields(self):
        """全字段 Offer PDF 正常生成"""
        buf = generate_offer_pdf(
            name="赵六", position="主管", department="人事行政部",
            base_salary="10000", salary_range="10000-15000",
            report_date="2026-09-01", medical_date="2026-08-25",
            offer_expire_date="2026-08-20", send_date="2026年08月15日",
        )
        data = buf.read()
        assert len(data) > 1000


class TestTerminationCertificate:
    def test_generate_html_contains_content(self):
        """离职证明 HTML 包含关键信息"""
        html = generate_termination_certificate_html(
            name="张三", id_number="350100199001011234",
            department="生产部", position="操作工",
            entry_date="2020-01-01", leave_date="2026-07-31",
            leave_reason="个人原因",
        )
        assert "张三" in html
        assert "生产部" in html
        assert "解除劳动关系" in html
        assert "NotoSansSC" in html

    def test_generate_pdf_fallback(self):
        """fpdf2 兜底离职证明"""
        buf = _generate_termination_certificate_pdf_fallback(
            name="李四", id_number="350100199002021234",
            department="技术部", position="工程师",
            entry_date="2021-06-01", leave_date="2026-07-31",
        )
        data = buf.read()
        assert data[:5] == b"%PDF-"
        assert len(data) > 1000

    def test_generate_pdf_main_path(self):
        """主路径离职证明"""
        buf = generate_termination_certificate_pdf(
            name="王五", id_number="350100199003031234",
            department="质量部", position="QA",
            entry_date="2019-03-01", leave_date="2026-07-31",
        )
        data = buf.read()
        assert data[:5] == b"%PDF-"
        assert len(data) > 1000

    def test_default_leave_reason(self):
        """缺省离职原因时使用默认值"""
        html = generate_termination_certificate_html(
            name="测试", id_number="123", department="部门",
            position="岗位", entry_date="2020-01-01", leave_date="2026-01-01",
        )
        assert "个人原因" in html
