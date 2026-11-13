"""HR business workflows live here."""

import asyncio
import logging
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy import update as _update_stmt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.hr.models import (
    AnnualTrainingPlan,
    AnnualTrainingPlanItem,
    Candidate,
    CandidateAnalysisReport,
    CandidateReview,
    CandidateStatusLog,
    DepartureRecord,
    DeptTrainingPersonnel,
    Employee,
    HrDepartment,
    Interview,
    InterviewFeedback,
    InterviewStatusLog,
    JobRequirement,
    MonthlyPerformanceEvaluation,
    OffboardingRecord,
    OnboardingRecord,
    OnboardingTask,
    PositionTraining,
    Team,
    TrainingLedger,
    TrainingLedgerPage,
)
from app.modules.hr.repository import (
    AnnualTrainingPlanItemRepository,
    AnnualTrainingPlanRepository,
    CandidateAnalysisReportRepository,
    CandidateRepository,
    CandidateReviewRepository,
    CandidateStatusLogRepository,
    DepartmentRepository,
    DepartureRecordRepository,
    EmployeeRepository,
    InterviewFeedbackRepository,
    InterviewRepository,
    JobRequirementRepository,
    OffboardingRecordRepository,
    OnboardingRecordRepository,
    PerformanceEvaluationRepository,
    TeamRepository,
    TrainingLedgerPageRepository,
    TrainingLedgerRepository,
)
from app.modules.hr.schemas import (
    AnnualTrainingPlanCreate,
    AnnualTrainingPlanItemBatchUpdate,
    AnnualTrainingPlanUpdate,
    CandidateCreate,
    CandidateUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    DepartureRecordCreate,
    DepartureRecordUpdate,
    EmployeeCreate,
    EmployeeUpdate,
    InterviewCreate,
    InterviewFeedbackIn,
    InterviewUpdate,
    JobRequirementCreate,
    JobRequirementUpdate,
    OffboardingRecordCreate,
    OffboardingRecordUpdate,
    PerformanceEvaluationCreate,
    PerformanceEvaluationUpdate,
    PerformanceListParams,
    TeamCreate,
    TeamUpdate,
    TrainingLedgerCreate,
    TrainingLedgerUpdate,
)

if TYPE_CHECKING:
    from app.modules.hr.deps import HrAccessContext

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

    async def _ensure_employees_writable(self) -> None:
        """员工档案同步启用期间档案为只读镜像（后端守卫：防止绕过前端隐藏直接调 API）。

        经 API 手工新建的员工没有 feishu_record_id，永远不会被同步管理，
        其编辑结果也会被下一轮对账覆盖，因此创建/更新/删除一律拒绝。
        """
        from app.modules.hr.employee_sync.config import load_config

        cfg = await load_config(self.repo.session)
        if cfg.is_ready:
            raise AppException(
                status_code=409,
                detail="员工档案同步已启用：档案由飞书多维表格单向维护，"
                       "请在源数据表中新增/修改/删除后等待同步",
            )

    async def create_employee(self, data: EmployeeCreate) -> Employee:
        await self._ensure_employees_writable()
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

        # 同步进入培训人员名单（复制白名单初值；手动新建的员工也进名单）
        await self._ensure_roster_for_new_employee(result)

        return result

    async def _ensure_roster_for_new_employee(self, employee: Employee) -> None:
        """新员工进入培训名单（软删同工号行复活并刷新初值，避免唯一约束冲突）。"""
        from sqlalchemy import select as _select

        from app.modules.hr.employee_sync.config import ROSTER_INITIAL_FIELDS
        from app.modules.hr.models import TrainingRosterProfile
        existing_profile = (await self.repo.session.execute(
            _select(TrainingRosterProfile).where(
                TrainingRosterProfile.employee_number == employee.employee_number,
            )
        )).scalar_one_or_none()
        profile = existing_profile or TrainingRosterProfile(
            employee_number=employee.employee_number,
        )
        # 白名单 + level（level 不外显，但 report_level 分级依赖它）
        for attr in ROSTER_INITIAL_FIELDS:
            setattr(profile, attr, getattr(employee, attr, None))
        if not profile.department:
            profile.department = "未分类"
        if not profile.position:
            profile.position = ""
        if not profile.name:
            profile.name = ""
        profile.is_deleted = False  # 历史软删行复活并刷新初值（工号重现=重新进入名单）
        if existing_profile is None:
            self.repo.session.add(profile)
        await self.repo.session.flush()

    async def _sync_employee_training(self, employee: Employee) -> None:
        """为新员工自动创建培训台账页面和岗位关联的培训记录。"""
        from app.modules.hr.models import TrainingLedgerPage
        # 创建台账页面
        q = select(TrainingLedgerPage).where(
            TrainingLedgerPage.employee_number == employee.employee_number,
            TrainingLedgerPage.is_deleted == False,  # noqa: E712
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
                PositionTraining.is_deleted == False,  # noqa: E712
                PositionTraining.department == employee.department,
                or_(
                    PositionTraining.position_name == employee.position,
                    PositionTraining.position_name.endswith(employee.position),
                ),
            )
            pts = (await self.repo.session.execute(pt_q)).scalars().all()
            existing_subjects = set((await self.repo.session.execute(
                select(TrainingLedger.training_subject).where(
                    TrainingLedger.employee_number == employee.employee_number,
                    TrainingLedger.is_deleted == False,  # noqa: E712
                )
            )).scalars().all())
            for pt in pts:
                if pt.training_category in existing_subjects:
                    continue
                existing_subjects.add(pt.training_category)
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
            position=employee.position,
            job_category=employee.job_category,
            status_category=employee.status_category,
            is_employed="是",
            hire_date=employee.hire_date,
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
        # 新数据源只有一个「部门」概念：直接落体现部门（权限判定/培训名单
        # NOT NULL/看板分组都吃 department）
        "部门": "department",
        "职位": "position",
        # 新数据源「岗位」是岗位族（会计/采购/IT…），作为职位；职类由「职能分类」承载
        "岗位": "position",
        "体现岗位": "position",
        "职务": "duty",
        "岗位类别": "job_category",
        "级别": "level",
        "职级": "level",
        "证书": "certificates",
        "性别": "gender",
        "籍贯": "native_place",
        "婚姻状况": "marital_status",
        "户籍类型": "household_type",
        "用工性质": "status_category",
        "员工性质": "status_category",
        "人员状态": "status",
        "出生年份": "birth_year",
        "出生月份": "birth_month",
        "出生日": "birth_day",
        "出生年月": "_birth_date",
        "参加工作时间": "work_start_date",
        "入职日期": "hire_date",
        "毕业时间": "graduation_date",
        "公司工龄": "company_tenure",
        "学历": "education",
        "分类": "classification",
        "毕业学校": "school",
        "毕业院校": "school",
        "专业": "major",
        "身份证号": "id_card",
        "身份证号码": "id_card",
        "身份证有效期": "id_card_expiry",
        "现居住地址": "current_address",
        "合同开始日期": "contract_start_date",
        "合同结束日期": "contract_end_date",
        "手机": "phone",
        "紧急联系人": "emergency_contact_name",
        "紧急联系人电话": "emergency_contact_phone",
        "紧急联系人关系": "emergency_contact_relation",
        "调动历史": "transfer_history",
        "报表用职级": "report_grade",
        "离职时间": "departure_date",
        # ── 新数据源（飞书「员工信息表」）列名别名；追加在末尾保证导出列头稳定 ──
        "户口类型": "household_type",
        "出生日期": "_birth_date",
        "司龄": "company_tenure",
        "学习形式": "classification",
        "联系电话": "phone",
        "居住地址": "current_address",
        "紧急联系人-姓名": "emergency_contact_name",
        "紧急联系人-联系电话": "emergency_contact_phone",
        "紧急联系人-关系": "emergency_contact_relation",
        "离职日期": "departure_date",
        "任命与岗位调动": "transfer_history",
        "岗位职级": "report_grade",
        "职能分类": "job_category",
        "员工账号": "feishu_open_id",
        "民族": "ethnicity",
        "离职原因": "departure_reason",
        "学位类型": "degree_type",
        "毕业证书": "graduation_certificate",
        "人力资源分析": "hr_analysis",
    }

    # Excel 上传时，以下字段全部以 Excel 为准（Excel 中未出现的字段置空）
    _EXCEL_RESETTABLE_FIELDS: set[str] = {
        "name", "domain_account", "department", "position",
        "job_category", "level",
        "gender", "native_place", "marital_status",
        "household_type", "status_category",
        "birth_year", "birth_month", "birth_day",
        "work_start_date",
        "hire_date", "graduation_date",
        "company_tenure",
        "education", "classification", "school", "major",
        "id_card", "id_card_expiry", "current_address",
        "contract_start_date", "contract_end_date",
        "phone",
        "emergency_contact_name", "emergency_contact_phone",
        "emergency_contact_relation",
        "transfer_history",
        "certificates",
        "duty", "report_grade", "departure_date",
        # 新数据源字段
        "ethnicity", "departure_reason", "degree_type",
        "graduation_certificate", "hr_analysis",
    }

    _DATE_FIELDS: set[str] = {
        "work_start_date",
        "hire_date", "graduation_date", "id_card_expiry",
        "contract_start_date", "contract_end_date",
        "departure_date",
    }

    _INT_FIELDS: set[str] = {
        "birth_year", "birth_month", "birth_day",
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
        from datetime import date as date_cls
        from datetime import datetime as datetime_cls

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

    async def upload_trainers(self, file_bytes: bytes, allowed_departments: set[str] | None = None) -> dict:
        """上传内训师 Excel，按姓名+部门 upsert。allowed_departments 非空时仅导入该范围内的部门。"""
        from io import BytesIO

        from openpyxl import load_workbook

        from app.modules.hr.models import HrTrainer

        wb = await asyncio.to_thread(load_workbook, BytesIO(file_bytes), data_only=True)
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

        created, updated, skipped, errors = 0, 0, 0, []
        for row_idx, row in enumerate(rows[1:], start=2):
            if all(c is None for c in row):
                continue
            outcome = ""
            try:
                # SQLAlchemy 原生 SAVEPOINT：flush 失败只回滚本行，不毒化整个导入
                async with self.repo.session.begin_nested():
                    data = {}
                    for ci, fn in col_map.items():
                        v = row[ci] if ci < len(row) else None
                        if v is None or (isinstance(v, str) and v.strip() == ""):
                            continue
                        if isinstance(v, str):
                            v = v.strip()
                        if fn in ("certification_date", "confirmation_date", "confirmation_reminder"):
                            parsed = self._parse_date_value(v)
                            if parsed is None:
                                # 非空但无法解析：跳过该列，不能清空已有日期
                                continue
                            v = parsed
                        data[fn] = v
                    if "name" not in data or "department" not in data:
                        outcome = "error_missing"
                    elif allowed_departments is not None and data.get("department") not in allowed_departments:
                        outcome = "skipped"
                    else:
                        q = select(HrTrainer).where(
                            HrTrainer.name == data["name"],
                            HrTrainer.department == data["department"],
                            HrTrainer.is_deleted == False)  # noqa: E712
                        r = await self.repo.session.execute(q)
                        existing = r.scalar_one_or_none()
                        if existing:
                            for k, v in data.items():
                                setattr(existing, k, v)
                            outcome = "updated"
                        else:
                            self.repo.session.add(HrTrainer(**data))
                            outcome = "created"
                        await self.repo.session.flush()
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")
                continue
            if outcome == "updated":
                updated += 1
            elif outcome == "created":
                created += 1
            elif outcome == "skipped":
                skipped += 1
            elif outcome == "error_missing":
                errors.append(f"第{row_idx}行: 缺少姓名或部门")
        return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}

    async def upload_sop_catalog(
        self, file_bytes: bytes, allowed_departments: set[str] | None = None,
    ) -> dict:
        """上传 SOP 目录 Excel，按 SOP 编号 + 部门 upsert。"""
        from io import BytesIO

        from openpyxl import load_workbook

        from app.modules.hr.models import PositionTraining, SopCatalog

        wb = await asyncio.to_thread(load_workbook, BytesIO(file_bytes), data_only=True)
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
            if all(c is None for c in row):
                continue
            row_created = row_updated = 0
            try:
                # SQLAlchemy 原生 SAVEPOINT：flush 失败只回滚本行，不毒化整个导入
                async with self.repo.session.begin_nested():
                    data = {}
                    for ci, fn in col_map.items():
                        v = row[ci] if ci < len(row) else None
                        if v is None or (isinstance(v, str) and v.strip() == ""):
                            continue
                        if isinstance(v, str):
                            v = v.strip()
                        data[fn] = v
                    if "file_name" not in data:
                        errors.append(f"第{row_idx}行: 缺少文件名称")
                        continue
                    # 行级数据范围：受限用户只导入授权部门
                    if (
                        allowed_departments is not None
                        and data.get("department")
                        and data["department"] not in allowed_departments
                    ):
                        continue

                    # 培训内容可能包含逗号分隔的多个条目，拆分为独立记录
                    raw_names = str(data["file_name"])
                    split_names = [n.strip() for n in raw_names.replace("，", ",").split(",") if n.strip()]
                    # 没有培训类别时，用拆分后的值作为类别
                    has_category = "category" in data

                    for name in split_names:
                        row_data = {**data, "file_name": name}
                        if not has_category:
                            row_data["category"] = name
                        # 去重必须带部门：否则相同 SOP 编号会跨部门覆盖别人的目录行
                        if row_data.get("sop_number"):
                            q = select(SopCatalog).where(
                                SopCatalog.sop_number == row_data["sop_number"],
                                SopCatalog.file_name == name,
                                SopCatalog.department == row_data.get("department"),
                                SopCatalog.is_deleted == False)  # noqa: E712
                        else:
                            q = select(SopCatalog).where(
                                SopCatalog.file_name == name,
                                SopCatalog.department == row_data.get("department"),
                                SopCatalog.position_name == row_data.get("position_name"),
                                SopCatalog.is_deleted == False)  # noqa: E712
                        r = await self.repo.session.execute(q)
                        existing = r.scalar_one_or_none()
                        if existing:
                            for k, v in row_data.items():
                                if v is not None:
                                    setattr(existing, k, v)
                            row_updated += 1
                        else:
                            self.repo.session.add(SopCatalog(**row_data))
                            row_created += 1

                        # 同步写入岗位培训关联表（用于入职培训自动匹配），同样去重
                        if row_data.get("position_name") and row_data.get("department"):
                            pt_category = row_data.get("category") or name
                            pt_q = select(PositionTraining).where(
                                PositionTraining.position_name == row_data["position_name"],
                                PositionTraining.department == row_data["department"],
                                PositionTraining.training_category == pt_category,
                                PositionTraining.is_deleted == False)  # noqa: E712
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
                    await self.repo.session.flush()
            except Exception as e:
                errors.append(f"第{row_idx}行: {e}")
                continue
            created += row_created
            updated += row_updated
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
        await self._ensure_employees_writable()
        employee = await self.get_employee(employee_id)
        update_data = data.model_dump(exclude_unset=True)

        # 工号/姓名/性别/身份证号为身份标识字段，仅创建时允许填写；
        # 更新接口直接忽略（前端已禁用输入，此处防止绕过界面直接调 API 修改）
        for protected in ("employee_number", "name", "gender", "id_card"):
            update_data.pop(protected, None)

        for field, value in update_data.items():
            setattr(employee, field, value)

        result = await self.repo.update(employee)

        # 人员状态随总表同步到培训名单（病产假统计/SOP选人/通知名单都走名单口径，
        # 同步未启用时定时对账不会兜底，必须在状态变更处即时同步）
        if "status" in update_data:
            from sqlalchemy import update as _update

            from app.modules.hr.models import TrainingRosterProfile
            await self.repo.session.execute(
                _update(TrainingRosterProfile)
                .where(
                    TrainingRosterProfile.employee_number == employee.employee_number,
                    TrainingRosterProfile.is_deleted.is_(False),
                )
                .values(status=employee.status)
            )
        return result

    async def delete_employee(self, employee_id: UUID) -> None:
        await self._ensure_employees_writable()
        employee = await self.repo.get_by_id(employee_id)
        if not employee:
            raise NotFoundException("员工", str(employee_id))
        employee.is_deleted = True
        await self.repo.update(employee)
        # 培训名单同步移出（人员增减语义；不等定时对账兜底）
        from sqlalchemy import update as _update

        from app.modules.hr.models import TrainingRosterProfile
        await self.repo.session.execute(
            _update(TrainingRosterProfile)
            .where(
                TrainingRosterProfile.employee_number == employee.employee_number,
                TrainingRosterProfile.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )

    async def list_employees(
        self,
        *,
        department: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "department",
        sort_order: str = "asc",
        include_uncategorized: bool = False,
        departments: set[str] | None = None,
    ) -> tuple[list[Employee], int]:
        return await self.repo.list_employees(
            department=department,
            include_uncategorized=include_uncategorized,
            departments=departments,
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

    async def upload_annual_plan(
        self, file_bytes: bytes, *, allowed_departments: set[str] | None = None,
    ) -> dict:
        """从 Excel 批量导入年度培训计划，按年度+部门自动分类。

        支持两种 Excel 格式：
        1. 系统导出格式：标题行 → 部门行 → 表头行 → 数据行
        2. 自定义格式：第一行直接为表头，需包含「年度」「部门」列

        allowed_departments 非 None 时行级过滤：仅接受授权部门（及全员可见的
        「厂级」）的数据行，越权行计入 errors 跳过。
        每行使用独立 SAVEPOINT，单行失败不影响其他行。
        """
        from io import BytesIO

        from openpyxl import load_workbook

        from app.modules.hr.models import AnnualTrainingPlan, AnnualTrainingPlanItem

        wb = await asyncio.to_thread(load_workbook, BytesIO(file_bytes), data_only=True)
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
            parse_error = ""
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
                if fn in ("year", "trainee_count"):
                    try:
                        v = int(float(str(v)))
                    except (ValueError, TypeError):
                        parse_error = "年度格式不正确" if fn == "year" else "培训人数格式不正确"
                        break
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

            if parse_error:
                errors.append(f"第{row_idx}行: {parse_error}")
                continue

            # 预校验：必须有部门和有效数据
            dept = data.get("department", "") or plan_dept or ""
            year = data.get("year") or plan_year or date.today().year
            if not dept:
                errors.append(f"第{row_idx}行: 缺少部门")
                continue
            # 行级数据范围：受限用户仅可导入授权部门（「厂级」培训全员可见可操作）
            if (
                allowed_departments is not None
                and dept != "厂级"
                and dept not in allowed_departments
            ):
                errors.append(f"第{row_idx}行: 部门「{dept}」不在授权范围内，已跳过")
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
                        AnnualTrainingPlan.is_deleted == False,  # noqa: E712
                    )
                    r = await self.repo.session.execute(q)
                    plan = r.scalar_one_or_none()
                    if not plan:
                        plan = AnnualTrainingPlan(year=int(year), department=str(dept), status="草稿")
                        self.repo.session.add(plan)
                        await self.repo.session.flush()
                    plan_cache[cache_key] = plan

                # 添加计划项（去重：同计划+同内容+同月份视为重复，跳过）
                # 缺失值入库是 NULL，不能拿空串去比较，否则重传会不断新增重复行
                content = item_data.get("content_and_textbook")
                month_val = item_data.get("month")
                content_cond = (
                    AnnualTrainingPlanItem.content_and_textbook == content
                    if content else AnnualTrainingPlanItem.content_and_textbook.is_(None)
                )
                month_cond = (
                    AnnualTrainingPlanItem.month == month_val
                    if month_val else AnnualTrainingPlanItem.month.is_(None)
                )
                existing_item = (await self.repo.session.execute(
                    select(AnnualTrainingPlanItem).where(
                        AnnualTrainingPlanItem.plan_id == plan.id,
                        content_cond,
                        month_cond,
                        AnnualTrainingPlanItem.is_deleted == False,  # noqa: E712
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
        from sqlalchemy import func, select

        from app.modules.hr.models import Employee
        for dept in departments:
            # 人数不过滤状态：与看板部门分布同口径（仅软删不计）
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

async def _sync_roster_status(
    session: AsyncSession, employee_number: str | None, status: str,
) -> None:
    """离职/复职时同步培训名单状态（培训统计/SOP 选人读名单口径）。

    名单字段独立维护，但 status 是动态事实，必须随总表即时更新；
    否则在 02:00 对账前（或同步未启用时）离职者仍会出现在培训名单里。
    """
    if not employee_number:
        return
    from sqlalchemy import update as _update

    from app.modules.hr.models import TrainingRosterProfile

    await session.execute(
        _update(TrainingRosterProfile)
        .where(
            TrainingRosterProfile.employee_number == employee_number,
            TrainingRosterProfile.is_deleted.is_(False),
        )
        .values(status=status)
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
        await _sync_roster_status(
            self.repo.session, employee.employee_number, "离职",
        )

        return record

    async def update_record(self, record_id: UUID, data: OffboardingRecordUpdate) -> OffboardingRecord:
        record = await self.get_record(record_id)
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(record, field, value)

        result = await self.repo.update(record)

        return result

    async def delete_record(self, record_id: UUID) -> None:
        # 删除离职记录时恢复员工在职状态（与 departure 流程对称）
        record = await self.get_record(record_id)
        if record and record.employee_id:
            employee = await self.employee_repo.get_by_id(record.employee_id)
            if employee and employee.status == "离职":
                employee.status = "在职"
                await self.employee_repo.update(employee)
                await _sync_roster_status(
                    self.repo.session, employee.employee_number, "在职",
                )
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
        departments: set[str] | None = None,
        offboarding_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "offboarding_date",
        sort_order: str = "desc",
    ) -> tuple[list[DepartureRecord], int]:
        return await self.repo.list_records(
            department=department,
            departments=departments,
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
            await _sync_roster_status(
                self.repo.session, employee.employee_number, "离职",
            )

        # 同步更新入职台账为不在职，确保所有列表过滤生效
        from app.modules.hr.models import OnboardingRecord
        onboarding_q = select(OnboardingRecord).where(
            OnboardingRecord.name == data.name,
            OnboardingRecord.department == data.department,
            OnboardingRecord.is_deleted == False,  # noqa: E712
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
            OnboardingRecord.is_deleted == False,  # noqa: E712
        )
        onboarding_r = await self.repo.session.execute(onboarding_q)
        for onboarding in onboarding_r.scalars().all():
            onboarding.is_employed = "是"
            self.repo.session.add(onboarding)

        employee = await self.employee_repo.get_by_name_and_department(record.name, record.department)
        if employee and employee.status == "离职":
            employee.status = "在职"
            await self.employee_repo.update(employee)
            await _sync_roster_status(
                self.repo.session, employee.employee_number, "在职",
            )

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
                TrainingLedger.is_deleted == False,  # noqa: E712
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
        record.is_deleted = True
        await self.repo.session.flush()

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
            OnboardingRecord.is_deleted == False,  # noqa: E712
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
        """软删计划（先软删其明细；原硬删在有明细时触发 FK 违规 500）。"""
        from app.modules.hr.models import AnnualTrainingPlanItem
        await self.repo.session.execute(
            _update_stmt(AnnualTrainingPlanItem)
            .where(
                AnnualTrainingPlanItem.plan_id == plan_id,
                AnnualTrainingPlanItem.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        await self.repo.session.execute(
            _update_stmt(AnnualTrainingPlan)
            .where(
                AnnualTrainingPlan.id == plan_id,
                AnnualTrainingPlan.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )

    async def list_plans(
        self,
        *,
        year: int | None = None,
        department: str | None = None,
        departments: set[str] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AnnualTrainingPlan], int]:
        return await self.repo.list_plans(
            year=year,
            department=department,
            departments=departments,
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

        # 创建新明细（统一 add 后一次 flush，避免 N 次往返）
        results: list[AnnualTrainingPlanItem] = []
        for idx, item_data in enumerate(data.items):
            item = AnnualTrainingPlanItem(
                plan_id=plan_id,
                sort_order=idx,
                **item_data.model_dump(exclude={"sort_order"}),
            )
            self.repo.session.add(item)
            results.append(item)
        if results:
            await self.repo.session.flush()
        return results


# ─── Recruitment Services ───

# 候选人状态流转规则
_CANDIDATE_TRANSITIONS: dict[str, set[str]] = {
    "待筛选": {"已筛选", "已拒绝"},
    "已筛选": {"待部门审核", "已拒绝"},
    "待部门审核": {"面试中", "已拒绝"},
    "面试中": {"已面试", "已拒绝"},
    "已面试": {"录用中", "已拒绝"},
    "录用中": {"已录用", "已拒绝"},
    "已录用": {"待入职审批", "已拒绝"},
    # 已入职只能由 onboard() 完成（创建入职记录/工号/子任务），
    # 不允许裸状态流转绕过入职链
    "待入职审批": {"已录用", "已拒绝"},
    "已拒绝": set(),
}


class JobRequirementService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = JobRequirementRepository(session)

    async def list_all(
        self, *, status: str | None = None, departments: list[str] | None = None,
    ) -> list[JobRequirement]:
        return await self.repo.list_all(status=status, departments=departments)

    async def get(self, req_id: UUID) -> JobRequirement:
        req = await self.repo.get_by_id(req_id)
        if not req:
            raise NotFoundException("岗位需求", str(req_id))
        return req

    async def create(self, data: JobRequirementCreate) -> JobRequirement:
        req = JobRequirement(**data.model_dump())
        return await self.repo.create(req)

    async def update(self, req_id: UUID, data: JobRequirementUpdate) -> JobRequirement:
        req = await self.get(req_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(req, k, v)
        return await self.repo.update(req)

    async def delete(self, req_id: UUID) -> dict:
        """删除岗位需求（仅限已关闭）：级联清理名下未入职候选人。

        招聘中岗位必须先关闭再删——防止误删进行中的需求及其候选人；
        已入职候选人不清理（已生成员工档案与入职记录，留作溯源）。
        """
        req = await self.get(req_id)
        if req.status == "招聘中":
            raise ValueError("岗位仍在招聘中，请先在「编辑」中改为已关闭，再删除")
        return await self.repo.soft_delete_with_candidates(req.id)


class CandidateService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = CandidateRepository(session)
        self.log_repo = CandidateStatusLogRepository(session)

    async def list_all(
        self, *, job_requirement_id: UUID | None = None, status: str | None = None,
        keyword: str | None = None, candidate_type: str | None = None,
        departments: list[str] | None = None, reviewer: str | None = None,
        page: int = 1, page_size: int = 100,
    ) -> tuple[list[Candidate], int]:
        return await self.repo.list_all(
            job_requirement_id=job_requirement_id, status=status,
            keyword=keyword, candidate_type=candidate_type,
            departments=departments, reviewer=reviewer,
            page=page, page_size=page_size,
        )

    async def get(self, candidate_id: UUID) -> Candidate:
        c = await self.repo.get_by_id(candidate_id)
        if not c:
            raise NotFoundException("候选人", str(candidate_id))
        return c

    async def ensure_accessible(self, candidate: Candidate, hr_scope: "HrAccessContext") -> None:
        """招聘数据范围校验：非 all 范围用户仅可访问授权部门岗位下、或本人审核过的候选人。

        飞书审核卡片深链直达候选人详情，审核人（含历史审核人）命中即放行。
        """
        if hr_scope.is_unrestricted:
            return
        if hr_scope.scoped_departments:
            if candidate.department in hr_scope.scoped_departments:
                return
            if candidate.job_requirement_id:
                jd = await JobRequirementRepository(self.repo.session).get_by_id(candidate.job_requirement_id)
                if jd and jd.department in hr_scope.scoped_departments:
                    return
        if await CandidateReviewRepository(self.repo.session).exists_reviewer(
            candidate.id, hr_scope.user.name,
        ):
            return
        raise ForbiddenException("数据范围限制：仅可访问本部门岗位或您审核的候选人")

    async def create(self, data: CandidateCreate, operator: str | None = None) -> Candidate:
        c = Candidate(**data.model_dump())
        result = await self.repo.create(c)
        # 记录初始状态
        self.repo.session.add(CandidateStatusLog(
            candidate_id=result.id, from_status=None, to_status=result.status,
            remark="创建候选人", operator=operator,
        ))
        await self.repo.session.flush()
        return result

    async def update(self, candidate_id: UUID, data: CandidateUpdate) -> Candidate:
        c = await self.get(candidate_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(c, k, v)
        return await self.repo.update(c)

    async def delete(self, candidate_id: UUID) -> None:
        c = await self.get(candidate_id)
        if c.status == "已入职":
            raise ValueError("已入职候选人不可删除（已生成员工档案与入职记录），如需处理请走离职流程")
        await self.repo.soft_delete(c.id)

    async def transition_status(
        self, candidate_id: UUID, new_status: str, remark: str | None = None,
        operator: str | None = None,
    ) -> Candidate:
        c = await self.get(candidate_id)
        allowed = _CANDIDATE_TRANSITIONS.get(c.status, set())
        if new_status not in allowed:
            raise ValueError(f"不允许从「{c.status}」变更为「{new_status}」")
        old_status = c.status
        c.status = new_status
        result = await self.repo.update(c)
        self.repo.session.add(CandidateStatusLog(
            candidate_id=result.id, from_status=old_status, to_status=new_status,
            remark=remark, operator=operator,
        ))
        await self.repo.session.flush()
        return result

    async def get_status_logs(self, candidate_id: UUID) -> list[CandidateStatusLog]:
        return await self.log_repo.list_by_candidate(candidate_id)

    async def onboard(self, candidate_id: UUID, operator: str | None = None) -> tuple[Candidate, OnboardingRecord, str]:
        """候选人入职：校验状态、生成工号、创建入职记录、更新岗位需求 hired_count。"""
        import uuid as _uuid
        from datetime import date as date_type

        from app.modules.hr.models import OnboardingRecord
        from app.modules.hr.repository import (
            CandidateRepository,
            JobRequirementRepository,
        )
        from app.modules.hr.schemas import CandidateUpdate

        # SELECT FOR UPDATE 防止并发入职
        candidate_repo = CandidateRepository(self.repo.session)
        c = await candidate_repo.get_by_id_for_update(candidate_id)
        if not c:
            raise NotFoundException("候选人", str(candidate_id))
        if c.status != "待入职审批":
            raise ValueError("候选人状态必须为「待入职审批」才能入职（请先通过入职审批）")

        # 生成工号
        emp_no = f"ZP{date_type.today().strftime('%y%m%d')}{str(_uuid.uuid4())[:4].upper()}"

        onboarding = OnboardingRecord(
            employee_number=emp_no,
            name=c.name or "",
            department=c.department or "未分配",
            position=c.position or "未分配",
            hire_date=date_type.today(),
            phone=c.phone,
            email=c.email,
            education=c.education,
            school=c.school,
            major=c.major,
            source="recruitment",
        )
        self.repo.session.add(onboarding)
        await self.repo.session.flush()

        # 与 create_employee 副作用对齐：同步建员工档案 + 培训台账页 +
        # 培训名单行，否则招聘入职者游离于培训名单/台账体系外
        #（HR 后续在员工总台账正式建档时可按工号合并）
        # 字段带出：候选人档案已有的基本信息（性别/毕业时间等）随入职落档，
        # 避免入职后档案大面积空缺等员工自填补录；candidate_id 回链供溯源
        employee = Employee(
            employee_number=emp_no,
            name=c.name or "",
            department=c.department or "未分配",
            position=c.position or "未分配",
            hire_date=date_type.today(),
            phone=c.phone,
            gender=c.gender,
            education=c.education,
            school=c.school,
            major=c.major,
            graduation_date=c.graduation_date,
            candidate_id=candidate_id,
            status="在职",
        )
        self.repo.session.add(employee)
        await self.repo.session.flush()
        employee_service = EmployeeService(self.repo.session)
        await employee_service._sync_employee_training(employee)
        await employee_service._ensure_roster_for_new_employee(employee)

        # 自动创建入职子任务
        task_types = [
            ("体检确认", 0), ("资料审核", 1), ("合同签署", 2), ("入职培训", 3),
        ]
        for task_type, sort_order in task_types:
            task = OnboardingTask(
                candidate_id=candidate_id,
                task_type=task_type,
                sort_order=sort_order,
                status="待完成",
            )
            self.repo.session.add(task)
        await self.repo.session.flush()

        # 更新候选人状态（update() 不写状态日志，此处显式补记，
        # 供月度入职统计与招聘周期计算取事件时间）
        await self.update(candidate_id, CandidateUpdate(status="已入职", offer_status="已接受"))
        self.repo.session.add(CandidateStatusLog(
            candidate_id=candidate_id, from_status="待入职审批", to_status="已入职",
            remark=f"一键入职，工号 {emp_no}", operator=operator,
        ))

        # 更新岗位需求 hired_count
        if c.job_requirement_id:
            jd_repo = JobRequirementRepository(self.repo.session)
            await jd_repo.increment_hired_count(c.job_requirement_id)

        # UPDATE 后 re-fetch，确保返回最新状态
        c = await candidate_repo.get_by_id(candidate_id) or c

        return c, onboarding, emp_no


class InterviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = InterviewRepository(session)

    # 面试状态机白名单（镜像 _CANDIDATE_TRANSITIONS 模式）：
    # 待安排→已安排/已完成（无日历的面试实际发生了可直接完成）/已取消；
    # 已安排→已完成/已取消/待安排（改期回退）；已完成/已取消为终态
    _TRANSITIONS: dict[str, set[str]] = {
        "待安排": {"已安排", "已完成", "已取消"},
        "已安排": {"已完成", "已取消", "待安排"},
        "已完成": set(),
        "已取消": set(),
    }

    @classmethod
    def _validate_transition(cls, current: str, target: str) -> None:
        allowed = cls._TRANSITIONS.get(current, set())
        if target not in allowed:
            raise AppException(
                status_code=400,
                message=f"不允许将面试状态从「{current}」变更为「{target}」",
            )

    def _log_status(
        self, interview_id: UUID, from_status: str | None, to_status: str,
        operator: str | None, remark: str | None = None,
    ) -> None:
        self.repo.session.add(InterviewStatusLog(
            interview_id=interview_id, from_status=from_status, to_status=to_status,
            operator=operator, remark=remark,
        ))

    async def list_by_candidate(self, candidate_id: UUID) -> list[Interview]:
        return await self.repo.list_by_candidate(candidate_id)

    async def list_overview(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        interviewer: str | None = None,
        status: str | None = None,
        candidate_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[Interview, str | None, str | None]], int]:
        """跨候选人面试总览（按日期倒序分页，含候选人姓名/岗位）。"""
        return await self.repo.search_overview(
            date_from=date_from, date_to=date_to, interviewer=interviewer,
            status=status, candidate_id=candidate_id, page=page, page_size=page_size,
        )

    async def get(self, interview_id: UUID) -> Interview:
        iv = await self.repo.get_by_id(interview_id)
        if not iv:
            raise NotFoundException("面试记录", str(interview_id))
        return iv

    async def create(
        self, data: InterviewCreate,
        operator: UUID | None = None, operator_name: str | None = None,
    ) -> Interview:
        self._validate_time_range(data.start_time, data.end_time)
        await self._ensure_no_conflict(
            interviewer=data.interviewer,
            interview_date=data.interview_date,
            start_time=data.start_time, end_time=data.end_time,
            exclude_id=None, force=data.force_conflict,
        )

        create_calendar = data.create_calendar_event
        iv = Interview(**data.model_dump(exclude={"create_calendar_event", "force_conflict"}))
        iv.created_by = operator
        result = await self.repo.create(iv)

        if create_calendar and data.interview_date:
            try:
                candidate_repo = CandidateRepository(self.repo.session)
                candidate = await candidate_repo.get_by_id(data.candidate_id)
                candidate_name = candidate.name if candidate else "候选人"
                position = candidate.position if candidate else ""

                from app.modules.hr.feishu_calendar import FeishuCalendarService
                calendar = FeishuCalendarService()
                event_id = await calendar.create_interview_event(
                    interview_id=result.id,
                    candidate_name=candidate_name,
                    position=position,
                    interview_date_val=data.interview_date,
                    interviewer_name=data.interviewer or "未指定",
                    location=data.location or "未指定",
                    interview_type=data.interview_type,
                    start_time_val=data.start_time,
                    end_time_val=data.end_time,
                )
                result.calendar_event_id = event_id
                # 日历建成功 = 面试确定进入日程，状态从「待安排」推进到「已安排」
                if result.status == "待安排":
                    result.status = "已安排"
                result = await self.repo.update(result)
            except Exception as e:
                logger.warning("创建日历事件失败（面试已保存）: %s", e)
                # 面试已保存成功，日程失败不回滚——记录原因随响应返回供前端提示
                result.calendar_sync_error = f"飞书日程创建失败：{e}"

        self._log_status(
            result.id, None, result.status,
            operator=operator_name, remark="创建面试",
        )
        await self.repo.session.flush()
        return result

    @staticmethod
    def _validate_time_range(start_time: time | None, end_time: time | None) -> None:
        if start_time and end_time and end_time <= start_time:
            raise AppException(status_code=400, message="面试结束时间必须晚于开始时间")

    async def _ensure_no_conflict(
        self,
        *,
        interviewer: str | None,
        interview_date: date | None,
        start_time: time | None,
        end_time: time | None,
        exclude_id: UUID | None,
        force: bool,
    ) -> None:
        """同面试官同日时段重叠校验；信息不全（无日期/起止/面试官）时跳过。"""
        if force or not (interviewer and interview_date and start_time and end_time):
            return
        conflicts = await self.repo.find_time_conflicts(
            interviewer, interview_date, start_time, end_time, exclude_id=exclude_id,
        )
        if conflicts:
            c = conflicts[0]
            # 查询条件已保证起止时间非空，窄化类型供 mypy
            assert c.start_time is not None and c.end_time is not None
            detail = (
                f"{c.interviewer} 在 {c.interview_date} "
                f"{c.start_time.strftime('%H:%M')}-{c.end_time.strftime('%H:%M')} "
                f"已有一场「{c.interview_type}」（{c.status}）"
            )
            raise AppException(
                status_code=409,
                message=f"面试官时段冲突：{detail}",
                detail={"conflict": detail},
            )

    async def update(
        self, interview_id: UUID, data: InterviewUpdate,
        operator: UUID | None = None, operator_name: str | None = None,
    ) -> Interview:
        iv = await self.get(interview_id)
        old_date = iv.interview_date
        old_location = iv.location
        old_interviewer = iv.interviewer
        old_start = iv.start_time
        old_end = iv.end_time
        old_status = iv.status

        fields = data.model_dump(exclude={"create_calendar_event", "force_conflict"}, exclude_unset=True)
        # 冲突校验用「合并后的生效值」：未传的字段沿用旧值
        eff_date = fields.get("interview_date", old_date)
        eff_start = fields.get("start_time", iv.start_time)
        eff_end = fields.get("end_time", iv.end_time)
        self._validate_time_range(eff_start, eff_end)
        if data.status != "已取消":  # 取消操作无需查冲突
            await self._ensure_no_conflict(
                interviewer=fields.get("interviewer", old_interviewer),
                interview_date=eff_date,
                start_time=eff_start, end_time=eff_end,
                exclude_id=interview_id, force=data.force_conflict,
            )

        # 状态流转校验（白名单）+ 落状态日志
        if "status" in fields and fields["status"] != old_status:
            self._validate_transition(old_status, fields["status"])

        for k, v in fields.items():
            setattr(iv, k, v)
        iv.updated_by = operator
        result = await self.repo.update(iv)

        if old_status != result.status:
            self._log_status(
                interview_id, old_status, result.status,
                operator=operator_name, remark="更新面试",
            )
            await self.repo.session.flush()

        # 状态联动：标记完成的瞬间，若候选人处于「面试中」且无剩余未完成轮次，
        # 自动推进到「已面试」（走候选人状态机白名单，失败不影响面试保存）
        if old_status != "已完成" and result.status == "已完成":
            try:
                await self._maybe_complete_candidate(result, operator_name)
            except Exception as e:
                logger.warning("面试完成后自动推进候选人状态失败: %s", e)

        # 状态流转为「已取消」时同步删除日历事件——与 DELETE 取消行为保持一致
        if old_status != "已取消" and result.status == "已取消" and result.calendar_event_id:
            await self._delete_calendar_event_quietly(result)

        # 此前创建日历失败的记录（calendar_event_id 为空）：更新时显式
        # 勾选 create_calendar_event 补建，否则一次失败后永远没有日程
        if (
            data.create_calendar_event
            and not result.calendar_event_id
            and result.interview_date
            and result.status != "已取消"
        ):
            try:
                event_id = await self._create_calendar_event(result)
                if event_id:
                    result.calendar_event_id = event_id
                    result = await self.repo.update(result)
            except Exception as e:
                logger.warning("补建日历事件失败（面试已更新）: %s", e)
                result.calendar_sync_error = f"飞书日程补建失败：{e}"

        if result.calendar_event_id and result.status != "已取消" and (
            old_date != result.interview_date
            or old_location != result.location
            or old_interviewer != result.interviewer
            or old_start != result.start_time
            or old_end != result.end_time
        ):
            try:
                from app.modules.hr.feishu_calendar import FeishuCalendarService
                calendar = FeishuCalendarService()
                await calendar.update_interview_event(
                    result.calendar_event_id,
                    interview_date_val=result.interview_date,
                    location=result.location,
                    interviewer_name=result.interviewer,
                    start_time_val=result.start_time,
                    end_time_val=result.end_time,
                )
            except Exception as e:
                logger.warning("同步日历事件失败（面试已更新）: %s", e)
                result.calendar_sync_error = f"飞书日程同步失败：{e}"

        return result

    async def _maybe_complete_candidate(self, interview: Interview, operator_name: str | None) -> None:
        """面试全部轮次完成时，把「面试中」的候选人自动推进到「已面试」。"""
        candidate_repo = CandidateRepository(self.repo.session)
        candidate = await candidate_repo.get_by_id(interview.candidate_id)
        if not candidate or candidate.status != "面试中":
            return
        all_ivs = await self.repo.list_by_candidate(interview.candidate_id)
        # 已取消（软删的历史数据同理）与已完成之外的轮次都算「还有安排」
        pending = [
            x for x in all_ivs
            if x.status not in ("已完成", "已取消") and x.id != interview.id
        ]
        if pending:
            return
        candidate_service = CandidateService(self.repo.session)
        await candidate_service.transition_status(
            interview.candidate_id, "已面试",
            remark=f"全部面试轮次已完成（{interview.interview_type} 完成时自动推进）",
            operator=operator_name,
        )

    async def _create_calendar_event(self, interview: Interview) -> str | None:
        """为面试记录创建飞书日历日程，返回 event_id（失败抛异常由调用方降级）。"""
        candidate_repo = CandidateRepository(self.repo.session)
        candidate = await candidate_repo.get_by_id(interview.candidate_id)
        candidate_name = candidate.name if candidate else "候选人"
        position = candidate.position if candidate else ""

        from app.modules.hr.feishu_calendar import FeishuCalendarService
        calendar = FeishuCalendarService()
        return await calendar.create_interview_event(
            interview_id=interview.id,
            candidate_name=candidate_name,
            position=position,
            interview_date_val=interview.interview_date,
            interviewer_name=interview.interviewer or "未指定",
            location=interview.location or "未指定",
            interview_type=interview.interview_type,
            start_time_val=interview.start_time,
            end_time_val=interview.end_time,
        )

    async def delete(
        self, interview_id: UUID,
        operator: UUID | None = None, operator_name: str | None = None,
    ) -> None:
        """取消面试：状态流转为「已取消」+ 删除日历事件。

        不做软删除——已取消的记录保留在面试列表中（前端已渲染红色 Tag），
        与 PUT 改状态为「已取消」的行为保持一致。终态（已完成/已取消）不可再取消。
        """
        iv = await self.get(interview_id)
        if iv.status != "已取消":
            self._validate_transition(iv.status, "已取消")
            old_status = iv.status
            iv.status = "已取消"
            iv.updated_by = operator
            await self.repo.update(iv)
            self._log_status(
                interview_id, old_status, "已取消",
                operator=operator_name, remark="取消面试",
            )
            await self.repo.session.flush()
        if iv.calendar_event_id:
            await self._delete_calendar_event_quietly(iv)

    async def _delete_calendar_event_quietly(self, interview: Interview) -> None:
        """删除飞书日程并清空 calendar_event_id（失败仅记录日志，取消不应被日历故障阻塞）。"""
        if not interview.calendar_event_id:
            return
        try:
            from app.modules.hr.feishu_calendar import FeishuCalendarService
            calendar = FeishuCalendarService()
            await calendar.delete_interview_event(interview.calendar_event_id)
        except Exception as e:
            logger.warning("删除日历事件失败: %s", e)
        interview.calendar_event_id = None
        await self.repo.update(interview)



class CandidateReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = CandidateReviewRepository(session)
        self.candidate_repo = CandidateRepository(session)
        self.jd_repo = JobRequirementRepository(session)

    async def list_pending(self, *, reviewer: str | None = None) -> list[dict]:
        reviews = await self.repo.list_pending(reviewer=reviewer)
        # 批量预取候选人 + 岗位需求，避免 N+1
        candidate_ids = [rv.candidate_id for rv in reviews]
        jd_ids = [rv.job_requirement_id for rv in reviews if rv.job_requirement_id]
        candidate_map = {}
        jd_map = {}
        if candidate_ids:
            candidates = await self.candidate_repo.get_by_ids(candidate_ids)
            candidate_map = {c.id: c for c in candidates}
        if jd_ids:
            jds = await self.jd_repo.get_by_ids(jd_ids)
            jd_map = {j.id: j for j in jds}
        result = []
        for rv in reviews:
            c = candidate_map.get(rv.candidate_id)
            if not c:
                continue
            result.append({
                "review": rv,
                "candidate": c,
                "job_requirement": jd_map.get(rv.job_requirement_id) if rv.job_requirement_id else None,
            })
        return result

    async def push(
        self, candidate_id: UUID, pushed_by: str, push_note: str | None = None,
        reviewer: str | None = None, operator: str | None = None,
    ) -> CandidateReview:
        c = await self.candidate_repo.get_by_id(candidate_id)
        if not c:
            raise NotFoundException("候选人", str(candidate_id))
        if not c.job_requirement_id:
            raise ValueError("该候选人未关联岗位需求，无法推送审核")

        jd = await self.jd_repo.get_by_id(c.job_requirement_id)
        # 优先用传入的 reviewer，其次用岗位负责人，最后报错
        final_reviewer = reviewer or (jd.owner if jd and jd.owner else None)
        if not final_reviewer:
            raise ValueError("请填写审核人姓名，或为岗位需求设置负责人")

        # 状态机校验：走 _CANDIDATE_TRANSITIONS，防止「已面试/录用中」等
        # 后段状态直接回推部门审核（旧逻辑只挡了三个终态）
        if "待部门审核" not in _CANDIDATE_TRANSITIONS.get(c.status, set()):
            raise ValueError(f"候选人状态为「{c.status}」，无法推送审核")

        rv = CandidateReview(
            candidate_id=candidate_id,
            job_requirement_id=c.job_requirement_id,
            pushed_by=pushed_by,
            push_note=push_note,
            reviewer=final_reviewer,
            status="待审核",
        )
        result = await self.repo.create(rv)

        # 候选人状态流转
        old_status = c.status
        c.status = "待部门审核"
        await self.candidate_repo.update(c)
        self.candidate_repo.session.add(CandidateStatusLog(
            candidate_id=candidate_id,
            from_status=old_status,
            to_status="待部门审核",
            remark=f"推送至{final_reviewer}审核",
            operator=operator or pushed_by,
        ))

        # 发送飞书消息卡片给审核人
        await self._send_review_card(result, c, jd, push_note)

        return result

    async def find_pending_review_id(self, candidate_id: UUID) -> UUID:
        """按候选人查找待审核记录的ID（用于审核决策时自动查找）。"""
        rv = await self.repo.get_by_candidate(candidate_id)
        if not rv:
            raise ValueError("未找到审核记录")
        if rv.status != "待审核":
            raise ValueError("该审核已处理")
        return rv.id

    async def decide(
        self, review_id: UUID, decision: str, review_comment: str | None = None,
        operator: str | None = None,
    ) -> CandidateReview:
        rv = await self.repo.get_by_id(review_id)
        if not rv:
            raise NotFoundException("审核记录", str(review_id))
        if rv.status != "待审核":
            raise ValueError("该审核已处理")

        # 先校验候选人状态，再落库审核结果——避免校验失败时审核记录已被
        # flush 且随路由 commit（候选人卡死、审核无法重做）
        is_onboarding = rv.review_type == "入职审批"
        c = await self.candidate_repo.get_by_id(rv.candidate_id)
        new_status: str | None = None
        if c:
            if is_onboarding:
                if c.status != "待入职审批":
                    raise ValueError(f"候选人状态为「{c.status}」，与入职审批不匹配")
                # 同意后保持「待入职审批」：实际入职由 HR 执行 onboard()
                # （创建入职记录/工号/子任务），避免状态直接跳「已入职」导致入职链断裂
                new_status = None if decision == "已同意" else "已录用"
            else:
                if c.status not in ("待部门审核", "面试中"):
                    raise ValueError(f"候选人状态为「{c.status}」，与当前审核不匹配，无法更新状态")
                new_status = "面试中" if decision == "已同意" else "已拒绝"

        rv.status = decision
        rv.review_comment = review_comment
        rv.reviewed_at = datetime.now()
        result = await self.repo.update(rv)

        # 候选人状态更新
        if c and new_status:
            old_status = c.status
            c.status = new_status
            await self.candidate_repo.update(c)
            self.candidate_repo.session.add(CandidateStatusLog(
                candidate_id=c.id,
                from_status=old_status,
                to_status=new_status,
                remark=f"审核人{decision}" + (f"：{review_comment}" if review_comment else ""),
                operator=operator or rv.reviewer,
            ))

        # 通知HR审核结果
        if rv.pushed_by:
            await self._send_decision_notification(result, c, decision, review_comment)

        return result

    async def _send_review_card(self, review: CandidateReview, candidate: Candidate, jd: JobRequirement | None, push_note: str | None) -> None:
        """发送飞书消息卡片给审核人"""
        try:
            from app.modules.hr.feishu_review_service import send_review_card
            await send_review_card(review, candidate, jd, push_note)
        except Exception as e:
            logger.warning(f"发送飞书审核卡片失败: {e}")

    async def push_onboarding(
        self, candidate_id: UUID, pushed_by: str, push_note: str | None = None,
        reviewer: str | None = None, operator: str | None = None,
    ) -> CandidateReview:
        """发起入职审批"""
        c = await self.candidate_repo.get_by_id(candidate_id)
        if not c:
            raise NotFoundException("候选人", str(candidate_id))
        if c.status != "已录用":
            raise ValueError(f"候选人状态必须为「已录用」才能发起入职审批，当前状态：「{c.status}」")

        # 审批人优先级：显式指定 > 岗位负责人 > 发起人
        final_reviewer = reviewer
        if not final_reviewer and c.job_requirement_id:
            jd = await self.jd_repo.get_by_id(c.job_requirement_id)
            if jd and jd.owner:
                final_reviewer = jd.owner
        if not final_reviewer:
            final_reviewer = pushed_by

        rv = CandidateReview(
            candidate_id=candidate_id,
            job_requirement_id=c.job_requirement_id,
            pushed_by=pushed_by,
            push_note=push_note,
            reviewer=final_reviewer,
            status="待审核",
            review_type="入职审批",
        )
        result = await self.repo.create(rv)

        old_status = c.status
        c.status = "待入职审批"
        await self.candidate_repo.update(c)
        self.candidate_repo.session.add(CandidateStatusLog(
            candidate_id=candidate_id,
            from_status=old_status,
            to_status="待入职审批",
            remark=f"发起入职审批，审批人：{final_reviewer}",
            operator=operator or pushed_by,
        ))

        # 通知审批人（与部门审核 push 行为一致）
        jd = await self.jd_repo.get_by_id(c.job_requirement_id) if c.job_requirement_id else None
        await self._send_review_card(result, c, jd, push_note)

        return result

    async def _send_decision_notification(self, review: CandidateReview, candidate: Candidate | None, decision: str, comment: str | None) -> None:
        """通知HR审核结果"""
        try:
            from app.modules.hr.feishu_review_service import send_decision_notification
            await send_decision_notification(review, candidate, decision, comment)
        except Exception as e:
            logger.warning(f"发送飞书审核通知失败: {e}")


# ─── 月度绩效考核 ───


class PerformanceEvaluationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PerformanceEvaluationRepository(db)

    async def list_evaluations(
        self, params: PerformanceListParams, departments: frozenset[str] | None = None,
    ) -> tuple[list[dict], int]:
        evals, total = await self.repo.list_evaluations(
            month=params.evaluation_month,
            department=params.department,
            status=params.status,
            departments=departments,
            page=params.page,
            page_size=params.page_size,
        )
        items = []
        for e in evals:
            items.append(self._to_response_dict(e))
        return items, total

    async def get_evaluation(self, evaluation_id: UUID) -> dict | None:
        e = await self.repo.get_by_id(evaluation_id)
        if e is None:
            return None
        return self._to_response_dict(e)

    async def create_evaluation(self, data: PerformanceEvaluationCreate) -> dict:
        existing = await self.repo.get_by_month_dept(data.evaluation_month, data.department)
        if existing:
            raise ValueError(f"部门 {data.department} 在 {data.evaluation_month} 已有考核记录")

        # 如果未提供部门负责人，从部门培训人员表拉取
        dept_head = data.department_head
        if not dept_head:
            dtp = (await self.db.execute(
                select(DeptTrainingPersonnel).where(
                    DeptTrainingPersonnel.department == data.department,
                    DeptTrainingPersonnel.is_deleted == False,  # noqa: E712
                )
            )).scalars().first()
            if dtp and dtp.department_head:
                dept_head = dtp.department_head

        evaluation = MonthlyPerformanceEvaluation(
            department=data.department,
            department_head=dept_head or "",
            evaluator_leader=data.evaluator_leader,
            evaluation_month=data.evaluation_month,
            headcount=data.headcount,
        )
        evaluation = await self.repo.create(evaluation)

        if data.items:
            await self.repo.upsert_items(evaluation.id, [
                it.model_dump() for it in data.items
            ])
        evaluation = await self.repo.get_by_id(evaluation.id)
        assert evaluation is not None
        return self._to_response_dict(evaluation)

    async def update_evaluation(self, evaluation_id: UUID, data: PerformanceEvaluationUpdate) -> dict:
        e = await self.repo.get_by_id(evaluation_id)
        if e is None:
            raise ValueError("考核记录不存在")
        if e.status not in ("draft", "self_submitted"):
            # 自评提交后进入领导评分阶段，允许继续编辑指标项（leader_score）；
            # leader_scored 终态后不可再改
            raise ValueError("仅草稿或待领导评分状态可编辑")

        if data.department_head is not None:
            e.department_head = data.department_head
        if data.evaluator_leader is not None:
            e.evaluator_leader = data.evaluator_leader
        if data.headcount is not None:
            e.headcount = data.headcount
        e = await self.repo.update(e)

        if data.items is not None:
            await self.repo.upsert_items(e.id, [
                it.model_dump() for it in data.items
            ])
        e = await self.repo.get_by_id(evaluation_id)
        assert e is not None
        return self._to_response_dict(e)

    async def submit_self(self, evaluation_id: UUID, user_name: str) -> dict:
        e = await self.repo.get_by_id(evaluation_id)
        if e is None:
            raise ValueError("考核记录不存在")
        if e.status != "draft":
            raise ValueError("仅草稿状态可提交自评")
        if not e.department_head:
            raise PermissionError("考核未配置部门负责人，无法提交自评")
        if user_name and user_name != e.department_head:
            raise PermissionError("仅部门负责人可提交自评")
        e.status = "self_submitted"
        e.self_submitted_at = datetime.now(UTC)
        await self.repo.update(e)
        if _is_notify_enabled():
            await self._notify_leader(e)
        return self._to_response_dict(
            await self.repo.get_by_id(evaluation_id)  # type: ignore[arg-type]
        )

    async def submit_leader(self, evaluation_id: UUID, user_name: str | None = None) -> dict:
        e = await self.repo.get_by_id(evaluation_id)
        if e is None:
            raise ValueError("考核记录不存在")
        if e.status not in ("draft", "self_submitted"):
            raise ValueError("仅草稿或已自评状态可提交领导评分")
        if not e.evaluator_leader:
            raise PermissionError("考核未配置分管领导，无法提交领导评分")
        if user_name and user_name != e.evaluator_leader:
            raise PermissionError("仅分管领导可提交领导评分")
        e.status = "leader_scored"
        e.leader_submitted_at = datetime.now(UTC)
        await self.repo.update(e)
        if _is_notify_enabled():
            await self._notify_dept_head(e)
        return self._to_response_dict(
            await self.repo.get_by_id(evaluation_id)  # type: ignore[arg-type]
        )

    async def auto_create_for_month(self, month: str, departments: list[str]) -> list[dict]:
        created: list[dict] = []
        for dept in departments:
            existing = await self.repo.get_by_month_dept(month, dept)
            if existing:
                continue
            dtp = (await self.db.execute(
                select(DeptTrainingPersonnel).where(
                    DeptTrainingPersonnel.department == dept,
                    DeptTrainingPersonnel.is_deleted == False,  # noqa: E712
                )
            )).scalars().first()
            dept_head = dtp.department_head if dtp and dtp.department_head else ""
            evaluation = MonthlyPerformanceEvaluation(
                department=dept,
                department_head=dept_head,
                evaluation_month=month,
            )
            await self.repo.create(evaluation)
            # 为每个启用的考核项目预填空评分记录
            active_cats = await self.repo.list_categories()
            for cat in active_cats:
                if cat.is_active:
                    await self.repo.upsert_category_score(
                        evaluation.id, cat.id, None, None, cat.weight,
                    )
            # 添加默认考核项目
            default_items = [
                {"category": "key_work", "indicator": "月度重点工作1", "weight": 20, "sort_order": 0},
                {"category": "key_work", "indicator": "月度重点工作2", "weight": 20, "sort_order": 1},
                {"category": "key_work", "indicator": "月度重点工作3", "weight": 20, "sort_order": 2},
                {"category": "routine_work", "indicator": "月度常规工作", "weight": 30, "sort_order": 3},
                {"category": "reward_penalty", "indicator": "奖惩项目", "standard": "造成重大事故可否决绩效总分；获得省级以上奖项可加分", "weight": 10, "sort_order": 4},
            ]
            await self.repo.upsert_items(evaluation.id, default_items)
            # re-fetch 避免 MissingGreenlet（items 是 lazy relationship）
            evaluation = await self.repo.get_by_id(evaluation.id)
            assert evaluation is not None
            # 通知部门负责人（测试阶段默认关闭）
            if dept_head and _is_notify_enabled():
                await self._notify_self_required(evaluation)
            created.append(self._to_response_dict(evaluation))
        # 通知所有项目负责人（仅 PERFORMANCE_NOTIFY=true 时发送）
        if created and _is_notify_enabled():
            await self._notify_evaluators(month, created)
        return created

    async def _notify_evaluators(self, month: str, evaluations: list[dict]) -> None:
        """通知各项目负责人：本月有 N 个部门需要评分"""
        cats = await self.repo.list_categories()
        # evaluator → list of departments
        evaluator_depts: dict[str, list[str]] = {}
        for cat in cats:
            if not cat.is_active or not cat.evaluator:
                continue
            evaluator_depts.setdefault(cat.evaluator, []).extend(
                [e["department"] for e in evaluations]
            )
        for evaluator, depts in evaluator_depts.items():
            unique_depts = list(dict.fromkeys(depts))  # 去重保序
            try:
                from app.modules.hr.feishu_review_service import (
                    _lookup_open_id,
                    _send_card,
                )
                open_id = await _lookup_open_id(evaluator)
                if open_id:
                    card = {
                        "config": {"wide_screen_mode": True},
                        "header": {"title": {"tag": "plain_text", "content": f"📋 {month} 月度考核 - 待评分"}, "template": "blue"},
                        "elements": [
                            {"tag": "markdown", "content": f"您负责的考核项目需要为 **{len(unique_depts)}** 个部门评分：\n\n" + "\n".join(f"• {d}" for d in unique_depts[:10]) + ("\n..." if len(unique_depts) > 10 else "")},
                            {"tag": "hr"},
                            *([{"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "前往评分"}, "type": "primary", "url": f"{_get_base_url()}/hr/performance/score?month={month}"}]}] if _get_base_url() else []),
                        ],
                    }
                    await _send_card(open_id, card)
            except Exception as exc:
                logger.warning(f"通知项目负责人 {evaluator} 失败: {exc}")

    async def _notify_self_required(self, evaluation: MonthlyPerformanceEvaluation) -> None:
        try:
            from app.modules.hr.feishu_review_service import _lookup_open_id, _send_card
            open_id = await _lookup_open_id(evaluation.department_head)
            if open_id:
                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": "📋 月度绩效考核 - 待自评"}, "template": "blue"},
                    "elements": [
                        {"tag": "markdown", "content": f"**{evaluation.evaluation_month}** 月度绩效考核已生成，请及时完成自评。\n\n部门：{evaluation.department}\n负责人：{evaluation.department_head}"},
                        {"tag": "hr"},
                        *([{"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "前往填写自评"}, "type": "primary", "url": f"{_get_base_url()}/hr/performance/{evaluation.id}"}]}] if _get_base_url() else []),
                    ],
                }
                await _send_card(open_id, card)
        except Exception as exc:
            logger.warning(f"发送绩效考核自评提醒失败: {exc}")

    async def _notify_leader(self, evaluation: MonthlyPerformanceEvaluation) -> None:
        if not evaluation.evaluator_leader:
            return
        try:
            from app.modules.hr.feishu_review_service import _lookup_open_id, _send_card
            open_id = await _lookup_open_id(evaluation.evaluator_leader)
            if open_id:
                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": "📋 月度绩效考核 - 待领导评分"}, "template": "blue"},
                    "elements": [
                        {"tag": "markdown", "content": f"**{evaluation.evaluation_month}** 部门负责人已完成自评，请进行分管领导评分。\n\n部门：{evaluation.department}\n负责人：{evaluation.department_head}"},
                        {"tag": "hr"},
                        *([{"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "前往评分"}, "type": "primary", "url": f"{_get_base_url()}/hr/performance/{evaluation.id}"}]}] if _get_base_url() else []),
                    ],
                }
                await _send_card(open_id, card)
        except Exception as exc:
            logger.warning(f"发送绩效考核领导评分提醒失败: {exc}")

    async def _notify_dept_head(self, evaluation: MonthlyPerformanceEvaluation) -> None:
        try:
            from app.modules.hr.feishu_review_service import _lookup_open_id, _send_card
            open_id = await _lookup_open_id(evaluation.department_head)
            if open_id:
                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {"title": {"tag": "plain_text", "content": "📋 月度绩效考核 - 领导已评分"}, "template": "green"},
                    "elements": [
                        {"tag": "markdown", "content": f"**{evaluation.evaluation_month}** 绩效考核领导评分已完成，请查看结果。\n\n部门：{evaluation.department}"},
                        {"tag": "hr"},
                        *([{"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "查看考核结果"}, "type": "primary", "url": f"{_get_base_url()}/hr/performance/{evaluation.id}"}]}] if _get_base_url() else []),
                    ],
                }
                await _send_card(open_id, card)
        except Exception as exc:
            logger.warning(f"发送绩效考核结果通知失败: {exc}")

    @staticmethod
    def _to_response_dict(e: MonthlyPerformanceEvaluation) -> dict:
        sorted_items = sorted(e.items or [], key=lambda x: x.sort_order)
        return {
            "id": str(e.id),
            "department": e.department,
            "department_head": e.department_head,
            "evaluator_leader": e.evaluator_leader,
            "evaluation_month": e.evaluation_month,
            "headcount": e.headcount,
            "status": e.status,
            "self_submitted_at": e.self_submitted_at.isoformat() if e.self_submitted_at else None,
            "leader_submitted_at": e.leader_submitted_at.isoformat() if e.leader_submitted_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None,
            "items": [
                {
                    "id": str(it.id),
                    "category": it.category,
                    "indicator": it.indicator,
                    "standard": it.standard,
                    "weight": it.weight,
                    "self_score": it.self_score,
                    "leader_score": it.leader_score,
                    "final_score": it.final_score,
                    "completion": it.completion,
                    "sort_order": it.sort_order,
                }
                for it in sorted_items
            ],
        }


def _get_base_url() -> str:
    """卡片按钮链接前缀：取 Settings.FRONTEND_URL（生产已配置项）。

    未配置时返回空串，调用方跳过按钮渲染——不再回退 localhost
    （收件人点开会打开自己的本机，纯属误导）。
    """
    from app.core.config import get_settings
    return (get_settings().FRONTEND_URL or "").strip().rstrip("/")


class OnboardingTaskService:
    """入职子任务管理"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_candidate(self, candidate_id: UUID) -> list[OnboardingTask]:
        from sqlalchemy import select as _select
        result = await self.session.execute(
            _select(OnboardingTask)
            .where(OnboardingTask.candidate_id == candidate_id, OnboardingTask.is_deleted == False)  # noqa: E712
            .order_by(OnboardingTask.sort_order)
        )
        return list(result.scalars().all())

    async def update(self, task_id: UUID, data: dict, candidate_id: UUID) -> OnboardingTask:
        from app.core.exceptions import NotFoundException as _NF
        result = await self.session.execute(
            select(OnboardingTask).where(OnboardingTask.id == task_id, OnboardingTask.is_deleted == False)  # noqa: E712
        )
        task = result.scalar_one_or_none()
        if not task:
            raise _NF("入职任务", str(task_id))
        # 任务必须归属路径中的候选人，防止把任务挪到别的候选人名下
        if task.candidate_id != candidate_id:
            raise _NF("入职任务", str(task_id))
        # 字段白名单：只允许更新状态/完成人/备注，防客户端覆盖归属等内部字段
        allowed = {"status", "completed_by", "notes"}
        for k, v in data.items():
            if k not in allowed:
                continue
            setattr(task, k, v)
        if data.get("status") == "已完成" and not task.completed_at:
            task.completed_at = datetime.now()
        await self.session.flush()
        return task


def _is_notify_enabled() -> bool:
    """是否启用绩效飞书通知（默认关闭，设置 HR_PERFORMANCE_NOTIFY=true 开启）"""
    from app.core.config import get_settings

    return get_settings().HR_PERFORMANCE_NOTIFY


# ─── 候选人胜任度多维分析报告 ───

_ANALYSIS_SYSTEM_PROMPT = """你是企业人力资源部的资深招聘评估专家。基于候选人简历、岗位JD和面试记录，输出结构化的胜任度多维分析报告。评估必须客观、具体，引用事实依据，评分严格（不及格就直说不及格，合格就直说合格）。"""

_ANALYSIS_PROMPT_TEMPLATE = """请对候选人进行多维度胜任度分析，参照以下报告结构输出 JSON：

{{
  "dimensions": [
    {{"name": "维度名", "score": 0-100, "star": 1-5, "assessment": "岗位要求 vs 候选人情况 vs 评价"}}
  ],
  "strengths": ["核心优势1", "核心优势2"],
  "risks": ["潜在风险1", "潜在风险2"],
  "total_score": 0-100,
  "recommend_level": "强烈推荐/推荐/待定/不推荐 之一",
  "interview_suggestions": ["面试考察重点建议1", "建议2"],
  "training_suggestions": ["录用后培养建议1", "建议2"],
  "summary": "总体结论一段话"
}}

维度确定规则（重要）：
1. 评估维度从【岗位JD】的任职要求中提取 4-6 个核心维度（如学历专业、
   工作经验、专业技能、沟通协作等）——JD 明确要求的才纳入；
   例如 JD 有英语要求才设「英语能力」维度，未提及的能力不要强行评估
2. 另外补充两项通用评估：稳定性（跳槽频率/职业规划）与薪资期望匹配度
   （与 JD 预算或市场水平比较），信息不足时如实写明「信息不足」
3. 每个维度的 assessment 按「岗位要求 → 候选人情况 → 评价结论」结构撰写

【候选人简历】
{resume_text}

【岗位JD】
{jd_text}

【面试记录】
{interview_text}
"""


class InterviewFeedbackService:
    """人工面试评价：每场面试一条，重复提交覆盖更新。"""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = InterviewFeedbackRepository(session)

    async def get_by_interview(self, interview_id: UUID) -> InterviewFeedback | None:
        return await self.repo.get_by_interview(interview_id)

    async def upsert(
        self, interview_id: UUID, data: InterviewFeedbackIn, operator: UUID | None = None,
    ) -> InterviewFeedback:
        interview = await InterviewRepository(self.repo.session).get_by_id(interview_id)
        if not interview:
            raise NotFoundException("面试记录", str(interview_id))
        if data.result not in ("通过", "待定", "不通过"):
            raise AppException(status_code=400, message="面试结论仅支持：通过/待定/不通过")

        dimensions = [d.model_dump() for d in data.dimensions]
        existing = await self.repo.get_by_interview(interview_id)
        if existing:
            existing.evaluator = data.evaluator
            existing.dimensions = dimensions
            existing.overall_comment = data.overall_comment
            existing.result = data.result
            existing.updated_by = operator
            await self.repo.session.flush()
            # UPDATE 后 re-fetch（铁律：flush 不回填 updated_at，避免懒加载）
            r = await self.repo.session.execute(
                select(InterviewFeedback).where(InterviewFeedback.id == existing.id)
            )
            return r.scalar_one()

        fb = InterviewFeedback(
            interview_id=interview_id,
            candidate_id=interview.candidate_id,
            evaluator=data.evaluator,
            dimensions=dimensions,
            overall_comment=data.overall_comment,
            result=data.result,
            created_by=operator,
        )
        self.repo.session.add(fb)
        await self.repo.session.flush()
        return fb


class CandidateAnalysisService:
    """候选人胜任度多维分析报告：面试记录提交后自动生成。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CandidateAnalysisReportRepository(session)

    async def list_by_candidate(self, candidate_id: UUID) -> list[CandidateAnalysisReport]:
        return await self.repo.list_by_candidate(candidate_id)

    async def get_by_interview(self, interview_id: UUID) -> CandidateAnalysisReport | None:
        return await self.repo.get_by_interview(interview_id)

    async def generate(
        self, candidate_id: UUID, interview_id: UUID
    ) -> CandidateAnalysisReport:
        """基于简历+JD+面试记录生成报告；面试建议联动写入面试备注。"""
        from datetime import datetime as _dt

        interview = await InterviewRepository(self.session).get_by_id(interview_id)
        if not interview:
            raise NotFoundException("面试记录", str(interview_id))
        interview_text = (interview.transcript_text or "").strip() or (interview.notes or "").strip()
        if not interview_text:
            raise ValueError("请先填写面试记录（逐字稿或备注）")

        candidate = await CandidateRepository(self.session).get_by_id(candidate_id)
        if not candidate:
            raise NotFoundException("候选人", str(candidate_id))

        jd_text = ""
        if interview.job_requirement_id:
            jd = await JobRequirementRepository(self.session).get_by_id(interview.job_requirement_id)
            if jd:
                jd_parts = []
                if jd.duties:
                    jd_parts.append(f"岗位职责：{jd.duties}")
                if jd.requirements:
                    jd_parts.append(f"任职要求：{jd.requirements}")
                jd_text = "\n".join(jd_parts)

        resume_parts = [
            f"姓名：{candidate.name}",
            f"学历：{candidate.education or '未知'}",
            f"学校：{candidate.school or '未知'}",
            f"专业：{candidate.major or '未知'}",
        ]
        if candidate.current_company:
            resume_parts.append(f"当前公司：{candidate.current_company}")
        if candidate.work_years is not None:
            resume_parts.append(f"工作年限：{candidate.work_years}年")
        if candidate.resume_url:
            resume_parts.append(f"简历文件：{candidate.resume_url}")
        resume_text = "\n".join(resume_parts)

        from app.modules.hr.ai_service import AiChatService
        from app.modules.hr.config import HR_AI_MODEL

        prompt = _ANALYSIS_PROMPT_TEMPLATE.format(
            resume_text=resume_text,
            jd_text=jd_text or "（无岗位JD）",
            interview_text=interview_text[:6000],
        )
        result = await AiChatService.call_json(prompt, system_prompt=_ANALYSIS_SYSTEM_PROMPT)
        if not isinstance(result, dict) or not result.get("dimensions"):
            raise ValueError("AI 返回结构异常，请重试")

        # 同面试记录旧报告软删
        existing = await self.repo.get_by_interview(interview_id)
        if existing:
            existing.is_deleted = True
            await self.repo.session.flush()

        report = await self.repo.create(
            CandidateAnalysisReport(
                candidate_id=candidate_id,
                job_requirement_id=interview.job_requirement_id,
                interview_id=interview_id,
                dimensions=result.get("dimensions"),
                strengths=result.get("strengths"),
                risks=result.get("risks"),
                total_score=result.get("total_score"),
                recommend_level=result.get("recommend_level"),
                interview_suggestions=result.get("interview_suggestions"),
                training_suggestions=result.get("training_suggestions"),
                raw_text=str(result.get("summary") or ""),
                model_version=HR_AI_MODEL,
                generated_at=_dt.now().astimezone(),
            )
        )

        # 联动：面试建议写入面试备注，HR 面试流程中直接可见
        suggestions = result.get("interview_suggestions") or []
        if suggestions:
            prefix = "【AI面试建议】"
            notes = interview.notes or ""
            if prefix not in notes:
                joined = "；".join(str(s) for s in suggestions)
                interview.notes = f"{notes}\n{prefix} {joined}".strip()
                await InterviewRepository(self.session).update(interview)

        # 回写候选人匹配报告摘要
        if result.get("summary"):
            c = await CandidateRepository(self.session).get_by_id(candidate_id)
            if c:
                c.match_report = str(result["summary"])
                await CandidateRepository(self.session).update(c)

        return report
