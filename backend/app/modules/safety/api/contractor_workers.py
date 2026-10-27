"""Safety API — contractor_workers endpoints（3.x 平台关联 F1）。

承包商在册人员副台账：GET /safety/contractor-workers 返回三态信封
（live/degraded/empty）+ 5 项统计 + 全量人员行（客户端分页）。
岗位字典：GET /safety/contractor-workers/org-posts（全员主档去重，
个人明细不返回）。数据权威在 3.x 平台，dazah 只读不镜像；进程内
TTL 缓存（人员 10min / 岗位日级）与 Agent 工具共用单例。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.schemas.contractor_workers import (
    ContractorWorkersOut,
    OrgPostsOut,
)
from app.modules.safety.service import org_post_families
from app.modules.safety.service.contractor_workers import open_service
from app.modules.safety.service.org_directory import open_org_posts_service
from app.shared.schemas import ApiResponse

logger = logging.getLogger(__name__)

contractor_workers_router = APIRouter()


@contractor_workers_router.get(
    "/contractor-workers",
    response_model=ApiResponse,
    summary="承包商在册人员副台账（3.x 平台台账+三组交叉，三态信封）",
)
async def get_contractor_workers() -> ApiResponse:
    """S14 相关方管理域页副台账数据包（随域页并行一次拉回）。

    三组交叉（纯规则）：X1 保险覆盖（预报备审批表）、X2 特种持证
    （cert special_op 姓名 match）、X3 超龄（≥60 红/≥55 黄）。
    """
    payload = await open_service().get_payload()
    return ApiResponse(
        data=ContractorWorkersOut(**payload).model_dump(mode="json"),
        meta={"source": "tiji-platform", "mode": "direct"},
    )


@contractor_workers_router.get(
    "/contractor-workers/org-posts",
    response_model=ApiResponse,
    summary="全厂岗位字典（3.x 平台全员主档去重，三态信封；#4 挂族聚合）",
)
async def get_org_posts(
    dept: str | None = Query(None, description="部门名包含匹配"),
    keyword: str | None = Query(None, description="岗位名包含匹配"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """岗位字典：postName 分组 × deptName 聚合 + 人数；个人明细不返回。

    #4：live 时聚合维度=岗位族×人数（全厂口径聚合，不受 dept/keyword 过滤
    影响；无归类行时 families=null 不阻塞字典）。
    """
    payload = await open_org_posts_service().get_payload(dept=dept, keyword=keyword)
    if payload["status"] == "live":
        family_map = await org_post_families.family_map_for_posts(db)
        all_posts = (
            open_org_posts_service().cached_all_posts() or payload["posts"]
        )
        if family_map:
            payload["families"] = org_post_families.build_family_aggregation(
                all_posts, family_map
            )
    return ApiResponse(
        data=OrgPostsOut(**payload).model_dump(mode="json"),
        meta={"source": "tiji-platform", "mode": "direct"},
    )


# ═════════════════ #4 岗位族归类（AI 归类 + 人工确认/修正） ═════════════════


@contractor_workers_router.post(
    "/contractor-workers/org-posts/classify",
    response_model=ApiResponse,
    summary="岗位族批量归类（手动触发；manual 行不覆盖）",
)
async def classify_org_posts(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await org_post_families.run_classify(db)
    except Exception as exc:  # noqa: BLE001 平台/AI 侧失败统一 502
        logger.exception("岗位族归类失败")
        raise HTTPException(
            status_code=502, detail=f"归类失败: {str(exc)[:200]}"
        ) from exc
    top = "、".join(f"{k}{v}" for k, v in data["by_family"].items())
    return ApiResponse(
        data=data,
        message=(
            f"归类完成：字典 {data['posts_total']} 岗，AI 归类 {data['classified']}"
            f"（新插 {data['inserted']}/覆盖 {data['updated']}），manual 保留"
            f" {data['manual_kept']} 岗；分布 {top or '—'}"
        ),
    )


@contractor_workers_router.get(
    "/contractor-workers/org-posts/families",
    response_model=ApiResponse,
    summary="岗位族归类清单（source=ai 为待确认工作集）",
)
async def list_post_families(
    source: str | None = Query(None, description="来源筛选：ai/manual（缺省全部）"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    items = await org_post_families.list_families(db, source=source)
    return ApiResponse(data={"items": items, "total": len(items)})


@contractor_workers_router.post(
    "/contractor-workers/org-posts/families/{row_id}/confirm",
    response_model=ApiResponse,
    summary="按 AI 归类确认（ai→manual，重跑不再覆盖）",
)
async def confirm_post_family(
    row_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await org_post_families.confirm_family(db, row_id)
    except org_post_families.FamilyStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data, message=f"已确认：{data['post_name']} → {data['family']}")


class FamilyUpdateRequest(BaseModel):
    family: str = Field(..., min_length=1, description="目标岗位族（九族枚举之一）")
    note: str | None = Field(None, max_length=512, description="修正备注（可选）")


@contractor_workers_router.patch(
    "/contractor-workers/org-posts/families/{row_id}",
    response_model=ApiResponse,
    summary="人工修正岗位族（改后置 manual，重跑不覆盖）",
)
async def update_post_family(
    row_id: str,
    body: FamilyUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await org_post_families.update_family(
            db, row_id, family=body.family, note=body.note
        )
    except org_post_families.FamilyStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data, message=f"已修正：{data['post_name']} → {data['family']}（manual）")
