"""Meter 业务层（service）。

按业务域拆分为子模块，此处统一 re-export 对外符号，
保持 ``from app.modules.meter import service`` 后属性访问（``service.xxx``）不变。
"""

from app.modules.meter.service.common import (
    MODULE_CODE,
    _auto_calc_next_calibration_date,
    compute_status,
)
from app.modules.meter.service.departments import (
    create_department,
    delete_department,
    get_personnel_candidates,
    list_departments,
    update_department,
)
from app.modules.meter.service.gas_detectors import (
    batch_create_gas_detectors,
    batch_delete_gas_detectors,
    create_gas_detector,
    delete_gas_detector,
    get_all_gas_detector_ids,
    get_gas_detector,
    get_gas_detector_departments,
    get_gas_detector_filter_options,
    list_gas_detectors,
    update_gas_detector,
)
from app.modules.meter.service.instruments import (
    batch_create_instruments,
    batch_delete_instruments,
    create_instrument,
    delete_instrument,
    get_all_instrument_ids,
    get_instrument,
    get_instrument_departments,
    get_instrument_filter_options,
    list_instruments,
    update_instrument,
)
from app.modules.meter.service.ledger_import import (
    import_gas_detector_ledger,
    import_instrument_ledger,
)
from app.modules.meter.service.ledger_parsing import (
    GAS_DETECTOR_COLUMN_MAP,
    INSTRUMENT_COLUMN_MAP,
    _excel_serial_to_date,
    _map_and_convert_rows,
    _normalize_header,
    _parse_department,
)
from app.modules.meter.service.reminder_notify import send_calibration_reminders
from app.modules.meter.service.reminders import (
    _build_date_stats_tree,
    get_calibration_alerts,
    get_gas_detector_date_stats,
    get_instrument_date_stats,
    get_meter_overview,
)
from app.modules.meter.service.report_matching import (
    _parse_filename,
    analyze_report_files,
    batch_upload_reports,
    match_filenames,
    match_one,
)
from app.modules.meter.service.reports import (
    delete_report,
    download_report_data,
    export_gas_detector_reports,
    export_instrument_reports,
    get_report,
    list_gas_detector_reports,
    list_instrument_reports,
    update_report_certificate_no,
    upload_report,
)
from app.modules.meter.service.settings import get_meter_settings, update_meter_settings

__all__ = [
    "MODULE_CODE",
    "_auto_calc_next_calibration_date",
    "_build_date_stats_tree",
    "_excel_serial_to_date",
    "_map_and_convert_rows",
    "_normalize_header",
    "_parse_department",
    "_parse_filename",
    "GAS_DETECTOR_COLUMN_MAP",
    "INSTRUMENT_COLUMN_MAP",
    "analyze_report_files",
    "batch_create_gas_detectors",
    "batch_create_instruments",
    "batch_delete_gas_detectors",
    "batch_delete_instruments",
    "batch_upload_reports",
    "compute_status",
    "create_department",
    "create_gas_detector",
    "create_instrument",
    "delete_department",
    "delete_gas_detector",
    "delete_instrument",
    "delete_report",
    "download_report_data",
    "export_gas_detector_reports",
    "export_instrument_reports",
    "get_all_gas_detector_ids",
    "get_all_instrument_ids",
    "get_calibration_alerts",
    "get_gas_detector",
    "get_gas_detector_date_stats",
    "get_gas_detector_departments",
    "get_gas_detector_filter_options",
    "get_instrument",
    "get_instrument_date_stats",
    "get_instrument_departments",
    "get_instrument_filter_options",
    "get_meter_overview",
    "get_meter_settings",
    "get_personnel_candidates",
    "get_report",
    "import_gas_detector_ledger",
    "import_instrument_ledger",
    "list_departments",
    "list_gas_detector_reports",
    "list_gas_detectors",
    "list_instrument_reports",
    "list_instruments",
    "match_filenames",
    "match_one",
    "send_calibration_reminders",
    "update_department",
    "update_gas_detector",
    "update_instrument",
    "update_meter_settings",
    "update_report_certificate_no",
    "upload_report",
]
