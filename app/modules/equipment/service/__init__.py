"""Equipment service layer: re-export all public functions."""

from app.modules.equipment.service.calibration import (
    create_calibration_plan,
    create_calibration_record,
    delete_calibration_plan,
    get_calibration_plan_by_id,
    get_calibration_plans,
    get_calibration_record_by_id,
    get_calibration_records,
    get_overdue_calibration_plans,
    update_calibration_plan,
)
from app.modules.equipment.service.equipment import (
    create_equipment,
    create_equipment_category,
    create_location,
    delete_equipment,
    delete_equipment_category,
    delete_location,
    generate_equipment_no,
    get_departments_for_select,
    get_equipment_by_id,
    get_equipment_categories,
    get_equipment_category_by_id,
    get_equipment_category_tree,
    get_equipment_statistics,
    get_equipments,
    get_location_by_id,
    get_location_tree,
    get_locations,
    update_equipment,
    update_equipment_category,
    update_location,
)
from app.modules.equipment.service.failure_code import (
    FailureCodeModel,
    create_failure_code,
    delete_failure_code,
    get_failure_code_by_id,
    get_failure_codes,
    update_failure_code,
)
from app.modules.equipment.service.inspection import (
    close_task as close_inspection_task,
)
from app.modules.equipment.service.inspection import (
    complete_task as complete_inspection_task,
)
from app.modules.equipment.service.inspection import (
    create_route,
    delete_route,
    get_history,
    get_route_by_id,
    get_routes,
    get_task_detail,
    get_task_photos,
    set_route_equipments,
    submit_equipment_check,
    update_route,
)
from app.modules.equipment.service.inspection import (
    create_task as create_inspection_task,
)
from app.modules.equipment.service.inspection import (
    delete_photo as delete_inspection_photo,
)
from app.modules.equipment.service.inspection import (
    get_task_by_id as get_inspection_task_by_id,
)
from app.modules.equipment.service.inspection import (
    get_tasks as get_inspection_tasks,
)
from app.modules.equipment.service.inspection import (
    start_task as start_inspection_task,
)
from app.modules.equipment.service.inspection import (
    upload_photo as upload_inspection_photo,
)
from app.modules.equipment.service.ai import analyze_inspection_photo
from app.modules.equipment.service.inspection_template import (
    add_template_item,
    complete_inspection,
    create_inspection_template,
    delete_inspection_template,
    delete_template_item,
    get_inspection_template_by_id,
    get_inspection_templates,
    update_inspection_template,
    update_template_item,
)
from app.modules.equipment.service.maintenance_config import (
    get_claim_timeout_config,
    update_claim_timeout_config,
)
from app.modules.equipment.service.maintenance_plan import (
    create_maintenance_plan,
    delete_maintenance_plan,
    generate_due_work_orders,
    get_maintenance_plan_by_id,
    get_maintenance_plans,
    get_overdue_maintenance_plans,
    update_maintenance_plan,
)
from app.modules.equipment.service.personnel import (
    add_personnel,
    assign_roles,
    create_role,
    delete_personnel,
    delete_role,
    get_candidates,
    get_personnel,
    get_personnel_by_id,
    get_role,
    get_role_by_code,
    list_personnel,
    list_roles,
    refresh_feishu,
    update_categories,
    update_personnel,
    update_role,
)
from app.modules.equipment.service.spare_part import (
    adjust_stock,
    create_spare_part,
    delete_spare_part,
    get_spare_part_by_id,
    get_spare_parts,
    get_stock_by_spare_part_id,
    get_stock_warnings,
    inbound_stock,
    outbound_stock,
    update_spare_part,
)
from app.modules.equipment.service.work_order import (
    assign_work_order,
    claim_work_order,
    close_work_order,
    complete_work_order,
    consume_materials,
    create_work_order,
    generate_work_order_no,
    get_work_order_by_id,
    get_work_order_statistics,
    get_work_orders,
    start_work_order,
    update_work_order,
    verify_work_order,
)
from app.modules.equipment.service.work_order_image import (
    delete_image as delete_work_order_image,
)
from app.modules.equipment.service.work_order_image import (
    get_images as get_work_order_images,
)
from app.modules.equipment.service.work_order_image import (
    upload_images,
)

__all__ = [
    # ai
    "analyze_inspection_photo",
    # calibration
    "create_calibration_plan",
    "create_calibration_record",
    "delete_calibration_plan",
    "get_calibration_plan_by_id",
    "get_calibration_plans",
    "get_calibration_record_by_id",
    "get_calibration_records",
    "get_overdue_calibration_plans",
    "update_calibration_plan",
    # equipment
    "create_equipment",
    "create_equipment_category",
    "create_location",
    "delete_equipment",
    "delete_equipment_category",
    "delete_location",
    "generate_equipment_no",
    "get_departments_for_select",
    "get_equipment_by_id",
    "get_equipment_categories",
    "get_equipment_category_by_id",
    "get_equipment_category_tree",
    "get_equipment_statistics",
    "get_equipments",
    "get_location_by_id",
    "get_location_tree",
    "get_locations",
    "update_equipment",
    "update_equipment_category",
    "update_location",
    # failure code
    "FailureCodeModel",
    "add_template_item",
    "complete_inspection",
    "create_failure_code",
    "create_inspection_template",
    "delete_failure_code",
    "delete_inspection_template",
    "delete_template_item",
    "get_failure_code_by_id",
    "get_failure_codes",
    "get_inspection_template_by_id",
    "get_inspection_templates",
    "update_failure_code",
    "update_inspection_template",
    "update_template_item",
    # maintenance plan
    "create_maintenance_plan",
    "delete_maintenance_plan",
    "generate_due_work_orders",
    "get_maintenance_plan_by_id",
    "get_maintenance_plans",
    "get_overdue_maintenance_plans",
    "update_maintenance_plan",
    # spare part
    "adjust_stock",
    "create_spare_part",
    "delete_spare_part",
    "get_spare_part_by_id",
    "get_spare_parts",
    "get_stock_by_spare_part_id",
    "get_stock_warnings",
    "inbound_stock",
    "outbound_stock",
    "update_spare_part",
    # work order
    "assign_work_order",
    "claim_work_order",
    "close_work_order",
    "complete_work_order",
    "consume_materials",
    "create_work_order",
    "generate_work_order_no",
    "get_work_order_by_id",
    "get_work_order_statistics",
    "get_work_orders",
    "start_work_order",
    "update_work_order",
    "verify_work_order",
    # maintenance config
    "get_claim_timeout_config",
    "update_claim_timeout_config",
    # work order image
    "upload_images",
    "get_work_order_images",
    "delete_work_order_image",
    # personnel
    "add_personnel",
    "assign_roles",
    "create_role",
    "delete_personnel",
    "delete_role",
    "get_candidates",
    "get_personnel",
    "get_personnel_by_id",
    "get_role",
    "get_role_by_code",
    "list_personnel",
    "list_roles",
    "refresh_feishu",
    "update_categories",
    "update_personnel",
    "update_role",
]
