"""COA 快速打印：回填后的 docx 转 PDF，带缓存、出文件即留档。

沿用 test_coa_template_api 的 harness（权限打桩、文件存储换内存字典、AI 标注
打桩、模板现搭）。接口用例把 LibreOffice 换成打桩，只验证链路；转换本身由
「装了 LibreOffice 的机器才跑」的那一条用真实进程验证。
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pymupdf
import pytest
from docx.opc.oxml import serialize_part_xml
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from httpx import AsyncClient

from app.core.exceptions import AppException
from app.modules.qa.service.coa import template_pdf
from app.modules.qa.service.coa.template_pdf import docx_to_pdf, find_soffice
from tests.modules.qa._coa_template_builder import build_template
from tests.modules.qa.test_coa_api import ISSUE, MANAGE, READ, _client
from tests.modules.qa.test_coa_template_api import _bound_standard, _report
from tests.modules.qa.test_coa_template_api import (
    memory_storage as _memory_storage,
)
from tests.modules.qa.test_coa_template_api import (
    stub_annotation as _stub_annotation,
)

# pytest 按名字在模块里找 fixture：把别处定义的两个 fixture 挂到本模块名下
memory_storage = _memory_storage
stub_annotation = _stub_annotation

pytestmark = pytest.mark.anyio

PRINT = "/api/v1/qa/coa/reports/{}/print"
FAKE_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
AUDIT = {"qa:audit:read"}
# 建标准要管理权限，出文件要出具权限，查日志要审计读权限
PRINT_PERMS = MANAGE | ISSUE | AUDIT


# ─────────────────────── 夹具与取数 ───────────────────────


@pytest.fixture
def print_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """缓存换到用例自己的临时目录，并把「上次清理时间」归零。"""
    monkeypatch.setattr(template_pdf, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(template_pdf, "_last_sweep", 0.0)
    return tmp_path


@pytest.fixture
def fake_soffice(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """把 LibreOffice 换成打桩：记下每次收到的 docx，返回一份固定 PDF。"""
    seen: list[bytes] = []

    def _convert(docx: bytes, *, soffice: str | None = None) -> bytes:
        seen.append(docx)
        return FAKE_PDF

    monkeypatch.setattr(template_pdf, "docx_to_pdf", _convert)
    return seen


async def _records(ac: AsyncClient, report_id: str) -> list[dict[str, Any]]:
    resp = await ac.get("/api/v1/qa/coa/renders", params={"report_id": report_id})
    assert resp.status_code == 200, resp.text[:200]
    return list(resp.json()["data"])


async def _render_logs(ac: AsyncClient, report_id: str) -> list[dict[str, Any]]:
    """这份报告的「生成 COA」日志（下载和快速打印都记在这个动作下）。"""
    resp = await ac.get(
        "/api/v1/qa/operation-logs",
        params={"resource_type": "qa.coa_report", "report_id": report_id},
    )
    assert resp.status_code == 200, resp.text[:200]
    return [log for log in resp.json()["data"] if log["action"] == "report_rendered"]


# ─────────────────────── 接口 ───────────────────────


async def test_print_opens_inline_pdf_and_converts_once(
    print_cache: Path,
    fake_soffice: list[bytes],
    memory_storage: dict[str, bytes],
    stub_annotation: list[str],
) -> None:
    perms = PRINT_PERMS
    async with _client(perms) as (ac, _):
        standard = await _bound_standard(ac)
        report = await _report(ac, standard)
        url = PRINT.format(report["id"])

        first = await ac.get(url)
        assert first.status_code == 200, first.text[:200]
        assert first.content == FAKE_PDF
        assert first.headers["content-type"].startswith("application/pdf")
        # 浏览器里直接打开（不是下载），文件名跟着报告走
        assert first.headers["content-disposition"].startswith("inline;")
        assert ".pdf" in first.headers["content-disposition"]
        assert first.headers["cache-control"] == "no-store"

        again = await ac.get(url)
        assert (again.status_code, again.content) == (200, FAKE_PDF)
        # 同一份 docx 只转一次、只留一条底稿；每次打印都记日志
        assert len(fake_soffice) == 1
        assert len(await _records(ac, report["id"])) == 1
        assert len(await _render_logs(ac, report["id"])) == 2

        # 登记内容改了：docx 跟着变，就重新转、再留一条底稿
        resp = await ac.patch(
            f"/api/v1/qa/coa/reports/{report['id']}", json={"packaging": "7kg/Tin"}
        )
        assert resp.status_code == 200, resp.text[:200]
        changed = await ac.get(url)
        assert (changed.status_code, changed.content) == (200, FAKE_PDF)
        assert len(fake_soffice) == 2
        assert len(await _records(ac, report["id"])) == 2
        assert len(await _render_logs(ac, report["id"])) == 3


async def test_print_after_download_reuses_the_archive(
    print_cache: Path,
    fake_soffice: list[bytes],
    memory_storage: dict[str, bytes],
    stub_annotation: list[str],
) -> None:
    """下载和打印的是同一份内容：底稿只留下载那一条，打印只记日志。"""
    perms = PRINT_PERMS
    async with _client(perms) as (ac, _):
        standard = await _bound_standard(ac)
        report = await _report(ac, standard)
        downloaded = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
        assert downloaded.status_code == 200, downloaded.text[:200]

        printed = await ac.get(PRINT.format(report["id"]))
        assert printed.status_code == 200, printed.text[:200]
        # 拿去转 PDF 的就是刚下载的那份内容（不比字节：docx 里带保存时间）
        assert len(fake_soffice) == 1
        assert template_pdf.cache_key(fake_soffice[0]) == template_pdf.cache_key(
            downloaded.content
        )
        assert len(await _records(ac, report["id"])) == 1
        assert len(await _render_logs(ac, report["id"])) == 2


async def test_print_blocked_without_values_gives_readable_page(
    print_cache: Path, memory_storage: dict[str, bytes], stub_annotation: list[str]
) -> None:
    """这个地址在新标签页里直接打开：拦截时要给人一页提示，而不是一段 JSON。"""
    async with _client(PRINT_PERMS) as (ac, _):
        standard = await _bound_standard(ac)
        report = await _report(ac, standard, include=())
        resp = await ac.get(PRINT.format(report["id"]))
        assert resp.status_code == 422
        assert resp.headers["content-type"].startswith("text/html")
        assert "COA 打印版没有生成" in resp.text
        assert "没有登记值" in resp.text
        assert await _records(ac, report["id"]) == []


async def test_print_without_libreoffice_gives_readable_page(
    print_cache: Path,
    memory_storage: dict[str, bytes],
    stub_annotation: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(template_pdf, "find_soffice", lambda: None)
    async with _client(PRINT_PERMS) as (ac, _):
        standard = await _bound_standard(ac)
        report = await _report(ac, standard)
        resp = await ac.get(PRINT.format(report["id"]))
        assert resp.status_code == 503
        assert resp.headers["content-type"].startswith("text/html")
        assert "LibreOffice" in resp.text
        assert "下载 COA" in resp.text
        # 没出文件就不留档
        assert await _records(ac, report["id"]) == []


async def test_print_of_unknown_report_gives_readable_page(print_cache: Path) -> None:
    async with _client(PRINT_PERMS) as (ac, _):
        resp = await ac.get(PRINT.format(uuid4()))
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
        assert "COA 打印版没有生成" in resp.text


async def test_print_needs_issue_permission(print_cache: Path) -> None:
    """出文件和下载同一个权限：只读的人能看报告，不能出打印版。"""
    async with _client(READ) as (ac, _):
        resp = await ac.get(PRINT.format(uuid4()))
        assert resp.status_code == 403


# ─────────────────────── 转换 ───────────────────────


def _fake_soffice(directory: Path, body: str) -> Path:
    """一个假的 soffice：照 LibreOffice 的约定把 ``<源名>.pdf`` 写进 --outdir，
    并把收到的源文件名记到 ``seen`` 里。"""
    script = directory / "soffice"
    script.write_text(
        "#!/bin/sh\n"
        'out=""; src=""; prev=""\n'
        'for arg in "$@"; do\n'
        '  [ "$prev" = "--outdir" ] && out="$arg"\n'
        '  case "$arg" in *.docx) src="$arg" ;; esac\n'
        '  prev="$arg"\n'
        "done\n"
        f'basename "$src" > "{directory}/seen"\n'
        '[ -n "$FONTCONFIG_FILE" ] && [ -f "$FONTCONFIG_FILE" ] && echo fonts-conf >> "'
        f'{directory}/seen"\n'
        f'shasum -a 256 "$src" | cut -d" " -f1 >> "{directory}/seen"\n'
        f'{body} > "$out/$(basename "$src" .docx).pdf"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _workdirs_left() -> list[str]:
    return sorted(path.name for path in Path(tempfile.gettempdir()).glob("coa-print-*"))


def _child(parent: Any, tag: str) -> Any:
    element = OxmlElement(tag)
    parent.append(element)
    return element


def _docx_with_borders(docx: bytes) -> bytes:
    """给模板第一张表和第一个段落加几条边框，覆盖「该改 / 不该改」的全部情形。"""
    source = zipfile.ZipFile(io.BytesIO(docx))
    root = parse_xml(source.read("word/document.xml"))
    table = root.find(f".//{qn('w:tbl')}")
    paragraph = root.find(f".//{qn('w:p')}")
    assert table is not None and paragraph is not None
    cell_pr = table.find(f".//{qn('w:tcPr')}")
    table_pr = table.find(qn("w:tblPr"))
    assert cell_pr is not None and table_pr is not None
    paragraph_pr = OxmlElement("w:pPr")
    paragraph.insert(0, paragraph_pr)  # pPr 必须是段落的第一个子节点

    def edge(parent: Any, tag: str, val: str, size: str) -> None:
        element = _child(parent, tag)
        element.set(qn("w:val"), val)
        element.set(qn("w:sz"), size)

    cell_borders = _child(cell_pr, "w:tcBorders")
    edge(cell_borders, "w:top", "double", "4")  # 该改：0.5 磅双线（语料里的写法）
    edge(cell_borders, "w:left", "double", "12")  # 不该改：1.5 磅双线，Word 也画两条
    edge(cell_borders, "w:bottom", "single", "4")  # 不该改：本来就是单线
    table_borders = _child(table_pr, "w:tblBorders")
    edge(
        table_borders, "w:insideH", "thinThickSmallGap", "4"
    )  # 该改：别的细多线样式也改成单线
    paragraph_border = _child(paragraph_pr, "w:pBdr")
    edge(paragraph_border, "w:top", "double", "4")  # 不该改：段落边框不在范围内

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "word/document.xml":
                payload = serialize_part_xml(root)
            target.writestr(info, payload)
    return out.getvalue()


def _borders(docx: bytes) -> list[tuple[str, str | None, str | None]]:
    """边框 (所在, 样式, 线宽)，按文档顺序。"""
    archive = zipfile.ZipFile(io.BytesIO(docx))
    root = parse_xml(archive.read("word/document.xml"))
    return [
        (str(holder.tag).split("}")[-1], edge.get(qn("w:val")), edge.get(qn("w:sz")))
        for holder in root.iter(qn("w:tcBorders"), qn("w:tblBorders"), qn("w:pBdr"))
        for edge in holder
    ]


def test_print_copy_flattens_only_hairline_multi_line_borders() -> None:
    docx = _docx_with_borders(build_template())
    copied = template_pdf.print_copy(docx)
    after = _borders(copied)
    # 该改的：细多线边框 → 单线（线宽不变）
    assert ("tcBorders", "single", "4") in after
    assert ("tblBorders", "single", "4") in after
    assert ("tcBorders", "double", "4") not in after
    assert ("tblBorders", "thinThickSmallGap", "4") not in after
    # 不该改的：粗双线、段落边框
    assert ("tcBorders", "double", "12") in after
    assert ("pBdr", "double", "4") in after
    # 条目顺序不变，其它部件逐字节不动
    with (
        zipfile.ZipFile(io.BytesIO(docx)) as before_zip,
        zipfile.ZipFile(io.BytesIO(copied)) as after_zip,
    ):
        assert before_zip.namelist() == after_zip.namelist()
        for name in before_zip.namelist():
            if name != "word/document.xml":
                assert before_zip.read(name) == after_zip.read(name)


# ─────────────────────── 打印副本：行网格 ───────────────────────


_VML_NS = 'xmlns:v="urn:schemas-microsoft-com:vml"'  # python-docx 的前缀表里没有 VML


def _fragment(xml: str) -> Any:
    """一段 XML 片段 → 元素。"""
    return parse_xml(f"<w:root {nsdecls('w')} {_VML_NS}>{xml}</w:root>")[0]


def _run(text: str, half_points: str | None = None) -> str:
    size = f'<w:rPr><w:sz w:val="{half_points}"/></w:rPr>' if half_points else ""
    return f"<w:r>{size}<w:t>{text}</w:t></w:r>"


def _para_xml(ppr: str, inner: str) -> str:
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}{inner}</w:p>"


def _line_spacing_by_text(docx: bytes) -> dict[str, tuple[str, str] | None]:
    """文字 → 段落自己的行距 (lineRule, line)；没写行距的是 None。"""
    root = parse_xml(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    out: dict[str, tuple[str, str] | None] = {}
    for para in root.iter(qn("w:p")):
        text = "".join(t.text or "" for t in para.iter(qn("w:t")))
        if not text:
            continue
        ppr = para.find(qn("w:pPr"))
        spacing = ppr.find(qn("w:spacing")) if ppr is not None else None
        rule = spacing.get(qn("w:lineRule")) if spacing is not None else None
        line = spacing.get(qn("w:line")) if spacing is not None else None
        out[text] = (str(rule), str(line)) if rule else None
    return out


def _docx_on_grid(docx: bytes, grid_type: str = "lines") -> bytes:
    """给模板加 15.6 磅的行网格，再往正文末尾放一批段落，覆盖「该写死行高 / 不该动」的情形。"""
    source = zipfile.ZipFile(io.BytesIO(docx))
    root = parse_xml(source.read("word/document.xml"))
    body = root.find(qn("w:body"))
    sect = body.find(qn("w:sectPr"))
    # 现搭模板自带一个没开行网格的 docGrid：复用它，不另加
    grid = sect.find(qn("w:docGrid"))
    if grid is None:
        grid = _child(sect, "w:docGrid")
    grid.set(qn("w:type"), grid_type)
    grid.set(qn("w:linePitch"), "312")
    styles = parse_xml(source.read("word/styles.xml"))
    for style in (
        '<w:style w:type="paragraph" w:styleId="GridOffStyle"><w:name w:val="Grid Off"/>'
        '<w:pPr><w:snapToGrid w:val="false"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="GridExactStyle"><w:name w:val="Grid Exact"/>'
        '<w:pPr><w:spacing w:lineRule="exact" w:line="240"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="GridBigStyle"><w:name w:val="Grid Big"/>'
        '<w:rPr><w:sz w:val="32"/></w:rPr></w:style>',
    ):
        styles.append(_fragment(style))
    exact = '<w:spacing w:lineRule="exact" w:line="200"/>'
    blocks = [
        _fragment(_para_xml("", _run("甲", "18"))),  # 普通段落 9pt：靠网格撑到一行
        _fragment(_para_xml(exact, _run("乙", "18"))),  # 固定行距：不动
        _fragment(
            _para_xml('<w:snapToGrid w:val="false"/>', _run("丙", "18"))
        ),  # 关了网格对齐
        _fragment(_para_xml("", _run("丁", "32"))),  # 16pt：一行占两格
        _fragment(
            _para_xml(
                '<w:spacing w:lineRule="atLeast" w:line="200"/>', _run("戊", "18")
            )
        ),
        _fragment(
            _para_xml('<w:spacing w:line="360"/>', _run("己", "21"))
        ),  # 1.5 倍行距
        _fragment(_para_xml("", _run("辛"))),  # 没写字号：按默认字号
        _fragment(
            "<w:tbl><w:tr><w:tc><w:tcPr/>"
            + _para_xml("", _run("庚", "18"))
            + "</w:tc></w:tr></w:tbl>"
        ),
        _fragment(
            "<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>"
            + _para_xml("", _run("框", "18"))
            + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>",
        ),
        _fragment(_para_xml('<w:pStyle w:val="GridOffStyle"/>', _run("壬", "18"))),
        _fragment(_para_xml('<w:pStyle w:val="GridExactStyle"/>', _run("癸", "18"))),
        _fragment(_para_xml('<w:pStyle w:val="GridBigStyle"/>', _run("子"))),
    ]
    for block in blocks:
        body.insert(list(body).index(sect), block)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "word/document.xml":
                payload = serialize_part_xml(root)
            elif info.filename == "word/styles.xml":
                payload = serialize_part_xml(styles)
            target.writestr(info, payload)
    return out.getvalue()


def test_print_copy_releases_line_grid_and_pins_grid_dependent_lines() -> None:
    docx = _docx_on_grid(build_template())
    copied = template_pdf.print_copy(docx)
    root = parse_xml(zipfile.ZipFile(io.BytesIO(copied)).read("word/document.xml"))
    grid = root.find(qn("w:body")).find(qn("w:sectPr")).find(qn("w:docGrid"))
    assert grid.get(qn("w:type")) == "default"
    after = _line_spacing_by_text(copied)
    # 靠网格撑行高的：写死成「网格行高 × 行数」，行高和 Word 里一致
    assert after["甲"] == ("exact", "312")  # 9pt：一格
    assert after["丁"] == ("exact", "624")  # 16pt：两格
    assert after["戊"] == ("exact", "312")  # 最小行距 10pt 没超过一格
    assert after["己"] == ("exact", "624")  # 1.5 倍行距：折算后超过一格
    assert after["辛"] == ("exact", "312")
    assert after["庚"] == ("exact", "312")  # 表格里的段落同样处理
    assert after["子"] == ("exact", "624")  # 字号来自段落样式
    # 不靠网格的：一个字节都不动
    assert after["乙"] == ("exact", "200")
    assert after["丙"] is None
    assert after["框"] is None  # 文本框里的文字不受页面网格约束
    assert after["壬"] is None  # 样式里关了网格对齐
    assert after["癸"] is None  # 样式里是固定行距


def test_print_copy_turns_char_grid_into_chars_only() -> None:
    docx = _docx_on_grid(build_template(), grid_type="linesAndChars")
    copied = template_pdf.print_copy(docx)
    grid = (
        parse_xml(zipfile.ZipFile(io.BytesIO(copied)).read("word/document.xml"))
        .find(qn("w:body"))
        .find(qn("w:sectPr"))
        .find(qn("w:docGrid"))
    )
    assert grid.get(qn("w:type")) == "chars"


def test_print_copy_leaves_documents_without_line_grid_alone() -> None:
    docx = build_template()
    # 现搭模板自带一个没开行网格的 docGrid（没写 type）
    assert '<w:docGrid w:linePitch="360"/>' in zip_contents(docx, "word/document.xml")
    copied = template_pdf.print_copy(docx)
    assert _line_spacing_by_text(copied) == _line_spacing_by_text(docx)
    assert '<w:docGrid w:linePitch="360"/>' in zip_contents(copied, "word/document.xml")


# ─────────────────────── 打印副本：固定行高的字顶 ───────────────────────

_TITLE = "检验报告单"


def _cjk_run(
    text: str, half_points: str, before_size: str = "", after_size: str = ""
) -> str:
    """一个黑体粗体 run；before_size / after_size 是要排在字号前 / 后面的属性。"""
    return (
        f'<w:r><w:rPr><w:rFonts w:eastAsia="黑体"/><w:b/>{before_size}'
        f'<w:sz w:val="{half_points}"/>{after_size}</w:rPr><w:t>{text}</w:t></w:r>'
    )


def _docx_with_lines(blocks: list[str], header_block: str | None = None) -> bytes:
    """往模板正文末尾放一批段落（blocks 是 <w:p> 片段）；header_block 放进页眉。"""
    source = zipfile.ZipFile(io.BytesIO(build_template()))
    root = parse_xml(source.read("word/document.xml"))
    sect = root.find(qn("w:body")).find(qn("w:sectPr"))
    for block in blocks:
        sect.addprevious(_fragment(block))
    header = None
    if header_block is not None:
        header = ("word/header1.xml", parse_xml(source.read("word/header1.xml")))
        header[1].append(_fragment(header_block))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "word/document.xml":
                payload = serialize_part_xml(root)
            elif header is not None and info.filename == header[0]:
                payload = serialize_part_xml(header[1])
            target.writestr(info, payload)
    return out.getvalue()


def _fixed_lines(
    docx: bytes, part: str = "word/document.xml"
) -> dict[str, dict[str, Any]]:
    """文字 → 段落自己的行距、段距，以及每个有字的 run 的 (上下移量, 上下标)。"""
    out: dict[str, dict[str, Any]] = {}
    root = parse_xml(zipfile.ZipFile(io.BytesIO(docx)).read(part))
    for para in root.iter(qn("w:p")):
        text = "".join(t.text or "" for t in para.iter(qn("w:t")))
        if not text:
            continue
        ppr = para.find(qn("w:pPr"))
        spacing = ppr.find(qn("w:spacing")) if ppr is not None else None
        runs = []
        for run in para.iter(qn("w:r")):
            if not any((t.text or "").strip() for t in run.iter(qn("w:t"))):
                continue
            rpr = run.find(qn("w:rPr"))
            found = (
                rpr.findall(qn("w:position")) + rpr.findall(qn("w:vertAlign"))
                if rpr is not None
                else []
            )
            runs.append(
                (found[0].get(qn("w:val")), str(found[0].tag).split("}")[-1])
                if found
                else (None, None)
            )
        out[text] = {
            "spacing": {
                key.split("}")[-1]: value for key, value in spacing.attrib.items()
            }
            if spacing is not None
            else {},
            "runs": runs,
        }
    return out


def test_print_copy_grows_title_line_with_its_own_spacing() -> None:
    """16 磅黑体配 16 磅固定行高：行框加高 1.4 磅、等量扣段前距，文字不动。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320" w:before="78" w:after="0"/>',
                _cjk_run(_TITLE, "32"),
            )
        ]
    )
    line = _fixed_lines(template_pdf.print_copy(docx))[_TITLE]
    assert line["spacing"] == {
        "lineRule": "exact",
        "line": "348",
        "before": "50",
        "after": "0",
    }
    assert line["runs"] == [(None, None)]


def test_print_copy_lowers_text_when_spacing_falls_short() -> None:
    """14 磅字挤在 12 磅行高里：段前距只能借到剩 1 磅，还差的一点靠下移补上。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="240" w:before="78" w:after="0"/>',
                _cjk_run(_TITLE, "28"),
            )
        ]
    )
    line = _fixed_lines(template_pdf.print_copy(docx))[_TITLE]
    assert line["spacing"] == {
        "lineRule": "exact",
        "line": "298",
        "before": "20",
        "after": "0",
    }
    assert line["runs"] == [("-1", "position")]


def test_print_copy_leaves_lines_that_are_not_visibly_clipped_alone() -> None:
    """9 磅字配 9 磅行高只被削 0.6 磅、拉丁字母行不会被削、不是固定行距的：都不动。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="180" w:before="78"/>',
                _cjk_run("品名批号", "18"),
            ),
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320"/>',
                '<w:r><w:rPr><w:sz w:val="32"/></w:rPr><w:t>CERTIFICATE OF ANALYSIS</w:t></w:r>',
            ),
            _para_xml("", _cjk_run(_TITLE, "32")),
        ]
    )
    copied = template_pdf.print_copy(docx)
    assert _fixed_lines(copied) == _fixed_lines(docx)


def test_print_copy_does_not_borrow_spacing_it_cannot_spare() -> None:
    """表格里的段落、会折行的长段落、开着自动段距的段落都借不了段距：行高不动，只把文字下移。"""
    docx = _docx_with_lines(
        [
            "<w:tbl><w:tr><w:tc><w:tcPr/>"
            + _para_xml(
                '<w:spacing w:lineRule="exact" w:line="200" w:before="156"/>',
                _cjk_run("日期", "21"),
            )
            + "</w:tc></w:tr></w:tbl>",
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320" w:before="78"/>',
                _cjk_run("字" * 200, "32"),
            ),
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320" w:beforeAutospacing="1" w:before="78"/>',
                _cjk_run(_TITLE, "32"),
            ),
        ]
    )
    lines = _fixed_lines(template_pdf.print_copy(docx))
    # 表格里：行高段距原样，下移一档（只够补一部分，但不会让字底出框）
    assert lines["日期"]["spacing"] == {
        "lineRule": "exact",
        "line": "200",
        "before": "156",
    }
    assert lines["日期"]["runs"] == [("-1", "position")]
    # 长段落：行高段距原样，下移到刚好够
    assert lines["字" * 200]["spacing"] == {
        "lineRule": "exact",
        "line": "320",
        "before": "78",
    }
    assert lines["字" * 200]["runs"] == [("-2", "position")]
    # 自动段距：LibreOffice 不看 before，行高原样，只下移
    assert lines[_TITLE]["spacing"] == {
        "lineRule": "exact",
        "line": "320",
        "beforeAutospacing": "1",
        "before": "78",
    }
    assert lines[_TITLE]["runs"] == [("-2", "position")]


def test_print_copy_borrows_before_spacing_next_to_line_unit_attributes() -> None:
    """WPS 存的模板会同时写 beforeLines / beforeAutospacing="0"：LibreOffice 只认 before，照常借段前距。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:before="78" w:beforeLines="25" w:beforeAutospacing="0" '
                'w:after="0" w:line="240" w:lineRule="exact"/>',
                _cjk_run(_TITLE, "28"),
            )
        ]
    )
    line = _fixed_lines(template_pdf.print_copy(docx))[_TITLE]
    assert line["spacing"] == {
        "before": "20",
        "beforeLines": "25",
        "beforeAutospacing": "0",
        "after": "0",
        "line": "298",
        "lineRule": "exact",
    }
    assert line["runs"] == [("-1", "position")]


def test_print_copy_does_not_push_deep_glyphs_out_of_the_line() -> None:
    """带全角逗号、括号和下伸字母的行往下挪会让字底出框：借不到段距时宁可不挪。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320" w:before="0" w:after="0"/>',
                _cjk_run("检验，报告单", "32"),
            ),
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320" w:before="0" w:after="0"/>',
                _cjk_run("报告单(g)", "32"),
            ),
        ]
    )
    copied = template_pdf.print_copy(docx)
    assert _fixed_lines(copied) == _fixed_lines(docx)


def test_print_copy_grows_line_for_deep_glyphs_when_spacing_allows() -> None:
    """签字行（10.5 磅字挤在 10 磅行高里、带括号）：行框加高到字顶字底都放得下，从段前距里扣。"""
    text = "起草(QC):  审核（RA）："
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="200" w:before="156" w:after="0"/>',
                _cjk_run(text, "21"),
            )
        ]
    )
    line = _fixed_lines(template_pdf.print_copy(docx))[text]
    assert line["spacing"] == {
        "lineRule": "exact",
        "line": "243",
        "before": "113",
        "after": "0",
    }
    assert line["runs"] == [(None, None)]


def test_print_copy_sizes_a_line_by_the_runs_that_paint_text() -> None:
    """段落里混着一个 1 磅的空白 run：字号按真正有字的 run 沿样式链求，不被它带偏。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="200" w:before="78" w:after="0"/>',
                '<w:r><w:rPr><w:sz w:val="2"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r>'
                + "<w:r><w:t>品</w:t></w:r><w:r><w:t>名</w:t></w:r>",
            )
        ]
    )
    line = _fixed_lines(template_pdf.print_copy(docx))[" 品名"]
    # 现搭模板默认 11 磅：字顶放得下要 239 缇的行高，从段前距里扣
    assert line["spacing"] == {
        "lineRule": "exact",
        "line": "239",
        "before": "39",
        "after": "0",
    }
    assert line["runs"] == [(None, None), (None, None)]


def test_print_copy_lowers_runs_on_top_of_existing_offset_and_skips_scripts() -> None:
    """已有的上下移量上叠加；上下标不跟着动。"""
    docx = _docx_with_lines(
        [
            _para_xml(
                '<w:spacing w:lineRule="exact" w:line="320" w:before="0" w:after="0"/>',
                _cjk_run("检", "32")
                + _cjk_run("验", "32", before_size='<w:position w:val="4"/>')
                + _cjk_run("报", "32", after_size='<w:vertAlign w:val="superscript"/>'),
            )
        ]
    )
    lines = _fixed_lines(template_pdf.print_copy(docx))
    assert lines["检验报"]["runs"] == [
        ("-2", "position"),
        ("2", "position"),
        ("superscript", "vertAlign"),
    ]


def test_print_copy_fits_fixed_lines_in_headers_too() -> None:
    """标题在页眉里的模板：页眉部件同样处理，正文不动。"""
    docx = _docx_with_lines(
        [],
        header_block=_para_xml(
            '<w:spacing w:lineRule="exact" w:line="320" w:before="78"/>',
            _cjk_run(_TITLE, "32"),
        ),
    )
    copied = template_pdf.print_copy(docx)
    line = _fixed_lines(copied, "word/header1.xml")[_TITLE]
    # 段后距没动：不把样式里的值抄成显式属性
    assert line["spacing"] == {"lineRule": "exact", "line": "348", "before": "50"}
    assert zip_contents(copied, "word/document.xml") == zip_contents(
        docx, "word/document.xml"
    )


@pytest.mark.parametrize(
    ("step", "size", "twips"),
    [(1, 320, 13), (2, 320, 27), (4, 320, 60), (3, 280, 44), (1, 180, 15)],
)
def test_lowering_follows_libreoffice(step: int, size: int, twips: int) -> None:
    """w:position 的实际位移按 LibreOffice 的折算规则（本机 26.8 与镜像 25.2.3 实测一致）。"""
    assert template_pdf._lowering(step, size) == twips


def zip_contents(docx: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read(name).decode("utf-8")


def test_docx_to_pdf_uses_a_private_workdir_and_cleans_up(tmp_path: Path) -> None:
    script = _fake_soffice(tmp_path, r"printf '%%PDF-1.4\nstub\n%%%%EOF\n'")
    before = _workdirs_left()
    docx = build_template()
    pdf = docx_to_pdf(docx, soffice=str(script))
    assert pdf == b"%PDF-1.4\nstub\n%%EOF\n"
    # 源文件用固定名（批号不落进临时文件名）；字体配置经环境变量交给进程；交给
    # LibreOffice 的是打印副本而不是原件；临时目录用完即删
    seen = (tmp_path / "seen").read_text(encoding="utf-8").split()
    assert seen == [
        "COA.docx",
        "fonts-conf",
        hashlib.sha256(template_pdf.print_copy(docx)).hexdigest(),
    ]
    assert _workdirs_left() == before


@pytest.mark.parametrize(
    ("body", "word"),
    [
        ("true", "转换失败"),  # 退出码 0，但没有产出
        ("printf 'not a pdf'", "转换失败"),  # 产出的不是 PDF
        ("sleep 5", "超时"),
    ],
)
def test_docx_to_pdf_failures_point_to_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, word: str
) -> None:
    monkeypatch.setattr(template_pdf, "_CONVERT_TIMEOUT", 1)
    script = _fake_soffice(tmp_path, body)
    docx = build_template()
    with pytest.raises(AppException) as info:
        docx_to_pdf(docx, soffice=str(script))
    assert info.value.status_code == 503
    assert word in info.value.message
    assert "下载 COA" in info.value.message
    assert _workdirs_left() == []


def test_docx_to_pdf_without_libreoffice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(template_pdf, "find_soffice", lambda: None)
    with pytest.raises(AppException) as info:
        docx_to_pdf(b"docx")
    assert info.value.status_code == 503
    assert "LibreOffice" in info.value.message


def test_print_fontconfig_is_process_scoped() -> None:
    """字体映射只给转 PDF 的进程用：接着系统配置，再补字体目录和兜底映射。"""
    conf = template_pdf.fontconfig_for_print()
    assert '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>' in conf
    fonts_dir = template_pdf.bundled_fonts_dir()
    if fonts_dir is not None:
        assert f"<dir>{fonts_dir}</dir>" in conf
    # 写法是 prefer 而不是 assign：哪天装了真字体，真字体优先
    assert (
        "<family>宋体</family><prefer><family>Noto Serif SC</family></prefer>" in conf
    )
    assert "assign" not in conf


@pytest.mark.skipif(find_soffice() is None, reason="本机没有安装 LibreOffice")
def test_docx_to_pdf_with_real_libreoffice() -> None:
    """真转换一条：现搭的模板能转出一份读得开的单页 PDF。"""
    docx = build_template()
    pdf = docx_to_pdf(docx)
    # PyMuPDF 的 Python 侧没有类型标注（同 pyproject 里对其它模块的说明），只压这一类噪声
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        assert doc.page_count >= 1
        assert "".join(page.get_text() for page in doc).strip()


def test_pdf_name_follows_the_docx_name() -> None:
    assert template_pdf.pdf_name_of("HAF2607001A_HAF-3205-006_COA.docx") == (
        "HAF2607001A_HAF-3205-006_COA.pdf"
    )
    assert template_pdf.pdf_name_of("COA.DOCX") == "COA.pdf"


# ─────────────────────── 缓存 ───────────────────────


def _key_of(text: str) -> str:
    """一段文字装进 zip 当作一份 docx，取它的内容指纹。"""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", text)
    return template_pdf.cache_key(out.getvalue())


def test_cache_only_counts_complete_pdfs(print_cache: Path) -> None:
    key = _key_of("same docx")
    assert template_pdf.read_cached_pdf(key) is None
    template_pdf.write_cached_pdf(key, FAKE_PDF, now=1000.0)
    assert template_pdf.read_cached_pdf(key) == FAKE_PDF
    # 写了一半或损坏的文件不当作命中
    template_pdf._cache_file(print_cache, key).write_bytes(b"%PDF-1.7\nhalf written")
    assert template_pdf.read_cached_pdf(key) is None


def _rezipped(docx: bytes, date_time: tuple[int, int, int, int, int, int]) -> bytes:
    """同一份 docx 换一组 zip 条目时间重新打包——python-docx 每次保存写进的就是当时的时间。"""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(docx)) as source,
        zipfile.ZipFile(out, "w") as target,
    ):
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=date_time)
            entry.compress_type = info.compress_type
            target.writestr(entry, source.read(info.filename))
    return out.getvalue()


def test_cache_key_ignores_save_time_and_tracks_content() -> None:
    docx = build_template()
    resaved = _rezipped(docx, (2020, 1, 1, 0, 0, 0))
    # 字节不一样（只是保存时间不同），内容一样：指纹必须相同，否则缓存会莫名失效
    assert resaved != docx
    assert template_pdf.cache_key(resaved) == template_pdf.cache_key(docx)
    # 内容变了指纹就变
    assert template_pdf.cache_key(
        build_template(filled=False)
    ) != template_pdf.cache_key(docx)


def test_cache_key_follows_the_conversion_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """打印副本或字体映射变了（规则版本加一）：同一份 docx 也要重新转，不能吃旧缓存。"""
    docx = build_template()
    before = template_pdf.cache_key(docx)
    monkeypatch.setattr(template_pdf, "_PRINT_POLICY", template_pdf._PRINT_POLICY + 1)
    assert template_pdf.cache_key(docx) != before


def test_cache_drops_files_older_than_ttl(print_cache: Path) -> None:
    old = _key_of("old")
    fresh = _key_of("fresh")
    now = time.time()
    template_pdf.write_cached_pdf(old, FAKE_PDF, now=now - template_pdf._CACHE_TTL - 60)
    expired = now - template_pdf._CACHE_TTL - 60
    os.utime(template_pdf._cache_file(print_cache, old), (expired, expired))
    template_pdf.write_cached_pdf(fresh, FAKE_PDF, now=now)
    assert template_pdf.read_cached_pdf(old) is None
    assert template_pdf.read_cached_pdf(fresh) == FAKE_PDF
