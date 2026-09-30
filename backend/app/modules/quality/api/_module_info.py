"""_module_info API 路由（api.py 拆分）。"""




from app.modules.quality.api._common import (
    _module,
    router,
)


@router.get("/", summary=f"{_module.name}模块信息")
async def read_module() -> dict[str, str]:
    return _module.as_dict()
