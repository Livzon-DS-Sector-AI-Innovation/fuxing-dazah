from fastapi import APIRouter

from app.modules.administration import router as administration_router
from app.modules.energy import router as energy_router
from app.modules.environment import router as environment_router
from app.modules.equipment import router as equipment_router
from app.modules.hr import ai_exam_router
from app.modules.hr import router as hr_router
from app.modules.hr.labor_contract.routes import (
    sign_router as labor_contract_sign_router,
)
from app.modules.hr.offboarding.sign_routes import (
    sign_router as departure_cert_sign_router,
)
from app.modules.meter import router as meter_router
from app.modules.procurement import router as procurement_router
from app.modules.production import router as production_router
from app.modules.qa.api import router as qa_router
from app.modules.quality import router as quality_router
from app.modules.registration import router as registration_router
from app.modules.research import router as research_router
from app.modules.toolbox import router as toolbox_router
from app.modules.warehouse import router as warehouse_router
from app.platform.feedback import router as feedback_router
from app.platform.identity.api import (
    dept_router,
    impersonation_router,
    personnel_router,
    sync_router,
    user_router,
)
from app.platform.identity.api import (
    router as identity_router,
)
from app.platform.permission.api import router as permission_router
from app.platform.system import router as system_router

api_router = APIRouter()

api_router.include_router(identity_router, prefix="/identity", tags=["身份认证"])
api_router.include_router(user_router, prefix="/identity", tags=["用户信息"])
api_router.include_router(impersonation_router, prefix="/identity", tags=["用户代理"])
api_router.include_router(dept_router, prefix="/identity", tags=["组织架构"])
api_router.include_router(personnel_router, prefix="/identity", tags=["人员名单"])
api_router.include_router(sync_router, prefix="/identity", tags=["飞书同步"])
api_router.include_router(system_router, prefix="/system", tags=["系统"])
api_router.include_router(production_router, prefix="/production", tags=["生产管理"])
api_router.include_router(equipment_router, prefix="/equipment", tags=["设备管理"])
api_router.include_router(environment_router, prefix="/environment", tags=["环保管理"])
api_router.include_router(energy_router, prefix="/energy", tags=["能源管理"])
api_router.include_router(warehouse_router, prefix="/warehouse", tags=["仓储管理"])
api_router.include_router(toolbox_router, prefix="/toolbox", tags=["工具箱"])
api_router.include_router(procurement_router, prefix="/procurement", tags=["采购管理"])
api_router.include_router(
    administration_router,
    prefix="/administration",
    tags=["行政管理"],
)
api_router.include_router(hr_router, prefix="/hr", tags=["人事管理"])
# 劳动合同公开签字（免登）：token 即凭证，不能挂在带 require_hr_basic 门禁的 hr_router 下
api_router.include_router(labor_contract_sign_router, prefix="/hr", tags=["HR-劳动合同"])
# 离职证明公开签字（免登）：token 即凭证，员工离职办结后无系统账号
api_router.include_router(departure_cert_sign_router, prefix="/hr", tags=["HR-离职管理"])
api_router.include_router(ai_exam_router, prefix="/hr", tags=["AI 出题"])
api_router.include_router(research_router, prefix="/research", tags=["研发管理"])
api_router.include_router(
    registration_router,
    prefix="/registration",
    tags=["注册管理"],
)
api_router.include_router(quality_router, prefix="/quality", tags=["质量管理"])
api_router.include_router(qa_router, prefix="/qa", tags=["QA"])
api_router.include_router(meter_router, prefix="/meter", tags=["仪表管理"])
api_router.include_router(feedback_router, prefix="/feedback", tags=["系统反馈"])
api_router.include_router(permission_router, prefix="/permission", tags=["权限管理"])
