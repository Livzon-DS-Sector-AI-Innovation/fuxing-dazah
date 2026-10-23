"""讲义要点卡 / 试卷 docx 渲染 — 纯函数（链2）。

讲义：标题 + 培训信息行 + 培训目标 + 章节要点 + 核心要点 + 参考资料。
试卷：单选/判断/多选/填空四节 + 参考答案页（§5.3）。样式参照 HR 试卷
排版口径（宋体/加粗层级/选项缩进）但代码独立。无 DB / 网络依赖，便于直测。
"""

from __future__ import annotations

import io
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

from app.modules.safety.ai_training_material.schemas import LectureOutput

_EMPTY = "—"


def _add_para(
    doc: Document,
    text: str,
    *,
    bold: bool = False,
    size: int = 10.5,
    center: bool = False,
) -> None:
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    run = para.add_run(text)
    run.font.bold = bold
    run.font.size = Pt(size)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def render_lecture_docx(output: LectureOutput, *, info_line: str = "") -> bytes:
    """渲染讲义要点卡 docx。

    Args:
        output: 讲义结构化内容
        info_line: 培训信息行（编排层拼装，如「类别：专项培训｜学时：4｜对象：电工」）
    """
    doc = Document()

    _add_para(doc, output.title or "培训讲义要点卡", bold=True, size=14, center=True)
    if info_line:
        _add_para(doc, info_line, size=9, center=True)

    if output.objectives:
        _add_para(doc, "培训目标", bold=True, size=12)
        for item in output.objectives:
            _add_para(doc, f"• {item}")

    for section in output.sections:
        _add_para(doc, section.heading or _EMPTY, bold=True, size=12)
        for point in section.points:
            _add_para(doc, f"• {point}")

    if output.key_takeaways:
        _add_para(doc, "核心要点", bold=True, size=12)
        for item in output.key_takeaways:
            _add_para(doc, f"★ {item}")

    if output.references:
        _add_para(doc, "参考资料", bold=True, size=12)
        for item in output.references:
            _add_para(doc, f"- {item}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_exam_docx(
    questions: dict[str, list[dict[str, Any]]],
    *,
    title: str = "培训考核试卷",
) -> bytes:
    """渲染试卷 docx：单选/判断/多选/填空四节（仅含非空节）+ 参考答案页。"""
    doc = Document()

    _add_para(doc, title, bold=True, size=14, center=True)
    _add_para(doc, "姓名：＿＿＿＿＿＿　部门：＿＿＿＿＿＿　日期：＿＿＿＿＿＿",
              size=9)

    sections: list[tuple[str, list[dict[str, Any]]]] = [
        ("一、单选题", questions.get("choice_questions") or []),
        ("二、判断题", questions.get("true_false_questions") or []),
        ("三、多选题", questions.get("multi_choice_questions") or []),
        ("四、填空题", questions.get("fill_blank_questions") or []),
    ]
    for heading, qs in sections:
        if not qs:
            continue
        _add_para(doc, f"{heading}（共{len(qs)}题）", bold=True, size=12)
        for i, q in enumerate(qs, start=1):
            _add_para(doc, f"{i}. {q.get('question', '')}")
            for opt in q.get("options") or []:
                _add_para(doc, f"    {opt.get('label', '')}. {opt.get('text', '')}", size=10)
            if heading == "二、判断题":
                _add_para(doc, "    对 □    错 □", size=10)
            if heading == "四、填空题":
                _add_para(doc, "    ____________________", size=10)

    _add_para(doc, "参考答案", bold=True, size=12)
    answer_headings = {
        "一、单选题": "choice_questions",
        "二、判断题": "true_false_questions",
        "三、多选题": "multi_choice_questions",
        "四、填空题": "fill_blank_questions",
    }
    for heading, key in answer_headings.items():
        qs = questions.get(key) or []
        if not qs:
            continue
        _add_para(doc, f"{heading}答案：", bold=True)
        for i, q in enumerate(qs, start=1):
            _add_para(doc, f"  {i}. {q.get('answer', '?')}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


__all__ = ["render_exam_docx", "render_lecture_docx"]
