"""离职证明生成：电子单张版复用现有 generator，纸质两联版补员工签收栏。

版式要求（需求「离职证明版式」）：与现行版式保持一致——电子版单张；
纸质两联版在此基础上增加员工签收栏，一式两联，员工本人当面签收。
PDF 优先 WeasyPrint（两联各占一页），无系统库时降级 fpdf2（macOS 开发环境）。
"""

from datetime import date
from html import escape
from io import BytesIO

from app.modules.hr.template_utils import find_font, find_hr_template
from app.modules.hr.termination_certificate_generator import (
    _fmt_date,
    generate_termination_certificate_html,
    generate_termination_certificate_pdf,
)


def generate_electronic_html(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> str:
    """电子单张版 HTML（直接复用现行 generator，版式不动；字段转义在 generator 内）。"""
    return generate_termination_certificate_html(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
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
) -> BytesIO:
    return generate_termination_certificate_pdf(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
    )


_SIGN_BLOCK = """
<p>&nbsp;</p>
<div style="margin-top:12px;border-top:1px dashed #999;padding-top:10px;">
  <p style="font-size:12pt;">员工签收栏：本人已收到《解除劳动关系证明》，对证明内容无异议。</p>
  <p style="font-size:12pt;margin-top:16px;">签收人（本人签字）：＿＿＿＿＿＿＿＿＿＿&nbsp;&nbsp;&nbsp;&nbsp;签收日期：＿＿＿＿年＿＿月＿＿日</p>
</div>
"""


def generate_paper_html(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> str:
    """纸质两联版 HTML：同一版式两联（第一联公司留存 / 第二联员工留存），各带签收栏。"""
    import base64

    # 与电子版同口径转义：这段 HTML 会进 HR 预览窗和免登签字页的 DOM
    safe_name = escape(name)
    safe_id_number = escape(id_number)
    safe_department = escape(department)
    safe_position = escape(position)
    safe_leave_reason = escape(leave_reason)
    entry_str = _fmt_date(entry_date)
    leave_str = _fmt_date(leave_date)
    today = date.today()
    today_str = f"{today.year} 年 {today.month} 月 {today.day} 日"
    stamp_path = find_hr_template("company_stamp.png")
    stamp_b64 = base64.b64encode(stamp_path.read_bytes()).decode()
    font_path = find_font("NotoSansSC.ttf")

    def _copy(no: int, keep: str) -> str:
        return f"""
<div class="copy">
<p style="text-align:right;font-size:9pt;color:#666;">HR-RE-013（{no}）· {keep}</p>
<p class="center title">解除劳动关系证明</p>
<p>&nbsp;</p>
<p class="indent">兹有我司原职工姓名：{safe_name}，身份证号：{safe_id_number}，
入职时间 {entry_str} 到我公司工作，{safe_department}部门，
{safe_position}岗位 工作。现因{safe_leave_reason}，
于 {leave_str} 正式解除劳动关系。</p>
<p>特此证明。</p>
<p>&nbsp;</p>
<p>1、员工离职后仍需履行保密义务，未经我公司书面许可，不得向任何单位<br/>和个人透露我公司商业秘密和其他经营秘密（造成影响公司保留追责权力）</p>
<p>2、本证明仅开具一次，请妥善保管，如遗失不补开。</p>
<p>&nbsp;</p>
<div class="signature">
  <img class="signature-stamp" src="data:image/png;base64,{stamp_b64}" alt="公章">
  <p class="signature-text">丽珠集团福州福兴医药有限公司</p>
  <p class="right" style="margin-top:0;">{today_str}</p>
</div>
{_SIGN_BLOCK}
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 1.8cm 2.5cm; }}
  @font-face {{ font-family: "NotoSansSC"; src: url("file://{font_path}"); }}
  body {{ font-family: "NotoSansSC", sans-serif; font-size: 12pt; line-height: 1.9; color: #000; }}
  .center {{ text-align: center; }}
  .right {{ text-align: right; }}
  .indent {{ text-indent: 2em; }}
  .title {{ font-size: 18pt; font-weight: bold; letter-spacing: 0.3em; }}
  .signature {{ text-align: right; margin-top: 16px; }}
  .signature-stamp {{ display: block; width: 5.2cm; margin-left: auto; }}
  .signature-text {{ margin-top: -3cm; font-size: 12pt; }}
  .copy {{ page-break-after: always; }}
  .copy:last-child {{ page-break-after: auto; }}
</style>
</head>
<body>{_copy(1, "第一联 · 公司留存")}{_copy(2, "第二联 · 员工留存")}
</body>
</html>"""


def generate_paper_pdf(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> BytesIO:
    """纸质两联版 PDF：优先 WeasyPrint（分页两联），无系统库时降级 fpdf2 单页两段。"""
    try:
        html = generate_paper_html(
            name=name, id_number=id_number, department=department, position=position,
            entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        )
        from weasyprint import HTML
        buf = BytesIO()
        HTML(string=html).write_pdf(buf)
        buf.seek(0)
        return buf
    except (OSError, ImportError):
        return _paper_pdf_fallback(
            name=name, id_number=id_number, department=department, position=position,
            entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        )


def _paper_pdf_fallback(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> BytesIO:
    """fpdf2 兜底：两联各占一页，签收栏以文字段落呈现（纯文本渲染，无需转义）。"""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_margin(18)
    pdf.set_auto_page_break(auto=True, margin=18)
    fn = "Helvetica"
    try:
        font_path = find_font("NotoSansSC.ttf")
        # 常规 + 粗体都要注册：标题用的是 "B" 字重，只加常规会在 set_font 时抛 Undefined font
        pdf.add_font("NotoSans", "", str(font_path))
        pdf.add_font("NotoSans", "B", str(font_path))
        fn = "NotoSans"
    except FileNotFoundError:
        pass
    for idx, keep in ((1, "第一联 · 公司留存"), (2, "第二联 · 员工留存")):
        pdf.add_page()
        pdf.set_font(fn, "", 9)
        pdf.cell(0, 8, f"HR-RE-013（{idx}）· {keep}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)
        pdf.set_font(fn, "B", 18)
        pdf.cell(0, 14, "解除劳动关系证明", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(6)
        pdf.set_font(fn, "", 11)
        pdf.multi_cell(
            pdf.w - pdf.l_margin - pdf.r_margin, 8,
            (f"兹有我司原职工姓名：{name}，身份证号：{id_number}，"
             f"入职时间 {_fmt_date(entry_date)} 到我公司工作，{department}部门，"
             f"{position}岗位 工作。现因{leave_reason}，"
             f"于 {_fmt_date(leave_date)} 正式解除劳动关系。"),
        )
        pdf.ln(4)
        pdf.set_font(fn, "", 9)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 6,
                       "1、员工离职后仍需履行保密义务，未经我公司书面许可，不得向任何单位和个人透露我公司商业秘密和其他经营秘密（造成影响公司保留追责权力）")
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 6, "2、本证明仅开具一次，请妥善保管，如遗失不补开。")
        pdf.ln(10)
        stamp_path = find_hr_template("company_stamp.png")
        pdf.image(str(stamp_path), x=pdf.w - pdf.r_margin - 40, y=pdf.get_y() - 28, w=40)
        pdf.set_font(fn, "", 10)
        pdf.cell(0, 8, "丽珠集团福州福兴医药有限公司", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, _fmt_date(date.today()), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(8)
        pdf.set_font(fn, "", 10)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 7,
                       "员工签收栏：本人已收到《解除劳动关系证明》，对证明内容无异议。\n"
                       "签收人（本人签字）：____________    签收日期：______年____月____日")
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
