"""图谱截图/PDF 自动解析：MinerU 提取 Markdown 后做峰表结构化（仅预览，
人工确认后经 calc-fill 填任务）。

MinerU HTTP 适配在 service/mineru.py；本文件只保留 Markdown → 峰表的业务解析。
解析结果只做预填草稿：峰面积保留两位小数，组分名归一化匹配在填入链路处理。
"""

import re
from typing import Any

from app.modules.quality.service.mineru import (
    ChromatogramParseError as ChromatogramParseError,  # noqa: F401 — 向既有导入方 re-export
)
from app.modules.quality.service.mineru import (
    parse_chromatogram_markdown as parse_chromatogram_markdown,  # noqa: F401
)

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".pdf"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _markdown_tables(markdown: str) -> list[list[list[str]]]:
    """提取 markdown 中的表格块（| 分隔），返回 [表[行[单元格]]]。"""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # 分隔行
            current.append(cells)
        elif current:
            if len(current) >= 2:
                tables.append(current)
            current = []
    if len(current) >= 2:
        tables.append(current)
    return tables


_AREA_HINTS = ("面积", "area", "峰面", "%面")
_NAME_HINTS = ("峰名", "组分", "名称", "化合物", "name", "component", "峰")


def extract_peak_table(markdown: str) -> list[dict[str, Any]]:
    """从 MinerU Markdown 提取峰表：{name, area}，面积保留两位小数（仅提取不判定）。"""
    peaks: list[dict[str, Any]] = []
    for table in _markdown_tables(markdown):
        header = [c.casefold() for c in table[0]]
        area_cols = [i for i, h in enumerate(header) if any(k in h for k in _AREA_HINTS)]
        name_col = next(
            (i for i, h in enumerate(header) if any(k in h for k in _NAME_HINTS)), 0,
        )
        for row in table[1:]:
            if not row:
                continue
            name = str(row[name_col]).strip() if name_col < len(row) else ""
            if not name or not re.search(r"[一-龥A-Za-z]", name):
                continue
            cols = area_cols or [len(row) - 1]
            for c in cols:
                if c >= len(row):
                    continue
                m = re.search(r"-?\d+(?:\.\d+)?", str(row[c]))
                if m:
                    peaks.append({"name": name, "area": round(float(m.group(0)), 2)})
                    break
    return peaks
