"""Safety API — contractor_workers endpoints（3.x 平台关联 F1）。

承包商在册人员副台账：GET /safety/contractor-workers 返回三态信封
（live/degraded/empty）+ 5 项统计 + 全量人员行（客户端分页）。
岗位字典：GET /safety/contractor-workers/org-posts（全员主档去重，
个人明细不返回）。数据权威在 3.x 平台，dazah 只读不镜像；进程内
TTL 缓存（人员 10min / 岗位日级）与 Agent 工具共用单例。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.modules.safety.schemas.contractor_workers import (
    ContractorWorkersOut,
    OrgPostsOut,
)
from app.modules.safety.service.contractor_workers import open_service
from app.modules.safety.service.org_directory import open_org_posts_service
from app.shared.schemas import ApiResponse

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
    summary="全厂岗位字典（3.x 平台全员主档去重，三态信封）",
)
async def get_org_posts(
    dept: str | None = Query(None, description="部门名包含匹配"),
    keyword: str | None = Query(None, description="岗位名包含匹配"),
) -> ApiResponse:
    """岗位字典：postName 分组 × deptName 聚合 + 人数；个人明细不返回。"""
    payload = await open_org_posts_service().get_payload(dept=dept, keyword=keyword)
    return ApiResponse(
        data=OrgPostsOut(**payload).model_dump(mode="json"),
        meta={"source": "tiji-platform", "mode": "direct"},
    )
