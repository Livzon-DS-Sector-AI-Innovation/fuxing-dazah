"""A1 JSON 局部修复链 —— 视觉链 + 文本链（测试接缝 S1）。

只测外部行为：
    - `json_repair` 纯函数对真实畸形样本的修复结果（不测内部阶段实现细节，
      只断言 data / stages / error 的可观察契约）；
    - `AuditedAIService.chat_vision_parsed` / `chat_parsed` 的可观察行为：
      修复成功时只发 1 次 HTTP 请求、缺键仍报错、视觉不可修复才重试一次；
    - 审计质量维度通过 monkeypatch `_mark_parse_outcome` / `_write_audit` 观察。

无真实网络/DB：HTTP 用 httpx.MockTransport，审计落库全部 fake。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.modules.safety.ai_audit import audited_client
from app.modules.safety.ai_audit.audited_client import AuditedAIService
from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.ai_audit.json_repair import (
    drop_trailing_commas,
    repair_json,
    repair_json_object,
    slice_object,
    strip_fences,
)
from app.platform.integrations.ai.client import AIOutputError

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"


# ═══════════════════════════════════════════════════════════════
# json_repair 纯函数契约
# ═══════════════════════════════════════════════════════════════


def test_strip_fences_and_slice_object() -> None:
    fenced = '```json\n{"a": 1}\n```'
    assert strip_fences(fenced) == '{"a": 1}'
    # 前后带包裹文字：fence 不从头开始 → 由 slice_object 兜底
    wrapped = '以下是识别结果：\n```json\n{"a": 1}\n```\n请查收'
    assert slice_object(wrapped) == '{"a": 1}'


def test_drop_trailing_commas_keeps_string_inner_comma() -> None:
    raw = '{"a": "x, }", "b": [1, 2,], }'
    fixed = drop_trailing_commas(raw)
    assert json.loads(fixed) == {"a": "x, }", "b": [1, 2]}


def test_repair_object_trailing_comma_real_sample() -> None:
    """实测 22/31 非法样本形态：字段间合法、末尾多一个逗号。"""
    raw = '{\n  "key_defect": "管道标识缺失",\n  "hazard_level": "general",\n}'
    result = repair_json_object(raw)
    assert result.data == {"key_defect": "管道标识缺失", "hazard_level": "general"}
    assert result.repaired is True
    assert "trailing_comma" in result.stages


def test_repair_object_wrapped_by_text_and_fence() -> None:
    raw = '结果如下：\n```json\n{"a": 1}\n```\n以上。'
    result = repair_json_object(raw)
    assert result.data == {"a": 1}
    assert result.repaired is True


def test_repair_object_fullwidth_quotes_fallback() -> None:
    raw = "{“a”: 1, “b”: 2}"
    result = repair_json_object(raw)
    assert result.data == {"a": 1, "b": 2}
    assert "fullwidth_quotes" in result.stages


def test_repair_object_plain_valid_json_not_marked_repaired() -> None:
    result = repair_json_object('{"a": 1}')
    assert result.data == {"a": 1}
    assert result.repaired is False
    assert result.stages == ()


def test_repair_object_unrecoverable_returns_none_with_error() -> None:
    result = repair_json_object("这不是 JSON，也没有大括号")
    assert result.data is None
    assert result.error


def test_repair_object_structural_truncation_not_faked() -> None:
    """缺失闭合符不做括号配平（残余结构畸形交给带反馈重试，避免修出错误结构）。"""
    result = repair_json_object('{"key_defect": "x", "nested": {"a": 1}')
    assert result.data is None


def test_repair_json_general_supports_list() -> None:
    """文本链平台语义支持数组输出：通用修复不强制 dict。"""
    result = repair_json("```json\n[{\"a\": 1},]\n```")
    assert result.data == [{"a": 1}]
    assert result.repaired is True


# ── T1③ 误修复矩阵：不确定的畸形宁可返回 None，也不伪造成「合法对象」 ──


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ('注意{不是JSON}，结果：{"a": 1}', "prose 先出现 { → slice 区间错误"),
        ('{"a": 1,}}', "多余闭合符（不配平）"),
        ('{"a": 1， "b": 2}', "中文逗号非分隔符"),
        ("{'a': 1}", "单引号 JSON"),
        ('{"a": 1', "缺闭合"),
        ('结果：“a”: 1', "全角引号但无对象包裹"),
    ],
)
def test_repair_object_does_not_fake_repair_malformed(raw: str, reason: str) -> None:
    """误修复矩阵：这些形态不得被「修」成貌似合法的错误对象（安全优先）。"""
    result = repair_json_object(raw)
    assert result.data is None, f"{reason}：不应伪造成合法对象 {result.data!r}"


def test_repair_object_fullwidth_after_slice_still_repairs() -> None:
    """边界另一侧：可安全修复的全角引号对象仍应修复（避免把修复能力一起收掉）。"""
    result = repair_json_object('结果如下：{“a”: 1}')
    assert result.data == {"a": 1}
    assert "fullwidth_quotes" in result.stages


# ── T1④ 空/非字符串输入：返回 empty response，不抛异常 ──


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_repair_json_empty_input_returns_error(raw: Any) -> None:
    result = repair_json(raw)
    assert result.data is None
    assert result.repaired is False
    assert result.error == "empty response"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_repair_json_object_empty_input_returns_error(raw: Any) -> None:
    result = repair_json_object(raw)
    assert result.data is None
    assert result.error == "empty response"


# ═══════════════════════════════════════════════════════════════
# 测试用 service / handler
# ═══════════════════════════════════════════════════════════════


def _make_service(
    handler: Callable[[httpx.Request], httpx.Response]
) -> AuditedAIService:
    service = AuditedAIService(api_key="test", base_url=BASE_URL, model=MODEL)
    service._client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    )
    return service


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


class _Calls:
    """记录 HTTP 请求次数与请求体（外部边界观察）。"""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        if not self.responses:
            raise AssertionError("HTTP 请求次数超出预期")
        return self.responses.pop(0)


async def _no_writes(**kwargs: object) -> None:  # noqa: ANN003
    return None


# ═══════════════════════════════════════════════════════════════
# chat_vision_parsed：修复成功零额外调用
# ═══════════════════════════════════════════════════════════════


async def test_vision_trailing_comma_repaired_with_single_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    marked: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marked.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('{"key_defect": "缺失", "level": "general",}')])
    service = _make_service(calls)
    try:
        parsed = await service.chat_vision_parsed(
            "识别", [], ["key_defect", "level"], temperature=0.05
        )
    finally:
        await service.close()

    assert parsed == {"key_defect": "缺失", "level": "general"}
    assert len(calls.bodies) == 1  # 零额外 AI 调用
    assert marked and marked[0]["json_valid"] is False
    assert marked[0]["json_repaired"] is True
    assert "trailing_comma" in marked[0]["stages"]


async def test_vision_valid_json_marks_json_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    marked: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marked.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('{"a": 1}')])
    service = _make_service(calls)
    try:
        assert await service.chat_vision_parsed("p", [], ["a"]) == {"a": 1}
    finally:
        await service.close()
    assert len(calls.bodies) == 1
    assert marked[0]["json_valid"] is True
    assert marked[0]["json_repaired"] is False


async def test_vision_repaired_still_checks_expected_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """修复「能解析」不等于「有效业务输出」：缺键仍报错。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)

    async def _noop_mark(**kwargs: object) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _noop_mark)
    calls = _Calls(
        [
            _completion('{"a": 1,}'),
            _completion('{"a": 1,}'),  # 反馈重试仍缺键
        ]
    )
    service = _make_service(calls)
    try:
        with pytest.raises(AIOutputError, match="missing keys"):
            await service.chat_vision_parsed("p", [], ["a", "b"])
    finally:
        await service.close()
    assert len(calls.bodies) == 2


async def test_vision_unrecoverable_retries_once_with_error_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    attempts: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        attempts.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion("完全不是 JSON"), _completion('{"a": 1}')])
    service = _make_service(calls)
    try:
        parsed = await service.chat_vision_parsed("原始要求", [], ["a"])
    finally:
        await service.close()

    assert parsed == {"a": 1}
    assert len(calls.bodies) == 2
    # 第二次 prompt 带错误反馈（而不是同 prompt 盲重发）
    second_texts = [
        part["text"]
        for part in calls.bodies[1]["messages"][-1]["content"]
        if part.get("type") == "text"
    ]
    assert any("上一次输出无法解析" in text for text in second_texts)
    assert attempts[0]["parse_attempts"] == 1
    assert attempts[-1]["parse_attempts"] == 2


async def test_vision_retry_twice_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)

    async def _noop_mark(**kwargs: object) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _noop_mark)
    calls = _Calls([_completion("bad"), _completion("still bad")])
    service = _make_service(calls)
    try:
        with pytest.raises(AIOutputError, match="not valid JSON"):
            await service.chat_vision_parsed("p", [], ["a"])
    finally:
        await service.close()
    assert len(calls.bodies) == 2  # 只重试一次


async def test_vision_parse_retry_writes_two_audit_rows_and_meta_targets_each_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1①：客户端解析重试一次 → 2 条审计行，parse 元数据落在各自「最近」的行。

    第 1 次输出不可解析：`json_valid=false / parse_attempts=1` → row-1；
    第 2 次输出合法：`json_valid=true / parse_attempts=2` → row-2。
    """
    audit_rows: list[dict[str, Any]] = []
    marks: list[tuple[str | None, dict[str, Any]]] = []

    async def _fake_write_audit(**kwargs: object) -> None:  # noqa: ANN003
        row_id = f"row-{len(audit_rows) + 1}"
        audit_rows.append({"row_id": row_id, **kwargs})
        audited_client._last_audit_row_id.set(row_id)

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marks.append((audited_client._last_audit_row_id.get(), dict(kwargs)))

    monkeypatch.setattr(audited_client, "_write_audit", _fake_write_audit)
    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion("完全不是 JSON"), _completion('{"a": 1}')])
    service = _make_service(calls)
    try:
        assert await service.chat_vision_parsed("p", [], ["a"]) == {"a": 1}
    finally:
        await service.close()

    assert len(calls.bodies) == 2
    assert [row["row_id"] for row in audit_rows] == ["row-1", "row-2"]
    assert [mark[0] for mark in marks] == ["row-1", "row-2"]
    # 第 1 次：不可解析 → json_valid=false，attempts=1
    assert marks[0][1]["parse_attempts"] == 1
    assert marks[0][1]["json_valid"] is False
    assert marks[0][1]["json_repaired"] is False
    # 第 2 次：原文合法 → json_valid=true，attempts=2
    assert marks[1][1]["parse_attempts"] == 2
    assert marks[1][1]["json_valid"] is True
    assert marks[1][1]["json_repaired"] is False


# ═══════════════════════════════════════════════════════════════
# chat_parsed：文本链修复（所有审计场景受益）+ 平台语义兼容
# ═══════════════════════════════════════════════════════════════


async def test_text_trailing_comma_repaired_single_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    marked: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marked.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('```json\n{"a": 1,}\n```')])
    service = _make_service(calls)
    try:
        parsed = await service.chat_parsed(
            [{"role": "user", "content": "返回 json"}], ["a"]
        )
    finally:
        await service.close()
    assert parsed == {"a": 1}
    assert len(calls.bodies) == 1
    assert marked[0]["json_repaired"] is True


async def test_text_array_merged_kept_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """平台 AIService.chat_parsed 的数组→合并语义保持不变。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)

    async def _noop_mark(**kwargs: object) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _noop_mark)
    calls = _Calls([_completion('[{"a": "x"}, {"a": "y", "b": 1}]')])
    service = _make_service(calls)
    try:
        parsed = await service.chat_parsed(
            [{"role": "user", "content": "返回 json"}], ["a", "b"]
        )
    finally:
        await service.close()
    assert parsed["a"] == "x；y"
    assert parsed["b"] == 1


async def test_text_unrecoverable_raises_without_extra_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文本链重试策略归 ① 插件；客户端只修复一次、不额外重试。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)

    async def _noop_mark(**kwargs: object) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _noop_mark)
    calls = _Calls([_completion("not json")])
    service = _make_service(calls)
    try:
        with pytest.raises(AIOutputError, match="not valid JSON"):
            await service.chat_parsed(
                [{"role": "user", "content": "返回 json"}], ["a"]
            )
    finally:
        await service.close()
    assert len(calls.bodies) == 1


async def test_parse_json_response_helper_still_compatible() -> None:
    """历史契约：_parse_json_response 支持围栏 + 布尔串。"""
    parsed = AuditedAIService._parse_json_response(
        '```json\n{"a": 1, "flag": "true"}\n```', ["a", "flag"]
    )
    assert parsed == {"a": 1, "flag": True}


def test_parse_json_response_with_meta_trailing_comma() -> None:
    outcome = AuditedAIService._parse_json_response_with_meta(
        '{"a": 1,}', ["a"]
    )
    assert outcome.data == {"a": 1}
    assert outcome.json_valid is False
    assert outcome.repaired is True


# ═══════════════════════════════════════════════════════════════
# 审计质量维度：无审计行时 no-op（不抛错）
# ═══════════════════════════════════════════════════════════════


async def test_mark_parse_outcome_noop_without_audit_row() -> None:
    await audited_client._mark_parse_outcome(
        json_valid=False, json_repaired=True, stages=("trailing_comma",), parse_attempts=1
    )


async def test_vision_parsed_works_with_audit_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有审计上下文时 mark 被调用且不因 fake _write_audit 报错。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    called: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        called.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('{"a": 1,}')])
    service = _make_service(calls)
    try:
        with ai_audit_scope(scenario="hazard_identification", extra={"bitable_record_id": "rec1"}):
            parsed = await service.chat_vision_parsed("p", [], ["a"])
    finally:
        await service.close()
    assert parsed == {"a": 1}
    assert called


async def test_vision_fenced_output_marked_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    """围栏包裹输出：原文非合法 JSON → json_valid=false / json_repaired=true。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    marked: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marked.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('```json\n{"a": 1}\n```')])
    service = _make_service(calls)
    try:
        assert await service.chat_vision_parsed("p", [], ["a"]) == {"a": 1}
    finally:
        await service.close()
    assert len(calls.bodies) == 1
    assert marked[0]["json_valid"] is False
    assert marked[0]["json_repaired"] is True
    assert "fence" in marked[0]["stages"]


async def test_text_fenced_output_marked_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    """文本链历史上不剥围栏：仅围栏修复也算 json_repaired=true。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    marked: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marked.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('```json\n{"a": 1}\n```')])
    service = _make_service(calls)
    try:
        assert await service.chat_parsed(
            [{"role": "user", "content": "返回 json"}], ["a"]
        ) == {"a": 1}
    finally:
        await service.close()
    assert marked[0]["json_valid"] is False
    assert marked[0]["json_repaired"] is True
    assert "fence" in marked[0]["stages"]


async def test_missing_keys_keeps_json_valid_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺键不是「JSON 非法」：原文可解析 → json_valid=true、json_repaired=false。"""
    monkeypatch.setattr(audited_client, "_write_audit", _no_writes)
    marked: list[dict[str, Any]] = []

    async def _capture_mark(**kwargs: object) -> None:  # noqa: ANN003
        marked.append(dict(kwargs))

    monkeypatch.setattr(audited_client, "_mark_parse_outcome", _capture_mark)
    calls = _Calls([_completion('{"a": 1}')])
    service = _make_service(calls)
    try:
        with pytest.raises(AIOutputError, match="missing keys"):
            await service.chat_parsed(
                [{"role": "user", "content": "返回 json"}], ["a", "b"]
            )
    finally:
        await service.close()
    assert marked[0]["json_valid"] is True
    assert marked[0]["json_repaired"] is False


async def test_mark_parse_outcome_writes_extra_via_independent_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A7 落库路径：独立 session 执行 JSONB 合并 UPDATE（fake session 捕获语句）。

    注意（B0）：本用例只断言 UPDATE 语句的 patch 绑定参数，**不执行 SQL**，
    不能作为 extra 合并语义的验收证据（旧 `coalesce(extra, cast("{}"))` 实现下
    它同样通过，但真 PG 里 `'null'::jsonb || patch` 会变成数组）；真 PG 级
    验收见 ``test_ai_audit_extra_merge_db.py``。
    """
    import uuid

    captured: dict[str, object] = {}

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def execute(self, stmt: object) -> None:
            captured["stmt"] = stmt

        async def commit(self) -> None:
            captured["committed"] = True

    import app.core.database as database

    monkeypatch.setattr(database, "async_session_factory", lambda: _FakeSession())
    row_id = uuid.uuid4()
    audited_client._last_audit_row_id.set(row_id)
    await audited_client._mark_parse_outcome(
        json_valid=False,
        json_repaired=True,
        stages=("trailing_comma",),
        parse_attempts=2,
    )

    assert captured.get("committed") is True
    stmt = captured["stmt"]
    params = stmt.compile().params  # type: ignore[attr-defined]
    # CASE 的 ELSE 兜底空对象（{}）也是 dict 绑定参数，这里只挑 patch 载荷
    patches = [
        value
        for value in params.values()
        if isinstance(value, dict) and "json_valid" in value
    ]
    assert patches, params
    assert patches[0]["json_valid"] is False
    assert patches[0]["json_repaired"] is True
    assert patches[0]["repair_stages"] == ["trailing_comma"]
    assert patches[0]["parse_attempts"] == 2


async def test_mark_parse_outcome_swallows_db_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审计回写失败绝不影响业务（只日志）。"""

    def _boom() -> None:
        raise RuntimeError("db down")

    import app.core.database as database

    monkeypatch.setattr(database, "async_session_factory", _boom)
    audited_client._last_audit_row_id.set("row-1")
    await audited_client._mark_parse_outcome(
        json_valid=False, json_repaired=False, stages=(), parse_attempts=1
    )
