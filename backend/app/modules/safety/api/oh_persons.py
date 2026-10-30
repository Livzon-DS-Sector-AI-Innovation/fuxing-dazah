"""Safety API — oh_persons endpoints（职业健康人员汇总台账）。

对齐 backend-design.md §6.2：列表/详情（含体检历史+随访）/体检链/统计/手动总表回填。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    OhAiConclusion,
    OhFollowupResponse,
    OhHealthExamResponse,
    OhPersonDetail,
    OhPersonProfile,
    OhPersonResponse,
    OhPersonStats,
    OhPlatformIdentity,
    OhProfileApplicationOut,
    OhProfileViolationOut,
    OhTrainingAttendeeOut,
)
from app.modules.safety.service import OhPersonService, OhProfileService

oh_persons_router = APIRouter()


@oh_persons_router.get(
    "/oh/persons", response_model=ApiResponse, summary="获取人员汇总台账列表"
)
async def get_oh_persons(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    department: str | None = Query(None, description="部门"),
    position: str | None = Query(None, description="岗位"),
    hazard_exposure: str | None = Query(None, description="是否接害: yes"),
    last_exam_conclusion: OhAiConclusion | None = Query(None, description="最后体检结论"),
    keyword: str | None = Query(None, description="关键词（姓名/身份证/工号/部门/电话）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """人员台账列表（筛选 + keyword + 分页）"""
    service = OhPersonService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_persons(
        skip=skip,
        limit=page_size,
        department=department,
        position=position,
        hazard_exposure=hazard_exposure,
        last_exam_conclusion=last_exam_conclusion.value if last_exam_conclusion else None,
        keyword=keyword,
    )
    return ApiResponse(
        data=[OhPersonResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_persons_router.get(
    "/oh/persons/stats", response_model=ApiResponse, summary="人员台账统计"
)
async def get_oh_person_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """台账统计（按部门/岗位/在岗状态/最后体检结论/接害分布）"""
    service = OhPersonService(db)
    stats = await service.get_stats()
    return ApiResponse(data=OhPersonStats(**stats))


@oh_persons_router.get(
    "/oh/persons/{person_id}", response_model=ApiResponse, summary="人员台账详情"
)
async def get_oh_person(
    person_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """人员详情（含体检历史 + 异常随访 + 接触危害）"""
    service = OhPersonService(db)
    person = await service.get_person(person_id)
    if not person:
        return ApiResponse(code=404, message="人员记录不存在")
    exams = await service.get_exams_by_person(person_id)
    followups = await service.get_followups_by_person(person_id)
    detail = OhPersonDetail.model_validate(person)
    detail.exams = [OhHealthExamResponse.model_validate(e) for e in exams]
    detail.followups = [OhFollowupResponse.model_validate(f) for f in followups]
    return ApiResponse(data=detail)


@oh_persons_router.get(
    "/oh/persons/{person_id}/profile", response_model=ApiResponse, summary="个人完整档案（六源聚合）"
)
async def get_oh_person_profile(
    person_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """个人完整档案：基本信息 + 体检史 + 异常随访 + 转岗离岗申请 + 培训参训 + 违章 + 3.x 平台身份。

    person_id 支持 UUID 与 Bitable record_id（直读行防呆）；违章源（Bitable
    直读）失败降级为 None 不阻塞其余区块，见 errors/match_notes；平台身份卡
    （第 6 源）自带三态信封（platform.status），不匹配/降级不阻塞其余区块。
    """
    service = OhProfileService(db)
    profile = await service.build_profile(person_id)
    if profile is None:
        return ApiResponse(code=404, message="人员记录不存在")
    raw_violations = profile["violations"]
    data = OhPersonProfile(
        person=OhPersonResponse.model_validate(profile["person"]),
        exams=[OhHealthExamResponse.model_validate(e) for e in profile["exams"]],
        followups=[OhFollowupResponse.model_validate(f) for f in profile["followups"]],
        applications=[
            OhProfileApplicationOut.model_validate(a) for a in profile["applications"]
        ],
        trainings=[
            OhTrainingAttendeeOut.model_validate(t) for t in profile["trainings"]
        ],
        violations=(
            [OhProfileViolationOut(**v) for v in raw_violations]
            if raw_violations is not None
            else None
        ),
        platform=(
            OhPlatformIdentity.model_validate(profile["platform"])
            if profile.get("platform") is not None
            else None
        ),
        match_notes=profile["match_notes"],
        errors=profile["errors"],
    )
    return ApiResponse(data=data)


@oh_persons_router.get(
    "/oh/persons/{person_id}/exams", response_model=ApiResponse, summary="该人员的体检记录链"
)
async def get_oh_person_exams(
    person_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """该人员的体检记录链"""
    service = OhPersonService(db)
    person = await service.get_person(person_id)
    if not person:
        return ApiResponse(code=404, message="人员记录不存在")
    exams = await service.get_exams_by_person(person_id)
    return ApiResponse(data=[OhHealthExamResponse.model_validate(e) for e in exams])


@oh_persons_router.post(
    "/oh/persons/{person_id}/sync", response_model=ApiResponse, summary="手动触发总表回填"
)
async def sync_oh_person(
    person_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发总表回填（取最近一次体检 → last_exam_* + exam_record_ids + Bitable 回写）"""
    service = OhPersonService(db)
    person = await service.manual_sync(person_id)
    if not person:
        return ApiResponse(code=404, message="人员记录不存在")
    return ApiResponse(data=OhPersonResponse.model_validate(person))
