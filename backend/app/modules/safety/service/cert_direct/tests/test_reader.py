"""cert 直读读取器单测（cert-direct Ticket 02）。

替身实现 BitablePageClient 协议全方法（含 strict 参数，mypy 结构化检查口径）；
覆盖 3 kind 映射、无姓名跳过、strict 两态、镜像口径排序。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.safety.service.cert_direct.reader import (
    CertBitableReader,
    CertWarningView,
)


class FakePageClient:
    """BitablePageClient 替身：单页返回预置 items 或抛错。"""

    def __init__(
        self, items: list[dict[str, Any]], *, error: Exception | None = None
    ) -> None:
        self._items = items
        self._error = error

    async def search_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = 500,
        page_token: str | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        if page_token:
            return {"items": [], "has_more": False}
        return {"items": self._items, "has_more": False}


def _special_op_item(rid: str, name: str | None = "张三") -> dict[str, Any]:
    fields: dict[str, Any] = {
        "部门": "生产部",
        "作业类别": "电工",
        "证件编号": f"NO-{rid}",
        "再复审时间": 1790000000000,
    }
    if name is not None:
        fields["姓名 (人员 )"] = [{"name": name}]
    return {"record_id": rid, "fields": fields}


def _guardian_item(rid: str, kind_field: str = "A证") -> dict[str, Any]:
    return {
        "record_id": rid,
        "fields": {
            "姓名": [{"name": f"人-{rid}"}],
            "部门": ["质检部"],
            "证件类型": kind_field,
            "第一次复审截止日期": 1790000000000,
        },
    }


def _make_reader(
    special_op: list[dict[str, Any]] | None = None,
    guardian_a: list[dict[str, Any]] | None = None,
    guardian_b: list[dict[str, Any]] | None = None,
    *,
    special_op_error: Exception | None = None,
    guardian_a_error: Exception | None = None,
    guardian_b_error: Exception | None = None,
) -> CertBitableReader:
    tables = {
        "special_op": ("appA", "tblA"),
        "guardian_a": ("appB", "tblB"),
        "guardian_b": ("appB", "tblC"),
    }
    clients: dict[str, Any] = {
        "special_op": FakePageClient(special_op or [], error=special_op_error),
        "guardian_a": FakePageClient(guardian_a or [], error=guardian_a_error),
        "guardian_b": FakePageClient(guardian_b or [], error=guardian_b_error),
    }
    return CertBitableReader(clients, tables=tables)


class TestGetAllActive:
    async def test_maps_three_kinds(self) -> None:
        reader = _make_reader(
            special_op=[_special_op_item("recS")],
            guardian_a=[_guardian_item("recA")],
            guardian_b=[_guardian_item("recB", "B证")],
        )
        views = await reader.get_all_active()
        by_id = {v.id: v for v in views}
        assert set(by_id) == {"recS", "recA", "recB"}
        assert by_id["recS"].cert_category == "special_op"
        assert by_id["recA"].cert_category == "guardian_a"
        assert by_id["recB"].cert_category == "guardian_b"
        assert by_id["recA"].feishu_record_id == "recA"

    async def test_no_name_record_skipped(self) -> None:
        """无姓名脏数据跳过（与镜像 upsert 行为一致）。"""
        reader = _make_reader(
            special_op=[_special_op_item("recOk"), _special_op_item("recBad", None)],
        )
        views = await reader.get_all_active()
        assert [v.id for v in views] == ["recOk"]

    async def test_strict_false_skips_failed_kind(self) -> None:
        reader = _make_reader(
            special_op=[_special_op_item("recS")],
            guardian_b_error=RuntimeError("boom"),
        )
        views = await reader.get_all_active(strict=False)
        assert [v.id for v in views] == ["recS"]

    async def test_strict_true_raises_with_failed_kinds(self) -> None:
        reader = _make_reader(
            special_op_error=RuntimeError("boom-a"),
            guardian_a_error=RuntimeError("boom-b"),
        )
        with pytest.raises(RuntimeError, match="special_op.*guardian_a"):
            await reader.get_all_active(strict=True)

    async def test_sorted_like_mirror(self) -> None:
        """reader 输出按镜像 repo 口径排序（cert_category ASC 打头）。"""
        reader = _make_reader(
            special_op=[_special_op_item("recS")],
            guardian_a=[_guardian_item("recA")],
            guardian_b=[_guardian_item("recB", "B证")],
        )
        views = await reader.get_all_active()
        # guardian_a < guardian_b < special_op（类别字典序）
        assert [v.id for v in views] == ["recA", "recB", "recS"]

    async def test_sorted_within_category_by_date(self) -> None:
        """同类别内按 next_review_date 升序（None 殿后，镜像口径）。"""
        from app.modules.safety.service.cert_direct.reader import sort_like_mirror

        ga_late = CertWarningView(
            id="ga-late", cert_category="guardian_a",
            next_review_date=date(2026, 6, 1),
        )
        ga_early = CertWarningView(
            id="ga-early", cert_category="guardian_a",
            next_review_date=date(2026, 1, 1),
        )
        ga_none = CertWarningView(id="ga-none", cert_category="guardian_a")
        assert sort_like_mirror([ga_late, ga_none, ga_early]) == [
            ga_early, ga_late, ga_none,
        ]
