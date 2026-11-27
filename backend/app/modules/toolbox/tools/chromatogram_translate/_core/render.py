"""渲染层：全文档先汇总「目标字符集」，对每个目标字符求不与任何存活字符盒
相交的安全子矩形（防止误删相邻数字——试验中曾因此丢过 RT 值），再统一
遮盖（apply_redactions 只删文本不动图形）与回填。"""

from __future__ import annotations

from typing import Any

import pymupdf

InsertText = tuple[int, float, float, str, float, int]  # (page, x, y, text, fs, rotate)


def max_safe_subrect(cr: pymupdf.Rect, near: list[pymupdf.Rect]) -> pymupdf.Rect:
    """cr 内不与任何存活字符盒相交的最大面积子矩形（x/y 条带两家族取最大）"""
    eps, cands = 0.15, []
    near = [f for f in near if f.intersects(cr)]
    xs = sorted(
        {
            round(v, 2)
            for v in {cr.x0, cr.x1}
            | {min(max(f.x0, cr.x0), cr.x1) for f in near}
            | {min(max(f.x1, cr.x0), cr.x1) for f in near}
        }
    )
    for a, b in zip(xs, xs[1:]):
        if b - a < 0.25:
            continue
        cand = pymupdf.Rect(a + eps, cr.y0 + eps, b - eps, cr.y1 - eps)
        if cand.is_valid and not any(cand.intersects(f) for f in near):
            cands.append(cand)
    ys = sorted(
        {
            round(v, 2)
            for v in {cr.y0, cr.y1}
            | {min(max(f.y0, cr.y0), cr.y1) for f in near}
            | {min(max(f.y1, cr.y0), cr.y1) for f in near}
        }
    )
    for a, b in zip(ys, ys[1:]):
        if b - a < 0.25:
            continue
        cand = pymupdf.Rect(cr.x0 + eps, a + eps, cr.x1 - eps, b - eps)
        if cand.is_valid and not any(cand.intersects(f) for f in near):
            cands.append(cand)
    return max(cands, key=lambda r: r.get_area()) if cands else pymupdf.Rect(cr)


class Ops:
    """目标字符（含可选表格列内裁剪）+ 插入文本 + 版式告警收集。"""

    def __init__(self) -> None:
        self.targets: dict[
            int, dict[int, tuple[dict[str, Any], pymupdf.Rect | None]]
        ] = {}
        self.texts: list[InsertText] = []
        self.warnings: list[str] = []

    def target_chars(
        self, span: dict[str, Any], clip: pymupdf.Rect | None = None
    ) -> None:
        self.targets.setdefault(span["p"], {})[id(span)] = (span, clip)

    def text(self, p: int, x: float, y: float, t: str, fs: float, rot: int = 0) -> None:
        self.texts.append((p, x, y, t, fs, rot))

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def render(
        self,
        doc: pymupdf.Document,
        page_spans: list[list[dict[str, Any]]],
        font_file: str,
        font_name: str = "chrom-en",
    ) -> None:
        for pno in range(len(doc)):
            page = doc[pno]
            tset = self.targets.get(pno, {})
            tchars = [(r, clip) for s, clip in tset.values() for _, r in s["chars"]]
            tkeys = {
                (c, round(r.x0, 2), round(r.y0, 2))
                for s, _ in tset.values()
                for c, r in s["chars"]
            }
            foreign = [
                r
                for s in page_spans[pno]
                for c, r in s["chars"]
                if (c, round(r.x0, 2), round(r.y0, 2)) not in tkeys
            ]
            for r, clip in tchars:
                rect = max_safe_subrect(r, foreign)
                if clip is not None:  # 表格区：白 fill 不得压到列线
                    cr = pymupdf.Rect(
                        max(rect.x0, clip.x0), rect.y0, min(rect.x1, clip.x1), rect.y1
                    )
                    if cr.is_valid and not cr.is_empty:
                        rect = cr
                page.add_redact_annot(rect, fill=(1, 1, 1))
        for pno2 in range(len(doc)):
            doc[pno2].apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,  # type: ignore[attr-defined]
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,  # type: ignore[attr-defined]
            )
        for pno3 in range(len(doc)):
            doc[pno3].insert_font(fontname=font_name, fontfile=font_file)
        for pno, x, y, t, fs, rot in self.texts:
            doc[pno].insert_text((x, y), t, fontname=font_name, fontsize=fs, rotate=rot)
