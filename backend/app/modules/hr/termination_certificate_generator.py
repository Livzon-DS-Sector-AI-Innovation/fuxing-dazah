"""解除劳动关系证明：HTML 预览 + WeasyPrint 转 PDF。"""

from datetime import date
from io import BytesIO

from app.modules.hr.template_utils import find_hr_template


def _fmt_date(d: date | str) -> str:
    if isinstance(d, date):
        return f"{d.year} 年 {d.month} 月 {d.day} 日"
    return str(d or "")


def generate_termination_certificate_pdf(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> BytesIO:
    """生成解除劳动关系证明 PDF：优先 WeasyPrint（Docker），无系统库时降级 fpdf2。"""
    html = generate_termination_certificate_html(
        name=name, id_number=id_number, department=department,
        position=position, entry_date=entry_date, leave_date=leave_date,
        leave_reason=leave_reason,
    )
    try:
        from weasyprint import HTML
        buf = BytesIO()
        HTML(string=html).write_pdf(buf)
        buf.seek(0)
        return buf
    except (OSError, ImportError):
        return _generate_termination_certificate_pdf_fallback(
            name=name, id_number=id_number, department=department,
            position=position, entry_date=entry_date, leave_date=leave_date,
            leave_reason=leave_reason,
        )


def _generate_termination_certificate_pdf_fallback(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> BytesIO:
    """fpdf2 兜底 PDF（macOS 开发环境，无 WeasyPrint 系统库时使用）。"""
    import os as _os
    from fpdf import FPDF

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_margin(20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    fn = "Helvetica"
    font_path = ""
    for p in ["/System/Library/Fonts/Supplemental/Songti.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
               "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]:
        if _os.path.exists(p):
            font_path = p
            break
    if font_path:
        pdf.add_font("CJK", "", font_path)
        pdf.add_font("CJK", "B", font_path)
        fn = "CJK"

    entry_str = _fmt_date(entry_date)
    leave_str = _fmt_date(leave_date)
    today = date.today()
    today_str = f"{today.year} 年 {today.month} 月 {today.day} 日"
    body = (f"兹有我司原职工姓名：{name}，身份证号：{id_number}，"
            f"入职时间 {entry_str} 到我公司工作，{department}部门，"
            f"{position}岗位 工作。现因{leave_reason}，"
            f"于 {leave_str} 正式解除劳动关系。")
    w = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font(fn, "", 9)
    pdf.cell(0, 8, "HR-RE-013", ln=True, align="R")
    pdf.ln(6)
    pdf.set_font(fn, "B", 18)
    pdf.cell(0, 14, "解除劳动关系证明", ln=True, align="C")
    pdf.ln(8)
    pdf.set_font(fn, "", 11)
    pdf.multi_cell(w, 8, body)
    pdf.ln(4)
    pdf.cell(0, 8, "特此证明。", ln=True)
    pdf.ln(4)
    pdf.set_font(fn, "", 9)
    pdf.multi_cell(w, 6, "1、员工离职后仍需履行保密义务，未经我公司书面许可，不得向任何单位和个人透露我公司商业秘密和其他经营秘密（造成影响公司保留追责权力）")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w, 6, "2、本证明仅开具一次，请妥善保管，如遗失不补开。")
    pdf.ln(10)
    stamp_path = find_hr_template("company_stamp.png")
    # 公章叠在落款上：Y-3 让公章几乎贴着文字，字在公章下半部分穿过
    pdf.image(str(stamp_path), x=pdf.w - pdf.r_margin - 40, y=pdf.get_y() - 28, w=40)
    pdf.set_font(fn, "", 10)
    pdf.cell(0, 8, "丽珠集团福州福兴医药有限公司", ln=True, align="R")
    pdf.cell(0, 8, today_str, ln=True, align="R")
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def generate_termination_certificate_html(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> str:
    """生成解除劳动关系证明 HTML（用于预览和 PDF）。"""
    import base64

    entry_str = _fmt_date(entry_date)
    leave_str = _fmt_date(leave_date)
    today = date.today()
    today_str = f"{today.year} 年 {today.month} 月 {today.day} 日"

    stamp_path = find_hr_template("company_stamp.png")
    stamp_b64 = base64.b64encode(stamp_path.read_bytes()).decode()

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2.5cm 3cm; }}
  body {{ font-family: "SimSun", "宋体", serif; font-size: 12pt; line-height: 2; color: #000; }}
  .center {{ text-align: center; }}
  .right {{ text-align: right; }}
  .indent {{ text-indent: 2em; }}
  .title {{ font-size: 18pt; font-weight: bold; letter-spacing: 0.3em; }}
  .signature {{ text-align: right; margin-top: 24px; }}
  .signature-stamp {{ display: block; width: 6cm; margin-left: auto; }}
  .signature-text {{ margin-top: -3.5cm; font-size: 12pt; }}
</style>
</head>
<body>
<p style="text-align:right;font-size:9pt;color:#666;">HR-RE-013</p>
<p class="center title">解除劳动关系证明</p>
<p>&nbsp;</p>
<p class="indent">兹有我司原职工姓名：{name}，身份证号：{id_number}，
入职时间 {entry_str} 到我公司工作，{department}部门，
{position}岗位 工作。现因{leave_reason}，
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
</body>
</html>"""
