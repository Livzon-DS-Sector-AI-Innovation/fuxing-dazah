"""文档翻译工具：上传 Word/PDF 文档，AI 中英互译并输出校验报告。

引擎自 ai_translator 项目 vendor 于 _engine/（功能原封不动，仅增加进度回调）：
- docx：原格式回写（双语对照 / 整段替换），输出同名 .docx
- pdf：结构化抽取 + 领域预读 + 重排式输出为 .docx
- 产物：翻译后文件 + Markdown 校验报告（报告全文同时在结果区渲染）

AI 凭据与术语表在工具配置页维护（/toolbox/config/document-translate），
所有用户执行时使用同一份配置；术语表留空即禁用。
"""

import asyncio
import contextlib
import io
import re
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

from ._engine.cli import run_pipeline
from ._engine.config import Settings

_VALID_MODES = ("bilingual", "replace")
_VALID_DIRECTIONS = ("auto", "zh2en", "en2zh")
_VALID_DATE_FORMATS = ("keep", "iso", "en", "zh")
_VALID_THINKING_LEVELS = ("", "low", "high", "max")
_DEFAULT_DOC_TYPE = "GMP 文件（批记录/工艺验证报告）"

# ponytail: 全局锁串行化引擎执行——redirect_stdout/stderr 是进程级重定向，
# 并发任务会互抢捕获（错误信息错配到他人会话）。吞吐受限时改引擎接收
# 输出流参数或子进程隔离。
_engine_lock = asyncio.Lock()


def _option(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


def _positive_int(value: Any, default: int, name: str, maximum: int | None = None) -> int:
    """配置值转正整数：空值回退默认，非法值报用户可见错误。"""
    if value in (None, ""):
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name}需为正整数") from None
    if n < 1 or (maximum is not None and n > maximum):
        raise ToolError(f"{name}需为 1~{maximum} 的整数" if maximum else f"{name}需为正整数")
    return n


@tool(
    id="document-translate",
    name="文档翻译",
    description="上传 Word/PDF 文档进行中英互译：双语对照或整段替换输出，附 Markdown 校验报告。PDF 为重排式输出（转 Word）。",
    background=True,
    config_schema=[
        ConfigField(
            key="ai.api_base_url", label="模型接口地址", type="text", section="AI 模型", required=True,
            help="OpenAI 兼容接口地址，如 https://api.deepseek.com 或 https://open.bigmodel.cn/api/paas/v4",
        ),
        ConfigField(
            key="ai.api_key", label="模型 API Key", type="password", section="AI 模型", required=True,
            help="翻译模型的 API Key，由管理员统一维护",
        ),
        ConfigField(
            key="ai.model", label="模型名称", type="text", section="AI 模型", required=True,
            help="如 deepseek-v4-flash、glm-4.7",
        ),
        ConfigField(
            key="ai.thinking_level", label="思考等级", type="text", section="AI 模型",
            help="空=服务端默认；low 最快（常规文档推荐）；high/max 更稳但更慢",
        ),
        ConfigField(
            key="translate.batch_size", label="每批段落数", type="number", section="翻译调优",
            help="每次模型请求的最大段落数（默认 30，超过 6000 字符自动切批）",
        ),
        ConfigField(
            key="translate.concurrency", label="并发请求数", type="number", section="翻译调优",
            help="并发翻译请求数，1=顺序执行；被限流(429)时调小（默认 4，最大 16）",
        ),
        ConfigField(
            key="glossary.csv_content", label="术语表 CSV 内容", type="textarea", section="术语表",
            help="每行一条「中文术语,English Term」，首行可为表头；留空=不启用。"
                 "翻译时注入提示词并做译后术语一致性校验",
        ),
    ],
    steps=[
        ToolStep(
            id="translate",
            name="翻译文档",
            description="上传待翻译文档并配置参数；执行时间随文档大小与模型速度变化，完成后展示校验报告并提供译文下载",
            inputs=[
                ToolInput(
                    key="input_file", label="待翻译文档", type="file", accept=".docx,.pdf", required=True,
                    help="Word（.docx）原格式回写、保留原版式；PDF（.pdf）重排式输出为 Word 文档",
                ),
                ToolInput(
                    key="mode", label="输出模式", type="select", default="bilingual",
                    options=[_option("bilingual", "双语对照"), _option("replace", "整段替换")],
                    help="双语对照=每段原文后插入一行译文（便于审阅）；整段替换=直接用译文替换原文",
                ),
                ToolInput(
                    key="direction", label="翻译方向", type="select", default="auto",
                    options=[
                        _option("auto", "自动判断"),
                        _option("zh2en", "中译英"),
                        _option("en2zh", "英译中"),
                    ],
                    help="自动判断=逐段检测语言互译；指定方向时跳过语言不符的段落",
                ),
                ToolInput(
                    key="doc_type", label="文档类型", type="text", default=_DEFAULT_DOC_TYPE,
                    placeholder="如：设备操作规程 / 培训材料 / 验证方案",
                    help="告知 AI 该文档的业务类型，作为翻译上下文提升术语与语气准确性",
                ),
                ToolInput(
                    key="date_format", label="译文日期格式", type="select", default="keep",
                    options=[
                        _option("keep", "保持原样"),
                        _option("iso", "ISO 格式"),
                        _option("en", "英文格式"),
                        _option("zh", "中文格式"),
                    ],
                    help="日期由程序转换不经模型（如 keep 原样、iso 2026-01-31）；"
                         "英文/中文格式仅在译入对应语言时生效",
                ),
                ToolInput(
                    key="profile_pages", label="领域预读页数", type="number", default=5,
                    help="仅 PDF：翻译前先读前 N 页生成「领域档案」注入翻译提示（0~50，0=关闭）",
                ),
                ToolInput(
                    key="pages", label="翻译页码范围", type="text", default="",
                    placeholder="如 1-20 或 6，留空=全部页",
                    help="仅 PDF：只翻译指定页码范围，适合大文档先试译部分",
                ),
            ],
        ),
    ],
)
async def document_translate(
    step_id: str, params: dict[str, Any], context: StepContext
) -> dict[str, Any]:
    # ── 输入文件 ──
    paths = context.file_paths.get("input_file") or []
    if not paths:
        raise ToolError("缺少待翻译文档")
    input_path = Path(paths[0])
    if input_path.suffix.lower() not in (".docx", ".pdf"):
        raise ToolError(f"仅支持 .docx / .pdf 文件，收到「{input_path.name}」")

    # ── 工具配置（管理员配置页维护）──
    cfg = context.config or {}
    ai_raw = cfg.get("ai")
    ai_cfg = ai_raw if isinstance(ai_raw, dict) else {}
    api_base_url = str(ai_cfg.get("api_base_url") or "").strip()
    api_key = str(ai_cfg.get("api_key") or "").strip()
    model = str(ai_cfg.get("model") or "").strip()
    if not (api_base_url and api_key and model):
        raise ToolError("请先在工具配置中填写 AI 模型信息（接口地址 / API Key / 模型名称）")
    thinking_level = str(ai_cfg.get("thinking_level") or "").strip()
    if thinking_level not in _VALID_THINKING_LEVELS:
        raise ToolError("思考等级只能是空（默认）/ low / high / max")
    translate_raw = cfg.get("translate")
    translate_cfg = translate_raw if isinstance(translate_raw, dict) else {}
    batch_size = _positive_int(translate_cfg.get("batch_size"), 30, "每批段落数")
    concurrency = _positive_int(translate_cfg.get("concurrency"), 4, "并发请求数", maximum=16)

    # ── 步骤参数校验（前端已约束，此处兜底）──
    mode = params.get("mode") or "bilingual"
    if mode not in _VALID_MODES:
        raise ToolError(f"输出模式只能是 {' / '.join(_VALID_MODES)}")
    direction = params.get("direction") or "auto"
    if direction not in _VALID_DIRECTIONS:
        raise ToolError(f"翻译方向只能是 {' / '.join(_VALID_DIRECTIONS)}")
    date_format = params.get("date_format") or "keep"
    if date_format not in _VALID_DATE_FORMATS:
        raise ToolError(f"译文日期格式只能是 {' / '.join(_VALID_DATE_FORMATS)}")
    doc_type = str(params.get("doc_type") or "").strip() or _DEFAULT_DOC_TYPE
    profile_pages_raw = params.get("profile_pages")
    try:
        profile_pages = 5 if profile_pages_raw in (None, "") else int(profile_pages_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ToolError("领域预读页数需为 0~50 的整数（0=关闭）") from None
    if not 0 <= profile_pages <= 50:
        raise ToolError("领域预读页数需为 0~50 的整数（0=关闭）")
    pages = str(params.get("pages") or "").strip()
    if pages and not re.fullmatch(r"\d+(-\d+)?", pages):
        raise ToolError('翻译页码范围格式不正确，应为 "1-20" 或 "6"，留空=全部页')

    # ── 术语表：配置页 CSV 内容 → 执行目录临时文件（空内容=禁用）──
    glossary_raw = cfg.get("glossary")
    glossary_cfg = glossary_raw if isinstance(glossary_raw, dict) else {}
    glossary_text = str(glossary_cfg.get("csv_content") or "").strip()
    glossary_path = ""
    if glossary_text:
        glossary_path = str(context.output_dir / "glossary.csv")
        Path(glossary_path).write_bytes(glossary_text.encode("utf-8-sig"))

    # ── 引擎设置：产物写执行目录，命名沿用引擎规则 ──
    suffix = "_bilingual" if mode == "bilingual" else "_translated"
    output_path = context.output_dir / f"{input_path.stem}{suffix}.docx"
    report_path = output_path.with_suffix(".report.md")
    s = Settings(
        input=str(input_path),
        output=str(output_path),
        report=str(report_path),
        mode=mode,
        direction=direction,
        doc_type=doc_type,
        glossary=glossary_path,
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        batch_size=batch_size,
        concurrency=concurrency,
        thinking_level=thinking_level,
        date_format=date_format,
        profile_pages=profile_pages,
        pages=pages,
        mock=False,
    )

    reporter = context.report_progress

    def progress_cb(percent: int, message: str) -> None:
        if reporter:
            reporter(percent, message)

    # 引擎的 print/stderr 全程捕获：错误场景作为用户可见消息返回，不污染服务日志。
    # 锁内才安全：重定向是进程级的，无锁并发时不同任务的捕获互相串写
    out_buf, err_buf = io.StringIO(), io.StringIO()
    async with _engine_lock:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            rc = await asyncio.to_thread(run_pipeline, s, progress_cb)

    # 退出码非 0 且无产物 = 前置失败（文件/参数/凭据问题），stderr 即原因
    if rc != 0 and not output_path.exists():
        detail = err_buf.getvalue().strip()
        raise ToolError(detail or "翻译失败：引擎未产出文件，请联系管理员查看服务器日志")

    # ── 产物注册：翻译后文件 + 校验报告（48h 内可下载）──
    translated_fid, _ = await asyncio.to_thread(
        storage.save_upload, context.execution_id, output_path.name, output_path.read_bytes()
    )
    report_fid, _ = await asyncio.to_thread(
        storage.save_upload, context.execution_id, report_path.name, report_path.read_bytes()
    )
    return {
        "report_md": report_path.read_text(encoding="utf-8"),
        "translated_file": {"file_id": translated_fid, "filename": output_path.name},
        "report_file": {"file_id": report_fid, "filename": report_path.name},
    }
