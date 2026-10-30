"""色谱报告翻译：批量上传 Waters Empower 导出的液相/荧光检测报告 PDF，
AI 将中文原位替换为英文——版式、色谱曲线与全部数据保持不变，
逐文件输出 <原名>_英文.pdf 与批量校验报告（数字完整性/残留中文双硬门禁）。

与文档翻译工具完全独立：不共享其代码与配置（AI 凭据、术语表在本工具
配置页单独维护）。仅支持带文本层的 Empower 版式；无文本层/版式不符的
文件会被明确标记失败，绝不静默输出原样副本。
"""

import asyncio
import zipfile
from pathlib import Path
from typing import Any

from app.modules.toolbox import storage
from app.modules.toolbox.registry import (
    ConfigField,
    StepContext,
    ToolError,
    ToolInput,
    ToolStep,
    tool,
)

from ._core import llm as llm_mod
from ._core import terms as terms_mod
from ._core.pipeline import (
    FileResult,
    build_report,
    collect_all_span_texts,
    translate_file,
)
from ._core.profiles import EMPOWER_CN

_MAX_FILES = 50


def _option(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


@tool(
    id="chromatogram-translate",
    name="色谱报告翻译",
    description="批量上传 Empower 液相/荧光检测报告 PDF，AI 将中文原位替换为英文"
    "（版式与数据逐位不变），输出同名英文 PDF 与校验报告。"
    "仅支持带文本层的 Empower 版式；扫描件不支持。",
    background=True,
    config_schema=[
        ConfigField(
            key="ai.api_base_url",
            label="模型接口地址",
            type="text",
            section="AI 模型",
            required=True,
            help="OpenAI 兼容接口地址，如 https://api.deepseek.com 或 "
            "https://open.bigmodel.cn/api/paas/v4",
        ),
        ConfigField(
            key="ai.api_key",
            label="模型 API Key",
            type="password",
            section="AI 模型",
            required=True,
            help="术语补译用的模型 API Key，由管理员统一维护",
        ),
        ConfigField(
            key="ai.model",
            label="模型名称",
            type="text",
            section="AI 模型",
            required=True,
            help="如 deepseek-v4-flash、glm-4.7",
        ),
        ConfigField(
            key="glossary.csv_content",
            label="术语表 CSV 内容",
            type="textarea",
            section="术语表",
            help="每行一条「中文术语,English Term」，首行可为表头。用于补充/覆盖"
            "内置锁定术语；报告中的 AI 补译词条建议人工确认后加到这里。",
        ),
    ],
    steps=[
        ToolStep(
            id="translate",
            name="翻译报告",
            description="上传 Empower 色谱报告 PDF（可多选）执行中文→英文原位替换；"
            "逐文件校验数字完整性与残留中文，完成后提供英文 PDF 下载"
            "与校验报告",
            inputs=[
                ToolInput(
                    key="input_files",
                    label="色谱报告 PDF",
                    type="file",
                    accept=".pdf",
                    required=True,
                    multiple=True,
                    help=f"可一次选择多个文件（最多 {_MAX_FILES} 个）；"
                    "需为 Empower 导出的带文本层 PDF",
                ),
            ],
        ),
    ],
)
async def chromatogram_translate(
    step_id: str, params: dict[str, Any], context: StepContext
) -> dict[str, Any]:
    # ── 输入文件 ──
    paths = context.file_paths.get("input_files") or []
    if not paths:
        raise ToolError("缺少待翻译的 PDF 文件")
    if len(paths) > _MAX_FILES:
        raise ToolError(f"一次最多 {_MAX_FILES} 个文件，收到 {len(paths)} 个")
    bad = [Path(p).name for p in paths if Path(p).suffix.lower() != ".pdf"]
    if bad:
        raise ToolError(f"仅支持 .pdf 文件：{bad[:3]}")

    # ── 工具配置 ──
    cfg = context.config or {}
    ai_raw = cfg.get("ai")
    ai_cfg = ai_raw if isinstance(ai_raw, dict) else {}
    base_url = str(ai_cfg.get("api_base_url") or "").strip()
    api_key = str(ai_cfg.get("api_key") or "").strip()
    model = str(ai_cfg.get("model") or "").strip()
    if not (base_url and api_key and model):
        raise ToolError(
            "请先在工具配置中填写 AI 模型信息（接口地址 / API Key / 模型名称）"
        )
    glossary_raw = cfg.get("glossary")
    glossary_cfg = glossary_raw if isinstance(glossary_raw, dict) else {}
    glossary_csv = str(glossary_cfg.get("csv_content") or "")

    reporter = context.report_progress
    file_paths = [Path(p) for p in paths]
    # 落盘路径是内部 uuid 名；产物/报告一律用用户上传时的原始文件名
    raw_names = context.file_names.get("input_files") or []
    orig_names = [
        Path(raw_names[i]).name if i < len(raw_names) and raw_names[i] else fp.name
        for i, fp in enumerate(file_paths)
    ]

    def report(pct: int, msg: str) -> None:
        if reporter:
            reporter(pct, msg)

    # ── 术语准备（收集 → 合并 → AI 补译一次）──
    report(2, "正在读取文件并收集词条…")
    terms, glossary_warnings = terms_mod.merged_terms(glossary_csv)
    span_texts = await asyncio.to_thread(collect_all_span_texts, file_paths)
    ai_terms: dict[str, str] = {}
    need = terms_mod.collect_missing([t for _, t in span_texts], terms)
    if need:
        report(5, f"AI 补译 {len(need)} 条缺失词条…")
        try:
            ai_terms = await asyncio.to_thread(
                llm_mod.translate_terms, base_url, api_key, model, need
            )
        except llm_mod.LLMError as e:
            raise ToolError(str(e)) from None
        terms.update(ai_terms)

    # ── 逐文件翻译（重活放线程；进度按文件推进）──
    results: list[FileResult] = []
    n = len(file_paths)
    for i, fp in enumerate(file_paths):
        report(8 + int(84 * i / n), f"正在翻译第 {i + 1}/{n} 个文件：{orig_names[i]}")
        r = await asyncio.to_thread(
            translate_file, fp, terms, EMPOWER_CN, display_name=orig_names[i]
        )
        results.append(r)

    # ── 报告与产物注册 ──
    report(95, "正在生成校验报告…")
    report_md = build_report(results, ai_terms, glossary_warnings)
    report_path = context.output_dir / "chromatogram_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    report_fid, _ = await asyncio.to_thread(
        storage.save_upload,
        context.execution_id,
        report_path.name,
        report_path.read_bytes(),
    )

    files: list[dict[str, str]] = []
    ok_outputs: list[tuple[str, Path]] = []  # (译文名, 落盘路径) 供打包
    used_names: set[str] = set()  # 批量里同名文件去重（不同目录同名上传）
    for r in results:
        if not r.ok or r.output is None:
            continue
        stem = Path(r.name).stem
        name = f"{stem}_英文.pdf"
        k = 2
        while name in used_names:
            name = f"{stem}({k})_英文.pdf"
            k += 1
        used_names.add(name)
        fid, out_path = await asyncio.to_thread(
            storage.save_upload, context.execution_id, name, r.output
        )
        r.output = None  # 已落盘：释放内存，后面打包直接读磁盘
        files.append({"file_id": fid, "filename": name})
        ok_outputs.append((name, out_path))

    # 批量成功 >1 个时提供 ZIP 一键打包，免去逐个下载
    zip_file: dict[str, str] | None = None
    if len(ok_outputs) > 1:
        zip_name = f"色谱报告英文_共{len(ok_outputs)}个.zip"
        zip_path = context.output_dir / zip_name

        def _write_zip() -> None:
            # PDF 本身已压缩：STORED 省掉无效的 DEFLATE，且放线程里跑不阻塞事件循环
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                for name, p in ok_outputs:
                    zf.write(p, arcname=name)
                zf.write(report_path, arcname="chromatogram_report.md")

        await asyncio.to_thread(_write_zip)
        zfid, _ = await asyncio.to_thread(
            storage.save_upload_copy, context.execution_id, zip_name, zip_path
        )
        zip_file = {"file_id": zfid, "filename": zip_name}

    ok_n = sum(1 for r in results if r.ok)
    report(100, f"完成：成功 {ok_n}/{n}")
    return {
        "report_md": report_md,
        "files": files,
        "zip_file": zip_file,
        "成功文件数": ok_n,
        "失败文件数": sum(1 for r in results if r.status == "failed"),
        "跳过文件数": sum(1 for r in results if r.status == "skipped"),
    }
