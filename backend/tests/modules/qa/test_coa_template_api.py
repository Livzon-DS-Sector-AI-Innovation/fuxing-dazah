"""COA 模板标注与回填的 API 链路：上传模板 → AI 标注提案（打桩）→ 人工确认保存
→ 预检 → 生成 docx。

沿用 test_coa_api 的 harness（权限打桩、每个 ``_client`` 块独占一个最终回滚的
会话——同一条用例里建的数据要在同一个块里用完）；模板用
_coa_template_builder 现搭；AI 调用整体打桩（``template_bind.annotate._chat_json``），
文件存储换成内存字典，不往开发环境上传目录里落测试文件。
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response

from app.modules.qa import file_service
from app.modules.qa.service.coa.template_address import TemplateDoc, flat_text
from app.modules.qa.service.coa.template_bind import annotate as template_annotate
from tests.modules.qa._coa_template_builder import build_template
from tests.modules.qa.test_coa_api import (
    ISSUE,
    MANAGE,
    READ,
    _client,
    _mk_product,
    _mk_standard,
    _uniq,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ITEMS = [
    {"name_cn": "水分", "name_en": "Water", "value_type": "number", "unit": "%", "spec_text": "≤5.0%", "spec_max": 5.0},
    {"name_cn": "杂质A-RRT约0.76", "name_en": "Impurity A (RRT 0.76)", "value_type": "number", "unit": "%", "spec_text": "≤3.0%", "spec_max": 3.0},
    {"name_cn": "杂质C-RRT约1.86", "name_en": "Impurity C (RRT 1.86)", "value_type": "number", "unit": "%", "spec_text": "≤1.0%", "spec_max": 1.0},
]
BATCH_FIELDS = [
    {"key": "mfg_date", "label_cn": "生产日期", "label_en": "Mfg. Date", "field_type": "date"},
    {"key": "exp_date", "label_cn": "有效期", "label_en": "Exp. Date", "field_type": "date"},
    {"key": "packaging", "label_cn": "包装规格", "label_en": "Packaging", "field_type": "text"},
]


@pytest.fixture
def memory_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """模板文件存进内存字典：存储、读取、清理三个入口一起换掉。"""
    store: dict[str, bytes] = {}

    def _store(filename: str | None, content_type: str | None, data: bytes) -> file_service.StoredFile:
        safe_name, extension, mime = file_service.validate_file(filename, content_type, data)
        key = f"documents/{uuid4().hex}.{extension}"
        store[key] = data
        return file_service.StoredFile(
            key=key,
            original_filename=safe_name,
            extension=extension,
            mime_type=mime,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def _read(key: str) -> tuple[bytes, str] | None:
        return (store[key], DOCX_MIME) if key in store else None

    def _cleanup(stored: Any) -> None:
        store.pop(stored if isinstance(stored, str) else stored.key, None)

    monkeypatch.setattr(file_service, "store_file", _store)
    monkeypatch.setattr(file_service, "read_file", _read)
    monkeypatch.setattr(file_service, "cleanup_stored_file", _cleanup)
    return store


@pytest.fixture
def stub_annotation(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """AI 标注打桩：返回「模型标对了」的结果，并记下发给模型的提示词。"""
    prompts: list[str] = []

    async def _fake(prompt: str) -> dict[str, Any]:
        prompts.append(prompt)
        return {
            "bindings": [
                {"field": "batch:serial_no", "slots": [{"id": "P1", "sample": "26081215"}]},
                {"field": "batch:batch_no", "slots": [{"id": "T0.R0.G1.p0", "sample": "HAF2607001A"}]},
                {"field": "batch:mfg_date", "slots": [{"id": "T0.R0.G3.p0", "sample": "2026.07.29"}]},
                {"field": "batch:packaging", "slots": [{"id": "T0.R1.G1.p0", "sample": "5kg/Tin"}]},
                {"field": "batch:exp_date", "slots": [{"id": "T0.R1.G3.p0", "sample": "2028.07.28"}]},
                {"field": "item:1", "slots": [{"id": "T1.R2.G3.p0", "sample": "0.63%"}]},
                {"field": "item:2", "slots": [{"id": "T1.R3.G3.p0", "sample": "0.23%"}]},
                {"field": "item:3", "slots": [{"id": "T1.R4.G3.p0", "sample": "0.05%"}]},
            ],
            "unmapped": [],
        }

    monkeypatch.setattr(template_annotate, "_chat_json", _fake)
    return prompts


async def _standard_matching_template(ac: AsyncClient) -> dict[str, Any]:
    """产品默认批次字段带上生产日期/有效期/包装规格，标准的三个项目对应模板的三行。

    另放一个键叫 storage_conditions、标签「储存条件」的字段：真实产品里就是这样配的，
    它按设计不回填，不该出现在可标注的字段里。
    """
    product = await _mk_product(ac)
    resp = await ac.put(
        f"/api/v1/qa/coa/products/{product['id']}/fields",
        json={
            "fields": [
                *BATCH_FIELDS,
                {"key": "storage_conditions", "label_cn": "储存条件", "label_en": "Storage", "field_type": "text"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    return await _mk_standard(ac, product["id"], items=ITEMS)


async def _upload(ac: AsyncClient, standard_id: str | UUID, **options: Any) -> Response:
    return await ac.put(
        f"/api/v1/qa/coa/standards/{standard_id}/template",
        files={"file": ("coa-template.docx", build_template(**options), DOCX_MIME)},
    )


async def _annotate(ac: AsyncClient, standard_id: str) -> dict[str, Any]:
    resp = await ac.post(f"/api/v1/qa/coa/standards/{standard_id}/template/annotate")
    assert resp.status_code == 200, resp.text
    return _check(resp)


def _binding_payload(proposal: dict[str, Any], *, static: list[str] | None = None) -> dict[str, Any]:
    """前端「确认标注并保存」时提交的内容：地址与格式规则（原位替换的带上原文）。"""
    return {
        "fields": [
            {
                "field": row["field"],
                "required": row["required"],
                "slots": [
                    {"sid": s["sid"], "fmt": s["fmt"], **({"sample": s["sample"]} if s["mode"] == "inplace" else {})}
                    for s in row["slots"]
                ],
            }
            for row in proposal["fields"]
            if row["slots"]
        ],
        "static_slots": sorted({*proposal.get("static_slots", []), *(r["sid"] for r in proposal["residue"])})
        if static is None
        else static,
        "verdicts": proposal["verdicts"],
    }


async def _save_binding(ac: AsyncClient, standard_id: str, proposal: dict[str, Any], **options: Any) -> Response:
    return await ac.put(
        f"/api/v1/qa/coa/standards/{standard_id}/template/binding",
        json=_binding_payload(proposal, **options),
    )


async def _bound_standard(ac: AsyncClient) -> dict[str, Any]:
    """建标准 → 传模板 → 标注 → 确认保存。返回标准详情。"""
    standard = await _standard_matching_template(ac)
    assert (await _upload(ac, standard["id"])).status_code == 200
    saved = await _save_binding(ac, standard["id"], await _annotate(ac, standard["id"]))
    assert saved.status_code == 200, saved.text
    return _check(await ac.get(f"/api/v1/qa/coa/standards/{standard['id']}"))


async def _get_template(ac: AsyncClient, standard_id: str) -> dict[str, Any]:
    return _check(await ac.get(f"/api/v1/qa/coa/standards/{standard_id}/template"))


async def _report(
    ac: AsyncClient,
    standard: dict[str, Any],
    *,
    include: tuple[str, ...] = ("水分", "杂质A-RRT约0.76", "杂质C-RRT约1.86"),
    **overrides: Any,
) -> dict[str, Any]:
    """登记一份报告：三个项目各给值，可按名去掉；批次头字段默认齐全。"""
    by_name = {i["name_cn"]: i for i in standard["items"]}
    results = {"水分": 1.5, "杂质A-RRT约0.76": 0.2, "杂质C-RRT约1.86": 0.06}
    payload: dict[str, Any] = {
        "product_id": standard["product_id"],
        "standard_id": standard["id"],
        "batch_no": _uniq("HAF2607"),
        "serial_no": _uniq("26"),
        "mfg_date": "2026-07-30",
        "exp_date": "2028-07-29",
        "packaging": "6kg/Tin",
        "values": [
            {"item_id": by_name[name]["id"], "value_num": value, "value_text": str(value)}
            for name, value in results.items()
            if name in include
        ],
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/coa/reports", json=payload)
    assert resp.status_code == 201, resp.text
    return _check(resp)


def _check(response: Response) -> dict[str, Any]:
    data: dict[str, Any] = response.json()["data"]
    return data


class TestTemplateUpload:
    async def test_upload_requires_manage(self, memory_storage: dict[str, bytes]) -> None:
        async with _client(READ) as (ac, _):
            assert (await _upload(ac, uuid4())).status_code == 403
            assert memory_storage == {}

    async def test_only_docx_is_accepted(self, memory_storage: dict[str, bytes]) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _standard_matching_template(ac)
            url = f"/api/v1/qa/coa/standards/{standard['id']}/template"
            legacy = await ac.put(url, files={"file": ("old.doc", b"\xd0\xcf\x11\xe0", "application/msword")})
            assert legacy.status_code == 400 and ".docx" in legacy.json()["message"]
            # 是 zip 但不是 docx（加密文档另存后常见）：魔数校验放行，解析时才拦下
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as archive:
                archive.writestr("hello.txt", "not a word document")
            broken = await ac.put(url, files={"file": ("encrypted.docx", buf.getvalue(), DOCX_MIME)})
            assert broken.status_code == 400 and "损坏" in broken.json()["message"]
            assert memory_storage == {}  # 校验没过就不落文件

    async def test_uploaded_template_is_addressable_but_unbound(self, memory_storage: dict[str, bytes]) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _standard_matching_template(ac)
            assert standard["template_status"] == "none"
            data = _check(await _upload(ac, standard["id"]))
            assert data["template"]["status"] == "unbound"
            assert data["template"]["filename"] == "coa-template.docx"
            assert data["binding"] is None
            tables = [b for section in data["grid"] for b in section["blocks"] if b["type"] == "table"]
            assert [t["sid"] for t in tables] == ["T0", "T1"]
            assert data["result_columns"] == {"T1": 3}  # 结果列：表头写「结果」的那一列
            # 品名、储存条件不回填，不在字段清单里
            assert [f["field"] for f in data["fields"] if f["kind"] == "batch"] == [
                "batch:batch_no", "batch:serial_no", "batch:mfg_date", "batch:exp_date", "batch:packaging",
            ]
            listed = (await ac.get("/api/v1/qa/coa/standards", params={"product_id": standard["product_id"]})).json()["data"]
            assert next(s for s in listed if s["id"] == standard["id"])["template_status"] == "unbound"


class TestAnnotate:
    async def test_annotate_is_a_proposal_and_is_not_saved(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _standard_matching_template(ac)
            await _upload(ac, standard["id"])
            proposal = await _annotate(ac, standard["id"])
            assert proposal["needs_review"] == 0 and proposal["problems"] == []
            assert [r["sid"] for r in proposal["residue"]] == ["T1.R1.G3.p0"]  # 写死的「符合规定Conform」
            water = next(f for f in proposal["fields"] if f["label_cn"] == "水分")
            assert water["slots"][0]["fmt"] == {"kind": "number", "decimals": 2, "suffix": "%"}
            # 发给模型的是带地址的模板 + 字段清单（项目按序号）
            assert "[T0.R0.G1.p0]HAF2607001A" in stub_annotation[0]
            assert "- item:1：检测项目「水分」，英文 Water，标准 ≤5.0%，单位 %" in stub_annotation[0]
            # 提案不落库：人工确认之前状态不变
            assert proposal["template"]["status"] == "unbound"
            current = await _get_template(ac, standard["id"])
            assert current["template"]["status"] == "unbound" and current["binding"] is None

    async def test_annotate_needs_manage_and_a_template(self, stub_annotation: list[str]) -> None:
        async with _client(READ) as (ac, _):
            resp = await ac.post(f"/api/v1/qa/coa/standards/{uuid4()}/template/annotate")
            assert resp.status_code == 403
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            standard = await _mk_standard(ac, product["id"])
            resp = await ac.post(f"/api/v1/qa/coa/standards/{standard['id']}/template/annotate")
            assert resp.status_code == 400 and "尚未上传" in resp.json()["message"]

    async def test_model_errors_are_caught_before_a_human_looks(
        self, memory_storage: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """实测里出现过的两个模型错误：标题行流水号归给批号、值标到标准列。"""
        async with _client(MANAGE) as (ac, _):
            standard = await _standard_matching_template(ac)
            await _upload(ac, standard["id"])

            async def _wrong(prompt: str) -> dict[str, Any]:
                return {
                    "bindings": [
                        {"field": "batch:batch_no", "slots": [
                            {"id": "T0.R0.G1.p0", "sample": "HAF2607001A"}, {"id": "P1", "sample": "26081215"},
                        ]},
                        {"field": "item:1", "slots": [{"id": "T1.R2.G2.p0", "sample": ""}]},
                    ],
                    "unmapped": ["batch:serial_no"],
                }

            monkeypatch.setattr(template_annotate, "_chat_json", _wrong)
            proposal = await _annotate(ac, standard["id"])
            batch_no = next(f for f in proposal["fields"] if f["field"] == "batch:batch_no")
            assert batch_no["flags"] == ["inconsistent_values", "body_paragraph"]
            assert next(f for f in proposal["fields"] if f["field"] == "batch:serial_no")["flags"] == [
                "batch_unbound"
            ]
            water = next(f for f in proposal["fields"] if f["label_cn"] == "水分")
            assert water["slots"] == []
            assert any("不是空格" in problem for problem in proposal["problems"])


class TestSaveBinding:
    async def test_confirmed_binding_marks_standard_bound(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _bound_standard(ac)
            assert standard["template_status"] == "bound"
            current = await _get_template(ac, standard["id"])
            assert current["template"]["status"] == "bound" and current["template"]["bound_at"]
            serial = next(f for f in current["binding"]["fields"] if f["field"] == "batch:serial_no")
            # 值夹在固定文字中间：保存的是要被替换的那段原文
            assert (serial["slots"][0]["mode"], serial["slots"][0]["sample"]) == ("inplace", "26081215")
            assert current["binding"]["static_slots"] == ["T1.R1.G3.p0"]

    async def test_unhandled_result_cells_block_saving(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _standard_matching_template(ac)
            await _upload(ac, standard["id"])
            proposal = await _annotate(ac, standard["id"])
            resp = await _save_binding(ac, standard["id"], proposal, static=[])
            assert resp.status_code == 400
            assert "未处理的非空格子" in resp.json()["message"]
            assert [r["sid"] for r in resp.json()["detail"]] == ["T1.R1.G3.p0"]
            detail = (await ac.get(f"/api/v1/qa/coa/standards/{standard['id']}")).json()["data"]
            assert detail["template_status"] == "unbound"  # 没保存成功

    async def test_invalid_bindings_are_rejected(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _standard_matching_template(ac)
            await _upload(ac, standard["id"])
            good = _binding_payload(await _annotate(ac, standard["id"]))
            url = f"/api/v1/qa/coa/standards/{standard['id']}/template/binding"
            percent = {"kind": "number", "decimals": 2, "suffix": "%"}
            cases = {
                "字段不在标准里": {**good, "fields": good["fields"] + [
                    {"field": f"item:{uuid4()}", "slots": [{"sid": "P2", "fmt": percent}]},
                ]},
                "地址不存在": {**good, "fields": [
                    {"field": "batch:batch_no", "slots": [{"sid": "T9.R9.G9.p0", "fmt": percent}]},
                ]},
                "同一格绑给两个字段": {**good, "fields": [
                    {"field": "batch:batch_no", "slots": [{"sid": "T0.R0.G1.p0", "fmt": percent}]},
                    {"field": "batch:serial_no", "slots": [{"sid": "T0.R0.G1.p0", "fmt": percent}]},
                ]},
                "同一格的多个段落": {**good, "fields": [
                    {"field": "batch:batch_no", "slots": [
                        {"sid": "T0.R0.G0.p0", "fmt": percent}, {"sid": "T0.R0.G0.p1", "fmt": percent},
                    ]},
                ]},
                "给的原文不在格子里": {**good, "fields": [
                    {"field": "batch:batch_no", "slots": [
                        {"sid": "T0.R0.G1.p0", "sample": "别的批号", "fmt": percent},
                    ]},
                ]},
            }
            for label, payload in cases.items():
                resp = await ac.put(url, json=payload)
                assert resp.status_code == 400, (label, resp.text)
            # 非法日期格式在入参校验层就拦下（422），到不了服务层
            resp = await ac.put(url, json={**good, "fields": [
                {"field": "batch:mfg_date", "slots": [
                    {"sid": "T0.R0.G3.p0", "fmt": {"kind": "date", "pattern": "%Y年%Q"}},
                ]},
            ]})
            assert resp.status_code == 422 and "日期格式只支持年月日" in resp.json()["detail"]

    async def test_deleting_the_standard_removes_the_template_file(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _bound_standard(ac)
            assert len(memory_storage) == 1
            resp = await ac.delete(f"/api/v1/qa/coa/standards/{standard['id']}")
            assert resp.status_code == 200, resp.text
            assert memory_storage == {}  # 标准是软删行，模板文件不能留成孤儿

    async def test_replacing_the_template_invalidates_the_binding(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE) as (ac, _):
            standard = await _bound_standard(ac)
            assert len(memory_storage) == 1
            data = _check(await _upload(ac, standard["id"]))
            assert data["template"]["status"] == "unbound" and data["binding"] is None
            assert len(memory_storage) == 1  # 旧模板文件被清掉


class TestRender:
    async def test_render_requires_issue_permission(self, stub_annotation: list[str]) -> None:
        async with _client(READ) as (ac, _):
            resp = await ac.post(f"/api/v1/qa/coa/reports/{uuid4()}/render", params={"dry_run": "true"})
            assert resp.status_code == 403

    async def test_render_needs_an_uploaded_and_confirmed_template(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _standard_matching_template(ac)
            report = await _report(ac, standard)
            render = f"/api/v1/qa/coa/reports/{report['id']}/render"
            resp = await ac.post(render, params={"dry_run": "true"})
            assert resp.status_code == 400 and "尚未上传" in resp.json()["message"]

            await _upload(ac, standard["id"])  # 传了模板但还没确认标注
            resp = await ac.post(render, params={"dry_run": "true"})
            assert resp.status_code == 409 and "确认标注" in resp.json()["message"]

    async def test_dry_run_lists_missing_values_and_render_is_blocked(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(
                ac, standard, include=("水分",), mfg_date=None, exp_date=None, packaging=None
            )
            check = _check(await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render", params={"dry_run": "true"}))
            assert check["ok"] is False
            assert {(b["field"], b["label"]) for b in check["blocking"]} == {
                ("batch:mfg_date", "生产日期"),
                ("batch:packaging", "包装规格"),
                ("batch:exp_date", "有效期"),
                (f"item:{standard['items'][1]['id']}", "杂质A-RRT约0.76"),
                (f"item:{standard['items'][2]['id']}", "杂质C-RRT约1.86"),
            }
            assert check["filename"] == f"{report['batch_no']}_{standard['code']}_COA.docx"
            blocked = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
            assert blocked.status_code == 422 and "没有登记值" in blocked.json()["message"]

    async def test_render_downloads_the_filled_docx(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            preflight = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render", params={"dry_run": "true"})
            assert _check(preflight)["ok"] is True

            resp = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
            assert resp.status_code == 200, resp.text[:200]
            assert resp.headers["content-type"].startswith(DOCX_MIME)
            assert f"{report['batch_no']}_{standard['code']}_COA.docx" in resp.headers["content-disposition"]
            out = TemplateDoc(resp.content).by_id
            assert out["P1"].text == f"CERTIFICATE OF ANALYSIS   {report['serial_no']}"
            assert flat_text(out["T0.R0.G1.p0"].element) == report["batch_no"]
            assert flat_text(out["T0.R0.G3.p0"].element) == "2026.07.30"  # 日期按模板写法
            assert flat_text(out["T0.R1.G1.p0"].element) == "6kg/Tin"
            assert flat_text(out["T1.R2.G3.p0"].element) == "1.50%"  # 模板位数 + 四舍五入
            assert flat_text(out["T1.R3.G3.p0"].element).strip() == "0.20%"  # 值两侧的排版空白保留
            # 没标注到的固定文字原样保留
            assert out["T1.R1.G3.p0"].text == "符合规定Conform"
            assert out["P2"].text == "No.:COA-HAF-3205-006"

    async def test_field_marked_optional_is_blanked_when_empty(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """人工核对时去掉「必填」：没值不拦，但模板里的旧值要清掉。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            impurity_c = f"item:{standard['items'][2]['id']}"
            current = await _get_template(ac, standard["id"])
            payload = _binding_payload(current["binding"])
            next(f for f in payload["fields"] if f["field"] == impurity_c)["required"] = False
            assert (await ac.put(f"/api/v1/qa/coa/standards/{standard['id']}/template/binding", json=payload)).status_code == 200

            report = await _report(ac, standard, include=("水分", "杂质A-RRT约0.76"))
            resp = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
            assert resp.status_code == 200, resp.text[:200]
            assert flat_text(TemplateDoc(resp.content).by_id["T1.R4.G3.p0"].element) == ""

    async def test_old_batch_value_left_in_output_blocks_the_download(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """模板里有一处批号没标注到：回填后旧批号还在，必须拦下来。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _standard_matching_template(ac)
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{standard['id']}/template",
                files={"file": ("leaky.docx", build_template(leak=True), DOCX_MIME)},
            )
            assert resp.status_code == 200, resp.text
            assert (await _save_binding(ac, standard["id"], await _annotate(ac, standard["id"]))).status_code == 200
            report = await _report(ac, standard)
            check = _check(await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render", params={"dry_run": "true"}))
            assert check["ok"] is False
            assert check["blocking"] == [{"kind": "stale", "sample": "HAF2607001A", "found_in": ["P4"]}]
            blocked = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
            assert blocked.status_code == 422 and "旧批号" in blocked.json()["message"]

    async def test_standard_items_replaced_after_binding_is_rejected(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            # 标准项目被整体替换（旧项目软删）：标注引用的字段不在了
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{standard['id']}/items",
                json={"items": [{"name_cn": "水分", "value_type": "number", "unit": "%", "spec_text": "≤5.0%"}]},
            )
            assert resp.status_code == 200, resp.text
            blocked = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render", params={"dry_run": "true"})
            assert blocked.status_code == 409 and "重新核对模板标注" in blocked.json()["message"]

    async def test_removed_item_is_named_in_the_drift(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """移除的项目在偏差里叫得出名字；它原来占的结果格成了待处理格子，要人处理后再保存。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            impurity_a = standard["items"][1]
            items = _items_payload(standard["items"])
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{standard['id']}/items",
                json={"items": [items[0], items[2]]},
            )
            assert resp.status_code == 200, resp.text
            state = await _get_template(ac, standard["id"])
            assert state["drift"]["removed"] == [
                {"field": f"item:{impurity_a['id']}", "label_cn": "杂质A-RRT约0.76"}
            ]
            assert [r["sid"] for r in state["binding"]["residue"]] == ["T1.R3.G3.p0"]


def _items_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """标准详情里的项目 → 项目全量替换的入参（带 id=保留更新）。"""
    keys = (
        "id", "group_name", "name_cn", "name_en", "value_type", "unit",
        "spec_text", "spec_min", "spec_max", "sort_order", "default_value", "remark",
    )
    return [{key: item[key] for key in keys} for item in items]


class TestBindingDrift:
    """标注确认之后字段配置变了：状态变「需重新核对」、生成被拦；重新确认保存后恢复。"""

    @staticmethod
    async def _statuses(ac: AsyncClient, standard: dict[str, Any]) -> dict[str, str]:
        """这份标准在三处的模板状态：标准详情 / 标准列表 / 出具页矩阵。"""
        product_id = standard["product_id"]
        detail = _check(await ac.get(f"/api/v1/qa/coa/standards/{standard['id']}"))
        listed = _check(
            await ac.get("/api/v1/qa/coa/standards", params={"product_id": product_id})
        )
        matrix = _check(
            await ac.get("/api/v1/qa/coa/reports/matrix", params={"product_id": product_id})
        )
        return {
            "detail": detail["template_status"],
            "list": next(s for s in listed if s["id"] == standard["id"])["template_status"],
            "matrix": next(
                s for s in matrix["standards"] if s["id"] == standard["id"]
            )["template_status"],
        }

    @classmethod
    async def _assert_status(cls, ac: AsyncClient, standard: dict[str, Any], expected: str) -> None:
        statuses = await cls._statuses(ac, standard)
        assert set(statuses.values()) == {expected}, statuses

    @staticmethod
    async def _dry_run(ac: AsyncClient, report: dict[str, Any]) -> Response:
        return await ac.post(
            f"/api/v1/qa/coa/reports/{report['id']}/render", params={"dry_run": "true"}
        )

    async def test_batch_field_added_after_confirmation_needs_review(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            await self._assert_status(ac, standard, "bound")

            # 产品默认字段里新增「批量」：这份标准用的是产品默认，它的标注没跟着变
            resp = await ac.put(
                f"/api/v1/qa/coa/products/{standard['product_id']}/fields",
                json={
                    "fields": [
                        *BATCH_FIELDS,
                        {"key": "batch_size", "label_cn": "批量", "label_en": "Batch Size", "field_type": "text"},
                    ]
                },
            )
            assert resp.status_code == 200, resp.text
            report = await _report(ac, standard, batch_data={"batch_size": "41kg"})

            await self._assert_status(ac, standard, "stale")
            state = await _get_template(ac, standard["id"])
            assert state["template"]["status"] == "stale"
            added = [{"field": "batch:batch_size", "label_cn": "批量", "kind": "batch"}]
            assert state["drift"] == {
                "removed": [],
                "added": added,
                "changed": [],
                "lines": ["新增的「批量」还没有标注位置"],
            }

            # 新字段有登记值，不能悄悄不出现在 COA 上：生成被拦
            blocked = await self._dry_run(ac, report)
            assert blocked.status_code == 409 and "重新核对模板标注" in blocked.json()["message"]
            # 报错里直接说是哪一处（生成弹窗原样显示后端的文字）
            assert blocked.json()["detail"] == ["新增的「批量」还没有标注位置"]

            # 回到抽屉重新确认保存（新字段不写入模板，是这次核对认可的）：状态恢复
            assert (await _save_binding(ac, standard["id"], state["binding"])).status_code == 200
            await self._assert_status(ac, standard, "bound")
            assert (await _get_template(ac, standard["id"]))["drift"] is None
            check = _check(await self._dry_run(ac, report))
            assert check["ok"] is True
            # 放行，但出报告的人要知道这一项不会出现在 COA 上
            assert {"kind": "unbound_batch", "count": 1, "labels": ["批量"]} in check["warnings"]

    async def test_item_unit_changed_after_confirmation_needs_review(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """项目改了单位：已确认的格式规则（后缀 %）不能原样拿去出报告。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            water = standard["items"][0]
            water_field = f"item:{water['id']}"

            items = _items_payload(standard["items"])
            items[0]["unit"] = "ppm"
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{standard['id']}/items", json={"items": items}
            )
            assert resp.status_code == 200, resp.text

            await self._assert_status(ac, standard, "stale")
            state = await _get_template(ac, standard["id"])
            assert state["drift"] == {
                "removed": [],
                "added": [],
                "changed": [{"field": water_field, "label_cn": "水分", "changes": ["单位：% → ppm"]}],
                "lines": ["「水分」的单位：% → ppm，格式要重新确认"],
            }
            # 核对清单里这一条带标记，格式规则还是确认时的样子，改不改由人决定
            row = next(f for f in state["binding"]["fields"] if f["field"] == water_field)
            assert row["flags"] == ["config_changed"]
            assert row["slots"][0]["fmt"]["suffix"] == "%"
            assert (await self._dry_run(ac, report)).status_code == 409

            payload = _binding_payload(state["binding"])
            slot = next(f for f in payload["fields"] if f["field"] == water_field)["slots"][0]
            slot["fmt"]["suffix"] = "ppm"
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{standard['id']}/template/binding", json=payload
            )
            assert resp.status_code == 200, resp.text
            await self._assert_status(ac, standard, "bound")
            resp = await ac.post(f"/api/v1/qa/coa/reports/{report['id']}/render")
            assert resp.status_code == 200, resp.text[:200]
            assert flat_text(TemplateDoc(resp.content).by_id["T1.R2.G3.p0"].element) == "1.50ppm"

    async def test_batch_field_type_changed_after_confirmation_needs_review(
        self, memory_storage: dict[str, bytes], stub_annotation: list[str]
    ) -> None:
        """批次字段从文字改成日期：日期怎么写得重新确认，不能原样把 ISO 日期写上去。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            standard = await _bound_standard(ac)
            report = await _report(ac, standard)
            fields = [dict(f) for f in BATCH_FIELDS]
            fields[2]["field_type"] = "date"  # 包装规格
            resp = await ac.put(
                f"/api/v1/qa/coa/products/{standard['product_id']}/fields",
                json={"fields": fields},
            )
            assert resp.status_code == 200, resp.text
            await self._assert_status(ac, standard, "stale")
            state = await _get_template(ac, standard["id"])
            assert state["drift"] == {
                "removed": [],
                "added": [],
                "changed": [
                    {"field": "batch:packaging", "label_cn": "包装规格", "changes": ["类型：文字 → 日期"]}
                ],
                "lines": ["「包装规格」的类型：文字 → 日期，格式要重新确认"],
            }
            # 抽屉里这一条带标记，格式规则还是确认时的「文字」。字段成了日期型、位置上却是
            # 「5kg/Tin」，原有的校验标记（位置上不是日期）也一并带出来
            row = next(f for f in state["binding"]["fields"] if f["field"] == "batch:packaging")
            assert "config_changed" in row["flags"] and "sample_not_date" in row["flags"]
            assert row["slots"][0]["fmt"]["kind"] == "text"
            assert (await self._dry_run(ac, report)).status_code == 409
