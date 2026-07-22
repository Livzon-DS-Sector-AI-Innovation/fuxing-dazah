"""Departure (老厂离职) Bitable datasource adapter.

Adapts Feishu Bitable API quirks for the departure table:
- Text fields read as [{"text": ..., "type": "text"}] but write as plain strings
- Date fields require millisecond timestamps
- Multi-select fields for offboarding reasons
"""

import logging
from datetime import date, datetime
from typing import Any

from app.core.config import get_settings
from app.modules.hr.feishu.bitable import BitableClient, _to_ms_timestamp

logger = logging.getLogger(__name__)
_settings = get_settings()


def _extract_text(value: Any) -> str:
    """Extract plain text from Feishu text-field array format."""
    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
        return value[0].get("text", "")
    if isinstance(value, dict) and "text" in value:
        return value.get("text", "")
    if isinstance(value, str):
        return value
    return str(value) if value is not None else ""


def _extract_number(value: Any) -> int | float | None:
    """Extract number from Feishu number/array format."""
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict) and "value" in value:
        v = value["value"]
        if isinstance(v, list) and len(v) > 0:
            return v[0]
    if isinstance(value, list) and len(value) > 0:
        return value[0]
    return None


def _extract_multi_select(value: Any) -> list[str]:
    """Extract multi-select options."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    return [str(value)]


def _ms_to_date(value: Any) -> date | None:
    """Convert Feishu millisecond timestamp to Python date."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    return None


class DepartureBitableDataSource:
    """Departure (老厂离职) datasource backed by Feishu Bitable."""

    def __init__(self) -> None:
        self.client = BitableClient()
        self.client.app_token = _settings.HR_BITABLE_APP_TOKEN or "KHLsboPBGaah6Vs3EpgcpvzsnuH"
        self.table_id = _settings.HR_BITABLE_DEPARTURE_TABLE_ID or "tblvHabV24ccEqcu"

    def _is_enabled(self) -> bool:
        return bool(self.client.app_token and self.table_id)

    async def _search(
        self,
        *,
        filter_str: str | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        if not self._is_enabled():
            raise RuntimeError("Bitable not configured")
        return await self.client.search_records(
            self.table_id,
            filter_str=filter_str,
            page_size=page_size,
        )

    async def query(
        self,
        *,
        department: str | None = None,
        page_size: int = 500,
    ) -> list["DepartureRecord"]:
        filters: list[str] = []
        if department:
            filters.append(f'CurrentValue.[部门] = "{department}"')

        filter_str = " AND ".join(filters) if filters else None
        items = await self._search(filter_str=filter_str, page_size=page_size)
        return [DepartureRecord.from_api(item) for item in items]

    async def create(self, data: dict[str, Any]) -> str:
        fields = self._prepare_write_fields(data)
        record = await self.client.create_record(self.table_id, fields)
        return record.get("record_id", "")

    async def update(self, record_id: str, data: dict[str, Any]) -> None:
        fields = self._prepare_write_fields(data)
        if fields:
            await self.client.update_record(self.table_id, record_id, fields)

    def _prepare_write_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Python types to Feishu API format."""
        prepared: dict[str, Any] = {}
        for key, value in data.items():
            if value is None:
                continue
            if key in {"离职日期", "进厂时间", "入丽珠时间", "参加工作时间"}:
                prepared[key] = _to_ms_timestamp(value)
            else:
                prepared[key] = value
        return prepared


class DepartureRecord:
    """Parsed departure record from Bitable API."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.record_id: str = raw.get("record_id", "")
        fields = raw.get("fields", {})

        # Basic info
        self.name: str = _extract_text(fields.get("姓名"))
        self.department: str = _extract_text(fields.get("部门"))
        self.team: str = _extract_text(fields.get("班组"))
        self.position: str = _extract_text(fields.get("职位"))
        self.job_category: str = _extract_text(fields.get("职类"))
        self.gender: str = fields.get("性别", "")
        self.status_category: str = _extract_text(fields.get("统计类别"))

        # Dates
        self._livo_entry_date = fields.get("入丽珠时间")
        self._factory_entry_date = fields.get("进厂时间")
        self._work_start_date = fields.get("参加工作时间")
        self._offboarding_date = fields.get("离职日期")
        self.company_tenure_at_leave: str = _extract_text(fields.get("离职时司龄"))

        # Education
        self.education: str = _extract_text(fields.get("学历"))
        self.school: str = _extract_text(fields.get("毕业学校"))
        self.major: str = _extract_text(fields.get("专业"))
        self.classification: str = fields.get("分类", "")

        # Personal
        self.id_card: str = _extract_text(fields.get("身份证号"))
        self.native_place: str = _extract_text(fields.get("籍贯"))
        self.household_type: str = fields.get("户籍类型", "")
        self.marital_status: str = fields.get("婚姻状况", "")
        self.political_status: str = fields.get("政治面貌", "")

        # Contact
        self.phone: str = _extract_text(fields.get("手机"))
        self.emergency_contact_phone: str = _extract_text(fields.get("紧急联系人电话"))
        self.emergency_contact_relation: str = _extract_text(fields.get("紧急联系人|关系"))
        self.bank_account: str = _extract_text(fields.get("银行卡号"))

        # Contract
        self.contract_type: str = fields.get("合同期限", "")

        # Work history
        self.transfer_history: str = _extract_text(fields.get("异动(含曾经工作部门、岗位)"))

        # Offboarding specific
        self.offboarding_type: str = _extract_text(fields.get("离职类型"))
        self.offboarding_reason: list[str] = _extract_multi_select(fields.get("离职原因"))
        self.offboarding_reason_2: list[str] = _extract_multi_select(fields.get("离职原因2"))
        self.offboarding_remarks: list[str] = _extract_multi_select(fields.get("离职备注"))

        # Other
        self.remarks: str = _extract_text(fields.get("备注"))

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "DepartureRecord":
        return cls(raw)

    @property
    def livo_entry_date(self) -> date | None:
        return _ms_to_date(self._livo_entry_date)

    @property
    def factory_entry_date(self) -> date | None:
        return _ms_to_date(self._factory_entry_date)

    @property
    def work_start_date(self) -> date | None:
        return _ms_to_date(self._work_start_date)

    @property
    def offboarding_date(self) -> date | None:
        return _ms_to_date(self._offboarding_date)

    def to_dict(self) -> dict[str, Any]:
        """Export to plain dict suitable for local DB storage."""
        return {
            "feishu_record_id": self.record_id,
            "name": self.name,
            "department": self.department,
            "team": self.team,
            "position": self.position,
            "job_category": self.job_category,
            "gender": self.gender,
            "status_category": self.status_category,
            "livo_entry_date": self.livo_entry_date,
            "factory_entry_date": self.factory_entry_date,
            "work_start_date": self.work_start_date,
            "offboarding_date": self.offboarding_date,
            "company_tenure_at_leave": self.company_tenure_at_leave,
            "education": self.education,
            "school": self.school,
            "major": self.major,
            "classification": self.classification,
            "id_card": self.id_card,
            "native_place": self.native_place,
            "household_type": self.household_type,
            "marital_status": self.marital_status,
            "political_status": self.political_status,
            "phone": self.phone,
            "emergency_contact_phone": self.emergency_contact_phone,
            "emergency_contact_relation": self.emergency_contact_relation,
            "bank_account": self.bank_account,
            "contract_type": self.contract_type,
            "transfer_history": self.transfer_history,
            "offboarding_type": self.offboarding_type,
            "offboarding_reason": self.offboarding_reason,
            "offboarding_reason_2": self.offboarding_reason_2,
            "offboarding_remarks": self.offboarding_remarks,
            "remarks": self.remarks,
        }
