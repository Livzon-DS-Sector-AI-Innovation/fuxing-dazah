"""Onboarding (老厂入职) Bitable datasource adapter.

Adapts Feishu Bitable API quirks for the onboarding table:
- Text fields read as [{"text": ..., "type": "text"}] but write as plain strings
- Formula fields (age, tenure, etc.) are read-only
- Phone fields use type=13 (phone_v2)
- Date fields require millisecond timestamps
- Duplicate education fields: 毕业学校 (1) / 学历 (1) / 专业 (1) take priority
- Email is returned as URL object {"type": "url", "text": "...", "link": "mailto:..."}
"""

import logging
from datetime import date, datetime
from typing import Any

from app.core.config import get_settings
from app.modules.hr.feishu.bitable import BitableClient, _to_ms_timestamp

logger = logging.getLogger(__name__)
_settings = get_settings()

# ─── Read-only formula fields ───
FORMULA_FIELDS = {"年龄", "工作年限", "厂龄", "司龄", "入职月份", "字段 1"}


def _extract_text(value: Any) -> str:
    """Extract plain text from Feishu text-field array format.

    Handles:
    - [{"text": "...", "type": "text"}] → "..."
    - {"text": "..."} → "..."
    - {"type": 1, "value": [{"text": "...", "type": "text"}]} → "..."
    - {"type": 2, "value": [123]} → "123"
    """
    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
        return value[0].get("text", "")
    if isinstance(value, dict):
        if "text" in value:
            return value.get("text", "")
        if "value" in value and isinstance(value["value"], list) and len(value["value"]) > 0:
            inner = value["value"][0]
            if isinstance(inner, dict) and "text" in inner:
                return inner.get("text", "")
            return str(inner)
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


def _extract_email(value: Any) -> str:
    """Extract email from Feishu URL format."""
    if isinstance(value, dict):
        if "text" in value:
            return value["text"]
        if "link" in value:
            link = value["link"]
            if isinstance(link, str) and link.startswith("mailto:"):
                return link[7:]
    return _extract_text(value)


def _ms_to_date(value: Any) -> date | None:
    """Convert Feishu millisecond timestamp to Python date."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    return None


class OnboardingBitableDataSource:
    """Onboarding (老厂入职) datasource backed by Feishu Bitable."""

    def __init__(self) -> None:
        self.client = BitableClient()
        self.client.app_token = _settings.HR_BITABLE_APP_TOKEN or "KHLsboPBGaah6Vs3EpgcpvzsnuH"
        self.table_id = _settings.HR_BITABLE_ONBOARDING_TABLE_ID or "tblb7CpwKUW25ONC"

    def _is_enabled(self) -> bool:
        return bool(self.client.app_token and self.table_id)

    # ─── Internal raw API ───

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

    async def _create(self, fields: dict[str, Any]) -> str:
        record = await self.client.create_record(self.table_id, fields)
        return record.get("record_id", "")

    async def _update(self, record_id: str, fields: dict[str, Any]) -> None:
        await self.client.update_record(self.table_id, record_id, fields)

    # ─── Public query API ───

    async def query(
        self,
        *,
        department: str | None = None,
        page_size: int = 500,
    ) -> list["OnboardingRecord"]:
        filters: list[str] = []
        if department:
            filters.append(f'CurrentValue.[部门] = "{department}"')

        filter_str = " AND ".join(filters) if filters else None
        items = await self._search(filter_str=filter_str, page_size=page_size)
        return [OnboardingRecord.from_api(item) for item in items]

    async def find_by_employee_number(self, employee_number: str) -> "OnboardingRecord | None":
        items = await self._search(
            filter_str=f'CurrentValue.[工号] = "{employee_number}"'
        )
        if not items:
            return None
        return OnboardingRecord.from_api(items[0])

    # ─── Write API ───

    async def create(self, data: dict[str, Any]) -> str:
        fields = self._prepare_write_fields(data)
        rid = await self._create(fields)
        logger.info("Onboarding record created in Bitable: %s", rid)
        return rid

    async def update(self, record_id: str, data: dict[str, Any]) -> None:
        fields = self._prepare_write_fields(data)
        if fields:
            await self._update(record_id, fields)
            logger.info("Onboarding record updated in Bitable: %s", record_id)

    # ─── Field preparation ───

    def _prepare_write_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Python types to Feishu API format and strip read-only fields."""
        prepared: dict[str, Any] = {}
        for key, value in data.items():
            if key in FORMULA_FIELDS:
                continue
            if value is None:
                continue
            if key in {
                "入职时间", "进厂时间", "入丽珠时间", "参加工作时间", "毕业时间",
                "第一次合同起点时间", "第一次合同终止时间",
                "第二次合同起点时间", "第二次合同终止时间",
                "第三次合同起点时间", "第三次合同终止时间",
                "第四次合同起点时间", "第四次合同终止时间",
            }:
                prepared[key] = _to_ms_timestamp(value)
            else:
                prepared[key] = value
        return prepared


class OnboardingRecord:
    """Parsed onboarding record from Bitable API."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.record_id: str = raw.get("record_id", "")
        fields = raw.get("fields", {})

        # Identifiers
        self.seq_number: int | None = _extract_number(fields.get("编号"))
        self.employee_number: str = _extract_text(fields.get("工号"))
        self.name: str = _extract_text(fields.get("姓名"))
        self.domain_account: str = _extract_text(fields.get("域账号"))

        # Organization
        self.department: str = fields.get("部门", "")
        self.team: str = _extract_text(fields.get("班组"))
        self.position: str = _extract_text(fields.get("岗位"))
        self.job_category: str = fields.get("职类", "")
        self.status_category: str = fields.get("统计类别", "")

        # Employment status
        self.is_employed: str = fields.get("是否在职", "")

        # Dates (raw ms timestamps)
        self._hire_date = fields.get("入职时间")
        self._factory_entry_date = fields.get("进厂时间")
        self._livo_entry_date = fields.get("入丽珠时间")
        self._work_start_date = fields.get("参加工作时间")
        self._graduation_date = fields.get("毕业时间")
        self.birth_month: int | None = _extract_number(fields.get("月"))
        self.birth_day: int | None = _extract_number(fields.get("日"))

        # Contract
        self.contract_type: str = fields.get("合同期限", "")
        self._contract_start_date = fields.get("第一次合同起点时间")
        self._contract_end_date = fields.get("第一次合同终止时间")
        self._contract_start_2 = fields.get("第二次合同起点时间")
        self._contract_end_2 = fields.get("第二次合同终止时间")
        self._contract_start_3 = fields.get("第三次合同起点时间")
        self._contract_end_3 = fields.get("第三次合同终止时间")
        self._contract_start_4 = fields.get("第四次合同起点时间")
        self._contract_end_4 = fields.get("第四次合同终止时间")

        # Formula / computed (read-only)
        self.age = _extract_number(fields.get("年龄"))
        self.work_years = _extract_number(fields.get("工作年限"))
        self.factory_tenure = _extract_text(fields.get("厂龄"))
        self.company_tenure = _extract_text(fields.get("司龄"))
        self.hire_month = _extract_text(fields.get("入职月份"))

        # Education (prefer (1) fields, fallback to base fields)
        school_1 = _extract_text(fields.get("毕业学校 (1)"))
        self.school: str = school_1 if school_1 else _extract_text(fields.get("毕业学校"))
        edu_1 = fields.get("学历 (1)")
        self.education: str = edu_1 if edu_1 else (fields.get("学历") or "")
        major_1 = _extract_text(fields.get("专业 (1)"))
        self.major: str = major_1 if major_1 else _extract_text(fields.get("专业"))
        self.classification: str = fields.get("分类", "")

        # Personal
        self.id_card: str = _extract_text(fields.get("身份证号"))
        self.id_card_expiry: str = _extract_text(fields.get("身份证到期日"))
        self.id_card_address: str = _extract_text(fields.get("身份证地址|家庭地址"))
        self.current_address: str = _extract_text(fields.get("现住址"))
        self.marital_status: str = fields.get("婚姻状况", "")
        self.household_type: str = fields.get("户籍类型", "")
        self.political_status: str = fields.get("政治面貌", "")

        # Contact
        self.phone: str = _extract_text(fields.get("手机"))
        self.email: str = _extract_email(fields.get("邮箱地址"))
        self.emergency_contact_phone: str = _extract_text(fields.get("紧急联系人电话"))
        self.emergency_contact_relation: str = _extract_text(fields.get("紧急联系人|关系"))

        # Banking
        self.bank_account: str = _extract_text(fields.get("银行卡号"))
        self.bank_account_location: str = fields.get("银行卡开户地", "")

        # Other
        self.training_id: str = _extract_text(fields.get("培训档案编号"))
        self.transfer_history: str = _extract_text(fields.get("异动（含曾经工作部门、岗位)"))
        self.remarks: list[str] = _extract_multi_select(fields.get("备注"))

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "OnboardingRecord":
        return cls(raw)

    @property
    def hire_date(self) -> date | None:
        return _ms_to_date(self._hire_date)

    @property
    def factory_entry_date(self) -> date | None:
        return _ms_to_date(self._factory_entry_date)

    @property
    def livo_entry_date(self) -> date | None:
        return _ms_to_date(self._livo_entry_date)

    @property
    def work_start_date(self) -> date | None:
        return _ms_to_date(self._work_start_date)

    @property
    def graduation_date(self) -> date | None:
        return _ms_to_date(self._graduation_date)

    @property
    def contract_start_date(self) -> date | None:
        return _ms_to_date(self._contract_start_date)

    @property
    def contract_end_date(self) -> date | None:
        return _ms_to_date(self._contract_end_date)

    @property
    def contract_start_2(self) -> date | None:
        return _ms_to_date(self._contract_start_2)

    @property
    def contract_end_2(self) -> date | None:
        return _ms_to_date(self._contract_end_2)

    @property
    def contract_start_3(self) -> date | None:
        return _ms_to_date(self._contract_start_3)

    @property
    def contract_end_3(self) -> date | None:
        return _ms_to_date(self._contract_end_3)

    @property
    def contract_start_4(self) -> date | None:
        return _ms_to_date(self._contract_start_4)

    @property
    def contract_end_4(self) -> date | None:
        return _ms_to_date(self._contract_end_4)

    def to_dict(self) -> dict[str, Any]:
        """Export to plain dict suitable for local DB storage."""
        return {
            "feishu_record_id": self.record_id,
            "seq_number": self.seq_number,
            "employee_number": self.employee_number,
            "name": self.name,
            "domain_account": self.domain_account,
            "department": self.department,
            "team": self.team,
            "position": self.position,
            "job_category": self.job_category,
            "status_category": self.status_category,
            "is_employed": self.is_employed,
            "hire_date": self.hire_date,
            "factory_entry_date": self.factory_entry_date,
            "livo_entry_date": self.livo_entry_date,
            "work_start_date": self.work_start_date,
            "graduation_date": self.graduation_date,
            "birth_month": self.birth_month,
            "birth_day": self.birth_day,
            "contract_type": self.contract_type,
            "contract_start_date": self.contract_start_date,
            "contract_end_date": self.contract_end_date,
            "contract_start_2": self.contract_start_2,
            "contract_end_2": self.contract_end_2,
            "contract_start_3": self.contract_start_3,
            "contract_end_3": self.contract_end_3,
            "contract_start_4": self.contract_start_4,
            "contract_end_4": self.contract_end_4,
            "age": self.age,
            "work_years": self.work_years,
            "factory_tenure": self.factory_tenure,
            "company_tenure": self.company_tenure,
            "hire_month": self.hire_month,
            "school": self.school,
            "education": self.education,
            "major": self.major,
            "classification": self.classification,
            "id_card": self.id_card,
            "id_card_expiry": self.id_card_expiry,
            "id_card_address": self.id_card_address,
            "current_address": self.current_address,
            "marital_status": self.marital_status,
            "household_type": self.household_type,
            "political_status": self.political_status,
            "phone": self.phone,
            "email": self.email,
            "emergency_contact_phone": self.emergency_contact_phone,
            "emergency_contact_relation": self.emergency_contact_relation,
            "bank_account": self.bank_account,
            "bank_account_location": self.bank_account_location,
            "training_id": self.training_id,
            "transfer_history": self.transfer_history,
            "remarks": self.remarks,
        }
