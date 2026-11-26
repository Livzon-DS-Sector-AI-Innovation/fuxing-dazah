"""现场问答/实操记录表 Word 文档生成器 — 基于 {标记} 模板（模板可由用户自维护）。

模板标记清单见 training_template_registry（键 qa_record）：
- 头部：{培训内容} {实施日期} {培训方式} {培训对象} {培训目的}
- 考题模板行（以 {题目} 定位）：{$index+1} {文件编号} {题目} {正确答案} {分值}
- 受训人模板行（以 {姓名} 定位）：{姓名} {答题结果} {考核日期} {总分}
考题区/受训人区按数据条数克隆模板行；无考题时考题区保留空白行供打印后手写。
"""

import copy
from datetime import date
from io import BytesIO

from docx import Document

from app.modules.hr.docx_markers import (
    clear_unused_markers,
    find_row_index_by_marker,
    remove_row,
    replace_markers,
    replace_markers_in_row,
    set_cell_text,
)
from app.modules.hr.template_utils import find_hr_template_bytes

# 无题目导出时，考题区保留的空白行数（供打印后手写）
_BLANK_QUESTION_ROWS = 5

QUESTION_ANCHOR = "{题目}"
TRAINEE_ANCHOR = "{姓名}"


def _clone_row_after(table, tpl_tr, after_tr) -> None:
    """在 after_tr 之后深拷贝插入一行（样式随模板行）。"""
    after_tr.addnext(copy.deepcopy(tpl_tr))


def _row_fill_mapping(entry: dict) -> dict[str, str]:
    return {
        "{$index+1}": str(entry.get("seq", "")),
        "{文件编号}": entry.get("file_no", ""),
        "{题目}": entry.get("question", ""),
        "{正确答案}": entry.get("answer", ""),
        "{分值}": str(entry.get("score", "")),
    }


def _trainee_fill_mapping(entry: dict) -> dict[str, str]:
    return {
        "{姓名}": entry.get("name", ""),
        "{答题结果}": entry.get("result_text", ""),
        "{考核日期}": entry.get("assessed_date", ""),
        "{总分}": entry.get("total_score", ""),
    }


def generate_qa_record(
    *,
    training_content: str = "",
    training_purpose: str = "",
    training_date: date | None = None,
    training_method: str = "",
    training_department: str = "",
    questions: list[dict] | None = None,
    trainee_names: list[str] | None = None,
    scores: list[dict] | None = None,
    trainer_name: str = "",
    template_bytes: bytes | None = None,
) -> BytesIO:
    """生成现场问答/实操记录表（marker-based）。"""
    raw = template_bytes or find_hr_template_bytes("qa_record")
    doc = Document(BytesIO(raw))
    table = doc.tables[0]

    date_str = str(training_date) if training_date else ""
    questions = questions or []
    trainee_names = trainee_names or []

    # ── 头部标记 ──
    replace_markers(doc, {
        "{培训内容}": training_content or "",
        "{实施日期}": date_str,
        "{培训方式}": training_method or "",
        "{培训对象}": training_department or "",
        "{培训目的}": training_purpose or "",
    })

    # ── 考题区域 ──
    q_tpl_idx = find_row_index_by_marker(table, QUESTION_ANCHOR)
    if q_tpl_idx is not None:
        q_tpl_tr = table.rows[q_tpl_idx]._tr
        if questions:
            entries = [
                {**q, "seq": qi}
                for qi, q in enumerate(questions, start=1)
            ]
            # 先克隆出其余数据行（保持干净模板行），再逐行填充
            after_tr = q_tpl_tr
            for _ in entries[1:]:
                _clone_row_after(table, q_tpl_tr, after_tr)
                after_tr = after_tr.getnext()
            for qi, entry in enumerate(entries):
                replace_markers_in_row(table.rows[q_tpl_idx + qi], _row_fill_mapping(entry))
            # 删除模板自带的空白行（紧随数据块之后的那一行）
            empty_row_idx = q_tpl_idx + len(entries)
            if empty_row_idx < len(table.rows):
                remove_row(table, empty_row_idx)
        else:
            # 没有题目：清空模板行并补足空白行供打印后手写
            for cell in table.rows[q_tpl_idx].cells:
                set_cell_text(cell, "")
            after_tr = q_tpl_tr
            for _ in range(_BLANK_QUESTION_ROWS - 1):
                _clone_row_after(table, q_tpl_tr, after_tr)
                after_tr = after_tr.getnext()
            # 删除模板自带的空行（现在位于空白块之后）
            empty_row_idx = q_tpl_idx + _BLANK_QUESTION_ROWS
            if empty_row_idx < len(table.rows):
                remove_row(table, empty_row_idx)
        # 模板行本身保留（有题时它是第一道题，无题时是第一个空白行）

    # ── 受训人员区域 ──
    t_tpl_idx = find_row_index_by_marker(table, TRAINEE_ANCHOR)
    if t_tpl_idx is not None:
        t_tpl_tr = table.rows[t_tpl_idx]._tr
        entries = (
            [dict(s) for s in scores]
            if scores
            else [{"name": n} for n in trainee_names]
        )
        if entries:
            after_tr = t_tpl_tr
            for _ in entries[1:]:
                _clone_row_after(table, t_tpl_tr, after_tr)
                after_tr = after_tr.getnext()
            for ei, entry in enumerate(entries):
                replace_markers_in_row(table.rows[t_tpl_idx + ei], _trainee_fill_mapping(entry))
        else:
            # 无数据：清空模板行保留空白行（与历史行为一致）
            for cell in table.rows[t_tpl_idx].cells:
                set_cell_text(cell, "")

    clear_unused_markers(doc)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
