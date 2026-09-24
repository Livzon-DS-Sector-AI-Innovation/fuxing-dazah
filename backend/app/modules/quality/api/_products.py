"""products API 路由（api.py 拆分）。"""


from typing import Any

from fastapi import (
    Body,
    Depends,
)

from app.modules.quality.api._common import (
    _load_products,
    _save_products,
    router,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.get("/products", summary="列出产品代码映射")
async def list_products() -> list[dict[str, Any]]:
    return _load_products()


@router.post("/products", summary="保存产品代码映射")
async def save_products(
    data: list[dict[str, Any]] = Body(...),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> dict[str, Any]:
    _save_products(data)
    return {"message": "已保存", "count": len(data)}
