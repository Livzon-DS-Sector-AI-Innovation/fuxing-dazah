"""台账导入必填字段过滤测试（无 DB、无网络）。"""

from app.modules.meter.service import _map_and_convert_rows

COLUMN_MAP = {
    "资产编号": "asset_number",
    "器具名称": "instrument_name",
    "出厂编号": "serial_number",
    "检定周期": "calibration_cycle_months",
}

REQUIRED = ("instrument_name", "asset_number", "serial_number")


def _sheet(rows: list[list]) -> list[dict]:
    return [{
        "name": "测试部门",
        "dept": "测试部门",
        "headers": ["资产编号", "器具名称", "出厂编号", "检定周期"],
        "rows": rows,
    }]


def test_required_fields_filter():
    rows = [
        ["ZC-001", "电子天平", "SN-001", 12],   # 完整 → 导入
        ["", "温湿度计", "SN-002", 12],          # 资产编号空 → 跳过
        ["ZC-003", "", "SN-003", 12],            # 名称空 → 跳过
        ["ZC-004", "pH计", "", 12],              # 出厂编号空 → 跳过
        ["ZC-005", "BOD仪", "SN-005", 12],       # 完整 → 导入
    ]
    mapped, warnings, _skipped = _map_and_convert_rows(
        _sheet(rows), COLUMN_MAP, use_sheet_name_as_dept=True,
        required_fields=REQUIRED,
    )
    assert [r["asset_number"] for r in mapped] == ["ZC-001", "ZC-005"]
    skip_msgs = [w["message"] for w in warnings if "已跳过" in w["message"]]
    assert len(skip_msgs) == 3


def test_no_required_fields_imports_all():
    rows = [["ZC-001", "电子天平", "SN-001", 12], ["", "", "", 12]]
    mapped, _, _skipped = _map_and_convert_rows(
        _sheet(rows), COLUMN_MAP, use_sheet_name_as_dept=True,
    )
    # 不传 required_fields 时保持旧行为：全部导入
    assert len(mapped) == 2
