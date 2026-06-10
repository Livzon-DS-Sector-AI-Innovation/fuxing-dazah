"""设备模块 API 路由入口."""

from app.modules.equipment.api.calibration import (
    router as calibration_router,
)
from app.modules.equipment.api.claim import router as claim_router
from app.modules.equipment.api.config import router as config_router
from app.modules.equipment.api.equipment import (
    router as equipment_router,
)
from app.modules.equipment.api.failure_codes import (
    router as failure_codes_router,
)
from app.modules.equipment.api.images import router as images_router
from app.modules.equipment.api.inspection import (
    router as inspection_router,
)
from app.modules.equipment.api.inspection_templates import (
    router as inspection_templates_router,
)
from app.modules.equipment.api.maintainers import router as maintainers_router
from app.modules.equipment.api.maintenance_plans import (
    router as maintenance_plans_router,
)
from app.modules.equipment.api.personnel import router as personnel_router
from app.modules.equipment.api.spare_parts import (
    router as spare_parts_router,
)
from app.modules.equipment.api.work_orders import (
    router as work_orders_router,
)
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

router = create_module_router(MODULES_BY_CODE["equipment"])

# 设备台账路由
router.include_router(equipment_router)

# 备件管理路由
router.include_router(spare_parts_router, prefix="/spare-parts")

# 维护模块路由
router.include_router(
    failure_codes_router, prefix="/maintenance/failure-codes"
)
router.include_router(
    work_orders_router, prefix="/maintenance/work-orders"
)
router.include_router(
    calibration_router, prefix="/maintenance/calibration"
)
router.include_router(
    maintenance_plans_router, prefix="/maintenance/plans"
)
router.include_router(
    inspection_templates_router,
    prefix="/maintenance/inspection-templates",
)
router.include_router(images_router, prefix="/maintenance/work-orders")
router.include_router(claim_router, prefix="/maintenance/work-orders")
router.include_router(config_router, prefix="/maintenance/config")
router.include_router(maintainers_router, prefix="/maintenance/staff")
router.include_router(personnel_router, prefix="/personnel")
# 巡检模块路由（独立于维修工单）
router.include_router(inspection_router, prefix="/inspection")
