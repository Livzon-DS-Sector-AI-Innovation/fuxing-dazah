"""培训成绩单 Word 文档生成器 — 基于 {标记} 模板（模板可由用户自维护）。

模板标记清单见 training_template_registry（键 score_report）：
表头之下含 {姓名} 的数据行是模板行，系统按人数克隆填充：
{序号} {姓名} {部门} {总分}。模板行之外多余的数据行清空保留（与历史行为一致）。
"""

from copy import deepcopy
from io import BytesIO

from docx import Document

from app.modules.hr.docx_markers import (
    clear_unused_markers,
    find_row_index_by_marker,
    replace_markers_in_row,
    set_cell_text,
)
from app.modules.hr.template_utils import find_hr_template_bytes

NAME_ANCHOR = "{姓名}"


def _score_row_mapping(idx: int, entry: dict) -> dict[str, str]:
    return {
        "{序号}": str(idx + 1),
        "{姓名}": entry.get("name", ""),
        "{部门}": entry.get("department", ""),
        "{总分}": str(entry.get("total_score", "")),
    }


def generate_score_report(
    *,
    training_content: str = "",
    training_date: str = "",
    department: str = "",
    scores: list[dict] | None = None,
    template_bytes: bytes | None = None,
) -> BytesIO:
    """生成成绩单，按人数自动追加行。scores: [{name, department, total_score}]"""
    raw = template_bytes or find_hr_template_bytes("score_report")
    doc = Document(BytesIO(raw))
    table = doc.tables[0]
    scores = scores or []

    anchor_idx = find_row_index_by_marker(table, NAME_ANCHOR)
    if anchor_idx is None:
        raise ValueError("成绩单模板缺少 {姓名} 数据模板行")
    tpl_row = table.rows[anchor_idx]
    anchor_tr = tpl_row._tr

    # 先克隆出其余数据行（干净模板行），再逐行填充
    for _ in range(len(scores) - 1):
        anchor_tr.addnext(deepcopy(anchor_tr))
    for ri, entry in enumerate(scores):
        replace_markers_in_row(table.rows[anchor_idx + ri], _score_row_mapping(ri, entry))
    if not scores:
        # 无数据时模板行清空（保留空行，与历史行为一致）
        for cell in tpl_row.cells:
            set_cell_text(cell, "")

    # 清空数据块之外的旧数据行（模板若带预留空白行则保留为空行）
    for ri in range(anchor_idx + max(len(scores), 1), len(table.rows)):
        for cell in table.rows[ri].cells:
            set_cell_text(cell, "")

    clear_unused_markers(doc)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
