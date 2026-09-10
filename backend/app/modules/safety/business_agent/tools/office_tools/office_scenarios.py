"""办公场景辅助：markdown→docx blocks 与本地 docx/pdf 生成。"""

from __future__ import annotations

import html
import re
from io import BytesIO
from typing import Any

from app.modules.safety.feishu.docx_blocks import (
    build_bullet,
    build_divider,
    build_heading,
    build_ordered,
    build_text_block,
)


def build_report_docx_blocks(title: str, markdown_report: str) -> list[dict]:
    """把 Markdown 日报/报表转成飞书 docx blocks（供 office_create_docx 复用）。

    场景模板「日报 → 飞书云文档 → 推群」：模型先用报表工具生成
    markdown_report，再调用本函数得到 blocks，最后传给 office_create_docx
    创建云文档并返回可编辑链接。

    转换规则：
      - ``#`` / ``##`` / ``###`` → 标题块（H1/H2/H3）
      - ``---`` / ``***`` / ``___`` → 分割线
      - ``- `` / ``* `` / ``• `` → 无序列表（纯文本块）
      - ``1. `` 等有序列表 → 文本块（docx children API 不直接支持 ordered）
      - 其它行 → 普通文本块
    标题会固定作为文档首块（H1）。
    """
    blocks: list[dict] = []
    if title.strip():
        blocks.append(build_heading(title.strip(), level=1))

    for raw in (markdown_report or "").split("\n"):
        line = raw.strip()
        if not line:
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            blocks.append(build_heading(heading_match.group(2), level=level))
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
            blocks.append(build_divider())
            continue

        if re.match(r"^[-*•]\s+", line):
            blocks.append(build_bullet(line))
            continue

        if re.match(r"^\d+[\.\、）)]\s*", line):
            blocks.append(build_ordered(line))
            continue

        blocks.append(build_text_block(line))

    return blocks


def _generate_docx(
    title: str,
    content: str,
    sections: list[dict] | None,
) -> bytes:
    """用 python-docx 生成通用 .docx 文件。"""
    from docx import Document

    doc = Document()
    doc.add_heading(title or "未命名文档", level=0)

    if sections:
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = section.get("heading") or section.get("title") or ""
            body = section.get("body") or section.get("content") or ""
            if heading:
                doc.add_heading(str(heading), level=1)
            if body:
                for paragraph in str(body).split("\n"):
                    doc.add_paragraph(paragraph)
    else:
        for paragraph in (content or "").split("\n"):
            doc.add_paragraph(paragraph)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _generate_pdf(
    title: str,
    content: str,
    sections: list[dict] | None,
) -> bytes:
    """用 reportlab 生成通用 A4 PDF（内置 CJK 字体）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"
    title_style = ParagraphStyle(
        "office_title", fontName=font, fontSize=20, leading=26, spaceAfter=12,
    )
    body_style = ParagraphStyle(
        "office_body", fontName=font, fontSize=10.5, leading=16, wordWrap="CJK",
    )

    story: list[Any] = [
        Paragraph(html.escape(title or "未命名文档"), title_style),
        Spacer(1, 8),
    ]

    if sections:
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = section.get("heading") or section.get("title") or ""
            body = section.get("body") or section.get("content") or ""
            if heading:
                story.append(
                    Paragraph(html.escape(str(heading)), title_style),
                )
            if body:
                for paragraph in str(body).split("\n"):
                    story.append(
                        Paragraph(html.escape(paragraph), body_style),
                    )
    else:
        for paragraph in (content or "").split("\n"):
            story.append(Paragraph(html.escape(paragraph), body_style))

    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4).build(story)
    return buffer.getvalue()
