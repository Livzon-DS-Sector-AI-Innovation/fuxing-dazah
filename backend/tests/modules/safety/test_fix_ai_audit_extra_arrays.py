"""B0 配套修复脚本 —— 纯函数单测（不连 DB、不 apply、无网络）。

脚本位于 ``backend/scripts/fix_ai_audit_extra_arrays.py``；用 importlib 按路径加载，
只测其外部可观察契约：数组脏行折叠规则与待修复清单筛选。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "fix_ai_audit_extra_arrays.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fix_ai_audit_extra_arrays", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixer = _load_script()


def test_fold_merges_dict_items_in_order() -> None:
    """数组里的 dict 按顺序折叠，后者覆盖前者；null/字符串/嵌套数组丢弃。"""
    value = [
        None,
        {"json_valid": False, "parse_attempts": 1},
        "{}",
        ["nested"],
        {"json_valid": True},
    ]
    assert fixer.fold_extra_array(value) == {
        "json_valid": True,
        "parse_attempts": 1,
    }


def test_fold_empty_and_non_list() -> None:
    assert fixer.fold_extra_array([]) == {}
    assert fixer.fold_extra_array(None) == {}
    assert fixer.fold_extra_array({"a": 1}) == {}
    assert fixer.fold_extra_array("oops") == {}


def test_plan_fixes_keeps_only_array_rows() -> None:
    rows = [
        {"id": "r1", "extra": json.dumps([None, {"json_valid": True}])},
        {"id": "r2", "extra": '{"json_valid": true}'},
        {"id": "r3", "extra": "null"},
        {"id": "r4", "extra": '"{}"'},
        {"id": "r5", "extra": "[null, {\"a\": 1}]"},
        {"id": "r6", "extra": "not-json"},
        {"id": "r7", "extra": None},
    ]

    plans = fixer.plan_fixes(rows)

    assert [plan["id"] for plan in plans] == ["r1", "r5"]
    assert plans[0]["after"] == {"json_valid": True}
    assert plans[1]["after"] == {"a": 1}


def test_plan_fixes_accepts_decoded_lists() -> None:
    """asyncpg text 列之外，直接喂已解码 list 也能工作。"""
    plans = fixer.plan_fixes([{"id": "r1", "extra": [{"a": 1}, {"b": 2}]}])
    assert plans == [{"id": "r1", "before": [{"a": 1}, {"b": 2}], "after": {"a": 1, "b": 2}}]


def test_main_defaults_to_dry_run_and_apply_requires_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 dry-run 只 SELECT；只有显式 --apply 才写库。"""
    calls = {"fetch": 0, "apply": 0}

    async def _fake_fetch(dsn: str, *, limit: int) -> list[dict[str, object]]:
        calls["fetch"] += 1
        return [{"id": "r1", "extra": '[null, {"a": 1}]'}]

    async def _fake_apply(dsn: str, plans: list[dict[str, object]]) -> int:
        calls["apply"] += 1
        return len(plans)

    monkeypatch.setattr(fixer, "_resolve_dsn", lambda explicit="": "postgresql://test/db")
    monkeypatch.setattr(fixer, "fetch_array_rows", _fake_fetch)
    monkeypatch.setattr(fixer, "apply_fixes", _fake_apply)

    assert fixer.main([]) == 0
    assert calls == {"fetch": 1, "apply": 0}

    assert fixer.main(["--apply"]) == 0
    assert calls == {"fetch": 2, "apply": 1}
