"""点检记录标准 PDF 渲染器（纯函数）。

复刻既有归档样例版式：标题 + 信息栅格 + 点检项目表 + 现场照片双框 +
签字框 + 页脚说明。房内范式：reportlab platypus + 内置 CID 字体
STSong-Light（无需字体文件，服务器无中文字体可渲染）、wordWrap="CJK"。
"""

from __future__ import annotations

import html
import io
from typing import TYPE_CHECKING, Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.modules.safety.fire_inspection.models import (
    FIELD_EQUIPMENT,
    Attachment,
    InspectionRecord,
)

if TYPE_CHECKING:
    from reportlab.platypus import Flowable

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
_FONT = "STSong-Light"

_TITLE = ParagraphStyle("fi_title", fontName=_FONT, fontSize=18, leading=24, alignment=1, spaceAfter=6)
_LABEL = ParagraphStyle("fi_label", fontName=_FONT, fontSize=10, leading=14, wordWrap="CJK")
_VALUE = ParagraphStyle("fi_value", fontName=_FONT, fontSize=10, leading=14, wordWrap="CJK")
_HEAD = ParagraphStyle("fi_head", fontName=_FONT, fontSize=10, leading=14, alignment=1)
_NOTE = ParagraphStyle("fi_note", fontName=_FONT, fontSize=8, leading=12, wordWrap="CJK")
_NOTE_RIGHT = ParagraphStyle("fi_note_right", fontName=_FONT, fontSize=8, leading=12, alignment=2)

_GRAY = colors.Color(0.94, 0.94, 0.94)
# reportlab TableStyle 指令元组形状随指令类型不同而不同，统一按宽元组处理
_VALIGN_MIDDLE: list[tuple[Any, ...]] = [("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
_CELL_PADDING: list[tuple[Any, ...]] = [
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]
_BOXED_CENTER: list[tuple[Any, ...]] = [
    ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
]
_GRID_STYLE = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.8, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), _GRAY),
        ("BACKGROUND", (2, 0), (2, -1), _GRAY),
        *_VALIGN_MIDDLE,
        *_CELL_PADDING,
    ]
)

# 版面尺寸（样例栅格：标签窄列 + 值宽列）
_COL_LABEL = 26 * mm
_COL_VALUE = 62 * mm
_PHOTO_BOX_HEIGHT = 45 * mm
_SIGN_BOX_HEIGHT = 22 * mm


def _esc(value: str) -> str:
    return html.escape(value or "")


def _label(text: str) -> Paragraph:
    return Paragraph(_esc(text), _LABEL)


def _value(text: str | None) -> Paragraph:
    return Paragraph(_esc(text or ""), _VALUE)


def _kv_table(rows: list[tuple[str, str | None]]) -> Table:
    """4 列信息栅格：标签|值|标签|值。"""
    data: list[list[Flowable]] = []
    for i in range(0, len(rows), 2):
        left_label, left_value = rows[i]
        right_label, right_value = rows[i + 1] if i + 1 < len(rows) else ("", None)
        data.append([_label(left_label), _value(left_value), _label(right_label), _value(right_value)])
    table = Table(data, colWidths=[_COL_LABEL, _COL_VALUE, _COL_LABEL, _COL_VALUE])
    table.setStyle(_GRID_STYLE)
    return table


def _confirm_text(record: InspectionRecord) -> str:
    return "已确认" if record.confirmed else "未确认"


def _info_grid(record: InspectionRecord) -> Table:
    inspect_at = record.inspect_at.strftime("%Y-%m-%d %H:%M") if record.inspect_at else ""
    return _kv_table(
        [
            (FIELD_EQUIPMENT, record.equipment_no),
            ("所属部门", record.dept),
            ("点检人", record.inspector),
            ("点检时间", inspect_at),
            ("点检结果", record.result),
            ("整改状态", record.rectify_status),
            ("异常描述", record.abnormal_desc),
            ("本人确认", _confirm_text(record)),
        ]
    )


def _check_table(record: InspectionRecord) -> Table:
    """点检项目表：项目|点检内容|结果，勾选→符合 / 未勾→不符合。"""
    data: list[list[Flowable]] = [
        [_head_cell("点检项目"), _head_cell("点检内容"), _head_cell("结果")]
    ]
    for name, checked in record.checks:
        data.append([_label(name), _value(""), _value("符合" if checked else "不符合")])
    table = Table(data, colWidths=[92 * mm, 38 * mm, 24 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.8, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), _GRAY),
                *_VALIGN_MIDDLE,
                *_CELL_PADDING,
            ]
        )
    )
    return table


def _head_cell(text: str) -> Paragraph:
    return Paragraph(_esc(text), _HEAD)


def _photo_box(label: str, image: Image | None) -> Table:
    """照片框：标签行 + 固定高度图框（缺图留空框）。"""
    inner: list[Flowable] = [image] if image is not None else [""]
    box = Table([inner], colWidths=[_COL_VALUE + _COL_LABEL - 2 * mm], rowHeights=[_PHOTO_BOX_HEIGHT])
    box.setStyle(TableStyle(list(_BOXED_CENTER)))
    outer = Table(
        [[_label(label)], [box]],
        colWidths=[_COL_VALUE + _COL_LABEL],
    )
    outer.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return outer


def _photos_section(record: InspectionRecord, images: dict[str, bytes]) -> Table:
    """现场照片双框：整体照片 | 关键部位照片。"""
    left = _photo_box("整体照片", _fit_image(record.overall_photos, images, 68 * mm, _PHOTO_BOX_HEIGHT - 4 * mm))
    right = _photo_box("关键部位照片", _fit_image(record.key_photos, images, 68 * mm, _PHOTO_BOX_HEIGHT - 4 * mm))
    table = Table(
        [[Paragraph(_esc("现场照片"), _LABEL)], [left, right]],
        colWidths=[(_COL_VALUE + _COL_LABEL)] * 2,
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 6),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ]
        )
    )
    return table


def _fit_image(
    attachments: tuple[Attachment, ...],
    images: dict[str, bytes],
    max_width: float,
    max_height: float,
) -> Image | None:
    """取首个有字节内容的附件生成等比缩放图片；无图返回 None 留空框。"""
    from reportlab.lib.utils import ImageReader

    for att in attachments:
        data = images.get(att.file_token)
        if not data:
            continue
        reader = ImageReader(io.BytesIO(data))
        iw, ih = reader.getSize()
        if iw <= 0 or ih <= 0:
            continue
        scale = min(max_width / iw, max_height / ih)
        return Image(io.BytesIO(data), width=iw * scale, height=ih * scale)
    return None


def _signature_section(record: InspectionRecord, images: dict[str, bytes]) -> Table:
    """签字框 + 创建人/创建时间。"""
    sign_img = _fit_image(record.signatures, images, 50 * mm, _SIGN_BOX_HEIGHT - 4 * mm)
    inner: list[Flowable] = [sign_img] if sign_img is not None else [""]
    box = Table([inner], colWidths=[60 * mm], rowHeights=[_SIGN_BOX_HEIGHT])
    box.setStyle(TableStyle(list(_BOXED_CENTER)))
    created = "创建人：" + (record.created_by or "")
    created_at = "创建时间：" + (record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else "")
    created_lines = Paragraph(_esc(created) + "<br/>" + _esc(created_at), _VALUE)
    table = Table(
        [[Paragraph(_esc("点检人签字"), _LABEL), ""], [box, created_lines]],
        colWidths=[64 * mm, 84 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _footer(record: InspectionRecord) -> list[Flowable]:
    note_text = _esc("记录生成：系统自动整理") + "<br/>" + _esc(
        "本记录依据消防设施二维码点检数据及对应附件自动整理生成，可用于查询、归档及打印。"
    )
    note = Paragraph(note_text, _NOTE)
    equipment = Paragraph(_esc("设备编号：" + (record.equipment_no or "")), _NOTE_RIGHT)
    table = Table([[note, equipment]], colWidths=[128 * mm, 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [Spacer(1, 6 * mm), table]


def render(record: InspectionRecord, images: dict[str, bytes] | None = None) -> bytes:
    """渲染单条点检记录为标准归档 PDF（A4 单页）。images: file_token -> 字节。"""
    image_map = images or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="消防设施点检记录",
    )
    story: list[Flowable] = [
        Paragraph(_esc("消防设施点检记录"), _TITLE),
        _info_grid(record),
        Spacer(1, 5 * mm),
        _check_table(record),
        Spacer(1, 5 * mm),
        _photos_section(record, image_map),
        Spacer(1, 4 * mm),
        _signature_section(record, image_map),
        *_footer(record),
    ]
    doc.build(story)
    return buf.getvalue()
