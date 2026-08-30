"""meter 模块 Pydantic schema 校验规则测试（从 API 契约角度）。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.meter.schemas import (
    BatchCreateRequest,
    BatchDeleteRequest,
    DateStatsResponse,
    DepartmentCreate,
    DepartmentUpdate,
    ExportReportRequest,
    FileMatchRequest,
    GasDetectorCreate,
    GasDetectorFilter,
    InstrumentCreate,
    InstrumentFilter,
    LedgerImportResult,
    MeterSettingsUpdate,
)


def _items(count: int) -> list[dict[str, Any]]:
    return [
        {"asset_number": f"A{i}", "instrument_name": "压力表", "department": "质量部"}
        for i in range(count)
    ]


class TestInstrumentCreate:
    def test_required_fields(self) -> None:
        """asset_number 与 instrument_name 为必填，缺失应报校验错误。"""
        with pytest.raises(ValidationError):
            InstrumentCreate.model_validate({})

    def test_asset_number_cannot_be_blank(self) -> None:
        """资产编号为空串应被 min_length 拒绝。"""
        with pytest.raises(ValidationError):
            InstrumentCreate.model_validate({"asset_number": "", "instrument_name": "压力表"})

    def test_calibration_cycle_months_at_least_1(self) -> None:
        """检定周期必须 ≥1 个月。"""
        with pytest.raises(ValidationError):
            InstrumentCreate.model_validate(
                {"asset_number": "A1", "instrument_name": "压力表", "calibration_cycle_months": 0}
            )

    def test_dates_parsed_as_date(self) -> None:
        """ISO 日期字符串应解析为 date 对象。"""
        obj = InstrumentCreate.model_validate(
            {
                "asset_number": "A1",
                "instrument_name": "压力表",
                "calibration_date": "2026-08-01",
                "next_calibration_date": "2027-08-01",
            }
        )
        assert obj.calibration_date == date(2026, 8, 1)
        assert obj.next_calibration_date == date(2027, 8, 1)


class TestGasDetectorCreate:
    def test_instrument_name_required(self) -> None:
        """探测器名称必填。"""
        with pytest.raises(ValidationError):
            GasDetectorCreate.model_validate({})

    def test_product_number_optional(self) -> None:
        """产品编号可选。"""
        obj = GasDetectorCreate(instrument_name="探测器")
        assert obj.product_number is None


class TestPageParams:
    def test_page_min_1(self) -> None:
        """页码从 1 开始。"""
        with pytest.raises(ValidationError):
            InstrumentFilter.model_validate({"page": 0})

    def test_page_size_capped_at_200(self) -> None:
        """单页条数上限 200。"""
        with pytest.raises(ValidationError):
            InstrumentFilter.model_validate({"page_size": 201})

    def test_defaults(self) -> None:
        """默认第 1 页、每页 20 条。"""
        f = InstrumentFilter()
        assert f.page == 1 and f.page_size == 20

    def test_gas_detector_filter_defaults(self) -> None:
        """探测器筛选同样继承分页默认值。"""
        f = GasDetectorFilter()
        assert f.page == 1 and f.page_size == 20


class TestBatchRequests:
    def test_batch_create_requires_items(self) -> None:
        """批量新增 items 不能为空。"""
        with pytest.raises(ValidationError):
            BatchCreateRequest.model_validate({"items": []})

    def test_batch_create_max_200(self) -> None:
        """批量新增单次最多 200 条。"""
        with pytest.raises(ValidationError):
            BatchCreateRequest.model_validate({"items": _items(201)})

    def test_batch_delete_requires_ids(self) -> None:
        """批量删除 ids 不能为空。"""
        with pytest.raises(ValidationError):
            BatchDeleteRequest.model_validate({"ids": []})

    def test_export_report_max_200(self) -> None:
        """批量导出报告单次最多 200 份。"""
        with pytest.raises(ValidationError):
            ExportReportRequest.model_validate({"ids": [str(i) for i in range(201)]})

    def test_file_match_max_200(self) -> None:
        """文件名批量匹配单次最多 200 个。"""
        with pytest.raises(ValidationError):
            FileMatchRequest.model_validate({"filenames": [f"f{i}.pdf" for i in range(201)]})


class TestDepartmentSchemas:
    def test_source_pattern(self) -> None:
        """部门 source 仅允许 instrument / gas_detector。"""
        with pytest.raises(ValidationError):
            DepartmentCreate.model_validate({"source": "other", "name": "部门A"})

    def test_name_required_non_blank(self) -> None:
        """部门名称不能为空串。"""
        with pytest.raises(ValidationError):
            DepartmentCreate.model_validate({"source": "instrument", "name": ""})

    def test_update_name_required(self) -> None:
        """更新部门时新名称必填（改名联动需要显式提供）。"""
        with pytest.raises(ValidationError):
            DepartmentUpdate.model_validate({"heads": [{"name": "张三"}]})


class TestMeterSettingsUpdate:
    def test_time_format_pattern(self) -> None:
        """提醒时间必须为 HH:MM。"""
        assert MeterSettingsUpdate(notify_time="17:45").notify_time == "17:45"

    def test_invalid_format_rejected(self) -> None:
        """非 HH:MM 格式应被 schema 拒绝。"""
        with pytest.raises(ValidationError):
            MeterSettingsUpdate.model_validate({"notify_time": "17点45"})

    def test_range_validation_left_to_service(self) -> None:
        """格式合法但数值越界（25:99）能通过 schema，由 service 层拒绝。"""
        assert MeterSettingsUpdate(notify_time="25:99").notify_time == "25:99"


class TestNestedResponses:
    def test_date_stats_response(self) -> None:
        """日期聚合响应应支持年→月→日嵌套结构。"""
        payload = {
            "field": "calibration_date",
            "years": [
                {"year": 2026, "count": 2, "months": [
                    {"month": 8, "count": 2, "days": [{"day": 1, "count": 2}]},
                ]},
            ],
        }
        resp = DateStatsResponse(**payload)
        assert resp.years[0].months[0].days[0].day == 1

    def test_ledger_import_result_warnings(self) -> None:
        """台账导入结果应包含 updated_count 与 warnings 结构。"""
        resp = LedgerImportResult.model_validate(
            {
                "deleted_count": 1,
                "imported_count": 2,
                "updated_count": 3,
                "sheet_count": 1,
                "sheet_details": [{"sheet_name": "Sheet1", "department": "质量部", "rows": 2}],
                "warnings": [
                    {
                        "sheet": "Sheet1",
                        "row": 5,
                        "type": "warning",
                        "message": "缺少字段: 位置",
                        "missing_fields": ["位置"],
                    }
                ],
            }
        )
        assert resp.updated_count == 3
        assert resp.warnings[0].missing_fields == ["位置"]
