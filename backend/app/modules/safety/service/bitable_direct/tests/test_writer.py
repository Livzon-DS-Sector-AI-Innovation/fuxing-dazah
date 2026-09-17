"""底座写入 / 串行回写 / 字段 ID 缓存 / 幂等建列 单测（假 client，无 IO）。

覆盖票据 05 验收项：全部成功、部分失败、间隔生效、跳过空项、字段 ID 缓存、
建列幂等与 dry-run、list_fields 空时拒绝建列、冲突不改列。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct import reader, writer


class FakeWriter:
    """替身回写器：记录每次写请求；可整体失败（False）或抛错。"""

    def __init__(self, result: bool | Exception = True) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def update_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        table_id: str | None = None,
    ) -> bool:
        self.calls.append(
            {"record_id": record_id, "fields": fields, "table_id": table_id}
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSleep:
    """替身 sleep：记录间隔，不真等。"""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class FakeFieldAdmin:
    """替身字段管理客户端：记录 list_fields / create_field 调用。"""

    def __init__(
        self,
        fields: list[dict[str, Any]] | None = None,
        create_result: dict[str, Any] | None = None,
    ) -> None:
        self.fields = list(fields or [])
        self.create_result = dict(create_result or {})
        self.list_calls = 0
        self.create_calls: list[dict[str, Any]] = []

    async def list_fields(self, table_id: str | None = None) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [dict(item) for item in self.fields]

    async def create_field(
        self,
        field_name: str,
        field_type: int,
        table_id: str | None = None,
        *,
        property_: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.create_calls.append(
            {
                "field_name": field_name,
                "field_type": field_type,
                "table_id": table_id,
                "property_": property_,
            }
        )
        return dict(self.create_result)


def _ru(record_id: str, fields: dict[str, Any] | None = None) -> writer.RecordUpdate:
    return writer.RecordUpdate(record_id, fields if fields is not None else {"x": 1})


def _field(
    name: str,
    field_id: str,
    *,
    field_type: int = 3,
    options: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "field_name": name,
        "field_id": field_id,
        "type": field_type,
    }
    if options is not None:
        item["property"] = {
            "options": [
                {"id": f"opt{i}", "name": option}
                for i, option in enumerate(options)
            ]
        }
    return item


RISK_SPEC = writer.FieldSpec(
    name="日报风险等级（AI）",
    field_type=3,
    property_={
        "options": [{"name": "高风险"}, {"name": "中风险"}, {"name": "低风险"}]
    },
)
RISK_FIELD = _field(
    "日报风险等级（AI）",
    "fldRisk",
    options=["高风险", "中风险", "低风险"],
)


class TestWriteSerial:
    async def test_all_success_writes_only_given_fields(self) -> None:
        fake = FakeWriter()
        updates = [
            _ru("rec1", {"日报风险等级（AI）": "高风险"}),
            _ru("rec2", {"日报风险等级（AI）": "中风险"}),
        ]

        result = await writer.write_serial(fake, updates, sleep=FakeSleep())

        assert [call["record_id"] for call in fake.calls] == ["rec1", "rec2"]
        assert [call["fields"] for call in fake.calls] == [
            {"日报风险等级（AI）": "高风险"},
            {"日报风险等级（AI）": "中风险"},
        ]
        assert all(
            list(call["fields"]) == ["日报风险等级（AI）"] for call in fake.calls
        )
        assert (result.attempted, result.written, result.skipped, result.failed) == (
            2,
            2,
            0,
            [],
        )
        assert result.ok is True

    async def test_interval_between_items_only(self) -> None:
        sleeper = FakeSleep()

        await writer.write_serial(
            FakeWriter(),
            [_ru("a"), _ru("b"), _ru("c")],
            sleep=sleeper,
        )

        assert sleeper.delays == [0.5, 0.5]
        assert writer.WRITEBACK_INTERVAL_SECONDS == 0.5

    async def test_custom_interval(self) -> None:
        sleeper = FakeSleep()

        await writer.write_serial(
            FakeWriter(),
            [_ru("a"), _ru("b"), _ru("c")],
            interval_seconds=0.2,
            sleep=sleeper,
        )

        assert sleeper.delays == [0.2, 0.2]

    async def test_skips_empty_fields_and_record_id(self) -> None:
        fake = FakeWriter()
        sleeper = FakeSleep()

        result = await writer.write_serial(
            fake,
            [_ru(""), _ru("rec", {}), _ru("ok")],
            sleep=sleeper,
        )

        assert [call["record_id"] for call in fake.calls] == ["ok"]
        assert (result.attempted, result.written, result.skipped) == (1, 1, 2)
        assert sleeper.delays == []

    async def test_partial_failure_records_failed_without_raising(self) -> None:
        result = await writer.write_serial(
            FakeWriter(result=False), [_ru("a"), _ru("b")], sleep=FakeSleep()
        )

        assert result.attempted == 2
        assert result.written == 0
        assert result.failed == ["a", "b"]
        assert result.ok is False

    async def test_exception_is_swallowed_per_item(self) -> None:
        result = await writer.write_serial(
            FakeWriter(result=RuntimeError("bitable 500")),
            [_ru("a")],
            sleep=FakeSleep(),
        )

        assert result.failed == ["a"]
        assert result.written == 0

    async def test_table_id_forwarded(self) -> None:
        fake = FakeWriter()

        await writer.write_serial(
            fake, [_ru("a")], table_id="tbl9", sleep=FakeSleep()
        )

        assert fake.calls[0]["table_id"] == "tbl9"

    async def test_empty_updates(self) -> None:
        result = await writer.write_serial(FakeWriter(), [], sleep=FakeSleep())

        assert (result.attempted, result.written, result.skipped) == (0, 0, 0)


class TestFieldIdResolver:
    async def test_resolves_and_caches(self) -> None:
        admin = FakeFieldAdmin([RISK_FIELD])
        resolver = writer.FieldIdResolver(admin, table_id="tbl1")

        assert await resolver.field_id("日报风险等级（AI）") == "fldRisk"
        assert await resolver.field_id("日报风险等级（AI）") == "fldRisk"
        assert admin.list_calls == 1

    async def test_missing_field_returns_none_and_caches(self) -> None:
        admin = FakeFieldAdmin([_field("其它", "f0")])
        resolver = writer.FieldIdResolver(admin)

        assert await resolver.field_id("不存在") is None
        assert await resolver.field_id("不存在") is None
        assert admin.list_calls == 1

    async def test_invalidate_forces_refetch(self) -> None:
        admin = FakeFieldAdmin([RISK_FIELD])
        resolver = writer.FieldIdResolver(admin)

        await resolver.field_id("日报风险等级（AI）")
        resolver.invalidate()
        await resolver.field_id("日报风险等级（AI）")

        assert admin.list_calls == 2

    async def test_function_with_external_cache(self) -> None:
        admin = FakeFieldAdmin([RISK_FIELD])
        cache: dict[tuple[str, str], str] = {}

        first = await writer.resolve_field_id(
            admin, "日报风险等级（AI）", table_id="tbl1", cache=cache
        )
        second = await writer.resolve_field_id(
            admin, "日报风险等级（AI）", table_id="tbl1", cache=cache
        )

        assert first == second == "fldRisk"
        assert cache == {("tbl1", "日报风险等级（AI）"): "fldRisk"}
        assert admin.list_calls == 1


class TestFieldMatching:
    def test_property_subset_tolerates_extra_keys(self) -> None:
        actual = {"options": [{"id": "opt1", "name": "高风险"}]}
        assert writer.property_matches(actual, {"options": [{"name": "高风险"}]})

    def test_property_list_order_matters(self) -> None:
        actual = {"options": [{"name": "中风险"}, {"name": "高风险"}]}
        assert not writer.property_matches(
            actual, {"options": [{"name": "高风险"}, {"name": "中风险"}]}
        )

    def test_property_list_length_matters(self) -> None:
        actual = {"options": [{"name": "高风险"}]}
        assert not writer.property_matches(
            actual, {"options": [{"name": "高风险"}, {"name": "中风险"}]}
        )

    def test_bool_is_not_int(self) -> None:
        assert writer.property_matches(True, True)
        assert not writer.property_matches(True, 1)
        assert not writer.property_matches(1, True)

    def test_field_matches_type_and_name(self) -> None:
        assert writer.field_matches(RISK_FIELD, RISK_SPEC)
        assert not writer.field_matches({**RISK_FIELD, "type": 1}, RISK_SPEC)
        assert not writer.field_matches({**RISK_FIELD, "field_name": "其它"}, RISK_SPEC)
        assert writer.field_matches(
            {"field_name": "X", "field_id": "f", "type": 3},
            writer.FieldSpec(name="X", field_type=3),
        )

    def test_extract_option_names(self) -> None:
        assert writer.extract_option_names(RISK_SPEC.property_) == [
            "高风险",
            "中风险",
            "低风险",
        ]
        assert writer.extract_option_names(None) == []
        assert writer.extract_option_names({"options": "not-a-list"}) == []

    def test_describe_spec(self) -> None:
        text = writer.describe_spec(RISK_SPEC)
        assert "日报风险等级（AI）" in text
        assert "type=3" in text
        assert "高风险" in text


class TestEnsureField:
    async def test_missing_dry_run_does_not_create(self) -> None:
        admin = FakeFieldAdmin([_field("其它", "f0")])

        result = await writer.ensure_field(admin, RISK_SPEC)

        assert result.status == "would_create"
        assert result.ok is True
        assert result.changed is False
        assert admin.create_calls == []
        assert "dry-run" in result.message

    async def test_missing_apply_creates_and_verifies(self) -> None:
        admin = FakeFieldAdmin([_field("其它", "f0")], create_result=RISK_FIELD)

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "created"
        assert result.ok is True
        assert result.changed is True
        assert admin.create_calls == [
            {
                "field_name": "日报风险等级（AI）",
                "field_type": 3,
                "table_id": None,
                "property_": RISK_SPEC.property_,
            }
        ]

    async def test_existing_matching_is_skipped(self) -> None:
        admin = FakeFieldAdmin([RISK_FIELD])

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "exists"
        assert result.ok is True
        assert result.changed is False
        assert admin.create_calls == []

    async def test_existing_type_mismatch_is_conflict_and_never_modified(self) -> None:
        admin = FakeFieldAdmin(
            [_field("日报风险等级（AI）", "fldRisk", field_type=1)]
        )

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "conflict"
        assert result.ok is False
        assert admin.create_calls == []

    async def test_existing_option_mismatch_is_conflict(self) -> None:
        admin = FakeFieldAdmin(
            [_field("日报风险等级（AI）", "fldRisk", options=["高风险", "中风险"])]
        )

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "conflict"
        assert admin.create_calls == []

    async def test_empty_list_fields_refuses_to_create(self) -> None:
        admin = FakeFieldAdmin([])

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "failed"
        assert result.ok is False
        assert admin.create_calls == []

    async def test_create_failure(self) -> None:
        admin = FakeFieldAdmin([_field("其它", "f0")], create_result={})

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "failed"
        assert admin.create_calls

    async def test_created_but_mismatch_reports_manual_check(self) -> None:
        admin = FakeFieldAdmin(
            [_field("其它", "f0")],
            create_result=_field("日报风险等级（AI）", "fldRisk", options=["高风险"]),
        )

        result = await writer.ensure_field(admin, RISK_SPEC, apply=True)

        assert result.status == "created"
        assert "人工核对" in result.message


class TestOpenWriter:
    def test_returns_resolved_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = object()
        monkeypatch.setattr(reader, "resolve_client", lambda *a, **k: fake)

        assert writer.open_writer("fire_alarm", "alarm") is fake

    def test_passes_table_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = object()
        captured: dict[str, Any] = {}

        def fake_resolve(domain: str, kind: str, *, table_id: str | None = None) -> Any:
            captured["domain"] = domain
            captured["kind"] = kind
            captured["table_id"] = table_id
            return fake

        monkeypatch.setattr(reader, "resolve_client", fake_resolve)

        assert writer.open_writer("fire_alarm", "alarm", table_id="tblX") is fake
        assert captured == {
            "domain": "fire_alarm",
            "kind": "alarm",
            "table_id": "tblX",
        }
