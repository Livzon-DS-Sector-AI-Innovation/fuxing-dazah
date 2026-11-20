"""峰表提取器单元测试：markdown 竖线表 + HTML 表（MinerU VLM 实际输出形态）+ 空峰名兜底。

HTML 样例取自真实图谱截图（2026-11-19 B-1 样本验收）：VLM 输出 <table>、
名称列 24 行仅 1 行有值——序号兜底「峰N」是可用前提。
"""

from app.modules.quality.service.chromatogram import extract_peak_table

# 真实样本 20261103-135522.jpeg 的 VLM 输出结构（截取前 3 行数据）
_HTML_MD = """峰结果
![](images/xxx.jpg)

<table><tr><td></td><td>名称</td><td>保留时间(分钟)</td><td>面积(微伏*秒)</td><td>面积%</td><td>理论塔板数</td><td>高度(微伏)</td></tr><tr><td>1</td><td></td><td>2.313</td><td>27835</td><td>0.08</td><td>3257</td><td>3372</td></tr><tr><td>2</td><td>万古霉素B</td><td>5.879</td><td>273149</td><td>78.4</td><td>5274</td><td>22079</td></tr><tr><td>3</td><td></td><td>6.553</td><td>8430</td><td>2.42</td><td>3588</td><td>995</td></tr></table>
"""

_MD_TABLE = """# 图谱报告

| 峰名 | 面积 |
| --- | --- |
| 万古霉素B | 1000.5 |
| 杂质F | 20.3 |
"""


def test_extract_from_markdown_pipe_table() -> None:
    peaks = extract_peak_table(_MD_TABLE)
    assert [(p["name"], p["area"]) for p in peaks] == [("万古霉素B", 1000.5), ("杂质F", 20.3)]


def test_extract_from_html_table() -> None:
    """VLM 输出 HTML 表：识别列头、原始面积列优先（避开 %面积）、保留时间。"""
    peaks = extract_peak_table(_HTML_MD)
    assert len(peaks) == 3
    # 序号兜底峰名
    assert peaks[0]["name"] == "峰1"
    assert peaks[0]["area"] == 27835.0  # 原始面积列（微伏*秒），不是 % 列的 0.08
    assert peaks[0]["rt"] == 2.313
    # 有名称的行保持原名
    assert peaks[1]["name"] == "万古霉素B"
    assert peaks[1]["area"] == 273149.0
    assert peaks[2]["name"] == "峰3"


def test_html_and_pipe_tables_merged() -> None:
    """两种表并存（多页 PDF 各一段）：全部提取。"""
    peaks = extract_peak_table(_MD_TABLE + "\n" + _HTML_MD)
    assert len(peaks) == 5


def test_row_without_name_or_seq_skipped() -> None:
    md = """<table><tr><td>名称</td><td>面积</td></tr><tr><td></td><td></td></tr><tr><td></td><td>abc</td></tr></table>"""
    # 无名称且无纯数字序号的行跳过（abc 不是序号）
    peaks = extract_peak_table(md)
    assert peaks == []


def test_numeric_only_row_gets_seq_fallback_name() -> None:
    md = """<table><tr><td>名称</td><td>面积</td></tr><tr><td></td><td>123</td></tr></table>"""
    # 只有数字的行：数字即序号兜底（峰123），检验员在弹窗里改名或删行
    peaks = extract_peak_table(md)
    assert peaks == [{"name": "峰123", "area": 123.0, "rt": None}]
