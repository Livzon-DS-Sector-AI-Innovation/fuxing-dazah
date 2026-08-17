"""文档表格提取：docx → PDF → 逐页渲染 → 千问 VL 提取 → CSV 汇总。

链路（纯 Python，无系统依赖）：mammoth(docx→HTML) → WeasyPrint(HTML→PDF) → PyMuPDF(fitz) 渲染 PNG → 千问 VL 逐页提取 → 相邻重复行去重 → CSV(UTF-8 BOM)。
仅支持 .docx；.doc 老格式在 api 层按 accept 声明拒绝。
"""

import asyncio
import base64
import csv
import io
import shutil
import tempfile
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from app.modules.toolbox import storage
from app.modules.toolbox.registry import (
    StepContext,
    ToolError,
    ToolInput,
    ToolStep,
    tool,
)
from app.modules.toolbox.tools._qwen import extract_table_rows

RENDER_DPI = 150
LLM_CONCURRENCY = 3


def parse_field_lines(text: str) -> list[dict[str, str]]:
    """解析字段清单文本：每行 `字段名` 或 `字段名|含义说明`。"""
    fields: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name, _, description = line.partition("|")
        name = name.strip()
        if not name:
            continue
        if name in seen:
            raise ToolError(f"字段重复: {name}")
        seen.add(name)
        fields.append({"name": name, "description": description.strip()})
    if not fields:
        raise ToolError("请至少填写一个字段")
    return fields


def dedupe_rows(rows: list[list[str]]) -> list[list[str]]:
    """相邻完全重复行去重（处理跨页重复表头）。"""
    out: list[list[str]] = []
    for row in rows:
        if not out or row != out[-1]:
            out.append(row)
    return out


def drop_header_rows(rows: list[list[str]], columns: list[str]) -> list[list[str]]:
    """过滤与字段名列表完全相同的表头行（LLM 按页输出表头，汇总时剔除）。"""
    return [row for row in rows if row != columns]


def rows_to_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return "\ufeff" + buf.getvalue()  # UTF-8 BOM，Excel 中文兼容


def _find_font(filename: str = "NotoSansSC.ttf") -> Path:
    """查找项目打包的 CJK 字体（backend/assets/fonts/，随镜像打包）。"""
    candidates = [
        Path(__file__).resolve().parents[4] / "assets" / "fonts" / filename,
        Path("assets/fonts") / filename,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise ToolError(f"字体文件未找到: {filename}，请部署 Noto Sans SC 到 assets/fonts/")


def _docx_to_html(input_path: Path) -> str:
    """docx → HTML（mammoth，纯 Python）。

    mammoth 输出结构化 HTML（含 colspan/rowspan），不输出表格样式。
    """
    import mammoth

    try:
        with open(input_path, "rb") as f:
            result = mammoth.convert_to_html(f)
    except Exception as e:
        raise ToolError("无法解析文档，请确认是有效的 .docx 文件") from e

    body: str = str(result.value).strip()
    if not body:
        raise ToolError("文档内容为空，无法提取表格")
    return body


def _docx_to_pdf(input_path: Path, work_dir: Path) -> Path:
    """docx → PDF：mammoth(HTML) + WeasyPrint。

    视觉识别依赖边框线，mammoth 不输出表格样式，故在此注入表格 CSS。
    """
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    body = _docx_to_html(input_path)
    font_config = FontConfiguration()
    css = CSS(
        string=f"""
@page {{ size: A4; margin: 1.5cm; }}
@font-face {{ font-family: "NotoSansSC"; src: url("file://{_find_font()}"); }}
body {{ font-family: "NotoSansSC", sans-serif; font-size: 10.5pt; color: #1a1a1a; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #444; padding: 4px 8px; text-align: left; }}
""",
        font_config=font_config,
    )
    pdf_path = work_dir / (input_path.stem + ".pdf")
    HTML(string=body).write_pdf(pdf_path, stylesheets=[css], font_config=font_config)
    return pdf_path


def _render_pages(pdf_path: Path) -> list[str]:
    """逐页渲染 PNG 并返回 base64 列表。"""
    images: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=RENDER_DPI)
            images.append(base64.b64encode(pix.tobytes("png")).decode())
    return images


def _render_doc(input_path: Path, work_dir: Path) -> list[str]:
    """docx → PDF → 逐页 PNG（同步，供 asyncio.to_thread 调用）。"""
    pdf_path = _docx_to_pdf(input_path, work_dir)
    return _render_pages(pdf_path)


async def extract_page(image_base64: str, fields: list[dict[str, str]], semaphore: asyncio.Semaphore) -> list[list[str]]:
    """提取单页（带并发信号量），测试中 monkeypatch 此函数。"""
    async with semaphore:
        return await extract_table_rows(image_base64, "image/png", fields)


@tool(
    id="doc-table-extract",
    name="文档表格提取",
    description="上传一个或多个 docx 文件，按指定字段提取表格数据，汇总为一个 CSV",
    image=None,  # 后续有图后放 tools/images/ 并填文件名，如 "doc-table-extract.png"
    steps=[
        ToolStep(
            id="configure",
            name="配置字段",
            description="填写要提取的字段，每行一个，可带含义说明",
            inputs=[
                ToolInput(
                    key="fields",
                    label="字段清单",
                    type="textarea",
                    required=True,
                    placeholder="每行一个，如：\n批号\n含量%|色谱峰含量数值",
                )
            ],
        ),
        ToolStep(
            id="extract",
            name="上传并提取",
            description="上传 docx 文件，执行提取并汇总为 CSV",
            inputs=[
                ToolInput(key="files", label="文档文件（仅 .docx）", type="file", accept=".docx", required=True, multiple=True)
            ],
        ),
    ],
)
async def doc_table_extract(step_id: str, params: dict[str, Any], context: StepContext) -> dict[str, Any]:
    if step_id == "configure":
        fields = parse_field_lines(str(params.get("fields", "")))
        return {"fields": fields, "count": len(fields)}

    if step_id == "extract":
        prev = context.prev_outputs.get("configure") or {}
        fields = prev.get("fields") or []
        if not fields:
            raise ToolError("请先完成「配置字段」步骤")

        input_paths = context.file_paths.get("files", [])
        if not input_paths:
            raise ToolError("请上传至少一个文档文件")

        work_dir = Path(tempfile.mkdtemp(prefix="doc-extract-", dir=context.output_dir))
        try:
            # 逐文件流水线：渲染完一个文件立即提取并释放其页面 base64，
            # 避免所有文件的全部页面常驻内存；单文件失败给出序号，不拖垮整个批次。
            semaphore = asyncio.Semaphore(LLM_CONCURRENCY)
            all_rows: list[list[str]] = []
            for i, path_str in enumerate(input_paths, start=1):
                try:
                    images = await asyncio.to_thread(_render_doc, Path(path_str), work_dir)
                except ToolError as e:
                    raise ToolError(f"第 {i} 个文档无法解析: {e}") from e
                if not images:
                    raise ToolError(f"第 {i} 个文档没有可提取的页面")
                page_rows = await asyncio.gather(
                    *(extract_page(img, fields, semaphore) for img in images)
                )
                all_rows.extend(row for rows in page_rows for row in rows)
            if not all_rows:
                raise ToolError("文档没有可提取的页面")

            columns = [f["name"] for f in fields]
            data_rows = drop_header_rows(dedupe_rows(all_rows), columns)
            csv_text = rows_to_csv([columns, *data_rows])

            file_id, _ = await asyncio.to_thread(
                storage.save_upload, context.execution_id, "提取汇总.csv", csv_text.encode("utf-8")
            )
            return {
                "columns": columns,
                "rows": data_rows,
                "csv_file": {"file_id": file_id, "filename": "提取汇总.csv"},
            }
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    raise ToolError(f"未知步骤: {step_id}")
