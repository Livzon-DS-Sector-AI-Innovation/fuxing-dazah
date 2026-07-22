from fastapi import APIRouter

from app.shared.module_registry import BUSINESS_MODULES

router = APIRouter()


@router.get("/modules", summary="业务模块清单")
async def list_modules() -> list[dict[str, str]]:
    return [module.as_dict() for module in BUSINESS_MODULES]
