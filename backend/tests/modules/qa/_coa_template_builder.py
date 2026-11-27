"""COA 模板回填测试用的仿真模板：python-docx 现搭，不依赖外部文件。

形态照着真实 COA：标题行流水号、批次信息表、项目表（表头「项目」跨两列、
大类格跨行、行内格子数不一致）、写死的「符合规定Conform」、页眉页脚。
值刻意拆成两个 run、部分值两侧带排版空白——Word/WPS 存出来的 docx 就是这样。

数据位地址（test 里直接引用）：
- P0 检验报告单 / P1 CERTIFICATE OF ANALYSIS <流水号> / P2 No. / P3 起草…
- T0 批次表：R0 批号 G1、生产日期 G3；R1 包装规格 G1、有效期 G3
- T1 项目表（结果列=G3）：R1 外观（写死符合规定Conform）、R2 水分、R3 杂质A、R4 杂质C
- H.P0 页眉、F.P0 页脚
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document


def _fill(cell: Any, *lines: str) -> None:
    cell.text = lines[0]
    for line in lines[1:]:
        cell.add_paragraph(line)


def _runs(paragraph: Any, *parts: str) -> None:
    for part in parts:
        paragraph.add_run(part)


def build_template(*, filled: bool = True, leak: bool = False) -> bytes:
    """filled=False 是空白模板（结果格为空、标题行是 XXXXXXXX）。

    leak=True 在正文末尾多加一行没标注到的「Batch No. HAF2607001A」，模拟填过值的
    模板里漏标的位置——回填后旧值泄漏扫描必须抓到它。
    """
    doc = Document()
    doc.add_paragraph("检验报告单")
    doc.add_paragraph(f"CERTIFICATE OF ANALYSIS   {'26081215' if filled else 'XXXXXXXX'}")
    doc.add_paragraph("No.:COA-HAF-3205-006")

    batch = doc.add_table(rows=2, cols=4)
    values = [
        (("批  号", "Batch No."), "HAF2607001A", ("生产日期", "Mfg. Date"), "2026.07.29"),
        (("包装规格", "Packaging"), "5kg/Tin", ("有效期", "Exp. Date"), "2028.07.28"),
    ]
    for row, (label_a, value_a, label_b, value_b) in zip(batch.rows, values, strict=True):
        cells = row.cells
        _fill(cells[0], *label_a)
        _fill(cells[1], value_a if filled else "")
        _fill(cells[2], *label_b)
        _fill(cells[3], value_b if filled else "")

    items = doc.add_table(rows=5, cols=4)
    head = items.rows[0].cells
    _fill(head[0].merge(head[1]), "项目", "Tests")
    _fill(head[2], "标准", "Specifications")
    _fill(head[3], "结果", "Results")

    row = items.rows[1].cells
    _fill(row[0], "性状", "Characters")
    _fill(row[1], "外观", "Appearance")
    _fill(row[2], "白色或类白色粉末。")
    _runs(row[3].paragraphs[0], "符合规定", "Conform")

    row = items.rows[2].cells
    _fill(row[0].merge(row[1]), "水分", "Water")
    _fill(row[2], "≤5.0%")
    if filled:
        _runs(row[3].paragraphs[0], "0.", "63%")

    row = items.rows[3].cells
    _fill(row[0], "有关物质", "Related substances")
    _fill(row[1], "杂质A-RRT约0.76", "Impurity A (RRT 0.76)")
    _fill(row[2], "≤3.0%")
    if filled:
        _runs(row[3].paragraphs[0], "\u2002\u2002", "0.", "23%", "\u2002\u2002\u2002")

    row = items.rows[4].cells
    row[0].merge(items.rows[3].cells[0])
    _fill(row[1], "杂质C-RRT约1.86", "Impurity C (RRT 1.86)")
    _fill(row[2], "≤1.0%")
    if filled:
        _runs(row[3].paragraphs[0], "0.", "05%")

    doc.add_paragraph("起草(QC):              审核（RA）：              批准（QA):")
    if leak:
        doc.add_paragraph("Batch No. HAF2607001A")
    doc.sections[0].header.paragraphs[0].text = "丽珠集团福州福兴医药有限公司"
    doc.sections[0].footer.paragraphs[0].text = "LIVZON GROUP FUZHOU FUXING PHARMACEUTICAL CO., LTD."
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
