"""职称评审 HTTP 路由（v2）。"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.title_review.schemas import (
    TitleReviewActivityCreate,
    TitleReviewActivityListOut,
    TitleReviewActivityOut,
    TitleReviewActivityUpdate,
    TitleReviewApplicationOut,
    TitleReviewDeptCommitteeIn,
    TitleReviewDeptCommitteeOut,
    TitleReviewDimensionOut,
    TitleReviewJudgeAssignIn,
    TitleReviewJudgeOut,
    TitleReviewJudgeVoteIn,
    TitleReviewLevelOut,
)
from app.modules.hr.title_review.service import TitleReviewService
from app.shared.schemas import PageParams

router = APIRouter(tags=["HR-职称评审"])


def get_service(session: AsyncSession = Depends(get_db)) -> TitleReviewService:
    return TitleReviewService(session)


def _apply_scope(service: TitleReviewService, ctx: HrAccessContext) -> None:
    """把数据范围注入服务：受限用户仅能访问授权部门（或本人）的申报数据。

    self_only 且身份无工号时 fail-closed：无法定位本人即拒绝，而不是放开全部。
    """
    if ctx.is_unrestricted:
        service.set_scope(None, None)
    elif ctx.data_scope == "self_only":
        if not ctx.employee_number:
            raise HTTPException(403, "数据范围限制：无法定位本人对应的员工档案，请联系管理员")
        service.set_scope(None, ctx.employee_number)
    else:
        service.set_scope(set(ctx.scoped_departments), None)


# ─── 活动 CRUD ───


@router.post("/title/activities", summary="创建评定活动（含职级组默认模板）")
async def create_activity(
    data: TitleReviewActivityCreate,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.create_activity(data, user=ctx.user)
    return success_response(
        data=TitleReviewActivityOut.model_validate(activity).model_dump(mode="json"),
        message="活动创建成功",
    )


@router.get("/title/activities", summary="评定活动列表（含进度）")
async def list_activities(
    status: str | None = Query(None, description="按状态筛选"),
    keyword: str | None = Query(None, description="按活动名称搜索"),
    page_params: PageParams = Depends(),
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activities, total, app_counts, voted_counts, judge_counts = (
        await service.list_activities_with_progress(
            status=status, keyword=keyword, page=page_params.page, page_size=page_params.page_size
        )
    )
    out = []
    for a in activities:
        item = TitleReviewActivityListOut.model_validate(a)
        item.application_count = app_counts.get(a.id, 0)
        item.total_judge_count = judge_counts.get(a.id, 0)
        item.voted_judge_count = voted_counts.get(a.id, 0)
        out.append(item.model_dump(mode="json"))
    return paginated_response(
        data=out,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.get("/title/activities/{activity_id}", summary="评定活动详情（含职级组）")
async def get_activity(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.get_activity(activity_id)
    levels = await service.get_levels(activity_id)
    dims = await service.get_dimensions(activity_id)
    out = TitleReviewActivityOut.model_validate(activity)
    out.levels = [TitleReviewLevelOut.model_validate(lv) for lv in levels]
    return success_response(
        data={
            **out.model_dump(mode="json"),
            "dimensions": [
                TitleReviewDimensionOut.model_validate(d).model_dump(mode="json") for d in dims
            ],
        }
    )


@router.put("/title/activities/{activity_id}", summary="更新评定活动")
async def update_activity(
    activity_id: UUID,
    data: TitleReviewActivityUpdate,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.update_activity(activity_id, data, user=ctx.user)
    return success_response(
        data=TitleReviewActivityOut.model_validate(activity).model_dump(mode="json"),
        message="活动更新成功",
    )


@router.delete("/title/activities/{activity_id}", summary="删除评定活动（仅 draft）")
async def delete_activity(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    await service.delete_activity(activity_id, user=ctx.user)
    return success_response(message="活动已删除")


@router.post("/title/activities/{activity_id}/bind-tables", summary="校验并订阅飞书表格")
async def bind_tables(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.bind_tables(activity_id, user=ctx.user)
    return success_response(
        data=TitleReviewActivityOut.model_validate(activity).model_dump(mode="json"),
        message="飞书表格绑定成功",
    )


# ─── 状态流转 ───


@router.post("/title/activities/{activity_id}/open", summary="开启申报（draft→open）")
async def open_activity(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.open_activity(activity_id, user=ctx.user)
    return success_response(
        data=TitleReviewActivityOut.model_validate(activity).model_dump(mode="json"),
        message="已开启申报",
    )


@router.post("/title/activities/{activity_id}/review", summary="开启评审（open→reviewing）")
async def start_review(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.start_review(activity_id, user=ctx.user)
    return success_response(
        data=TitleReviewActivityOut.model_validate(activity).model_dump(mode="json"),
        message="已开启评审",
    )


@router.post("/title/activities/{activity_id}/close", summary="结束活动（→closed）")
async def close_activity(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    activity = await service.close_activity(activity_id, user=ctx.user)
    return success_response(
        data=TitleReviewActivityOut.model_validate(activity).model_dump(mode="json"),
        message="活动已结束",
    )


@router.post("/title/activities/{activity_id}/reconcile", summary="手动对账（立即同步飞书表格）")
async def reconcile_activity(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    stats = await service.reconcile_activity(activity_id)
    return success_response(data=stats, message="对账完成")


# ─── 部门评审组 ───


@router.get("/title/departments", summary="部门列表（员工档案去重，评审组配置用）")
async def list_departments(
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    departments = await service.list_departments()
    return success_response(data=departments)


# ─── 部门评审组 ───


@router.get("/title/committees", summary="部门评审组列表")
async def list_committees(
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    committees = await service.list_committees()
    return success_response(
        data=[
            TitleReviewDeptCommitteeOut.model_validate(c).model_dump(mode="json")
            for c in committees
        ]
    )


@router.post("/title/committees", summary="新增/更新部门评审组（按部门幂等）")
async def upsert_committee(
    data: TitleReviewDeptCommitteeIn,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    committee = await service.upsert_committee(data, user=ctx.user)
    return success_response(
        data=TitleReviewDeptCommitteeOut.model_validate(committee).model_dump(mode="json"),
        message="部门评审组已保存",
    )


@router.delete("/title/committees/{committee_id}", summary="删除部门评审组")
async def delete_committee(
    committee_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    await service.delete_committee(committee_id, user=ctx.user)
    return success_response(message="已删除")


# ─── 申报管理 ───


@router.get("/title/activities/{activity_id}/applications", summary="活动申报列表")
async def list_applications(
    activity_id: UUID,
    status: str | None = Query(None, description="按流程状态筛选"),
    keyword: str | None = Query(None, description="按姓名/工号搜索"),
    page_params: PageParams = Depends(),
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    rows, total = await service.list_applications(
        activity_id, status=status, keyword=keyword, page=page_params.page, page_size=page_params.page_size
    )
    return paginated_response(
        data=[
            TitleReviewApplicationOut.model_validate(r).model_dump(mode="json")
            for r in rows
        ],
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )


@router.get("/title/applications/{application_id}", summary="申报详情（含评委，不含投票明细）")
async def get_application(
    application_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    application, judges = await service.get_application_detail(application_id)
    out = TitleReviewApplicationOut.model_validate(application).model_dump(mode="json")
    out["judges"] = [
        TitleReviewJudgeOut.model_validate(j).model_dump(mode="json") for j in judges
    ]
    return success_response(data=out)


@router.post("/title/applications/{application_id}/finalize", summary="按当前票数判定（可提前判定）")
async def finalize_votes(
    application_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    application = await service.finalize_by_votes(application_id, user=ctx.user, force=True)
    return success_response(
        data=TitleReviewApplicationOut.model_validate(application).model_dump(mode="json"),
        message="已按票数判定",
    )


# ─── 评委 ───


@router.get("/title/my-judge-tasks", summary="我的投票任务（评委视角）")
async def my_judge_tasks(
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:judge")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    tasks = await service.list_my_judge_tasks(ctx.employee_number)
    return success_response(data=tasks)


@router.post("/title/judge-tasks/{judge_id}/vote", summary="提交投票（评委）")
async def submit_vote(
    judge_id: UUID,
    data: TitleReviewJudgeVoteIn,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:judge")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    judge = await service.submit_vote(judge_id, ctx.employee_number, data)
    return success_response(
        data=TitleReviewJudgeOut.model_validate(judge).model_dump(mode="json"),
        message="投票提交成功",
    )


@router.get("/title/applications/{application_id}/default-judges", summary="默认评委（部门评定小组）")
async def default_judges(
    application_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    members = await service.default_committee_members(application_id)
    return success_response(data=members)


@router.post("/title/applications/{application_id}/judges", summary="指定/调整评委（含角色）")
async def assign_judges(
    application_id: UUID,
    data: TitleReviewJudgeAssignIn,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:manage")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    judges = await service.assign_judges(application_id, data, user=ctx.user)
    return success_response(
        data=[TitleReviewJudgeOut.model_validate(j).model_dump(mode="json") for j in judges],
        message="评委指定成功",
    )


# ─── 评审结果 ───


@router.get("/title/activities/{activity_id}/results", summary="评审结果（含投票明细，保密）")
async def get_results(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:scores:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    results = await service.get_results(activity_id)
    return success_response(data=results)


@router.get("/title/activities/{activity_id}/summary", summary="评审结果汇总统计")
async def get_summary(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:read")),
    service: TitleReviewService = Depends(get_service),
) -> JSONResponse:
    _apply_scope(service, ctx)
    data = await service.get_summary(activity_id)
    return success_response(data=data)


@router.get("/title/activities/{activity_id}/export", summary="导出评审结果汇总（xlsx）")
async def export_results(
    activity_id: UUID,
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:scores:read")),
    service: TitleReviewService = Depends(get_service),
) -> StreamingResponse:
    """导出三个工作表：汇总统计 / 申报明细 / 评委明细（业务逻辑在 service 层）。"""
    from urllib.parse import quote

    _apply_scope(service, ctx)
    content, filename = await service.export_results_xlsx(activity_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


@router.post("/title/activities/{activity_id}/roster-export", summary="生成最终名单（docx 表格）")
async def export_roster(
    activity_id: UUID,
    payload: dict[str, Any],
    ctx: HrAccessContext = Depends(require_hr_access("hr:title:scores:read")),
    service: TitleReviewService = Depends(get_service),
) -> StreamingResponse:
    """HR 勾选评审合格人员 → 生成表格名单（序号/职务/姓名/职级认定结果）。"""
    from urllib.parse import quote

    _apply_scope(service, ctx)
    try:
        ids = [UUID(str(i)) for i in (payload.get("application_ids") or [])]
    except (TypeError, ValueError):
        raise HTTPException(400, "申报 ID 格式不正确")
    content, filename = await service.generate_roster_docx(activity_id, ids)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )
