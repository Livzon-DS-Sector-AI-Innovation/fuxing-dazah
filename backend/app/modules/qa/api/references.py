"""QA 引用选择器端点：部门与外部来源（生产/设备）引用。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import paginated_response, success_response
from app.modules.qa.api._deps import (
    deviation_reference_read,
    qa_read,
)
from app.platform.identity.models import User

router = APIRouter()


@router.get("/references/departments", summary="QA责任部门引用")
async def reference_departments(
    user: User = Depends(deviation_reference_read),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    include_inactive: bool = False,
) -> Any:
    from app.platform.identity.public_api import list_department_briefs

    rows = await list_department_briefs(
        db, keyword=keyword, include_deleted=include_inactive
    )
    return success_response(
        [
            {
                "id": row.id,
                "feishu_department_id": row.feishu_department_id,
                "name": row.name,
                "parent_feishu_department_id": row.parent_feishu_department_id,
                "path": row.path,
                "available": row.is_active,
            }
            for row in rows
        ]
    )


@router.get("/references/sources/{kind}", summary="QA外部来源引用")
async def reference_sources(
    kind: str,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    value = kind.upper()
    rows: list[Any]
    total: int
    if value == "PRODUCT":
        from app.modules.production.public_api import list_products

        rows, total = await list_products(db, keyword, page, page_size)
        entity = "product"
    elif value in {"MATERIAL", "INTERMEDIATE_TYPE", "INTERMEDIATE-TYPE"}:
        from app.modules.production.public_api import list_intermediate_types

        rows, total = await list_intermediate_types(db, keyword, page, page_size)
        entity = "intermediate_type"
    elif value == "EQUIPMENT":
        from app.modules.equipment.public_api import list_equipment_references

        rows, total = await list_equipment_references(
            db,
            user,
            "qa",
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        entity = "equipment"
    else:
        raise AppException(status_code=422, message="不支持的外部来源类型")

    def brief_value(row: Any, *names: str) -> Any:
        """兼容 public_api 摘要对象和字典型适配器返回值。"""
        for name in names:
            value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
            if value not in (None, ""):
                return value
        return None

    data = []
    for row in rows:
        source_id = brief_value(row, "id")
        active = brief_value(row, "is_active")
        deleted = brief_value(row, "is_deleted")
        data.append(
            {
                "id": source_id,
                # production Product 的 product_code 允许为空；引用选择器仍
                # 需要稳定可显示的 code，因此回退到来源 ID。
                "code": brief_value(row, "code", "equipment_no", "product_code")
                or str(source_id),
                "name": brief_value(row, "name", "product_name", "equipment_name")
                or str(source_id),
                "source_module": "equipment" if entity == "equipment" else "production",
                "source_entity": entity,
                "source_id": source_id,
                "is_active": active if active is not None else True,
                "is_deleted": deleted if deleted is not None else False,
                # 仅用于选择器分组，不暴露设备台账详情。
                "source": brief_value(row, "source"),
                "category": brief_value(row, "category"),
                "is_product": brief_value(row, "is_product"),
            }
        )
    return paginated_response(data, page, page_size, total)


# ───────────────────────── 文件类型与台账 ─────────────────────────
