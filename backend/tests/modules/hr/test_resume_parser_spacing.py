"""简历解析器字段提取回归测试。

对应修复：招聘平台导出 PDF 的字距空格（「姓 名： 练 珊」）与开头水印噪声
导致姓名/性别提取失败，建档变成「未识别姓名」。
"""

import pytest

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


def test_name_fallback_adjacent_single_chars():
    """智联简历：无标签 + 姓名被字距空格拆成「翁 甜」，兜底按单字游程拼接。"""
    text = "个人简历 27岁 翁 甜 18770951892 求职意向：发酵研究员/生产工艺管理/技术支持"
    assert _extract_name(text) == "翁甜"


def test_name_fallback_plain_token():
    text = "陈兆丰 男 28岁 本科 求职意向：QA专员"
    assert _extract_name(text) == "陈兆丰"


# ─── LLM 复核开放字段（school/major） ───


@pytest.mark.asyncio
async def test_llm_enhance_overrides_keyword_major():
    """关键词兜底的专业（低置信）被 LLM 结果覆盖。"""
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {
        "school": "华中农业大学", "major": "化学",  # 「化学」为关键词猜测
        "_llm_fields": ["major"], "_llm_text_head": "教育经历 华中农业大学 农艺与种业（硕士）",
    }
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value={"school": None, "major": "农艺与种业"}),
    ):
        out = await enhance_parsed_with_llm(parsed)
    assert out["major"] == "农艺与种业"
    assert out["school"] == "华中农业大学"  # 高置信值不被覆盖
    assert "_llm_fields" not in out and "_llm_text_head" not in out  # 内部键清理


@pytest.mark.asyncio
async def test_llm_enhance_not_triggered_when_confident():
    """标签提取齐全时不调 LLM（控制成本）。"""
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {"school": "福建医科大学", "major": "生物制药", "_llm_fields": [], "_llm_text_head": "x"}
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json", new=AsyncMock()
    ) as mocked:
        out = await enhance_parsed_with_llm(parsed)
    mocked.assert_not_called()
    assert out["major"] == "生物制药"


@pytest.mark.asyncio
async def test_llm_enhance_fills_missing_school():
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {"school": "", "major": "药学", "_llm_fields": ["school"], "_llm_text_head": "正文"}
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value={"school": "中国药科大学", "major": "药学"}),
    ):
        out = await enhance_parsed_with_llm(parsed)
    assert out["school"] == "中国药科大学"


@pytest.mark.asyncio
async def test_llm_enhance_failure_keeps_rule_values():
    """LLM 失败静默降级，保留规则值且不抛异常。"""
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {"school": "", "major": "化学", "_llm_fields": ["school", "major"], "_llm_text_head": "正文"}
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(side_effect=ValueError("AI 服务连接失败")),
    ):
        out = await enhance_parsed_with_llm(parsed)
    assert out["school"] == "" and out["major"] == "化学"


@pytest.mark.asyncio
async def test_llm_enhance_rejects_overlong_value():
    """LLM 返回超长文本（>40 字符）视为污染，不写入。"""
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {"school": "", "major": "化学", "_llm_fields": ["school"], "_llm_text_head": "正文"}
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value={"school": "某大学" * 30}),
    ):
        out = await enhance_parsed_with_llm(parsed)
    assert out["school"] == ""


@pytest.mark.asyncio
async def test_llm_enhance_fills_missing_name():
    """「求职自荐书」式简历：封面全是水印、姓名无标签深藏正文，规则取不到 → LLM 补。"""
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {
        "name": "", "school": "永州职业技术学院", "major": "药学",
        "_llm_fields": ["name"], "_llm_text_head": "毕业院校：永州职业技术学院 王秀丽 专业：药学",
    }
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value={"name": "王秀丽", "school": None, "major": None}),
    ):
        out = await enhance_parsed_with_llm(parsed)
    assert out["name"] == "王秀丽"


@pytest.mark.asyncio
async def test_llm_enhance_rejects_non_name_value():
    """LLM 把标题词当姓名返回时拒绝写回（严格中文姓名形态校验）。"""
    from unittest.mock import AsyncMock, patch

    from app.modules.hr.resume_parser import enhance_parsed_with_llm
    parsed = {"name": "", "school": "", "major": "", "_llm_fields": ["name"], "_llm_text_head": "x"}
    for bad in ("求职自荐书", "药学技术岗2026", "Mr. Wang"):
        with patch(
            "app.modules.hr.ai_service.AiChatService.call_json",
            new=AsyncMock(return_value={"name": bad}),
        ):
            out = await enhance_parsed_with_llm(dict(parsed))
        assert out["name"] == "", bad


# ─── 校名提取：教育经历段落优先 + 介词前缀剥离 ───


def test_extract_school_strips_preposition_prefix():
    """教育经历叙述句「…于XX大学…」的介词不得混入校名（历史脏数据根因）。"""
    from app.modules.hr.resume_parser import _extract_school

    assert _extract_school(
        "教育经历 2018.09-2022.06 于华中农业大学 农艺与种业（硕士） 工作经历 2022.07-至今 某药企"
    ) == "华中农业大学"
    assert _extract_school("教育背景 2019.09-2023.06 就读于浙江工业大学 药学专业") == "浙江工业大学"
    assert _extract_school("2017.09-2021.06 毕业于沈阳药科大学 药学类") == "沈阳药科大学"


def test_extract_school_prefers_education_section():
    """校名优先取教育经历段，避免工作段的「xx大学附属医院」类公司名误命中。"""
    from app.modules.hr.resume_parser import _extract_school

    text = (
        "工作经历 2015-2020 任职于某某大学附属医院 药剂师 "
        "教育经历 2011-2015 考入某某学院 药学专业"
    )
    assert _extract_school(text) == "某某学院"


def test_extract_school_label_and_fallback():
    """标签提取不受剥离影响；无段落无标签时全文兜底仍可用。"""
    from app.modules.hr.resume_parser import _extract_school

    assert _extract_school("毕业院校：某某大学") == "某某大学"
    assert _extract_school("华中农业大学 农艺与种业（硕士）") == "华中农业大学"
    # 剥离后不以大学/学院结尾（脏值）返回空，交给 LLM 复核兜底
    assert _extract_school("学校：于") == ""
