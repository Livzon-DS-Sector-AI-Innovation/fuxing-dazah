"""督办通报 @ 提及标识解析的单元测试。

纯内存桩验证，不打飞书网络：责任人 open_id 应优先直取记录「整改责任人」
人员字段自带的 id（读取应用作用域，与卡片 @ 同源）；仅表外人名（部门映射
覆盖产生）走 identity 回退 ``_load_person_open_ids``。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import bitable_repo, bulletin


def _record(
    no: str,
    *,
    dept: str = "设备工程部",
    persons: list[dict[str, str]] | None = None,
    supervision: str = "红色预警",
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "隐患编号": no,
        "隐患描述": f"{no} 隐患描述",
        "整改责任人": persons if persons is not None else [
            {"id": f"ou_{no}", "name": "张三"},
        ],
        "整改责任人.部门": [dept],
        "督办等级": supervision,
        "整改状态": "未关闭",
    }
    return {"record_id": f"rec_{no}", "fields": fields}


def _view(record: dict[str, Any]) -> bitable_repo.HazardView:
    return bitable_repo.to_view(record)


# ── _harvest_person_ids ─────────────────────────────────────────


def test_harvest_old_list_format() -> None:
    views = [_view(_record("HZ-001")), _view(_record("HZ-002"))]
    assert bulletin._harvest_person_ids(views) == {
        "张三": "ou_HZ-001",  # 同名首条为准
    }


def test_harvest_new_users_format_and_multi_person() -> None:
    record = _record("HZ-003", persons=None)
    record["fields"]["整改责任人"] = {"users": [
        {"userId": "ou_a", "name": "李四"},
        {"userId": "ou_b", "name": "王五"},
    ]}
    out = bulletin._harvest_person_ids([_view(record)])
    assert out == {"李四": "ou_a", "王五": "ou_b"}


def test_harvest_skips_blank_and_garbage_entries() -> None:
    record = _record("HZ-004")
    record["fields"]["整改责任人"] = [
        {"name": "无id人"},
        {"id": "ou_x"},               # 无姓名 → 丢弃
        "纯字符串",                    # 非 dict → 跳过
        {"id": "ou_ok", "name": "赵六"},
    ]
    assert bulletin._harvest_person_ids([_view(record)]) == {"赵六": "ou_ok"}


# ── build_bulletin 整链 ─────────────────────────────────────────


def _patch_render_deps(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
    *,
    dept_override: dict[str, str] | None = None,
) -> list[list[str]]:
    """桩掉网络/DB 依赖；返回回退解析器的收参记录。"""
    from app.modules.safety.bitable_config.store import store as bitable_store
    from app.modules.safety.service import responsible_mapping
    from app.modules.safety.service.hazard_direct import progress_track

    async def fake_fetch(client: Any) -> list[dict[str, Any]]:
        return records

    async def fake_marks(views: Any) -> dict[str, str]:
        return {}

    async def fake_fallback(names: list[str]) -> dict[str, str]:
        calls.append(names)
        return {n: f"ou_fb_{n}" for n in names}

    calls: list[list[str]] = []
    monkeypatch.setattr(bulletin, "_fetch_targets", fake_fetch)
    monkeypatch.setattr(progress_track, "compute_marks", fake_marks)
    monkeypatch.setattr(bulletin, "_load_person_open_ids", fake_fallback)
    monkeypatch.setattr(
        responsible_mapping, "DEPARTMENT_RESPONSIBLE_OVERRIDE",
        dept_override or {},
    )
    monkeypatch.setattr(
        bitable_store, "get_connection",
        lambda *a: SimpleNamespace(
            app_token="app", table_id="tbl", status="active",
        ),
    )
    return calls


async def test_build_bulletin_ats_from_person_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """人员字段自带 id → 直接用于 @，不走 identity 回退。"""
    records = [
        _record("HZ-001", persons=[{"id": "ou_lin", "name": "林建水"}]),
        _record("HZ-002", persons=[{"id": "ou_yang", "name": "杨剑"}]),
    ]
    calls = _patch_render_deps(monkeypatch, records)

    content, stats = await bulletin.build_bulletin()

    assert stats["total"] == 2 and stats["urgent"] == 2
    assert "<at id=ou_lin></at>" in content
    assert "<at id=ou_yang></at>" in content
    assert calls == []  # 全员命中人员字段，零回退


async def test_build_bulletin_falls_back_for_dept_override_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """部门映射覆盖出的表外人名 → 走回退解析并合入 @。"""
    records = [
        _record("HZ-001", dept="质量控制部", persons=[
            {"id": "ou_raw", "name": "原责任人"},
        ]),
    ]
    calls = _patch_render_deps(
        monkeypatch, records,
        dept_override={"质量控制部": "陈雅芳"},
    )

    content, stats = await bulletin.build_bulletin()

    assert stats["total"] == 1
    assert calls == [["陈雅芳"]]  # 仅表外名回退
    assert "<at id=ou_fb_陈雅芳></at>" in content
    assert "ou_raw" not in content  # 被映射覆盖的原责任人不 @
