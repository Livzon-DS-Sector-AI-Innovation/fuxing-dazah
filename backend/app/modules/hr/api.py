from datetime import date
from io import BytesIO
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.hr.analysis_api import router as analysis_router
from app.modules.hr.document_generator import generate_onboarding_training_record
from app.modules.hr.evaluation_document_generator import generate_training_evaluation
from app.modules.hr.notification_document_generator import (
    generate_training_notification,
)
from app.modules.hr.onboarding_evaluation_document_generator import (
    generate_onboarding_evaluation,
)
from app.modules.hr.prejob_document_generator import generate_prejob_training_plan
from app.modules.hr.schemas import (
    AnnualTrainingPlanCreate,
    AnnualTrainingPlanItemBatchUpdate,
    AnnualTrainingPlanItemResponse,
    AnnualTrainingPlanResponse,
    AnnualTrainingPlanUpdate,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    DepartureRecordCreate,
    DepartureRecordResponse,
    DepartureRecordUpdate,
    DeptTrainingPersonnelResponse,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    OffboardingRecordCreate,
    OffboardingRecordResponse,
    OffboardingRecordUpdate,
    OnboardingEvaluationInput,
    OnboardingRecordResponse,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
    TrainingEvaluationInput,
    TrainingLedgerCreate,
    TrainingLedgerPageCreate,
    TrainingLedgerPageResponse,
    TrainingLedgerResponse,
    TrainingLedgerUpdate,
    TrainingNotificationInput,
    TrainingSignInSheetInput,
    TrainerResponse,
    TrainerListResponse,
    SopCatalogResponse,
    SopCatalogListResponse,
)
from app.modules.hr.service import (
    AnnualTrainingPlanItemService,
    AnnualTrainingPlanService,
    DepartmentService,
    DepartureRecordService,
    EmployeeService,
    OffboardingRecordService,
    OnboardingRecordService,
    TeamService,
    TrainingLedgerPageService,
    TrainingLedgerService,
)
from app.modules.hr.signin_document_generator import generate_training_sign_in_sheet
from app.modules.hr.system_settings_routes import router as system_settings_router
from app.modules.hr.candidate_routes import router as candidate_router
from app.modules.hr.job_requirement_routes import router as job_requirement_router
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE
from app.shared.schemas import PageParams

router = create_module_router(MODULES_BY_CODE["hr"])
router.include_router(system_settings_router)
router.include_router(candidate_router)
router.include_router(job_requirement_router)


def get_employee_service(session: AsyncSession = Depends(get_db)) -> EmployeeService:
    return EmployeeService(session)


def get_department_service(
    session: AsyncSession = Depends(get_db),
) -> DepartmentService:
    return DepartmentService(session)


def get_offboarding_service(
    session: AsyncSession = Depends(get_db),
) -> OffboardingRecordService:
    return OffboardingRecordService(session)


def get_team_service(
    session: AsyncSession = Depends(get_db),
) -> TeamService:
    return TeamService(session)


def get_onboarding_service(
    session: AsyncSession = Depends(get_db),
) -> OnboardingRecordService:
    return OnboardingRecordService(session)


def get_departure_service(
    session: AsyncSession = Depends(get_db),
) -> DepartureRecordService:
    return DepartureRecordService(session)


def get_training_ledger_service(
    session: AsyncSession = Depends(get_db),
) -> TrainingLedgerService:
    return TrainingLedgerService(session)


def get_training_ledger_page_service(
    session: AsyncSession = Depends(get_db),
) -> TrainingLedgerPageService:
    return TrainingLedgerPageService(session)


def get_annual_training_plan_service(
    session: AsyncSession = Depends(get_db),
) -> AnnualTrainingPlanService:
    return AnnualTrainingPlanService(session)


def get_annual_training_plan_item_service(
    session: AsyncSession = Depends(get_db),
) -> AnnualTrainingPlanItemService:
    return AnnualTrainingPlanItemService(session)


# ─── Employee Routes ───

@router.get("/employees", summary="员工列表")
async def list_employees(
    department: str | None = Query(None, description="部门筛选"),
    status: str | None = Query("在职", description="状态筛选，默认仅显示在职"),
    keyword: str | None = Query(None, description="姓名或工号关键词"),
    page_params: PageParams = Depends(),
    service: EmployeeService = Depends(get_employee_service),
):
    employees, total = await service.list_employees(
        department=department,
        status=status,
        keyword=keyword,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    data = [
        EmployeeResponse.model_validate(e).model_dump(mode="json")
        for e in employees
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/employees", summary="创建员工")
async def create_employee(
    payload: EmployeeCreate,
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.create_employee(payload)
    return success_response(
        data=EmployeeResponse.model_validate(employee).model_dump(mode="json"),
        message="员工创建成功",
        status_code=201,
    )


@router.post("/employees/upload", summary="上传人员名单")
async def upload_employees(
    file: UploadFile,
    service: EmployeeService = Depends(get_employee_service),
):
    """上传 Excel 人员名单，按工号自动新增或更新。"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx / .xls 格式")
    try:
        content = await file.read()
        result = await service.upload_employees(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=result, message=f"新增 {result['created']}，更新 {result['updated']}")


@router.get("/roster", summary="下载花名册")
async def download_roster(
    department: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
):
    """按部门下载员工花名册 Excel。"""
    from app.modules.hr.roster_generator import generate_roster_sync
    from app.modules.hr.models import Employee
    r = await session.execute(
        select(Employee).where(Employee.is_deleted == False, Employee.status != "离职").order_by(Employee.department, Employee.employee_number)
    )
    employees = [(e.name, e.department, e.gender or "", e.education or "", e.hire_date, e.status) for e in r.scalars().all()]
    if department:
        employees = [e for e in employees if e[1] == department]
    buffer = generate_roster_sync(employees, department)
    filename = f"花名册_{department or '全部'}.docx"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"}
    )


@router.get("/employees/training-candidates", summary="待培训人员列表")
async def training_candidates(
    keyword: str | None = Query(None, description="姓名或工号关键词"),
    session: AsyncSession = Depends(get_db),
):
    """返回入职台账中在职的员工列表，用于新员工入职培训页面选择员工。"""
    from app.modules.hr.models import OnboardingRecord
    stmt = select(OnboardingRecord).where(
        OnboardingRecord.is_deleted == False,
        OnboardingRecord.is_employed == "是",
    )
    if keyword:
        stmt = stmt.where(
            OnboardingRecord.name.ilike(f"{keyword}%")
            | OnboardingRecord.employee_number.ilike(f"{keyword}%")
        )
    stmt = stmt.order_by(OnboardingRecord.hire_date.desc().nulls_last())
    r = await session.execute(stmt)
    records = r.scalars().all()
    return success_response(data=[
        {
            "id": str(rec.id),
            "employee_number": rec.employee_number,
            "name": rec.name,
            "department": rec.department,
            "position": rec.position,
            "hire_date": str(rec.hire_date) if rec.hire_date else None,
            "education": rec.education,
            "school": rec.school,
            "graduation_date": str(rec.graduation_date) if rec.graduation_date else None,
            "source": rec.source or "新入职",
        }
        for rec in records
    ])


@router.get("/employees/by-number/{employee_number}", summary="根据工号查询员工")
async def get_employee_by_number(
    employee_number: str,
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.get_employee_by_number(employee_number)
    return success_response(
        data=EmployeeResponse.model_validate(employee).model_dump(mode="json"),
    )


@router.get("/employees/{employee_id}", summary="员工详情")
async def get_employee(
    employee_id: UUID,
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.get_employee(employee_id)
    return success_response(
        data=EmployeeResponse.model_validate(employee).model_dump(mode="json"),
    )


@router.put("/employees/{employee_id}", summary="更新员工")
async def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.update_employee(employee_id, payload)
    return success_response(
        data=EmployeeResponse.model_validate(employee).model_dump(mode="json"),
        message="员工更新成功",
    )


@router.delete("/employees/{employee_id}", summary="删除员工")
async def delete_employee(
    employee_id: UUID,
    service: EmployeeService = Depends(get_employee_service),
):
    await service.delete_employee(employee_id)
    return success_response(message="员工删除成功")


@router.get(
    "/employees/{employee_number}/onboarding-training-record",
    summary="导出员工入职培训记录",
)
async def export_onboarding_training_record(
    employee_number: str,
    service: EmployeeService = Depends(get_employee_service),
):
    """根据员工工号自动生成并下载入职培训记录 Word 文档。"""
    employee = await service.get_employee_by_number(employee_number)
    try:
        buffer: BytesIO = generate_onboarding_training_record(employee)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    filename = f"onboarding_training_record_{employee.employee_number}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class TrainingItem(BaseModel):
    sop_number: str = ""
    file_name: str = ""
    content: str = ""
    method: str = ""
    trainer: str = ""
    plan_date: str = ""


class TrainingExportRequest(BaseModel):
    training_items: list[TrainingItem] = []


@router.post(
    "/employees/{employee_number}/onboarding-training-record",
    summary="导出员工入职培训记录（带培训项）",
)
async def export_onboarding_training_record_with_items(
    employee_number: str,
    body: TrainingExportRequest,
    service: EmployeeService = Depends(get_employee_service),
):
    """根据员工工号和前端选中的培训项，生成入职培训记录 Word 文档。"""
    employee = await service.get_employee_by_number(employee_number)
    items = [it.model_dump() for it in body.training_items]
    try:
        buffer: BytesIO = generate_onboarding_training_record(employee, training_items=items)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    filename = f"onboarding_training_record_{employee.employee_number}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/employees/{employee_number}/training-record",
    summary="导出新员工培训记录",
)
async def export_training_record(
    employee_number: str,
    body: TrainingExportRequest,
    service: EmployeeService = Depends(get_employee_service),
):
    """根据员工工号和培训项，生成新员工培训记录 Word 文档。"""
    from app.modules.hr.training_record_generator import generate_training_record

    employee = await service.get_employee_by_number(employee_number)
    items = [it.model_dump() for it in body.training_items]
    try:
        buffer: BytesIO = generate_training_record(employee, training_items=items)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    filename = f"training_record_{employee.employee_number}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/employees/{employee_number}/work-permit",
    summary="导出员工上岗证",
)
async def export_work_permit(
    employee_number: str,
    body: TrainingExportRequest,
    service: EmployeeService = Depends(get_employee_service),
):
    """根据员工工号和培训项，生成上岗证 Word 文档。"""
    from app.modules.hr.work_permit_generator import generate_work_permit

    employee = await service.get_employee_by_number(employee_number)
    items = [it.model_dump() for it in body.training_items]
    try:
        buffer: BytesIO = generate_work_permit(employee, training_items=items)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    filename = f"work_permit_{employee.employee_number}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class PrejobTrainingItems(BaseModel):
    training_items: list[dict] = []


@router.post(
    "/employees/{employee_id}/prejob-training-plan",
    summary="导出员工岗前培训计划",
)
async def export_prejob_training_plan(
    employee_id: UUID,
    payload: PrejobTrainingItems | None = None,
    service: EmployeeService = Depends(get_employee_service),
    session: AsyncSession = Depends(get_db),
):
    """根据入职台账数据生成并下载岗前培训计划 Word 文档。

    优先使用入职台账（hr.onboarding_records）数据，
    找不到时回退到员工表（hr.employees）。
    支持 POST 传入前端填写的培训项（含计划完成日期、培训师、培训方式）。
    """
    from app.modules.hr.models import OnboardingRecord, PositionTraining

    # 优先查入职台账
    record = (await session.execute(
        select(OnboardingRecord).where(
            OnboardingRecord.id == employee_id,
            OnboardingRecord.is_deleted == False,
        )
    )).scalar_one_or_none()

    if record:
        person = record
        emp_no = record.employee_number
        dept = record.department
        pos = record.position
    else:
        person = await service.get_employee(employee_id)
        emp_no = person.employee_number
        dept = person.department
        pos = person.position

    # 前端传了培训项则优先用，否则查数据库
    if payload and payload.training_items:
        training_items = [
            {
                "training_category": item.get("content", "") or item.get("file_name", ""),
                "trainer": item.get("trainer", ""),
                "training_method": item.get("method", ""),
                "plan_date": item.get("plan_date", ""),
            }
            for item in payload.training_items
        ]
    else:
        # 查询岗位培训内容（精确匹配优先，无结果时模糊匹配）
        training_rows = (await session.execute(
            select(PositionTraining).where(
                PositionTraining.department == dept,
                PositionTraining.position_name == pos,
                PositionTraining.is_deleted == False,
            ).order_by(PositionTraining.sort_order)
        )).scalars().all()

        if not training_rows:
            training_rows = (await session.execute(
                select(PositionTraining).where(
                    PositionTraining.department == dept,
                    PositionTraining.position_name.ilike(f"%{pos}%"),
                    PositionTraining.is_deleted == False,
                ).order_by(PositionTraining.sort_order)
            )).scalars().all()

        training_items = [
            {
                "training_category": t.training_category or "",
                "trainer": t.trainer or "",
                "training_method": t.training_method or "",
                "plan_date": "",
            }
            for t in training_rows
        ]

    try:
        buffer: BytesIO = generate_prejob_training_plan(person, training_items)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    filename = f"prejob_training_plan_{emp_no}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/employees/{employee_id}/onboarding-evaluation",
    summary="导出员工上岗评估表",
)
async def export_onboarding_evaluation_by_employee(
    employee_id: UUID,
    service: EmployeeService = Depends(get_employee_service),
):
    """根据员工档案预填基本信息并导出上岗评估表 Excel 文档。"""
    employee = await service.get_employee(employee_id)

    payload = OnboardingEvaluationInput(
        employee_name=employee.name or "",
        employee_number=employee.employee_number or None,
        gender=employee.gender or None,
        department_position=f"{employee.department or ''}/{employee.position or ''}",
        hire_date=employee.hire_date,
    )
    buffer: BytesIO = generate_onboarding_evaluation(payload)

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    safe_date = str(employee.hire_date).replace("-", "") if employee.hire_date else "nodate"
    filename = f"onboarding_evaluation_{employee.employee_number}_{safe_date}.xlsx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )




@router.post("/training-sign-in-sheet", summary="生成培训签到表")
async def export_training_sign_in_sheet(
    payload: TrainingSignInSheetInput,
):
    """根据填写的培训信息自动生成培训签到表 Word 文档。

    超过一页（20人）时自动分页，所有页面合并在一个 docx 中。
    """
    safe_date = str(payload.training_date).replace("-", "")
    try:
        buffer: BytesIO = generate_training_sign_in_sheet(payload)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    safe_filename = f"training_sign_in_sheet_{safe_date}.docx"
    from urllib.parse import quote

    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"; filename*=utf-8''{quote('培训签到表_' + safe_date + '.docx')}"
        },
    )


class AssessmentScoreInput(BaseModel):
    training_content: str = ""
    training_date: str = ""
    department: str = ""
    scores: list[dict] = []


@router.post("/training-assessment-scores/export", summary="导出实操考核成绩单")
async def export_assessment_scores(payload: AssessmentScoreInput):
    """根据填写的培训信息和员工成绩，生成实操考核成绩单 Word 文档。"""
    from app.modules.hr.assessment_score_generator import generate_assessment_score_sheet

    buf = generate_assessment_score_sheet(
        training_content=payload.training_content,
        training_date=payload.training_date,
        department=payload.department,
        scores=payload.scores,
    )
    safe_date = payload.training_date.replace("-", "") if payload.training_date else "nodate"

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(f'考核成绩单_{safe_date}.docx')}"
        },
    )


@router.post("/training-notification", summary="生成培训通知")
async def export_training_notification(
    payload: TrainingNotificationInput,
    service: TrainingLedgerService = Depends(get_training_ledger_service),
):
    """根据填写的培训信息生成培训通知 Word 文档。培训台账需通过「添加到培训台账」按钮手动录入。"""
    try:
        buffer: BytesIO = generate_training_notification(payload)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    safe_date = str(payload.training_date).replace("-", "")
    filename = f"training_notification_{safe_date}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/training-notification/generate-assessment", summary="AI生成考核题目")
async def generate_assessment_questions(
    file: UploadFile,
    assessment_method: str = Form("笔试"),
    subject: str = Form(""),
):
    """上传培训材料文件，AI 自动生成考核题目。"""
    if not file.filename:
        raise HTTPException(400, "请上传文件")
    try:
        content = await file.read()
        # 尝试解码文件内容
        text = ""
        if file.filename.endswith(".txt"):
            text = content.decode("utf-8")
        elif file.filename.endswith(".docx"):
            from io import BytesIO
            from docx import Document
            doc = Document(BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        elif file.filename.endswith(".doc"):
            # 转换旧版 .doc 文件（兼容 macOS / Linux）
            import subprocess, tempfile, os, shutil
            with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                text = ""
                # macOS: 使用 textutil
                if shutil.which("textutil"):
                    result = subprocess.run(
                        ["textutil", "-convert", "txt", tmp_path, "-output", "/tmp/hr-doc-convert.txt"],
                        capture_output=True, timeout=30,
                    )
                    if result.returncode == 0:
                        with open("/tmp/hr-doc-convert.txt", "r") as f:
                            text = f.read()
                # Linux: 尝试 antiword / catdoc
                elif shutil.which("antiword"):
                    result = subprocess.run(["antiword", tmp_path], capture_output=True, timeout=30)
                    if result.returncode == 0:
                        text = result.stdout.decode("utf-8", errors="ignore")
                elif shutil.which("catdoc"):
                    result = subprocess.run(["catdoc", tmp_path], capture_output=True, timeout=30)
                    if result.returncode == 0:
                        text = result.stdout.decode("utf-8", errors="ignore")
                # 都不可用：提示安装
                if not text:
                    text = "（提示：服务器未安装 .doc 转换工具，请上传 .docx 或 .txt 格式文件）"
            finally:
                os.unlink(tmp_path)
        else:
            text = content.decode("utf-8", errors="ignore")

        if not text.strip():
            raise HTTPException(400, "无法提取文件内容，请确认文件不为空")

        # 截断过长文本
        text = text[:8000]

        # 使用 AI 生成题目
        from app.modules.hr.ai_service import AiChatService
        from app.core.config import get_settings
        settings = get_settings()
        api_key = settings.HR_AI_API_KEY
        model = settings.HR_AI_MODEL or "deepseek-chat"

        if api_key:
            service = AiChatService(api_key=api_key, model=model)
            qtype = "简答题" if assessment_method == "问答" else "选择题"
            prompt = f"""你是一个药厂培训考核出题人。根据以下培训材料生成4道{qtype}，参考题库风格：

风格要求（非常重要）：
1. 题目简短精炼，10-20字以内，直接问操作要点或关键知识
2. 答案简洁明了，15字以内，一句话说清
3. 参考示例：问"调平依据什么工具？"答"使用水平尺"、问"拿取砝码需佩戴什么？"答"佩戴手套操作"
4. 每题10分，总计40分
5. 题目必须基于材料内容，不要编造

请以JSON格式返回：
{{
  "title": "考核标题",
  "total_score": 40,
  "questions": [
    {{"type": "问答", "question": "简短题目", "answer": "简短答案", "score": 10}}
  ]
}}

培训主题：{subject}
培训材料：
{text}"""

            messages = [{"role": "user", "content": prompt}]
            full_response = ""
            async for chunk in service.stream_chat(messages):
                if chunk.get("type") == "content":
                    full_response += chunk["text"]

            import json
            json_start = full_response.find("{")
            json_end = full_response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(full_response[json_start:json_end])
            else:
                raise ValueError("AI 返回格式无法解析")
        else:
            # 无 AI key 时，基于文档内容生成提取式题目
            # 过滤掉页眉页脚等非内容行
            skip_patterns = ["LIVZON", "ADD:", "TEL:", "FAX:", "E-MAIL:", "Website:", "Page ", "TEM.", "丽珠集团"]
            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 10
                     and not any(p in l for p in skip_patterns)]
            questions = []
            for i, line in enumerate(lines[:8], 1):
                if len(line) > 30:
                    # 截取关键句作为题目
                    short = line[:60] + ("..." if len(line) > 60 else "")
                    questions.append({
                        "type": "问答",
                        "question": f"请简述以下内容：{short}",
                        "answer": line,
                        "score": 25,
                    })
                if len(questions) >= 4:
                    break
            # 不足4道则补
            while len(questions) < 4:
                i = len(questions) + 1
                questions.append({
                    "type": "问答",
                    "question": f"请总结培训材料第{i}部分的核心内容",
                    "answer": "",
                    "score": 25,
                })
            result = {
                "title": subject or "考核内容",
                "total_score": 100,
                "questions": questions[:4],
            }

        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"生成失败: {str(e)}")


@router.post("/training-evaluations/export-admin", summary="导出培训效果评估表（台账管理端）")
async def export_training_evaluation_admin(
    department: str = Form(""),
    training_subject: str = Form(""),
    training_date: str = Form(""),
    training_method: str = Form(""),
    trainer_name: str = Form(""),
    assessment_method: str = Form(""),
    expected_count: int = Form(0),
    actual_count: int = Form(0),
    exam_count: int = Form(0),
    excellent_count: int = Form(0),
    qualified_count: int = Form(0),
    unqualified_count: int = Form(0),
    session: AsyncSession = Depends(get_db),
):
    """导出培训效果评估表，自动关联年度计划和台账成绩。"""
    from app.modules.hr.evaluation_document_generator import generate_training_evaluation, TrainingEvaluationInput

    training_date_val = date.fromisoformat(training_date) if training_date else None
    plan_expected = expected_count
    plan_method = training_method or None
    plan_trainer = trainer_name or None
    plan_assessment = assessment_method or None
    plan_duration = None

    # 从年度计划补全空缺数据
    plan_target = None
    if department and training_subject:
        for subj_pat in (training_subject, f"%{training_subject}%", "%"):
            plan_row = (await session.execute(
                text("SELECT pi.trainee_count, pi.assessment_method, pi.training_method, pi.duration_hours, pi.content_and_textbook, pi.target_audience FROM hr.annual_training_plan_items pi JOIN hr.annual_training_plans p ON pi.plan_id = p.id WHERE p.department = :dept AND pi.content_and_textbook ILIKE :subj AND pi.is_deleted = false AND p.is_deleted = false LIMIT 1"),
                {"dept": department, "subj": subj_pat},
            )).fetchone()
            if plan_row:
                if not plan_expected and plan_row[0]:
                    plan_expected = int(plan_row[0])
                plan_assessment = plan_assessment or plan_row[1]
                plan_method = plan_method or plan_row[2]
                plan_duration = plan_duration or plan_row[3]
                plan_target = plan_row[5]  # target_audience
                break

    # 从台账统计成绩（混合文字+数字）
    if department and training_subject:
        if department and training_subject:
            scores_result = await session.execute(
                text("SELECT tl.assessment_result FROM hr.training_ledgers tl JOIN hr.employees e ON tl.employee_number = e.employee_number AND e.is_deleted = false WHERE tl.is_deleted = false AND e.department = :dept AND tl.training_subject ILIKE :subj AND tl.assessment_result IS NOT NULL AND tl.assessment_result != ''"),
                {"dept": department, "subj": f"%{training_subject}%"},
            )
            scores = [row[0] for row in scores_result.fetchall() if row[0]]
            if scores:
                exam_count = len(scores)
                excellent = qualified = unqualified = 0
                for s in scores:
                    try:
                        n = float(s)
                        if n >= 90: excellent += 1
                        elif n >= 80: qualified += 1
                        else: unqualified += 1
                    except ValueError:
                        if s in ("不合格", "unqualified", "fail"): unqualified += 1
                        elif s in ("合格", "qualified", "pass"): qualified += 1
                        elif s in ("优秀", "优", "excellent"): excellent += 1
                excellent_count = excellent
                qualified_count = qualified
                unqualified_count = unqualified

    # 从台账查培训对象（学员姓名列表），无则从年度计划取 target_audience
    trainee_names: list[str] = []
    if department and training_subject:
        names_result = await session.execute(
            text("SELECT e.name FROM hr.training_ledgers tl JOIN hr.employees e ON tl.employee_number = e.employee_number AND e.is_deleted = false WHERE tl.is_deleted = false AND e.department = :dept AND tl.training_subject ILIKE :subj"),
            {"dept": department, "subj": f"%{training_subject}%"},
        )
        trainee_names = list(dict.fromkeys(row[0] for row in names_result.fetchall() if row[0]))
    if not trainee_names and plan_target:
        trainee_names = [plan_target]

    # 应到人数：始终以部门在职员工数为准，不受台账记录数影响
    if department:
        emp_count = (await session.execute(
            text("SELECT count(*) FROM hr.employees WHERE department = :dept AND is_deleted = false AND status = '在职'"),
            {"dept": department},
        )).scalar()
        if not emp_count:
            emp_count = (await session.execute(
                text("SELECT count(*) FROM hr.onboarding_records WHERE department = :dept AND is_deleted = false AND is_employed = '是'"),
                {"dept": department},
            )).scalar()
        plan_expected = emp_count or 0

    # 实到人数 = 有成绩的人数（参加考核才算实到）
    actual_count = exam_count

    # 计算参与率和合格率
    participation_rate = None
    pass_rate = None
    if plan_expected and plan_expected > 0:
        participation_rate = f"{round(actual_count / plan_expected * 100)}%"
    if exam_count and exam_count > 0:
        pass_count = (excellent_count or 0) + (qualified_count or 0)
        pass_rate = f"{round(pass_count / exam_count * 100)}%"

    payload = TrainingEvaluationInput(
        subject=training_subject or "培训",
        training_date=training_date_val,
        training_method=plan_method,
        trainer=plan_trainer,
        assessment_method=plan_assessment,
        duration_hours=plan_duration,
        expected_count=plan_expected or None,
        actual_count=actual_count or None,
        exam_count=exam_count or None,
        excellent_count=excellent_count or None,
        qualified_count=qualified_count or None,
        unqualified_count=unqualified_count or None,
        trainee_names=trainee_names,
        participation_rate=participation_rate,
        pass_rate=pass_rate,
    )
    buffer: BytesIO = generate_training_evaluation(payload)
    safe_date = training_date.replace("-", "") if training_date else "nodate"
    filename = f"training_evaluation_{safe_date}.docx"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


@router.post("/training-evaluation", summary="生成培训效果评估表")
async def export_training_evaluation(
    payload: TrainingEvaluationInput,
):
    """根据填写的培训信息自动生成培训效果评估表 Word 文档。"""
    buffer: BytesIO = generate_training_evaluation(payload)

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    safe_date = str(payload.training_date).replace("-", "") if payload.training_date else "nodate"
    from urllib.parse import quote
    safe_filename = f"training_evaluation_{safe_date}.docx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"; filename*=utf-8''{quote('培训效果评估表_' + safe_date + '.docx')}"
        },
    )


@router.post("/onboarding-evaluation", summary="生成员工上岗评估表")
async def export_onboarding_evaluation(
    payload: OnboardingEvaluationInput,
):
    """根据填写的评估信息自动生成员工上岗评估表 Excel 文档。"""
    buffer: BytesIO = generate_onboarding_evaluation(payload)

    def _iterfile():
        buffer.seek(0)
        yield buffer.read()

    safe_date = str(payload.evaluation_date).replace("-", "") if payload.evaluation_date else "nodate"
    filename = f"onboarding_evaluation_{safe_date}.xlsx"
    return StreamingResponse(
        _iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Department Routes ───

@router.get("/departments", summary="部门列表")
async def list_departments(
    keyword: str | None = Query(None, description="部门名称或编码关键词"),
    page_params: PageParams = Depends(),
    service: DepartmentService = Depends(get_department_service),
):
    departments, total = await service.list_departments(
        keyword=keyword,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    data = [
        DepartmentResponse.model_validate(d).model_dump(mode="json")
        for d in departments
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/departments", summary="创建部门")
async def create_department(
    payload: DepartmentCreate,
    service: DepartmentService = Depends(get_department_service),
):
    department = await service.create_department(payload)
    return success_response(
        data=DepartmentResponse.model_validate(department).model_dump(mode="json"),
        message="部门创建成功",
        status_code=201,
    )


@router.get("/departments/{department_id}", summary="部门详情")
async def get_department(
    department_id: UUID,
    service: DepartmentService = Depends(get_department_service),
):
    department = await service.get_department(department_id)
    return success_response(
        data=DepartmentResponse.model_validate(department).model_dump(mode="json"),
    )


@router.put("/departments/{department_id}", summary="更新部门")
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    service: DepartmentService = Depends(get_department_service),
):
    department = await service.update_department(department_id, payload)
    return success_response(
        data=DepartmentResponse.model_validate(department).model_dump(mode="json"),
        message="部门更新成功",
    )


@router.delete("/departments/{department_id}", summary="删除部门")
async def delete_department(
    department_id: UUID,
    service: DepartmentService = Depends(get_department_service),
):
    await service.delete_department(department_id)
    return success_response(message="部门删除成功")


# ─── Position Routes ───

@router.get("/positions", summary="职位列表（按部门筛选）")
async def list_positions(
    department: str | None = Query(None, description="部门名称筛选"),
    session: AsyncSession = Depends(get_db),
):
    """返回职位列表，可按部门筛选，包含关联的培训大类。"""
    from app.modules.hr.models import HrPosition, PositionTraining

    q = select(HrPosition).where(HrPosition.is_deleted == False)
    if department:
        q = q.where(HrPosition.department == department)
    q = q.order_by(HrPosition.sort_order)

    result = await session.execute(q)
    rows = result.scalars().all()

    # 批量查询所有岗位关联的培训大类
    dept_pos_keys = {(r.department, r.name) for r in rows}
    pt_map: dict[tuple[str, str], list[str]] = {}
    if dept_pos_keys:
        pt_q = select(PositionTraining).where(
            PositionTraining.is_deleted == False,
            PositionTraining.training_category != "",
        )
        pt_rows = (await session.execute(pt_q)).scalars().all()
        for pt in pt_rows:
            key = (pt.department, pt.position_name)
            if key in dept_pos_keys:
                pt_map.setdefault(key, []).append(pt.training_category)

    data = [
        {
            "id": str(r.id),
            "department": r.department,
            "name": r.name,
            "categories": list(dict.fromkeys(pt_map.get((r.department, r.name), []))),
        }
        for r in rows
    ]
    return success_response(data=data)


class PositionCreate(BaseModel):
    department: str
    name: str


@router.post("/positions", summary="新建职位")
async def create_position(
    payload: PositionCreate,
    session: AsyncSession = Depends(get_db),
):
    """手动新建一个职位，写入 hr.positions 表。"""
    from app.modules.hr.models import HrPosition

    pos = HrPosition(department=payload.department, name=payload.name)
    session.add(pos)
    await session.flush()
    return success_response(
        data={"id": str(pos.id), "department": pos.department, "name": pos.name},
        message="职位创建成功",
        status_code=201,
    )


@router.delete("/positions/by-name/{position_name}", summary="按名称删除职位")
async def delete_position_by_name(
    position_name: str,
    department: str = Query(..., description="部门名称"),
    session: AsyncSession = Depends(get_db),
):
    """删除指定部门和名称的职位，同时清除关联的 SOP 目录条目。"""
    from app.modules.hr.models import HrPosition, SopCatalog

    pos = (await session.execute(
        select(HrPosition).where(
            HrPosition.department == department,
            HrPosition.name == position_name,
            HrPosition.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not pos:
        raise HTTPException(404, "职位不存在")
    await session.execute(text("DELETE FROM hr.sop_catalog WHERE department = :d AND position_name = :p"), {"d": department, "p": position_name})
    await session.execute(text("DELETE FROM hr.positions WHERE id = :id"), {"id": pos.id})
    await session.commit()
    return success_response(message="删除成功")


@router.get("/positions/departments", summary="职位表中所有部门")
async def list_position_departments(
    session: AsyncSession = Depends(get_db),
):
    """返回职位表中所有不重复的部门名称。"""
    from app.modules.hr.models import HrPosition

    result = await session.execute(
        select(HrPosition.department)
        .where(HrPosition.is_deleted == False)
        .distinct()
        .order_by(HrPosition.department)
    )
    return success_response(data=[row[0] for row in result.all()])


# ─── Position Training Routes ───

@router.get("/position-trainings", summary="岗位培训内容列表")
async def list_position_trainings(
    department: str | None = Query(None, description="部门筛选"),
    position_name: str | None = Query(None, description="岗位名称筛选"),
    session: AsyncSession = Depends(get_db),
):
    """按部门和岗位查询关联的培训内容（SOP/文件）。"""
    from app.modules.hr.models import PositionTraining

    q = select(PositionTraining).where(PositionTraining.is_deleted == False)
    if department:
        q = q.where(PositionTraining.department == department)
    if position_name:
        q = q.where(or_(
            PositionTraining.position_name == position_name,
            PositionTraining.position_name.endswith(position_name),
        ))
    q = q.order_by(PositionTraining.department, PositionTraining.position_name, PositionTraining.sort_order)

    result = await session.execute(q)
    rows = result.scalars().all()
    data = [
        {
            "id": str(r.id),
            "position_name": r.position_name,
            "department": r.department,
            "variety": r.variety,
            "training_category": r.training_category,
            "trainer": r.trainer,
            "training_method": r.training_method,
            "sop_number": r.sop_number,
            "file_name": r.file_name,
        }
        for r in rows
    ]
    return success_response(data=data)


class PositionTrainingCreate(BaseModel):
    department: str
    position_name: str
    training_category: str
    sop_number: str | None = None
    file_name: str


@router.post("/position-trainings", summary="新建岗位培训内容")
async def create_position_training(
    payload: PositionTrainingCreate,
    session: AsyncSession = Depends(get_db),
):
    """手动新建一条岗位培训关联记录。"""
    from app.modules.hr.models import PositionTraining, SopCatalog

    pt = PositionTraining(
        department=payload.department,
        position_name=payload.position_name,
        training_category=payload.training_category,
        sop_number=payload.sop_number,
        file_name=payload.file_name,
    )
    session.add(pt)

    # 同步写入 SOP 目录
    sc = SopCatalog(
        department=payload.department,
        category=payload.training_category,
        sop_number=payload.sop_number,
        file_name=payload.file_name,
        position_name=payload.position_name,
    )
    session.add(sc)

    await session.flush()
    return success_response(data={"id": str(pt.id)}, message="创建成功", status_code=201)


@router.get("/position-trainings/departments", summary="岗位培训内容中的部门列表")
async def list_pt_departments(
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import PositionTraining

    result = await session.execute(
        select(PositionTraining.department)
        .where(PositionTraining.is_deleted == False)
        .distinct()
        .order_by(PositionTraining.department)
    )
    return success_response(data=[row[0] for row in result.all()])


# ─── Team Routes ───

@router.get("/teams", summary="班组列表")
async def list_teams(
    department_id: UUID | None = Query(None, description="部门筛选"),
    keyword: str | None = Query(None, description="班组名称或编码关键词"),
    page_params: PageParams = Depends(),
    service: TeamService = Depends(get_team_service),
):
    teams, total = await service.list_teams(
        department_id=department_id,
        keyword=keyword,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    data = [
        TeamResponse.model_validate(t).model_dump(mode="json")
        for t in teams
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/teams", summary="创建班组")
async def create_team(
    payload: TeamCreate,
    service: TeamService = Depends(get_team_service),
):
    team = await service.create_team(payload)
    return success_response(
        data=TeamResponse.model_validate(team).model_dump(mode="json"),
        message="班组创建成功",
        status_code=201,
    )


@router.get("/teams/{team_id}", summary="班组详情")
async def get_team(
    team_id: UUID,
    service: TeamService = Depends(get_team_service),
):
    team = await service.get_team(team_id)
    return success_response(
        data=TeamResponse.model_validate(team).model_dump(mode="json"),
    )


@router.put("/teams/{team_id}", summary="更新班组")
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    service: TeamService = Depends(get_team_service),
):
    team = await service.update_team(team_id, payload)
    return success_response(
        data=TeamResponse.model_validate(team).model_dump(mode="json"),
        message="班组更新成功",
    )


@router.delete("/teams/{team_id}", summary="删除班组")
async def delete_team(
    team_id: UUID,
    service: TeamService = Depends(get_team_service),
):
    await service.delete_team(team_id)
    return success_response(message="班组删除成功")


# ─── OffboardingRecord Routes ───

@router.get("/offboarding-records", summary="离职记录列表")
async def list_offboarding_records(
    employee_id: UUID | None = Query(None, description="员工ID筛选"),
    keyword: str | None = Query(None, description="姓名或工号关键词"),
    page_params: PageParams = Depends(),
    service: OffboardingRecordService = Depends(get_offboarding_service),
):
    records, total = await service.list_records(
        employee_id=employee_id,
        keyword=keyword,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    data = [
        OffboardingRecordResponse.model_validate(r).model_dump(mode="json")
        for r in records
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/offboarding-records", summary="创建离职记录")
async def create_offboarding_record(
    payload: OffboardingRecordCreate,
    service: OffboardingRecordService = Depends(get_offboarding_service),
):
    record = await service.create_record(payload)
    # 手动构建响应，避免触发未加载的 relationship
    data = {
        "id": str(record.id),
        "employee_id": str(record.employee_id),
        "offboarding_date": (
            record.offboarding_date.isoformat()
            if record.offboarding_date else None
        ),
        "offboarding_type": record.offboarding_type,
        "reason": record.reason,
        "handover_status": record.handover_status,
        "notes": record.notes,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    return success_response(
        data=data,
        message="离职记录创建成功，员工状态已更新为离职",
        status_code=201,
    )


@router.get("/offboarding-records/{record_id}", summary="离职记录详情")
async def get_offboarding_record(
    record_id: UUID,
    service: OffboardingRecordService = Depends(get_offboarding_service),
):
    record = await service.get_record(record_id)
    return success_response(
        data=OffboardingRecordResponse.model_validate(record).model_dump(mode="json"),
    )


@router.put("/offboarding-records/{record_id}", summary="更新离职记录")
async def update_offboarding_record(
    record_id: UUID,
    payload: OffboardingRecordUpdate,
    service: OffboardingRecordService = Depends(get_offboarding_service),
):
    record = await service.update_record(record_id, payload)
    return success_response(
        data=OffboardingRecordResponse.model_validate(record).model_dump(mode="json"),
        message="离职记录更新成功",
    )


@router.delete("/offboarding-records/{record_id}", summary="删除离职记录")
async def delete_offboarding_record(
    record_id: UUID,
    service: OffboardingRecordService = Depends(get_offboarding_service),
):
    await service.delete_record(record_id)
    return success_response(message="离职记录删除成功")


# ─── OnboardingRecord Routes ───

@router.get("/onboarding-records", summary="老厂入职台账列表")
async def list_onboarding_records(
    department: str | None = Query(None, description="部门筛选"),
    position: str | None = Query(None, description="岗位筛选"),
    is_employed: str | None = Query("是", description="是否在职筛选，默认仅显示在职"),
    keyword: str | None = Query(None, description="姓名或工号关键词"),
    sort_by: str = Query("hire_date", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向"),
    page_params: PageParams = Depends(),
    service: OnboardingRecordService = Depends(get_onboarding_service),
):
    records, total = await service.list_records(
        department=department,
        position=position,
        is_employed=is_employed,
        keyword=keyword,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    data = [
        OnboardingRecordResponse.model_validate(r).model_dump(mode="json")
        for r in records
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.get("/onboarding-records/{record_id}", summary="入职记录详情")
async def get_onboarding_record(
    record_id: UUID,
    service: OnboardingRecordService = Depends(get_onboarding_service),
):
    record = await service.get_record(record_id)
    return success_response(
        data=OnboardingRecordResponse.model_validate(record).model_dump(mode="json"),
    )


@router.delete("/onboarding-records/{record_id}", summary="删除入职台账记录")
async def delete_onboarding_record(
    record_id: UUID,
    service: OnboardingRecordService = Depends(get_onboarding_service),
):
    await service.delete_record(record_id)
    return success_response(message="删除成功")


# ─── DepartureRecord Routes ───

@router.get("/departure-records", summary="老厂离职台账列表")
async def list_departure_records(
    department: str | None = Query(None, description="部门筛选"),
    offboarding_type: str | None = Query(None, description="离职类型筛选"),
    keyword: str | None = Query(None, description="姓名/部门/职位关键词"),
    sort_by: str = Query("offboarding_date", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向"),
    page_params: PageParams = Depends(),
    service: DepartureRecordService = Depends(get_departure_service),
):
    records, total = await service.list_records(
        department=department,
        offboarding_type=offboarding_type,
        keyword=keyword,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    data = [
        DepartureRecordResponse.model_validate(r).model_dump(mode="json")
        for r in records
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/departure-records", summary="创建离职台账记录")
async def create_departure_record(
    payload: DepartureRecordCreate,
    service: DepartureRecordService = Depends(get_departure_service),
):
    record = await service.create_record(payload)
    return success_response(
        data=DepartureRecordResponse.model_validate(record).model_dump(mode="json"),
        message="离职台账记录创建成功",
        status_code=201,
    )


@router.get("/departure-records/{record_id}", summary="离职台账记录详情")
async def get_departure_record(
    record_id: UUID,
    service: DepartureRecordService = Depends(get_departure_service),
):
    record = await service.get_record(record_id)
    return success_response(
        data=DepartureRecordResponse.model_validate(record).model_dump(mode="json"),
    )


@router.put("/departure-records/{record_id}", summary="更新离职台账记录")
async def update_departure_record(
    record_id: UUID,
    payload: DepartureRecordUpdate,
    service: DepartureRecordService = Depends(get_departure_service),
):
    record = await service.update_record(record_id, payload)
    return success_response(
        data=DepartureRecordResponse.model_validate(record).model_dump(mode="json"),
        message="离职台账记录更新成功",
    )


@router.delete("/departure-records/{record_id}", summary="删除离职台账记录")
async def delete_departure_record(
    record_id: UUID,
    service: DepartureRecordService = Depends(get_departure_service),
):
    await service.delete_record(record_id)
    return success_response(message="离职台账记录删除成功")


@router.post("/departure-records/{record_id}/preview-certificate", summary="预览离职证明")
async def preview_departure_certificate(
    record_id: UUID,
    service: DepartureRecordService = Depends(get_departure_service),
):
    from fastapi.responses import HTMLResponse
    from app.modules.hr.termination_certificate_generator import generate_termination_certificate_html
    record = await service.get_record(record_id)
    html = generate_termination_certificate_html(
        name=record.name or "", id_number=getattr(record, "id_card", "") or "",
        department=record.department or "", position=record.position or "",
        entry_date=getattr(record, "livo_entry_date", None) or getattr(record, "factory_entry_date", None) or "",
        leave_date=record.offboarding_date or "",
        leave_reason=getattr(record, "offboarding_type", "") or "个人原因",
    )
    return HTMLResponse(content=html)


@router.post("/departure-records/{record_id}/send-certificate", summary="发送离职证明邮件")
async def send_departure_certificate(
    record_id: UUID, employee_email: str = Form(...),
    service: DepartureRecordService = Depends(get_departure_service),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import EmailLog
    from app.modules.hr.termination_certificate_generator import generate_termination_certificate_docx
    from app.platform.mail_service import send_email
    record = await service.get_record(record_id)
    name = record.name or "员工"
    docx_buf = generate_termination_certificate_docx(
        name=name, id_number=getattr(record, "id_card", "") or "",
        department=record.department or "", position=record.position or "",
        entry_date=getattr(record, "livo_entry_date", None) or getattr(record, "factory_entry_date", None) or "",
        leave_date=record.offboarding_date or "",
        leave_reason=getattr(record, "offboarding_type", "") or "个人原因",
    )
    filename = f"解除劳动关系证明_{name}.docx"
    subj = "解除劳动关系证明"
    html = f"<html><body style=\"font-family:sans-serif;padding:20px;\"><h2>解除劳动关系证明</h2><p>{name}，您好！</p><p>附件是您的解除劳动关系证明，请查收。</p></body></html>"
    try:
        send_email(to=employee_email, subject=subj, html_body=html, attachments=[(filename, docx_buf.read())]); st, err = "sent", None
    except Exception as e:
        st, err = "failed", str(e)
    session.add(EmailLog(email_type="departure_cert", employee_name=name, recipient=employee_email, subject=subj, status=st, error_message=err))
    await session.commit()
    if st == "failed": raise HTTPException(500, f"发送失败: {err}")
    return success_response(message="离职证明已发送")


# ─── TrainingLedger Routes ───

@router.get("/training-ledgers", summary="培训台账列表")
async def list_training_ledgers(
    employee_number: str | None = Query(None, description="工号筛选"),
    date_from: date | None = Query(None, description="培训日期起"),
    date_to: date | None = Query(None, description="培训日期止"),
    page_params: PageParams = Depends(),
    service: TrainingLedgerService = Depends(get_training_ledger_service),
):
    records, total = await service.list_records(
        employee_number=employee_number,
        date_from=date_from,
        date_to=date_to,
        page=page_params.page,
        page_size=page_params.page_size,
        sort_by="training_date",
        sort_order="asc",
    )
    data = [
        TrainingLedgerResponse.model_validate(r).model_dump(mode="json")
        for r in records
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/training-ledgers", summary="创建培训台账记录")
async def create_training_ledger(
    payload: TrainingLedgerCreate,
    service: TrainingLedgerService = Depends(get_training_ledger_service),
):
    record = await service.create_record(payload)
    return success_response(
        data=TrainingLedgerResponse.model_validate(record).model_dump(mode="json"),
        message="培训台账记录创建成功",
        status_code=201,
    )


class BatchScoreUpdate(BaseModel):
    id: str
    assessment_result: str


class BatchScoreRequest(BaseModel):
    records: list[BatchScoreUpdate]


@router.post("/training-ledgers/batch-scores", summary="批量保存培训成绩")
async def batch_update_scores(
    body: BatchScoreRequest,
    session: AsyncSession = Depends(get_db),
):
    """批量更新培训台账中的考核成绩字段。"""
    updated = 0
    for rec in body.records:
        result = await session.execute(
            text("UPDATE hr.training_ledgers SET assessment_result = :r, updated_at = now() WHERE id = :id AND is_deleted = false"),
            {"r": rec.assessment_result, "id": rec.id},
        )
        updated += result.rowcount
    await session.commit()
    return success_response(data={"updated": updated}, message=f"已更新 {updated} 条")


# ─── TrainingLedgerPage Routes (must be before /{record_id}) ───

@router.get("/training-ledgers/pages", summary="已创建的培训台账页面列表")
async def list_training_ledger_pages(
    service: TrainingLedgerPageService = Depends(get_training_ledger_page_service),
):
    pages_with_dept = await service.list_pages_with_department()
    data = [
        {
            "id": str(page.id),
            "employee_number": page.employee_number,
            "employee_name": page.employee_name,
            "department": dept or "未知部门",
            "created_at": page.created_at.isoformat() if page.created_at else None,
            "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        }
        for page, dept in pages_with_dept
    ]
    return success_response(data=data)


@router.post("/training-ledgers/pages", summary="创建培训台账页面")
async def create_training_ledger_page(
    payload: TrainingLedgerPageCreate,
    service: TrainingLedgerPageService = Depends(get_training_ledger_page_service),
):
    page = await service.create_page(payload)
    return success_response(
        data=TrainingLedgerPageResponse(
            id=page.id,
            employee_number=page.employee_number,
            employee_name=page.employee_name,
            department=None,
            created_at=page.created_at,
            updated_at=page.updated_at,
        ).model_dump(mode="json"),
        message="培训台账页面创建成功",
        status_code=201,
    )


def _generate_training_ledger_excel(employee: dict, records: list[dict]) -> BytesIO:
    """Generate training ledger Excel based on employee training ledger format."""
    wb = Workbook()
    ws = wb.active
    ws.title = "员工培训台账"

    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    bold_font = Font(bold=True, size=11)
    title_font = Font(bold=True, size=16)

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 32
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 24
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12

    ws.merge_cells("A1:G1")
    ws["A1"] = "丽珠集团福州福兴医药有限公司"
    ws["A1"].font = title_font
    ws["A1"].alignment = center_align
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:G2")
    ws["A2"] = "员工培训台账"
    ws["A2"].font = bold_font
    ws["A2"].alignment = center_align
    ws.row_dimensions[2].height = 24

    ws["A3"] = "姓名"
    ws["A3"].font = bold_font
    ws["A3"].alignment = center_align
    ws["A3"].border = thin_border
    ws["B3"] = employee.get("name", "")
    ws["B3"].border = thin_border
    ws["C3"] = "性别"
    ws["C3"].font = bold_font
    ws["C3"].alignment = center_align
    ws["C3"].border = thin_border
    ws["D3"] = employee.get("gender", "")
    ws["D3"].border = thin_border
    ws["E3"] = "工作卡号"
    ws["E3"].font = bold_font
    ws["E3"].alignment = center_align
    ws["E3"].border = thin_border
    ws.merge_cells("F3:G3")
    ws["F3"] = employee.get("employee_number", "")
    ws["F3"].border = thin_border
    ws["G3"].border = thin_border

    ws["A4"] = "部门"
    ws["A4"].font = bold_font
    ws["A4"].alignment = center_align
    ws["A4"].border = thin_border
    ws["B4"] = employee.get("department", "")
    ws["B4"].border = thin_border
    ws["C4"] = "岗位/职务"
    ws["C4"].font = bold_font
    ws["C4"].alignment = center_align
    ws["C4"].border = thin_border
    ws["D4"] = employee.get("position", "")
    ws["D4"].border = thin_border
    ws["E4"] = "入厂时间"
    ws["E4"].font = bold_font
    ws["E4"].alignment = center_align
    ws["E4"].border = thin_border
    ws.merge_cells("F4:G4")
    ws["F4"] = employee.get("factory_entry_date") or employee.get("hire_date", "")
    ws["F4"].border = thin_border
    ws["G4"].border = thin_border

    ws["A5"] = "岗位变动"
    ws["A5"].font = bold_font
    ws["A5"].alignment = center_align
    ws["A5"].border = thin_border
    ws.merge_cells("B5:G5")
    ws["B5"] = employee.get("transfer_history", "无")
    ws["B5"].border = thin_border
    for c in range(3, 8):
        ws.cell(row=5, column=c).border = thin_border

    ws["A6"] = "记录"
    ws["A6"].font = bold_font
    ws["A6"].alignment = center_align
    ws["A6"].border = thin_border
    ws.merge_cells("B6:G6")
    ws["B6"] = ""
    ws["B6"].border = thin_border
    for c in range(3, 8):
        ws.cell(row=6, column=c).border = thin_border

    headers = ["年月日", "培训课程", "培训方式", "课时", "培训单位/培训师", "考核成绩", "备注"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=7, column=col, value=header)
        cell.font = bold_font
        cell.border = thin_border
        cell.alignment = center_align
    ws.row_dimensions[7].height = 24

    for idx, record in enumerate(records, 8):
        values = [
            record.get("training_date", ""),
            record.get("training_subject", ""),
            record.get("training_method", ""),
            record.get("duration_hours", ""),
            record.get("trainer", ""),
            record.get("assessment_result", ""),
            record.get("remarks", ""),
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=idx, column=col, value=val)
            cell.border = thin_border
            cell.alignment = center_align if col in (1, 3, 4, 6, 7) else left_align

    while len(records) < 12:
        row = 8 + len(records)
        for col in range(1, 8):
            ws.cell(row=row, column=col, value="").border = thin_border
        records.append({})

    footer_row = 8 + len(records)
    ws.merge_cells(f"A{footer_row}:G{footer_row}")
    ws.cell(row=footer_row, column=1, value="备注：笔试考核设置为满分100分，考试合格线为80分。")
    ws.cell(row=footer_row, column=1).alignment = left_align
    ws.cell(row=footer_row, column=1).border = thin_border
    for c in range(2, 8):
        ws.cell(row=footer_row, column=c).border = thin_border

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


@router.get("/training-ledgers/export", summary="导出培训台账Excel")
async def export_training_ledger(
    employee_number: str = Query(..., description="员工工号"),
    ledger_service: TrainingLedgerService = Depends(get_training_ledger_service),
    employee_service: EmployeeService = Depends(get_employee_service),
):
    """根据员工数据生成并导出培训台账 Excel 文件。"""
    employee = await employee_service.get_employee_by_number(employee_number)
    if not employee:
        raise HTTPException(status_code=404, detail="未找到该员工")

    records, _ = await ledger_service.list_records(
        employee_number=employee_number,
        page=1,
        page_size=1000,
        sort_by="training_date",
        sort_order="asc",
    )

    employee_dict = EmployeeResponse.model_validate(employee).model_dump(mode="json")
    record_dicts = [
        TrainingLedgerResponse.model_validate(r).model_dump(mode="json")
        for r in records
    ]

    buffer = _generate_training_ledger_excel(employee_dict, record_dicts)
    buffer.seek(0)

    safe_name = employee.name or "unknown"
    filename = f"{safe_name}培训台账.xlsx"
    encoded_filename = quote(filename, safe="")

    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"
        },
    )


@router.get("/training-ledgers/admin", summary="管理员培训台账总览")
async def ledger_admin(department: str | None = Query(None), training_subject: str | None = Query(None), date_from: date | None = Query(None), date_to: date | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import Employee, TrainingLedger
    cols = (TrainingLedger.id, TrainingLedger.employee_number, Employee.name.label("employee_name"), TrainingLedger.training_subject, TrainingLedger.training_date, TrainingLedger.training_method, TrainingLedger.trainer, TrainingLedger.assessment_result, Employee.department)
    stmt = select(*cols).join(Employee, TrainingLedger.employee_number == Employee.employee_number).where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
    if department: stmt = stmt.where(Employee.department == department)
    if training_subject: stmt = stmt.where(TrainingLedger.training_subject.ilike(f"%{training_subject}%"))
    if date_from: stmt = stmt.where(TrainingLedger.training_date >= date_from)
    if date_to: stmt = stmt.where(TrainingLedger.training_date <= date_to)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await session.execute(stmt.order_by(TrainingLedger.training_date.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return paginated_response(data=[{"id":str(r[0]),"employee_number":r[1],"employee_name":r[2],"training_subject":r[3],"training_date":str(r[4]) if r[4] else None,"training_method":r[5],"trainer":r[6],"assessment_result":r[7],"department":r[8]} for r in rows], page=page, page_size=page_size, total=total)


@router.get("/training-ledgers/admin/departments", summary="台账中的部门列表")
async def ledger_admin_departments(session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import Employee, TrainingLedger
    r = (await session.execute(
        select(Employee.department).select_from(TrainingLedger)
        .join(Employee, TrainingLedger.employee_number == Employee.employee_number)
        .where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
        .distinct().order_by(Employee.department)
    )).all()
    return success_response(data=[d[0] for d in r if d[0]])


@router.get("/training-ledgers/admin/subjects", summary="台账中的培训内容列表")
async def ledger_admin_subjects(department: str | None = Query(None), session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import Employee, TrainingLedger
    stmt = (select(TrainingLedger.training_subject).select_from(TrainingLedger)
        .join(Employee, TrainingLedger.employee_number == Employee.employee_number)
        .where(TrainingLedger.is_deleted == False, Employee.is_deleted == False))
    if department: stmt = stmt.where(Employee.department == department)
    r = (await session.execute(stmt.distinct().order_by(TrainingLedger.training_subject))).all()
    return success_response(data=[s[0] for s in r if s[0]])


@router.get("/training-ledgers/admin/stats", summary="培训台账统计")
async def ledger_admin_stats(department: str | None = Query(None), training_subject: str | None = Query(None), date_from: date | None = Query(None), date_to: date | None = Query(None), session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import Employee, TrainingLedger
    base = select(TrainingLedger.assessment_result).select_from(TrainingLedger).join(Employee, TrainingLedger.employee_number == Employee.employee_number).where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
    if department: base = base.where(Employee.department == department)
    if training_subject: base = base.where(TrainingLedger.training_subject == training_subject)
    if date_from: base = base.where(TrainingLedger.training_date >= date_from)
    if date_to: base = base.where(TrainingLedger.training_date <= date_to)
    rows = (await session.execute(base)).all()
    total = len(rows)
    qualified = sum(1 for r in rows if r[0] and _parse_score(r[0]) >= 80)
    return success_response(data={"total": total, "qualified": qualified, "pass_rate": f"{qualified/max(total,1)*100:.0f}%" if total else "0%"})

def _parse_score(v: str | None) -> int:
    if not v: return 0
    try: return int(float(v))
    except: return 0


@router.get("/question-bank", summary="题库检索")
async def qbank_search(file_no: str | None = Query(None), keyword: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=500), session: AsyncSession = Depends(get_db)):
    where = "WHERE is_deleted = false"
    params: dict = {"lim": page_size, "off": (page - 1) * page_size}
    if file_no: where += " AND file_no ILIKE :fn"; params["fn"] = f"%{file_no}%"
    if keyword: where += " AND (question ILIKE :kw OR subject ILIKE :kw)"; params["kw"] = f"%{keyword}%"
    r = await session.execute(text(f"SELECT id, file_no, question, answer, score, source, usage_count FROM hr.question_bank {where} ORDER BY usage_count DESC LIMIT :lim OFFSET :off"), params)
    return success_response(data=[{"id":str(row[0]),"file_no":row[1],"question":row[2],"answer":row[3],"score":row[4],"source":row[5],"usage_count":row[6]} for row in r])


@router.post("/question-bank/import-docx", summary="从培训记录 docx 导入题库")
async def qbank_import_docx(
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
):
    """上传培训记录 .docx，自动提取问答题目并导入题库。"""
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(400, "仅支持 .docx 格式")
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(400, "读取文件失败")

    from app.modules.hr.qa_docx_importer import parse_training_record

    try:
        subject, questions = parse_training_record(content, file.filename or "")
    except Exception as e:
        raise HTTPException(400, f"解析文档失败: {e}")

    if not questions:
        raise HTTPException(400, "未从文档中提取到问答题目，请确认文件包含问答记录表")

    imported = 0
    for q in questions:
        # 检查去重：同 file_no + question
        existing = (await session.execute(
            text("SELECT 1 FROM hr.question_bank WHERE file_no = :fn AND question = :q AND is_deleted = false"),
            {"fn": q["file_no"], "q": q["question"]},
        )).first()
        if existing:
            continue
        await session.execute(
            text("INSERT INTO hr.question_bank (id, file_no, question, answer, score, source) VALUES (gen_random_uuid(), :fn, :q, :a, :s, :src)"),
            {"fn": q["file_no"], "q": q["question"], "a": q["answer"], "s": q["score"], "src": "docx_import"},
        )
        imported += 1

    await session.flush()
    return success_response(
        data={"subject": subject, "total": len(questions), "imported": imported, "skipped": len(questions) - imported},
        message=f"导入完成：新增 {imported} 题，跳过 {len(questions) - imported} 题（重复）",
        status_code=201,
    )


# ─── QA Assessments ───

class QaAssessmentCreateBody(BaseModel):
    subject: str
    department: str | None = None
    training_date: str | None = None
    training_method: str | None = None
    assessment_method: str | None = "问答"
    trainer: str | None = None
    questions: list[dict] | None = None
    question_count: int = 0
    full_score: int = 100
    excellent_line: int = 90
    pass_line: int = 80
    trainee_names: list[str] = []


@router.post("/qa-assessments", summary="创建考核场次")
async def create_qa_assessment(
    payload: QaAssessmentCreateBody,
    session: AsyncSession = Depends(get_db),
):
    """创建问答考核场次，含选题快照和受训人员名单。"""
    import json

    total_score = sum((q.get("score", 10) or 10) for q in (payload.questions or []))
    if total_score == 0 and payload.full_score:
        total_score = payload.full_score

    def _date(v: str | None):
        if not v:
            return None
        try:
            return date.fromisoformat(v)
        except (ValueError, TypeError):
            return None

    result = await session.execute(
        text("""INSERT INTO hr.qa_assessments
            (subject, department, training_date, training_method, assessment_method, trainer,
             questions, question_count, full_score, excellent_line, pass_line, trainee_names)
            VALUES (:s, :d, :td, :tm, :am, :t, :q, :qc, :fs, :el, :pl, :tn)
            RETURNING id"""),
        {
            "s": payload.subject, "d": payload.department,
            "td": _date(payload.training_date), "tm": payload.training_method,
            "am": payload.assessment_method, "t": payload.trainer,
            "q": json.dumps(payload.questions, ensure_ascii=False) if payload.questions else None,
            "qc": payload.question_count,
            "fs": total_score, "el": payload.excellent_line, "pl": payload.pass_line,
            "tn": json.dumps(payload.trainee_names, ensure_ascii=False),
        },
    )
    assessment_id = result.scalar_one()
    await session.flush()
    return success_response(data={"id": str(assessment_id)}, message="考核场次创建成功", status_code=201)


@router.get("/qa-assessments", summary="考核场次列表")
async def list_qa_assessments(
    department: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    """按部门查询考核场次列表。"""
    where = "WHERE is_deleted = false"
    params: dict = {"lim": page_size, "off": (page - 1) * page_size}
    if department:
        where += " AND department = :dept"
        params["dept"] = department
    total = (await session.execute(
        text(f"SELECT count(*) FROM hr.qa_assessments {where}"),
        {k: v for k, v in params.items() if k != "lim" and k != "off"},
    )).scalar() or 0
    rows = (await session.execute(
        text(f"SELECT id, subject, department, training_date, training_method, assessment_method, trainer, question_count, created_at FROM hr.qa_assessments {where} ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
        params,
    )).fetchall()
    data = [
        {
            "id": str(r[0]), "subject": r[1], "department": r[2],
            "training_date": str(r[3]) if r[3] else None,
            "training_method": r[4], "assessment_method": r[5], "trainer": r[6],
            "question_count": r[7], "created_at": str(r[8]) if r[8] else None,
        }
        for r in rows
    ]
    return paginated_response(data=data, page=page, page_size=page_size, total=total)


class QaScoreSaveBody(BaseModel):
    assessed_date: str | None = None
    scores: list[dict] = []


@router.get("/qa-assessments/{assessment_id}", summary="考核场次详情")
async def get_qa_assessment(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """获取考核详情，含题目和成绩。"""
    import json as _json
    row = (await session.execute(
        text("SELECT id, subject, department, training_date, training_method, assessment_method, trainer, questions, question_count, full_score, excellent_line, pass_line, trainee_names, created_at FROM hr.qa_assessments WHERE id = :id AND is_deleted = false"),
        {"id": assessment_id},
    )).fetchone()
    if not row:
        raise HTTPException(404, "考核场次不存在")

    scores = (await session.execute(
        text("SELECT id, employee_name, employee_number, wrong_questions, total_score, grade, result_text, assessed_date FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND is_deleted = false"),
        {"aid": assessment_id},
    )).fetchall()

    return success_response(data={
        "assessment": {
            "id": str(row[0]), "subject": row[1], "department": row[2],
            "training_date": str(row[3]) if row[3] else None,
            "training_method": row[4], "assessment_method": row[5], "trainer": row[6],
            "questions": (row[7] if isinstance(row[7], list) else _json.loads(row[7])) if row[7] else [],
            "question_count": row[8], "full_score": row[9],
            "excellent_line": row[10], "pass_line": row[11],
            "trainee_names": (row[12] if isinstance(row[12], list) else _json.loads(row[12])) if row[12] else [],
            "created_at": str(row[13]) if row[13] else None,
        },
        "scores": [
            {
                "id": str(s[0]), "employee_name": s[1], "employee_number": s[2],
                "wrong_questions": (s[3] if isinstance(s[3], list) else (_json.loads(s[3]) if s[3] else [])), "total_score": s[4],
                "grade": s[5], "result_text": s[6],
                "assessed_date": str(s[7]) if s[7] else None,
            }
            for s in scores
        ],
    })


@router.put("/qa-assessments/{assessment_id}/scores", summary="保存考核成绩")
async def save_qa_scores(
    assessment_id: UUID,
    payload: QaScoreSaveBody,
    session: AsyncSession = Depends(get_db),
):
    """保存或更新考核成绩。"""
    import json as _json

    from datetime import date as _date

    def _d(v: str | None):
        if not v:
            return None
        try:
            return _date.fromisoformat(v)
        except (ValueError, TypeError):
            return None

    # 获取考核场次题目信息用于准确计分
    assess_row = (await session.execute(
        text("SELECT questions, full_score, excellent_line, pass_line FROM hr.qa_assessments WHERE id = :id AND is_deleted = false"),
        {"id": assessment_id},
    )).fetchone()
    questions_data: list[dict] = []
    full_score_val = 100
    if assess_row:
        qs = assess_row[0]
        questions_data = qs if isinstance(qs, list) else (_json.loads(qs) if isinstance(qs, str) else [])
        full_score_val = assess_row[1] or 100

    # 更新考核日期
    if payload.assessed_date:
        await session.execute(
            text("UPDATE hr.qa_assessments SET training_date = :d WHERE id = :id"),
            {"d": _d(payload.assessed_date), "id": assessment_id},
        )

    for s in payload.scores:
        name = s.get("employee_name", "")
        if not name:
            continue
        wrong = s.get("wrong_questions") or []
        # 根据实际题目分值计算总分
        if questions_data:
            deduction = sum(
                (questions_data[i - 1].get("score", 10) if isinstance(questions_data[i - 1], dict) else 10)
                for i in wrong if isinstance(i, int) and 1 <= i <= len(questions_data)
            )
            score = max(0, full_score_val - deduction)
        else:
            per_q = full_score_val / max(len(questions_data) or 10, 1)
            score = max(0, full_score_val - len(wrong) * int(per_q))

        existing = (await session.execute(
            text("SELECT id FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND employee_name = :nm AND is_deleted = false"),
            {"aid": assessment_id, "nm": name},
        )).first()
        if existing:
            await session.execute(
                text("UPDATE hr.qa_assessment_scores SET wrong_questions=:wq, total_score=:ts, assessed_date=:ad WHERE id=:id"),
                {"wq": _json.dumps(wrong), "ts": score, "ad": _d(payload.assessed_date), "id": existing[0]},
            )
        else:
            await session.execute(
                text("INSERT INTO hr.qa_assessment_scores (assessment_id, employee_name, employee_number, wrong_questions, total_score, assessed_date) VALUES (:aid, :nm, :en, :wq, :ts, :ad)"),
                {
                    "aid": assessment_id, "nm": name,
                    "en": s.get("employee_number", ""),
                    "wq": _json.dumps(wrong), "ts": score,
                    "ad": _d(payload.assessed_date),
                },
            )

    await session.flush()

    # 同步写入培训台账
    assessment = (await session.execute(
        text("SELECT subject, training_date, training_method, trainer FROM hr.qa_assessments WHERE id = :id"),
        {"id": assessment_id},
    )).fetchone()
    if assessment:
        subj, train_date, method, trainer = assessment
        for s in payload.scores:
            name = s.get("employee_name", "")
            emp_no = s.get("employee_number", "")
            if not name:
                continue
            # 没工号时从员工表反查
            if not emp_no:
                emp = (await session.execute(
                    text("SELECT employee_number FROM hr.employees WHERE name = :nm AND is_deleted = false LIMIT 1"),
                    {"nm": name},
                )).fetchone()
                if emp and emp[0]:
                    emp_no = emp[0]
            if not emp_no:
                continue
            wrong = s.get("wrong_questions") or []
            if questions_data:
                deduction = sum(
                    (questions_data[i - 1].get("score", 10) if isinstance(questions_data[i - 1], dict) else 10)
                    for i in wrong if isinstance(i, int) and 1 <= i <= len(questions_data)
                )
                score = max(0, full_score_val - deduction)
            else:
                per_q = full_score_val / max(len(questions_data) or 10, 1)
                score = max(0, full_score_val - len(wrong) * int(per_q))
            ledger_date = _d(payload.assessed_date) or train_date or _date.today()
            exist = (await session.execute(
                text("SELECT 1 FROM hr.training_ledgers WHERE employee_number = :en AND training_date = :td AND training_subject = :ts AND is_deleted = false"),
                {"en": emp_no, "td": ledger_date, "ts": subj},
            )).first()
            if not exist:
                await session.execute(
                    text("INSERT INTO hr.training_ledgers (id, employee_number, training_date, training_subject, training_method, trainer, assessment_result, source_type) VALUES (gen_random_uuid(), :en, :td, :ts, :tm, :t, :ar, 'qa_assessment')"),
                    {"en": emp_no, "td": ledger_date, "ts": subj, "tm": method, "t": trainer, "ar": str(score)},
                )

    await session.commit()
    return success_response(message="成绩保存成功，已同步培训台账")


@router.post("/qa-assessments/{assessment_id}/sync-ledger", summary="同步成绩到培训台账")
async def sync_qa_to_ledger(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """将考核场次的成绩批量同步到培训台账。"""
    from datetime import date as _date

    # 获取考核场次
    assess = (await session.execute(
        text("SELECT subject, training_date, training_method, trainer FROM hr.qa_assessments WHERE id = :id AND is_deleted = false"),
        {"id": assessment_id},
    )).fetchone()
    if not assess:
        raise HTTPException(404, "考核场次不存在")

    subj, train_date, method, trainer = assess
    td = train_date or _date.today()

    # 获取所有成绩
    scores = (await session.execute(
        text("SELECT employee_name, employee_number, total_score FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND is_deleted = false"),
        {"aid": assessment_id},
    )).fetchall()

    if not scores:
        raise HTTPException(400, "该考核场次还没有成绩记录，请先保存成绩")

    synced = 0
    skipped_exist = 0
    no_emp = 0
    no_emp_names: list[str] = []

    for name, emp_no, score in scores:
        # 反查工号
        if not emp_no:
            emp = (await session.execute(
                text("SELECT employee_number FROM hr.employees WHERE name = :nm AND is_deleted = false LIMIT 1"),
                {"nm": name},
            )).fetchone()
            if emp and emp[0]:
                emp_no = emp[0]
        if not emp_no:
            no_emp += 1
            no_emp_names.append(name or "?")
            continue

        exist = (await session.execute(
            text("SELECT 1 FROM hr.training_ledgers WHERE employee_number = :en AND training_subject = :ts AND is_deleted = false"),
            {"en": emp_no, "ts": subj},
        )).fetchone()
        if exist:
            skipped_exist += 1
            continue

        await session.execute(
            text("INSERT INTO hr.training_ledgers (id, employee_number, training_date, training_subject, training_method, trainer, assessment_result, source_type) VALUES (gen_random_uuid(), :en, :td, :ts, :tm, :t, :ar, 'qa_assessment')"),
            {"en": emp_no, "td": td, "ts": subj, "tm": method or "", "t": trainer or "", "ar": str(score or 0)},
        )
        synced += 1

    await session.commit()

    msg = f"已同步 {synced} 人到培训台账"
    if skipped_exist:
        msg += f"，{skipped_exist} 人已存在跳过"
    if no_emp:
        msg += f"，{no_emp} 人缺工号未同步"
        if no_emp_names:
            msg += f"（{'、'.join(no_emp_names[:5])}{'...' if len(no_emp_names) > 5 else ''}）"

    return success_response(
        data={"synced": synced, "skipped": skipped_exist, "no_emp": no_emp},
        message=msg,
    )


@router.delete("/qa-assessments/{assessment_id}", summary="删除考核场次")
async def delete_qa_assessment(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """软删除考核场次及关联成绩。"""
    await session.execute(text("UPDATE hr.qa_assessments SET is_deleted = true WHERE id = :id"), {"id": assessment_id})
    await session.execute(text("UPDATE hr.qa_assessment_scores SET is_deleted = true WHERE assessment_id = :id"), {"id": assessment_id})
    await session.flush()
    return success_response(message="考核场次已删除")


class QaRecordExportRequest(BaseModel):
    training_content: str = ""
    training_date: str = ""
    training_method: str = ""
    training_department: str = ""
    questions_json: str = "[]"
    trainee_names_json: str = "[]"
    scores_json: str = "[]"
    trainer_name: str = ""


@router.post("/training-notification/export-qa-record-with-scores", summary="导出含错题的完整实操记录表")
async def export_training_qa_record_with_scores(
    body: QaRecordExportRequest,
    session: AsyncSession = Depends(get_db),
):
    """导出含学员错题记录和评分的完整问答实操记录表。"""
    import json as _json
    from app.modules.hr.qa_record_generator import generate_qa_record

    questions = _json.loads(body.questions_json) if body.questions_json else []
    trainee_names = _json.loads(body.trainee_names_json) if body.trainee_names_json else []
    scores_raw = _json.loads(body.scores_json) if body.scores_json else []
    training_date_val = date.fromisoformat(body.training_date) if body.training_date else None

    # 构建带错题描述的 score entries
    score_entries = []
    for s in scores_raw:
        wrong_indices = s.get("wrong_questions", []) or []
        total_q = len(questions)
        if wrong_indices and total_q:
            wrong_nums = "、".join(str(i + 1) for i in wrong_indices)
            result_text = f"第{wrong_nums}题错误，其他题目正确"
        else:
            result_text = "全对，所有题目回答正确"
        score_entries.append({
            "name": s.get("name", ""),
            "employee_number": "",
            "total_score": str(s.get("total_score", "")),
            "assessed_date": str(training_date_val) if training_date_val else "",
            "result_text": result_text,
        })

    # 尝试保存考核记录到数据库（失败不影响导出）
    try:
        import uuid as _uuid
        assessment_id = _uuid.uuid4()
        await session.execute(
            text("INSERT INTO hr.qa_assessments (id, subject, department, training_date, training_method, trainer, questions, trainee_names) VALUES (:id, :subject, :dept, :date, :method, :trainer, :questions, :trainees)"),
            {"id": assessment_id, "subject": body.training_content or "问答考核", "dept": body.training_department, "date": training_date_val, "method": body.training_method, "trainer": body.trainer_name, "questions": _json.dumps(questions), "trainees": _json.dumps(trainee_names)},
        )
        for s in scores_raw:
            await session.execute(
                text("INSERT INTO hr.qa_assessment_scores (id, assessment_id, employee_name, wrong_questions, total_score, assessed_date) VALUES (gen_random_uuid(), :aid, :name, :wrong, :score, :date)"),
                {"aid": assessment_id, "name": s.get("name", ""), "wrong": _json.dumps(s.get("wrong_questions", [])), "score": s.get("total_score", 0), "date": training_date_val},
            )
        await session.commit()
    except Exception:
        await session.rollback()

    buffer = generate_qa_record(
        training_content=body.training_content,
        training_date=training_date_val,
        training_method=body.training_method,
        training_department=body.training_department,
        questions=questions,
        trainee_names=trainee_names,
        scores=score_entries,
        trainer_name=body.trainer_name,
    )
    filename = f"问答实操记录表_{body.training_date}.docx"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


@router.post("/training-notification/export-score-report", summary="导出成绩单")
async def export_score_report(body: QaRecordExportRequest, session: AsyncSession = Depends(get_db)):
    """导出考核成绩单，同时自动录入培训台账。"""
    import json as _json
    from app.modules.hr.score_report_generator import generate_score_report

    scores_raw = _json.loads(body.scores_json) if body.scores_json else []
    training_date_val = date.fromisoformat(body.training_date) if body.training_date else None
    scores = [{"name": s.get("name", ""), "department": body.training_department, "total_score": s.get("total_score", 0)} for s in scores_raw]

    # 自动将成绩写入培训台账
    for s in scores_raw:
        name = s.get("name", "")
        score = s.get("total_score", 0)
        if not name:
            continue
        # 查找该员工的工号
        emp_row = (await session.execute(
            text("SELECT employee_number FROM hr.onboarding_records WHERE name = :n AND is_deleted = false AND is_employed = '是' LIMIT 1"),
            {"n": name},
        )).fetchone()
        emp_no = emp_row[0] if emp_row else None
        if emp_no:
            # 检查是否已有培训记录，有则更新成绩
            existing = (await session.execute(
                text("SELECT id FROM hr.training_ledgers WHERE employee_number = :en AND training_subject = :subj AND is_deleted = false LIMIT 1"),
                {"en": emp_no, "subj": body.training_content},
            )).fetchone()
            if existing:
                await session.execute(
                    text("UPDATE hr.training_ledgers SET assessment_result = :r, updated_at = now() WHERE id = :id"),
                    {"r": str(score), "id": existing[0]},
                )
            else:
                await session.execute(
                    text("INSERT INTO hr.training_ledgers (id, employee_number, training_subject, training_date, assessment_result, source_type) VALUES (gen_random_uuid(), :en, :subj, :date, :r, 'manual')"),
                    {"en": emp_no, "subj": body.training_content, "date": training_date_val, "r": str(score)},
                )
    await session.commit()

    buffer = generate_score_report(training_content=body.training_content, training_date=body.training_date, department=body.training_department, scores=scores)
    filename = f"成绩单_{body.training_date}.docx"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


@router.post("/training-notification/export-qa-record", summary="导出问答实操记录表")
async def export_training_qa_record(
    training_content: str = Form("", description="培训内容"),
    training_purpose: str = Form("", description="培训目的"),
    training_date: str = Form("", description="培训日期"),
    training_method: str = Form("", description="培训方式"),
    training_department: str = Form("", description="受训部门"),
    questions_json: str = Form("[]", description="题目JSON"),
    trainee_names_json: str = Form("[]", description="学员姓名JSON"),
):
    """从培训通知页直接导出问答实操记录表（无评分数据，供打印后手写）。"""
    import json as _json
    from app.modules.hr.qa_record_generator import generate_qa_record

    questions = _json.loads(questions_json) if questions_json else []
    trainee_names = _json.loads(trainee_names_json) if trainee_names_json else []
    training_date_val = date.fromisoformat(training_date) if training_date else None

    buffer = generate_qa_record(
        training_content=training_content,
        training_purpose=training_purpose,
        training_date=training_date_val,
        training_method=training_method,
        training_department=training_department,
        questions=questions,
        trainee_names=trainee_names,
    )
    filename = f"问答实操记录表_{training_date}.docx"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


@router.get("/qa-assessments/{assessment_id}/export-record", summary="导出问答记录表")
async def export_qa_record(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """导出问答实操记录表 docx。"""
    from app.modules.hr.qa_record_generator import generate_qa_record
    import json as _json

    row = (await session.execute(
        text("SELECT subject, department, training_date, training_method, trainer, questions, trainee_names FROM hr.qa_assessments WHERE id = :id AND is_deleted = false"),
        {"id": assessment_id},
    )).fetchone()
    if not row:
        raise HTTPException(404, "考核场次不存在")

    scores = (await session.execute(
        text("SELECT employee_name, employee_number, wrong_questions, total_score, assessed_date FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND is_deleted = false"),
        {"aid": assessment_id},
    )).fetchall()

    questions = row[5] if isinstance(row[5], list) else (_json.loads(row[5]) if row[5] else [])
    trainee_names = row[6] if isinstance(row[6], list) else (_json.loads(row[6]) if row[6] else [])

    score_entries = []
    for s in scores:
        wrong = s[2] if isinstance(s[2], list) else (_json.loads(s[2]) if s[2] else [])
        wrong_set = set(wrong)
        total_q = len(questions)
        wrong_nums = "、".join(str(i+1) for i in range(total_q) if i in wrong_set) if total_q else ""
        result_text = f"第{wrong_nums}题错误，其他题目正确" if wrong_nums else "全对，所有题目回答正确"
        score_entries.append({
            "name": s[0],
            "employee_number": s[1] or "",
            "total_score": str(s[3]) if s[3] is not None else "",
            "assessed_date": str(s[4]) if s[4] else "",
            "result_text": result_text,
        })

    try:
        buffer = generate_qa_record(
            training_content=row[0] or "",
            training_department=row[1] or "",
            training_date=row[2],
            training_method=row[3] or "",
            trainer_name=row[4] or "",
            questions=questions,
            trainee_names=trainee_names,
            scores=score_entries,
        )
    except Exception as e:
        raise HTTPException(400, f"生成记录表失败: {e}")

    def _iter(): buffer.seek(0); yield buffer.read()
    return StreamingResponse(_iter(), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=qa_record.docx"})


@router.get("/qa-assessments/{assessment_id}/export-evaluation", summary="导出培训效果评估表")
async def export_qa_evaluation(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """导出培训效果评估表 docx。自动从成绩数据汇总统计。"""
    from app.modules.hr.evaluation_document_generator import generate_training_evaluation, TrainingEvaluationInput

    row = (await session.execute(
        text("SELECT subject, department, training_date, training_method, trainer, assessment_method FROM hr.qa_assessments WHERE id = :id AND is_deleted = false"),
        {"id": assessment_id},
    )).fetchone()
    if not row:
        raise HTTPException(404, "考核场次不存在")

    scores = (await session.execute(
        text("SELECT employee_name, total_score FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND is_deleted = false"),
        {"aid": assessment_id},
    )).fetchall()

    # 从成绩汇总统计
    total = len(scores)
    excellent = sum(1 for s in scores if (s[1] or 0) >= 90)
    qualified = sum(1 for s in scores if 80 <= (s[1] or 0) < 90)
    unqualified = sum(1 for s in scores if (s[1] or 0) < 80)

    # 应到人数 = 部门总人数
    dept_count = (await session.execute(
        text("SELECT count(*) FROM hr.employees WHERE department = :d AND is_deleted = false"),
        {"d": row[1] or ""},
    )).scalar()
    expected = dept_count if dept_count else None

    pass_rate = f"{(excellent + qualified) / max(total, 1) * 100:.0f}%" if total > 0 else ""
    participation = f"{total / max(expected or total, 1) * 100:.0f}%" if total > 0 else ""

    payload = TrainingEvaluationInput(
        subject=row[0] or "",
        training_date=row[2],
        training_method=row[3] or "",
        trainer=row[4] or "",
        assessment_method=row[5] or "",
        trainee_names=[s[0] for s in scores],
        expected_count=expected,
        actual_count=total if total > 0 else None,
        exam_count=total if total > 0 else None,
        excellent_count=excellent if total > 0 else None,
        qualified_count=qualified if total > 0 else None,
        unqualified_count=unqualified if total > 0 else None,
        pass_rate=pass_rate or None,
        participation_rate=participation or None,
    )
    try:
        buffer = generate_training_evaluation(payload)
    except Exception as e:
        raise HTTPException(400, f"生成评估表失败: {e}")

    def _iter(): buffer.seek(0); yield buffer.read()
    return StreamingResponse(_iter(), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=qa_evaluation.docx"})


@router.get("/qa-assessments/{assessment_id}/export-scores", summary="导出成绩单")
async def export_qa_scores(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """导出成绩单 docx（使用成绩单模板），并自动同步成绩到培训台账。"""
    from app.modules.hr.score_report_generator import generate_score_report
    from datetime import date as _date

    row = (await session.execute(
        text("SELECT subject, department, training_date, training_method, trainer FROM hr.qa_assessments WHERE id = :id AND is_deleted = false"),
        {"id": assessment_id},
    )).fetchone()
    if not row:
        raise HTTPException(404, "考核场次不存在")

    subj, dept, train_date, method, trainer = row

    scores = (await session.execute(
        text("SELECT employee_name, employee_number, total_score FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND is_deleted = false ORDER BY employee_name"),
        {"aid": assessment_id},
    )).fetchall()

    dept = dept or ""
    score_list = [{"name": s[0], "total_score": s[2] or 0, "department": dept} for s in scores]

    # 同步到培训台账
    def _d(v):
        if not v: return None
        try: return _date.fromisoformat(str(v))
        except: return None

    td = _d(train_date) or _date.today()
    for s in scores:
        name, emp_no, score = s[0], s[1], s[2] or 0
        # 没工号时从员工表反查
        if not emp_no:
            emp = (await session.execute(
                text("SELECT employee_number FROM hr.employees WHERE name = :nm AND is_deleted = false LIMIT 1"),
                {"nm": name},
            )).fetchone()
            if emp and emp[0]:
                emp_no = emp[0]
        if not emp_no:
            continue
        exist = (await session.execute(
            text("SELECT 1 FROM hr.training_ledgers WHERE employee_number = :en AND training_date = :td AND training_subject = :ts AND is_deleted = false"),
            {"en": emp_no, "td": td, "ts": subj},
        )).first()
        if not exist:
            await session.execute(
                text("INSERT INTO hr.training_ledgers (id, employee_number, training_date, training_subject, training_method, trainer, assessment_result, source_type) VALUES (gen_random_uuid(), :en, :td, :ts, :tm, :t, :ar, 'qa_assessment')"),
                {"en": emp_no, "td": td, "ts": subj, "tm": method, "t": trainer, "ar": str(score)},
            )
    await session.commit()

    try:
        buffer = generate_score_report(
            training_content=row[0] or "",
            training_date=str(row[2] or ""),
            department=row[1] or "",
            scores=score_list,
        )
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"生成成绩单失败: {e}")

    def _iter(): buffer.seek(0); yield buffer.read()
    return StreamingResponse(_iter(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=score_report.docx"})


@router.get("/training-ledgers/{record_id}", summary="培训台账记录详情")
async def get_training_ledger(
    record_id: UUID,
    service: TrainingLedgerService = Depends(get_training_ledger_service),
):
    record = await service.get_record(record_id)
    return success_response(
        data=TrainingLedgerResponse.model_validate(record).model_dump(mode="json"),
    )


@router.put("/training-ledgers/{record_id}", summary="更新培训台账记录")
async def update_training_ledger(
    record_id: UUID,
    payload: TrainingLedgerUpdate,
    service: TrainingLedgerService = Depends(get_training_ledger_service),
):
    record = await service.update_record(record_id, payload)
    return success_response(
        data=TrainingLedgerResponse.model_validate(record).model_dump(mode="json"),
        message="培训台账记录更新成功",
    )


@router.delete("/training-ledgers/{record_id}", summary="删除培训台账记录")
async def delete_training_ledger(
    record_id: UUID,
    service: TrainingLedgerService = Depends(get_training_ledger_service),
):
    await service.delete_record(record_id)
    return success_response(message="培训台账记录删除成功")


# ─── AnnualTrainingPlan Routes ───

@router.post("/annual-training-plans/upload", summary="上传年度培训计划")
async def upload_annual_training_plan(
    file: UploadFile,
    service: EmployeeService = Depends(get_employee_service),
):
    """上传 Excel 年度培训计划，按年度+部门自动分类为计划项。"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx / .xls 格式")
    try:
        content = await file.read()
        result = await service.upload_annual_plan(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(
        data=result,
        message=f"新增 {result['created']} 条，更新 {result['updated']} 条"
        + (f"，{len(result['errors'])} 条失败" if result.get('errors') else ""),
    )


@router.get("/annual-training-plans", summary="年度培训计划列表")
async def list_annual_training_plans(
    year: int | None = Query(None, description="年度筛选"),
    department: str | None = Query(None, description="部门筛选"),
    page_params: PageParams = Depends(),
    service: AnnualTrainingPlanService = Depends(get_annual_training_plan_service),
    session: AsyncSession = Depends(get_db),
):
    plans, total = await service.list_plans(
        year=year,
        department=department,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    # 批量查每个计划的培训完成进度
    plan_ids = [p.id for p in plans]
    progress_map: dict = {}
    if plan_ids:
        rows = (await session.execute(
            text("SELECT plan_id, count(*) as total, sum(CASE WHEN tracking_status = '完成' THEN 1 ELSE 0 END) as done FROM hr.annual_training_plan_items WHERE plan_id = ANY(:pids) AND is_deleted = false GROUP BY plan_id"),
            {"pids": plan_ids},
        )).fetchall()
        progress_map = {str(r[0]): f"{int(r[2] or 0)}/{int(r[1])} 已完成" for r in rows}

    data = [
        {
            **AnnualTrainingPlanResponse.model_validate(p).model_dump(mode="json"),
            "training_progress": progress_map.get(str(p.id), ""),
        }
        for p in plans
    ]
    return paginated_response(
        data=data,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.post("/annual-training-plans", summary="创建年度培训计划")
async def create_annual_training_plan(
    payload: AnnualTrainingPlanCreate,
    service: AnnualTrainingPlanService = Depends(get_annual_training_plan_service),
):
    plan = await service.create_plan(payload)
    return success_response(
        data=AnnualTrainingPlanResponse.model_validate(plan).model_dump(mode="json"),
        message="年度培训计划创建成功",
        status_code=201,
    )


@router.get("/annual-training-plans/{plan_id}", summary="年度培训计划详情")
async def get_annual_training_plan(
    plan_id: UUID,
    service: AnnualTrainingPlanService = Depends(get_annual_training_plan_service),
):
    plan = await service.get_plan(plan_id)
    return success_response(
        data=AnnualTrainingPlanResponse.model_validate(plan).model_dump(mode="json"),
    )


@router.put("/annual-training-plans/{plan_id}", summary="更新年度培训计划")
async def update_annual_training_plan(
    plan_id: UUID,
    payload: AnnualTrainingPlanUpdate,
    service: AnnualTrainingPlanService = Depends(get_annual_training_plan_service),
):
    plan = await service.update_plan(plan_id, payload)
    return success_response(
        data=AnnualTrainingPlanResponse.model_validate(plan).model_dump(mode="json"),
        message="年度培训计划更新成功",
    )


@router.delete("/annual-training-plans/{plan_id}", summary="删除年度培训计划")
async def delete_annual_training_plan(
    plan_id: UUID,
    service: AnnualTrainingPlanService = Depends(get_annual_training_plan_service),
):
    await service.delete_plan(plan_id)
    return success_response(message="年度培训计划删除成功")


@router.get("/annual-plan-items", summary="全部年度计划明细（扁平列表）")
async def list_all_annual_plan_items(
    year: int | None = Query(None, description="年度筛选"),
    department: str | None = Query(None, description="部门筛选"),
    keyword: str | None = Query(None, description="培训内容关键词"),
    session: AsyncSession = Depends(get_db),
):
    """返回所有年度计划明细的扁平列表，关联部门信息，用于表格展示。"""
    conditions = ["i.is_deleted = false", "p.is_deleted = false"]
    params: dict = {}
    if year is not None:
        conditions.append("p.year = :year")
        params["year"] = year
    if department:
        conditions.append("p.department ILIKE :dept")
        params["dept"] = f"%{department}%"
    if keyword:
        conditions.append("i.content_and_textbook ILIKE :kw")
        params["kw"] = f"%{keyword}%"

    where = " AND ".join(conditions)
    sql = text(f"""
        SELECT i.id, i.month, i.content_and_textbook, i.target_audience,
               i.position_and_count, i.training_method, i.duration_hours,
               i.confirmer, i.confirm_date, i.remarks, i.tracking_status,
               i.location, i.assessment_method, i.notes,
               p.department, p.year, p.id as plan_id
        FROM hr.annual_training_plan_items i
        JOIN hr.annual_training_plans p ON i.plan_id = p.id
        WHERE {where}
        ORDER BY p.department, i.month
    """)
    rows = (await session.execute(sql, params)).all()

    return success_response(data=[
        {
            "id": str(r[0]), "month": r[1], "content_and_textbook": r[2],
            "target_audience": r[3], "position_and_count": r[4],
            "training_method": r[5], "duration_hours": r[6],
            "confirmer": r[7], "confirm_date": str(r[8]) if r[8] else None,
            "remarks": r[9], "tracking_status": r[10],
            "location": r[11], "assessment_method": r[12], "notes": r[13],
            "department": r[14], "year": r[15], "plan_id": str(r[16]),
        }
        for r in rows
    ])


@router.get("/annual-training-plans/{plan_id}/items", summary="年度计划明细列表")
async def list_annual_training_plan_items(
    plan_id: UUID,
    service: AnnualTrainingPlanItemService = Depends(get_annual_training_plan_item_service),
):
    items = await service.list_items(plan_id)
    data = [
        AnnualTrainingPlanItemResponse.model_validate(i).model_dump(mode="json")
        for i in items
    ]
    return success_response(data=data)


class CreatePlanItemBody(BaseModel):
    month: str | None = None
    content_and_textbook: str | None = None
    target_audience: str | None = None
    position_and_count: str | None = None
    training_method: str | None = None
    assessment_method: str | None = None
    location: str | None = None
    duration_hours: float | None = None
    confirm_date: str | None = None
    notes: str | None = None
    remarks: str | None = None


@router.post("/annual-training-plans/{plan_id}/items", summary="新增年度计划明细")
async def create_annual_training_plan_item(
    plan_id: UUID,
    payload: CreatePlanItemBody,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import AnnualTrainingPlanItem
    from datetime import date as dt_date

    item = AnnualTrainingPlanItem(plan_id=plan_id, **payload.model_dump(exclude_none=True))
    if payload.confirm_date:
        try:
            item.confirm_date = dt_date.fromisoformat(payload.confirm_date)
        except ValueError:
            pass
    session.add(item)
    await session.flush()
    return success_response(
        data=AnnualTrainingPlanItemResponse.model_validate(item).model_dump(mode="json"),
        message="创建成功",
        status_code=201,
    )


@router.delete("/annual-training-plans/{plan_id}/items/{item_id}", summary="删除年度计划明细")
async def delete_annual_training_plan_item(
    plan_id: UUID,
    item_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """软删除一条年度计划明细。"""
    from app.modules.hr.models import AnnualTrainingPlanItem
    item = (await session.execute(
        select(AnnualTrainingPlanItem).where(
            AnnualTrainingPlanItem.id == item_id,
            AnnualTrainingPlanItem.plan_id == plan_id,
            AnnualTrainingPlanItem.is_deleted == False,
        )
    )).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "明细不存在")
    # 同时物理删除关联的培训台账记录
    if item.content_and_textbook:
        from app.modules.hr.models import TrainingLedger
        ledgers = (await session.execute(
            select(TrainingLedger).where(
                TrainingLedger.training_subject == item.content_and_textbook,
            )
        )).scalars().all()
        for ledger in ledgers:
            session.delete(ledger)
    session.delete(item)
    await session.flush()
    return success_response(message="删除成功")


@router.put("/annual-training-plans/{plan_id}/items/batch", summary="批量更新年度计划明细")
async def batch_update_annual_training_plan_items(
    plan_id: UUID,
    payload: AnnualTrainingPlanItemBatchUpdate,
    service: AnnualTrainingPlanItemService = Depends(get_annual_training_plan_item_service),
):
    items = await service.batch_update_items(plan_id, payload)
    data = [
        AnnualTrainingPlanItemResponse.model_validate(i).model_dump(mode="json")
        for i in items
    ]
    return success_response(
        data=data,
        message="年度计划明细更新成功",
    )


def _generate_annual_plan_excel(plan: dict, items: list[dict]) -> BytesIO:
    """Generate annual training plan Excel based on 7.7 template format."""
    wb = Workbook()
    ws = wb.active
    ws.title = "年度培训计划"

    # Styles
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    bold_font = Font(bold=True, size=11)
    title_font = Font(bold=True, size=16)

    # Column widths
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 32
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 10
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 14
    ws.column_dimensions["I"].width = 10

    # Title row
    ws.merge_cells("A1:I1")
    ws["A1"] = f"{plan['year']} 年培训计划"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # Department row
    ws.merge_cells("A2:I2")
    ws["A2"] = f"部门：{plan['department']}"
    ws["A2"].font = bold_font
    ws["A2"].alignment = left_align
    ws.row_dimensions[2].height = 22

    # Header row
    headers = ["序号", "培训季度及课时", "培训内容及使用教材", "培训对象",
               "授课单位及授课人", "考核方式", "培训跟踪", "确认人/日期", "备注"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col, value=header)
        cell.font = bold_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = center_align
    ws.row_dimensions[3].height = 28

    # Data rows
    for idx, item in enumerate(items, 1):
        row = 3 + idx
        quarter = item.get("month") or ""
        hours = item.get("duration_hours")
        quarter_hours = f"{quarter}\n{hours}课时" if hours else quarter

        values = [
            idx,
            quarter_hours,
            item.get("content_and_textbook") or "",
            item.get("target_audience") or "",
            item.get("position_and_count") or "",
            item.get("training_method") or "",
            item.get("tracking_status") or "",
            f"{item.get('confirmer') or ''}{' / ' + str(item.get('confirm_date')) if item.get('confirm_date') else ''}",
            item.get("remarks") or "",
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = center_align if col in (1, 2, 6, 7) else left_align
        ws.row_dimensions[row].height = 36

    # Pad to at least 12 rows
    while len(items) < 12:
        row = 3 + len(items) + 1
        for col in range(1, 10):
            cell = ws.cell(row=row, column=col, value="")
            cell.border = thin_border
        ws.row_dimensions[row].height = 36
        items.append({})

    # Footer row
    footer_row = 4 + len(items) + 1
    ws.merge_cells(f"A{footer_row}:E{footer_row}")
    ws.cell(row=footer_row, column=1, value="制表人/日期：")
    ws.cell(row=footer_row, column=1).alignment = left_align
    ws.cell(row=footer_row, column=1).border = thin_border
    for c in range(2, 6):
        ws.cell(row=footer_row, column=c).border = thin_border

    ws.merge_cells(f"F{footer_row}:I{footer_row}")
    ws.cell(row=footer_row, column=6, value="部门负责人/日期：")
    ws.cell(row=footer_row, column=6).alignment = left_align
    ws.cell(row=footer_row, column=6).border = thin_border
    for c in range(7, 10):
        ws.cell(row=footer_row, column=c).border = thin_border

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


@router.post("/annual-training-plans/complete-by-content", summary="按培训内容标记完成")
async def complete_plan_by_content(
    payload: dict = None,
    session: AsyncSession = Depends(get_db),
):
    """根据培训内容标记所有匹配的年度计划明细为已完成。"""
    from app.modules.hr.models import AnnualTrainingPlanItem
    content = payload.get("content", "") if payload else ""
    if not content:
        raise HTTPException(400, "缺少培训内容")
    items = (await session.execute(
        select(AnnualTrainingPlanItem).where(
            AnnualTrainingPlanItem.content_and_textbook == content,
            AnnualTrainingPlanItem.is_deleted == False,
        )
    )).scalars().all()
    for item in items:
        item.tracking_status = "完成"
    await session.flush()
    return success_response(data={"updated": len(items)}, message=f"已标记 {len(items)} 条为完成")


@router.get("/annual-training-plans/{plan_id}/export", summary="导出年度培训计划Excel")
async def export_annual_training_plan(
    plan_id: UUID,
    plan_service: AnnualTrainingPlanService = Depends(get_annual_training_plan_service),
    item_service: AnnualTrainingPlanItemService = Depends(get_annual_training_plan_item_service),
):
    """根据年度计划数据生成并导出Excel文件（7.7年度培训计划格式）。"""
    plan = await plan_service.get_plan(plan_id)
    items = await item_service.list_items(plan_id)

    plan_dict = AnnualTrainingPlanResponse.model_validate(plan).model_dump(mode="json")
    item_dicts = [
        AnnualTrainingPlanItemResponse.model_validate(i).model_dump(mode="json")
        for i in items
    ]

    buffer = _generate_annual_plan_excel(plan_dict, item_dicts)
    buffer.seek(0)

    safe_dept = plan.department.replace(" ", "_")
    filename = f"{plan.year}年度培训计划_{safe_dept}.xlsx"
    encoded_filename = quote(filename, safe="")

    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"
        },
    )

# ─── Trainer Routes ───


@router.post("/trainers/upload", summary="上传内训师台账")
async def upload_trainers(
    file: UploadFile,
    service: EmployeeService = Depends(get_employee_service),
):
    """上传 Excel 内训师名单，按姓名+部门自动新增或更新。"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx / .xls 格式")
    try:
        content = await file.read()
        result = await service.upload_trainers(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=result, message=f"新增 {result['created']}，更新 {result['updated']}")


@router.get("/trainers", summary="内训师台账列表", response_model=TrainerListResponse)
async def list_trainers(
    department: str | None = Query(None),
    keyword: str | None = Query(None),
    is_level1: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import HrTrainer
    from app.core.response import paginated_response

    query = select(HrTrainer).where(HrTrainer.is_deleted == False)
    count_q = select(func.count()).select_from(HrTrainer).where(HrTrainer.is_deleted == False)
    if department:
        query = query.where(HrTrainer.department == department)
        count_q = count_q.where(HrTrainer.department == department)
    if is_level1:
        query = query.where(HrTrainer.is_level1 == is_level1)
        count_q = count_q.where(HrTrainer.is_level1 == is_level1)
    if keyword:
        query = query.where(
            or_(HrTrainer.name.ilike(f"%{keyword}%"), HrTrainer.trainable_departments.ilike(f"%{keyword}%"))
        )
        count_q = count_q.where(
            or_(HrTrainer.name.ilike(f"%{keyword}%"), HrTrainer.trainable_departments.ilike(f"%{keyword}%"))
        )

    total = (await session.execute(count_q)).scalar() or 0
    rows = (await session.execute(query.order_by(HrTrainer.department, HrTrainer.name).offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return paginated_response(
        data=[TrainerResponse.model_validate(r).model_dump(mode="json") for r in rows],
        page=page, page_size=page_size, total=total,
    )


class TrainerCreate(BaseModel):
    name: str
    department: str | None = None
    trainable_departments: str | None = None
    qualification_scope: str | None = None
    certification_date: date | None = None
    confirmation_date: date | None = None
    confirmation_reminder: date | None = None
    is_level1: str | None = None
    admin: str | None = None
    remarks: str | None = None


@router.post("/trainers", summary="新增内训师")
async def create_trainer(payload: TrainerCreate, session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import HrTrainer
    t = HrTrainer(**payload.model_dump())
    session.add(t)
    await session.flush()
    return success_response(data=TrainerResponse.model_validate(t).model_dump(mode="json"), message="创建成功", status_code=201)


@router.put("/trainers/{trainer_id}", summary="更新内训师")
async def update_trainer(trainer_id: UUID, payload: TrainerCreate, session: AsyncSession = Depends(get_db)):
    from app.modules.hr.models import HrTrainer
    t = (await session.execute(select(HrTrainer).where(HrTrainer.id == trainer_id, HrTrainer.is_deleted == False))).scalar_one_or_none()
    if not t: raise HTTPException(404, "内训师不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    await session.flush()
    return success_response(data=TrainerResponse.model_validate(t).model_dump(mode="json"), message="更新成功")


@router.delete("/trainers/{trainer_id}", summary="删除内训师")
async def delete_trainer(
    trainer_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    await session.execute(text("DELETE FROM hr.trainers WHERE id = :id"), {"id": trainer_id})
    await session.commit()
    return success_response(message="删除成功")


@router.delete("/trainers", summary="清空内训师台账")
async def clear_trainers(
    session: AsyncSession = Depends(get_db),
):
    await session.execute(text("DELETE FROM hr.trainers"))
    await session.commit()
    return success_response(message="清空成功")


# ─── DeptTrainingPersonnel Routes ───


@router.get("/dept-training-personnel", summary="部门培训人员表列表")
async def list_dept_training_personnel(
    department: str | None = Query(None, description="部门筛选"),
    keyword: str | None = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import DeptTrainingPersonnel

    query = select(DeptTrainingPersonnel).where(DeptTrainingPersonnel.is_deleted == False)
    count_q = select(func.count()).select_from(DeptTrainingPersonnel).where(DeptTrainingPersonnel.is_deleted == False)

    if department:
        query = query.where(
            or_(
                DeptTrainingPersonnel.department == department,
                DeptTrainingPersonnel.display_department == department,
            )
        )
        count_q = count_q.where(
            or_(
                DeptTrainingPersonnel.department == department,
                DeptTrainingPersonnel.display_department == department,
            )
        )
    if keyword:
        query = query.where(
            or_(
                DeptTrainingPersonnel.display_department.ilike(f"%{keyword}%"),
                DeptTrainingPersonnel.training_admin.ilike(f"%{keyword}%"),
                DeptTrainingPersonnel.department_head.ilike(f"%{keyword}%"),
                DeptTrainingPersonnel.level1_trainer.ilike(f"%{keyword}%"),
            )
        )
        count_q = count_q.where(
            or_(
                DeptTrainingPersonnel.display_department.ilike(f"%{keyword}%"),
                DeptTrainingPersonnel.training_admin.ilike(f"%{keyword}%"),
                DeptTrainingPersonnel.department_head.ilike(f"%{keyword}%"),
                DeptTrainingPersonnel.level1_trainer.ilike(f"%{keyword}%"),
            )
        )

    total = (await session.execute(count_q)).scalar() or 0
    rows = (
        await session.execute(
            query.order_by(DeptTrainingPersonnel.display_department, DeptTrainingPersonnel.variety)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return paginated_response(
        data=[DeptTrainingPersonnelResponse.model_validate(r).model_dump(mode="json") for r in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


class DeptTrainingPersonnelCreateBody(BaseModel):
    display_department: str
    variety: str | None = None
    department: str
    training_admin: str | None = None
    department_head: str | None = None
    level1_trainer: str | None = None


@router.post("/dept-training-personnel", summary="新增部门培训人员")
async def create_dept_training_personnel(
    payload: DeptTrainingPersonnelCreateBody,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import DeptTrainingPersonnel

    t = DeptTrainingPersonnel(**payload.model_dump())
    session.add(t)
    await session.flush()
    return success_response(
        data=DeptTrainingPersonnelResponse.model_validate(t).model_dump(mode="json"),
        message="创建成功",
        status_code=201,
    )


@router.put("/dept-training-personnel/{item_id}", summary="更新部门培训人员")
async def update_dept_training_personnel(
    item_id: UUID,
    payload: DeptTrainingPersonnelCreateBody,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import DeptTrainingPersonnel

    t = (
        await session.execute(
            select(DeptTrainingPersonnel).where(
                DeptTrainingPersonnel.id == item_id,
                DeptTrainingPersonnel.is_deleted == False,
            )
        )
    ).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "记录不存在")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    await session.flush()
    return success_response(
        data=DeptTrainingPersonnelResponse.model_validate(t).model_dump(mode="json"),
        message="更新成功",
    )


@router.delete("/dept-training-personnel/{item_id}", summary="删除部门培训人员")
async def delete_dept_training_personnel(
    item_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import DeptTrainingPersonnel

    t = (
        await session.execute(
            select(DeptTrainingPersonnel).where(
                DeptTrainingPersonnel.id == item_id,
                DeptTrainingPersonnel.is_deleted == False,
            )
        )
    ).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "记录不存在")
    t.is_deleted = True
    await session.flush()
    return success_response(message="删除成功")


@router.post("/dept-training-personnel/upload", summary="上传部门培训人员表")
async def upload_dept_training_personnel(
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
):
    """上传 Excel 部门培训人员表，按体现部门+品种去重 upsert。"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx / .xls 格式")

    try:
        content = await file.read()
        import openpyxl
        from io import BytesIO

        wb = openpyxl.load_workbook(BytesIO(content))
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))  # skip header

        created = 0
        updated = 0

        for row in rows:
            display_dept = str(row[1]).strip() if row[1] else None
            if not display_dept:
                continue
            variety = str(row[2]).strip() if len(row) > 2 and row[2] else None
            department = str(row[3]).strip() if len(row) > 3 and row[3] else display_dept
            training_admin = str(row[4]).strip() if len(row) > 4 and row[4] else None
            department_head = str(row[5]).strip() if len(row) > 5 and row[5] else None
            level1_trainer = str(row[6]).strip() if len(row) > 6 and row[6] else None

            from app.modules.hr.models import DeptTrainingPersonnel

            # 按体现部门+品种去重查找
            existing_q = select(DeptTrainingPersonnel).where(
                DeptTrainingPersonnel.is_deleted == False,
                DeptTrainingPersonnel.display_department == display_dept,
            )
            if variety:
                existing_q = existing_q.where(DeptTrainingPersonnel.variety == variety)
            else:
                existing_q = existing_q.where(DeptTrainingPersonnel.variety.is_(None))

            existing = (await session.execute(existing_q)).scalar_one_or_none()

            if existing:
                existing.department = department
                existing.training_admin = training_admin
                existing.department_head = department_head
                existing.level1_trainer = level1_trainer
                updated += 1
            else:
                t = DeptTrainingPersonnel(
                    display_department=display_dept,
                    variety=variety,
                    department=department,
                    training_admin=training_admin,
                    department_head=department_head,
                    level1_trainer=level1_trainer,
                )
                session.add(t)
                created += 1

        await session.flush()
    except Exception as e:
        raise HTTPException(400, f"导入失败: {str(e)}")

    return success_response(
        data={"created": created, "updated": updated},
        message=f"新增 {created}，更新 {updated}",
    )


# ─── SOP Catalog Routes ───

@router.delete("/sop-catalog/{item_id}", summary="删除SOP目录条目")
async def delete_sop_catalog_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import SopCatalog
    item = (await session.execute(
        select(SopCatalog).where(SopCatalog.id == item_id, SopCatalog.is_deleted == False)
    )).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "SOP条目不存在")
    await session.execute(text("DELETE FROM hr.sop_catalog WHERE id = :id"), {"id": item_id})
    await session.commit()
    return success_response(message="删除成功")


@router.post("/sop-catalog/upload", summary="上传SOP目录")
async def upload_sop_catalog(
    file: UploadFile,
    service: EmployeeService = Depends(get_employee_service),
):
    """上传 Excel SOP 目录，按 SOP编号 自动新增或更新。"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 .xlsx / .xls 格式")
    try:
        content = await file.read()
        result = await service.upload_sop_catalog(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=result, message=f"新增 {result['created']}，更新 {result['updated']}")


@router.get("/sop-catalog", summary="SOP目录列表", response_model=SopCatalogListResponse)
async def list_sop_catalog(
    department: str | None = Query(None),
    category: str | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import SopCatalog
    from app.core.response import paginated_response

    query = select(SopCatalog).where(SopCatalog.is_deleted == False)
    count_q = select(func.count()).select_from(SopCatalog).where(SopCatalog.is_deleted == False)
    if department:
        query = query.where(SopCatalog.department == department)
        count_q = count_q.where(SopCatalog.department == department)
    if category:
        query = query.where(SopCatalog.category == category)
        count_q = count_q.where(SopCatalog.category == category)
    if keyword:
        query = query.where(SopCatalog.file_name.ilike(f"%{keyword}%"))
        count_q = count_q.where(SopCatalog.file_name.ilike(f"%{keyword}%"))

    total = (await session.execute(count_q)).scalar() or 0
    rows = (await session.execute(query.order_by(SopCatalog.category, SopCatalog.file_name).offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return paginated_response(
        data=[SopCatalogResponse.model_validate(r).model_dump(mode="json") for r in rows],
        page=page, page_size=page_size, total=total,
    )


@router.get("/sop-catalog/departments", summary="SOP目录部门列表")
async def list_sop_catalog_departments(
    session: AsyncSession = Depends(get_db),
):
    """返回 SOP 目录中所有不重复的部门名称。"""
    from app.modules.hr.models import SopCatalog

    result = await session.execute(
        select(SopCatalog.department)
        .where(SopCatalog.is_deleted == False, SopCatalog.department.isnot(None))
        .distinct()
        .order_by(SopCatalog.department)
    )
    departments = [row[0] for row in result.all()]
    return success_response(data=departments)


@router.get("/sop-catalog/categories", summary="SOP目录分类列表")
async def list_sop_catalog_categories(
    department: str | None = Query(None, description="按部门筛选"),
    session: AsyncSession = Depends(get_db),
):
    """返回 SOP 目录中所有不重复的分类名称，可按部门筛选。"""
    from app.modules.hr.models import SopCatalog

    stmt = (
        select(SopCatalog.category)
        .where(SopCatalog.is_deleted == False, SopCatalog.category.isnot(None))
        .distinct()
        .order_by(SopCatalog.category)
    )
    if department:
        stmt = stmt.where(SopCatalog.department == department)
    result = await session.execute(stmt)
    categories = [row[0] for row in result.all()]
    return success_response(data=categories)


@router.post("/training-evaluations/upsert", summary="同步评估补录的记录（培训内容+部门+应到人数）")
async def upsert_training_evaluation(
    training_content: str = Form(...),
    department: str = Form(...),
    expected_count: int = Form(0),
    training_method: str = Form(""),
    trainer_name: str = Form(""),
    assessment_method: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    """从培训通知面板同步：按培训内容+部门 upsert。"""
    from app.modules.hr.models import TrainingLedger
    existing = (await session.execute(
        text("SELECT id FROM hr.training_evaluations WHERE training_content = :c AND department = :d AND is_deleted = false"),
        {"c": training_content, "d": department}
    )).fetchone()
    if existing:
        await session.execute(
            text("UPDATE hr.training_evaluations SET expected_count = :n, training_method = :tm, trainer_name = :tn, assessment_method = :am, updated_at = now() WHERE id = :id"),
            {"n": expected_count, "id": existing[0], "tm": training_method, "tn": trainer_name, "am": assessment_method}
        )
        msg = "updated"
    else:
        await session.execute(
            text("INSERT INTO hr.training_evaluations (id, training_content, department, expected_count, training_method, trainer_name, assessment_method) VALUES (gen_random_uuid(), :c, :d, :n, :tm, :tn, :am)"),
            {"c": training_content, "d": department, "n": expected_count, "tm": training_method, "tn": trainer_name, "am": assessment_method}
        )
        msg = "created"
    await session.commit()
    return success_response(data={"status": msg}, message="同步成功")



@router.get("/job-requirements", summary="岗位需求列表")
async def list_job_reqs(session: AsyncSession = Depends(get_db)):
    r = await session.execute(text("SELECT id, position_name, department, headcount, hired_count, requirements, status FROM hr.job_requirements WHERE is_deleted = false ORDER BY created_at DESC"))
    return success_response(data=[{"id":str(row[0]),"position_name":row[1],"department":row[2],"headcount":row[3],"hired_count":row[4],"requirements":row[5],"status":row[6]} for row in r])


@router.post("/job-requirements", summary="创建岗位需求")
async def create_job_req(payload: dict, session: AsyncSession = Depends(get_db)):
    await session.execute(text("INSERT INTO hr.job_requirements (id, position_name, department, headcount, requirements, status, created_at, updated_at) VALUES (gen_random_uuid(), :pn, :dept, :hc, :req, '招聘中', now(), now())"), {"pn":payload.get("position_name",""), "dept":payload.get("department",""), "hc":int(payload.get("headcount",1)), "req":payload.get("requirements","")})
    await session.commit()
    return success_response(message="创建成功", status_code=201)


@router.put("/job-requirements/{req_id}", summary="更新岗位需求")
async def update_job_req(req_id: UUID, payload: dict, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.job_requirements SET position_name=COALESCE(:pn,position_name), department=COALESCE(:dept,department), headcount=COALESCE(:hc,headcount), requirements=COALESCE(:req,requirements), status=COALESCE(:st,status) WHERE id=:id AND is_deleted=false"), {"pn":payload.get("position_name"),"dept":payload.get("department"),"hc":payload.get("headcount"),"req":payload.get("requirements"),"st":payload.get("status"),"id":req_id})
    await session.commit()
    return success_response(message="已更新")


@router.delete("/job-requirements/{req_id}", summary="删除岗位需求")
async def delete_job_req(req_id: UUID, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.job_requirements SET is_deleted=true WHERE id=:id"), {"id":req_id})
    await session.commit()
    return success_response(message="已删除")


@router.post("/candidates/parse-resume", summary="解析简历")
async def parse_cv(file: UploadFile = Form(..., alias="resume")):
    if not file.filename or not file.filename.endswith(".pdf"): raise HTTPException(400, "仅支持PDF")
    from app.modules.hr.resume_parser import parse_resume_pdf
    import os; os.makedirs("uploads/resumes", exist_ok=True)
    content=bytes(await file.read()); path=f"uploads/resumes/{file.filename}"
    open(path,"wb").write(content); r=parse_resume_pdf(content); r["resume_file_path"]=path
    return success_response(data=r)


@router.get("/candidates/{cid}/resume-preview", summary="简历预览")
async def resume_preview(cid: UUID, session: AsyncSession = Depends(get_db)):
    r = await session.execute(text("SELECT resume_url FROM hr.candidates WHERE id=:id"), {"id": cid})
    row = r.first()
    if not row or not row[0]: raise HTTPException(404, "无简历文件")
    import os
    if not os.path.exists(row[0]): raise HTTPException(404, "简历文件不存在")
    return FileResponse(row[0], media_type="application/pdf")


@router.get("/candidates", summary="候选人列表")
async def list_candidates(page_params: PageParams = Depends(), session: AsyncSession = Depends(get_db)):
    r=await session.execute(text("SELECT id,name,phone,email,position,department,gender,school,education,major,status,recommendation_level,job_requirement_id FROM hr.candidates WHERE is_deleted=false ORDER BY created_at DESC LIMIT :lim OFFSET :off"),{"lim":page_params.page_size,"off":(page_params.page-1)*page_params.page_size})
    return success_response(data=[{"id":str(row[0]),"name":row[1],"phone":row[2],"email":row[3],"position":row[4],"department":row[5],"gender":row[6],"school":row[7],"education":row[8],"major":row[9],"status":row[10],"recommendation_level":row[11],"job_requirement_id":str(row[12]) if row[12] else None} for row in r])


@router.post("/candidates", summary="创建候选人")
async def create_candidate(payload: dict, session: AsyncSession = Depends(get_db)):
    import os,shutil; rp=None
    if payload.get("resume_file_path") and os.path.exists(payload["resume_file_path"]):
        os.makedirs("uploads/resumes",exist_ok=True); rp=f"uploads/resumes/{payload.get('name','candidate')}_{os.path.basename(payload['resume_file_path'])}"
        shutil.copy(payload["resume_file_path"],rp)
    await session.execute(text("INSERT INTO hr.candidates (id,name,phone,email,position,department,gender,school,education,major,status,recommendation_level,job_requirement_id,resume_url,created_at,updated_at) VALUES (gen_random_uuid(),:n,:ph,:em,:pos,:dept,:g,:sch,:edu,:maj,:st,:rl,:jid,:rp,now(),now())"),{"n":payload.get("name",""),"ph":payload.get("phone",""),"em":payload.get("email",""),"pos":payload.get("position",""),"dept":payload.get("department",""),"g":payload.get("gender",""),"sch":payload.get("school",""),"edu":payload.get("education",""),"maj":payload.get("major",""),"st":payload.get("status","待筛选"),"rl":payload.get("recommendation_level",""),"jid":payload.get("job_requirement_id"),"rp":rp})
    await session.commit(); return success_response(message="创建成功", status_code=201)


@router.get("/candidates/{cid}", summary="候选人详情")
async def get_candidate(cid: UUID, session: AsyncSession = Depends(get_db)):
    r=await session.execute(text("SELECT id,name,phone,email,position,department,gender,school,education,major,status,recommendation_level,job_requirement_id FROM hr.candidates WHERE id=:id AND is_deleted=false"),{"id":cid})
    row=r.first()
    if not row: raise HTTPException(404,"不存在")
    return success_response(data={"id":str(row[0]),"name":row[1],"phone":row[2],"email":row[3],"position":row[4],"department":row[5],"gender":row[6],"school":row[7],"education":row[8],"major":row[9],"status":row[10],"recommendation_level":row[11],"job_requirement_id":str(row[12]) if row[12] else None})


@router.put("/candidates/{cid}", summary="更新候选人")
async def update_candidate(cid: UUID, payload: dict, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.candidates SET name=COALESCE(:n,name),phone=COALESCE(:ph,phone),email=COALESCE(:em,email),position=COALESCE(:pos,position),department=COALESCE(:dept,department),gender=COALESCE(:g,gender),school=COALESCE(:sch,school),education=COALESCE(:edu,education),major=COALESCE(:maj,major),status=COALESCE(:st,status),recommendation_level=COALESCE(:rl,recommendation_level) WHERE id=:id AND is_deleted=false"),{"n":payload.get("name"),"ph":payload.get("phone"),"em":payload.get("email"),"pos":payload.get("position"),"dept":payload.get("department"),"g":payload.get("gender"),"sch":payload.get("school"),"edu":payload.get("education"),"maj":payload.get("major"),"st":payload.get("status"),"rl":payload.get("recommendation_level"),"id":cid})
    await session.commit(); return success_response(message="已更新")


@router.delete("/candidates/{cid}", summary="删除候选人")
async def delete_candidate(cid: UUID, session: AsyncSession = Depends(get_db)):
    await session.execute(text("UPDATE hr.candidates SET is_deleted=true WHERE id=:id"),{"id":cid})


# ─── Exam Papers Routes ───

class SaveExamPaperRequest(BaseModel):
    subject: str
    department: str | None = None
    training_date: str | None = None
    training_method: str | None = None
    questions: dict | None = None
    full_score: int = 100
    pass_line: int = 80
    choice_count: int = 0
    true_false_count: int = 0
    multi_choice_count: int = 0
    fill_blank_count: int = 0


@router.post("/exam-papers", summary="保存试卷")
async def save_exam_paper(
    payload: SaveExamPaperRequest,
    session: AsyncSession = Depends(get_db),
):
    """保存 AI 生成或手工组卷的笔试试卷，供后续复用下载。"""
    from app.modules.hr.models import ExamPaper
    paper = ExamPaper(
        subject=payload.subject,
        department=payload.department,
        training_date=date.fromisoformat(payload.training_date) if payload.training_date else None,
        training_method=payload.training_method,
        questions=payload.questions,
        full_score=payload.full_score,
        pass_line=payload.pass_line,
        choice_count=payload.choice_count,
        true_false_count=payload.true_false_count,
        multi_choice_count=payload.multi_choice_count,
        fill_blank_count=payload.fill_blank_count,
    )
    session.add(paper)
    await session.commit()
    return success_response(data={"id": str(paper.id)}, message="试卷已保存", status_code=201)


@router.get("/exam-papers", summary="试卷列表")
async def list_exam_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    """列出已保存的笔试试卷。"""
    from app.modules.hr.models import ExamPaper
    q = select(ExamPaper).where(ExamPaper.is_deleted == False).order_by(ExamPaper.created_at.desc())
    total_q = select(func.count()).select_from(ExamPaper).where(ExamPaper.is_deleted == False)
    total = (await session.execute(total_q)).scalar() or 0
    papers = (await session.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    data = [{
        "id": str(p.id),
        "subject": p.subject,
        "department": p.department,
        "training_date": str(p.training_date) if p.training_date else None,
        "training_method": p.training_method,
        "full_score": p.full_score,
        "pass_line": p.pass_line,
        "choice_count": p.choice_count,
        "true_false_count": p.true_false_count,
        "multi_choice_count": p.multi_choice_count,
        "fill_blank_count": p.fill_blank_count,
        "source": p.source,
        "created_at": str(p.created_at) if p.created_at else None,
    } for p in papers]
    return paginated_response(data=data, page=page, page_size=page_size, total=total)


@router.get("/exam-papers/{paper_id}/download", summary="下载试卷")
async def download_exam_paper(
    paper_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """根据已保存试卷的题目快照重新生成 Word 文档下载。"""
    from app.modules.hr.models import ExamPaper
    from app.modules.hr.exam_paper_generator import generate_exam_paper

    q = select(ExamPaper).where(ExamPaper.id == paper_id, ExamPaper.is_deleted == False)
    r = await session.execute(q)
    paper = r.scalar_one_or_none()
    if not paper:
        raise HTTPException(404, "试卷不存在")

    buffer = generate_exam_paper(paper)
    filename = f"笔试试卷_{paper.subject}.docx"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )
    await session.commit(); return success_response(message="已删除")
