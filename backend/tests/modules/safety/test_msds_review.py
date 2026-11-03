"""MSDS 错别字审核 + 修订同步机制测试（2026-10-30）。

纯单测（零 DB/零真机）：hash 判定矩阵、entry 反查（外观列新旧名兼容、
富文本段兜底）、_map_fields 新旧列共存不覆盖、AI 校对输出过滤与格式化、
修订记录裁剪。接缝：create_ai_service 替身（chat_parsed 假返回）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.feishu.msds_bitable_handler import _map_fields
from app.modules.safety.service.msds_review import (
    FIELD_TYPO_DETAIL,
    FIELD_TYPO_STATUS,
    REVISION_LOG_MAX_LINES,
    TYPO_STATUS_CLEAN,
    TYPO_STATUS_SUSPECT,
    append_revision_log,
    decide_pdf_sync,
    entry_from_bitable_fields,
    format_typo_detail,
    msds_content_hash,
    proofread_entry,
    typo_review_fields,
    _validate_issues,
)


# ── 内容 hash ──


def test_content_hash_stable_and_whitespace_normalized():
    a = {"name": "乙醇", "appearance": "无色液体"}
    b = {"name": "乙醇", "appearance": "无色 液体\n"}  # 仅空白差异
    c = {"name": "乙醇", "appearance": "无色液体，有酒香"}  # 实质修改
    assert msds_content_hash(a) == msds_content_hash(b)
    assert msds_content_hash(a) != msds_content_hash(c)


def test_content_hash_independent_of_extra_keys():
    a = {"name": "乙醇"}
    b = {"name": "乙醇", "msds_attachment": [{"x": 1}]}
    # 附件/日期不参与内容比对；标签要素 2026-11-02 起入内容面（改列→PDF 追平）
    assert msds_content_hash(a) == msds_content_hash(b)
    assert msds_content_hash(a) != msds_content_hash({**a, "label_elements": "图形：火焰"})


# ── 同步判定矩阵 ──


@pytest.mark.parametrize(
    "current,pdf,marker,force,expected",
    [
        ("h1", "h1", None, False, "skip_up_to_date"),
        ("h1", "h1", "h1", False, "skip_up_to_date"),  # up_to_date 优先
        ("h1", "h0", "h1", False, "skip_self_write"),
        ("h1", None, None, False, "regenerate"),  # 存量行无 hash
        ("h1", "h0", None, False, "regenerate"),  # 人工修改
        ("h1", "h0", "h2", False, "regenerate"),  # 标记过期不匹配
        ("h1", "h1", None, True, "regenerate"),  # force 恒重建
    ],
)
def test_decide_pdf_sync(current, pdf, marker, force, expected):
    assert decide_pdf_sync(current, pdf, marker, force=force) == expected


# ── Bitable fields → entry ──


def test_entry_from_bitable_fields_new_and_legacy_appearance():
    base = {"物质名称": "乙醇", "CAS号": "64-17-5"}
    assert entry_from_bitable_fields({**base, "外观与性状": "无色液体"})["appearance"] == "无色液体"
    # 旧列名环境（未改名）回落
    assert entry_from_bitable_fields({**base, "外观与现状": "无色液体"})["appearance"] == "无色液体"
    # 新列优先，旧列空值不覆盖
    both = entry_from_bitable_fields(
        {**base, "外观与性状": "无色液体", "外观与现状": ""}
    )
    assert both["appearance"] == "无色液体"


def test_entry_from_bitable_fields_rich_text_segments():
    fields = {"物质名称": [{"text": "乙", "type": "text"}, {"text": "醇", "type": "text"}]}
    assert entry_from_bitable_fields(fields)["name"] == "乙醇"


def test_entry_from_bitable_fields_excludes_non_content_columns():
    entry = entry_from_bitable_fields({
        "物质名称": "乙醇",
        "标签要素": "图形：火焰；信号词：危险",
        "日期": 1785945600000,
        "MSDS附件": [{"file_token": "x"}],
        "错别字审核": "疑似错别字",
        "修订记录": "2026-10-30 …",
    })
    assert set(entry) == {"name", "label_elements"}
    assert "typo_review_status" not in entry and "source_date" not in entry


# ── 镜像映射（新旧列共存 + 审核字段）──


def test_map_fields_appearance_fallback_no_overwrite():
    legacy = _map_fields({"外观与现状": "无色液体"})
    modern = _map_fields({"外观与性状": "无色液体"})
    both = _map_fields({"外观与性状": "无色液体", "外观与现状": None})
    assert legacy["appearance"] == modern["appearance"] == both["appearance"] == "无色液体"


def test_map_fields_includes_review_and_revision_columns():
    mapped = _map_fields({
        "物质名称": "乙醇",
        "错别字审核": "疑似错别字",
        "错别字明细": "「急救措施」：『迅术』→『迅速』（形近字）",
        "修订记录": "2026-10-30 15:04 内容字段已修改，标准 PDF 已同步重新生成",
    })
    assert mapped["typo_review_status"] == "疑似错别字"
    assert "迅术" in mapped["typo_review_detail"]
    assert "PDF" in mapped["revision_log"]


# ── 校对输出 ──


def test_validate_issues_filters_unknown_field_and_dups():
    raw = [
        {"field": "急救措施", "original": "迅术脱离", "suggestion": "迅速脱离", "reason": "形近字"},
        {"field": "不存在的字段", "original": "x", "suggestion": "y"},  # 字段名不在清单 → 丢
        {"field": "急救措施", "original": "同样", "suggestion": "同样"},  # 原文=建议 → 丢
        {"field": "健康危害", "original": "", "suggestion": "y"},  # 空片段 → 丢
        "garbage-string",  # 非 dict → 丢
    ]
    valid = _validate_issues(raw)
    assert len(valid) == 1
    assert valid[0]["field"] == "急救措施"


def test_validate_issues_accepts_english_field_key():
    # AI 偶尔回传英文 key 也认（known_fields 含 key 面）
    valid = _validate_issues([
        {"field": "first_aid", "original": "迅术脱离", "suggestion": "迅速脱离"},
    ])
    assert valid and valid[0]["field"] == "first_aid"


def test_typo_review_fields_status_and_detail():
    from app.modules.safety.service.msds_review import TYPO_STATUS_AUTOFIXED

    applied = [{
        "field": "急救措施", "original": "迅术", "suggestion": "迅速",
        "reason": "形近字", "confidence": "high", "key": "first_aid",
    }]
    flagged = [{
        "field": "健康危害", "original": "吸入后对鼻、喉有刺激性",
        "suggestion": "（语义级改动建议）", "reason": "疑似", "confidence": "low",
    }]
    # 有已修正 → 已自动修正；明细分段（已自动修正 + 待人工复核）
    fields = typo_review_fields(applied, flagged)
    assert fields[FIELD_TYPO_STATUS] == TYPO_STATUS_AUTOFIXED
    assert "已自动修正" in fields[FIELD_TYPO_DETAIL]
    assert "『迅术』→『迅速』" in fields[FIELD_TYPO_DETAIL]
    assert "待人工复核" in fields[FIELD_TYPO_DETAIL]
    # 仅待人工 → 疑似错别字
    fields2 = typo_review_fields([], flagged)
    assert fields2[FIELD_TYPO_STATUS] == TYPO_STATUS_SUSPECT
    # 全空 → 无错别字
    assert typo_review_fields([], []) == {
        FIELD_TYPO_STATUS: TYPO_STATUS_CLEAN, FIELD_TYPO_DETAIL: "",
    }
    # 旧「仅 issues」调用形态兼容（视为全 flagged）
    assert typo_review_fields(issues=flagged)[FIELD_TYPO_STATUS] == TYPO_STATUS_SUSPECT


def test_apply_issues_autofix_and_flag():
    from app.modules.safety.service.msds_review import apply_issues

    entry = {
        "first_aid": "吸入：迅术脱离现场至空气新鲜处。眼晴接触时立即冲洗。",
        "health_hazard": "长期接触可引起过敏性皮炎样改变。",
    }
    issues = [
        # high：1 字形近替换 → 自动修正
        {"field": "急救措施", "original": "迅术", "suggestion": "迅速",
         "reason": "形近字", "confidence": "high"},
        # high：但原文在字段中不存在 → 降级待人工（防误定位）
        {"field": "急救措施", "original": "吸入佳", "suggestion": "吸入后",
         "reason": "形近字", "confidence": "high"},
        # low：只标记不改
        {"field": "健康危害", "original": "皮炎样", "suggestion": "皮疹样",
         "reason": "疑似", "confidence": "low"},
        # 中文标签字段名同样可定位
        {"field": "急救措施", "original": "眼晴", "suggestion": "眼睛",
         "reason": "形近字", "confidence": "high"},
    ]
    fixed, applied, flagged = apply_issues(entry, issues)
    assert fixed["first_aid"] == "吸入：迅速脱离现场至空气新鲜处。眼睛接触时立即冲洗。"
    assert fixed["health_hazard"] == entry["health_hazard"]  # low 未改
    assert {a["original"] for a in applied} == {"迅术", "眼晴"}
    assert {f["original"] for f in flagged} == {"吸入佳", "皮炎样"}


def test_format_typo_detail_empty():
    assert format_typo_detail([], []) == ""
    assert format_typo_detail() == ""


# ── 修订记录裁剪 ──


def test_append_revision_log_caps_lines():
    existing = "\n".join(f"2026-01-01 00:0{i} 第{i}行" for i in range(REVISION_LOG_MAX_LINES))
    appended = append_revision_log(existing, "新一行")
    lines = appended.splitlines()
    assert len(lines) == REVISION_LOG_MAX_LINES
    assert lines[-1].endswith("新一行")
    assert "第0行" not in appended  # 最旧行被裁


def test_append_revision_log_rich_text_segments():
    appended = append_revision_log([{"text": "2026-10-30 旧记录"}], "第二条")
    assert "旧记录" in appended and "第二条" in appended


# ── AI 校对接缝（create_ai_service 替身）──


class _FakeAI:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload
        self.calls: list[dict] = []

    async def chat_parsed(self, messages, expected_keys=None, temperature=None):
        self.calls.append({"messages": messages, "expected_keys": expected_keys})
        return self._payload

    async def close(self):
        return None


@pytest.fixture()
def fake_ai_factory(monkeypatch):
    holder: dict[str, _FakeAI] = {}

    def _install(payload: dict[str, Any]) -> _FakeAI:
        ai = _FakeAI(payload)
        holder["ai"] = ai

        import app.modules.safety.service.config as cfg

        monkeypatch.setattr(cfg, "create_ai_service", lambda *a, **k: ai)
        return ai

    yield _install


async def test_proofread_entry_returns_validated_issues(fake_ai_factory):
    ai = fake_ai_factory({"issues": [
        {"field": "急救措施", "original": "迅术脱离", "suggestion": "迅速脱离", "reason": "形近字"},
        {"field": "未知字段", "original": "a", "suggestion": "b"},
    ]})
    issues = await proofread_entry({"name": "乙醇", "first_aid": "吸入：迅术脱离现场。"})
    assert len(issues) == 1
    assert issues[0]["suggestion"] == "迅速脱离"
    # 只传非空字段给 AI
    sent = ai.calls[0]["messages"][1]["content"]
    assert "乙醇" in sent and "急救措施" in sent


async def test_proofread_entry_skips_empty_entry(fake_ai_factory):
    fake_ai_factory({"issues": []})
    assert await proofread_entry({}) == []


async def test_proofread_entry_none_issues_tolerated(fake_ai_factory):
    fake_ai_factory({"issues": None})
    assert await proofread_entry({"name": "乙醇"}) == []


# ── 标准 PDF 单页契约（打印需求，2026-10-30）──


def test_standard_pdf_single_page(tmp_path):
    """常规与超长内容都必须输出单页（自适应缩放 + 极端截断安全阀）。"""
    pypdf = pytest.importorskip("pypdf")
    from app.modules.safety.feishu.msds_pdf import build_standard_msds_pdf

    base = {
        "name": "乙醇；酒精", "cas_no": "64-17-5", "molecular_formula": "C2H6O",
        "un_no": "1170", "hazard_statement": "高度易燃液体和蒸气，其蒸气与空气混合,能形成爆炸性混合物。",
        "appearance": "无色液体,有酒香。", "solubility": "与水混溶。",
        "melting_point": "-114.1℃", "boiling_point": "78.3℃", "flash_point": "13℃（CC）",
        "relative_density": "1.59", "explosion_upper_limit": "19.0", "explosion_lower_limit": "3.3",
        "autoignition_temperature": "363℃", "decomposition_temperature": "无资料",
        "pc_twa": "1000ppm", "pc_stel": "/", "mac": "/",
        "health_hazard": "本品为中枢神经系统抑制剂。" * 20,
        "first_aid": "皮肤接触：立即脱去污染的衣着,用流动清水彻底冲洗。就医。" * 10,
        "fire_fighting": "灭火剂:用抗溶性泡沫、干粉、二氧化碳、砂土灭火。" * 8,
        "leakage_response": "消除所有点火源。根据液体流动和蒸气扩散的影响区域划定警戒区。" * 8,
        "waste_disposal": "废弃化学品：建议用焚烧法处置。" * 6,
        "exposure_controls": "工程控制：生产过程密闭,加强通风。" * 8,
        "handling_storage": "操作注意事项：密闭操作,全面通风。" * 10,
        "stability_reactivity": "稳定性稳定 禁配物强氧化剂、酸类、酸酐、碱金属、胺类。" * 6,
        "environmental_hazard": "对水生环境有害。" * 6,
    }
    out1 = tmp_path / "normal.pdf"
    build_standard_msds_pdf(base, str(out1))
    assert len(pypdf.PdfReader(str(out1)).pages) == 1

    extreme = {k: (v * 30 if isinstance(v, str) else v) for k, v in base.items()}
    out2 = tmp_path / "extreme.pdf"
    build_standard_msds_pdf(extreme, str(out2))
    assert len(pypdf.PdfReader(str(out2)).pages) == 1


# ── PDF 文本规范化（分子式上下标修复，2026-11-02）──


def test_rich_markup_subscript_conversion():
    from app.modules.safety.feishu.msds_pdf import _rich_markup

    # Unicode 下标 → <sub>（STSong-Light 无 U+208x 字形，MgSO₄ 原样渲染丢 ₄）
    assert _rich_markup("MgSO₄") == "MgSO<sub>4</sub>"
    assert _rich_markup("MnO₂") == "MnO<sub>2</sub>"
    # 连续下标合并一个标记
    assert _rich_markup("C₂H₆O") == "C<sub>2</sub>H<sub>6</sub>O"
    # 上标（mg/m³ 类）与中点保留
    assert _rich_markup("mg/m³") == "mg/m<sup>3</sup>"
    assert _rich_markup("NH₃·H₂O") == "NH<sub>3</sub>·H<sub>2</sub>O"


def test_rich_markup_invisible_chars_and_escape():
    from app.modules.safety.feishu.msds_pdf import _rich_markup

    # AI 提取残留零宽字符删除
    assert _rich_markup("C4\u200bH6\u200bCaO4") == "C4H6CaO4"
    # XML 转义仍生效
    assert _rich_markup("a<b>&c") == "a&lt;b&gt;&amp;c"
    assert _rich_markup("") == ""


# ── 标签要素 GHS 规则推导（2026-11-02）──


def test_derive_label_elements_flammable():
    from app.modules.safety.service.msds_review import derive_label_elements

    # 「爆炸性混合物」是易燃蒸气特性描述，不是爆炸物类别 → 只给火焰
    r = derive_label_elements({
        "hazard_statement": "高度易燃液体和蒸气，其蒸气与空气混合能形成爆炸性混合物。",
    })
    assert "火焰" in r and "爆炸" not in r and "信号词：危险" in r


def test_derive_label_elements_corrosive_warning_dominance():
    from app.modules.safety.service.msds_review import derive_label_elements

    # 腐蚀（危险）+ 刺激（警告）→ 信号词取最高级别"危险"，图形按名去重
    r = derive_label_elements({
        "hazard_statement": "造成严重皮肤灼伤和眼损伤。",
        "health_hazard": "可引起呼吸道刺激。",
    })
    assert "腐蚀" in r and "感叹号" in r and "信号词：危险" in r
    assert r.count("感叹号") == 1  # 同图形多类别命中只出现一次


def test_derive_label_elements_negative_and_empty():
    from app.modules.safety.service.msds_review import derive_label_elements

    # 「不燃/不危险性分类」类物质不给火焰（描述词宽匹配负向排除）
    r = derive_label_elements({
        "hazard_statement": "根据全球统一制度，该化学品不危险性分类。",
        "health_hazard": "吞咽可能有害。",
    })
    assert "火焰" not in r
    assert derive_label_elements({"hazard_statement": "无资料"}) == ""
    assert derive_label_elements({}) == ""


def test_derive_label_elements_shape():
    from app.modules.safety.service.msds_review import derive_label_elements

    r = derive_label_elements({"name": "硫酸", "hazard_statement": "造成皮肤腐蚀"})
    assert r.startswith("图形：") and "；信号词：" in r


# ── 黑体注册（缺字体环境回退不炸）──


def test_heiti_font_registered_or_fallback():
    from app.modules.safety.feishu import msds_pdf

    assert msds_pdf._HEITI in ("NotoSansSC", "STSong-Light")
    styles = msds_pdf._scaled_styles(1.0)
    # 顶部表头黑体居中（docx 模板基准：bold+黑体+居中）
    from reportlab.lib.enums import TA_CENTER

    assert styles["label_top"].alignment == TA_CENTER
    assert styles["value_top"].alignment == TA_CENTER
    assert styles["section_head"].alignment == TA_CENTER


def test_rich_markup_cjk_gap_and_punctuation():
    """中文排版规范化：断词残留清除 + CJK 间半角标点全角化（2026-11-02 审计批）。"""
    from app.modules.safety.feishu.msds_pdf import _rich_markup

    # 供应商 PDF 断行残留（换行/空格夹在 CJK 之间）
    assert _rich_markup("呼吸道刺\n激性气味") == "呼吸道刺激性气味"
    assert _rich_markup("建 议操作人员") == "建议操作人员"
    # 半角标点任一侧是 CJK 即转全角（含标点后接拉丁：非常大,L）
    assert _rich_markup("眼损伤,可能") == "眼损伤，可能"
    assert _rich_markup("氨溶液;氨水") == "氨溶液；氨水"
    assert _rich_markup("毒性非常大,LC") == "毒性非常大，LC"
    # 两侧都是数字/拉丁不动（3.5、13:00、20 mg/m3、1,2-丙二醇安全）
    assert _rich_markup("13:00") == "13:00"
    assert _rich_markup("1,2-丙二醇") == "1,2-丙二醇"
    assert _rich_markup("沸点 38.3℃") == "沸点 38.3℃"
    # m3 单位上标（参考《丁醇》实测 5.8pt 上标），两侧数字/拉丁其余不动
    assert _rich_markup("20 mg/m3") == "20 mg/m<sup>3</sup>"
    # 半角引号配对全角化（含已有全角引号的状态承接）；escape 实体不被全角化破坏
    assert _rich_markup("这种\"物质\"有危险") == "这种“物质”有危险"
    assert _rich_markup("可发生“金属烟热\"，病人") == "可发生“金属烟热”，病人"
    assert _rich_markup("全角“对”没问题") == "全角“对”没问题"
    # 组合：断词 + 半角 + 上下标一起
    assert _rich_markup("对水生 生物毒性非常大,LC₅₀") == "对水生生物毒性非常大，LC<sub>50</sub>"


def test_environmental_hazard_rendered(tmp_path):
    """环境危害字段有值必须上 PDF（内容完整性审计 27 处缺漏的回归锚）。"""
    pypdf = pytest.importorskip("pypdf")
    from app.modules.safety.feishu.msds_pdf import build_standard_msds_pdf

    entry = {
        "name": "测试环境危害", "cas_no": "67-64-1",
        "health_hazard": "轻度刺激。",
        "environmental_hazard": "对环境可能有害。",
    }
    out = tmp_path / "env.pdf"
    build_standard_msds_pdf(entry, str(out))
    text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(str(out)).pages)
    assert "对环境可能有害" in text.replace("\n", "")


# ── 分子式下标 + GHS 象形图 + 静态字体（2026-11-02 业务反馈批）──


def test_formula_markup_plain_digits_to_subscript():
    from app.modules.safety.feishu.msds_pdf import _formula_markup

    # 普通数字形态 → 下标（业务反馈"识别成大数字"根因）
    assert _formula_markup("C2H6O") == "C<sub>2</sub>H<sub>6</sub>O"
    assert _formula_markup("CH4O") == "CH<sub>4</sub>O"
    # Unicode 下标形态保持（已转 sub 不二次处理）
    assert _formula_markup("MgSO₄") == "MgSO<sub>4</sub>"
    # 行首系数不下标；·中点保留
    assert _formula_markup("2H2O·SiO2") == "2H<sub>2</sub>O·SiO<sub>2</sub>"
    # 右括号后数字（配位）下标
    assert _formula_markup("(C2H5)2") == "(C<sub>2</sub>H<sub>5</sub>)<sub>2</sub>"


def test_parse_label_elements():
    from app.modules.safety.feishu.msds_pdf import _parse_label_elements

    names, sig = _parse_label_elements("图形：火焰、感叹号；信号词：危险")
    assert names == ["火焰", "感叹号"] and sig == "危险"
    # 宽容人工填写：图形名子串匹配；未知图形跳过；无信号词返回空
    names, sig = _parse_label_elements("图形：骷髅和交叉骨（急性毒性）,环境 信号词：警告")
    assert names == ["骷髅和交叉骨", "环境"] and sig == "警告"
    assert _parse_label_elements("随便写的文本") == ([], "")
    assert _parse_label_elements("") == ([], "")


def test_heiti_font_is_static_not_variable():
    """黑体必须用静态实例：原 NotoSansSC.ttf 是 VF（默认 wght=100 Thin），
    reportlab 按 100 极细渲染=「淡黑色」+ 子集嵌入部分阅读器乱码。"""
    from app.modules.safety.feishu import msds_pdf

    if msds_pdf._HEITI == "NotoSansSC":
        from fontTools.ttLib import TTFont as FT

        path = next(
            p for p in (
                __import__("pathlib").Path("assets/fonts/NotoSansSC-Medium.ttf"),
            ) if p.exists()
        )
        ft = FT(str(path))
        assert "fvar" not in ft, "不得使用可变字体"
        assert ft["OS/2"].usWeightClass == 500


def test_label_elements_ghs_images_rendered(tmp_path):
    """标签要素渲染为象形图网格（图片形式）+ 信号词，PDF 可生成且单页。"""
    pypdf = pytest.importorskip("pypdf")
    from app.modules.safety.feishu.msds_pdf import build_standard_msds_pdf

    entry = {
        "name": "测试象形图", "cas_no": "64-17-5", "un_no": "1170",
        "label_elements": "图形：火焰、感叹号、环境；信号词：危险",
    }
    out = tmp_path / "ghs.pdf"
    build_standard_msds_pdf(entry, str(out))
    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 1
    # 图片存在性：页面资源含 XObject 图像
    xo = reader.pages[0].get("/Resources", {}).get("/XObject", {})
    assert xo and len(xo) >= 3, "应嵌入至少 3 张象形图"
    text = "".join(p.extract_text() or "" for p in reader.pages).replace("\n", "")
    assert "信号词：危险" in text
