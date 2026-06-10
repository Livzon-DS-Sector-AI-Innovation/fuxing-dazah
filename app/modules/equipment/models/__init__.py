"""Equipment ORM models."""

from app.modules.equipment.models.calibration import (
    CalibrationPlan,
    CalibrationRecord,
)
from app.modules.equipment.models.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentCategoryLink,
    Location,
)
from app.modules.equipment.models.failure_code import (
    FailureAction,
    FailureCause,
    FailureSymptom,
)
from app.modules.equipment.models.inspection import (
    InspectionPhoto,
    InspectionRoute,
    InspectionRouteEquipment,
    InspectionTask,
)
from app.modules.equipment.models.inspection_template import (
    InspectionRecord,
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.modules.equipment.models.maintenance_config import MaintenanceConfig
from app.modules.equipment.models.maintenance_plan import MaintenancePlan
from app.modules.equipment.models.personnel import (
    EquipmentPersonnel,
    EquipmentPersonnelCategory,
    EquipmentPersonnelRole,
    EquipmentRole,
)
from app.modules.equipment.models.spare_part import (
    EquipmentSparePart,
    SparePart,
    SparePartStock,
    SparePartTransaction,
)
from app.modules.equipment.models.work_order import WorkOrder
from app.modules.equipment.models.work_order_image import WorkOrderImage

__all__ = [
    "CalibrationPlan",
    "CalibrationRecord",
    "Equipment",
    "EquipmentCategory",
    "EquipmentCategoryLink",
    "EquipmentPersonnel",
    "EquipmentPersonnelCategory",
    "EquipmentPersonnelRole",
    "EquipmentRole",
    "FailureAction",
    "FailureCause",
    "FailureSymptom",
    "InspectionPhoto",
    "InspectionRecord",
    "InspectionRoute",
    "InspectionRouteEquipment",
    "InspectionTask",
    "InspectionTemplate",
    "InspectionTemplateItem",
    "Location",
    "MaintenancePlan",
    "EquipmentSparePart",
    "SparePart",
    "SparePartStock",
    "SparePartTransaction",
    "MaintenanceConfig",
    "WorkOrder",
    "WorkOrderImage",
]
