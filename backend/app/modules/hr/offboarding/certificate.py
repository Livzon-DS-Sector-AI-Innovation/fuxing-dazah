"""离职证明生成：电子单张版与纸质两联版共用公司现行版式。

版式要求（需求「离职证明版式」）：与公司现行样式保持一致——电子版单张；
纸质两联版在同一版式上分两联（第一联公司留存 / 第二联员工留存），各带员工签收栏，
由员工本人到公司当面签收。版式与文案统一在 termination_certificate_generator 维护，
这里只负责两种模板的差异。PDF 优先 WeasyPrint（Docker），无系统库时降级 fpdf2。
"""

from datetime import date
from io import BytesIO

from app.modules.hr import termination_certificate_generator as base
from app.modules.hr.termination_certificate_generator import CertificateFields

__all__ = [
    "generate_electronic_html",
    "generate_electronic_pdf",
    "generate_paper_html",
    "generate_paper_pdf",
]


def generate_electronic_html(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
    issued_on: date | None = None,
) -> str:
    """电子单张版 HTML（字段转义在 generator 内）。"""
    return base.generate_termination_certificate_html(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    )


def generate_electronic_pdf(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
    issued_on: date | None = None,
) -> BytesIO:
    return base.generate_termination_certificate_pdf(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    )


def generate_paper_html(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
    issued_on: date | None = None,
) -> str:
    """纸质两联版 HTML：同一版式两联，各带员工签收栏。"""
    fields = CertificateFields(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    )
    return base.render_paper_copies_html(base.prepare_fields(**fields))


def generate_paper_pdf(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
    issued_on: date | None = None,
) -> BytesIO:
    """纸质两联版 PDF：两联各占一页。"""
    fields = CertificateFields(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    )
    return base.render_paper_copies_pdf(fields)
