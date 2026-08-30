"""Meter Pydantic schema 契约。

按业务域拆分为子模块，此处统一 re-export，
保持 ``from app.modules.meter.schemas import X`` 全部既有导入路径不变。
"""

from app.modules.meter.schemas.common import (
    BatchDeleteRequest,
    ExportReportRequest,
    NormalizedDepartment,
    StrUUID,
    _normalize_department,
)
from app.modules.meter.schemas.departments import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    PersonnelCandidate,
)
from app.modules.meter.schemas.gas_detectors import (
    GasDetectorBatchCreateItem,
    GasDetectorBatchCreateRequest,
    GasDetectorCreate,
    GasDetectorFilter,
    GasDetectorFilterOptions,
    GasDetectorListResponse,
    GasDetectorResponse,
    GasDetectorUpdate,
)
from app.modules.meter.schemas.instruments import (
    BatchCreateItem,
    BatchCreateRequest,
    BatchCreateResult,
    BatchCreateRowResult,
    InstrumentCreate,
    InstrumentFilter,
    InstrumentFilterOptions,
    InstrumentListResponse,
    InstrumentResponse,
    InstrumentUpdate,
)
from app.modules.meter.schemas.ledger import (
    LedgerImportError,
    LedgerImportResult,
    LedgerImportSheetDetail,
)
from app.modules.meter.schemas.reports import (
    BatchUploadItem,
    BatchUploadRequest,
    BatchUploadResult,
    FileMatchItem,
    FileMatchRequest,
    ReportAnalyzeItem,
    ReportCreate,
    ReportFieldExtraction,
    ReportItem,
    ReportMatchCandidate,
    ReportResponse,
    UpdateReportRequest,
)
from app.modules.meter.schemas.settings import (
    MeterSettingsResponse,
    MeterSettingsUpdate,
)
from app.modules.meter.schemas.stats import (
    CalibrationAlertResponse,
    DateStatDay,
    DateStatMonth,
    DateStatsResponse,
    DateStatYear,
    ExtractDateResponse,
    MeterOverviewResponse,
)

__all__ = [
    "BatchCreateItem",
    "BatchCreateRequest",
    "BatchCreateResult",
    "BatchCreateRowResult",
    "BatchDeleteRequest",
    "BatchUploadItem",
    "BatchUploadRequest",
    "BatchUploadResult",
    "CalibrationAlertResponse",
    "DateStatDay",
    "DateStatMonth",
    "DateStatYear",
    "DateStatsResponse",
    "DepartmentCreate",
    "DepartmentResponse",
    "DepartmentUpdate",
    "ExportReportRequest",
    "ExtractDateResponse",
    "FileMatchItem",
    "FileMatchRequest",
    "GasDetectorBatchCreateItem",
    "GasDetectorBatchCreateRequest",
    "GasDetectorCreate",
    "GasDetectorFilter",
    "GasDetectorFilterOptions",
    "GasDetectorListResponse",
    "GasDetectorResponse",
    "GasDetectorUpdate",
    "InstrumentCreate",
    "InstrumentFilter",
    "InstrumentFilterOptions",
    "InstrumentListResponse",
    "InstrumentResponse",
    "InstrumentUpdate",
    "LedgerImportError",
    "LedgerImportResult",
    "LedgerImportSheetDetail",
    "MeterOverviewResponse",
    "MeterSettingsResponse",
    "MeterSettingsUpdate",
    "NormalizedDepartment",
    "PersonnelCandidate",
    "ReportAnalyzeItem",
    "ReportCreate",
    "ReportFieldExtraction",
    "ReportItem",
    "ReportMatchCandidate",
    "ReportResponse",
    "StrUUID",
    "UpdateReportRequest",
    "_normalize_department",
]
