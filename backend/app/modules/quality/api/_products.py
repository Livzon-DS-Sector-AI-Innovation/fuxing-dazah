"""products API 路由（api.py 拆分）。"""


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
async def list_products():
    return _load_products()


@router.post("/products", summary="保存产品代码映射")
async def save_products(
    data: list[dict] = Body(...),
    _user: User = Depends(require_permission("quality:standard:manage")),
):
    _save_products(data)
    return {"message": "已保存", "count": len(data)}
