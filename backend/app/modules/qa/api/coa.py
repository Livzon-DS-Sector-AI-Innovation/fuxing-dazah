"""QA COA HTTP API：产品/客户标准配置、docx 导入预览、出具登记、矩阵透视。

挂在 QA 模块路由下（``/api/v1/qa/coa``）。读取放行 COA 专用读码或模块
通配读码 ``qa:*:read``（standard:manage / issue:create 写权限隐含读）。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.qa.schemas.coa import (
    CoaProductCreate,
    CoaProductFieldsReplace,
    CoaProductUpdate,
    CoaReportCreate,
    CoaReportUpdate,
    CoaStandardCreate,
    CoaStandardFieldsReplace,
    CoaStandardItemsReplace,
    CoaStandardUpdate,
)
from app.modules.qa.service import coa as service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()

# 读取放行专用读码 + 模块通配读码；写权限隐含读（能配置/登记的人天然要
# 读得动页面数据），与 apr 口径一致。
_coa_read = require_permission(
    "qa:coa:read", "qa:*:read", "qa:coa:standard:manage", "qa:coa:issue:create"
)
_coa_manage = require_permission("qa:coa:standard:manage")
_coa_issue = require_permission("qa:coa:issue:create")


# ───────────────────────── 产品 ─────────────────────────


@router.get("/coa/products", summary="COA 产品列表")
async def list_products(
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(default=False, description="只看启用产品"),
) -> Any:
    return success_response(
        data=await service.list_products(db, active_only=active_only)
    )


@router.post("/coa/products", summary="新增 COA 产品", status_code=201)
async def create_product(
    payload: CoaProductCreate,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_product(db, payload, user), status_code=201
    )


@router.patch("/coa/products/{product_id}", summary="编辑 COA 产品")
async def update_product(
    payload: CoaProductUpdate,
    product_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_product(db, product_id, payload, user)
    )


@router.get(
    "/coa/products/{product_id}/fields", summary="产品批次信息字段配置列表"
)
async def list_product_fields(
    product_id: uuid.UUID,
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.list_product_fields(db, product_id)
    )


@router.put(
    "/coa/products/{product_id}/fields",
    summary="产品批次信息字段配置全量替换",
)
async def replace_product_fields(
    payload: CoaProductFieldsReplace,
    product_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.replace_product_fields(db, product_id, payload, user)
    )


# ───────────────────────── 客户标准 ─────────────────────────


@router.get("/coa/standards", summary="客户标准列表")
async def list_standards(
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID | None = Query(default=None, description="按产品过滤"),
    active_only: bool = Query(default=False, description="只看启用标准"),
) -> Any:
    return success_response(
        data=await service.list_standards(
            db, product_id=product_id, active_only=active_only
        )
    )


@router.get("/coa/standards/{standard_id}", summary="客户标准详情（含项目）")
async def get_standard(
    standard_id: uuid.UUID,
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.get_standard_detail(db, standard_id))


@router.post("/coa/standards", summary="新建客户标准（含首批项目）", status_code=201)
async def create_standard(
    payload: CoaStandardCreate,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_standard(db, payload, user), status_code=201
    )


@router.patch("/coa/standards/{standard_id}", summary="编辑客户标准头")
async def update_standard(
    payload: CoaStandardUpdate,
    standard_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_standard(db, standard_id, payload, user)
    )


@router.delete("/coa/standards/{standard_id}", summary="删除客户标准")
async def delete_standard(
    standard_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_standard(db, standard_id, user)
    return success_response(data=None)


@router.put(
    "/coa/standards/{standard_id}/fields",
    summary="标准批次信息字段覆盖全量替换（与产品默认解耦）",
)
async def replace_standard_fields(
    payload: CoaStandardFieldsReplace,
    standard_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.replace_standard_fields(db, standard_id, payload, user)
    )


@router.delete(
    "/coa/standards/{standard_id}/fields",
    summary="恢复产品默认批次信息字段（删标准覆盖）",
)
async def restore_standard_fields(
    standard_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.restore_standard_fields(db, standard_id))


@router.put("/coa/standards/{standard_id}/items", summary="标准项目全量替换")
async def replace_items(
    payload: CoaStandardItemsReplace,
    standard_id: uuid.UUID,
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.replace_items(db, standard_id, payload, user)
    )


@router.post(
    "/coa/standards/import-preview",
    summary="docx 导入预览：客户标准草稿（不落库）",
)
async def import_standard_preview(
    user: User = Depends(_coa_manage),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(description="COA docx 报告文件"),
) -> Any:
    data = await file.read()
    return success_response(
        data=await service.import_standard_preview(
            db, data, filename=file.filename or "coa.docx"
        )
    )


# ───────────────────────── 出具登记 ─────────────────────────


@router.get("/coa/reports", summary="出具登记列表（按产品）")
async def list_reports(
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 id"),
) -> Any:
    return success_response(data=await service.list_reports(db, product_id))


@router.get("/coa/reports/matrix", summary="产品维度矩阵（所有 COA × 所有项目）")
async def report_matrix(
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 id"),
    standard_id: list[uuid.UUID] | None = Query(
        default=None, description="按标准筛列（可多个）"
    ),
) -> Any:
    return success_response(
        data=await service.matrix(db, product_id, standard_ids=standard_id)
    )


@router.get("/coa/reports/{report_id}", summary="COA 报告详情（含结果值）")
async def get_report(
    report_id: uuid.UUID,
    user: User = Depends(_coa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.get_report_detail(db, report_id))


@router.post(
    "/coa/reports",
    summary="出具登记（手工/导入统一落库；业务键=产品+模板+批号，batch_data=模板动态批次字段）",
    status_code=201,
)
async def create_report(
    payload: CoaReportCreate,
    user: User = Depends(_coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_report(db, payload, user), status_code=201
    )


@router.patch("/coa/reports/{report_id}", summary="编辑 COA 报告")
async def update_report(
    payload: CoaReportUpdate,
    report_id: uuid.UUID,
    user: User = Depends(_coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_report(db, report_id, payload, user)
    )


@router.delete("/coa/reports/{report_id}", summary="作废 COA 报告")
async def delete_report(
    report_id: uuid.UUID,
    user: User = Depends(_coa_issue),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_report(db, report_id, user)
    return success_response(data=None)


@router.post(
    "/coa/reports/import-preview",
    summary="docx 导入预览：标准匹配 + 项目对齐 + 值预填（不落库）",
)
async def import_report_preview(
    user: User = Depends(_coa_issue),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(description="COA docx 报告文件"),
    standard_id: uuid.UUID | None = Query(
        default=None, description="显式指定标准（缺省按报告编号自动匹配）"
    ),
) -> Any:
    data = await file.read()
    return success_response(
        data=await service.import_report_preview(
            db, data, standard_id=standard_id, filename=file.filename or "coa.docx"
        )
    )
