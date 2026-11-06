"""① 补录管线纯函数单测（P1-1 R3b，S3/S4 接缝）—— 全合成，不碰 ragplus/DB。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "ingest_regulation_doc.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ingest_regulation_doc", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ing = _load_script()


class TestTablePreprocess:
    def test_rows_to_context_text_with_article_prefix(self) -> None:
        text = ing.table_to_context_text(
            [("5.1", "动火作业前应办理动火作业票。"), ("6.2.1", "受限空间作业应先通风检测。")],
            doc_title="GB 30871-2022 危险化学品企业特殊作业安全规范",
        )
        lines = text.strip().splitlines()
        assert lines[0] == (
            "《GB 30871-2022 危险化学品企业特殊作业安全规范》第5.1条："
            "动火作业前应办理动火作业票。"
        )
        assert "第6.2.1条" in lines[1] and "受限空间" in lines[1]
        assert lines[1].startswith("《GB 30871-2022")

    def test_parse_table_csv(self, tmp_path: Path) -> None:
        csv = tmp_path / "ppe.csv"
        csv.write_text(
            "条文号,内容\n5.1,安全帽应在有效期内使用\n5.2,安全带高挂低用\n",
            encoding="utf-8",
        )
        rows = ing.parse_table_csv(csv)
        assert rows == [("5.1", "安全帽应在有效期内使用"), ("5.2", "安全带高挂低用")]

    def test_parse_table_csv_skips_header_and_blank(self, tmp_path: Path) -> None:
        csv = tmp_path / "x.csv"
        csv.write_text("条文号,内容\n,\n5.1,内容一\n", encoding="utf-8")
        assert ing.parse_table_csv(csv) == [("5.1", "内容一")]


class TestProbeVerify:
    async def test_probe_hit_when_doc_in_results(self) -> None:
        async def fake_search(question: str, top_k: int = 6):
            class _Hit:
                def __init__(self, name: str) -> None:
                    self.doc_name = name
            return [_Hit("GB 30871-2022 危险化学品企业特殊作业安全规范.pdf")]

        ok, detail = await ing.verify_probe_hits(
            ["受限空间作业"], "GB 30871-2022 危险化学品企业特殊作业安全规范",
            search=fake_search,
        )
        assert ok is True
        assert detail["受限空间作业"] is True

    async def test_probe_miss_when_doc_absent(self) -> None:
        async def fake_search(question: str, top_k: int = 6):
            class _Hit:
                def __init__(self, name: str) -> None:
                    self.doc_name = name
            return [_Hit("无关文档.pdf")]

        ok, detail = await ing.verify_probe_hits(
            ["动火作业票"], "GB 30871", search=fake_search,
        )
        assert ok is False
        assert detail["动火作业票"] is False

    async def test_probe_search_error_is_miss_not_crash(self) -> None:
        async def fake_search(question: str, top_k: int = 6):
            raise RuntimeError("引擎不可用")

        ok, detail = await ing.verify_probe_hits(
            ["探针"], "任意", search=fake_search,
        )
        assert ok is False
