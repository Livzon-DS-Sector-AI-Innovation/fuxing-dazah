"""contractor_admission 变更检测触发器单测（Ticket 04）。

覆盖：候选判定（协议挂载/派生态/新行/diff/可收敛键集 M-1）、附件 file_token
稳定键、并发上限与 in-flight 去重、后台任务完成/异常后的 in-flight 清理。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.contractor_admission_direct import trigger
from app.modules.safety.service.contractor_admission_direct.views import (
    ContractorAdmissionView,
    mapped_field_keys,
    view_from_record_id,
)


def _view(vid: str, *, agreement: bool = True, completed: bool = False) -> ContractorAdmissionView:
    view = view_from_record_id(vid, {
        "作业单位名称": [{"text": f"公司{vid}", "type": "text"}],
        "相关方类型": "承包商",
        "AI审核结论": ("审核通过" if completed else None),
    })
    if agreement:
        view.safety_agreement_files = [{"file_token": f"tok_{vid}", "name": "协议.pdf"}]
    return view


def _row_like(view: ContractorAdmissionView) -> Any:
    """平台行替身：与视图同值（镜像行 getattr 同构）。"""
    return FakeRow({k: getattr(view, k) for k in mapped_field_keys()})


class FakeRow:
    """平台行替身：按属性名取值（与 ORM 行 getattr 同构）。"""

    def __init__(self, values: dict[str, Any]):
        self.__dict__.update(values)


class TestDetectCandidates:
    def test_new_record_with_agreement_is_candidate(self) -> None:
        rows = trigger.detect_candidates([_view("r1")], {})
        assert [rid for rid, _ in rows] == ["r1"]

    def test_no_agreement_skipped(self) -> None:
        assert trigger.detect_candidates([_view("r1", agreement=False)], {}) == []

    def test_completed_skipped(self) -> None:
        assert trigger.detect_candidates([_view("r1", completed=True)], {}) == []

    def test_unchanged_row_skipped(self) -> None:
        view = _view("r1")
        assert trigger.detect_candidates([view], {"r1": _row_like(view)}) == []

    def test_edited_row_is_candidate(self) -> None:
        view = _view("r1")
        row = _row_like(view)
        row.company_name = "改过的名字"
        rows = trigger.detect_candidates([view], {"r1": row})
        assert [rid for rid, _ in rows] == ["r1"]

    def test_stale_none_vs_old_value_converges_not_candidate(self) -> None:
        """审查 M-1：视图 None / 行残留旧值的键 upsert 改不动，diff 不计入——
        否则 WRITEBACK_AI 关时派生态恒 none，每查询周期重复触发审核。"""
        view = _view("r1")
        view.notes = None
        row = _row_like(view)
        row.notes = "镜像残留的旧备注"
        assert trigger.detect_candidates([view], {"r1": row}) == []

    def test_stale_key_plus_other_change_still_candidate(self) -> None:
        """残留键不计入 diff，但其他键的变更照常触发。"""
        view = _view("r1")
        view.notes = None
        row = _row_like(view)
        row.notes = "镜像残留的旧备注"
        row.company_name = "改过的名字"
        rows = trigger.detect_candidates([view], {"r1": row})
        assert [rid for rid, _ in rows] == ["r1"]

    def test_candidate_values_carry_mapped_snapshot(self) -> None:
        rows = trigger.detect_candidates([_view("r1")], {})
        values = rows[0][1]
        assert values["company_name"] == "公司r1"
        assert "ai_review_status" not in values  # 派生态不进 upsert


class TestFireAndForget:
    @pytest.fixture(autouse=True)
    def _clean_inflight(self) -> None:
        trigger._inflight.clear()

    async def _noop_review(self, record_id: str, values: dict[str, Any]) -> None:
        return None

    async def test_bounded_by_max_inflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        monkeypatch.setattr(trigger, "_MAX_INFLIGHT", 2)
        monkeypatch.setattr(trigger, "_run_review", self._noop_review)
        candidates = [(f"r{i}", {}) for i in range(5)]
        launched = trigger.fire_and_forget(candidates)
        await asyncio.sleep(0)  # 让被替身的任务跑完
        assert launched == 2
        assert trigger.inflight_count() == 2

    async def test_skip_already_inflight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        monkeypatch.setattr(trigger, "_MAX_INFLIGHT", 5)
        monkeypatch.setattr(trigger, "_run_review", self._noop_review)
        trigger._inflight.add("r1")
        launched = trigger.fire_and_forget([("r1", {}), ("r2", {})])
        await asyncio.sleep(0)
        assert launched == 1
        assert trigger.inflight_count() == 2

    async def test_run_review_success_clears_inflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str]] = []

        class FakeService:
            def __init__(self, session: Any) -> None:
                pass

            async def upsert_from_bitable(
                self, mapped: dict[str, Any], record_id: str, table_kind: str
            ) -> Any:
                calls.append(("upsert", record_id))
                return FakeRow({"id": "uuid-1", "feishu_record_id": record_id})

            async def run_admission_review(self, admission_id: Any, channel: str) -> Any:
                calls.append(("review", channel))
                return None

        import app.modules.safety.service.contractor_admission as service_pkg

        class FakeSessionFactory:
            def __call__(self) -> Any:
                return self

            async def __aenter__(self) -> Any:
                return object()

            async def __aexit__(self, *exc: Any) -> None:
                return None

        monkeypatch.setattr(service_pkg, "ContractorAdmissionService", FakeService)
        monkeypatch.setattr(
            "app.core.database.async_session_factory", FakeSessionFactory()
        )
        trigger._inflight.add("r1")
        await trigger._run_review("r1", {"company_name": "x"})
        assert calls == [("upsert", "r1"), ("review", "system")]
        assert trigger.inflight_count() == 0

    async def test_run_review_exception_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeService:
            def __init__(self, session: Any) -> None:
                pass

            async def upsert_from_bitable(
                self, mapped: dict[str, Any], record_id: str, table_kind: str
            ) -> Any:
                raise RuntimeError("db down")

        import app.modules.safety.service.contractor_admission as service_pkg

        class FakeSessionFactory:
            def __call__(self) -> Any:
                return self

            async def __aenter__(self) -> Any:
                return object()

            async def __aexit__(self, *exc: Any) -> None:
                return None

        monkeypatch.setattr(service_pkg, "ContractorAdmissionService", FakeService)
        monkeypatch.setattr(
            "app.core.database.async_session_factory", FakeSessionFactory()
        )
        trigger._inflight.add("r1")
        await trigger._run_review("r1", {})  # 不抛
        assert trigger.inflight_count() == 0
