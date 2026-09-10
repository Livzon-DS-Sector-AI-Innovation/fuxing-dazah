"""URS 智能审核报告 PDF 生成器。

将一条 URS 审核的完整状态（基本信息 / 五维风险画像 / 审核结论 / 标准条款审核过程）
导出为排版整齐的 A4 纵向 PDF。

字体用 reportlab 内置 CID 字体 STSong-Light（无需字体文件，Docker 无中文字体也能渲染），
中文换行用 wordWrap="CJK"（与 msds_pdf.py 一致）。
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from app.modules.safety.ai_urs_review.seed_items import CATEGORY_LABELS

logger = logging.getLogger(__name__)

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
_FONT = "STSong-Light"

# ── 标签映射（与前端 ursConstants.tsx 保持一致）──
_STATUS_LABEL: dict[str, str] = {
    "draft": "草稿",
    "pending_assessment": "待评估",
    "assessing": "评估中",
    "failed": "评估失败",
    "assessment_confirmed": "评估已确认",
    "human_review": "待人工复核",
    "adapting": "标准适配中",
    "item_review": "逐条审核中",
    "conclusion": "结论生成中",
    "approved": "已通过",
    "rejected": "已驳回",
    "appeal": "申诉中",
    "closed": "已闭环",
}
_RISK_DIMENSION_LABELS: dict[str, str] = {
    "mechanical": "机械",
    "electrical": "电气",
    "data": "数据",
    "environmental": "环境",
    "chemical": "化学",
    "none": "通用",
}
_RISK_LEVEL_LABELS: dict[str, str] = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}
_APPLICABILITY_LABELS: dict[str, str] = {
    "mandatory": "强制",
    "recommended": "建议",
    "not_applicable": "不适用",
}
_ITEM_VERDICT_LABELS: dict[str, str] = {
    "pending": "待审核",
    "passed": "通过",
    "failed": "不通过",
    "skipped": "跳过",
}

# ── 样式 ──
_TITLE = ParagraphStyle("urs_title", fontName=_FONT, fontSize=18, leading=24, alignment=1, spaceAfter=4)
_SUBTITLE = ParagraphStyle("urs_subtitle", fontName=_FONT, fontSize=9, leading=13, alignment=1, spaceAfter=12)
_SECTION = ParagraphStyle("urs_section", fontName=_FONT, fontSize=12, leading=16)
_LABEL = ParagraphStyle(
    "urs_label", fontName=_FONT, fontSize=9, leading=13, wordWrap="CJK",
    textColor=colors.HexColor("#555555"),
)
_BODY = ParagraphStyle("urs_body", fontName=_FONT, fontSize=9, leading=13, wordWrap="CJK")
_HEAD = ParagraphStyle(
    "urs_head", fontName=_FONT, fontSize=9, leading=13, wordWrap="CJK",
    textColor=colors.HexColor("#ffffff"),
)

# A4(595.27) − 左右边距 40×2 → 内容宽 515
_COL_LABEL = 95
_COL_VALUE = 420
_ITEM_COLS = [52, 152, 111, 100, 100]  # 合计 515


def _esc(value: str) -> str:
    """转义 XML 实体 + 换行 → <br/>，安全嵌入 reportlab Paragraph 标记。"""
    return html.escape(str(value or "")).replace("\n", "<br/>")


def _p(text: str, style: ParagraphStyle = _BODY) -> Paragraph:
    return Paragraph(_esc(text), style)


def _section_block(title: str) -> Table:
    """章节标题块（浅底深字，替代无法加粗的 CID 字体）。"""
    return Table(
        [[Paragraph(_esc(title), _SECTION)]],
        colWidths=[515],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef3fa")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1f4e79")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (0, 0), 8),
        ]),
    )


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    """键值表：左列标签（浅灰底）+ 右列内容（可换行）。"""
    data = [[_p(label, _LABEL), _p(value)] for label, value in rows]
    return Table(
        data,
        colWidths=[_COL_LABEL, _COL_VALUE],
        style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d6d6d6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f6f4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    )


def _item_table(items: list[Any]) -> Table:
    """标准条款审核过程明细表（表头跨页重复 repeatRows=1）。"""
    header = [_p("条款", _HEAD), _p("标准条款", _HEAD), _p("适配", _HEAD), _p("AI判定", _HEAD), _p("审核意见", _HEAD)]
    rows: list[list[Paragraph]] = [header]
    for it in items:
        no_text = f"{it.item_no}（否决）" if it.is_veto else it.item_no
        category = CATEGORY_LABELS.get(it.category, it.category or "")
        dim = _RISK_DIMENSION_LABELS.get(it.risk_dimension, it.risk_dimension or "")

        title_text = _esc(it.standard_title)
        if it.standard_ref:
            title_text += f"<br/>{_esc(it.standard_ref)}"
        meta = f"{category}" + (f"｜{dim}" if dim and dim != "通用" else "")
        title_text = f"{title_text}<br/>{_esc(meta)}"

        # 兜底值（越域/脏数据）必须 _esc，否则 raw `<`/`&` 会破坏 reportlab Paragraph 解析
        app_text = _APPLICABILITY_LABELS.get(it.applicability) or _esc(it.applicability or "—")
        if it.applicability_reason:
            app_text += f"<br/>{_esc(it.applicability_reason)}"

        verdict = "skipped" if it.applicability == "not_applicable" else it.review_status
        verdict_text = _ITEM_VERDICT_LABELS.get(verdict) or _esc(verdict or "—")
        if it.ai_suggestion:
            verdict_text += f"<br/>{_esc(it.ai_suggestion)}"

        comment_text = _esc(it.review_comment) if it.review_comment else "—"
        if it.rectification_required:
            # 语义区分：failed → 需整改；passed（部分满足）→ 需在设计/验收阶段确认细节
            tag = "（需整改）" if it.review_status == "failed" else "（需确认细节）"
            comment_text += tag

        rows.append([
            _p(no_text),
            Paragraph(title_text, _BODY),
            Paragraph(app_text, _BODY),
            Paragraph(verdict_text, _BODY),
            Paragraph(comment_text, _BODY),
        ])

    return Table(
        rows,
        colWidths=_ITEM_COLS,
        repeatRows=1,
        style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d6d6d6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3a5a86")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]),
    )


def _audit_stats_line(items: list[Any]) -> str:
    """汇总统计行：强制/建议/不适用、通过/不通过/待审、否决项状态。"""
    applicable = [i for i in items if i.applicability != "not_applicable"]
    mandatory = sum(1 for i in items if i.applicability == "mandatory")
    recommended = sum(1 for i in items if i.applicability == "recommended")
    not_applicable = len(items) - len(applicable)
    passed = sum(1 for i in applicable if i.review_status == "passed")
    failed = sum(1 for i in applicable if i.review_status == "failed")
    pending = sum(1 for i in applicable if i.review_status not in ("passed", "failed", "skipped"))
    veto = [i for i in items if i.is_veto]
    veto_failed = sum(1 for i in veto if i.review_status == "failed")
    veto_pending = sum(1 for i in veto if i.review_status == "pending")
    if veto_failed > 0:
        veto_txt = f"{veto_failed} 项未通过（一票否决）"
    elif veto_pending > 0:
        veto_txt = f"{veto_pending} 项待审"
    else:
        veto_txt = "全部通过"
    return (
        f"强制 {mandatory} / 建议 {recommended} / 不适用 {not_applicable} | "
        f"通过 {passed} / 不通过 {failed} / 待审 {pending} | "
        f"否决项 {len(veto)} 项：{veto_txt}"
    )


def build_urs_review_pdf(report: Any, items: list[Any]) -> bytes:
    """生成单条 URS 审核的完整报告 PDF，返回 bytes。

    Args:
        report: URSReport ORM 对象
        items: 按 item_no 排序的 URSStandardItem 列表
    """
    buffer = BytesIO()
    story: list[Any] = []

    story.append(Paragraph("URS 智能审核报告", _TITLE))
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    story.append(Paragraph(_esc(f"{report.urs_no} | {report.equipment_name} | 生成时间 {gen_at}"), _SUBTITLE))

    # 一、基本信息
    story.append(_section_block("一、基本信息"))
    story.append(_kv_table([
        ("设备名称", report.equipment_name),
        ("设备类别", report.equipment_category or "—"),
        ("申请部门", report.department or "—"),
        ("申请人", report.applicant_name or "—"),
        ("采购用途", report.procurement_purpose or "—"),
        ("审核状态", _STATUS_LABEL.get(report.review_status, report.review_status or "—")),
    ]))
    # URS 正文单独渲染：内容可能很长（完整原文），放表格单元格无法跨页会触发
    # reportlab LayoutError（Paragraph 在 Table 内不可 split），必须作为独立 flowable
    if report.urs_content:
        story.append(Paragraph(_esc("URS 正文"), _BODY))
        story.append(Paragraph(_esc(report.urs_content), _BODY))
    story.append(Paragraph("", _BODY))

    # 二、五维风险画像
    if report.risk_profile:
        story.append(_section_block("二、五维风险画像"))
        profile = report.risk_profile
        rows: list[tuple[str, str]] = []
        for dim, label in _RISK_DIMENSION_LABELS.items():
            if dim == "none":
                continue
            entry = profile.get(dim)
            if not entry:
                continue
            level = entry.get("level") or ""
            level_label = _RISK_LEVEL_LABELS.get(level, level or "—")
            indicators = entry.get("indicators") or []
            evidence = entry.get("evidence") or ""
            parts: list[str] = []
            if indicators:
                parts.append("关注点：" + "、".join(str(i) for i in indicators))
            if evidence:
                parts.append("依据：" + str(evidence))
            rows.append((f"{label}风险：{level_label}", "；".join(parts) or "—"))
        rows.append(("综合风险", _RISK_LEVEL_LABELS.get(report.overall_risk_level, report.overall_risk_level or "—")))
        if report.ai_confidence is not None:
            rows.append(("置信度", f"{round(report.ai_confidence * 100)}%"))
        if report.risk_profile_reasoning:
            rows.append(("综合定级理由", report.risk_profile_reasoning))
        story.append(_kv_table(rows))
        story.append(Paragraph("", _BODY))

    # 三、审核结论
    if report.conclusion:
        story.append(_section_block("三、审核结论"))
        veto_break = bool((report.review_result or {}).get("veto_break"))
        conclusion_text = "通过" if report.conclusion == "approved" else "不通过"
        if veto_break:
            conclusion_text += "（一票否决）"
        rows = [
            ("评分", f"{report.score} 分（{report.grade} 级）" if report.score is not None else "—"),
            ("结论", conclusion_text),
        ]
        summary = (report.review_result or {}).get("summary")
        if summary:
            rows.append(("结论摘要", str(summary)))
        reqs = report.rectification_requirements or []
        if reqs:
            req_text = "；".join(
                f"{r.get('item_no', '')} {r.get('requirement', '')}".strip()
                for r in reqs if isinstance(r, dict)
            )
        else:
            req_text = ""
        rows.append(("整改要求", req_text or "无"))
        story.append(_kv_table(rows))
        story.append(Paragraph("", _BODY))

    # 四、标准条款审核过程
    story.append(_section_block("四、标准条款审核过程"))
    story.append(Paragraph(_esc(_audit_stats_line(items)), _BODY))
    story.append(Paragraph("", _BODY))
    story.append(_item_table(items))

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=32,
        title=f"{report.urs_no} URS 智能审核报告",
        author="DAZAH 安全模块",
    )
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    logger.info("URS 审核报告 PDF 已生成: %s (%d bytes)", report.urs_no, len(pdf_bytes))
    return pdf_bytes
