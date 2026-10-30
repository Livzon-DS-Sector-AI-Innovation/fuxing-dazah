"""工具函数层测试：参数/配置校验、批量编排、产物注册、术语表覆盖生效。

内置术语对 fixture 完全覆盖，故 monkeypatch translate_terms 设为「被调用
即失败」——既避免测试触网，也守护内置术语表不回退。"""

from pathlib import Path
from typing import Any, cast

import pytest

from app.modules.toolbox import storage
from app.modules.toolbox.registry import StepContext, ToolError
from app.modules.toolbox.tools.chromatogram_translate import (
    chromatogram_translate as run_tool,
)
from app.modules.toolbox.tools.chromatogram_translate._core import llm as llm_mod

FIXTURES = Path(__file__).parent / "fixtures"
AI_CONFIG: dict[str, Any] = {
    "ai": {
        "api_base_url": "https://api.example.com",
        "api_key": "sk-test",
        "model": "test-model",
    },
}


def make_context(
    tmp_path: Path,
    input_files: list[Path],
    config: dict[str, Any] | None = None,
) -> StepContext:
    return StepContext(
        execution_id="exec-test",
        user_id="u1",
        prev_outputs={},
        file_paths={"input_files": [str(f) for f in input_files]},
        output_dir=tmp_path,
        config=config if config is not None else AI_CONFIG,
    )


def no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("fixture 应被内置术语完全覆盖，不应触发 LLM 补译")

    monkeypatch.setattr(llm_mod, "translate_terms", _fail)


@pytest.fixture
def bsa() -> Path:
    return FIXTURES / "sample_bsa.pdf"


async def test_batch_success_and_failed_mix(
    tmp_path: Path, bsa: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """批量：可翻译文件出产物，无文本层文件明确失败且不出产物，报告含两者；
    多个成功文件时提供 ZIP 打包（内含全部译文名 PDF + 报告）。"""
    no_llm(monkeypatch)
    from .test_core_pipeline import make_no_text_pdf

    blank = FIXTURES / "sample_blank.pdf"
    bad = make_no_text_pdf(tmp_path / "vector.pdf")
    ctx = make_context(tmp_path, [bsa, blank, bad])
    progress: list[tuple[int, str]] = []
    ctx.report_progress = lambda pct, msg: progress.append((pct, msg))

    result = await run_tool("translate", {}, ctx)

    assert result["成功文件数"] == 2
    assert result["失败文件数"] == 1
    assert {f["filename"] for f in result["files"]} == {
        "sample_bsa_英文.pdf",
        "sample_blank_英文.pdf",
    }
    assert "文本层" in result["report_md"]
    assert "AI 补译词条" not in result["report_md"]
    # 产物可按 file_id 找回
    for ref in result["files"]:
        p = storage.resolve_file("exec-test", ref["file_id"])
        assert p is not None and p.exists()
    # ZIP 打包：包含两个译文名 PDF 与校验报告
    import zipfile

    zp = storage.resolve_file("exec-test", result["zip_file"]["file_id"])
    assert zp is not None
    with zipfile.ZipFile(zp) as zf:
        names = set(zf.namelist())
    assert names == {
        "sample_bsa_英文.pdf",
        "sample_blank_英文.pdf",
        "chromatogram_report.md",
    }
    assert progress[-1] == (100, "完成：成功 2/3")


async def test_single_success_has_no_zip(
    tmp_path: Path, bsa: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单个成功文件不产 ZIP（zip_file 为 None，前端不渲染）。"""
    no_llm(monkeypatch)
    result = await run_tool("translate", {}, make_context(tmp_path, [bsa]))
    assert result["成功文件数"] == 1
    assert result["zip_file"] is None


async def test_glossary_override_applies_to_output(
    tmp_path: Path, bsa: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置页术语覆盖内置：色谱图→Plot 出现在译后文本。"""
    no_llm(monkeypatch)
    cfg = {
        "ai": AI_CONFIG["ai"],
        "glossary": {"csv_content": "自动标尺色谱图,Auto Plot"},
    }
    ctx = make_context(tmp_path, [bsa], cfg)
    result = await run_tool("translate", {}, ctx)
    assert result["成功文件数"] == 1
    out = storage.resolve_file("exec-test", result["files"][0]["file_id"])
    import pymupdf

    text = "\n".join(cast(str, pg.get_text()) for pg in pymupdf.open(str(out)))
    assert "Auto Plot" in text and "Auto-Scaled" not in text


async def test_missing_files_rejected(tmp_path: Path) -> None:
    ctx = StepContext(
        execution_id="e",
        user_id="u",
        prev_outputs={},
        file_paths={},
        output_dir=tmp_path,
    )
    with pytest.raises(ToolError, match="缺少"):
        await run_tool("translate", {}, ctx)


async def test_non_pdf_rejected(tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(ToolError, match="仅支持"):
        await run_tool("translate", {}, make_context(tmp_path, [f]))


async def test_too_many_files_rejected(tmp_path: Path, bsa: Path) -> None:
    many = [bsa] * 51
    with pytest.raises(ToolError, match="最多"):
        await run_tool("translate", {}, make_context(tmp_path, many))


async def test_missing_ai_config_rejected(tmp_path: Path, bsa: Path) -> None:
    with pytest.raises(ToolError, match="工具配置"):
        await run_tool("translate", {}, make_context(tmp_path, [bsa], config={}))


async def test_llm_failure_raises_tool_error(
    tmp_path: Path, bsa: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有缺词且补译失败：整批中止并给用户可见错误（不带中文原文输出）。"""

    def _fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise llm_mod.LLMError("补译失败（已重试 2 次）：401")

    monkeypatch.setattr(llm_mod, "translate_terms", _fail)
    monkeypatch.setattr(
        "app.modules.toolbox.tools.chromatogram_translate._core.terms.BUILTIN_TERMS",
        {"名称": "Name"},  # 抽空内置表，制造缺词
    )
    with pytest.raises(ToolError, match="补译失败"):
        await run_tool("translate", {}, make_context(tmp_path, [bsa]))


async def test_original_filenames_used_for_outputs(
    tmp_path: Path, bsa: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落盘路径是内部 uuid 名时，产物/报告一律用用户上传的原始文件名。

    回归：曾出现「下载 dc0161104cab…_英文.pdf」——uuid 落盘名泄漏到产物。
    """
    no_llm(monkeypatch)
    import shutil

    # 模拟真实链路：磁盘上是 uuid 名，原始名只在 file_names 里
    uuid_stem = "dc0161104cab490585b0527ebf137a49"
    uuid_path = tmp_path / f"{uuid_stem}.pdf"
    shutil.copy(bsa, uuid_path)
    ctx = StepContext(
        execution_id="exec-test",
        user_id="u1",
        prev_outputs={},
        file_paths={"input_files": [str(uuid_path)]},
        file_names={"input_files": ["峰鉴别-1.pdf"]},
        output_dir=tmp_path,
        config=AI_CONFIG,
    )
    result = await run_tool("translate", {}, ctx)
    assert result["成功文件数"] == 1
    assert result["files"][0]["filename"] == "峰鉴别-1_英文.pdf"
    assert uuid_stem not in result["report_md"]
    assert "峰鉴别-1" in result["report_md"]
