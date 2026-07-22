"""Employee roster Bitable datasource adapter.

Adapts Feishu Bitable API quirks:
- Text fields read as [{"text": ..., "type": "text"}] but write as plain strings
- Formula fields (age, tenure, etc.) are read-only
- Phone fields use type=13
- Date fields require millisecond timestamps
"""

import logging
from datetime import date, datetime
from typing import Any

from app.core.config import get_settings
from app.modules.hr.feishu.bitable import BitableClient, _to_ms_timestamp

logger = logging.getLogger(__name__)
_settings = get_settings()

# ─── Field type constants ───
TEXT = 1
NUMBER = 2
SINGLE_SELECT = 3
MULTI_SELECT = 4
DATE = 5
FORMULA = 20
PHONE = 13
AUTO_NUMBER = 1005
LINK = 18

# ─── Read-only formula fields ───
FORMULA_FIELDS = {"年龄", "工作年限", "厂龄", "司龄", "入职月份", "字段 1"}


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


class EmployeeBitableDataSource:
    """Employee roster datasource backed by Feishu Bitable.

    Usage:
        ds = EmployeeBitableDataSource()

        # Query all employees
        rows = await ds.query()
        for emp in rows:
            print(emp.name, emp.employee_number, emp.department)

        # Find by employee number
        emp = await ds.find_by_employee_number("110000149")

        # Create new employee
        record_id = await ds.create({
            "姓名": "张三",
            "工号": "110000999",
            "部门": "生产部",
            "性别": "男",
            "进厂时间": datetime(2024, 1, 1),
        })
    """

    def __init__(self) -> None:
        self.client = BitableClient()
        # New employee base: https://j0eukrlohu.feishu.cn/base/KHLsboPBGaah6Vs3EpgcpvzsnuH
        self.client.app_token = _settings.HR_BITABLE_APP_TOKEN or "KHLsboPBGaah6Vs3EpgcpvzsnuH"
        self.table_id = _settings.HR_BITABLE_EMPLOYEE_TABLE_ID or "tblrcSHfS5ivun7e"

    def _is_enabled(self) -> bool:
        return bool(self.client.app_token)

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
        """Create raw record, return record_id."""
        record = await self.client.create_record(self.table_id, fields)
        return record.get("record_id", "")

    async def _update(self, record_id: str, fields: dict[str, Any]) -> None:
        await self.client.update_record(self.table_id, record_id, fields)

    async def _delete(self, record_id: str) -> None:
        await self.client.delete_record(self.table_id, record_id)

    # ─── Public query API ───

    async def query(
        self,
        *,
        department: str | None = None,
        gender: str | None = None,
        status: str | None = None,
        page_size: int = 500,
    ) -> list["EmployeeRecord"]:
        """Query employees with optional filters."""
        filters: list[str] = []
        if department:
            filters.append(f'CurrentValue.[部门] = "{department}"')
        if gender:
            filters.append(f'CurrentValue.[性别] = "{gender}"')
        if status:
            filters.append(f'CurrentValue.[分类] = "{status}"')

        filter_str = " AND ".join(filters) if filters else None
        items = await self._search(filter_str=filter_str, page_size=page_size)
        return [EmployeeRecord.from_api(item) for item in items]

    async def find_by_employee_number(self, employee_number: str) -> "EmployeeRecord | None":
        """Find single employee by employee number (工号)."""
        items = await self._search(
            filter_str=f'CurrentValue.[工号] = "{employee_number}"'
        )
        if not items:
            return None
        return EmployeeRecord.from_api(items[0])

    async def find_by_name(self, name: str) -> list["EmployeeRecord"]:
        """Find employees by name (may return multiple)."""
        items = await self._search(
            filter_str=f'CurrentValue.[姓名] contains "{name}"'
        )
        return [EmployeeRecord.from_api(item) for item in items]

    async def find_by_domain_account(self, account: str) -> "EmployeeRecord | None":
        """Find by domain account (域账号)."""
        items = await self._search(
            filter_str=f'CurrentValue.[域账号] = "{account}"'
        )
        if not items:
            return None
        return EmployeeRecord.from_api(items[0])

    # ─── Write API ───

    async def create(self, data: dict[str, Any]) -> str:
        """Create employee record.

        Args:
            data: Dict with field names as keys.
                  Date fields accept datetime/date/str("2024-01-01").
                  Text fields accept plain strings.
                  Formula fields (年龄/厂龄/司龄/工作年限/入职月份) are ignored.
        """
        fields = self._prepare_write_fields(data)
        rid = await self._create(fields)
        logger.info("Employee created in Bitable: %s", rid)
        return rid

    async def update(self, record_id: str, data: dict[str, Any]) -> None:
        """Update employee record by record_id."""
        fields = self._prepare_write_fields(data)
        if fields:
            await self._update(record_id, fields)
            logger.info("Employee updated in Bitable: %s", record_id)

    async def upsert_by_employee_number(self, data: dict[str, Any]) -> str:
        """Update if exists, create if not. Returns record_id."""
        emp_no = data.get("工号")
        if not emp_no:
            raise ValueError("工号 is required for upsert")

        existing = await self.find_by_employee_number(str(emp_no))
        if existing:
            await self.update(existing.record_id, data)
            return existing.record_id
        else:
            return await self.create(data)

    async def delete(self, record_id: str) -> None:
        await self._delete(record_id)
        logger.info("Employee deleted from Bitable: %s", record_id)

    # ─── Bulk sync ───

    async def sync_from_db(self, employees: list[dict[str, Any]]) -> dict[str, int]:
        """Bulk upsert from local database records.

        Returns:
            {"created": N, "updated": N, "failed": N}
        """
        stats = {"created": 0, "updated": 0, "failed": 0}
        for emp in employees:
            try:
                rid = await self.upsert_by_employee_number(emp)
                if existing := await self.find_by_employee_number(str(emp["工号"])):
                    if existing.record_id == rid:
                        stats["updated"] += 1
                    else:
                        stats["created"] += 1
                else:
                    stats["created"] += 1
            except Exception as e:
                logger.error("Failed to sync employee %s: %s", emp.get("工号"), e)
                stats["failed"] += 1
        return stats

    # ─── Field preparation ───

    def _prepare_write_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Python types to Feishu API format and strip read-only fields."""
        prepared: dict[str, Any] = {}
        for key, value in data.items():
            if key in FORMULA_FIELDS:
                # Skip formula fields - they are computed by Bitable
                continue
            if value is None:
                continue
            if key in {
                "参加工作时间", "进厂时间", "入丽珠时间", "毕业时间",
                "第一次合同起点时间", "第一次合同终止时间",
                "第二次合同起点时间", "第二次合同终止时间",
                "第三次合同起点时间", "第三次合同终止时间",
                "第四次合同起点时间", "第四次合同终止时间",
            }:
                prepared[key] = _to_ms_timestamp(value)
            else:
                prepared[key] = value
        return prepared


class EmployeeRecord:
    """Parsed employee record from Bitable API."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.record_id: str = raw.get("record_id", "")
        fields = raw.get("fields", {})

        # Basic info
        self.name: str = _extract_text(fields.get("姓名"))
        self.employee_number: str = _extract_text(fields.get("工号"))
        self.domain_account: str = _extract_text(fields.get("域账号"))
        self.department: str = fields.get("部门", "")
        self.team: str = fields.get("班组", "")
        self.gender: str = fields.get("性别", "")
        self.position: str = _extract_text(fields.get("职位"))
        self.job_category: str = fields.get("职类", "")
        self.level: str = fields.get("级别", "")

        # IDs
        self.id_card: str = _extract_text(fields.get("身份证号"))
        self.id_card_expiry: str = _extract_text(fields.get("身份证到期日"))
        self.phone: str = fields.get("手机", "")
        self.email: str = _extract_text(fields.get("邮箱地址"))

        # Origin / education
        self.native_place: str = _extract_text(fields.get("籍贯"))
        self.political_status: str = fields.get("政治面貌", "")
        self.marital_status: str = fields.get("婚姻状况", "")
        self.household_type: str = fields.get("户籍类型", "")
        self.education: str = fields.get("学历", "")
        self.school: str = _extract_text(fields.get("毕业学校"))
        self.major: str = _extract_text(fields.get("专业"))

        # Career
        self.qualifications: list[str] = _extract_multi_select(fields.get("职称／职业资格"))
        self.qualification_type: str = fields.get("职称类型", "")
        self.classification: str = fields.get("分类", "")
        self.status: str = fields.get("统计类别", "")
        self.contract_type: str = fields.get("合同期限", "")

        # Dates (raw ms timestamps - expose helper properties)
        self._work_start_date = fields.get("参加工作时间")
        self._factory_entry_date = fields.get("进厂时间")
        self._livo_entry_date = fields.get("入丽珠时间")
        self._graduation_date = fields.get("毕业时间")

        # Banking / emergency
        self.bank_account: str = _extract_text(fields.get("银行卡号"))
        self.emergency_contact_phone: str = fields.get("紧急联系人电话", "")
        self.emergency_contact: str = _extract_text(fields.get("紧急联系人|关系"))

        # Address
        self.id_card_address: str = _extract_text(fields.get("身份证地址|家庭地址"))
        self.current_address: str = _extract_text(fields.get("现住址"))

        # Other
        self.training_id: str = _extract_text(fields.get("培训档案编号"))
        self.transfer_history: str = _extract_text(fields.get("异动（含曾经工作部门、岗位)"))
        self.remarks: list[str] = _extract_multi_select(fields.get("备注"))

        # Formula / computed (read-only)
        self.age = _extract_number(fields.get("年龄"))
        self.work_years = _extract_number(fields.get("工作年限"))
        self.factory_tenure = _extract_text(fields.get("厂龄"))
        self.company_tenure = _extract_text(fields.get("司龄"))

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "EmployeeRecord":
        return cls(raw)

    @property
    def work_start_date(self) -> date | None:
        return self._ms_to_date(self._work_start_date)

    @property
    def factory_entry_date(self) -> date | None:
        return self._ms_to_date(self._factory_entry_date)

    @property
    def livo_entry_date(self) -> date | None:
        return self._ms_to_date(self._livo_entry_date)

    @property
    def graduation_date(self) -> date | None:
        return self._ms_to_date(self._graduation_date)

    @staticmethod
    def _ms_to_date(value: Any) -> date | None:
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value / 1000).date()
        return None

    def to_dict(self) -> dict[str, Any]:
        """Export to plain dict suitable for local DB storage."""
        return {
            "record_id": self.record_id,
            "name": self.name,
            "employee_number": self.employee_number,
            "domain_account": self.domain_account,
            "department": self.department,
            "team": self.team,
            "gender": self.gender,
            "position": self.position,
            "job_category": self.job_category,
            "level": self.level,
            "id_card": self.id_card,
            "id_card_expiry": self.id_card_expiry,
            "phone": self.phone,
            "email": self.email,
            "native_place": self.native_place,
            "political_status": self.political_status,
            "marital_status": self.marital_status,
            "household_type": self.household_type,
            "education": self.education,
            "school": self.school,
            "major": self.major,
            "qualifications": self.qualifications,
            "qualification_type": self.qualification_type,
            "classification": self.classification,
            "status": self.status,
            "contract_type": self.contract_type,
            "work_start_date": self.work_start_date.isoformat() if self.work_start_date else None,
            "factory_entry_date": self.factory_entry_date.isoformat() if self.factory_entry_date else None,
            "livo_entry_date": self.livo_entry_date.isoformat() if self.livo_entry_date else None,
            "graduation_date": self.graduation_date.isoformat() if self.graduation_date else None,
            "bank_account": self.bank_account,
            "emergency_contact_phone": self.emergency_contact_phone,
            "emergency_contact": self.emergency_contact,
            "id_card_address": self.id_card_address,
            "current_address": self.current_address,
            "training_id": self.training_id,
            "transfer_history": self.transfer_history,
            "remarks": self.remarks,
            "age": self.age,
            "work_years": self.work_years,
            "factory_tenure": self.factory_tenure,
            "company_tenure": self.company_tenure,
        }
