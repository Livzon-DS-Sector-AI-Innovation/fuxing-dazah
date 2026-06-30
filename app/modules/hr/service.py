"""HR business workflows live here."""

import logging
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.hr.feishu import FeishuBitableSync
from app.modules.hr.feishu.departure_datasource import (
    DepartureBitableDataSource,
)
from app.modules.hr.feishu.employee_datasource import (
    EmployeeBitableDataSource,
)
from app.modules.hr.feishu.onboarding_datasource import (
    OnboardingBitableDataSource,
)
from app.modules.hr.models import (
    AnnualTrainingPlan,
    AnnualTrainingPlanItem,
    DepartureRecord,
    Employee,
    HrDepartment,
    OffboardingRecord,
    OnboardingRecord,
    Team,
    TrainingLedger,
    TrainingLedgerPage,
)
from app.modules.hr.repository import (
    AnnualTrainingPlanItemRepository,
    AnnualTrainingPlanRepository,
    DepartmentRepository,
    DepartureRecordRepository,
    EmployeeRepository,
    OffboardingRecordRepository,
    OnboardingRecordRepository,
    TeamRepository,
    TrainingLedgerPageRepository,
    TrainingLedgerRepository,
)
from app.modules.hr.schemas import (
    AnnualTrainingPlanCreate,
    AnnualTrainingPlanItemBatchUpdate,
    AnnualTrainingPlanUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    DepartureRecordCreate,
    DepartureRecordUpdate,
    EmployeeCreate,
    EmployeeUpdate,
    OffboardingRecordCreate,
    OffboardingRecordUpdate,
    SyncStatusResponse,
    TeamCreate,
    TeamUpdate,
    TrainingLedgerCreate,
    TrainingLedgerUpdate,
)

logger = logging.getLogger(__name__)

# ─── Feishu field mapping helpers ───

def _extract_text(value) -> str:
    """Extract text from Feishu array format or plain string."""
    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
        return value[0].get("text", "")
    if isinstance(value, dict):
        if "text" in value:
            return value["text"]
        if "value" in value and isinstance(value["value"], list):
            inner = value["value"]
            if len(inner) > 0 and isinstance(inner[0], dict):
                return inner[0].get("text", "")
    if value is None:
        return ""
    return str(value)


def _extract_number(value) -> int | None:
    """Extract number from Feishu format."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        if "value" in value and isinstance(value["value"], list) and len(value["value"]) > 0:
            return int(value["value"][0])
    return None


def _ms_to_date(value) -> date | None:
    """Convert Feishu millisecond timestamp to Python date."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    return None


def _parse_feishu_record(record: dict) -> dict:
    """Convert a raw Feishu record into Employee constructor kwargs."""
    fields = record.get("fields", {})
    rid = record.get("record_id", "")
    updated_time = record.get("updated_time", "")

    def gt(key: str):
        return fields.get(key)

    data = {
        "feishu_record_id": rid,
        "employee_number": _extract_text(gt("工号")),
        "name": _extract_text(gt("姓名")),
        "domain_account": _extract_text(gt("域账号")),
        "department": gt("部门") or "",
        "team": gt("班组") or "",
        "position": _extract_text(gt("职位")),
        "job_category": gt("职类") or "",
        "level": gt("级别") or "",
        "qualifications": gt("职称／职业资格") if isinstance(gt("职称／职业资格"), list) else None,
        "qualification_type": gt("职称类型") or "",
        "gender": gt("性别") or "",
        "native_place": _extract_text(gt("籍贯")),
        "political_status": gt("政治面貌") or "",
        "marital_status": gt("婚姻状况") or "",
        "household_type": gt("户籍类型") or "",
        "status_category": gt("统计类别") or "",
        "birth_year": _extract_number(gt("年")),
        "birth_month": _extract_number(gt("月")),
        "birth_day": _extract_number(gt("日")),
        "age": _extract_number(gt("年龄")),
        "work_start_date": _ms_to_date(gt("参加工作时间")),
        "factory_entry_date": _ms_to_date(gt("进厂时间")),
        "livo_entry_date": _ms_to_date(gt("入丽珠时间")),
        "hire_date": _ms_to_date(gt("进厂时间")) or date.today(),
        "graduation_date": _ms_to_date(gt("毕业时间")),
        "work_years": _extract_number(gt("工作年限")),
        "factory_tenure": _extract_text(gt("厂龄")),
        "company_tenure": _extract_text(gt("司龄")),
        "education": gt("学历") or "",
        "classification": gt("分类") or "",
        "school": _extract_text(gt("毕业学校")),
        "major": _extract_text(gt("专业")),
        "id_card": _extract_text(gt("身份证号")),
        "id_card_expiry": _extract_text(gt("身份证到期日")),
        "id_card_address": _extract_text(gt("身份证地址|家庭地址")),
        "current_address": _extract_text(gt("现住址")),
        "contract_type": gt("合同期限") or "",
        "contract_start_date": _ms_to_date(gt("第一次合同起点时间")),
        "contract_end_date": _ms_to_date(gt("第一次合同终止时间")),
        "contract_start_2": _ms_to_date(gt("第二次合同起点时间")),
        "contract_end_2": _ms_to_date(gt("第二次合同终止时间")),
        "contract_start_3": _ms_to_date(gt("第三次合同起点时间")),
        "contract_end_3": _ms_to_date(gt("第三次合同终止时间")),
        "contract_start_4": _ms_to_date(gt("第四次合同起点时间")),
        "contract_end_4": _ms_to_date(gt("第四次合同终止时间")),
        "phone": _extract_text(gt("手机")),
        "email": _extract_text(gt("邮箱地址")),
        "emergency_contact_name": "",
        "emergency_contact_phone": _extract_text(gt("紧急联系人电话")),
        "emergency_contact_relation": _extract_text(gt("紧急联系人|关系")),
        "bank_account": _extract_text(gt("银行卡号")),
        "training_id": _extract_text(gt("培训档案编号")),
        "transfer_history": _extract_text(gt("异动（含曾经工作部门、岗位)")),
        "remarks": gt("备注") if isinstance(gt("备注"), list) else None,
        "status": "在职",
    }
    # Parse updated_time for sync tracking
    if updated_time:
        try:
            # Feishu returns ISO format string like "2024-01-15T08:30:00.000000Z"
            dt = datetime.fromisoformat(updated_time.replace("Z", "+00:00"))
            data["feishu_synced_at"] = dt.date()
        except Exception:
            data["feishu_synced_at"] = date.today()
    else:
        data["feishu_synced_at"] = date.today()

    # Remove empty strings for optional text fields to avoid overwriting existing data
    cleaned = {k: v for k, v in data.items() if v != "" or k in ("department", "name", "employee_number", "status", "position")}
    return cleaned


# ─── Services ───

class EmployeeService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = EmployeeRepository(session)
        self.feishu = FeishuBitableSync()
        self.bitable = EmployeeBitableDataSource()

    async def get_employee(self, employee_id: UUID) -> Employee:
        employee = await self.repo.get_by_id(employee_id)
        if not employee:
            raise NotFoundException("员工", str(employee_id))
        return employee

    async def get_employee_by_number(self, employee_number: str) -> Employee:
        employee = await self.repo.get_by_employee_number(employee_number)
        if not employee:
            raise NotFoundException("员工", employee_number)
        return employee

    async def create_employee(self, data: EmployeeCreate) -> Employee:
        existing = await self.repo.get_by_employee_number(data.employee_number)
        if existing:
            raise DuplicateException("工号", data.employee_number)

        employee = Employee(**data.model_dump())
        employee.status = "在职"

        # 根据手机号获取飞书 open_id（非阻塞，失败仅记录日志）
        if data.phone:
            try:
                from app.modules.hr.feishu.im import FeishuIM

                im = FeishuIM()
                # 飞书接口要求手机号带 +86 区号
                mobile = data.phone if data.phone.startswith("+") else f"+86{data.phone}"
                mapping = await im.batch_get_open_ids_by_mobile([mobile])
                open_id = mapping.get(mobile) or mapping.get(data.phone)
                if open_id:
                    employee.feishu_open_id = open_id
                    logger.info(
                        "Fetched feishu_open_id for employee %s: %s",
                        data.employee_number,
                        open_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to fetch feishu open_id for phone %s: %s",
                    data.phone,
                    e,
                )

        result = await self.repo.create(employee)

        # Sync to Feishu
        rid = await self.bitable.create(self._to_bitable_fields(result))
        if rid:
            result.feishu_record_id = rid
            result.feishu_synced_at = date.today()
            await self.repo.update(result)

        return result

    # ── Excel 列名 → 模型字段名 映射 ──
    _UPLOAD_COLUMN_MAP: dict[str, str] = {
        "工号": "employee_number",
        "姓名": "name",
        "域账号": "domain_account",
        "部门": "department",
        "班组": "team",
        "职位": "position",
        "岗位类别": "job_category",
        "级别": "level",
        "兼任部门": "concurrent_departments",
        "资格": "qualifications",
        "资格类型": "qualification_type",
        "性别": "gender",
        "籍贯": "native_place",
        "政治面貌": "political_status",
        "婚姻状况": "marital_status",
        "户籍类型": "household_type",
        "用工性质": "status_category",
        "出生年份": "birth_year",
        "出生月份": "birth_month",
        "出生日": "birth_day",
        "年龄": "age",
        "参加工作时间": "work_start_date",
        "进厂时间": "factory_entry_date",
        "进丽珠时间": "livo_entry_date",
        "入职日期": "hire_date",
        "毕业时间": "graduation_date",
        "工龄": "work_years",
        "厂龄": "factory_tenure",
        "公司工龄": "company_tenure",
        "学历": "education",
        "分类": "classification",
        "毕业学校": "school",
        "专业": "major",
        "身份证号": "id_card",
        "身份证有效期": "id_card_expiry",
        "身份证地址": "id_card_address",
        "现居住地址": "current_address",
        "合同类型": "contract_type",
        "合同开始日期": "contract_start_date",
        "合同结束日期": "contract_end_date",
        "合同开始日期2": "contract_start_2",
        "合同结束日期2": "contract_end_2",
        "合同开始日期3": "contract_start_3",
        "合同结束日期3": "contract_end_3",
        "合同开始日期4": "contract_start_4",
        "合同结束日期4": "contract_end_4",
        "手机": "phone",
        "邮箱": "email",
        "紧急联系人": "emergency_contact_name",
        "紧急联系人电话": "emergency_contact_phone",
        "紧急联系人关系": "emergency_contact_relation",
        "银行卡号": "bank_account",
        "培训编号": "training_id",
        "调动历史": "transfer_history",
        "备注": "remarks",
    }

    _DATE_FIELDS: set[str] = {
        "work_start_date", "factory_entry_date", "livo_entry_date",
        "hire_date", "graduation_date", "id_card_expiry",
        "contract_start_date", "contract_end_date",
        "contract_start_2", "contract_end_2",
        "contract_start_3", "contract_end_3",
        "contract_start_4", "contract_end_4",
    }

    _INT_FIELDS: set[str] = {
        "birth_year", "birth_month", "birth_day", "age", "work_years",
    }

    async def upload_employees(self, file_bytes: bytes) -> dict:
        """从 Excel 文件批量导入员工，按工号 upsert。返回 {created, updated, errors}。"""
        from io import BytesIO
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("文件为空")

        header = [str(c).strip() if c else "" for c in rows[0]]
        # 建立列索引
        col_map: dict[int, str] = {}
        for idx, col_name in enumerate(header):
            field = self._UPLOAD_COLUMN_MAP.get(col_name)
            if field:
                col_map[idx] = field

        if "employee_number" not in col_map.values():
            raise ValueError("缺少「工号」列，无法导入")

        created = 0
        updated = 0
        errors: list[str] = []

        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row):
                continue
            try:
                data: dict = {}
                for col_idx, field_name in col_map.items():
                    val = row[col_idx] if col_idx < len(row) else None
                    if val is None or (isinstance(val, str) and val.strip() == ""):
                        continue
                    if isinstance(val, str):
                        val = val.strip()
                    if field_name in self._DATE_FIELDS and isinstance(val, str):
                        val = date.fromisoformat(val)
                    elif field_name in self._DATE_FIELDS and isinstance(val, datetime):
                        val = val.date()
                    elif field_name in self._INT_FIELDS:
                        try:
                            val = int(float(str(val)))
                        except (ValueError, TypeError):
                            continue
                    elif field_name == "qualifications":
                        val = [v.strip() for v in str(val).split(",") if v.strip()]
                    data[field_name] = val

                if "employee_number" not in data:
                    errors.append(f"第{row_idx}行: 缺少工号")
                    continue

                existing = await self.repo.get_by_employee_number(data["employee_number"])
                if existing:
                    if "department" in data and data["department"] != existing.department:
                        existing.department = data["department"]
                        await self.repo.session.flush()
                    if "position" in data and data["position"] != existing.position:
                        existing.position = data["position"]
                        await self.repo.session.flush()
                    updated += 1
                else:
                    if "hire_date" not in data:
                        data["hire_date"] = date.today()
                    if "status" not in data:
                        data["status"] = "待审批"
                    await self.repo.upsert_by_employee_number(data)
                    created += 1
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")

        return {"created": created, "updated": updated, "errors": errors}

    async def approve_employee(self, employee_number: str) -> Employee:
        employee = await self.repo.get_by_employee_number(employee_number)
        if not employee:
            raise NotFoundException("员工", employee_number)
        if employee.status != "待审批":
            raise DuplicateException("审批", "该员工已审批完成")

        employee.status = "在职"
        result = await self.repo.update(employee)

        try:
            await self._sync_single_to_feishu(result)
        except Exception as e:
            logger.warning("Feishu sync failed for employee approved: %s", e)

        return result

    async def update_employee(self, employee_id: UUID, data: EmployeeUpdate) -> Employee:
        employee = await self.get_employee(employee_id)
        update_data = data.model_dump(exclude_unset=True)

        if "employee_number" in update_data:
            existing = await self.repo.get_by_employee_number(update_data["employee_number"])
            if existing and existing.id != employee_id:
                raise DuplicateException("工号", update_data["employee_number"])

        for field, value in update_data.items():
            setattr(employee, field, value)

        result = await self.repo.update(employee)

        try:
            await self._sync_single_to_feishu(result)
        except Exception as e:
            logger.warning("Feishu sync failed for employee updated: %s", e)

        return result

    async def delete_employee(self, employee_id: UUID) -> None:
        employee = await self.get_employee(employee_id)
        employee_number = employee.employee_number
        await self.repo.soft_delete(employee)

        try:
            if employee.feishu_record_id:
                await self.bitable.delete(employee.feishu_record_id)
            else:
                await self.feishu.sync_employee_deleted(employee_number)
        except Exception as e:
            logger.warning("Feishu sync failed for employee deleted: %s", e)

    async def list_employees(
        self,
        *,
        department: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "sort_order",
        sort_order: str = "asc",
    ) -> tuple[list[Employee], int]:
        return await self.repo.list_employees(
            department=department,
            status=status,
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def notify_training(self, payload) -> dict:
        """给受训人员发送飞书单聊消息（直接读取数据库 feishu_open_id）。

        Args:
            payload: TrainingNotifyInput instance.
        """
        from app.modules.hr.feishu.im import FeishuIM

        im = FeishuIM()

        # 1. 查询所有员工
        emp_list: list[Employee] = []
        for emp_no in payload.employee_numbers:
            emp = await self.repo.get_by_employee_number(emp_no)
            if emp:
                emp_list.append(emp)

        # 2. 组装消息内容
        time_str = ""
        if payload.training_time_start and payload.training_time_end:
            time_str = f"{payload.training_time_start} ~ {payload.training_time_end}"
        content_lines = [
            "【培训通知】",
            f"主题：{payload.subject}",
            f"时间：{payload.training_date} {time_str}",
            f"地点：{payload.location or '待定'}",
            f"培训师：{payload.trainer or '待定'}",
        ]
        if payload.content:
            content_lines.append(f"内容：{payload.content}")
        content_lines.append("请准时参加，自带笔记本笔，不得无故缺席。")
        content = "\n".join(content_lines)

        # 3. 逐条发送（直接读取数据库 feishu_open_id）
        sent = 0
        failed = 0
        details: list[dict] = []
        for emp in emp_list:
            open_id = emp.feishu_open_id
            if not open_id:
                failed += 1
                details.append(
                    {
                        "employee_number": emp.employee_number,
                        "name": emp.name,
                        "status": "failed",
                        "reason": "数据库中缺少 feishu_open_id，请先同步",
                    }
                )
                continue

            try:
                await im.send_text_message(open_id, content)
                sent += 1
                details.append(
                    {
                        "employee_number": emp.employee_number,
                        "name": emp.name,
                        "status": "sent",
                    }
                )
            except Exception as e:
                failed += 1
                details.append(
                    {
                        "employee_number": emp.employee_number,
                        "name": emp.name,
                        "status": "failed",
                        "reason": str(e),
                    }
                )

        # 未找到的员工
        found_numbers = {emp.employee_number for emp in emp_list}
        for emp_no in payload.employee_numbers:
            if emp_no not in found_numbers:
                failed += 1
                details.append(
                    {
                        "employee_number": emp_no,
                        "status": "failed",
                        "reason": "未找到员工",
                    }
                )

        return {"sent": sent, "failed": failed, "details": details}

    # ─── Bi-directional sync ───

    async def sync_from_feishu(self) -> dict:
        """Pull all records from Feishu Bitable and upsert into local PG.

        Returns:
            {"created": N, "updated": N, "failed": N, "total": N}
        """
        # Use raw client to get original dicts instead of EmployeeRecord wrappers
        raw_records = await self.bitable.client.search_records(
            self.bitable.table_id,
            page_size=500,
        )
        stats = {"created": 0, "updated": 0, "failed": 0, "total": len(raw_records)}

        for rec in raw_records:
            try:
                parsed = _parse_feishu_record(rec)
                emp_no = parsed.get("employee_number")
                if not emp_no:
                    stats["failed"] += 1
                    continue

                await self.repo.upsert_by_employee_number(parsed)
                existing = await self.repo.get_by_employee_number(emp_no)
                if existing and existing.created_at and (datetime.utcnow() - existing.created_at.replace(tzinfo=None)).total_seconds() < 60:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
            except Exception as e:
                logger.error("Failed to sync Feishu record %s: %s", rec.get("record_id"), e)
                stats["failed"] += 1

        return stats

    async def sync_to_feishu(self, employee_id: UUID) -> str:
        """Force-sync a single employee to Feishu.

        Returns the Feishu record_id.
        """
        employee = await self.get_employee(employee_id)
        return await self._sync_single_to_feishu(employee)

    async def get_sync_status(self) -> SyncStatusResponse:
        local_total = await self.repo.count_total()
        synced_count = await self.repo.count_synced()
        unsynced_count = local_total - synced_count

        # Use local synced count as feishu_total proxy to avoid expensive
        # real-time Feishu API calls (fetching 500 records takes ~5s).
        # Data consistency is ensured by the sync process itself.
        feishu_total = synced_count

        return SyncStatusResponse(
            local_total=local_total,
            feishu_total=feishu_total,
            synced_count=synced_count,
            unsynced_count=unsynced_count,
            conflict_count=0,  # TODO: implement conflict detection
            last_sync_at=None,
        )

    # ─── Internal helpers ───

    async def _sync_single_to_feishu(self, employee: Employee) -> str:
        """Sync one employee to Feishu, creating or updating as needed."""
        fields = self._to_bitable_fields(employee)
        if employee.feishu_record_id:
            await self.bitable.update(employee.feishu_record_id, fields)
            return employee.feishu_record_id
        else:
            rid = await self.bitable.create(fields)
            employee.feishu_record_id = rid
            employee.feishu_synced_at = date.today()
            await self.repo.update(employee)
            return rid

    def _to_bitable_fields(self, employee: Employee) -> dict:
        """Convert Employee ORM object to Feishu Bitable field dict.

        Filters out empty values to avoid Feishu validation errors
        (especially for phone fields which reject empty strings).
        """
        from app.modules.hr.feishu.bitable import _to_ms_timestamp

        # Build raw fields, keeping None/empty filtering for later
        raw: dict = {
            "姓名": employee.name,
            "工号": employee.employee_number,
            "部门": employee.department,
            "职位": employee.position,
            "手机": employee.phone,
            "邮箱地址": employee.email,
            "性别": employee.gender,
            "籍贯": employee.native_place,
            "政治面貌": employee.political_status,
            "婚姻状况": employee.marital_status,
            "学历": employee.education,
            "分类": employee.classification,
            "专业": employee.major,
            "身份证号": employee.id_card,
            "银行卡号": employee.bank_account,
            "培训档案编号": employee.training_id,
            "域账号": employee.domain_account,
            "班组": employee.team,
            "职类": employee.job_category,
            "级别": employee.level,
            "职称类型": employee.qualification_type,
            "户籍类型": employee.household_type,
            "统计类别": employee.status_category,
            "身份证到期日": employee.id_card_expiry,
            "合同期限": employee.contract_type,
            "身份证地址|家庭地址": employee.id_card_address,
            "现住址": employee.current_address,
            "紧急联系人电话": employee.emergency_contact_phone,
            "紧急联系人|关系": employee.emergency_contact_relation,
            "异动（含曾经工作部门、岗位)": employee.transfer_history,
        }
        # Filter out empty strings / None / empty lists
        fields = {k: v for k, v in raw.items() if v not in (None, "", [])}

        if employee.qualifications:
            fields["职称／职业资格"] = employee.qualifications
        if employee.remarks:
            fields["备注"] = employee.remarks

        # Dates
        if employee.work_start_date:
            fields["参加工作时间"] = _to_ms_timestamp(employee.work_start_date)
        if employee.factory_entry_date:
            fields["进厂时间"] = _to_ms_timestamp(employee.factory_entry_date)
        if employee.livo_entry_date:
            fields["入丽珠时间"] = _to_ms_timestamp(employee.livo_entry_date)
        if employee.graduation_date:
            fields["毕业时间"] = _to_ms_timestamp(employee.graduation_date)
        if employee.contract_start_date:
            fields["第一次合同起点时间"] = _to_ms_timestamp(employee.contract_start_date)
        if employee.contract_end_date:
            fields["第一次合同终止时间"] = _to_ms_timestamp(employee.contract_end_date)
        if employee.contract_start_2:
            fields["第二次合同起点时间"] = _to_ms_timestamp(employee.contract_start_2)
        if employee.contract_end_2:
            fields["第二次合同终止时间"] = _to_ms_timestamp(employee.contract_end_2)
        if employee.contract_start_3:
            fields["第三次合同起点时间"] = _to_ms_timestamp(employee.contract_start_3)
        if employee.contract_end_3:
            fields["第三次合同终止时间"] = _to_ms_timestamp(employee.contract_end_3)
        if employee.contract_start_4:
            fields["第四次合同起点时间"] = _to_ms_timestamp(employee.contract_start_4)
        if employee.contract_end_4:
            fields["第四次合同终止时间"] = _to_ms_timestamp(employee.contract_end_4)

        # Birth date
        if employee.birth_year:
            fields["年"] = employee.birth_year
        if employee.birth_month:
            fields["月"] = employee.birth_month
        if employee.birth_day:
            fields["日"] = employee.birth_day

        return fields

    # ── 年度培训计划上传 ──

    _PLAN_COLUMN_MAP: dict[str, str] = {
        "年度": "year",
        "年份": "year",
        "部门": "department",
        "月份": "month",
        "培训人数": "trainee_count",
        "课时": "duration_hours",
        "培训内容及使用教材": "content_and_textbook",
        "培训内容": "content_and_textbook",
        "培训对象": "target_audience",
        "参加岗位/参加人数": "position_and_count",
        "培训方式": "training_method",
        "培训学时": "training_hours",
        "确认者": "confirmer",
    }

    async def upload_annual_plan(self, file_bytes: bytes) -> dict:
        """从 Excel 批量导入年度培训计划，按年度+部门自动分类。"""
        from io import BytesIO
        from openpyxl import load_workbook
        from app.modules.hr.models import AnnualTrainingPlan, AnnualTrainingPlanItem

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("文件为空")
        header = [str(c).strip() if c else "" for c in rows[0]]
        col_map = {idx: self._PLAN_COLUMN_MAP[h] for idx, h in enumerate(header) if h in self._PLAN_COLUMN_MAP}

        plan_cache: dict[tuple, AnnualTrainingPlan] = {}
        created, updated, errors = 0, 0, []

        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row):
                continue
            try:
                data = {}
                for ci, fn in col_map.items():
                    v = row[ci] if ci < len(row) else None
                    if v is None or (isinstance(v, str) and v.strip() == ""):
                        continue
                    if isinstance(v, str):
                        v = v.strip()
                    if fn == "year":
                        v = int(float(str(v)))
                    if fn in ("trainee_count",):
                        v = int(float(str(v)))
                    data[fn] = v

                dept = data.get("department", "")
                year = data.get("year", 2026)
                if not dept:
                    errors.append(f"第{row_idx}行: 缺少部门"); continue

                # 找或创建年度计划
                cache_key = (year, dept)
                plan = plan_cache.get(cache_key)
                if not plan:
                    q = select(AnnualTrainingPlan).where(
                        AnnualTrainingPlan.year == year,
                        AnnualTrainingPlan.department == dept,
                        AnnualTrainingPlan.is_deleted == False,
                    )
                    r = await self.repo.session.execute(q)
                    plan = r.scalar_one_or_none()
                    if not plan:
                        plan = AnnualTrainingPlan(year=year, department=dept, status="草稿")
                        self.repo.session.add(plan)
                        await self.repo.session.flush()
                    plan_cache[cache_key] = plan

                # 添加计划项
                item_data = {k: v for k, v in data.items() if k not in ("year", "department")}
                item = AnnualTrainingPlanItem(plan_id=plan.id, **item_data)
                self.repo.session.add(item)
                await self.repo.session.flush()
                created += 1
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")

        return {"created": created, "updated": updated, "errors": errors}

    # ── SOP 目录上传 ──

    _SOP_COLUMN_MAP: dict[str, str] = {
        "文件名": "file_name",
        "SOP编号": "sop_number",
        "类别": "category",
        "部门": "department",
    }

    async def upload_sop_catalog(self, file_bytes: bytes) -> dict:
        """从 Excel 批量导入 SOP 目录，按 SOP编号 upsert。"""
        from io import BytesIO
        from openpyxl import load_workbook
        from app.modules.hr.models import SopCatalog

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("文件为空")

        header = [str(c).strip() if c else "" for c in rows[0]]
        col_map: dict[int, str] = {}
        for idx, col_name in enumerate(header):
            field = self._SOP_COLUMN_MAP.get(col_name)
            if field:
                col_map[idx] = field

        created = 0
        updated = 0
        errors: list[str] = []

        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row):
                continue
            try:
                data: dict = {}
                for col_idx, field_name in col_map.items():
                    val = row[col_idx] if col_idx < len(row) else None
                    if val is None or (isinstance(val, str) and val.strip() == ""):
                        continue
                    if isinstance(val, str):
                        val = val.strip()
                    data[field_name] = val

                if "file_name" not in data:
                    errors.append(f"第{row_idx}行: 缺少文件名")
                    continue

                sop_num = data.get("sop_number")
                existing = None
                if sop_num:
                    existing = await self.repo.session.execute(
                        select(SopCatalog).where(
                            SopCatalog.sop_number == sop_num,
                            SopCatalog.is_deleted == False,  # noqa: E712
                        )
                    )
                    existing = existing.scalar_one_or_none()

                if existing:
                    for k, v in data.items():
                        if v is not None:
                            setattr(existing, k, v)
                    await self.repo.session.flush()
                    updated += 1
                else:
                    new_sop = SopCatalog(**data)
                    self.repo.session.add(new_sop)
                    await self.repo.session.flush()
                    created += 1
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")

        return {"created": created, "updated": updated, "errors": errors}


    # ── 内训师上传 ──

    _TRAINER_COLUMN_MAP: dict[str, str] = {
        "姓名": "name",
        "部门": "department",
        "可培训部门": "trainable_departments",
        "资格范围": "qualification_scope",
        "认证日期": "certification_date",
        "确认日期": "confirmation_date",
        "确认提醒": "confirmation_reminder",
        "备注": "remarks",
        "是否主训师": "is_primary_trainer",
        "管理员": "admin",
    }

    async def upload_trainers(self, file_bytes: bytes) -> dict:
        """从 Excel 批量导入内训师，按姓名+部门 upsert。"""
        from io import BytesIO
        from openpyxl import load_workbook
        from app.modules.hr.models import HrTrainer

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("文件为空")
        header = [str(c).strip() if c else "" for c in rows[0]]
        col_map = {idx: self._TRAINER_COLUMN_MAP.get(h, "") for idx, h in enumerate(header) if h in self._TRAINER_COLUMN_MAP}
        created, updated, errors = 0, 0, []
        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row):
                continue
            try:
                data = {}
                for ci, fn in col_map.items():
                    v = row[ci] if ci < len(row) else None
                    if v is None or (isinstance(v, str) and v.strip() == ""):
                        continue
                    if isinstance(v, str):
                        v = v.strip()
                    if fn == "is_primary_trainer":
                        v = str(v).strip() in ("是", "1", "True", "true", "Y", "y")
                    data[fn] = v
                name = data.get("name")
                dept = data.get("department")
                if not name:
                    errors.append(f"第{row_idx}行: 缺少姓名"); continue
                existing = None
                if name:
                    q = select(HrTrainer).where(HrTrainer.name == name, HrTrainer.is_deleted == False)
                    if dept:
                        q = q.where(HrTrainer.department == dept)
                    r = await self.repo.session.execute(q)
                    existing = r.scalar_one_or_none()
                if existing:
                    for k, v in data.items():
                        if v is not None: setattr(existing, k, v)
                    updated += 1
                else:
                    self.repo.session.add(HrTrainer(**data))
                    created += 1
                await self.repo.session.flush()
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")
        return {"created": created, "updated": updated, "errors": errors}


class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DepartmentRepository(session)
        self.feishu = FeishuBitableSync()

    async def get_department(self, department_id: UUID) -> HrDepartment:
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException("部门", str(department_id))
        return department

    async def create_department(self, data: DepartmentCreate) -> HrDepartment:
        existing = await self.repo.get_by_code(data.code)
        if existing:
            raise DuplicateException("部门编码", data.code)

        department = HrDepartment(**data.model_dump())
        result = await self.repo.create(department)

        try:
            await self.feishu.sync_department_created(result.__dict__)
        except Exception as e:
            logger.warning("Feishu sync failed for department created: %s", e)

        return result

    async def update_department(self, department_id: UUID, data: DepartmentUpdate) -> HrDepartment:
        department = await self.get_department(department_id)
        update_data = data.model_dump(exclude_unset=True)

        if "code" in update_data:
            existing = await self.repo.get_by_code(update_data["code"])
            if existing and existing.id != department_id:
                raise DuplicateException("部门编码", update_data["code"])

        for field, value in update_data.items():
            setattr(department, field, value)

        result = await self.repo.update(department)

        try:
            await self.feishu.sync_department_updated(result.__dict__)
        except Exception as e:
            logger.warning("Feishu sync failed for department updated: %s", e)

        return result

    async def delete_department(self, department_id: UUID) -> None:
        department = await self.get_department(department_id)
        code = department.code
        await self.repo.soft_delete(department)

        try:
            await self.feishu.sync_department_deleted(code)
        except Exception as e:
            logger.warning("Feishu sync failed for department deleted: %s", e)

    async def list_departments(
        self,
        *,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[HrDepartment], int]:
        departments, total = await self.repo.list_departments(
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        # Attach employee count to each department
        from sqlalchemy import select, func
        from app.modules.hr.models import Employee
        for dept in departments:
            count = await self.repo.session.scalar(
                select(func.count()).select_from(Employee).where(
                    Employee.department == dept.name,
                    Employee.is_deleted.is_(False),
                )
            )
            dept.employee_count = count or 0
        return departments, total


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = TeamRepository(session)
        self.department_repo = DepartmentRepository(session)

    async def get_team(self, team_id: UUID) -> Team:
        team = await self.repo.get_by_id(team_id)
        if not team:
            raise NotFoundException("班组", str(team_id))
        return team

    async def create_team(self, data: TeamCreate) -> Team:
        department = await self.department_repo.get_by_id(data.department_id)
        if not department:
            raise NotFoundException("部门", str(data.department_id))

        team = Team(**data.model_dump())
        result = await self.repo.create(team)
        return result

    async def update_team(self, team_id: UUID, data: TeamUpdate) -> Team:
        team = await self.get_team(team_id)
        update_data = data.model_dump(exclude_unset=True)

        if "department_id" in update_data:
            department = await self.department_repo.get_by_id(update_data["department_id"])
            if not department:
                raise NotFoundException("部门", str(update_data["department_id"]))

        for field, value in update_data.items():
            setattr(team, field, value)

        result = await self.repo.update(team)
        return result

    async def delete_team(self, team_id: UUID) -> None:
        team = await self.get_team(team_id)
        await self.repo.soft_delete(team)

    async def list_teams(
        self,
        *,
        department_id: UUID | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Team], int]:
        return await self.repo.list_teams(
            department_id=department_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )


class OffboardingRecordService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = OffboardingRecordRepository(session)
        self.employee_repo = EmployeeRepository(session)
        self.feishu = FeishuBitableSync()

    async def get_record(self, record_id: UUID) -> OffboardingRecord:
        record = await self.repo.get_by_id(record_id)
        if not record:
            raise NotFoundException("离职记录", str(record_id))
        return record

    async def create_record(self, data: OffboardingRecordCreate) -> OffboardingRecord:
        employee = await self.employee_repo.get_by_id(data.employee_id)
        if not employee:
            raise NotFoundException("员工", str(data.employee_id))

        record = OffboardingRecord(**data.model_dump())
        record = await self.repo.create(record)

        # 自动将员工状态更新为离职
        employee.status = "离职"
        await self.employee_repo.update(employee)

        # 同步到飞书
        try:
            record_dict = {
                **record.__dict__,
                "employee": {
                    "name": employee.name,
                    "employee_number": employee.employee_number,
                },
            }
            await self.feishu.sync_offboarding_created(record_dict)
        except Exception as e:
            logger.warning("Feishu sync failed for offboarding created: %s", e)

        return record

    async def update_record(self, record_id: UUID, data: OffboardingRecordUpdate) -> OffboardingRecord:
        record = await self.get_record(record_id)
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(record, field, value)

        result = await self.repo.update(record)

        try:
            await self.feishu.sync_offboarding_updated(result.__dict__)
        except Exception as e:
            logger.warning("Feishu sync failed for offboarding updated: %s", e)

        return result

    async def delete_record(self, record_id: UUID) -> None:
        record = await self.get_record(record_id)
        await self.repo.soft_delete(record)

    async def list_records(
        self,
        *,
        employee_id: UUID | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[OffboardingRecord], int]:
        return await self.repo.list_records(
            employee_id=employee_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

class OnboardingRecordService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = OnboardingRecordRepository(session)
        self.bitable = OnboardingBitableDataSource()

    async def get_record(self, record_id: UUID) -> OnboardingRecord:
        record = await self.repo.get_by_id(record_id)
        if not record:
            raise NotFoundException("入职记录", str(record_id))
        return record

    async def list_records(
        self,
        *,
        department: str | None = None,
        position: str | None = None,
        is_employed: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "hire_date",
        sort_order: str = "desc",
    ) -> tuple[list[OnboardingRecord], int]:
        return await self.repo.list_records(
            department=department,
            position=position,
            is_employed=is_employed,
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def sync_from_feishu(self) -> dict:
        """Pull all records from Feishu Bitable and upsert into local PG.

        Returns:
            {"created": N, "updated": N, "failed": N, "total": N}
        """
        raw_records = await self.bitable.client.search_records(
            self.bitable.table_id,
            page_size=500,
        )
        stats = {"created": 0, "updated": 0, "failed": 0, "total": len(raw_records)}

        for rec in raw_records:
            try:
                from app.modules.hr.feishu.onboarding_datasource import (
                    OnboardingRecord as BitableOnboardingRecord,
                )

                parsed = BitableOnboardingRecord.from_api(rec)
                data = parsed.to_dict()
                data["feishu_synced_at"] = date.today()
                rid = data.get("feishu_record_id")
                if not rid:
                    stats["failed"] += 1
                    continue

                # Skip records with empty critical fields (blank rows in Bitable)
                if not data.get("name") or not data.get("department") or not data.get("hire_date"):
                    logger.debug("Skipping blank onboarding record: %s", rid)
                    continue

                await self.repo.upsert_by_feishu_record_id(data)
                existing = await self.repo.get_by_feishu_record_id(rid)
                if existing and existing.created_at and (
                    datetime.utcnow() - existing.created_at.replace(tzinfo=None)
                ).total_seconds() < 60:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
            except Exception as e:
                logger.error("Failed to sync onboarding record %s: %s", rec.get("record_id"), e)
                stats["failed"] += 1

        return stats

    async def get_sync_status(self) -> SyncStatusResponse:
        local_total = await self.repo.count_total()
        synced_count = await self.repo.count_synced()
        unsynced_count = local_total - synced_count
        feishu_total = synced_count

        return SyncStatusResponse(
            local_total=local_total,
            feishu_total=feishu_total,
            synced_count=synced_count,
            unsynced_count=unsynced_count,
            conflict_count=0,
            last_sync_at=None,
        )


class DepartureRecordService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DepartureRecordRepository(session)
        self.bitable = DepartureBitableDataSource()

    async def get_record(self, record_id: UUID) -> DepartureRecord:
        record = await self.repo.get_by_id(record_id)
        if not record:
            raise NotFoundException("离职台账记录", str(record_id))
        return record

    async def list_records(
        self,
        *,
        department: str | None = None,
        offboarding_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "offboarding_date",
        sort_order: str = "desc",
    ) -> tuple[list[DepartureRecord], int]:
        return await self.repo.list_records(
            department=department,
            offboarding_type=offboarding_type,
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def create_record(self, data: DepartureRecordCreate) -> DepartureRecord:
        record = DepartureRecord(**data.model_dump())
        return await self.repo.create(record)

    async def update_record(self, record_id: UUID, data: DepartureRecordUpdate) -> DepartureRecord:
        record = await self.get_record(record_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(record, field, value)
        return await self.repo.update(record)

    async def delete_record(self, record_id: UUID) -> None:
        record = await self.get_record(record_id)
        await self.repo.soft_delete(record)

    async def sync_from_feishu(self) -> dict:
        """Pull all records from Feishu Bitable and upsert into local PG.

        Returns:
            {"created": N, "updated": N, "failed": N, "total": N}
        """
        raw_records = await self.bitable.client.search_records(
            self.bitable.table_id,
            page_size=500,
        )
        stats = {"created": 0, "updated": 0, "failed": 0, "total": len(raw_records)}

        for rec in raw_records:
            try:
                from app.modules.hr.feishu.departure_datasource import (
                    DepartureRecord as BitableDepartureRecord,
                )

                parsed = BitableDepartureRecord.from_api(rec)
                data = parsed.to_dict()
                data["feishu_synced_at"] = date.today()
                rid = data.get("feishu_record_id")
                if not rid:
                    stats["failed"] += 1
                    continue

                await self.repo.upsert_by_feishu_record_id(data)
                existing = await self.repo.get_by_feishu_record_id(rid)
                if existing and existing.created_at and (
                    datetime.utcnow() - existing.created_at.replace(tzinfo=None)
                ).total_seconds() < 60:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
            except Exception:
                logger.exception("Failed to sync departure record %s", rec.get("record_id"))
                stats["failed"] += 1

        return stats

    async def get_sync_status(self) -> SyncStatusResponse:
        local_total = await self.repo.count_total()
        synced_count = await self.repo.count_synced()
        unsynced_count = local_total - synced_count
        feishu_total = synced_count

        return SyncStatusResponse(
            local_total=local_total,
            feishu_total=feishu_total,
            synced_count=synced_count,
            unsynced_count=unsynced_count,
            conflict_count=0,
            last_sync_at=None,
        )


class TrainingLedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = TrainingLedgerRepository(session)

    async def get_record(self, record_id: UUID) -> TrainingLedger:
        record = await self.repo.get_by_id(record_id)
        if not record:
            raise NotFoundException("培训台账记录", str(record_id))
        return record

    async def create_record(self, data: TrainingLedgerCreate) -> TrainingLedger:
        record = TrainingLedger(**data.model_dump())
        return await self.repo.create(record)

    async def update_record(
        self, record_id: UUID, data: TrainingLedgerUpdate
    ) -> TrainingLedger:
        record = await self.get_record(record_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(record, field, value)
        return await self.repo.update(record)

    async def delete_record(self, record_id: UUID) -> None:
        record = await self.get_record(record_id)
        await self.repo.soft_delete(record)

    async def list_records(
        self,
        *,
        employee_number: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "training_date",
        sort_order: str = "asc",
    ) -> tuple[list[TrainingLedger], int]:
        return await self.repo.list_records(
            employee_number=employee_number,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def create_from_notification(
        self,
        *,
        employee_number: str,
        training_date: date,
        training_subject: str,
        training_method: str | None,
        trainer: str | None,
        source_id: str | None = None,
    ) -> TrainingLedger | None:
        """当培训通知包含特定员工时，自动创建培训台账记录。"""
        if source_id:
            existing = await self.repo.get_by_source("notification", source_id)
            if existing:
                return existing

        record = TrainingLedger(
            employee_number=employee_number,
            training_date=training_date,
            training_subject=training_subject,
            training_method=training_method,
            trainer=trainer,
            source_type="notification",
            source_id=source_id,
        )
        return await self.repo.create(record)


class TrainingLedgerPageService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = TrainingLedgerPageRepository(session)

    async def list_pages(self) -> list[TrainingLedgerPage]:
        return await self.repo.list_pages()

    async def list_pages_with_department(self) -> list[tuple[TrainingLedgerPage, str | None]]:
        return await self.repo.list_pages_with_department()

    async def create_page(self, data) -> TrainingLedgerPage:
        existing = await self.repo.get_by_employee_number(data.employee_number)
        if existing:
            raise DuplicateException("培训台账页面", data.employee_number)
        page = TrainingLedgerPage(**data.model_dump())
        return await self.repo.create(page)


class AnnualTrainingPlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AnnualTrainingPlanRepository(session)
        self.item_repo = AnnualTrainingPlanItemRepository(session)

    async def get_plan(self, plan_id: UUID) -> AnnualTrainingPlan:
        plan = await self.repo.get_by_id(plan_id)
        if not plan:
            raise NotFoundException("年度培训计划", str(plan_id))
        return plan

    async def create_plan(self, data: AnnualTrainingPlanCreate) -> AnnualTrainingPlan:
        existing = await self.repo.get_by_year_and_department(data.year, data.department)
        if existing:
            raise DuplicateException("年度培训计划", f"{data.year}年-{data.department}")
        plan = AnnualTrainingPlan(**data.model_dump())
        return await self.repo.create(plan)

    async def update_plan(self, plan_id: UUID, data: AnnualTrainingPlanUpdate) -> AnnualTrainingPlan:
        plan = await self.get_plan(plan_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(plan, field, value)
        return await self.repo.update(plan)

    async def delete_plan(self, plan_id: UUID) -> None:
        plan = await self.get_plan(plan_id)
        await self.repo.soft_delete(plan)

    async def list_plans(
        self,
        *,
        year: int | None = None,
        department: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AnnualTrainingPlan], int]:
        return await self.repo.list_plans(
            year=year,
            department=department,
            page=page,
            page_size=page_size,
        )


class AnnualTrainingPlanItemService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AnnualTrainingPlanItemRepository(session)
        self.plan_repo = AnnualTrainingPlanRepository(session)

    async def list_items(self, plan_id: UUID) -> list[AnnualTrainingPlanItem]:
        return await self.repo.list_items(plan_id)

    async def batch_update_items(
        self, plan_id: UUID, data: AnnualTrainingPlanItemBatchUpdate
    ) -> list[AnnualTrainingPlanItem]:
        plan = await self.plan_repo.get_by_id(plan_id)
        if not plan:
            raise NotFoundException("年度培训计划", str(plan_id))

        # 删除旧明细
        await self.repo.delete_by_plan_id(plan_id)

        # 创建新明细
        results: list[AnnualTrainingPlanItem] = []
        for idx, item_data in enumerate(data.items):
            item = AnnualTrainingPlanItem(
                plan_id=plan_id,
                sort_order=idx,
                **item_data.model_dump(exclude={"sort_order"}),
            )
            created = await self.repo.create(item)
            results.append(created)
        return results
