"""QA 年度产品审核（PQR）HTTP API：产品/模板配置、批次录入、趋势、汇总、锁定。

挂在 QA 模块路由下（``/api/v1/qa/apr``）。读取放行 PQR 专用读码或模块
通配读码 ``qa:*:read``；配置/录入/导出/锁定各自独立权限。
"""

from __future__ import annotations

import io
import uuid
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import paginated_response, success_response
from app.modules.qa.schemas import (
    AprBatchCreate,
    AprBatchUpdate,
    AprBatchValuesIn,
    AprImportResult,
    AprItemCreate,
    AprItemsBulkCreate,
    AprItemUpdate,
    AprProductCreate,
    AprProductUpdate,
    AprSectionCreate,
    AprSectionUpdate,
)
from app.modules.qa.service import apr as service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()

# 读取放行专用读码 + 模块通配读码；enter/manage 写权限隐含读（能录入/
# 配置的人天然要读得动页面数据），否则按码配权的用户会看到菜单却整页 403。
_apr_read = require_permission(
    "qa:apr:read", "qa:*:read", "qa:apr:enter", "qa:apr:manage"
)
_apr_manage = require_permission("qa:apr:manage")
_apr_enter = require_permission("qa:apr:enter")
_apr_export = require_permission("qa:apr:export")
_apr_lock = require_permission("qa:apr:lock")


# ───────────────────────── 产品 ─────────────────────────


@router.get("/apr/products", summary="PQR 产品列表")
async def list_products(
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(default=False, description="只看启用产品"),
) -> Any:
    return success_response(
        data=await service.list_products(db, active_only=active_only)
    )


@router.post("/apr/products", summary="新增 PQR 产品", status_code=201)
async def create_product(
    payload: AprProductCreate,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_product(db, payload, user), status_code=201
    )


@router.patch("/apr/products/{product_id}", summary="编辑 PQR 产品")
async def update_product(
    payload: AprProductUpdate,
    product_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_product(db, product_id, payload, user)
    )


@router.delete("/apr/products/{product_id}", summary="删除 PQR 产品")
async def delete_product(
    product_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_product(db, product_id, user)
    return success_response(data={"id": str(product_id)})


# ───────────────────────── 模板段与列定义 ─────────────────────────


@router.get("/apr/sections", summary="产品模板段（含列定义）")
async def list_sections(
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 ID"),
    with_items: bool = Query(default=True, description="是否携带列定义"),
) -> Any:
    return success_response(
        data=await service.list_sections(db, product_id, with_items=with_items)
    )


@router.post("/apr/sections", summary="新增模板段", status_code=201)
async def create_section(
    payload: AprSectionCreate,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_section(db, payload, user), status_code=201
    )


@router.patch("/apr/sections/{section_id}", summary="编辑模板段")
async def update_section(
    payload: AprSectionUpdate,
    section_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_section(db, section_id, payload, user)
    )


@router.delete("/apr/sections/{section_id}", summary="删除模板段")
async def delete_section(
    section_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_section(db, section_id, user)
    return success_response(data={"id": str(section_id)})


@router.post("/apr/items", summary="新增列定义", status_code=201)
async def create_item(
    payload: AprItemCreate,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_item(db, payload, user), status_code=201
    )


@router.post(
    "/apr/sections/{section_id}/items/bulk",
    summary="批量新增列定义（从 Excel 粘贴）",
    status_code=201,
)
async def bulk_create_items(
    section_id: uuid.UUID,
    payload: AprItemsBulkCreate,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.bulk_create_items(db, section_id, payload, user),
        status_code=201,
    )


@router.patch("/apr/items/{item_id}", summary="编辑列定义")
async def update_item(
    payload: AprItemUpdate,
    item_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.update_item(db, item_id, payload, user))


@router.delete("/apr/items/{item_id}", summary="删除列定义（有值时转停用）")
async def delete_item(
    item_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.delete_item(db, item_id, user))


@router.post(
    "/apr/templates/{product_id}/copy-from/{source_product_id}",
    summary="从已有产品复制模板",
    status_code=201,
)
async def copy_template(
    product_id: uuid.UUID,
    source_product_id: uuid.UUID,
    user: User = Depends(_apr_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.copy_template(db, product_id, source_product_id, user),
        status_code=201,
    )


# ───────────────────────── 批次与值 ─────────────────────────


@router.get("/apr/batches", summary="批次列表（按段+年度过滤）")
async def list_batches(
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
    section_id: uuid.UUID = Query(description="段 ID"),
    year: int | None = Query(default=None, ge=2000, le=2100),
    keyword: str | None = Query(default=None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    items, total = await service.list_batches(
        db,
        section_id=section_id,
        year=year,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.post("/apr/batches", summary="登记批次", status_code=201)
async def create_batch(
    payload: AprBatchCreate,
    user: User = Depends(_apr_enter),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.create_batch(db, payload, user), status_code=201
    )


@router.get("/apr/batches/{batch_id}/values", summary="批次录入数据（表单渲染用）")
async def batch_values(
    batch_id: uuid.UUID,
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(data=await service.batch_values(db, batch_id))


@router.patch("/apr/batches/{batch_id}", summary="编辑批次")
async def update_batch(
    payload: AprBatchUpdate,
    batch_id: uuid.UUID,
    user: User = Depends(_apr_enter),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.update_batch(db, batch_id, payload, user)
    )


@router.delete("/apr/batches/{batch_id}", summary="删除批次（含值级联硬删）")
async def delete_batch(
    batch_id: uuid.UUID,
    user: User = Depends(_apr_enter),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_batch(db, batch_id, user)
    return success_response(data={"id": str(batch_id)})


@router.put("/apr/batches/{batch_id}/values", summary="整批保存录入值（全量替换）")
async def save_batch_values(
    payload: AprBatchValuesIn,
    batch_id: uuid.UUID,
    user: User = Depends(_apr_enter),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.save_batch_values(db, batch_id, payload, user)
    )


@router.get(
    "/apr/sections/{section_id}/import-template", summary="下载录入导入模板（xlsx）"
)
async def import_template(
    section_id: uuid.UUID,
    user: User = Depends(_apr_enter),
    db: AsyncSession = Depends(get_db),
    year: int = Query(ge=2000, le=2100),
) -> StreamingResponse:
    wb, base_name = await service.build_import_template(db, section_id, year)
    buf = io.BytesIO()
    wb.save(buf)
    encoded = quote(f"{base_name}.xlsx")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="apr-import-template.xlsx"; '
                f"filename*=UTF-8''{encoded}"
            )
        },
    )


@router.post("/apr/sections/{section_id}/values/import", summary="Excel 批量导入录入值")
async def import_values(
    section_id: uuid.UUID,
    user: User = Depends(_apr_enter),
    db: AsyncSession = Depends(get_db),
    year: int = Query(ge=2000, le=2100),
    mode: Literal["merge", "replace"] = Query(
        default="merge",
        description="merge=非空覆盖（空白格保留旧值）；replace=整批替换",
    ),
    file: UploadFile = File(description="按模板填写的 xlsx 文件"),
) -> Any:
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext != "xlsx":
        raise AppException(
            status_code=400,
            message="仅支持 .xlsx 文件，请用 Excel 另存为 .xlsx 后重试。",
        )
    content = await file.read()
    if not content:
        raise AppException(status_code=400, message="文件内容为空。")
    from app.core.config import get_settings

    max_size = get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_size:
        raise AppException(
            status_code=400,
            message=f"文件大小超过 {get_settings().MAX_UPLOAD_SIZE_MB}MB 限制。",
        )
    result = await service.import_section_values(
        db, section_id, year=year, mode=mode, file_bytes=content, user=user
    )
    return success_response(data=AprImportResult(**result).model_dump(mode="json"))


# ───────────────────────── 趋势与汇总 ─────────────────────────


@router.get("/apr/trends", summary="列趋势（数值序列+限度参考线+OOS/OOT 标记）")
async def trend(
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
    item_id: uuid.UUID = Query(description="列定义 ID"),
    year: int | None = Query(default=None, ge=2000, le=2100, description="不传则跨年"),
) -> Any:
    return success_response(data=await service.trend(db, item_id, year=year))


@router.get("/apr/summary", summary="年终汇总矩阵（按产品+年度）")
async def summary(
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 ID"),
    year: int = Query(ge=2000, le=2100),
    data_kind: Literal["production", "inspection"] | None = Query(
        default=None, description="生产数据/检验结果"
    ),
    market: str | None = Query(default=None, description="US/EP/Ch.P"),
) -> Any:
    return success_response(
        data=await service.summary(
            db, product_id, year=year, data_kind=data_kind, market=market
        )
    )


@router.get("/apr/summary/export", summary="导出年终汇总 Excel")
async def summary_export(
    user: User = Depends(_apr_export),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 ID"),
    year: int = Query(ge=2000, le=2100),
) -> StreamingResponse:
    data = await service.summary(db, product_id, year=year)
    wb = service.build_export_workbook(data)
    buf = io.BytesIO()
    wb.save(buf)
    product_name = data["product"]["name"]
    encoded = quote(f"{product_name}{year}年度审核汇总.xlsx")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"apr-summary.xlsx\"; filename*=UTF-8''{encoded}"
            )
        },
    )


# ───────────────────────── 年度锁定 ─────────────────────────


@router.get("/apr/annual-reviews", summary="产品年度锁定状态列表")
async def list_annual_reviews(
    user: User = Depends(_apr_read),
    db: AsyncSession = Depends(get_db),
    product_id: uuid.UUID = Query(description="产品 ID"),
) -> Any:
    return success_response(data=await service.list_annual_reviews(db, product_id))


@router.post(
    "/apr/annual-reviews/{product_id}/{year}/lock", summary="锁定年度（年终定稿）"
)
async def lock_year(
    product_id: uuid.UUID,
    year: int = Path(ge=2000, le=2100),
    user: User = Depends(_apr_lock),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.set_annual_review_lock(
            db, product_id, year, locked=True, user=user
        )
    )


@router.post("/apr/annual-reviews/{product_id}/{year}/unlock", summary="解锁年度")
async def unlock_year(
    product_id: uuid.UUID,
    year: int = Path(ge=2000, le=2100),
    user: User = Depends(_apr_lock),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(
        data=await service.set_annual_review_lock(
            db, product_id, year, locked=False, user=user
        )
    )
