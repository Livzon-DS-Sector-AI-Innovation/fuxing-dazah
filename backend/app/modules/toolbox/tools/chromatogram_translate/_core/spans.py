"""文本 span 收集与行/列拆分、混合串分段翻译、标点感知拼接。

span 用 dict 承载（p/text/rect/size/chars），与渲染层共享。"""

from __future__ import annotations

import re
from typing import Any, cast

import pymupdf

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PUNCT_CHARS = "([（)]*%.,:;，、-–—/"


def has_cjk(s: str) -> bool:
    return bool(CJK_RE.search(s))


def cjk_segments(text: str) -> list[str]:
    """文本里的连续中文段（词条覆盖检查/AI 补译按段进行）"""
    return re.findall(r"[\u4e00-\u9fff]+", text)


def collect_page(page: pymupdf.Page, pno: int) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    raw = cast(dict[str, Any], page.get_text("rawdict"))
    for block in raw["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for sp in line["spans"]:
                chars = [(c["c"], pymupdf.Rect(c["bbox"])) for c in sp["chars"]]
                if not chars:
                    continue
                spans.append(
                    {
                        "p": pno,
                        "text": "".join(c for c, _ in chars),
                        "rect": pymupdf.Rect(sp["bbox"]),
                        "size": sp["size"],
                        "chars": chars,
                    }
                )
    return spans


def normalize(s: str) -> str:
    for a, b in (
        ("（", "("),
        ("）", ")"),
        ("：", ":"),
        ("，", ","),
        ("　", " "),
        ("\u00a0", " "),
    ):
        s = s.replace(a, b)
    return re.sub(r"(?<=:) +", " ", re.sub(r"  +", " ", s))


def join_tokens(pieces: list[str]) -> str:
    """标点感知拼接："(min)"、"(µV*sec)"、"β-Isomer"、"Page: 1 (Total 1)"。
    裸开括号后贴、裸闭/连接符前后贴、% 前留空格、冒号前不空。"""
    out = ""
    for raw in pieces:
        p = normalize(raw).strip()
        if not p:
            continue
        if not out:
            out = p
            continue
        bare = len(p) <= 2 and all(c in PUNCT_CHARS for c in p)
        if bare and p[0] in "([（" and p[-1] in "([（":
            out += " " + p
        elif bare and all(c in ")]*" for c in p):
            out = out.rstrip() + p
        elif bare and all(c in "-–—/" for c in p):
            out = out.rstrip() + p
        elif p == "%":
            out += " %"
        elif out[-1] in "([（-–—/*":
            out += p
        elif p[0] in ":)]%*，、;。":
            out += p
        elif out[-1] in "-–—":  # 破折号后接字母数字不加空格
            out += p
        else:
            out += " " + p
    return out


def tr_run(terms: dict[str, str], t: str) -> str:
    """混合 run 翻译：按中文/非中文分段，中文段查表，段间智能补空格。
    杂质4→Impurity 4；β-异构体→β-Isomer；(分钟)→(min)；整串命中直接返回。"""
    if not has_cjk(t):
        return t
    if t in terms:
        return terms[t]
    out = ""
    for seg in re.findall(r"[\u4e00-\u9fff]+|[^\u4e00-\u9fff]+", t):
        if has_cjk(seg):
            if seg not in terms:
                return t
            s = terms[seg]
            if out and out[-1].isalnum() and s[:1].isalnum():
                out += " "
            out += s
        else:
            if out and out[-1].isalnum() and seg[:1].isalnum():
                out += " "
            out += seg
    return out


def run_text(run: list[tuple[str, pymupdf.Rect]]) -> str:
    return "".join(ch for ch, _ in run)


def lines_by_y(chars: list[tuple[Any, ...]]) -> list[list[tuple[Any, ...]]]:
    """按 y 分行；元素为 (char, rect[, span…]) 任意元组，rect 在第 2 位"""
    rows: list[list[Any]] = []
    cur: list[Any] = []
    for item in sorted(chars, key=lambda t: t[1].y0):
        if cur and item[1].y0 - min(t[1].y0 for t in cur) > 5.0:
            rows.append(cur)
            cur = []
        cur.append(item)
    if cur:
        rows.append(cur)
    return rows


def runs_by_gap(
    chars: list[tuple[str, pymupdf.Rect]], edges: list[float] | None = None
) -> list[list[tuple[str, pymupdf.Rect]]]:
    """行内字符按 x 间隙>3pt 拆段；再按表格列边界二次裁剪——
    空格 span 会横跨列边界填满间隙，仅靠间隙切不开（Area% Theoretical Plates 教训）"""
    runs: list[list[tuple[str, pymupdf.Rect]]] = []
    cur: list[tuple[str, pymupdf.Rect]] = []
    for ch, r in sorted(chars, key=lambda t: t[1].x0):
        if cur and r.x0 - max(rr.x1 for _, rr in cur) > 3.0:
            runs.append(cur)
            cur = []
        cur.append((ch, r))
    if cur:
        runs.append(cur)
    if not edges:
        return runs
    out: list[list[tuple[str, pymupdf.Rect]]] = []
    for run in runs:
        pieces = [run]
        for e in edges[1:-1]:
            nxt: list[list[tuple[str, pymupdf.Rect]]] = []
            for piece in pieces:
                if piece[0][1].x0 + 0.2 < e < max(rr.x1 for _, rr in piece) - 0.2:
                    a = [(c, r) for c, r in piece if (r.x0 + r.x1) / 2 < e]
                    b = [(c, r) for c, r in piece if (r.x0 + r.x1) / 2 >= e]
                    nxt.extend(p for p in (a, b) if p)
                else:
                    nxt.append(piece)
            pieces = nxt
        out.extend(pieces)
    return out


def cell_of(edges: list[float], x: float) -> tuple[float, float] | None:
    for i in range(len(edges) - 1):
        if edges[i] <= x < edges[i + 1]:
            return (edges[i], edges[i + 1])
    return None
