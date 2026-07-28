"""入职 Offer 生成器：HTML 预览 + WeasyPrint 转 PDF。"""

from datetime import date
from io import BytesIO

from app.modules.hr.template_utils import find_hr_template

# 模板占位符 → 参数名映射
PLACEHOLDER_MAP = {
    "{姓名}": "name",
    "{岗位}": "position",
    "{底薪}": "base_salary",
    "{综合月薪}": "salary_range",
    "{体检日期}": "medical_date",
    "{报到日期}": "report_date",
    "{岗位保留时间}": "offer_expire_date",
    "{发送日期}": "send_date",
}


def _build_vals(**kwargs) -> dict[str, str]:
    today = date.today()
    send_date = kwargs.get("send_date") or f"{today.year}年{today.month:02d}月{today.day:02d}日"
    vals: dict[str, str] = {}
    for placeholder, key in PLACEHOLDER_MAP.items():
        if key == "send_date":
            vals[key] = send_date
        else:
            vals[key] = str(kwargs.get(key, "") or "")
    return vals


def generate_offer_pdf(**kwargs) -> BytesIO:
    """生成 Offer PDF：优先 WeasyPrint（Docker），无系统库时降级 fpdf2。"""
    html = generate_offer_html(**kwargs)
    try:
        from weasyprint import HTML
        buf = BytesIO()
        HTML(string=html).write_pdf(buf)
        buf.seek(0)
        return buf
    except (OSError, ImportError):
        # 缺系统库或包未安装，用 fpdf2 兜底
        return _generate_offer_pdf_fallback(**kwargs)


def _generate_offer_pdf_fallback(**kwargs) -> BytesIO:
    """fpdf2 兜底 PDF（macOS 开发环境，无 WeasyPrint 系统库时使用）。"""
    import os as _os
    from fpdf import FPDF
    vals = _build_vals(**kwargs)
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

    w = pdf.w - pdf.l_margin - pdf.r_margin

    # 页眉：公司名 + logo
    logo_path = find_hr_template("company_logo.png")
    pdf.image(str(logo_path), x=pdf.w - pdf.r_margin - 40, y=pdf.t_margin, h=14)
    pdf.set_font(fn, "B", 12)
    pdf.cell(0, 14, "丽珠集团福州福兴医药有限公司", ln=True, align="L")
    pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
    pdf.ln(4)
    pdf.set_font(fn, "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "HR-RE-006", ln=True, align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    pdf.set_font(fn, "B", 18)
    pdf.cell(0, 14, "录用通知函", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font(fn, "", 12)
    pdf.cell(0, 10, f"{vals['name']}同学：", ln=True)
    pdf.ln(2)
    pdf.set_font(fn, "", 10)
    items = [
        "恭喜您从众多应聘者中脱颖而出，成为丽珠大家庭的一员。根据您的经验、技能、学历和各方综合素质，并与您本人协商后，我公司对您的入职相关事宜做以下安排：",
        f"一、职  位：{vals['position']}",
        f"二、转正薪酬：底薪{vals['base_salary']}元+其他津贴+绩效奖金，综合税前月薪{vals['salary_range']}元",
        "三、年收入=综合月薪*12+年终双薪+公司年度奖金+项目攻关奖励（根据参与的项目完成情况以及负责的职责由项目负责人进行分配）",
        "四、福利待遇：",
        "1、公司提供食宿，热水器、空调均有配套；",
        "2、假期：法定节假日+公司规定的其他假期；",
        "3、保险及公积金：按政府相关政策及公司的有关规定执行，公积金按照最高比例12%缴纳",
        "4、试用期：根据《劳动合同法》的相关规定，您的试用期为叁个月（根据工作表现和工作业绩可适当缩短试用期）。首次期间签订叁年的劳动合同及签订关键岗位保密协议。",
        f"5、请您{vals['medical_date'] or '___'}前至我公司指定体检中心参加职业健康体检，体检合格后上岗；",
        f"6、报到时间：请于{vals['report_date']}前到公司人力资源部报到。",
        "五、请您在报到时携带以下资料的原件及复印件：",
        "身份证；学历证、学位证等其他相关证书；个人一寸彩照2张；中国银行卡（工资卡，可入职后办理）；征信报告（任意银行APP可下载）",
        "竭诚欢迎您的加入，相信以您的能力，必能在公司一展所长！",
        f"说明：1、公司将为你保留职位至{vals['offer_expire_date']}，如您不能在此前在贵校的线上就业协议上应约，公司将视您为自动放弃本工作机会，本录用通知失效",
        "2、公司对薪酬福利要求保密，请勿同其它任何第三方讨论薪酬福利事宜，谢谢！",
    ]
    for item in items:
        bold = item.startswith("一、") or item.startswith("二、") or item.startswith("三、") or item.startswith("四、") or item.startswith("五、")
        pdf.set_font(fn, "B" if bold else "", 10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(w, 6, item)
        pdf.ln(1)
    pdf.ln(6)
    stamp_path = find_hr_template("company_stamp.png")
    # 公章叠在落款上：Y-3 让公章几乎贴着文字，字在公章下半部分穿过
    pdf.image(str(stamp_path), x=pdf.w - pdf.r_margin - 40, y=pdf.get_y() - 28, w=40)
    pdf.set_font(fn, "", 10)
    pdf.cell(0, 8, "丽珠集团福州福兴医药有限公司", ln=True, align="R")
    pdf.cell(0, 8, vals["send_date"], ln=True, align="R")
    pdf.ln(8)
    pdf.set_font(fn, "", 8)
    pdf.cell(0, 6, "公司地址：福建省福州市福清市江阴工业集中区  联系人：王琳18650755207", ln=True)
    pdf.cell(0, 6, "邮箱：wanglin03@livzon.cn", ln=True)
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def generate_offer_html(**kwargs) -> str:
    """生成 Offer HTML（用于前端预览和 WeasyPrint 转 PDF）。"""
    vals = _build_vals(**kwargs)

    stamp_path = find_hr_template("company_stamp.png")
    logo_path = find_hr_template("company_logo.png")
    import base64
    stamp_b64 = base64.b64encode(stamp_path.read_bytes()).decode()
    logo_b64 = base64.b64encode(logo_path.read_bytes()).decode()

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2cm 2.5cm 2cm 2.5cm; }}
  @media screen {{ body {{ max-width: 700px; margin: 30px auto; padding: 20px; }} }}
  body {{ font-family: "SimSun", "宋体", serif; font-size: 12pt; line-height: 1.8; color: #000; }}
  .center {{ text-align: center; }}
  .right {{ text-align: right; }}
  .indent {{ text-indent: 2em; }}
  .title {{ font-size: 18pt; font-weight: bold; margin: 12px 0 8px 0; }}
  .letterhead {{ margin: 0 0 16px 0; }}
  .letterhead-row {{ display: flex; justify-content: space-between; align-items: center; }}
  .letterhead-name {{ font-size: 12pt; font-weight: bold; margin: 0; text-align: left; }}
  .letterhead-logo {{ height: 50px; }}
  .letterhead-line {{ border: none; border-top: 1px solid #000; margin: 8px 0 0 0; }}
  .signature {{ text-align: right; margin-top: 24px; }}
  .signature-stamp {{ display: block; width: 6cm; margin-left: auto; }}
  .signature-text {{ margin-top: -3.5cm; font-size: 12pt; }}
</style>
</head>
<body>
<div class="letterhead">
  <div class="letterhead-row">
    <p class="letterhead-name">丽珠集团福州福兴医药有限公司</p>
    <img class="letterhead-logo" src="data:image/png;base64,{logo_b64}" alt="logo">
  </div>
  <hr class="letterhead-line">
</div>
<p class="right" style="font-size:9pt;color:#666;">HR-RE-006</p>
<p class="center title">录用通知函</p>
<p class="indent">{vals["name"]}同学：</p>
<p class="indent">恭喜您从众多应聘者中脱颖而出，成为丽珠大家庭的一员。根据您的经验、技能、学历和各方综合素质，并与您本人协商后，我公司对您的入职相关事宜做以下安排：</p>
<p>一、职&emsp;&emsp;位：{vals["position"]}</p>
<p>二、转正薪酬：底薪{vals["base_salary"]}元+其他津贴+绩效奖金，综合税前月薪{vals["salary_range"]}元</p>
<p>三、年收入=综合月薪*12+年终双薪+公司年度奖金+项目攻关奖励（根据参与的项目完成情况以及负责的职责由项目负责人进行分配）</p>
<p>四、福利待遇：</p>
<p>1、公司提供食宿，热水器、空调均有配套；</p>
<p>2、假期：法定节假日+公司规定的其他假期；</p>
<p>3、保险及公积金：按政府相关政策及公司的有关规定执行，公积金按照最高比例12%缴纳</p>
<p>4、试用期：根据《劳动合同法》的相关规定，您的试用期为&emsp;叁&emsp;个月（根据工作表现和工作业绩可适当缩短试用期）。首次期间签订&emsp;叁年&emsp;的劳动合同及签订关键岗位保密协议。</p>
<p>5、请您{vals["medical_date"]}前至我公司指定体检中心参加职业健康体检，体检合格后上岗：</p>
<p>6、报到时间：请于&emsp;{vals["report_date"]}前到公司人力资源部报到。</p>
<p>五、请您在报到时携带以下资料的原件及复印件：</p>
<p>身份证；学历证、学位证等其他相关证书；</p>
<p>个人一寸彩照2张；</p>
<p>中国银行卡（工资卡，可入职后办理）；</p>
<p>征信报告（任意银行APP可下载）</p>
<p>竭诚欢迎您的加入，相信以您的能力，必能在公司一展所长！</p>
<p>说明：1、公司将为你保留职位至{vals["offer_expire_date"]}，如您不能在此前在贵校的线上就业协议上应约，公司将视您为自动放弃本工作机会，本录用通知失效</p>
<p>2、公司对薪酬福利要求保密，请勿同其它任何第三方讨论薪酬福利事宜，谢谢！</p>
<div class="signature">
  <img class="signature-stamp" src="data:image/png;base64,{stamp_b64}" alt="公章">
  <p class="signature-text">丽珠集团福州福兴医药有限公司</p>
  <p class="right" style="margin-top:0;">{vals["send_date"]}</p>
</div>
<p style="margin-top:24px;">公司地址：福建省福州市福清市江阴工业集中区&emsp;联系人：王琳18650755207</p>
<p>邮箱：wanglin03@livzon.cn</p>
</body>
</html>"""
