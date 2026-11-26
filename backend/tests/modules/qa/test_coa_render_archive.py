"""COA 生成留档与验证：出文件即留档；一份 docx 丢进来，能不能判出「是不是系统出的」。

沿用 test_coa_template_api 的 harness（权限打桩、文件存储换内存字典、AI 标注
打桩、模板现搭）。争议文件按真实手法造：拿系统生成的 docx，用 python-docx
改值、改固定文字、删行、加空段，或只动文档属性（相当于 Word 打开又保存）。
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from docx import Document
from httpx import AsyncClient

from app.modules.qa import file_service
from tests.modules.qa._coa_template_builder import build_template
from tests.modules.qa.test_coa_api import ISSUE, MANAGE, READ, _client
from tests.modules.qa.test_coa_template_api import (
    DOCX_MIME,
    _bound_standard,
    _check,
    _report,
)
from tests.modules.qa.test_coa_template_api import (
    memory_storage as _memory_storage,
)
from tests.modules.qa.test_coa_template_api import (
    stub_annotation as _stub_annotation,
)

# pytest 按名字在模块里找 fixture：把别处定义的两个 fixture 挂到本模块名下
memory_storage = _memory_storage
stub_annotation = _stub_annotation

RENDER = MANAGE | ISSUE
AUDIT = READ | {"qa:audit:read"}
Edit = Callable[[Any], None]

RENDERS = "/api/v1/qa/coa/renders"


async def _render(ac: AsyncClient, report_id: str) -> bytes:
    resp = await ac.post(f"/api/v1/qa/coa/reports/{report_id}/render")
    assert resp.status_code == 200, resp.text[:200]
    return resp.content


async def _verify(
    ac: AsyncClient, data: bytes, *, filename: str = "disputed.docx", report_id: Any = None
) -> dict[str, Any]:
    resp = await ac.post(
        f"{RENDERS}/verify",
        files={"file": (filename, data, DOCX_MIME)},
        data={"report_id": str(report_id)} if report_id is not None else {},
    )
    assert resp.status_code == 200, resp.text[:300]
    return _check(resp)


async def _records(ac: AsyncClient, **params: Any) -> list[Any]:
    resp = await ac.get(RENDERS, params=params)
    assert resp.status_code == 200, resp.text[:200]
    return list(resp.json()["data"])


async def _logs(ac: AsyncClient, report_id: str) -> list[Any]:
    resp = await ac.get(
        "/api/v1/qa/operation-logs",
        params={"resource_type": "qa.coa_report", "report_id": report_id},
    )
    assert resp.status_code == 200, resp.text[:200]
    return list(resp.json()["data"])


async def _detail(ac: AsyncClient, report_id: str) -> dict[str, Any]:
    return _check(await ac.get(f"/api/v1/qa/coa/reports/{report_id}"))


async def _standard_of(ac: AsyncClient, report: dict[str, Any]) -> dict[str, Any]:
    return _check(await ac.get(f"/api/v1/qa/coa/standards/{report['standard_id']}"))


def _with_water(
    detail: dict[str, Any], water_id: str, value: str, *, remark: str | None = None
) -> list[dict[str, Any]]:
    """编辑报告的 values 载荷：全量替换语义，其余项目原样带上，只把水分换掉。"""
    return [
        {"item_id": water_id, "value_num": float(value), "value_text": value, "remark": remark}
        if row["item_id"] == water_id
        else {
            "item_id": row["item_id"],
            "value_num": row["value_num"],
            "value_text": row["value_text"],
            "remark": row["remark"],
        }
        for row in detail["values"]
    ]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resave(data: bytes, edit: Edit | None = None) -> bytes:
    doc = Document(io.BytesIO(data))
    if edit is not None:
        edit(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _saved_by_word(doc: Any) -> None:
    """Word 打开又保存：文字一个没动，只有文档属性变了。"""
    doc.core_properties.last_modified_by = "张三"
    doc.core_properties.revision += 1


def _set_result(row: int, text: str) -> Edit:
    """改项目表第 row 行的结果格。"""

    def edit(doc: Any) -> None:
        runs = doc.tables[1].rows[row].cells[3].paragraphs[0].runs
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""

    return edit


def _reorganise_margins() -> Edit:
    """模拟办公软件重新保存时对页眉页脚的重排（照 LibreOffice 实测）：
    拆出首页部件、内容整体再抄一份、多出空部件。"""

    def edit(doc: Any) -> None:
        section = doc.sections[0]
        section.different_first_page_header_footer = True
        for name in ("header", "footer"):
            original = getattr(section, name).paragraphs[0].text
            first = getattr(section, f"first_page_{name}")
            first.is_linked_to_previous = False
            first.paragraphs[0].text = original

    return edit


class TestArchive:
    async def test_download_archives_the_exact_bytes_sent(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            data = await _render(ac, report["id"])

            records = await _records(ac, report_id=report["id"])
            assert len(records) == 1
            record = records[0]
            assert record["file_sha256"] == _sha(data)
            assert (record["batch_no"], record["standard_code"]) == (
                report["batch_no"],
                standard["code"],
            )
            assert record["filename"] == f"{report['batch_no']}_{standard['code']}_COA.docx"
            # 批号 1 + 流水号 1 + 生产日期 1 + 包装规格 1 + 有效期 1 + 三个检测结果
            assert record["positions"] == 8
            assert record["actor_name"] and record["report_voided"] is False
            # 留档的就是送出去的那份：下载回来逐字节相同
            archived = await ac.get(f"{RENDERS}/{record['id']}/file")
            assert archived.status_code == 200 and archived.content == data
            assert record["filename"] in archived.headers["content-disposition"]
            # 一份模板 + 一份留档
            assert len(memory_storage) == 2

    async def test_dry_run_and_blocked_render_leave_no_record(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard, include=("水分",), mfg_date=None)
            url = f"/api/v1/qa/coa/reports/{report['id']}/render"
            assert (await ac.post(url, params={"dry_run": "true"})).status_code == 200
            assert (await ac.post(url)).status_code == 422  # 缺项拦截
            assert await _records(ac, report_id=report["id"]) == []
            assert len(memory_storage) == 1

    async def test_editing_values_then_rendering_again_keeps_both_versions(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """改了登记值再生成：两次生成的原件和当时的值都留着。"""
        async with _client(RENDER) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            first = await _render(ac, report["id"])
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={"values": _with_water(
                    await _detail(ac, report["id"]), standard["items"][0]["id"], "0.63"
                )},
            )
            assert resp.status_code == 200, resp.text
            second = await _render(ac, report["id"])

            records = await _records(ac, report_id=report["id"])
            assert len(records) == 2 and first != second
            assert {record["file_sha256"] for record in records} == {_sha(first), _sha(second)}
            assert [record["batch_no"] for record in records] == [report["batch_no"]] * 2

    async def test_voiding_the_report_keeps_the_archive(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            await _render(ac, report["id"])
            resp = await ac.delete(f"/api/v1/qa/coa/reports/{report['id']}")
            assert resp.status_code == 200, resp.text
            records = await _records(ac, report_id=report["id"])
            assert len(records) == 1 and records[0]["report_voided"] is True

    async def test_reading_records_needs_coa_read_permission(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(None) as (ac, _):
            assert (await ac.get(RENDERS)).status_code == 401
        async with _client({"qa:apr:read"}) as (ac, _):
            assert (await ac.get(RENDERS)).status_code == 403
            verify = await ac.post(
                f"{RENDERS}/verify", files={"file": ("x.docx", b"x", DOCX_MIME)}
            )
            assert verify.status_code == 403
        async with _client({"qa:all:read"}) as (ac, _):
            assert (await ac.get(RENDERS)).status_code == 200

    async def test_archiving_failure_means_no_file(
        self,
        memory_storage: dict[str, bytes],
        stub_annotation: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """存不下来就不出文件：没有留档的 COA 不算系统出具。"""
        async with _client(RENDER) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)

            def _disk_full(*_args: Any, **_kwargs: Any) -> None:
                raise OSError("disk full")

            with monkeypatch.context() as patch:
                patch.setattr(file_service, "store_file", _disk_full)
                resp = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
                assert resp.status_code == 500 and "留档" in resp.json()["message"]
            assert await _records(ac, report_id=report["id"]) == []


class TestVerify:
    async def test_the_untouched_download_is_the_system_original(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])
            result = await _verify(ac, data)
            assert result["verdict"] == "identical"
            assert result["scope"] == "bytes" and result["record"]["file_sha256"] == _sha(data)
            assert result["differing"] == 0 and result["other_records"] == []

    async def test_file_resaved_by_word_without_edits_matches(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """字节不同不能当成改动：用 Word 打开再保存就会改字节。"""
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])
            resaved = _resave(data, _saved_by_word)
            assert _sha(resaved) != _sha(data)

            result = await _verify(ac, resaved)
            assert result["verdict"] == "content_match"
            assert result["scope"] == "full_text"
            assert result["differing"] == 0 and result["other_differences"] == []
            assert result["compared"] == 8
            assert {row["status"] for row in result["slots"]} == {"match"}
            assert result["record"]["batch_no"] == report["batch_no"]  # 按文件里的批号认出来的

    async def test_edited_value_is_altered_and_names_the_field(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            result = await _verify(ac, _resave(data, _set_result(2, "9.99%")))
            assert result["verdict"] == "altered"
            assert result["differing"] == 1 and result["unresolved"] == 0
            water = next(row for row in result["slots"] if row["label"] == "水分")
            assert (water["expected"], water["actual"], water["status"]) == (
                "1.50%",
                "9.99%",
                "differs",
            )
            assert water["sid"] == "T1.R2.G3.p0"
            assert result["record"]["file_sha256"] == _sha(data)

    async def test_whitespace_and_empty_paragraphs_are_not_edits(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """排版空白、空段落增减、对齐方式不算改动——比对的是内容。

        开头多一个空段后，后面所有段落的地址整体错位；按地址硬对会把没动过
        的位置全报成改动，所以按文档顺序对齐。
        """
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            def _reformat(doc: Any) -> None:
                doc.paragraphs[0].insert_paragraph_before("")
                doc.paragraphs[1].alignment = 1  # 标题行居中
                runs = doc.tables[1].rows[2].cells[3].paragraphs[0].runs
                runs[0].text = " 1.50 "
                runs[-1].text = " % "

            result = await _verify(ac, _resave(data, _reformat))
            assert result["verdict"] == "content_match", result["other_differences"]
            assert {row["status"] for row in result["slots"]} == {"match"}

    async def test_edit_outside_the_written_positions_is_altered(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """系统没回填的固定文字被改了（报告编号），同样要抓出来。"""
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            def _rename(doc: Any) -> None:
                doc.paragraphs[2].text = "No.:COA-HAF-3205-999"

            result = await _verify(ac, _resave(data, _rename))
            assert result["verdict"] == "altered"
            assert {row["status"] for row in result["slots"]} == {"match"}
            assert result["other_differences"] == [
                {
                    "where": "正文",
                    "sid": "P2",
                    "expected": "No.:COA-HAF-3205-006",
                    "actual": "No.:COA-HAF-3205-999",
                    "status": "differs",
                }
            ]
            assert result["differing"] == 1

    async def test_headers_and_footers_reorganised_on_resave_are_not_edits(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """办公软件重新保存会重排页眉页脚部件（实测 LibreOffice）：文字没动就不算改动。"""
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            result = await _verify(ac, _resave(data, _reorganise_margins()))
            assert result["verdict"] == "content_match", result["other_differences"]
            assert result["other_differences"] == []

    async def test_edited_header_text_is_altered(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            def _edit_header(doc: Any) -> None:
                doc.sections[0].header.paragraphs[0].text = "别的公司有限公司"

            result = await _verify(ac, _resave(data, _edit_header))
            assert result["verdict"] == "altered"
            assert {row["status"] for row in result["slots"]} == {"match"}
            assert result["other_differences"] == [
                {
                    "where": "页眉",
                    "sid": "",
                    "expected": "丽珠集团福州福兴医药有限公司",
                    "actual": "别的公司有限公司",
                    "status": "differs",
                }
            ]

    async def test_deleted_row_is_reported_as_missing(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            def _drop_row(doc: Any) -> None:
                table = doc.tables[1]
                table._tbl.remove(table.rows[4]._tr)  # noqa: SLF001 — python-docx 删行只有这个口子

            result = await _verify(ac, _resave(data, _drop_row))
            assert result["verdict"] == "altered"
            impurity_c = next(row for row in result["slots"] if row["label"] == "杂质C-RRT约1.86")
            assert (impurity_c["status"], impurity_c["actual"]) == ("missing_position", None)
            assert result["unresolved"] == 1
            # 被删那一行的项目名、标准也一起报出来
            assert {item["sid"] for item in result["other_differences"]} >= {
                "T1.R4.G1.p0",
                "T1.R4.G2.p0",
            }

    async def test_added_text_is_altered(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])

            def _append(doc: Any) -> None:
                doc.add_paragraph("本批免检放行。")

            result = await _verify(ac, _resave(data, _append))
            assert result["verdict"] == "altered"
            assert [item["status"] for item in result["other_differences"]] == ["added"]
            assert result["other_differences"][0]["actual"] == "本批免检放行。"

    async def test_file_the_system_never_generated_has_no_record(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """拿别的批号的文件（或自己做的文件）说是系统出的：系统没有这个批号的留档。"""
        async with _client(RENDER) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            data = await _render(ac, report["id"])

            def _other_batch(doc: Any) -> None:
                doc.tables[0].rows[0].cells[1].text = "HAF2699999A"

            result = await _verify(ac, _resave(data, _other_batch))
            assert result["verdict"] == "no_record"
            assert result["record"] is None and result["slots"] == []

            # 空白模板原文：系统从没出过这份文件
            assert (await _verify(ac, build_template(filled=False)))["verdict"] == "no_record"

            # 指定报告时只跟它的留档比；这个报告从没生成过
            other = await _report(ac, standard)
            specified = await _verify(ac, _resave(data, _saved_by_word), report_id=other["id"])
            assert specified["verdict"] == "no_record"
            assert specified["report"] == {"id": other["id"], "batch_no": other["batch_no"]}
            # 内容相同但字节不同的文件，不会误判成另一份报告的字节一致
            same_text = await _verify(ac, _resave(data, _saved_by_word))
            assert same_text["verdict"] == "content_match"
            assert same_text["record"]["report_id"] == report["id"]

    async def test_only_written_positions_are_compared_when_the_original_is_gone(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """留档原件不在存储里时退一步：按地址只比系统写入的位置，并如实说明范围。"""
        async with _client(RENDER) as (ac, _):
            report = await _report(ac, await _bound_standard(ac))
            data = await _render(ac, report["id"])
            keys = [key for key, blob in memory_storage.items() if blob == data]
            assert len(keys) == 1
            del memory_storage[keys[0]]

            result = await _verify(ac, _resave(data, _saved_by_word))
            assert result["verdict"] == "content_match" and result["scope"] == "written_only"

            changed = await _verify(ac, _resave(data, _set_result(2, "9.99%")))
            assert changed["verdict"] == "altered" and changed["scope"] == "written_only"

    async def test_only_docx_can_be_verified(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(READ) as (ac, _):
            pdf = await ac.post(
                f"{RENDERS}/verify",
                files={"file": ("coa.pdf", b"%PDF-1.4", "application/pdf")},
            )
            assert pdf.status_code == 400 and ".docx" in pdf.json()["message"]
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as archive:
                archive.writestr("hello.txt", "not a word document")
            broken = await ac.post(
                f"{RENDERS}/verify",
                files={"file": ("coa.docx", buf.getvalue(), DOCX_MIME)},
            )
            assert broken.status_code == 400 and "损坏" in broken.json()["message"]
            missing = await ac.get(f"{RENDERS}/{uuid4()}/file")
            assert missing.status_code == 404


class TestOperationLog:
    async def test_register_edit_render_void_are_logged(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER | AUDIT) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            first = await _render(ac, report["id"])
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={
                    "values": _with_water(
                        await _detail(ac, report["id"]),
                        standard["items"][0]["id"],
                        "0.63",
                        remark="复测",
                    ),
                    "packaging": "10kg/Tin",
                },
            )
            assert resp.status_code == 200, resp.text
            second = await _render(ac, report["id"])
            assert (await ac.delete(f"/api/v1/qa/coa/reports/{report['id']}")).status_code == 200

            logs = await _logs(ac, report["id"])
            by_action: dict[str, list[dict[str, Any]]] = {}
            for log in logs:
                by_action.setdefault(log["action"], []).append(log)
            assert set(by_action) == {
                "report_created",
                "report_updated",
                "report_rendered",
                "report_voided",
            }
            assert all(log["source_label"] == "COA 出具登记" for log in logs)
            assert all(log["actor_name"] for log in logs)
            created = by_action["report_created"][0]
            assert created["old_value"] is None
            assert created["new_value"]["水分"] == {"值": "1.5"}
            assert created["new_value"]["批号"] == {"值": report["batch_no"]}
            assert created["new_value"]["生产日期"] == {"值": "2026-07-30"}
            assert created["extra"]["source"] == "manual"

            updated = by_action["report_updated"][0]
            assert updated["old_value"]["水分"] == {"值": "1.5"}
            assert updated["new_value"]["水分"] == {"值": "0.63", "备注": "复测"}
            assert updated["old_value"]["包装规格"] == {"值": "6kg/Tin"}
            assert updated["new_value"]["包装规格"] == {"值": "10kg/Tin"}
            assert "杂质A-RRT约0.76" not in updated["new_value"]  # 没动的格不记
            assert updated["extra"]["changed"] == 2

            # 同一事务里几条日志时间相同，按文件摘要认哪次生成是哪次
            rendered = {log["extra"]["file_sha256"]: log for log in by_action["report_rendered"]}
            assert set(rendered) == {_sha(first), _sha(second)}
            assert rendered[_sha(first)]["new_value"]["COA 文件"]["备注"] == f"SHA-256 {_sha(first)}"
            assert "8 个" in rendered[_sha(first)]["new_value"]["写入位置"]["值"]

            voided = by_action["report_voided"][0]
            assert voided["old_value"] == {"值数量": 3} and voided["new_value"] is None

    async def test_saving_without_changes_writes_no_log(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER | AUDIT) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            resp = await ac.patch(f"/api/v1/qa/coa/reports/{report['id']}", json={"remark": None})
            assert resp.status_code == 200, resp.text
            assert [log["action"] for log in await _logs(ac, report["id"])] == ["report_created"]

    async def test_logs_are_scoped_to_their_report(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(RENDER | AUDIT) as (ac, _):
            standard = await _bound_standard(ac)
            mine = await _report(ac, standard)
            await _report(ac, standard)
            logs = await _logs(ac, mine["id"])
            assert len(logs) == 1 and logs[0]["extra"]["batch_no"] == mine["batch_no"]
