"""系统设置接口"""

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access

router = APIRouter(tags=["HR-系统设置"])


@router.get("/system-settings", summary="读取系统设置")
async def get_settings(session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    from app.modules.hr.models import SystemSetting
    r = await session.execute(select(SystemSetting).where(SystemSetting.is_deleted == False))
    result = {}
    for s in r.scalars().all():
        result[s.key] = s.value
    return success_response(data=result)


@router.put("/system-settings", summary="保存系统设置")
async def save_settings(settings: dict[str, str], session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    from app.modules.hr.models import SystemSetting
    for key, value in settings.items():
        r = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = r.scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value))
    await session.commit()
    import asyncio, json as _json
    auth_url = None; device_code = None
    new_mail = settings.get("mail_sender", "")
    if new_mail:
        try:
            proc = await asyncio.create_subprocess_exec(
                "lark-cli", "auth", "login", "--domain", "mail", "--no-wait", "--json",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0 and stdout:
                try:
                    d = _json.loads(stdout.decode())
                    auth_url = d.get("verification_url"); device_code = d.get("device_code")
                except Exception: pass
        except (FileNotFoundError, TimeoutError):
            pass  # lark-cli 未安装或超时
    return success_response(data={"auth_url": auth_url, "device_code": device_code}, message="已保存" + (" — 请扫码授权新邮箱" if auth_url else ""))


@router.post("/system-settings/complete-auth", summary="完成邮箱授权")
async def complete_mail_auth(device_code: str = Form(...), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "auth", "login", "--device-code", device_code,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except FileNotFoundError:
        raise HTTPException(400, "lark-cli 未安装，请联系管理员在服务器上安装 lark-cli")
    except TimeoutError:
        raise HTTPException(400, "授权超时，请重试")
    if proc.returncode != 0:
        raise HTTPException(400, stderr.decode().strip() if stderr else "授权失败")
    return success_response(message="授权完成")


# ─── 数据管理 ───

# 排除这些表：岗位相关 + 邮箱相关（发件配置、邮件日志）+ alembic 版本表
_SKIP_TABLES = {"positions", "position_trainings", "system_settings", "email_logs", "alembic_version"}

# 表名 → 中文标签
_TABLE_LABELS = {
    "departments": "部门",
    "teams": "班组",
    "employees": "员工",
    "offboarding_records": "离职记录",
    "departure_records": "离厂记录",
    "training_ledgers": "培训台账",
    "training_ledger_pages": "培训台账页",
    "onboarding_records": "入职记录",
    "annual_training_plans": "年度培训计划",
    "annual_training_plan_items": "培训计划明细",
    "trainers": "讲师",
    "dept_training_personnel": "部门培训人员",
    "sop_catalog": "SOP 目录",
    "exam_papers": "试卷",
    "system_settings": "系统设置",
    "email_logs": "邮件日志",
    "transfer_records": "调动记录",
    "job_requirements": "招聘需求",
    "candidates": "候选人",
    "candidate_status_logs": "候选人状态日志",
    "interviews": "面试记录",
    "candidate_ai_evaluations": "候选人 AI 评估",
    "candidate_reviews": "候选人评审",
    "offboarding_applications": "离职申请",
    "onboarding_applications": "入职申请",
    "offer_tokens": "Offer 令牌",
    "probation_extensions": "试用期延期",
    "qa_assessments": "QA 考核",
    "qa_assessment_scores": "QA 考核成绩",
    "question_bank": "题库",
    "training_assessments": "培训考核",
    "training_assessment_scores": "培训考核成绩",
    "training_evaluations": "培训评估",
}


@router.get("/data-management/tables", summary="可管理的数据表及行数")
async def list_data_tables(session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    """自动扫描 hr schema 下所有表及行数（排除岗位相关表）。"""
    from sqlalchemy import text
    r = await session.execute(
        text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'hr' AND tablename != ALL(:skip)"),
        {"skip": list(_SKIP_TABLES)},
    )
    tables = [row[0] for row in r.all()]
    result = []
    for t in tables:
        cnt = (await session.execute(text(f"SELECT COUNT(*) FROM hr.{t}"))).scalar() or 0
        result.append({"table": t, "label": _TABLE_LABELS.get(t, t), "count": cnt})
    result.sort(key=lambda x: x["label"])
    return success_response(data=result)


@router.post("/data-management/clear", summary="清除指定表数据")
async def clear_data_tables(tables: list[str], session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    """清空指定 HR 数据表（自动排除岗位相关表）。"""
    from sqlalchemy import text
    r = await session.execute(
            text(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'hr'"
    ))
    allowed = {row[0] for row in r.all()} - _SKIP_TABLES
    cleared = []
    for table in tables:
        if table not in allowed:
            raise HTTPException(400, f"不允许操作表: {table}")
        await session.execute(text(f"DELETE FROM hr.{table}"))
        cleared.append(table)
    await session.commit()
    return success_response(data={"cleared": cleared}, message=f"已清空 {len(cleared)} 张表")
