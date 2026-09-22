"""回写列契约单测（chemical_inventory-direct Ticket 02）。"""

from __future__ import annotations

from app.modules.safety.chemical_inventory.enum_maps import (
    _ALERT_TYPE_ENUM_TO_LABEL,
    _ALERT_TYPE_LABEL_TO_ENUM,
    _RISK_FLAG_ENUM_TO_LABEL,
    _RISK_FLAG_LABEL_TO_ENUM,
)
from app.modules.safety.service.chemical_inventory_direct.contract import (
    EXPECTED_BITABLE_FIELDS,
    RISK_FLAG_FIELD,
    RISK_FLAG_OPTIONS,
    RISK_NOTE_FIELD,
    RISK_NOTE_OPTIONS,
    WRITEBACK_FIELD_NAMES,
)


class TestWritebackContract:
    def test_writeback_fields_exactly_two(self) -> None:
        """写面只允许两个风险列（写请求键集合断言的基准）。"""
        assert WRITEBACK_FIELD_NAMES == {RISK_FLAG_FIELD, RISK_NOTE_FIELD}
        assert RISK_FLAG_FIELD == "风险标记"
        assert RISK_NOTE_FIELD == "风险说明"

    def test_options_match_enum_maps_labels(self) -> None:
        """契约选项与写出映射的标签全集一致（防映射漂移）。"""
        assert set(RISK_FLAG_OPTIONS) == set(_RISK_FLAG_LABEL_TO_ENUM)
        assert set(RISK_FLAG_OPTIONS) == set(_RISK_FLAG_ENUM_TO_LABEL.values())
        assert set(RISK_NOTE_OPTIONS) == set(_ALERT_TYPE_LABEL_TO_ENUM)
        assert set(RISK_NOTE_OPTIONS) == set(_ALERT_TYPE_ENUM_TO_LABEL.values())

    def test_write_out_labels(self) -> None:
        """写出映射口径抽查（探针实证生产表选项）。"""
        assert _RISK_FLAG_ENUM_TO_LABEL["normal"] == "正常"
        assert _RISK_FLAG_ENUM_TO_LABEL["warn"] == "预警"
        assert _ALERT_TYPE_ENUM_TO_LABEL["over_limit"] == "超量"
        assert _ALERT_TYPE_ENUM_TO_LABEL["unit_anomaly"] == "单位异常"

    def test_expected_fields_registry_keys(self) -> None:
        """字段契约 = registry 映射键集合（15 列，探针全在表）。"""
        from app.modules.safety.chemical_inventory.enum_maps import (
            INVENTORY_BITABLE_TO_MODEL,
        )

        assert set(EXPECTED_BITABLE_FIELDS) == set(INVENTORY_BITABLE_TO_MODEL)
