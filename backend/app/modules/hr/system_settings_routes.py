"""系统设置接口"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access

router = APIRouter(tags=["HR-系统设置"])


@router.get("/system-settings", summary="读取系统设置")
async def get_settings(session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    from app.modules.hr.models import SystemSetting
    r = await session.execute(
        select(SystemSetting).where(SystemSetting.is_deleted == False)  # noqa: E712
    )
    result = {}
    for s in r.scalars().all():
        result[s.key] = s.value
    return success_response(data=result)


@router.put("/system-settings", summary="保存系统设置")
async def save_settings(settings: dict, session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    from app.modules.hr.models import SystemSetting
    for key, value in settings.items():
        r = await session.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = r.scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            session.add(SystemSetting(key=key, value=str(value)))
    await session.commit()
    return success_response(message="已保存")


# ─── 数据管理 ───

# 排除这些表：岗位相关 + 邮箱相关（发件配置、邮件日志）+ alembic 版本表
_SKIP_TABLES = {"positions", "system_settings", "email_logs", "alembic_version"}

# 表名 → 中文标签
_TABLE_LABELS = {
    "departments": "部门",
    "teams": "班组",
    "employees": "员工",
    "employee_classifications": "员工自定义分类",
    "employee_tags": "员工标签",
    "offboarding_records": "离职记录",
    "departure_records": "离厂记录",
    "training_ledgers": "培训台账",
    "training_ledger_pages": "培训台账页",
    "annual_training_plans": "年度培训计划",
    "annual_training_plan_items": "培训计划明细",
    "onboarding_records": "入职记录",
    "onboarding_tasks": "入职任务",
    "trainers": "讲师",
    "dept_training_personnel": "部门培训人员",
    "sop_catalog": "SOP 目录",
    "sop_training_masters": "SOP 培训统筹",
    "sop_training_entries": "SOP 培训明细",
    "sop_training_records": "SOP 培训记录",
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
    "candidate_analysis_reports": "候选人分析报告",
    "qa_assessments": "QA 考核",
    "qa_assessment_scores": "QA 考核成绩",
    "question_bank": "题库",
    "training_evaluations": "培训评估",
    "monthly_performance_evaluations": "月度绩效评价",
    "performance_categories": "绩效分类",
    "performance_category_scores": "绩效分类评分",
    "performance_dept_weights": "部门绩效权重",
    "performance_evaluation_items": "绩效评价项目",
    "position_trainings": "岗位培训",
    "user_department_access": "用户部门权限",
    "title_review_activities": "职称评审活动",
    "title_review_applications": "职称评审申报",
    "title_review_judges": "职称评审评委",
    "title_review_scores": "职称评审评分",
    "title_review_levels": "职称评审职级组",
    "title_review_dimensions": "职称评审评价项",
    "title_review_dept_committees": "职称评审部门评审组",
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


# ─── 测试数据分类 ───

# 测试数据识别规则：表名 → 附加 WHERE 条件（测试产生的数据按约定特征收纳，
# 新增测试数据类型时在此登记规则；条件为代码内常量，无注入风险）
TEST_DATA_RULES: dict[str, str] = {
    "employees": "name = '员工甲' AND department = '甲部门'",
    "sop_training_entries": "trainer LIKE '%员工甲%' OR personnel LIKE '%员工甲%'",
}


@router.get("/data-management/test-data", summary="测试数据分类汇总")
async def list_test_data(session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    """测试过程中实际产生的数据收纳于此：按约定特征统计各表测试行数。"""
    from sqlalchemy import text
    tables = []
    total = 0
    for table, where in TEST_DATA_RULES.items():
        cnt = (await session.execute(
            text(f"SELECT COUNT(*) FROM hr.{table} WHERE {where} AND is_deleted = false")
        )).scalar() or 0
        total += cnt
        tables.append({"table": table, "label": _TABLE_LABELS.get(table, table), "count": cnt})
    return success_response(data={"total": total, "tables": tables})


@router.post("/data-management/clear-test-data", summary="清空测试数据分类")
async def clear_test_data(session: AsyncSession = Depends(get_db), ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage"))):
    """物理删除测试数据分类收纳的全部行（与数据管理整表清空语义一致）。"""
    from sqlalchemy import text
    cleared = []
    for table, where in TEST_DATA_RULES.items():
        rowcount = (await session.execute(
            text(f"DELETE FROM hr.{table} WHERE {where}")
        )).rowcount or 0
        cleared.append({"table": table, "count": rowcount})
    await session.commit()
    return success_response(
        data={"cleared": cleared},
        message=f"已清空测试数据 {sum(c['count'] for c in cleared)} 条",
    )
