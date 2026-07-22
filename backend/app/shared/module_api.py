from fastapi import APIRouter

from app.shared.module_registry import ModuleDefinition


def create_module_router(module: ModuleDefinition) -> APIRouter:
    router = APIRouter()

    @router.get("/", summary=f"{module.name}模块信息")
    async def read_module() -> dict[str, str]:
        return module.as_dict()

    return router
