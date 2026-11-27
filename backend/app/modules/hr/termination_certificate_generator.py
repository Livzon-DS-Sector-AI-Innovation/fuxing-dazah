"""解除劳动关系证明：HTML 预览 + PDF。

版式对齐公司现行样式（表单编号 HR-RE-013）：左上 Logo + 公司名，右上加粗表单编号，
居中大标题，正文一段（兹有我司原职工…到我公司工作，担任 部门/岗位。现因…，于…正式
解除劳动关系。），「特此证明。」，「说明」两条，右下落款为公司名 / 开具日 / 人力资源部，
人力资源部印章压在落款上。

PDF 优先 WeasyPrint（Docker），无系统库时降级 fpdf2（macOS 开发环境）；两条路径共用
同一套文案，只差排版引擎。落款日期取开具日（issued_on），不是生成当天。
"""

import base64
import re
from datetime import date
from functools import lru_cache
from html import escape
from io import BytesIO
from typing import TypedDict

from fpdf import FPDF

from app.modules.hr.template_utils import find_font, find_hr_template

COMPANY_NAME = "丽珠集团福州福兴医药有限公司"
FORM_NO = "HR-RE-013"
SIGN_DEPARTMENT = "人力资源部"
NOTES = (
    "1、员工离职后仍需履行保密义务，未经我公司书面许可，不得向任何单位和个人透露我公司"
    "商业秘密和其他经营秘密（造成影响公司保留追责权力）",
    "2、本证明仅开具一次，请妥善保管，如遗失不补开。",
)
# 印章可见范围的宽度（厘米）：素材四周留白很大，整图缩放会让章面偏小
SEAL_WIDTH_CM = 3.8


class CertificateFields(TypedDict):
    """证明用到的全部字段：HTML 与 PDF 两条渲染路径、电子版与纸质两联版共用。"""

    name: str
    id_number: str
    department: str
    position: str
    entry_date: date | str
    leave_date: date | str
    leave_reason: str
    issued_on: date | None


def _fmt_date(d: date | str) -> str:
    if isinstance(d, date):
        return f"{d.year}年{d.month}月{d.day}日"
    return str(d or "")


def _issued_date(issued_on: date | None) -> date:
    return issued_on or date.today()


def body_text(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str = "个人原因",
) -> str:
    """证明正文一段（纯文本，HTML / PDF 两条渲染路径共用）。"""
    return (
        f"兹有我司原职工{name}，身份证号 {id_number}，{_fmt_date(entry_date)}到我公司工作，"
        f"担任{department}/{position}。现因{leave_reason}，"
        f"于{_fmt_date(leave_date)}正式解除劳动关系。"
    )


@lru_cache(maxsize=1)
def seal_png() -> bytes:
    """按透明通道裁掉印章素材四周的留白，只留章面（否则 6cm 宽的图里章面只有 2.4cm）。"""
    from PIL import Image

    path = find_hr_template("company_stamp.png")
    with Image.open(path) as source:
        image = source.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox:
        image = image.crop(bbox)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@lru_cache(maxsize=1)
def logo_png() -> bytes:
    return find_hr_template("company_logo.png").read_bytes()


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _render_copy_html(
    *,
    safe_name: str,
    safe_id_number: str,
    safe_department: str,
    safe_position: str,
    entry_str: str,
    leave_str: str,
    safe_leave_reason: str,
    issued_str: str,
    copy_label: str,
    receipt: bool,
) -> str:
    """一份证明（一联）的 HTML 片段。receipt=True 时在下方加员工签收栏（纸质两联版）。

    字段值由调用方转义后传入；正文里的日期是格式化后的纯文本。
    """
    receipt_html = (
        '<div class="receipt">'
        "<p>员工签收栏：本人已收到上述证明，对证明内容无异议。</p>"
        "<p>签收人（本人签字）：＿＿＿＿＿＿＿＿＿＿　　签收日期：＿＿＿＿年＿＿月＿＿日</p>"
        "</div>"
    ) if receipt else ""
    label = f" · {copy_label}" if copy_label else ""
    return f"""<section class="copy">
<table class="letterhead"><tr>
  <td class="logo-cell"><img class="logo" src="{_data_url(logo_png())}" alt="公司标识"></td>
  <td class="company">{COMPANY_NAME}</td>
</tr></table>
<p class="doc-no">{FORM_NO}{label}</p>
<p class="title">解除劳动关系证明</p>
<p class="body">兹有我司原职工{safe_name}，身份证号 {safe_id_number}，{entry_str}到我公司工作，担任{safe_department}/{safe_position}。现因{safe_leave_reason}，于{leave_str}正式解除劳动关系。</p>
<p class="body">特此证明。</p>
<p class="notes-title">说明：</p>
<p class="notes">{escape(NOTES[0])}</p>
<p class="notes">{escape(NOTES[1])}</p>
<div class="signature">
  <img class="seal" src="{_data_url(seal_png())}" alt="人力资源部印章">
  <p class="sign-company">{COMPANY_NAME}</p>
  <p class="sign-date">{issued_str}</p>
  <p class="sign-dept">{SIGN_DEPARTMENT}</p>
</div>
{receipt_html}
</section>"""


def _document_html(copies: list[str]) -> str:
    font_path = find_font("NotoSansSC.ttf")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2.2cm 2.6cm; }}
  @font-face {{ font-family: "NotoSansSC"; src: url("file://{font_path}"); }}
  /* file:// 字体只有服务端 WeasyPrint 能读；浏览器里预览时依次落到本机同款黑体 */
  body {{ font-family: "NotoSansSC", "Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 16pt; line-height: 1.8; color: #000; margin: 0; }}
  p {{ margin: 0; }}
  .letterhead {{ width: 100%; border-collapse: collapse; }}
  .letterhead td {{ vertical-align: middle; padding: 0; }}
  .logo-cell {{ width: 1.4cm; }}
  .logo {{ height: 1.2cm; }}
  .company {{ font-size: 15pt; padding-left: 0.2cm !important; }}
  .doc-no {{ text-align: right; font-size: 15pt; font-weight: bold; margin-top: 0.45cm !important; }}
  .title {{ text-align: center; font-size: 20pt; font-weight: bold; margin: 0.35cm 0 0.8cm !important; }}
  .body {{ text-indent: 2em; line-height: 1.77; }}
  .notes-title {{ margin-top: 0.55cm !important; }}
  .notes {{ font-size: 12.5pt; line-height: 1.5; text-indent: 1.5em; }}
  .signature {{ position: relative; margin-top: 3.4cm; width: 10.4cm; margin-left: auto; }}
  .signature p {{ position: relative; z-index: 2; text-align: center; line-height: 1.35; }}
  .sign-company, .sign-date {{ font-size: 16pt; }}
  .sign-dept {{ font-size: 15pt; }}
  .seal {{ position: absolute; z-index: 1; width: {SEAL_WIDTH_CM}cm; right: -0.2cm; top: 0.78cm; }}
  .receipt {{ margin-top: 2.2cm; border-top: 1px dashed #999; padding-top: 0.5cm; }}
  .receipt p {{ text-indent: 0; }}
  .copy {{ page-break-after: always; }}
  .copy:last-child {{ page-break-after: auto; }}
  /* 屏幕上（HR 预览弹窗、员工手机签字页）按 A4 纸面呈现：@page 边距只对打印 / WeasyPrint 生效，
     不补这组规则的话正文会顶到窗口边缘、印章还会撑出横向滚动条 */
  @media screen {{
    body {{ width: 21cm; min-height: 29.7cm; box-sizing: border-box; margin: 0; padding: 2.2cm 2.6cm; background: #fff; }}
    .copy {{ min-height: 25.3cm; }}
    .copy + .copy {{ margin-top: calc(4.4cm - 1px); padding-top: 2.2cm; border-top: 1px dashed #bbb; }}
  }}
</style>
</head>
<body>
{''.join(copies)}
</body>
</html>"""


def prepare_fields(
    *,
    name: str,
    id_number: str,
    department: str,
    position: str,
    entry_date: date | str,
    leave_date: date | str,
    leave_reason: str,
    issued_on: date | None,
) -> dict[str, str]:
    """字段转义 + 日期格式化：这段 HTML 会进预览窗 document.write 和免登签字页的 DOM，
    不转义即存储型 XSS。"""
    return {
        "safe_name": escape(name),
        "safe_id_number": escape(id_number),
        "safe_department": escape(department),
        "safe_position": escape(position),
        "entry_str": escape(_fmt_date(entry_date)),
        "leave_str": escape(_fmt_date(leave_date)),
        "safe_leave_reason": escape(leave_reason),
        "issued_str": _fmt_date(_issued_date(issued_on)),
    }


def generate_termination_certificate_pdf(
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
    """生成解除劳动关系证明 PDF：优先 WeasyPrint（Docker），无系统库时降级 fpdf2。"""
    fields = CertificateFields(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    )
    try:
        html = generate_termination_certificate_html(**fields)
        from weasyprint import HTML
        buf = BytesIO()
        HTML(string=html).write_pdf(buf)
        buf.seek(0)
        return buf
    except (OSError, ImportError):
        return _render_pdf_fallback(fields)


# ─── fpdf2 降级（macOS 开发环境，无 WeasyPrint 系统库时使用）───

_RECEIPT_LINES = (
    "员工签收栏：本人已收到上述证明，对证明内容无异议。",
    "签收人（本人签字）：____________    签收日期：______年____月____日",
)
# 断行单元：ASCII 连续串（身份证号、日期数字）不拆开，中文逐字可断；收尾标点不落到行首
_BREAK_TOKEN = re.compile(r"[A-Za-z0-9.,:/%\-]+|.")
_CLOSING_PUNCT = "，。、；：）】」』！？"


def wrap_lines(pdf: FPDF, text: str, width: float) -> list[str]:
    """中文正文按宽度折行：数字串整体换行（不在「20｜24 年」中间断开），标点不开头。"""
    tokens: list[str] = []
    for token in _BREAK_TOKEN.findall(text):
        if tokens and token[0] in _CLOSING_PUNCT:
            tokens[-1] += token
        else:
            tokens.append(token)
    lines: list[str] = []
    current = ""
    for token in tokens:
        if current and pdf.get_string_width(current + token) > width:
            lines.append(current.rstrip())
            current = token
        else:
            current += token
    if current:
        lines.append(current.rstrip())
    return lines


def _new_pdf() -> tuple[FPDF, str]:
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_margin(22)
    pdf.set_auto_page_break(auto=False)
    font_name = "Helvetica"
    try:
        font_path = find_font("NotoSansSC.ttf")
        # 常规 + 粗体都要注册：标题用的是 "B" 字重，只加常规会在 set_font 时抛 Undefined font
        pdf.add_font("NotoSans", "", str(font_path))
        pdf.add_font("NotoSans", "B", str(font_path))
        font_name = "NotoSans"
    except FileNotFoundError:
        pass
    return pdf, font_name


def _line(
    pdf: FPDF, w: float, h: float, text: str = "", *, align: str = "", x: float | None = None,
) -> None:
    """画一行后回到左边距并下移一行（fpdf2 的 cell 默认是往右走，这里统一成「换行」语义）。"""
    from fpdf.enums import XPos, YPos

    if x is not None:
        pdf.set_x(x)
    pdf.cell(w, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align)


def _draw_copy(
    pdf: FPDF, font: str, *, plain: dict[str, str], copy_label: str, receipt: bool,
) -> None:
    """在当前页画一联证明。印章先画、落款文字后画，字压在章上（与盖章效果一致）。

    字号与纵向位置按公司现行样式（HR-RE-013）的比例校准：正文 16pt 行距 10mm，
    标题 20pt 加粗，说明 12.5pt，落款 16pt，章面直径约 3.8cm。
    """
    left, right = pdf.l_margin, pdf.w - pdf.r_margin
    width = right - left

    def put_lines(text: str, size: float, line_h: float, *, indent: str = "") -> None:
        pdf.set_font(font, "", size)
        for line in wrap_lines(pdf, indent + text, width):
            _line(pdf, width, line_h, line)

    pdf.image(BytesIO(logo_png()), x=left, y=20, h=12, type="png")
    pdf.set_xy(left + 11.5, 20.5)
    pdf.set_font(font, "", 15)
    pdf.cell(width - 11.5, 11, COMPANY_NAME, align="L")
    pdf.set_y(33.5)
    pdf.set_font(font, "B", 15)
    _line(pdf, width, 8, FORM_NO + (f" · {copy_label}" if copy_label else ""), align="R")
    pdf.ln(4)
    pdf.set_font(font, "B", 20)
    _line(pdf, width, 12, "解除劳动关系证明", align="C")
    pdf.ln(8)

    put_lines(plain["body"], 16, 10, indent="　　")
    pdf.ln(1)
    put_lines("特此证明。", 16, 10, indent="　　")
    pdf.ln(6)
    put_lines("说明：", 12.5, 6)
    for note in NOTES:
        put_lines(note, 12.5, 6)

    # 落款：三行居中对齐在同一轴上，印章压在「公司名 / 开具日 / 人力资源部」上
    seal_w = SEAL_WIDTH_CM * 10
    block_w = 10.4 * 10
    top = pdf.get_y() + 24
    # 章面中心压在「开具日」那一行上，右缘略超出正文右边界（与手工盖章位置一致）
    pdf.image(
        BytesIO(seal_png()), x=right - seal_w + 2, y=top + 9.5 + 4.75 - seal_w * 0.51,
        w=seal_w, type="png",
    )
    pdf.set_y(top)
    pdf.set_font(font, "", 16)
    block_x = right - block_w
    _line(pdf, block_w, 9.5, COMPANY_NAME, align="C", x=block_x)
    _line(pdf, block_w, 9.5, plain["issued_str"], align="C", x=block_x)
    pdf.set_font(font, "", 15)
    _line(pdf, block_w, 8, SIGN_DEPARTMENT, align="C", x=block_x)

    if receipt:
        pdf.ln(22)
        pdf.set_draw_color(150, 150, 150)
        pdf.dashed_line(left, pdf.get_y(), right, pdf.get_y(), dash_length=1.5, space_length=1.2)
        pdf.ln(5)
        for line in _RECEIPT_LINES:
            put_lines(line, 13, 9)


def _generate_termination_certificate_pdf_fallback(
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
    """电子单张版的 fpdf2 兜底 PDF（保留原函数名，供测试与旧调用方使用）。"""
    return _render_pdf_fallback(CertificateFields(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    ))


def _render_pdf_fallback(
    fields: CertificateFields,
    *, copies: tuple[tuple[str, bool], ...] = (("", False),),
) -> BytesIO:
    """fpdf2 兜底 PDF（macOS 开发环境，无 WeasyPrint 系统库时使用）。
    copies：[(联次文案, 是否带签收栏)]，每联一页。
    """
    plain = {
        "body": body_text(
            name=fields["name"], id_number=fields["id_number"], department=fields["department"],
            position=fields["position"], entry_date=fields["entry_date"],
            leave_date=fields["leave_date"], leave_reason=fields["leave_reason"],
        ),
        "issued_str": _fmt_date(_issued_date(fields["issued_on"])),
    }
    pdf, font = _new_pdf()
    for copy_label, receipt in copies:
        pdf.add_page()
        _draw_copy(pdf, font, plain=plain, copy_label=copy_label, receipt=receipt)
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
    issued_on: date | None = None,
) -> str:
    """生成解除劳动关系证明 HTML（电子单张版，用于预览和 PDF）。"""
    fields = prepare_fields(
        name=name, id_number=id_number, department=department, position=position,
        entry_date=entry_date, leave_date=leave_date, leave_reason=leave_reason,
        issued_on=issued_on,
    )
    return _document_html([_render_copy_html(**fields, copy_label="", receipt=False)])


def render_paper_copies_html(fields: dict[str, str]) -> str:
    """纸质两联版整页 HTML：第一联公司留存 / 第二联员工留存，各带签收栏。"""
    copies = [
        _render_copy_html(**fields, copy_label=label, receipt=True)
        for label in ("第一联 · 公司留存", "第二联 · 员工留存")
    ]
    return _document_html(copies)


def render_paper_copies_pdf(fields: CertificateFields) -> BytesIO:
    """纸质两联版 PDF：优先 WeasyPrint（两联各占一页），无系统库时降级 fpdf2。"""
    try:
        from weasyprint import HTML
        buf = BytesIO()
        HTML(string=render_paper_copies_html(prepare_fields(**fields))).write_pdf(buf)
        buf.seek(0)
        return buf
    except (OSError, ImportError):
        return _render_pdf_fallback(
            fields, copies=(("第一联 · 公司留存", True), ("第二联 · 员工留存", True)),
        )
