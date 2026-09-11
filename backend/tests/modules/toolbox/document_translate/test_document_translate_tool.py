"""文档翻译工具：参数校验、配置读取、术语表落盘、产物注册。

引擎调用以假 run_pipeline 替身覆盖（真引擎的 mock 离线测试见
test_document_translate_engine.py），本文件聚焦工具函数自身逻辑。
"""

import sys
from pathlib import Path
from typing import Any

import pytest
from docx import Document

from app.modules.toolbox import storage
from app.modules.toolbox.registry import StepContext, ToolError
from app.modules.toolbox.tools import document_translate
from app.modules.toolbox.tools.document_translate import document_translate as run_tool

AI_CONFIG: dict[str, Any] = {
    "ai": {"api_base_url": "https://api.example.com", "api_key": "sk-test", "model": "test-model"}
}


def make_context(
    tmp_path: Path,
    input_file: Path,
    config: dict[str, Any] | None = None,
) -> StepContext:
    return StepContext(
        execution_id="exec-test",
        user_id="u1",
        prev_outputs={},
        file_paths={"input_file": [str(input_file)]},
        output_dir=tmp_path,
        config=config if config is not None else AI_CONFIG,
    )


def make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("This is a test paragraph.")
    doc.save(str(path))
    return path


@pytest.fixture
def docx_file(tmp_path: Path) -> Path:
    return make_docx(tmp_path / "sample.docx")


async def test_success_registers_outputs_and_returns_report(
    tmp_path: Path, docx_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功路径：产物落盘注册、报告全文与下载引用返回、进度回调透传。"""
    seen_settings: dict[str, Any] = {}

    def fake_run_pipeline(s, progress_cb=None):
        seen_settings.update({
            "mode": s.mode, "direction": s.direction, "date_format": s.date_format,
            "doc_type": s.doc_type, "profile_pages": s.profile_pages, "pages": s.pages,
            "glossary": s.glossary, "api_key": s.api_key, "mock": s.mock,
        })
        if progress_cb:
            progress_cb(50, "半程")
        make_docx(Path(s.output))
        Path(s.report).write_text("# 翻译校验报告\n\n**✅ 全部通过**\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(document_translate, "run_pipeline", fake_run_pipeline)
    ctx = make_context(tmp_path, docx_file)
    progress: list[tuple[int, str]] = []
    ctx.report_progress = lambda pct, msg: progress.append((pct, msg))
    result = await run_tool("translate", {
        "mode": "replace", "direction": "en2zh", "doc_type": "设备操作规程",
        "date_format": "zh", "profile_pages": 0, "pages": "1-5",
    }, ctx)

    assert result["report_md"].startswith("# 翻译校验报告")
    assert result["translated_file"]["filename"] == "sample_translated.docx"
    assert result["report_file"]["filename"] == "sample_translated.report.md"
    # 产物已注册，可按 file_id 找回
    for ref in (result["translated_file"], result["report_file"]):
        p = storage.resolve_file("exec-test", ref["file_id"])
        assert p is not None and p.exists()
    assert progress == [(50, "半程")]
    assert seen_settings["mode"] == "replace"
    assert seen_settings["direction"] == "en2zh"
    assert seen_settings["date_format"] == "zh"
    assert seen_settings["doc_type"] == "设备操作规程"
    assert seen_settings["profile_pages"] == 0
    assert seen_settings["pages"] == "1-5"
    assert seen_settings["mock"] is False


async def test_default_params_pass_engine_defaults(
    tmp_path: Path, docx_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """参数缺省时回退引擎默认值（mode/direction/date_format/profile_pages/doc_type）。"""
    seen: dict[str, Any] = {}

    def fake_run_pipeline(s, progress_cb=None):
        seen.update({"mode": s.mode, "direction": s.direction, "date_format": s.date_format,
                     "doc_type": s.doc_type, "profile_pages": s.profile_pages, "pages": s.pages})
        make_docx(Path(s.output))
        Path(s.report).write_text("report", encoding="utf-8")
        return 0

    monkeypatch.setattr(document_translate, "run_pipeline", fake_run_pipeline)
    result = await run_tool("translate", {}, make_context(tmp_path, docx_file))
    assert result["translated_file"]["filename"] == "sample_bilingual.docx"
    assert seen == {
        "mode": "bilingual", "direction": "auto", "date_format": "keep",
        "doc_type": "GMP 文件（批记录/工艺验证报告）", "profile_pages": 5, "pages": "",
    }


async def test_glossary_content_written_to_file(
    tmp_path: Path, docx_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """术语表配置：内容写入执行目录（utf-8-sig）；留空时禁用（空路径）。"""
    seen: dict[str, str] = {}

    def fake_run_pipeline(s, progress_cb=None):
        seen["glossary"] = s.glossary
        make_docx(Path(s.output))
        Path(s.report).write_text("report", encoding="utf-8")
        return 0

    monkeypatch.setattr(document_translate, "run_pipeline", fake_run_pipeline)

    cfg = {"ai": AI_CONFIG["ai"], "glossary": {"csv_content": "中文,English\n无菌,sterile"}}
    await run_tool("translate", {}, make_context(tmp_path, docx_file, cfg))
    assert seen["glossary"] == str(tmp_path / "glossary.csv")
    content = Path(seen["glossary"]).read_bytes()
    assert content.startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM（引擎 load_glossary 约定）
    assert "无菌,sterile" in content.decode("utf-8-sig")

    await run_tool("translate", {}, make_context(tmp_path, docx_file))
    assert seen["glossary"] == ""


async def test_missing_input_file_rejected(tmp_path: Path) -> None:
    ctx = StepContext(execution_id="e", user_id="u", prev_outputs={}, file_paths={}, output_dir=tmp_path)
    with pytest.raises(ToolError, match="缺少待翻译文档"):
        await run_tool("translate", {}, ctx)


async def test_wrong_suffix_rejected(tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(ToolError, match="仅支持"):
        await run_tool("translate", {}, make_context(tmp_path, f))


async def test_missing_ai_config_rejected(tmp_path: Path, docx_file: Path) -> None:
    with pytest.raises(ToolError, match="工具配置"):
        await run_tool("translate", {}, make_context(tmp_path, docx_file, config={}))


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"mode": "weird"}, "输出模式"),
        ({"direction": "xx"}, "翻译方向"),
        ({"date_format": "xx"}, "日期格式"),
        ({"pages": "abc"}, "页码范围"),
        ({"profile_pages": 51}, "领域预读页数"),
    ],
)
async def test_invalid_params_rejected(
    tmp_path: Path, docx_file: Path, params: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ToolError, match=fragment):
        await run_tool("translate", params, make_context(tmp_path, docx_file))


async def test_invalid_thinking_level_in_config_rejected(
    tmp_path: Path, docx_file: Path
) -> None:
    cfg = {"ai": {**AI_CONFIG["ai"], "thinking_level": "extreme"}}
    with pytest.raises(ToolError, match="思考等级"):
        await run_tool("translate", {}, make_context(tmp_path, docx_file, cfg))


async def test_engine_failure_without_output_raises_tool_error(
    tmp_path: Path, docx_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引擎退出码非 0 且无产物：stderr 文本作为用户可见错误透传。"""

    def fake_run_pipeline(s, progress_cb=None):
        print("错误：输入文件疑似扫描件，请先 OCR", file=sys.stderr)
        return 2

    monkeypatch.setattr(document_translate, "run_pipeline", fake_run_pipeline)
    with pytest.raises(ToolError, match="OCR"):
        await run_tool("translate", {}, make_context(tmp_path, docx_file))


async def test_engine_hard_issues_still_returns_result(
    tmp_path: Path, docx_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """退出码 2 但产物存在（翻译完成、有硬性问题）：正常返回，报告结论用户可见。"""

    def fake_run_pipeline(s, progress_cb=None):
        make_docx(Path(s.output))
        Path(s.report).write_text("# 翻译校验报告\n\n**❌ 存在必须处理的问题**\n", encoding="utf-8")
        return 2

    monkeypatch.setattr(document_translate, "run_pipeline", fake_run_pipeline)
    result = await run_tool("translate", {}, make_context(tmp_path, docx_file))
    assert "❌" in result["report_md"]
    assert result["translated_file"]["file_id"]
