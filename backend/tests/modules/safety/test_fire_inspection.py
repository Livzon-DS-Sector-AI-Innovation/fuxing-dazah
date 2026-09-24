"""消防设施点检 PDF 归档：模型解析、PDF 渲染、Bitable 端口解析单测。

纯内存构造 Bitable records/search 原始字段，不依赖网络；PDF 断言走
pdfplumber 文本层。样例基准：04_FE-TEST-004_2026-09-15_11-25。
"""

from __future__ import annotations

import struct
import zlib
from io import BytesIO
from typing import Any

import pdfplumber
import pytest

from app.modules.safety.fire_inspection import bitable as fi_bitable
from app.modules.safety.fire_inspection import models as fi_models
from app.modules.safety.fire_inspection import pdf as fi_pdf
from app.modules.safety.fire_inspection import service as fi_service

# 2026-09-15 11:25:00（点检）与 16:22:59（创建），Asia/Shanghai，毫秒
INSPECT_AT_MS = 1789442700000
CREATED_AT_MS = 1789460579000

CONFIRM_LABEL = "本人确认已按要求完成该消防设施现场点检，所填点检结果及上传照片真实有效。"


def _raw_record(**overrides: Any) -> dict[str, Any]:
    """构造 records/search 形状的单条记录（fields 按字段名索引）。"""
    fields: dict[str, Any] = {
        "设备编号": "FE-TEST-004",
        "点检人": [{"id": "ou_3ee0", "name": "林莉鑫"}],
        "点检人.部门": "安全工程中心",
        "点检时间": INSPECT_AT_MS,
        "点检结果": "正常",
        "整改状态": "无需整改",
        "异常描述": "无异常",
        CONFIRM_LABEL: True,
        "外壳、支座、压把是否腐蚀严重": True,
        "封签、插销是否完好": True,
        "喷嘴皮管是否破损、老化": True,
        "压力表指针是否在绿色区域内": True,
        "灭火器是否在设定位置（无遮挡、易启用）": True,
        "整体照片": [{"file_token": "BW00", "name": "overall.jpeg", "size": 664706}],
        "关键部位照片": [{"file_token": "A8ZD", "name": "key.jpeg", "size": 635157}],
        "签字": [{"file_token": "PK1H", "name": "sign.png", "size": 12872}],
        "巡检记录": [],
        "创建人": {"id": "ou_3ee0", "name": "林莉鑫"},
        "创建时间": CREATED_AT_MS,
    }
    fields.update(overrides)
    return {"record_id": "rec28bKoY95n16", "fields": fields}


def test_parse_record_extracts_typed_fields() -> None:
    record = fi_models.parse_record(_raw_record())

    assert record.record_id == "rec28bKoY95n16"
    assert record.equipment_no == "FE-TEST-004"
    assert record.inspector == "林莉鑫"
    assert record.dept == "安全工程中心"
    assert record.result == "正常"
    assert record.rectify_status == "无需整改"
    assert record.abnormal_desc == "无异常"
    assert record.confirmed is True
    assert record.created_by == "林莉鑫"
    # 点检时间 2026-09-15 11:25（本地时区）
    assert record.inspect_at is not None
    assert record.inspect_at.strftime("%Y-%m-%d %H:%M") == "2026-09-15 11:25"
    assert record.created_at is not None
    assert record.created_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-15 16:22:59"
    # 五项检查，按样例顺序
    assert [name for name, _ in record.checks] == [
        "外壳、支座、压把是否腐蚀严重",
        "封签、插销是否完好",
        "喷嘴皮管是否破损、老化",
        "压力表指针是否在绿色区域内",
        "灭火器是否在设定位置（无遮挡、易启用）",
    ]
    assert all(checked is True for _, checked in record.checks)
    # 附件
    assert record.overall_photos[0].file_token == "BW00"
    assert record.key_photos[0].file_token == "A8ZD"
    assert record.signatures[0].file_token == "PK1H"
    assert record.reports == ()


def _render_text(record: fi_models.InspectionRecord, **kwargs: Any) -> tuple[int, str]:
    pdf_bytes = fi_pdf.render(record, **kwargs)
    with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
        pages = len(doc.pages)
        text = "\n".join(page.extract_text() or "" for page in doc.pages)
    return pages, text


def test_render_single_page_with_title_and_equipment() -> None:
    record = fi_models.parse_record(_raw_record())

    pages, text = _render_text(record)

    assert pages == 1
    assert "消防设施点检记录" in text
    assert "FE-TEST-004" in text


def test_render_full_archive_layout() -> None:
    record = fi_models.parse_record(_raw_record())

    pages, text = _render_text(record)

    assert pages == 1
    # 信息栅格（对照样例文本层）
    for expected in (
        "设备编号", "所属部门", "安全工程中心", "点检人", "林莉鑫",
        "点检时间", "2026-09-15 11:25", "点检结果", "正常",
        "整改状态", "无需整改", "异常描述", "无异常", "本人确认", "已确认",
    ):
        assert expected in text, expected
    # 点检项目节：独立标题 + 两列表头，5 行全 符合
    assert "点检项目" in text
    assert "点检内容" in text
    for item in fi_models.CHECK_FIELDS:
        assert item in text, item
    assert text.count("符合") == 5
    # 照片区、签字与创建信息、页脚
    for expected in ("现场照片", "整体照片", "关键部位照片", "点检人签字",
                     "创建人：林莉鑫", "创建时间：2026-09-15 16:22:59",
                     "记录生成：系统自动整理", "FE-TEST-004"):
        assert expected in text, expected


def test_render_tolerates_missing_fields_and_unchecked() -> None:
    raw = _raw_record(
        设备编号=None,
        **{
            "点检人.部门": None,
            "点检时间": None,
            "异常描述": None,
            "整体照片": [],
            "关键部位照片": [],
            "签字": [],
            "创建人": None,
            "创建时间": None,
            "外壳、支座、压把是否腐蚀严重": False,
            "封签、插销是否完好": None,
            CONFIRM_LABEL: False,
        },
    )
    record = fi_models.parse_record(raw)

    assert record.equipment_no is None
    assert record.inspect_at is None
    assert record.overall_photos == ()
    pages, text = _render_text(record)

    assert pages == 1
    assert "设备编号" in text
    assert text.count("不符合") == 2
    assert text.count("符合") - text.count("不符合") == 3
    assert "未确认" in text


def _png_bytes() -> bytes:
    """纯 Python 构造 1x1 RGB PNG（测试用最小图片）。"""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_render_embeds_images_and_stays_single_page() -> None:
    record = fi_models.parse_record(_raw_record())
    png = _png_bytes()

    pdf_bytes = fi_pdf.render(record, images={"BW00": png, "A8ZD": png, "PK1H": png})

    with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
        assert len(doc.pages) == 1
        # 整体照片 + 关键部位照片 + 签字，三张图全部嵌入
        assert sum(len(page.images) for page in doc.pages) == 3


# ── Bitable 端口：纯解析函数（票据 02）──


def test_parse_text_fields_handle_rich_text_and_select_arrays() -> None:
    """真机形状：文本字段是富文本段列表，select 可能是数组（仓库 1659061 同款问题）。"""
    raw = _raw_record(
        设备编号=[{"text": "FE-TEST-001", "type": "text"}],
        **{"点检人.部门": ["安全工程中心", "安全监督部"], "异常描述": [{"text": "皮管老化", "type": "text"}]},
    )

    record = fi_models.parse_record(raw)

    assert record.equipment_no == "FE-TEST-001"
    assert record.dept == "安全工程中心、安全监督部"
    assert record.abnormal_desc == "皮管老化"


def test_parse_search_items_extracts_items_and_paging() -> None:
    data = {
        "items": [{"record_id": "r1", "fields": {}}, {"record_id": "r2", "fields": {}}],
        "has_more": True,
        "page_token": "pt1",
    }
    items, has_more, page_token = fi_bitable.parse_search_items(data)
    assert [i["record_id"] for i in items] == ["r1", "r2"]
    assert has_more is True
    assert page_token == "pt1"


def test_parse_search_items_tolerates_empty() -> None:
    assert fi_bitable.parse_search_items({}) == ([], False, None)


def test_ensure_ok_raises_on_error_code() -> None:
    with pytest.raises(fi_bitable.BitableError) as exc_info:
        fi_bitable.ensure_ok({"code": 1254040, "msg": "not found"})
    assert "1254040" in str(exc_info.value)
    assert "not found" in str(exc_info.value)
    fi_bitable.ensure_ok({"code": 0, "msg": "success"})
    fi_bitable.ensure_ok({"code": "Ok"})
    fi_bitable.ensure_ok({})


def test_parse_upload_token() -> None:
    assert fi_bitable.parse_upload_token({"file_token": "tok1"}) == "tok1"
    with pytest.raises(fi_bitable.BitableError):
        fi_bitable.parse_upload_token({})


def test_build_append_body() -> None:
    body = fi_bitable.build_append_body("rec1", "fld1", ["tokA", "tokB"])
    assert body == {
        "attachments": {
            "rec1": {
                "fld1": [{"file_token": "tokA"}, {"file_token": "tokB"}]
            }
        }
    }


def test_parse_get_attachments_maps_token_to_extra() -> None:
    """真机形状：base v3 get_attachments 按 record -> field -> 附件列表返回。"""
    data = {
        "attachments": {
            "rec1": {
                "fldA": [
                    {"file_token": "t1", "name": "a.png", "extra_info": "e1"},
                    {"file_token": "t2", "name": "b.png", "extra_info": "e2"},
                ],
                "fldB": [{"file_token": "t3", "name": "c.pdf", "extra_info": "e3"}],
            }
        }
    }

    extra_map = fi_bitable.parse_get_attachments(data)

    assert extra_map == {"rec1": {"t1": "e1", "t2": "e2", "t3": "e3"}}
    assert fi_bitable.parse_get_attachments({}) == {}


# ── 归档编排 service（票据 03，接缝①）──


class FakeRepo:
    """内存版数据端口桩：记录表 + 附件单元格状态。"""

    def __init__(self, raw_records: list[dict[str, Any]]) -> None:
        self.raw_records = raw_records
        self.uploaded: list[tuple[str, bytes]] = []
        self.appended: list[tuple[str, list[str]]] = []
        self._seq = 0
        self.fail_upload_for: set[str] = set()

    async def list_records(self) -> list[dict[str, Any]]:
        return self.raw_records

    async def download(self, file_token: str, extra: str | None = None) -> bytes:
        return _png_bytes()

    async def attachment_extra_map(self, record_ids: list[str]) -> dict[str, dict[str, str]]:
        return {}

    async def aclose(self) -> None:
        return None

    async def upload(self, file_name: str, content: bytes) -> str:
        for rid in self.fail_upload_for:
            if rid in file_name:
                raise RuntimeError(f"upload boom: {rid}")
        self.uploaded.append((file_name, content))
        self._seq += 1
        return f"newtok{self._seq}"

    async def append(self, record_id: str, file_tokens: list[str]) -> None:
        self.appended.append((record_id, list(file_tokens)))
        for raw in self.raw_records:
            if raw.get("record_id") == record_id:
                fields = raw.setdefault("fields", {})
                cell = fields.setdefault(fi_models.FIELD_REPORTS, [])
                cell.extend({"file_token": t, "name": "", "size": 0} for t in file_tokens)


def _with_archive(seq: int, equip: str) -> dict[str, Any]:
    raw = _raw_record(**{"设备编号": equip})
    raw["record_id"] = f"rec_arch_{seq:02d}"
    raw["fields"][fi_models.FIELD_REPORTS] = [
        {"file_token": f"arch{seq}", "name": f"{seq:02d}_{equip}_2026-08-15_15-02_消防设施点检记录.pdf", "size": 1}
    ]
    return raw


def _missing_record(rid: str, equip: str) -> dict[str, Any]:
    raw = _raw_record(**{"设备编号": equip})
    raw["record_id"] = rid
    return raw


async def test_backfill_generates_only_missing_and_appends() -> None:
    repo = FakeRepo([_with_archive(1, "FE-001"), _missing_record("rec_new", "FE-002")])

    result = await fi_service.generate_and_backfill(repo=repo)

    assert result.generated == ["rec_new"]
    assert result.skipped == ["rec_arch_01"]
    assert result.failed == []
    assert len(repo.uploaded) == 1
    name, content = repo.uploaded[0]
    assert name.startswith("02_FE-002_")
    assert name.endswith("_消防设施点检记录.pdf")
    assert content[:4] == b"%PDF"
    assert repo.appended == [("rec_new", ["newtok1"])]


async def test_backfill_seq_continues_after_max_existing() -> None:
    repo = FakeRepo(
        [_with_archive(i, f"FE-00{i}") for i in (1, 2, 5)]
        + [_missing_record("rec_a", "FE-009"), _missing_record("rec_b", "FE-010")]
    )

    result = await fi_service.generate_and_backfill(repo=repo)

    assert result.generated == ["rec_a", "rec_b"]
    names = [name for name, _ in repo.uploaded]
    assert names[0].startswith("06_")
    assert names[1].startswith("07_")


async def test_backfill_record_ids_limits_scope() -> None:
    repo = FakeRepo([_missing_record("rec_a", "FE-009"), _missing_record("rec_b", "FE-010")])

    result = await fi_service.generate_and_backfill(["rec_b"], repo=repo)

    assert result.generated == ["rec_b"]
    assert result.skipped == []
    assert len(repo.uploaded) == 1
    assert repo.uploaded[0][0].startswith("01_")


async def test_backfill_single_failure_does_not_block_others() -> None:
    repo = FakeRepo([_missing_record("rec_bad", "FE-BAD"), _missing_record("rec_ok", "FE-OK")])
    repo.fail_upload_for = {"FE-BAD"}

    result = await fi_service.generate_and_backfill(repo=repo)

    assert [rid for rid, _ in result.failed] == ["rec_bad"]
    assert result.generated == ["rec_ok"]


async def test_backfill_filename_falls_back_to_created_time() -> None:
    raw = _missing_record("rec_c", "FE-011")
    raw["fields"]["点检时间"] = None
    repo = FakeRepo([raw])

    result = await fi_service.generate_and_backfill(repo=repo)

    assert result.generated == ["rec_c"]
    assert "2026-09-15_16-22" in repo.uploaded[0][0]


async def test_backfill_download_failure_fails_record_not_blank_archive() -> None:
    """照片存在但下载失败：计入失败清单待次日重试，绝不归档出缺图 PDF。"""
    repo = FakeRepo([_missing_record("rec_dl", "FE-DL")])

    async def broken_download(file_token: str, extra: str | None = None) -> bytes:
        raise RuntimeError("download boom")

    repo.download = broken_download  # type: ignore[method-assign]

    result = await fi_service.generate_and_backfill(repo=repo)

    assert [rid for rid, _ in result.failed] == ["rec_dl"]
    assert result.generated == []
    assert repo.uploaded == []


# ── 调度接入（票据 04）──


def test_backfill_gate_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_FIRE_INSPECTION_PDF_ENABLED", raising=False)
    assert fi_service.backfill_enabled() is False
    monkeypatch.setenv("SAFETY_FIRE_INSPECTION_PDF_ENABLED", "1")
    assert fi_service.backfill_enabled() is True
    monkeypatch.setenv("SAFETY_FIRE_INSPECTION_PDF_ENABLED", "false")
    assert fi_service.backfill_enabled() is False


def test_scheduled_jobs_registers_backfill() -> None:
    from app.modules.safety import scheduler as fi_scheduler

    jobs = {job["name"]: job for job in fi_scheduler.SCHEDULED_JOBS}
    job = jobs["点检PDF归档"]
    assert job["hour"] == 17
    assert job["minute"] == 0


async def test_runner_skips_when_gate_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety import scheduler as fi_scheduler

    monkeypatch.delenv("SAFETY_FIRE_INSPECTION_PDF_ENABLED", raising=False)
    calls: list[Any] = []

    async def fake_backfill(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return fi_service.BackfillResult()

    monkeypatch.setattr(fi_service, "generate_and_backfill", fake_backfill)

    await fi_scheduler._run_fire_inspection_pdf_backfill()

    assert calls == []


async def test_runner_raises_on_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety import scheduler as fi_scheduler

    monkeypatch.setenv("SAFETY_FIRE_INSPECTION_PDF_ENABLED", "1")

    async def fake_backfill(*args: Any, **kwargs: Any) -> Any:
        return fi_service.BackfillResult(generated=["r1"], failed=[("r2", "boom")])

    monkeypatch.setattr(fi_service, "generate_and_backfill", fake_backfill)

    with pytest.raises(RuntimeError, match="r2"):
        await fi_scheduler._run_fire_inspection_pdf_backfill()
