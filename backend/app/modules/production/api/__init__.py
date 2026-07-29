"""生产模块 HTTP 路由。只做 HTTP 层：入参、依赖注入、调 service、统一响应。"""

from fastapi import APIRouter

from app.modules.production.api.assignment import router as assignment_router
from app.modules.production.api.batch import router as batch_router
from app.modules.production.api.execution import router as execution_router
from app.modules.production.api.intermediate import router as intermediate_router
from app.modules.production.api.material import router as material_router
from app.modules.production.api.planning import router as planning_router
from app.modules.production.api.product import router as product_router
from app.modules.production.api.route import router as route_router
from app.modules.production.api.workbench import router as workbench_router

router = APIRouter()
router.include_router(assignment_router)
router.include_router(product_router)
router.include_router(route_router)
router.include_router(batch_router)
router.include_router(execution_router)
router.include_router(intermediate_router)
router.include_router(material_router)
router.include_router(planning_router)
router.include_router(workbench_router)

__all__ = ["router"]
