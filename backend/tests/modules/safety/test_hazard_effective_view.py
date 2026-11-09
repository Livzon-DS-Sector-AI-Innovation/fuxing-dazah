"""T01 effective_* 视图与 API 契约单测（RED 先行）。

覆盖 spec S2：fake Bitable 记录 → HazardView 的 effective/source/mismatch；
人工分类/类别列（隐患分类/隐患类别）优先、AI fallback；台账 API 响应可读出。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.modules.safety.schemas.hazards import HazardReportResponse
from app.modules.safety.service import hazard_direct
from app.modules.safety.service.hazard_direct import bitable_repo


def _record(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        bitable_repo.F_NO: "HZ-20260101-001",
        bitable_repo.F_DESC: "人工隐患描述",
        bitable_repo.F_DATE: int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000),
        bitable_repo.F_RECTIFY_STATUS: "未关闭",
    }
    base.update(fields)
    return {"record_id": "rec001", "fields": base}


def test_effective_level_human_wins_with_mismatch() -> None:
    view = bitable_repo.to_view(
        _record(
            **{
                bitable_repo.F_LEVEL_MANUAL: ["较大隐患"],
                bitable_repo.F_LEVEL_AI: "一般隐患",
            }
        )
    )
    # 兼容字段：人工 raw 原样、AI 归一 EN
    assert view.hazard_level_manual == "较大隐患"
    assert view.hazard_level == "general"
    # 新口径
    assert view.effective_level == "serious"
    assert view.effective_level_source == "human"
    assert view.effective_level_mismatch is True


def test_effective_level_falls_back_to_ai() -> None:
    view = bitable_repo.to_view(
        _record(**{bitable_repo.F_LEVEL_AI: "重大隐患"})
    )
    assert view.effective_level == "major"
    assert view.effective_level_source == "ai"
    assert view.effective_level_mismatch is False


def test_effective_level_multi_select_takes_highest() -> None:
    view = bitable_repo.to_view(
        _record(**{bitable_repo.F_LEVEL_MANUAL: ["较大隐患", "一般隐患"]})
    )
    assert view.effective_level == "serious"
    assert view.effective_level_source == "human"


def test_effective_type_and_category_human_columns_are_read() -> None:
    view = bitable_repo.to_view(
        _record(
            **{
                bitable_repo.F_TYPE_MANUAL: "物的不安全状态",
                bitable_repo.F_TYPE_AI: "人的不安全行为",
                bitable_repo.F_CATEGORY_MANUAL: "设备设施",
                bitable_repo.F_CATEGORY_AI: "应急管理",
            }
        )
    )
    assert view.hazard_type_manual == "物的不安全状态"
    assert view.hazard_category_manual == "设备设施"
    assert view.effective_type == "unsafe_condition"
    assert view.effective_type_source == "human"
    assert view.effective_type_mismatch is True
    assert view.effective_category == "equipment"
    assert view.effective_category_source == "human"
    assert view.effective_category_mismatch is True
    # AI 原始值仍可读（前端 tooltip 用）
    assert view.hazard_type == "unsafe_action"
    assert view.hazard_category == "emergency_mgmt"


def test_effective_type_and_category_ai_fallback() -> None:
    view = bitable_repo.to_view(
        _record(
            **{
                bitable_repo.F_TYPE_AI: "管理的缺陷",
                bitable_repo.F_CATEGORY_AI: "设备设施",
            }
        )
    )
    assert view.effective_type == "management_defect"
    assert view.effective_type_source == "ai"
    assert view.effective_type_mismatch is False
    assert view.effective_category == "equipment"
    assert view.effective_category_source == "ai"


def test_effective_all_empty() -> None:
    view = bitable_repo.to_view(_record())
    assert view.effective_level is None
    assert view.effective_level_source is None
    assert view.effective_level_mismatch is False
    assert view.effective_type is None
    assert view.effective_category is None


def test_response_contract_exposes_effective_fields() -> None:
    view = bitable_repo.to_view(
        _record(
            **{
                bitable_repo.F_LEVEL_MANUAL: ["较大隐患"],
                bitable_repo.F_LEVEL_AI: "一般隐患",
                bitable_repo.F_TYPE_MANUAL: "物的不安全状态",
                bitable_repo.F_CATEGORY_MANUAL: "设备设施",
            }
        )
    )
    payload = HazardReportResponse.model_validate(view)
    dumped = payload.model_dump()
    assert dumped["effective_level"] == "serious"
    assert dumped["effective_level_source"] == "human"
    assert dumped["effective_level_mismatch"] is True
    assert dumped["effective_type"] == "unsafe_condition"
    assert dumped["effective_category"] == "equipment"


def test_response_effective_defaults_none_in_mirror_mode() -> None:
    """mirror/DB 路径无 effective 属性 → 响应默认 None，不炸。"""
    payload = HazardReportResponse(
        id="x",
        hazard_no="HZ-1",
        description="描述",
        rectification_status="closed",
        status="closed",
    )
    assert payload.effective_level is None
    assert payload.effective_level_source is None
    assert payload.effective_type is None
    assert payload.effective_category is None


def test_hazard_view_exported_from_package() -> None:
    """hazard_direct 包级导出保持可用（外部 import 不破坏）。"""
    assert hazard_direct.bitable_repo is bitable_repo


# ═══════════════════════════════════════════════════════════════
# 生产列名漂移护栏：人工「隐患分类/类别」全表读不到时告警一次（评审修复）
# ═══════════════════════════════════════════════════════════════


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _FakeListClient:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self._records = records

    async def list_all_records(self, **kwargs: object) -> list[dict[str, object]]:
        return self._records


def _reader_record(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "隐患编号": "HZ-20260101-001",
        "隐患描述": "人工隐患描述",
        "检查日期": 1767225600000,
    }
    base.update(fields)
    return {"record_id": "rec-r", "fields": base}


async def test_reader_warns_when_manual_type_category_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.hazard_direct import config as hazard_config
    from app.modules.safety.service.hazard_direct import reader as hazard_reader

    monkeypatch.setattr(hazard_reader, "_manual_column_warned", False)
    monkeypatch.setattr(hazard_config, "cache_ttl_seconds", lambda: 0)
    client = _FakeListClient(
        [
            _reader_record(
                **{
                    "隐患分类（AI）": "物的不安全状态",
                    "隐患类别（AI）": "设备设施",
                }
            )
        ]
    )
    cap = _LogCapture()
    hazard_reader.logger.addHandler(cap)
    try:
        views = await hazard_reader.CachedHazardReader(cast(Any, client)).fetch_all(strict=True)
    finally:
        hazard_reader.logger.removeHandler(cap)

    assert len(views) == 1
    warnings = [r for r in cap.records if r.levelno >= logging.WARNING]
    assert any("人工「隐患分类/隐患类别」列全表读取为空" in r.getMessage() for r in warnings)


async def test_reader_no_warning_when_manual_columns_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.hazard_direct import config as hazard_config
    from app.modules.safety.service.hazard_direct import reader as hazard_reader

    monkeypatch.setattr(hazard_reader, "_manual_column_warned", False)
    monkeypatch.setattr(hazard_config, "cache_ttl_seconds", lambda: 0)
    client = _FakeListClient(
        [_reader_record(**{"隐患分类": "物的不安全状态", "隐患类别": "设备设施"})]
    )
    cap = _LogCapture()
    hazard_reader.logger.addHandler(cap)
    try:
        await hazard_reader.CachedHazardReader(cast(Any, client)).fetch_all(strict=True)
    finally:
        hazard_reader.logger.removeHandler(cap)

    warnings = [r for r in cap.records if r.levelno >= logging.WARNING]
    assert not any("全表读取为空" in r.getMessage() for r in warnings)


def test_to_view_unmappable_manual_type_does_not_fall_back_to_ai() -> None:
    """人工分类选项无法归一 → effective_type 保持人工权威（None），不回退 AI。"""
    view = bitable_repo.to_view(
        _record(
            **{
                bitable_repo.F_TYPE_MANUAL: "未来新增分类",
                bitable_repo.F_TYPE_AI: "管理的缺陷",
            }
        )
    )
    assert view.effective_type is None
    assert view.effective_type_source == "human"
    assert view.effective_type_mismatch is False


def test_to_view_builds_ai_vs_manual_and_manual_raws() -> None:
    """P1-2/D3：to_view 装配 ai_vs_manual 三维差异 + 人工分类/类别原文（API 出参源）。"""
    view = bitable_repo.to_view(
        _record(
            **{
                bitable_repo.F_LEVEL_MANUAL: ["较大隐患"],
                bitable_repo.F_LEVEL_AI: "一般隐患",
                bitable_repo.F_TYPE_MANUAL: "管理的缺陷",
                bitable_repo.F_TYPE_AI: "物的不安全状态",
                bitable_repo.F_CATEGORY_AI: "设备设施",
            }
        )
    )
    assert view.hazard_type_manual == "管理的缺陷"
    assert view.hazard_category_manual is None
    assert view.ai_vs_manual == {
        "level": {
            "manual_raw": "较大隐患",
            "ai_raw": "一般隐患",
            "effective": "serious",
            "source": "human",
            "mismatch": True,
        },
        "type": {
            "manual_raw": "管理的缺陷",
            "ai_raw": "物的不安全状态",
            "effective": "management_defect",
            "source": "human",
            "mismatch": True,
        },
        "category": {
            "manual_raw": None,
            "ai_raw": "设备设施",
            "effective": "equipment",
            "source": "ai",
            "mismatch": False,
        },
    }
    # API 契约：Response 可从 view 读出三字段（from_attributes）
    resp = HazardReportResponse.model_validate(view)
    assert resp.ai_vs_manual == view.ai_vs_manual
    assert resp.hazard_type_manual == "管理的缺陷"
    assert resp.hazard_category_manual is None
