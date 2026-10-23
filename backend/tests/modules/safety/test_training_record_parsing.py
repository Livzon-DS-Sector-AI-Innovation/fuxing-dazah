"""链3 签到/成绩单解析：vision 插件 + 分级回填 + 编排测试。

接缝（双接缝）：① opener 替身（training 客户端注入：list_all_records/
list_fields/update_record/download_bitable_attachment 四方法 fake）
② ai_service 假服务（chat_vision_parsed）。图片字节用 Pillow 现生成
（encode_image_for_vision 会真校验解码）。规格 §6/§9。
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from app.modules.safety.ai_training_record_parsing import (
    DOC_UNKNOWN,
    TrainingRecordParseInput,
    TrainingRecordParsingError,
    TrainingRecordParsingPlugin,
)
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior import record_parsing

_RAW_SIGNIN = {
    "doc_type": "签到表", "attendance_count": 18,
    "names": ["张三", "李四"], "passed_count": None, "scores": [],
    "confidence": "high", "unrecognized": [], "notes": "照片清晰",
}
_RAW_SCORE_MEDIUM = {
    "doc_type": "成绩单", "attendance_count": None,
    "names": ["张三"], "passed_count": 16,
    "scores": [{"name": "张三", "score": "92"}],
    "confidence": "medium", "unrecognized": ["王五"], "notes": "手写部分模糊",
}
_RAW_UNKNOWN = {
    "doc_type": "无法识别", "attendance_count": None, "names": [],
    "passed_count": None, "scores": [], "confidence": "low",
    "unrecognized": [], "notes": "图片与培训留痕无关",
}


class FakeVisionService:
    def __init__(self, raw: dict | Exception = _RAW_SIGNIN) -> None:
        self.raw = raw
        self.calls: list[dict] = []

    async def chat_vision_parsed(
        self, *, text_prompt, image_urls, expected_keys, temperature=None
    ):
        self.calls.append({
            "text_prompt": text_prompt, "image_urls": image_urls,
            "expected_keys": expected_keys, "temperature": temperature,
        })
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


class FakeTrainingClient:
    def __init__(self, records: list[dict], attachment_bytes: bytes) -> None:
        self.records = records
        self.attachment_bytes = attachment_bytes
        self.updated: list[tuple[str, dict]] = []
        self.downloads: list[dict] = []
        self.fail_download = False

    async def list_all_records(self, **kwargs) -> list[dict]:
        return self.records

    async def list_fields(self, table_id=None) -> list[dict]:
        return [{"field_name": "签到表", "field_id": "fldSign"}]

    async def update_record(self, record_id: str, fields: dict) -> None:
        self.updated.append((record_id, fields))

    async def download_bitable_attachment(
        self, *, file_token, record_id, field_id
    ) -> bytes | None:
        if self.fail_download:
            return None
        self.downloads.append({
            "file_token": file_token, "record_id": record_id,
            "field_id": field_id,
        })
        return self.attachment_bytes


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


def _training_row(
    record_id: str = "recT1",
    *,
    attachments: list[dict] | None = None,
    remark: str | None = None,
) -> dict:
    fields: dict[str, Any] = {
        "培训名称": "受限空间作业专项培训",
        "应到人数": "20",
        "考核方式": "考试",
    }
    if attachments is not None:
        fields["签到表"] = attachments
    if remark is not None:
        fields["备注"] = remark
    return {"record_id": record_id, "fields": fields}


def _sign_attachment(name: str = "签到表照片.png") -> dict:
    return {"file_token": "att-token-1", "name": name}


def _opener(client: FakeTrainingClient):
    def open_client(domain: str, kind: str):
        if (domain, kind) != ("training_behavior", "training"):
            raise BitableConfigError(f"未配置: {domain}/{kind}")
        return client

    return open_client


# ── 插件 ────────────────────────────────────────────────────────


class TestPlugin:
    async def test_generate_parses_signin(self) -> None:
        service = FakeVisionService()
        output = await TrainingRecordParsingPlugin(service).generate(
            TrainingRecordParseInput(
                training_name="受限空间作业专项培训",
                expected_count="20", assessment="考试",
                image_data_uri="data:image/jpeg;base64,xxx",
            )
        )
        assert output.doc_type == "签到表"
        assert output.attendance_count == 18
        assert output.passed_count is None
        call = service.calls[0]
        assert call["temperature"] == 0.1
        assert call["expected_keys"] == [
            "doc_type", "attendance_count", "names", "passed_count",
            "scores", "confidence", "unrecognized", "notes",
        ]
        assert call["image_urls"] == ["data:image/jpeg;base64,xxx"]
        prompt = call["text_prompt"]
        assert "培训留痕单据解析员" in prompt
        assert "培训名称：受限空间作业专项培训" in prompt
        assert "应到人数：20" in prompt and "考核方式：考试" in prompt

    async def test_count_coercions(self) -> None:
        raw = dict(_RAW_SIGNIN, attendance_count="17", passed_count="15")
        output = TrainingRecordParsingPlugin._parse_output(raw)
        assert output.attendance_count == 17
        assert output.passed_count == 15
        bad = TrainingRecordParsingPlugin._parse_output(
            dict(_RAW_SIGNIN, attendance_count="十人")
        )
        assert bad.attendance_count is None

    async def test_unknown_doc_type_falls_back(self) -> None:
        output = TrainingRecordParsingPlugin._parse_output(
            dict(_RAW_SIGNIN, doc_type="菜单")
        )
        assert output.doc_type == DOC_UNKNOWN

    async def test_ai_failure_wraps(self) -> None:
        with pytest.raises(TrainingRecordParsingError):
            await TrainingRecordParsingPlugin(
                FakeVisionService(RuntimeError("boom"))
            ).generate(TrainingRecordParseInput(image_data_uri="data:"))


# ── 分级回填口径（§6.3 纯函数） ────────────────────────────────


class TestWriteback:
    def _output(self, raw: dict):
        return TrainingRecordParsingPlugin._parse_output(raw)

    def test_high_signin_fills_numbers(self) -> None:
        output = self._output(_RAW_SIGNIN)
        fields = record_parsing.build_writeback_fields(
            output, remark="旧备注", today="2026-10-23"
        )
        assert fields["实到人数"] == "18"
        assert "考核合格人数" not in fields  # passed None 不回填
        assert fields["备注"] == (
            "旧备注\nAI解析(confidence=high,签到表,2026-10-23)：实到 18 人；照片清晰"
        )

    def test_high_score_fills_passed_only(self) -> None:
        raw = dict(_RAW_SCORE_MEDIUM, confidence="high")
        fields = record_parsing.build_writeback_fields(
            self._output(raw), remark=None, today="2026-10-23"
        )
        assert "实到人数" not in fields  # 成绩单无出勤
        assert fields["考核合格人数"] == "16"

    def test_medium_keeps_numbers_out(self) -> None:
        fields = record_parsing.build_writeback_fields(
            self._output(_RAW_SCORE_MEDIUM), remark=None, today="2026-10-23"
        )
        assert "实到人数" not in fields
        assert "考核合格人数" not in fields
        assert fields["备注"].startswith("AI解析(confidence=medium,成绩单,2026-10-23)：")
        assert "辨认不清 1 名：王五" in fields["备注"]

    def test_unknown_doc_only_remark(self) -> None:
        fields = record_parsing.build_writeback_fields(
            self._output(_RAW_UNKNOWN), remark=None, today="2026-10-23"
        )
        assert list(fields.keys()) == ["备注"]
        assert fields["备注"].startswith("AI解析(confidence=low,无法识别,2026-10-23)")


# ── 解析编排（附件下载链 fake） ────────────────────────────────


class TestParseRecord:
    async def test_full_chain_downloads_and_writes_back(self) -> None:
        client = FakeTrainingClient(
            [_training_row(attachments=[_sign_attachment()], remark="旧备注")],
            _png_bytes(),
        )
        service = FakeVisionService()
        result = await record_parsing.parse_training_record(
            record_id="recT1", opener=_opener(client), ai_service=service,
        )
        # 下载形态：token+record+field_id 三元组（bitablePerm extra 链）
        assert client.downloads == [{
            "file_token": "att-token-1", "record_id": "recT1",
            "field_id": "fldSign",
        }]
        # 送视觉模型的是真 data URI（Pillow 校验重编码过）
        assert service.calls[0]["image_urls"][0].startswith("data:image/")
        record_id, fields = client.updated[0]
        assert record_id == "recT1"
        assert fields["实到人数"] == "18"
        assert fields["备注"].startswith("旧备注\nAI解析(confidence=high")
        assert "writeback_keys" in result and result["parse"]["doc_type"] == "签到表"

    async def test_no_attachment_raises(self) -> None:
        client = FakeTrainingClient([_training_row(attachments=[])], _png_bytes())
        with pytest.raises(record_parsing.RecordParseStateError, match="附件列为空"):
            await record_parsing.parse_training_record(
                record_id="recT1", opener=_opener(client),
                ai_service=FakeVisionService(),
            )

    async def test_non_image_attachment_raises(self) -> None:
        client = FakeTrainingClient(
            [_training_row(attachments=[_sign_attachment("签到表.pdf")])],
            _png_bytes(),
        )
        with pytest.raises(record_parsing.RecordParseStateError, match="非图片"):
            await record_parsing.parse_training_record(
                record_id="recT1", opener=_opener(client),
                ai_service=FakeVisionService(),
            )

    async def test_download_failure_raises(self) -> None:
        client = FakeTrainingClient(
            [_training_row(attachments=[_sign_attachment()])], _png_bytes()
        )
        client.fail_download = True
        with pytest.raises(record_parsing.RecordParseStateError, match="下载失败"):
            await record_parsing.parse_training_record(
                record_id="recT1", opener=_opener(client),
                ai_service=FakeVisionService(),
            )

    async def test_row_not_found(self) -> None:
        client = FakeTrainingClient([_training_row("recOther")], _png_bytes())
        with pytest.raises(record_parsing.RecordParseStateError, match="不存在"):
            await record_parsing.parse_training_record(
                record_id="recT1", opener=_opener(client),
                ai_service=FakeVisionService(),
            )

    async def test_domain_not_connected(self) -> None:
        def opener(domain: str, kind: str):
            raise BitableConfigError("未接入")

        with pytest.raises(record_parsing.RecordParseStateError, match="未接入"):
            await record_parsing.parse_training_record(
                record_id="recT1", opener=opener, ai_service=FakeVisionService(),
            )

    async def test_vision_failure_no_writes(self) -> None:
        client = FakeTrainingClient(
            [_training_row(attachments=[_sign_attachment()])], _png_bytes()
        )
        with pytest.raises(TrainingRecordParsingError):
            await record_parsing.parse_training_record(
                record_id="recT1", opener=_opener(client),
                ai_service=FakeVisionService(RuntimeError("boom")),
            )
        assert client.updated == []

    async def test_medium_result_keeps_number_columns(self) -> None:
        client = FakeTrainingClient(
            [_training_row(
                attachments=[_sign_attachment()],
                remark=None,
            )],
            _png_bytes(),
        )
        await record_parsing.parse_training_record(
            record_id="recT1", opener=_opener(client),
            ai_service=FakeVisionService(_RAW_SCORE_MEDIUM),
        )
        _, fields = client.updated[0]
        assert "实到人数" not in fields and "考核合格人数" not in fields
        assert fields["备注"].startswith("AI解析(confidence=medium")
