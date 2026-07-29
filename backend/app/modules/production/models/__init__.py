"""生产模块 ORM 模型。按聚合拆分：product / route / batch / execution / intermediate / assignment / planning。"""

from app.modules.production.models.assignment import NodeAssignment, StageAssignment
from app.modules.production.models.batch import Batch, BatchLink
from app.modules.production.models.execution import (
    NodeExecution,
    NodeExecutionEquipment,
    NodeFieldValue,
)
from app.modules.production.models.intermediate import (
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
    IntermediateType,
    RouteNodeIntermediate,
)
from app.modules.production.models.planning import (
    Demand,
    DemandAllocation,
    PlanAllocation,
    PlanItem,
    PlanOrder,
)
from app.modules.production.models.product import Product
from app.modules.production.models.route import (
    NodeFieldDef,
    ProcessRoute,
    RouteEdge,
    RouteNode,
)

__all__ = [
    "Batch",
    "BatchIntermediateConsumption",
    "BatchIntermediateOutput",
    "BatchLink",
    "Demand",
    "DemandAllocation",
    "IntermediateType",
    "NodeAssignment",
    "NodeExecution",
    "NodeExecutionEquipment",
    "NodeFieldValue",
    "NodeFieldDef",
    "PlanAllocation",
    "PlanItem",
    "PlanOrder",
    "ProcessRoute",
    "Product",
    "RouteEdge",
    "RouteNode",
    "RouteNodeIntermediate",
    "StageAssignment",
]
