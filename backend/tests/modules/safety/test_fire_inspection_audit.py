"""消防点检 AI 审核：编号比对/模型输出解析/判定合成/轮询编排单测。

纯内存桩（FakeRepo + 假 vision_chat），不依赖网络与真实模型。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.fire_inspection import audit as fi_audit
from app.modules.safety.fire_inspection import models as fi_models

CONFIRM_LABEL = fi_models.FIELD_CONFIRM


def _raw_record(rid: str = "recA", **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "设备编号": "FJ-2F-MF-005",
        "点检人": [{"id": "ou_x", "name": "邓宇"}],
        "点检人.部门": "发酵工程部",
        "点检时间": 1789442700000,
        "点检结果": "正常",
        "整改状态": "无需整改",
        "异常描述": "无异常",
        CONFIRM_LABEL: True,
        "整体照片": [{"file_token": "tok_o", "name": "overall.jpeg", "size": 100}],
        "关键部位照片": [],
        "签字": [{"file_token": "tok_s", "name": "sign.png", "size": 50}],
        "巡检记录": [],
        "创建人": {"id": "ou_x", "name": "邓宇"},
        "创建时间": 1789460579000,
    }
    fields.update(overrides)
    return {"record_id": rid, "fields": fields}


# ── 纯函数：归一 / 比对 ─────────────────────────────────────────


def test_normalize_strips_separators_and_case() -> None:
    assert fi_audit.normalize_equipment_no(" fj-2f_mf 005 ") == "FJ2FMF005"
    assert fi_audit.normalize_equipment_no(None) == ""


def test_compare_equipment_no_variants() -> None:
    ok, _ = fi_audit.compare_equipment_no("FJ-2F-MF-005", "FJ-2F-MF-005")
    assert ok is True
    # 识别串带标牌杂字符：归一后包含即一致
    ok, note = fi_audit.compare_equipment_no("FJ-2F-MF-005", "编号: FJ 2F MF 005")
    assert ok is True and "一致" in note
    ok, _ = fi_audit.compare_equipment_no("FJ-2F-MF-005", "T2-1F-CO2-001")
    assert ok is False
    # 期望为空 / 识别为空：无法核验，判不通过
    assert fi_audit.compare_equipment_no(None, "FJ-2F-MF-005")[0] is False
    assert fi_audit.compare_equipment_no("FJ-2F-MF-005", None)[0] is False


# ── 纯函数：模型输出解析 ────────────────────────────────────────


def test_parse_recognized_no_plain_and_fenced() -> None:
    assert fi_audit.parse_recognized_no('{"设备编号": "FJ-2F-MF-005"}') == "FJ-2F-MF-005"
    assert fi_audit.parse_recognized_no('```json\n{"设备编号": "FJ-2F-MF-005"}\n```') == "FJ-2F-MF-005"
    assert fi_audit.parse_recognized_no('{"设备编号": null}') is None
    # 空串归一为「照片无编号」（判不通过），不算解析失败
    assert fi_audit.parse_recognized_no('{"设备编号": ""}') is None


def test_parse_recognized_no_raises_on_garbage() -> None:
    for bad in ("照片里是一个灭火器", "[]", '{"别的": 1}'):
        with pytest.raises(fi_audit.AuditParseError):
            fi_audit.parse_recognized_no(bad)


# ── 纯函数：判定合成与写回体 ────────────────────────────────────


def test_decide_audit_all_pass_writes_no_note() -> None:
    d = fi_audit.decide_audit(has_signature=True, eq_ok=True, eq_note="")
    assert (d.result, d.note) == (fi_audit.AUDIT_PASS, "")
    assert fi_audit.build_writeback(d) == {"审核结果": "通过", "审核说明": ""}


def test_decide_audit_collects_failure_reasons() -> None:
    d = fi_audit.decide_audit(
        has_signature=False,
        eq_ok=False, eq_note="照片识别编号 X 与登记编号 Y 不一致",
    )
    assert d.result == fi_audit.AUDIT_FAIL
    assert "手写签字" in d.note and "不一致" in d.note and "；" in d.note


def test_to_data_uri_sniffs_magic() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    assert fi_audit.to_data_uri(png).startswith("data:image/png;base64,")
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 10
    assert fi_audit.to_data_uri(jpeg).startswith("data:image/jpeg;base64,")


# ── 编排：run_audit_round（内存桩）──────────────────────────────


class FakeRepo:
    def __init__(self, raw_records: list[dict[str, Any]]) -> None:
        self.raw_records = raw_records
        self.updates: list[tuple[str, dict[str, str]]] = []

    async def list_records(self) -> list[dict[str, Any]]:
        return self.raw_records

    async def download(self, file_token: str, extra: str | None = None) -> bytes:
        return b"\xff\xd8\xff\xe0" + b"\x00" * 10  # 小 JPEG 原样透传

    async def attachment_extra_map(self, record_ids: list[str]) -> dict[str, dict[str, str]]:
        return {}

    async def update_fields(self, record_id: str, field_values: dict[str, str]) -> None:
        self.updates.append((record_id, dict(field_values)))

    async def aclose(self) -> None:
        return None


def _vision_reply(no: str | None) -> Any:
    async def chat(prompt: str, uris: list[str]) -> str:
        import json as _json
        return _json.dumps({"设备编号": no}, ensure_ascii=False)
    return chat


async def test_round_audits_pending_and_skips_audited() -> None:
    repo = FakeRepo([
        _raw_record("rec_pending"),
        _raw_record("rec_done", **{"审核结果": "通过", "审核说明": ""}),
    ])

    result = await fi_audit.run_audit_round(repo=repo, vision_chat=_vision_reply("FJ-2F-MF-005"))

    assert result.audited == ["rec_pending"]
    assert result.passed == ["rec_pending"]
    assert result.infra_failed == []
    assert repo.updates == [("rec_pending", {"审核结果": "通过", "审核说明": ""})]


async def test_round_fail_verdict_on_mismatch_and_missing_sign() -> None:
    repo = FakeRepo([
        _raw_record("rec_mismatch", **{"签字": []}),  # 无签字 + 编号不一致
    ])

    result = await fi_audit.run_audit_round(repo=repo, vision_chat=_vision_reply("T2-9F-XX-999"))

    assert result.failed_audit == ["rec_mismatch"]
    _, body = repo.updates[0]
    assert body["审核结果"] == "不通过"
    assert "手写签字" in body["审核说明"] and "不一致" in body["审核说明"]


async def test_round_no_overall_photo_fails_verdict_without_vision_call() -> None:
    repo = FakeRepo([_raw_record("rec_nophoto", **{"整体照片": []})])
    called: list[int] = []

    async def chat(prompt: str, uris: list[str]) -> str:  # 不应被调到
        called.append(1)
        return '{"设备编号": "FJ-2F-MF-005"}'

    result = await fi_audit.run_audit_round(repo=repo, vision_chat=chat)

    assert called == []
    assert result.failed_audit == ["rec_nophoto"]
    assert "未上传整体照片" in repo.updates[0][1]["审核说明"]


async def test_round_infra_failure_skips_writeback_for_retry() -> None:
    repo = FakeRepo([_raw_record("rec_bad"), _raw_record("rec_ok")])
    calls: list[str] = []

    async def flaky_vision(prompt: str, uris: list[str]) -> str:
        calls.append(uris[0][:20])
        if len(calls) == 1:  # 首条（rec_bad）模型挂，次条正常
            raise RuntimeError("model boom")
        return '{"设备编号": "FJ-2F-MF-005"}'

    result = await fi_audit.run_audit_round(repo=repo, vision_chat=flaky_vision)

    assert [rid for rid, _ in result.infra_failed] == ["rec_bad"]
    assert result.audited == ["rec_ok"]
    assert [rid for rid, _ in repo.updates] == ["rec_ok"]  # 失败条绝不写回


async def test_round_scope_limited_by_record_ids() -> None:
    repo = FakeRepo([_raw_record("rec_a"), _raw_record("rec_b")])

    result = await fi_audit.run_audit_round(["rec_b"], repo=repo, vision_chat=_vision_reply("FJ-2F-MF-005"))

    assert result.audited == ["rec_b"]


# ── 双表：消火栓 spec（2026-11-10 接入）────────────────────────


def test_build_audit_prompt_injects_device_spec() -> None:
    hydrant_prompt = fi_audit.build_audit_prompt(fi_models.HYDRANT_SPEC)
    assert "消火栓" in hydrant_prompt
    assert "XHS" in hydrant_prompt  # 编号示例带消火栓类型码
    assert "灭火器" in fi_audit.build_audit_prompt(fi_models.EXTINGUISHER_SPEC)


async def test_round_hydrant_spec_audits_and_writes_back() -> None:
    repo = FakeRepo([_raw_record("rec_h1", **{"设备编号": "T2-3F-XHS-001"})])

    result = await fi_audit.run_audit_round(
        repo=repo, vision_chat=_vision_reply("T2-3F-XHS-001"), spec=fi_models.HYDRANT_SPEC
    )

    assert result.audited == ["rec_h1"]
    assert result.passed == ["rec_h1"]
    assert repo.updates == [("rec_h1", {"审核结果": "通过", "审核说明": ""})]


# ── 开关 ────────────────────────────────────────────────────────


def test_audit_gate_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_FIRE_INSPECTION_AUDIT_ENABLED", raising=False)
    assert fi_audit.audit_enabled() is False
    monkeypatch.setenv("SAFETY_FIRE_INSPECTION_AUDIT_ENABLED", "1")
    assert fi_audit.audit_enabled() is True
    monkeypatch.setenv("SAFETY_FIRE_INSPECTION_AUDIT_ENABLED", "false")
    assert fi_audit.audit_enabled() is False
