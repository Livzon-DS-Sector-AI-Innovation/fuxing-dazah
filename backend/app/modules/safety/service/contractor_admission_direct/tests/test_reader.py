"""contractor_admission 直读读取器单测（Ticket 03）。

替身实现 BitablePageClient 协议全部方法（含 strict 参数，mypy 结构化检查口径）：
多页拉取、record_id 空跳过、strict 两态（False 返回已拉部分 / True 上抛）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableQueryError
from app.modules.safety.service.contractor_admission_direct.reader import (
    ContractorAdmissionBitableReader,
)
from app.modules.safety.service.contractor_admission_direct.views import (
    view_from_record_id,
)


class FakePageClient:
    """search_records 替身：按预设页序列返回；strict 仅透传记录（行为断言在底座）。"""

    def __init__(self, pages: list[list[dict[str, Any]]], fail_on_page: int | None = None):
        self._pages = pages
        self._fail_on_page = fail_on_page
        self.calls = 0

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
        self.calls += 1
        index = int(page_token) if page_token else 0
        if self._fail_on_page is not None and index == self._fail_on_page:
            raise BitableQueryError("fake search failure")
        items = self._pages[index]
        has_more = index + 1 < len(self._pages)
        return {
            "items": items,
            "has_more": has_more,
            "page_token": str(index + 1) if has_more else None,
            "total": sum(len(p) for p in self._pages),
        }


def _record(rid: str, company: str = "公司") -> dict[str, Any]:
    return {
        "record_id": rid,
        "fields": {
            "作业单位名称": [{"text": company, "type": "text"}],
            "相关方类型": "承包商",
            "AI审核结论": "审核通过",
        },
    }


class TestFetchAll:
    async def test_multi_page_and_mapping(self) -> None:
        client = FakePageClient([
            [_record("r1", "甲"), _record("r2", "乙")],
            [_record("r3", "丙")],
        ])
        reader = ContractorAdmissionBitableReader(client, table_id="tblX", page_size=2)
        views = await reader.fetch_all(strict=True)
        assert [v.id for v in views] == ["r1", "r2", "r3"]
        assert views[0].company_name == "甲"
        assert views[0].ai_review_status == "completed"
        assert views[0].feishu_table_id == "admission"
        assert client.calls == 2

    async def test_empty_record_id_skipped(self) -> None:
        client = FakePageClient([[_record("r1"), {"record_id": "", "fields": {}}]])
        views = await ContractorAdmissionBitableReader(client).fetch_all()
        assert [v.id for v in views] == ["r1"]

    async def test_strict_false_returns_partial_on_error(self) -> None:
        client = FakePageClient([[_record("r1")], [_record("r2")]], fail_on_page=1)
        views = await ContractorAdmissionBitableReader(client).fetch_all(strict=False)
        assert [v.id for v in views] == ["r1"]

    async def test_strict_true_raises_on_error(self) -> None:
        client = FakePageClient([[_record("r1")], [_record("r2")]], fail_on_page=1)
        with pytest.raises(BitableQueryError):
            await ContractorAdmissionBitableReader(client).fetch_all(strict=True)

    async def test_protocol_conformance(self) -> None:
        from app.modules.safety.service.contractor_admission_direct.reader import (
            ContractorAdmissionRecordsReader,
        )

        reader = ContractorAdmissionBitableReader(FakePageClient([[]]))
        assert isinstance(reader, ContractorAdmissionRecordsReader)


class TestViewFromRecordIdRaw:
    async def test_map_fields_none_defensive(self) -> None:
        """map_fields 返回 None（软删除信号占位）时视图降级为空业务字段。"""
        view = view_from_record_id("recZ", {})
        assert view.id == "recZ"
        assert view.company_name is None
        assert view.ai_review_status == "none"
