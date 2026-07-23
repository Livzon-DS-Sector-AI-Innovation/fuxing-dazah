"""HR business workflows live here."""

import logging
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select, text, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.hr.models import (
    AnnualTrainingPlan,
    AnnualTrainingPlanItem,
    DepartureRecord,
    Employee,
    HrDepartment,
    OffboardingRecord,
    OnboardingRecord,
    PositionTraining,
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
    TeamCreate,
    TeamUpdate,
    TrainingLedgerCreate,
    TrainingLedgerUpdate,
)

logger = logging.getLogger(__name__)

# ─── Services ───

class EmployeeService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = EmployeeRepository(session)

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
        existing = await self.repo.get_by_employee_number(
            data.employee_number, include_deleted=True
        )
        if existing:
            raise DuplicateException("工号", data.employee_number)

        employee = Employee(**data.model_dump())
        if not employee.department:
            employee.department = "未分类"
        employee.status = "在职"

        result = await self.repo.create(employee)

        # 同时创建入职台账记录
        await self._create_onboarding_record(result)

        # 自动根据岗位创建培训台账
        await self._sync_employee_training(result)

        return result

    async def _sync_employee_training(self, employee: Employee) -> None:
        """为新员工自动创建培训台账页面和岗位关联的培训记录。"""
        from app.modules.hr.models import TrainingLedgerPage
        # 创建台账页面
        q = select(TrainingLedgerPage).where(
            TrainingLedgerPage.employee_number == employee.employee_number,
            TrainingLedgerPage.is_deleted == False,
        )
        r = await self.repo.session.execute(q)
        if not r.scalar_one_or_none():
            self.repo.session.add(TrainingLedgerPage(
                employee_number=employee.employee_number,
                employee_name=employee.name,
            ))

        # 根据岗位导入培训内容（兼容带部门前缀和不带前缀的岗位名）
        if employee.position and employee.department:
            pt_q = select(PositionTraining).where(
                PositionTraining.is_deleted == False,
                PositionTraining.department == employee.department,
                or_(
                    PositionTraining.position_name == employee.position,
                    PositionTraining.position_name.endswith(employee.position),
                ),
            )
            pts = (await self.repo.session.execute(pt_q)).scalars().all()
            for pt in pts:
                exist_q = select(TrainingLedger).where(
                    TrainingLedger.employee_number == employee.employee_number,
                    TrainingLedger.training_subject == pt.training_category,
                    TrainingLedger.is_deleted == False,
                )
                ext = await self.repo.session.execute(exist_q)
                if not ext.scalar_one_or_none():
                    self.repo.session.add(TrainingLedger(
                        employee_number=employee.employee_number,
                        training_subject=pt.training_category,
                        training_method=pt.training_method,
                        trainer=pt.trainer,
                        training_date=employee.hire_date or date.today(),
                    ))

    async def _create_onboarding_record(self, employee: Employee) -> None:
        """为新员工创建入职台账记录。"""
        from app.modules.hr.models import OnboardingRecord
        record = OnboardingRecord(
            employee_number=employee.employee_number,
            name=employee.name,
            domain_account=employee.domain_account,
            department=employee.department,
            team=employee.team,
            position=employee.position,
            job_category=employee.job_category,
            status_category=employee.status_category,
            is_employed="是",
            hire_date=employee.hire_date,
            factory_entry_date=employee.factory_entry_date,
            education=employee.education,
            school=employee.school,
            major=employee.major,
            phone=employee.phone,
        )
        self.repo.session.add(record)
        await self.repo.session.flush()

    # ── Excel 列名 → 模型字段名 映射 ──
    _UPLOAD_COLUMN_MAP: dict[str, str] = {
        "工号": "employee_number",
        "姓名": "name",
        "域账号": "domain_account",
        "体现部门": "department",
        "部门": "actual_department",
        "班组": "team",
        "职位": "position",
        "岗位": "job_category",
        "体现岗位": "position",
        "职务": "duty",
        "岗位类别": "job_category",
        "级别": "level",
        "职级": "level",
        "兼任部门": "concurrent_departments",
        "资格": "qualifications",
        "证书": "qualifications",
        "资格类型": "qualification_type",
        "性别": "gender",
        "籍贯": "native_place",
        "政治面貌": "political_status",
        "婚姻状况": "marital_status",
        "户籍类型": "household_type",
        "用工性质": "status_category",
        "员工性质": "status_category",
        "人员状态": "status",
        "出生年份": "birth_year",
        "出生月份": "birth_month",
        "出生日": "birth_day",
        "出生年月": "_birth_date",
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
        "毕业院校": "school",
        "专业": "major",
        "品种": "variety",
        "兼任品种": "variety",
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
        # Excel 扩展字段
        "部门管理者": "dept_manager",
        "额外管理者": "additional_manager",
        "报表用职级": "report_grade",
        "部门负责人/一级培训师": "dept_head_trainer",
        "入职安全培训日期": "safety_training_date",
        "入职安全培训成绩": "safety_training_score",
        "企业文化培训日期": "culture_training_date",
        "GMP基础培训时间": "gmp_training_date",
        "离职时间": "departure_date",
    }

    # Excel 上传时，以下字段全部以 Excel 为准（Excel 中未出现的字段置空）
    _EXCEL_RESETTABLE_FIELDS: set[str] = {
        "name", "domain_account", "department", "actual_department", "team", "position",
        "job_category", "level", "concurrent_departments",
        "qualifications", "qualification_type",
        "gender", "native_place", "political_status", "marital_status",
        "household_type", "status_category",
        "birth_year", "birth_month", "birth_day", "age",
        "work_start_date", "factory_entry_date", "livo_entry_date",
        "hire_date", "graduation_date",
        "work_years", "factory_tenure", "company_tenure",
        "education", "classification", "school", "major", "variety",
        "id_card", "id_card_expiry", "id_card_address", "current_address",
        "contract_type", "contract_start_date", "contract_end_date",
        "contract_start_2", "contract_end_2",
        "contract_start_3", "contract_end_3",
        "contract_start_4", "contract_end_4",
        "phone", "email",
        "emergency_contact_name", "emergency_contact_phone",
        "emergency_contact_relation",
        "bank_account", "training_id", "transfer_history", "remarks",
        "status",
        # Excel 扩展字段
        "duty", "dept_manager", "additional_manager", "report_grade",
        "dept_head_trainer", "safety_training_date", "safety_training_score",
        "culture_training_date", "gmp_training_date", "departure_date",
    }

    _DATE_FIELDS: set[str] = {
        "work_start_date", "factory_entry_date", "livo_entry_date",
        "hire_date", "graduation_date", "id_card_expiry",
        "contract_start_date", "contract_end_date",
        "contract_start_2", "contract_end_2",
        "contract_start_3", "contract_end_3",
        "contract_start_4", "contract_end_4",
        "safety_training_date", "culture_training_date",
        "gmp_training_date", "departure_date",
    }

    _INT_FIELDS: set[str] = {
        "birth_year", "birth_month", "birth_day", "age", "work_years",
    }

    # 常见日期格式（按优先级从高到低排序）
    _DATE_FORMATS: list[str] = [
        "%Y-%m-%d",       # 2024-01-15
        "%Y/%m/%d",       # 2024/01/15
        "%Y.%m.%d",       # 2024.01.15
        "%Y年%m月%d日",    # 2024年01月15日
        "%Y%m%d",         # 20240115
        "%Y-%m-%d %H:%M:%S",       # 2024-01-15 00:00:00
        "%Y/%m/%d %H:%M:%S",       # 2024/01/15 00:00:00
        "%d/%m/%Y",       # 15/01/2024
        "%m/%d/%Y",       # 01/15/2024
    ]

    @staticmethod
    def _parse_date_value(val: object) -> date | None:
        """将各种格式的日期值统一转换为 date 对象。返回 None 表示无法解析。"""
        from datetime import date as date_cls, datetime as datetime_cls

        if isinstance(val, datetime_cls):
            return val.date()
        if isinstance(val, date_cls):
            return val
        if isinstance(val, (int, float)):
            # Excel 日期序列号（以 1899-12-30 为第 0 天）
            try:
                from datetime import timedelta
                excel_epoch = date_cls(1899, 12, 30)
                return excel_epoch + timedelta(days=int(val))
            except (ValueError, OverflowError):
                return None
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return None
            for fmt in EmployeeService._DATE_FORMATS:
                try:
                    return datetime_cls.strptime(val, fmt).date()
                except ValueError:
                    continue
        return None

    async def upload_employees(self, file_bytes: bytes) -> dict:
        """从 Excel 文件批量导入员工，按工号 upsert。返回 {created, updated, errors}。

        每行使用独立的 SQL savepoint，单行失败通过 ROLLBACK TO SAVEPOINT 恢复事务，
        确保失败行不影响其他行。
        """
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

        # 获取底层连接，用于手动管理 savepoint
        conn = await self.repo.session.connection()
        sp_id = 0

        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row):
                continue

            sp_id += 1
            sp_name = f"row_{sp_id}"

            try:
                await conn.execute(text(f"SAVEPOINT {sp_name}"))

                data: dict = {}
                for col_idx, field_name in col_map.items():
                    val = row[col_idx] if col_idx < len(row) else None
                    if val is None or (isinstance(val, str) and val.strip() == ""):
                        continue
                    if isinstance(val, str):
                        val = val.strip()
                    if field_name in self._DATE_FIELDS:
                        parsed = self._parse_date_value(val)
                        if parsed is None:
                            continue
                        val = parsed
                    elif field_name in self._INT_FIELDS:
                        try:
                            val = int(float(str(val)))
                        except (ValueError, TypeError):
                            continue
                    elif field_name == "qualifications":
                        vals = [v.strip() for v in str(val).split(",") if v.strip()]
                        import json as _json
                        val = _json.dumps(vals, ensure_ascii=False)
                    elif field_name == "_birth_date":
                        # 出生年月：datetime 对象 → 拆分为 birth_year / birth_month / birth_day
                        if isinstance(val, (int, float)):
                            parsed_date = self._parse_date_value(val)
                        else:
                            parsed_date = self._parse_date_value(str(val))
                        if parsed_date:
                            data["birth_year"] = parsed_date.year
                            data["birth_month"] = parsed_date.month
                            data["birth_day"] = parsed_date.day
                        continue  # 不把 _birth_date 本身写入 data
                    elif field_name == "status":
                        # 规范化人员状态：'—' 或空 → 默认为在职
                        val_str = str(val).strip()
                        if val_str in ("—", "——", "-", "", "无"):
                            continue  # 跳过，后续默认设为"在职"
                        if val_str in ("在职", "离职", "待审批"):
                            val = val_str
                        else:
                            # 未知状态值，跳过（保留默认"在职"）
                            continue
                    data[field_name] = val

                data.setdefault("position", "")
                data.setdefault("department", "未分类")
                data.setdefault("name", "")

                if "employee_number" not in data:
                    raise ValueError("缺少工号")

                if "hire_date" not in data:
                    data["hire_date"] = date.today()
                if "status" not in data:
                    data["status"] = "在职"

                # ── Excel 没有的字段全部置空，确保完全以 Excel 为准 ──
                for field in self._EXCEL_RESETTABLE_FIELDS:
                    if field not in data:
                        data[field] = None

                is_new = await self.repo.upsert_by_employee_number(data)
                if is_new:
                    created += 1
                else:
                    updated += 1

                await conn.execute(text(f"RELEASE SAVEPOINT {sp_name}"))
            except Exception as e:
                # ROLLBACK TO SAVEPOINT 是 Postgres 恢复事务的唯一方式
                await conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp_name}"))
                await conn.execute(text(f"RELEASE SAVEPOINT {sp_name}"))
                errors.append(f"第{row_idx}行: {e}")

        # ── 上传完成后自动同步部门表 ──
        if created > 0 or updated > 0:
            await self._sync_departments_from_employees()

        return {"created": created, "updated": updated, "errors": errors}

    async def upload_trainers(self, file_bytes: bytes) -> dict:
        """上传内训师 Excel，按姓名+部门 upsert。"""
        from io import BytesIO
        from openpyxl import load_workbook
        from app.modules.hr.models import HrTrainer

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("文件为空")
        header = [str(c).strip() if c else "" for c in rows[0]]
        col_map = {}
        col_name_map = {"姓名": "name", "部门": "department", "可培训部门": "trainable_departments",
                        "资格范围": "qualification_scope", "认证日期": "certification_date",
                        "确认日期": "confirmation_date", "确认提醒": "confirmation_reminder",
                        "是否一级培训师": "is_level1", "培训管理员": "admin", "备注": "remarks"}
        for idx, h in enumerate(header):
            if h in col_name_map:
                col_map[idx] = col_name_map[h]

        created, updated, errors = 0, 0, []
        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row): continue
            try:
                data = {}
                for ci, fn in col_map.items():
                    v = row[ci] if ci < len(row) else None
                    if v is None or (isinstance(v, str) and v.strip() == ""): continue
                    if isinstance(v, str): v = v.strip()
                    if fn in ("certification_date", "confirmation_date", "confirmation_reminder"):
                        v = self._parse_date_value(v)
                    data[fn] = v
                if "name" not in data or "department" not in data:
                    errors.append(f"第{row_idx}行: 缺少姓名或部门"); continue

                q = select(HrTrainer).where(
                    HrTrainer.name == data["name"],
                    HrTrainer.department == data["department"],
                    HrTrainer.is_deleted == False)
                r = await self.repo.session.execute(q)
                existing = r.scalar_one_or_none()
                if existing:
                    for k, v in data.items(): setattr(existing, k, v)
                    updated += 1
                else:
                    self.repo.session.add(HrTrainer(**data))
                    created += 1
                await self.repo.session.flush()
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")
        return {"created": created, "updated": updated, "errors": errors}

    async def upload_sop_catalog(self, file_bytes: bytes) -> dict:
        """上传 SOP 目录 Excel，按 SOP 编号 upsert。"""
        from io import BytesIO
        from openpyxl import load_workbook
        from app.modules.hr.models import SopCatalog, PositionTraining

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows: raise ValueError("文件为空")
        header = [str(c).strip() if c else "" for c in rows[0]]
        col_map = {}
        col_name_map = {"SOP编号": "sop_number", "文件名称": "file_name", "培训类别": "category",
                        "部门": "department", "所属部门": "department", "岗位": "position_name",
                        "体现部门": "department", "SOP名称": "file_name", "文件名": "file_name",
                        "类别": "category", "分类": "category", "培训分类": "category",
                        "职位": "position_name", "岗位名称": "position_name", "培训内容": "file_name"}
        for idx, h in enumerate(header):
            if h in col_name_map: col_map[idx] = col_name_map[h]

        created, updated, errors = 0, 0, []
        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row): continue
            try:
                data = {}
                for ci, fn in col_map.items():
                    v = row[ci] if ci < len(row) else None
                    if v is None or (isinstance(v, str) and v.strip() == ""): continue
                    if isinstance(v, str): v = v.strip()
                    data[fn] = v
                if "file_name" not in data:
                    errors.append(f"第{row_idx}行: 缺少文件名称"); continue

                # 培训内容可能包含逗号分隔的多个条目，拆分为独立记录
                raw_names = str(data["file_name"])
                split_names = [n.strip() for n in raw_names.replace("，", ",").split(",") if n.strip()]
                # 没有培训类别时，用拆分后的值作为类别
                has_category = "category" in data

                for name in split_names:
                    row_data = {**data, "file_name": name}
                    if not has_category:
                        row_data["category"] = name
                    # 去重：有 SOP 编号按编号+文件名匹配，否则按部门+岗位+文件名匹配
                    if row_data.get("sop_number"):
                        q = select(SopCatalog).where(
                            SopCatalog.sop_number == row_data["sop_number"],
                            SopCatalog.file_name == name,
                            SopCatalog.is_deleted == False)
                    else:
                        q = select(SopCatalog).where(
                            SopCatalog.file_name == name,
                            SopCatalog.department == row_data.get("department"),
                            SopCatalog.position_name == row_data.get("position_name"),
                            SopCatalog.is_deleted == False)
                    r = await self.repo.session.execute(q)
                    existing = r.scalar_one_or_none()
                    if existing:
                        for k, v in row_data.items():
                            if v is not None:
                                setattr(existing, k, v)
                        updated += 1
                    else:
                        self.repo.session.add(SopCatalog(**row_data))
                        created += 1
                    await self.repo.session.flush()

                    # 同步写入岗位培训关联表（用于入职培训自动匹配），同样去重
                    if row_data.get("position_name") and row_data.get("department"):
                        pt_category = row_data.get("category") or name
                        pt_q = select(PositionTraining).where(
                            PositionTraining.position_name == row_data["position_name"],
                            PositionTraining.department == row_data["department"],
                            PositionTraining.training_category == pt_category,
                            PositionTraining.is_deleted == False)
                        pt_r = await self.repo.session.execute(pt_q)
                        pt_existing = pt_r.scalar_one_or_none()
                        if pt_existing:
                            pt_existing.file_name = name
                            pt_existing.sop_number = row_data.get("sop_number")
                            pt_existing.updated_at = func.now()
                        else:
                            self.repo.session.add(PositionTraining(
                                position_name=row_data["position_name"],
                                department=row_data["department"],
                                training_category=pt_category,
                                sop_number=row_data.get("sop_number"),
                                file_name=name,
                            ))
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")
        return {"created": created, "updated": updated, "errors": errors}

    async def _sync_departments_from_employees(self) -> int:
        """从员工表同步部门：激活已删除的 + 新增不存在的。"""
        from sqlalchemy import text as sql_text
        conn = await self.repo.session.connection()

        # 1. 激活已存在但被软删除的部门
        r1 = await conn.execute(sql_text("""
            UPDATE hr.departments SET is_deleted = false, updated_at = now()
            WHERE code IN (SELECT DISTINCT department FROM hr.employees WHERE is_deleted = false AND department != '')
              AND is_deleted = true
        """))

        # 2. 新增员工表中有但部门表中不存在的部门
        r2 = await conn.execute(sql_text("""
            INSERT INTO hr.departments (id, name, code, created_at)
            SELECT gen_random_uuid(), e.department, e.department, now()
            FROM (SELECT DISTINCT department FROM hr.employees WHERE is_deleted = false AND department != '') e
            WHERE NOT EXISTS (SELECT 1 FROM hr.departments d WHERE d.code = e.department)
        """))
        return (r1.rowcount or 0) + (r2.rowcount or 0)

    async def approve_employee(self, employee_number: str) -> Employee:
        employee = await self.repo.get_by_employee_number(employee_number)
        if not employee:
            raise NotFoundException("员工", employee_number)
        if employee.status != "待审批":
            raise DuplicateException("审批", "该员工已审批完成")

        employee.status = "在职"
        result = await self.repo.update(employee)
        return result

    async def update_employee(self, employee_id: UUID, data: EmployeeUpdate) -> Employee:
        employee = await self.get_employee(employee_id)
        update_data = data.model_dump(exclude_unset=True)

        if "employee_number" in update_data:
            existing = await self.repo.get_by_employee_number(
                update_data["employee_number"], include_deleted=True
            )
            if existing and existing.id != employee_id:
                raise DuplicateException("工号", update_data["employee_number"])

        for field, value in update_data.items():
            setattr(employee, field, value)

        result = await self.repo.update(employee)
        return result

    async def delete_employee(self, employee_id: UUID) -> None:
        await self.repo.session.execute(text("DELETE FROM hr.employees WHERE id = :id"), {"id": employee_id})

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

    # ── 年度培训计划上传 ──

    _PLAN_COLUMN_MAP: dict[str, str] = {
        "年度": "year",
        "年份": "year",
        "部门": "department",
        "体现部门": "department",
        "品种": "variety",
        "月份": "month",
        "培训时间": "month",
        "培训人数": "trainee_count",
        "课时": "duration_hours",
        "培训内容及使用教材": "content_and_textbook",
        "培训内容": "content_and_textbook",
        "培训对象": "target_audience",
        "参加岗位/参加人数": "position_and_count",
        "授课单位及授课人": "position_and_count",
        "授课单位/培训师": "position_and_count",
        "培训方式": "training_method",
        "考核方式": "assessment_method",
        "培训地点": "location",
        "注意事项": "notes",
        "培训学时": "training_hours",
        "培训跟踪": "tracking_status",
        "确认者": "confirmer",
        "确认人": "confirmer",
        "确认人/日期": "_confirmer_date",
        "确认日期": "confirm_date",
        "实施日期": "confirm_date",
        "提醒实施": "confirm_date",
        "培训季度及课时": "_quarter_hours",
        "部门管理员": "confirmer",
        "备注": "remarks",
    }

    @staticmethod
    def _parse_combined_quarter_hours(raw: str) -> dict:
        """解析导出格式的"培训季度及课时"列：'1月\n8课时' → {month, duration_hours}"""
        result: dict = {}
        if not raw or not raw.strip():
            return result
        parts = [p.strip() for p in raw.replace("\n", " ").split() if p.strip()]
        for part in parts:
            if part.endswith("课时") or part.endswith("学时"):
                try:
                    result["duration_hours"] = float(part.rstrip("课时学时"))
                except ValueError:
                    pass
            elif "月" in part:
                result["month"] = part
            else:
                # 可能是纯数字月份
                try:
                    int(part)
                    result["month"] = f"{part}月"
                except ValueError:
                    pass
        return result

    @staticmethod
    def _parse_combined_confirmer_date(raw: str) -> dict:
        """解析导出格式的"确认人/日期"列：'张三 / 2024-01-15' → {confirmer, confirm_date}"""
        result: dict = {}
        if not raw or not raw.strip():
            return result
        if " / " in raw:
            parts = raw.split(" / ", 1)
            name = parts[0].strip()
            if name:
                result["confirmer"] = name
            date_str = parts[1].strip()
            if date_str:
                parsed = EmployeeService._parse_date_value(date_str)
                if parsed:
                    result["confirm_date"] = parsed
        else:
            # 可能只是确认人名字
            result["confirmer"] = raw.strip()
        return result

    async def upload_annual_plan(self, file_bytes: bytes) -> dict:
        """从 Excel 批量导入年度培训计划，按年度+部门自动分类。

        支持两种 Excel 格式：
        1. 系统导出格式：标题行 → 部门行 → 表头行 → 数据行
        2. 自定义格式：第一行直接为表头，需包含「年度」「部门」列

        每行使用独立 SAVEPOINT，单行失败不影响其他行。
        """
        from io import BytesIO
        from openpyxl import load_workbook
        from app.modules.hr.models import AnnualTrainingPlan, AnnualTrainingPlanItem

        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("文件为空")

        # ── 智能识别表头行：跳过标题行（如 "2026 年培训计划"、"部门：xxx"）──
        header_row_idx = 0
        col_map: dict[int, str] = {}
        for i, row in enumerate(rows):
            candidate = [str(c).strip() if c else "" for c in row]
            mapping = {idx: self._PLAN_COLUMN_MAP[h] for idx, h in enumerate(candidate) if h in self._PLAN_COLUMN_MAP}
            if len(mapping) >= 2:  # 至少有 2 列能匹配才认为是表头行
                header_row_idx = i
                col_map = mapping
                break

        if not col_map:
            raise ValueError(
                "未识别到有效的表头列。支持的列名：年度/年份、部门、月份、培训人数、课时、"
                "培训内容及使用教材、培训对象、参加岗位/参加人数、授课单位及授课人、"
                "培训方式/考核方式、培训跟踪、确认人/确认者/确认人及日期、备注、培训季度及课时"
            )

        has_year_col = "year" in col_map.values()
        has_dept_col = "department" in col_map.values()

        # 如果表头行不含「年度」或「部门」列，尝试从标题行提取缺失的字段
        plan_year: int | None = None
        plan_dept: str | None = None
        if not has_year_col or not has_dept_col:
            for i in range(header_row_idx):
                cell_text = " ".join(
                    [str(c).strip() for c in rows[i] if c is not None]
                ).strip()
                import re
                if not has_year_col:
                    year_match = re.search(r"(\d{4})\s*年", cell_text)
                    if year_match:
                        plan_year = int(year_match.group(1))
                if not has_dept_col:
                    dept_match = re.search(r"部门[：:]\s*(.+)", cell_text)
                    if dept_match:
                        plan_dept = dept_match.group(1).strip()
            if not has_year_col and plan_year is None:
                plan_year = date.today().year
            if not has_dept_col and plan_dept is None:
                raise ValueError(
                    "Excel 表头缺少「部门」列，且标题行未找到「部门：xxx」。"
                    "请在 Excel 中添加「部门」列，或在标题行写明「部门：xxx」"
                )

        # ── 逐行解析数据（用 begin_nested 做行级 SAVEPOINT 隔离）──
        plan_cache: dict[tuple, AnnualTrainingPlan] = {}
        created, updated, errors = 0, 0, []
        skip_fields = {"year", "department", "_quarter_hours", "_confirmer_date", "variety"}

        data_start = header_row_idx + 1
        for row_idx, row in enumerate(rows[data_start:], start=data_start + 1):
            if all(c is None for c in row):
                continue

            # ── 先解析数据（无 DB 操作），做预校验 ──
            data: dict = {}
            for ci, fn in col_map.items():
                v = row[ci] if ci < len(row) else None
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    continue
                if isinstance(v, str):
                    v = v.strip()

                # 处理组合列
                if fn == "_quarter_hours":
                    combined = self._parse_combined_quarter_hours(str(v))
                    data.update(combined)
                    continue
                if fn == "_confirmer_date":
                    combined = self._parse_combined_confirmer_date(str(v))
                    data.update(combined)
                    continue

                if fn == "month" and isinstance(v, str) and len(v) > 16:
                    v = v[:16]
                if fn == "year":
                    v = int(float(str(v)))
                if fn in ("trainee_count",):
                    v = int(float(str(v)))
                if fn in ("duration_hours", "training_hours"):
                    try:
                        s = str(v).strip().rstrip('hH小时课时')
                        v = float(s)
                    except (ValueError, TypeError):
                        continue
                if fn == "confirm_date":
                    parsed = self._parse_date_value(v)
                    if parsed:
                        v = parsed
                    else:
                        continue
                data[fn] = v

            # 预校验：必须有部门和有效数据
            dept = data.get("department", "") or plan_dept or ""
            year = data.get("year") or plan_year or date.today().year
            if not dept:
                errors.append(f"第{row_idx}行: 缺少部门")
                continue

            item_data = {k: v for k, v in data.items() if k not in skip_fields}
            if not item_data:
                errors.append(f"第{row_idx}行: 无有效数据")
                continue

            cache_key = (int(year), str(dept))

            # ── DB 操作放在嵌套事务内，单行失败不影响其他行 ──
            try:
                nested = await self.repo.session.begin_nested()

                # 找或创建年度计划
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
                        plan = AnnualTrainingPlan(year=int(year), department=str(dept), status="草稿")
                        self.repo.session.add(plan)
                        await self.repo.session.flush()
                    plan_cache[cache_key] = plan

                # 添加计划项（去重：同计划+同内容+同月份视为重复，跳过）
                content = item_data.get("content_and_textbook") or ""
                month_val = item_data.get("month") or ""
                existing_item = (await self.repo.session.execute(
                    select(AnnualTrainingPlanItem).where(
                        AnnualTrainingPlanItem.plan_id == plan.id,
                        AnnualTrainingPlanItem.content_and_textbook == content,
                        AnnualTrainingPlanItem.month == month_val,
                        AnnualTrainingPlanItem.is_deleted == False,
                    )
                )).scalar_one_or_none()
                if existing_item:
                    for k, v in item_data.items():
                        setattr(existing_item, k, v)
                    updated += 1
                else:
                    item = AnnualTrainingPlanItem(plan_id=plan.id, **item_data)
                    self.repo.session.add(item)
                    created += 1
                await self.repo.session.flush()

                await nested.commit()
            except Exception as e:
                await nested.rollback()
                # 清除可能已失效的缓存（plan 在本次嵌套事务中新建但被回滚了）
                plan_cache.pop(cache_key, None)
                errors.append(f"第{row_idx}行: {e}")

        return {"created": created, "updated": updated, "errors": errors}

class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DepartmentRepository(session)

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
        return result

    async def delete_department(self, department_id: UUID) -> None:
        await self.repo.session.execute(text("DELETE FROM hr.departments WHERE id = :id"), {"id": department_id})

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
        from sqlalchemy import select, text, func, or_, func
        from app.modules.hr.models import Employee
        for dept in departments:
            count = await self.repo.session.scalar(
                select(func.count()).select_from(Employee).where(
                    Employee.department == dept.name,
                    Employee.is_deleted.is_(False),
                    Employee.status != "离职",
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
        await self.repo.session.execute(text("DELETE FROM hr.teams WHERE id = :id"), {"id": team_id})

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

        return record

    async def update_record(self, record_id: UUID, data: OffboardingRecordUpdate) -> OffboardingRecord:
        record = await self.get_record(record_id)
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(record, field, value)

        result = await self.repo.update(record)

        return result

    async def delete_record(self, record_id: UUID) -> None:
        await self.repo.session.execute(text("DELETE FROM hr.offboarding_records WHERE id = :id"), {"id": record_id})

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
        days: int = 7,
    ) -> tuple[list[OnboardingRecord], int]:
        if days > 0:
            await self._cleanup_old_records(days)
        return await self.repo.list_records(
            department=department,
            position=position,
            is_employed=is_employed,
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            days=days,
        )

    async def delete_record(self, record_id: UUID) -> None:
        await self.repo.session.execute(text("DELETE FROM hr.onboarding_records WHERE id = :id"), {"id": record_id})

    async def _cleanup_old_records(self, days: int) -> None:
        """软删除超过 N 天的入职台账记录。"""
        from sqlalchemy import text as sql_text
        await self.repo.session.execute(sql_text("""
            UPDATE hr.onboarding_records SET is_deleted = true, updated_at = now()
            WHERE is_deleted = false AND created_at < now() - make_interval(days => :days)
        """), {"days": days})

class DepartureRecordService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DepartureRecordRepository(session)
        self.employee_repo = EmployeeRepository(session)

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
        record = await self.repo.create(record)

        # 自动将对应员工状态更新为离职（按姓名+部门匹配）
        employee = await self.employee_repo.get_by_name_and_department(data.name, data.department)
        if employee and employee.status != "离职":
            employee.status = "离职"
            await self.employee_repo.update(employee)

        # 同步更新入职台账为不在职，确保所有列表过滤生效
        from app.modules.hr.models import OnboardingRecord
        onboarding_q = select(OnboardingRecord).where(
            OnboardingRecord.name == data.name,
            OnboardingRecord.department == data.department,
            OnboardingRecord.is_deleted == False,
        )
        onboarding_r = await self.repo.session.execute(onboarding_q)
        for onboarding in onboarding_r.scalars().all():
            if onboarding.is_employed != "否":
                onboarding.is_employed = "否"
                self.repo.session.add(onboarding)

        await self.repo.session.flush()
        return record

    async def update_record(self, record_id: UUID, data: DepartureRecordUpdate) -> DepartureRecord:
        record = await self.get_record(record_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(record, field, value)
        return await self.repo.update(record)

    async def delete_record(self, record_id: UUID) -> None:
        # 恢复入职台账的在职状态和员工状态
        record = await self.get_record(record_id)
        from app.modules.hr.models import OnboardingRecord
        onboarding_q = select(OnboardingRecord).where(
            OnboardingRecord.name == record.name,
            OnboardingRecord.department == record.department,
            OnboardingRecord.is_deleted == False,
        )
        onboarding_r = await self.repo.session.execute(onboarding_q)
        for onboarding in onboarding_r.scalars().all():
            onboarding.is_employed = "是"
            self.repo.session.add(onboarding)

        employee = await self.employee_repo.get_by_name_and_department(record.name, record.department)
        if employee and employee.status == "离职":
            employee.status = "在职"
            await self.employee_repo.update(employee)

        await self.repo.session.execute(text("DELETE FROM hr.departure_records WHERE id = :id"), {"id": record_id})

class TrainingLedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = TrainingLedgerRepository(session)

    async def get_record(self, record_id: UUID) -> TrainingLedger:
        record = await self.repo.get_by_id(record_id)
        if not record:
            raise NotFoundException("培训台账记录", str(record_id))
        return record

    async def create_record(self, data: TrainingLedgerCreate) -> TrainingLedger:
        # 去重：同员工+同日期+同主题视为重复
        existing = await self.repo.session.execute(
            select(TrainingLedger).where(
                TrainingLedger.employee_number == data.employee_number,
                TrainingLedger.training_date == data.training_date,
                TrainingLedger.training_subject == data.training_subject,
                TrainingLedger.is_deleted == False,
            )
        )
        dup = existing.scalar_one_or_none()
        if dup:
            return dup
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
        await self.repo.session.execute(text("DELETE FROM hr.training_ledgers WHERE id = :id"), {"id": record_id})

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
        # 排除已离职员工的培训记录
        from app.modules.hr.models import OnboardingRecord
        departed_subq = select(OnboardingRecord.employee_number).where(
            OnboardingRecord.is_deleted == False,
            OnboardingRecord.is_employed == "否",
        )
        return await self.repo.list_records(
            employee_number=employee_number,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            exclude_employee_numbers=departed_subq,
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
        await self.repo.session.execute(text("DELETE FROM hr.annual_training_plans WHERE id = :id"), {"id": plan_id})

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
