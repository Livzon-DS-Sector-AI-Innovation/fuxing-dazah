"""简历解析器字段提取回归测试。

对应修复：招聘平台导出 PDF 的字距空格（「姓 名： 练 珊」）与开头水印噪声
导致姓名/性别提取失败，建档变成「未识别姓名」。
"""

from app.modules.hr.resume_parser import (
    _extract_education,
    _extract_gender,
    _extract_name,
)


def test_name_plain_label():
    assert _extract_name("个人简历 姓名：张三 男 本科 28岁") == "张三"


def test_name_spaced_label_and_value():
    """平台导出 PDF：键内与字间均有空格，姓名后跟下一个标签。"""
    text = "~ A 8eb50979a361c6071HB939y6E1tWx423WPuXWOGnnfDVNRNk3A~ N R N V 基本信息 姓 名： 练 珊 出生年月： 1998年7月9日 籍 贯： 福建"
    assert _extract_name(text) == "练珊"


def test_name_spaced_three_char_before_digit():
    """三字名（字间空格）后直接跟数字，不应吞入出生年份。"""
    text = "基 本 信 息 姓 名： 欧 阳 娜 1998年7月出生"
    assert _extract_name(text) == "欧阳娜"


def test_name_fallback_window_skips_watermark_and_labels():
    """无标签简历：兜底窗口跳过开头水印噪声与基本信息标签词。"""
    text = "~ A 8eb50979a361c6071HB939y6E1tWx423WPuXWOGnnfDVNRNk3A~ 陈兆丰 男 28岁 本科 求职意向：QA"
    assert _extract_name(text) == "陈兆丰"


def test_gender_spaced_label():
    text = "性 别： 女 籍 贯： 福建"
    assert _extract_gender(text) == "女"


def test_gender_plain():
    assert _extract_gender("姓名：张三 性别：男") == "男"


def test_education_spaced_label():
    assert _extract_education("学 历： 硕士研究生 毕业院校：福建医科大学") == "硕士研究生"


def test_name_not_found_when_no_cjk_in_head():
    """开头无任何中文（纯噪声/英文）时返回空，交由占位与人工修改兜底。"""
    assert _extract_name("~ A 8eb50979a361c6071HB939y6E1tWx423WPuXWOGnnfDVNRNk3A~ 2023.06 Bachelor") == ""


def test_major_stops_at_watermark_noise():
    """直聘 PDF：专业值后紧跟水印噪声碎片，应只取词组本身。"""
    from app.modules.hr.resume_parser import _extract_major
    text = "邮箱：873436616@qq.com 专业：生物制药 9 1 1f 1f c c b 0 b 0 a a e e d d"
    assert _extract_major(text) == "生物制药"


def test_major_stops_at_next_section():
    from app.modules.hr.resume_parser import _extract_major
    assert _extract_major("学历：成人大专 专业：计算机应用技术 求职方向 - 制药生产技术员") == "计算机应用技术"


def test_major_spaced_value():
    from app.modules.hr.resume_parser import _extract_major
    assert _extract_major("专 业： 生 物 制 药 学 历：本科") == "生物制药"
