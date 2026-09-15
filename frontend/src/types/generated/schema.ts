export interface paths {
    "/api/v1/system/modules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 业务模块清单 */
        get: operations["list_modules_api_v1_system_modules_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/production/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 生产管理模块信息 */
        get: operations["read_module_api_v1_production__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 设备管理模块信息 */
        get: operations["read_module_api_v1_equipment__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/categories": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取设备分类列表
         * @description 获取设备分类列表
         */
        get: operations["get_equipment_categories_api_v1_equipment_categories_get"];
        put?: never;
        /**
         * 创建设备分类
         * @description 创建设备分类
         */
        post: operations["create_equipment_category_api_v1_equipment_categories_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/categories/{category_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取设备分类详情
         * @description 获取设备分类详情
         */
        get: operations["get_equipment_category_api_v1_equipment_categories__category_id__get"];
        /**
         * 更新设备分类
         * @description 更新设备分类
         */
        put: operations["update_equipment_category_api_v1_equipment_categories__category_id__put"];
        post?: never;
        /**
         * 删除设备分类
         * @description 删除设备分类
         */
        delete: operations["delete_equipment_category_api_v1_equipment_categories__category_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/locations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取位置列表
         * @description 获取位置列表
         */
        get: operations["get_locations_api_v1_equipment_locations_get"];
        put?: never;
        /**
         * 创建位置
         * @description 创建位置
         */
        post: operations["create_location_api_v1_equipment_locations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/locations/{location_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取位置详情
         * @description 获取位置详情
         */
        get: operations["get_location_api_v1_equipment_locations__location_id__get"];
        /**
         * 更新位置
         * @description 更新位置
         */
        put: operations["update_location_api_v1_equipment_locations__location_id__put"];
        post?: never;
        /**
         * 删除位置
         * @description 删除位置
         */
        delete: operations["delete_location_api_v1_equipment_locations__location_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/equipments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取设备列表
         * @description 获取设备列表
         */
        get: operations["get_equipments_api_v1_equipment_equipments_get"];
        put?: never;
        /**
         * 创建设备
         * @description 创建设备
         */
        post: operations["create_equipment_api_v1_equipment_equipments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/equipments/statistics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取设备统计
         * @description 获取设备统计
         */
        get: operations["get_equipment_statistics_api_v1_equipment_equipments_statistics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/equipments/{equipment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 获取设备详情
         * @description 获取设备详情
         */
        get: operations["get_equipment_api_v1_equipment_equipments__equipment_id__get"];
        /**
         * 更新设备
         * @description 更新设备
         */
        put: operations["update_equipment_api_v1_equipment_equipments__equipment_id__put"];
        post?: never;
        /**
         * 删除设备
         * @description 删除设备
         */
        delete: operations["delete_equipment_api_v1_equipment_equipments__equipment_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/spare-parts/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 备件列表 */
        get: operations["list_spare_parts_api_v1_equipment_spare_parts__get"];
        put?: never;
        /** 创建备件 */
        post: operations["create_spare_part_api_v1_equipment_spare_parts__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/spare-parts/stock/warnings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 库存预警列表 */
        get: operations["get_stock_warnings_api_v1_equipment_spare_parts_stock_warnings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/spare-parts/{spare_part_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 备件详情 */
        get: operations["get_spare_part_api_v1_equipment_spare_parts__spare_part_id__get"];
        /** 更新备件 */
        put: operations["update_spare_part_api_v1_equipment_spare_parts__spare_part_id__put"];
        post?: never;
        /** 删除备件 */
        delete: operations["delete_spare_part_api_v1_equipment_spare_parts__spare_part_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/spare-parts/{spare_part_id}/stock": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查看库存 */
        get: operations["get_stock_api_v1_equipment_spare_parts__spare_part_id__stock_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/spare-parts/{spare_part_id}/stock/inbound": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 入库 */
        post: operations["inbound_stock_api_v1_equipment_spare_parts__spare_part_id__stock_inbound_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/spare-parts/{spare_part_id}/stock/adjust": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 盘点调整 */
        post: operations["adjust_stock_api_v1_equipment_spare_parts__spare_part_id__stock_adjust_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/failure-codes/symptoms": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询故障现象列表 */
        get: operations["list_codes_api_v1_equipment_maintenance_failure_codes_symptoms_get"];
        put?: never;
        /** 新增故障现象 */
        post: operations["create_api_v1_equipment_maintenance_failure_codes_symptoms_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/failure-codes/symptoms/{code_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询单个故障现象 */
        get: operations["get_one_api_v1_equipment_maintenance_failure_codes_symptoms__code_id__get"];
        /** 修改故障现象 */
        put: operations["update_api_v1_equipment_maintenance_failure_codes_symptoms__code_id__put"];
        post?: never;
        /** 删除故障现象 */
        delete: operations["delete_api_v1_equipment_maintenance_failure_codes_symptoms__code_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/failure-codes/causes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询故障原因列表 */
        get: operations["list_codes_api_v1_equipment_maintenance_failure_codes_causes_get"];
        put?: never;
        /** 新增故障原因 */
        post: operations["create_api_v1_equipment_maintenance_failure_codes_causes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/failure-codes/causes/{code_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询单个故障原因 */
        get: operations["get_one_api_v1_equipment_maintenance_failure_codes_causes__code_id__get"];
        /** 修改故障原因 */
        put: operations["update_api_v1_equipment_maintenance_failure_codes_causes__code_id__put"];
        post?: never;
        /** 删除故障原因 */
        delete: operations["delete_api_v1_equipment_maintenance_failure_codes_causes__code_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/failure-codes/actions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询维修措施列表 */
        get: operations["list_codes_api_v1_equipment_maintenance_failure_codes_actions_get"];
        put?: never;
        /** 新增维修措施 */
        post: operations["create_api_v1_equipment_maintenance_failure_codes_actions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/failure-codes/actions/{code_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询单个维修措施 */
        get: operations["get_one_api_v1_equipment_maintenance_failure_codes_actions__code_id__get"];
        /** 修改维修措施 */
        put: operations["update_api_v1_equipment_maintenance_failure_codes_actions__code_id__put"];
        post?: never;
        /** 删除维修措施 */
        delete: operations["delete_api_v1_equipment_maintenance_failure_codes_actions__code_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 工单列表 */
        get: operations["list_work_orders_api_v1_equipment_maintenance_work_orders__get"];
        put?: never;
        /** 创建工单（报修） */
        post: operations["create_work_order_api_v1_equipment_maintenance_work_orders__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/statistics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 工单统计 */
        get: operations["get_work_order_statistics_api_v1_equipment_maintenance_work_orders_statistics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 工单详情 */
        get: operations["get_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}/assign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 指派维修人 */
        put: operations["assign_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__assign_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 开始维修 */
        put: operations["start_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__start_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 提交完成 */
        put: operations["complete_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__complete_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 验收 */
        put: operations["verify_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__verify_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}/close": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 关闭工单 */
        put: operations["close_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__close_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/work-orders/{work_order_id}/materials": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 工单领料记录 */
        get: operations["get_material_consumptions_api_v1_equipment_maintenance_work_orders__work_order_id__materials_get"];
        put?: never;
        /** 领料 */
        post: operations["consume_materials_api_v1_equipment_maintenance_work_orders__work_order_id__materials_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/calibration/plans": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 校准计划列表 */
        get: operations["list_calibration_plans_api_v1_equipment_maintenance_calibration_plans_get"];
        put?: never;
        /** 新增校准计划 */
        post: operations["create_calibration_plan_api_v1_equipment_maintenance_calibration_plans_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/calibration/plans/overdue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询到期/逾期的校准计划 */
        get: operations["get_overdue_plans_api_v1_equipment_maintenance_calibration_plans_overdue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/calibration/plans/{plan_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 校准计划详情 */
        get: operations["get_calibration_plan_api_v1_equipment_maintenance_calibration_plans__plan_id__get"];
        /** 修改校准计划 */
        put: operations["update_calibration_plan_api_v1_equipment_maintenance_calibration_plans__plan_id__put"];
        post?: never;
        /** 删除校准计划 */
        delete: operations["delete_calibration_plan_api_v1_equipment_maintenance_calibration_plans__plan_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/calibration/records": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 校准记录列表 */
        get: operations["list_calibration_records_api_v1_equipment_maintenance_calibration_records_get"];
        put?: never;
        /** 新增校准记录 */
        post: operations["create_calibration_record_api_v1_equipment_maintenance_calibration_records_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/calibration/records/{record_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 校准记录详情 */
        get: operations["get_calibration_record_api_v1_equipment_maintenance_calibration_records__record_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/plans/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 维护计划列表 */
        get: operations["list_maintenance_plans_api_v1_equipment_maintenance_plans__get"];
        put?: never;
        /** 新增维护计划 */
        post: operations["create_maintenance_plan_api_v1_equipment_maintenance_plans__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/plans/overdue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询到期/逾期的维护计划 */
        get: operations["get_overdue_plans_api_v1_equipment_maintenance_plans_overdue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/plans/{plan_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 维护计划详情 */
        get: operations["get_maintenance_plan_api_v1_equipment_maintenance_plans__plan_id__get"];
        /** 修改维护计划 */
        put: operations["update_maintenance_plan_api_v1_equipment_maintenance_plans__plan_id__put"];
        post?: never;
        /** 删除维护计划 */
        delete: operations["delete_maintenance_plan_api_v1_equipment_maintenance_plans__plan_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/inspection-templates/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 巡检模板列表 */
        get: operations["list_inspection_templates_api_v1_equipment_maintenance_inspection_templates__get"];
        put?: never;
        /** 新增巡检模板 */
        post: operations["create_inspection_template_api_v1_equipment_maintenance_inspection_templates__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/inspection-templates/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 巡检模板详情 */
        get: operations["get_inspection_template_api_v1_equipment_maintenance_inspection_templates__template_id__get"];
        /** 修改巡检模板 */
        put: operations["update_inspection_template_api_v1_equipment_maintenance_inspection_templates__template_id__put"];
        post?: never;
        /** 删除巡检模板 */
        delete: operations["delete_inspection_template_api_v1_equipment_maintenance_inspection_templates__template_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/inspection-templates/{template_id}/items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 添加检查项 */
        post: operations["add_template_item_api_v1_equipment_maintenance_inspection_templates__template_id__items_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/inspection-templates/items/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** 修改检查项 */
        put: operations["update_template_item_api_v1_equipment_maintenance_inspection_templates_items__item_id__put"];
        post?: never;
        /** 删除检查项 */
        delete: operations["delete_template_item_api_v1_equipment_maintenance_inspection_templates_items__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/equipment/maintenance/inspection-templates/complete/{work_order_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 提交巡检结果 */
        post: operations["complete_inspection_api_v1_equipment_maintenance_inspection_templates_complete__work_order_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/safety/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 安全管理模块信息 */
        get: operations["read_module_api_v1_safety__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/environment/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 环保管理模块信息 */
        get: operations["read_module_api_v1_environment__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 能源管理模块信息 */
        get: operations["read_module_api_v1_energy__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/devices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询设备配置列表 */
        get: operations["list_device_configs_api_v1_energy_devices_get"];
        put?: never;
        /** 新增设备配置 */
        post: operations["create_device_config_api_v1_energy_devices_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/devices/{config_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询单个设备配置 */
        get: operations["get_device_config_api_v1_energy_devices__config_id__get"];
        /** 修改设备配置 */
        put: operations["update_device_config_api_v1_energy_devices__config_id__put"];
        post?: never;
        /** 删除设备配置 */
        delete: operations["delete_device_config_api_v1_energy_devices__config_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/data": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询能耗数据 */
        get: operations["list_energy_data_api_v1_energy_data_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/data/statistics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 能耗统计 */
        get: operations["get_energy_statistics_api_v1_energy_data_statistics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/collect/trigger": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 手动触发采集 */
        post: operations["trigger_collection_api_v1_energy_collect_trigger_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/energy/collect/logs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 查询采集日志 */
        get: operations["list_collect_logs_api_v1_energy_collect_logs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/warehouse/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 仓储管理模块信息 */
        get: operations["read_module_api_v1_warehouse__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/procurement/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 采购管理模块信息 */
        get: operations["read_module_api_v1_procurement__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/administration/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 行政管理模块信息 */
        get: operations["read_module_api_v1_administration__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/hr/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 人事管理模块信息 */
        get: operations["read_module_api_v1_hr__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/research/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 研发管理模块信息 */
        get: operations["read_module_api_v1_research__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/registration/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 注册管理模块信息 */
        get: operations["read_module_api_v1_registration__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quality/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 质量管理模块信息 */
        get: operations["read_module_api_v1_quality__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * CalibrationPlanCreate
         * @description 创建校准计划请求
         */
        CalibrationPlanCreate: {
            /**
             * Equipment Id
             * Format: uuid
             * @description 设备ID
             */
            equipment_id: string;
            /**
             * Calibration Type
             * @description 校准类型
             * @enum {string}
             */
            calibration_type: "内部校准" | "外部检定";
            /**
             * Cycle Months
             * @description 校准周期（月）
             */
            cycle_months: number;
            /**
             * Last Calibration Date
             * @description 上次校准日期
             */
            last_calibration_date?: string | null;
            /**
             * Responsible Person Id
             * @description 负责人ID
             */
            responsible_person_id?: string | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /**
         * CalibrationPlanUpdate
         * @description 更新校准计划请求
         */
        CalibrationPlanUpdate: {
            /**
             * Calibration Type
             * @description 校准类型
             */
            calibration_type?: ("内部校准" | "外部检定") | null;
            /**
             * Cycle Months
             * @description 校准周期（月）
             */
            cycle_months?: number | null;
            /**
             * Last Calibration Date
             * @description 上次校准日期
             */
            last_calibration_date?: string | null;
            /**
             * Responsible Person Id
             * @description 负责人ID
             */
            responsible_person_id?: string | null;
            /**
             * Status
             * @description 状态
             */
            status?: ("启用" | "停用") | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /**
         * CalibrationRecordCreate
         * @description 创建校准记录请求
         */
        CalibrationRecordCreate: {
            /**
             * Calibration Plan Id
             * Format: uuid
             * @description 校准计划ID
             */
            calibration_plan_id: string;
            /**
             * Calibration Date
             * Format: date
             * @description 校准日期
             */
            calibration_date: string;
            /**
             * Calibration Type
             * @description 校准类型
             * @enum {string}
             */
            calibration_type: "内部校准" | "外部检定";
            /**
             * Result
             * @description 校准结果
             * @enum {string}
             */
            result: "合格" | "不合格";
            /**
             * Certificate No
             * @description 检定证书编号
             */
            certificate_no?: string | null;
            /**
             * Calibrated By
             * @description 校准单位/人员
             */
            calibrated_by?: string | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /** CollectTriggerRequest */
        CollectTriggerRequest: {
            /**
             * Platform Code
             * @description 指定平台，为空则采集所有平台
             */
            platform_code?: string | null;
        };
        /** EnergyDeviceConfigCreate */
        EnergyDeviceConfigCreate: {
            /**
             * Platform Code
             * @description 平台标识
             */
            platform_code: string;
            /**
             * Platform Device Code
             * @description 三方平台设备编码
             */
            platform_device_code: string;
            /**
             * Device Name
             * @description 设备名称
             */
            device_name: string;
            /**
             * Energy Type
             * @description 能源类型
             * @enum {string}
             */
            energy_type: "electricity" | "steam" | "water";
            /**
             * Api Endpoint
             * @description API 路径
             */
            api_endpoint: string;
            /**
             * Workshop
             * @description 所属车间
             */
            workshop: string;
            /**
             * Production Line
             * @description 所属产线
             */
            production_line: string;
            /**
             * Monitor Level
             * @description 监控等级
             * @default normal
             * @enum {string}
             */
            monitor_level: "normal" | "important" | "urgent";
            /**
             * Unit
             * @description 计量单位
             */
            unit: string;
            /**
             * Collection Interval
             * @description 采集间隔(分钟)
             * @default 60
             */
            collection_interval: number;
            /**
             * Is Enabled
             * @description 是否启用采集
             * @default true
             */
            is_enabled: boolean;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /** EnergyDeviceConfigUpdate */
        EnergyDeviceConfigUpdate: {
            /** Platform Code */
            platform_code?: string | null;
            /** Platform Device Code */
            platform_device_code?: string | null;
            /** Device Name */
            device_name?: string | null;
            /** Energy Type */
            energy_type?: ("electricity" | "steam" | "water") | null;
            /** Api Endpoint */
            api_endpoint?: string | null;
            /** Workshop */
            workshop?: string | null;
            /** Production Line */
            production_line?: string | null;
            /** Monitor Level */
            monitor_level?: ("normal" | "important" | "urgent") | null;
            /** Unit */
            unit?: string | null;
            /** Collection Interval */
            collection_interval?: number | null;
            /** Is Enabled */
            is_enabled?: boolean | null;
            /** Remark */
            remark?: string | null;
        };
        /**
         * EquipmentCategoryCreate
         * @description 创建设备分类请求
         */
        EquipmentCategoryCreate: {
            /**
             * Name
             * @description 分类名称
             */
            name: string;
            /**
             * Code
             * @description 分类代码
             */
            code: string;
            /**
             * Parent Id
             * @description 父分类ID
             */
            parent_id?: string | null;
            /**
             * Description
             * @description 分类描述
             */
            description?: string | null;
        };
        /**
         * EquipmentCategoryUpdate
         * @description 更新设备分类请求
         */
        EquipmentCategoryUpdate: {
            /**
             * Name
             * @description 分类名称
             */
            name?: string | null;
            /**
             * Code
             * @description 分类代码
             */
            code?: string | null;
            /**
             * Parent Id
             * @description 父分类ID
             */
            parent_id?: string | null;
            /**
             * Description
             * @description 分类描述
             */
            description?: string | null;
        };
        /**
         * EquipmentCreate
         * @description 创建设备请求
         */
        EquipmentCreate: {
            /**
             * Name
             * @description 设备名称
             */
            name: string;
            /**
             * Category Id
             * Format: uuid
             * @description 设备分类ID
             */
            category_id: string;
            /**
             * Location Id
             * Format: uuid
             * @description 设备位置ID
             */
            location_id: string;
            /**
             * Status
             * @description 设备状态：在用/备用/维修中/停用/报废
             * @default 在用
             * @enum {string}
             */
            status: "在用" | "备用" | "维修中" | "停用" | "报废";
            /**
             * Model
             * @description 设备型号
             */
            model?: string | null;
            /**
             * Specification
             * @description 设备规格
             */
            specification?: string | null;
            /**
             * Manufacturer
             * @description 制造商
             */
            manufacturer?: string | null;
            /**
             * Supplier
             * @description 供应商
             */
            supplier?: string | null;
            /**
             * Production Date
             * @description 出厂日期
             */
            production_date?: string | null;
            /**
             * Commissioning Date
             * @description 投用日期
             */
            commissioning_date?: string | null;
            /**
             * Description
             * @description 设备描述
             */
            description?: string | null;
            /**
             * Warranty Expire Date
             * @description 保修到期日
             */
            warranty_expire_date?: string | null;
            /**
             * Asset Value
             * @description 资产原值（元）
             */
            asset_value?: number | null;
            /**
             * Depreciation Years
             * @description 折旧年限
             */
            depreciation_years?: number | null;
            /**
             * Technical Params
             * @description 技术参数
             */
            technical_params?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * EquipmentUpdate
         * @description 更新设备请求
         */
        EquipmentUpdate: {
            /**
             * Name
             * @description 设备名称
             */
            name?: string | null;
            /**
             * Category Id
             * @description 设备分类ID
             */
            category_id?: string | null;
            /**
             * Location Id
             * @description 设备位置ID
             */
            location_id?: string | null;
            /**
             * Status
             * @description 设备状态：在用/备用/维修中/停用/报废
             */
            status?: ("在用" | "备用" | "维修中" | "停用" | "报废") | null;
            /**
             * Model
             * @description 设备型号
             */
            model?: string | null;
            /**
             * Specification
             * @description 设备规格
             */
            specification?: string | null;
            /**
             * Manufacturer
             * @description 制造商
             */
            manufacturer?: string | null;
            /**
             * Supplier
             * @description 供应商
             */
            supplier?: string | null;
            /**
             * Production Date
             * @description 出厂日期
             */
            production_date?: string | null;
            /**
             * Commissioning Date
             * @description 投用日期
             */
            commissioning_date?: string | null;
            /**
             * Description
             * @description 设备描述
             */
            description?: string | null;
            /**
             * Warranty Expire Date
             * @description 保修到期日
             */
            warranty_expire_date?: string | null;
            /**
             * Asset Value
             * @description 资产原值（元）
             */
            asset_value?: number | null;
            /**
             * Depreciation Years
             * @description 折旧年限
             */
            depreciation_years?: number | null;
            /**
             * Technical Params
             * @description 技术参数
             */
            technical_params?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * FailureCodeCreate
         * @description 创建故障代码请求
         */
        FailureCodeCreate: {
            /**
             * Code
             * @description 代码
             */
            code: string;
            /**
             * Name
             * @description 名称
             */
            name: string;
            /**
             * Description
             * @description 描述
             */
            description?: string | null;
            /**
             * Sort Order
             * @description 排序
             * @default 0
             */
            sort_order: number;
            /**
             * Is Active
             * @description 是否启用
             * @default true
             */
            is_active: boolean;
        };
        /**
         * FailureCodeUpdate
         * @description 更新故障代码请求
         */
        FailureCodeUpdate: {
            /**
             * Code
             * @description 代码
             */
            code?: string | null;
            /**
             * Name
             * @description 名称
             */
            name?: string | null;
            /**
             * Description
             * @description 描述
             */
            description?: string | null;
            /**
             * Sort Order
             * @description 排序
             */
            sort_order?: number | null;
            /**
             * Is Active
             * @description 是否启用
             */
            is_active?: boolean | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * InspectionCompleteRequest
         * @description 巡检完成请求（提交所有检查项结果）
         */
        InspectionCompleteRequest: {
            /**
             * Records
             * @description 检查项结果列表
             */
            records: components["schemas"]["InspectionRecordItem"][];
        };
        /**
         * InspectionRecordItem
         * @description 巡检记录项
         */
        InspectionRecordItem: {
            /**
             * Template Item Id
             * Format: uuid
             * @description 检查项ID
             */
            template_item_id: string;
            /**
             * Result
             * @description 结果：正常/异常/跳过
             */
            result: string;
            /**
             * Actual Value
             * @description 实际值
             */
            actual_value?: string | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /**
         * InspectionTemplateCreate
         * @description 创建巡检模板请求
         */
        InspectionTemplateCreate: {
            /**
             * Name
             * @description 模板名称
             */
            name: string;
            /**
             * Description
             * @description 模板描述
             */
            description?: string | null;
            /**
             * Equipment Category Id
             * @description 适用设备分类ID
             */
            equipment_category_id?: string | null;
            /**
             * Items
             * @description 检查项列表
             */
            items?: components["schemas"]["InspectionTemplateItemCreate"][];
        };
        /**
         * InspectionTemplateItemCreate
         * @description 创建巡检模板检查项请求
         */
        InspectionTemplateItemCreate: {
            /**
             * Item Name
             * @description 检查项名称
             */
            item_name: string;
            /**
             * Item Description
             * @description 检查项说明
             */
            item_description?: string | null;
            /**
             * Expected Result
             * @description 预期结果/标准值
             */
            expected_result?: string | null;
            /**
             * Check Method
             * @description 检查方法
             */
            check_method?: string | null;
            /**
             * Sort Order
             * @description 排序序号
             * @default 0
             */
            sort_order: number;
        };
        /**
         * InspectionTemplateItemUpdate
         * @description 更新巡检模板检查项请求
         */
        InspectionTemplateItemUpdate: {
            /**
             * Item Name
             * @description 检查项名称
             */
            item_name?: string | null;
            /**
             * Item Description
             * @description 检查项说明
             */
            item_description?: string | null;
            /**
             * Expected Result
             * @description 预期结果/标准值
             */
            expected_result?: string | null;
            /**
             * Check Method
             * @description 检查方法
             */
            check_method?: string | null;
            /**
             * Sort Order
             * @description 排序序号
             */
            sort_order?: number | null;
        };
        /**
         * InspectionTemplateUpdate
         * @description 更新巡检模板请求
         */
        InspectionTemplateUpdate: {
            /**
             * Name
             * @description 模板名称
             */
            name?: string | null;
            /**
             * Description
             * @description 模板描述
             */
            description?: string | null;
            /**
             * Equipment Category Id
             * @description 适用设备分类ID
             */
            equipment_category_id?: string | null;
            /**
             * Is Active
             * @description 是否启用
             */
            is_active?: boolean | null;
        };
        /**
         * LocationCreate
         * @description 创建位置请求
         */
        LocationCreate: {
            /**
             * Name
             * @description 位置名称
             */
            name: string;
            /**
             * Code
             * @description 位置代码
             */
            code: string;
            /**
             * Parent Id
             * @description 父位置ID
             */
            parent_id?: string | null;
            /**
             * Description
             * @description 位置描述
             */
            description?: string | null;
        };
        /**
         * LocationUpdate
         * @description 更新位置请求
         */
        LocationUpdate: {
            /**
             * Name
             * @description 位置名称
             */
            name?: string | null;
            /**
             * Code
             * @description 位置代码
             */
            code?: string | null;
            /**
             * Parent Id
             * @description 父位置ID
             */
            parent_id?: string | null;
            /**
             * Description
             * @description 位置描述
             */
            description?: string | null;
        };
        /**
         * MaintenancePlanCreate
         * @description 创建维护计划请求
         */
        MaintenancePlanCreate: {
            /**
             * Equipment Id
             * Format: uuid
             * @description 设备ID
             */
            equipment_id: string;
            /**
             * Plan Name
             * @description 计划名称
             */
            plan_name: string;
            /**
             * Plan Type
             * @description 计划类型
             * @default 预防性维护
             * @enum {string}
             */
            plan_type: "预防性维护" | "预测性维护";
            /**
             * Frequency
             * @description 维护频率数值
             */
            frequency: number;
            /**
             * Frequency Unit
             * @description 频率单位
             * @enum {string}
             */
            frequency_unit: "天" | "周" | "月" | "年";
            /**
             * Last Maintenance Date
             * @description 上次维护日期
             */
            last_maintenance_date?: string | null;
            /**
             * Responsible Person Id
             * @description 负责人ID
             */
            responsible_person_id?: string | null;
            /**
             * Maintenance Content
             * @description 维护内容说明
             */
            maintenance_content?: string | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /**
         * MaintenancePlanUpdate
         * @description 更新维护计划请求
         */
        MaintenancePlanUpdate: {
            /**
             * Plan Name
             * @description 计划名称
             */
            plan_name?: string | null;
            /**
             * Plan Type
             * @description 计划类型
             */
            plan_type?: ("预防性维护" | "预测性维护") | null;
            /**
             * Frequency
             * @description 维护频率数值
             */
            frequency?: number | null;
            /**
             * Frequency Unit
             * @description 频率单位
             */
            frequency_unit?: ("天" | "周" | "月" | "年") | null;
            /**
             * Last Maintenance Date
             * @description 上次维护日期
             */
            last_maintenance_date?: string | null;
            /**
             * Responsible Person Id
             * @description 负责人ID
             */
            responsible_person_id?: string | null;
            /**
             * Maintenance Content
             * @description 维护内容说明
             */
            maintenance_content?: string | null;
            /**
             * Status
             * @description 状态
             */
            status?: ("启用" | "停用" | "已完成") | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /**
         * MaterialConsumeItem
         * @description 单条领料项
         */
        MaterialConsumeItem: {
            /**
             * Spare Part Id
             * Format: uuid
             * @description 备件ID
             */
            spare_part_id: string;
            /**
             * Quantity
             * @description 领用数量
             */
            quantity: number;
        };
        /**
         * MaterialConsumeRequest
         * @description 领料请求
         */
        MaterialConsumeRequest: {
            /**
             * Items
             * @description 领料清单
             */
            items: components["schemas"]["MaterialConsumeItem"][];
        };
        /**
         * SparePartCreate
         * @description 创建备件请求
         */
        SparePartCreate: {
            /**
             * Code
             * @description 备件编码
             */
            code: string;
            /**
             * Name
             * @description 备件名称
             */
            name: string;
            /**
             * Specification
             * @description 规格型号
             */
            specification?: string | null;
            /**
             * Unit
             * @description 计量单位
             */
            unit: string;
            /**
             * Category
             * @description 备件分类
             */
            category?: string | null;
            /**
             * Default Supplier
             * @description 默认供应商
             */
            default_supplier?: string | null;
            /**
             * Unit Price
             * @description 参考单价
             */
            unit_price?: number | null;
            /**
             * Is Active
             * @description 是否启用
             * @default true
             */
            is_active: boolean;
        };
        /**
         * SparePartUpdate
         * @description 更新备件请求
         */
        SparePartUpdate: {
            /**
             * Code
             * @description 备件编码
             */
            code?: string | null;
            /**
             * Name
             * @description 备件名称
             */
            name?: string | null;
            /**
             * Specification
             * @description 规格型号
             */
            specification?: string | null;
            /**
             * Unit
             * @description 计量单位
             */
            unit?: string | null;
            /**
             * Category
             * @description 备件分类
             */
            category?: string | null;
            /**
             * Default Supplier
             * @description 默认供应商
             */
            default_supplier?: string | null;
            /**
             * Unit Price
             * @description 参考单价
             */
            unit_price?: number | null;
            /**
             * Is Active
             * @description 是否启用
             */
            is_active?: boolean | null;
        };
        /**
         * StockAdjustRequest
         * @description 盘点调整请求
         */
        StockAdjustRequest: {
            /**
             * New Qty
             * @description 调整后数量
             */
            new_qty: number;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /**
         * StockInboundRequest
         * @description 入库请求
         */
        StockInboundRequest: {
            /**
             * Quantity
             * @description 入库数量
             */
            quantity: number;
            /**
             * Warehouse Location
             * @description 库位
             */
            warehouse_location?: string | null;
            /**
             * Remark
             * @description 备注
             */
            remark?: string | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /**
         * WorkOrderAssign
         * @description 指派工单请求
         */
        WorkOrderAssign: {
            /**
             * Assignee Id
             * Format: uuid
             * @description 维修人ID
             */
            assignee_id: string;
        };
        /**
         * WorkOrderComplete
         * @description 完成工单请求
         */
        WorkOrderComplete: {
            /**
             * Repair Detail
             * @description 维修过程描述
             */
            repair_detail: string;
        };
        /**
         * WorkOrderCreate
         * @description 创建工单请求
         */
        WorkOrderCreate: {
            /**
             * Equipment Id
             * Format: uuid
             * @description 设备ID
             */
            equipment_id: string;
            /**
             * Order Type
             * @description 工单类型
             * @default 故障维修
             * @enum {string}
             */
            order_type: "故障维修" | "计划维护" | "巡检" | "校准";
            /**
             * Priority
             * @description 优先级
             * @default 中
             * @enum {string}
             */
            priority: "紧急" | "高" | "中" | "低";
            /**
             * Fault Symptom Id
             * @description 故障现象ID
             */
            fault_symptom_id?: string | null;
            /**
             * Fault Cause Id
             * @description 故障原因ID
             */
            fault_cause_id?: string | null;
            /**
             * Fault Action Id
             * @description 维修措施ID
             */
            fault_action_id?: string | null;
            /**
             * Fault Description
             * @description 故障详细描述
             */
            fault_description?: string | null;
            /**
             * Maintenance Plan Id
             * @description 关联维护计划ID
             */
            maintenance_plan_id?: string | null;
            /**
             * Planned Start Date
             * @description 计划执行日期
             */
            planned_start_date?: string | null;
            /**
             * Checklist Template Id
             * @description 关联巡检模板ID
             */
            checklist_template_id?: string | null;
        };
        /**
         * WorkOrderVerify
         * @description 验收工单请求
         */
        WorkOrderVerify: {
            /**
             * Result
             * @description 验收结果
             * @enum {string}
             */
            result: "合格" | "不合格";
            /**
             * Remark
             * @description 验收备注
             */
            remark?: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_modules_api_v1_system_modules_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    }[];
                };
            };
        };
    };
    read_module_api_v1_production__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_equipment__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    get_equipment_categories_api_v1_equipment_categories_get: {
        parameters: {
            query?: {
                /** @description 父分类ID */
                parent_id?: string | null;
                /** @description 是否返回树形结构 */
                tree?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_equipment_category_api_v1_equipment_categories_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EquipmentCategoryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_equipment_category_api_v1_equipment_categories__category_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                category_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_equipment_category_api_v1_equipment_categories__category_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                category_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EquipmentCategoryUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_equipment_category_api_v1_equipment_categories__category_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                category_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_locations_api_v1_equipment_locations_get: {
        parameters: {
            query?: {
                /** @description 父位置ID */
                parent_id?: string | null;
                /** @description 是否返回树形结构 */
                tree?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_location_api_v1_equipment_locations_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_location_api_v1_equipment_locations__location_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_location_api_v1_equipment_locations__location_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                location_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LocationUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_location_api_v1_equipment_locations__location_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                location_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_equipments_api_v1_equipment_equipments_get: {
        parameters: {
            query?: {
                /** @description 设备分类ID */
                category_id?: string | null;
                /** @description 设备位置ID */
                location_id?: string | null;
                /** @description 设备状态 */
                status?: string | null;
                /** @description 关键词搜索 */
                keyword?: string | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_equipment_api_v1_equipment_equipments_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EquipmentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_equipment_statistics_api_v1_equipment_equipments_statistics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_equipment_api_v1_equipment_equipments__equipment_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                equipment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_equipment_api_v1_equipment_equipments__equipment_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                equipment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EquipmentUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_equipment_api_v1_equipment_equipments__equipment_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                equipment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_spare_parts_api_v1_equipment_spare_parts__get: {
        parameters: {
            query?: {
                /** @description 备件分类 */
                category?: string | null;
                /** @description 关键词搜索 */
                keyword?: string | null;
                /** @description 是否启用 */
                is_active?: boolean | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_spare_part_api_v1_equipment_spare_parts__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SparePartCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_stock_warnings_api_v1_equipment_spare_parts_stock_warnings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_spare_part_api_v1_equipment_spare_parts__spare_part_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                spare_part_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_spare_part_api_v1_equipment_spare_parts__spare_part_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                spare_part_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SparePartUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_spare_part_api_v1_equipment_spare_parts__spare_part_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                spare_part_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_stock_api_v1_equipment_spare_parts__spare_part_id__stock_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                spare_part_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    inbound_stock_api_v1_equipment_spare_parts__spare_part_id__stock_inbound_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                spare_part_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StockInboundRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    adjust_stock_api_v1_equipment_spare_parts__spare_part_id__stock_adjust_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                spare_part_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StockAdjustRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_codes_api_v1_equipment_maintenance_failure_codes_symptoms_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    create_api_v1_equipment_maintenance_failure_codes_symptoms_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FailureCodeCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_one_api_v1_equipment_maintenance_failure_codes_symptoms__code_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_api_v1_equipment_maintenance_failure_codes_symptoms__code_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FailureCodeUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_v1_equipment_maintenance_failure_codes_symptoms__code_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_codes_api_v1_equipment_maintenance_failure_codes_causes_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    create_api_v1_equipment_maintenance_failure_codes_causes_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FailureCodeCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_one_api_v1_equipment_maintenance_failure_codes_causes__code_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_api_v1_equipment_maintenance_failure_codes_causes__code_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FailureCodeUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_v1_equipment_maintenance_failure_codes_causes__code_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_codes_api_v1_equipment_maintenance_failure_codes_actions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    create_api_v1_equipment_maintenance_failure_codes_actions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FailureCodeCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_one_api_v1_equipment_maintenance_failure_codes_actions__code_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_api_v1_equipment_maintenance_failure_codes_actions__code_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FailureCodeUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_api_v1_equipment_maintenance_failure_codes_actions__code_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_work_orders_api_v1_equipment_maintenance_work_orders__get: {
        parameters: {
            query?: {
                /** @description 工单状态 */
                status?: string | null;
                /** @description 设备ID */
                equipment_id?: string | null;
                /** @description 优先级 */
                priority?: string | null;
                /** @description 工单类型 */
                order_type?: string | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_work_order_api_v1_equipment_maintenance_work_orders__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkOrderCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_work_order_statistics_api_v1_equipment_maintenance_work_orders_statistics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assign_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__assign_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkOrderAssign"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__start_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    complete_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__complete_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkOrderComplete"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__verify_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkOrderVerify"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    close_work_order_api_v1_equipment_maintenance_work_orders__work_order_id__close_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_material_consumptions_api_v1_equipment_maintenance_work_orders__work_order_id__materials_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    consume_materials_api_v1_equipment_maintenance_work_orders__work_order_id__materials_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaterialConsumeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_calibration_plans_api_v1_equipment_maintenance_calibration_plans_get: {
        parameters: {
            query?: {
                /** @description 设备ID */
                equipment_id?: string | null;
                /** @description 状态 */
                status?: string | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_calibration_plan_api_v1_equipment_maintenance_calibration_plans_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalibrationPlanCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_overdue_plans_api_v1_equipment_maintenance_calibration_plans_overdue_get: {
        parameters: {
            query?: {
                /** @description 提前天数 */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_calibration_plan_api_v1_equipment_maintenance_calibration_plans__plan_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_calibration_plan_api_v1_equipment_maintenance_calibration_plans__plan_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalibrationPlanUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_calibration_plan_api_v1_equipment_maintenance_calibration_plans__plan_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_calibration_records_api_v1_equipment_maintenance_calibration_records_get: {
        parameters: {
            query?: {
                /** @description 设备ID */
                equipment_id?: string | null;
                /** @description 计划ID */
                plan_id?: string | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_calibration_record_api_v1_equipment_maintenance_calibration_records_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalibrationRecordCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_calibration_record_api_v1_equipment_maintenance_calibration_records__record_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                record_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_maintenance_plans_api_v1_equipment_maintenance_plans__get: {
        parameters: {
            query?: {
                /** @description 设备ID */
                equipment_id?: string | null;
                /** @description 状态 */
                status?: string | null;
                /** @description 关键词搜索 */
                keyword?: string | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_maintenance_plan_api_v1_equipment_maintenance_plans__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaintenancePlanCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_overdue_plans_api_v1_equipment_maintenance_plans_overdue_get: {
        parameters: {
            query?: {
                /** @description 提前天数 */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_maintenance_plan_api_v1_equipment_maintenance_plans__plan_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_maintenance_plan_api_v1_equipment_maintenance_plans__plan_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaintenancePlanUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_maintenance_plan_api_v1_equipment_maintenance_plans__plan_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_inspection_templates_api_v1_equipment_maintenance_inspection_templates__get: {
        parameters: {
            query?: {
                /** @description 设备分类ID */
                equipment_category_id?: string | null;
                /** @description 是否启用 */
                is_active?: boolean | null;
                /** @description 关键词搜索 */
                keyword?: string | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页数量 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_inspection_template_api_v1_equipment_maintenance_inspection_templates__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InspectionTemplateCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_inspection_template_api_v1_equipment_maintenance_inspection_templates__template_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_inspection_template_api_v1_equipment_maintenance_inspection_templates__template_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InspectionTemplateUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_inspection_template_api_v1_equipment_maintenance_inspection_templates__template_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_template_item_api_v1_equipment_maintenance_inspection_templates__template_id__items_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InspectionTemplateItemCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_template_item_api_v1_equipment_maintenance_inspection_templates_items__item_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InspectionTemplateItemUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_template_item_api_v1_equipment_maintenance_inspection_templates_items__item_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    complete_inspection_api_v1_equipment_maintenance_inspection_templates_complete__work_order_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                work_order_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InspectionCompleteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_module_api_v1_safety__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_environment__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_energy__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    list_device_configs_api_v1_energy_devices_get: {
        parameters: {
            query?: {
                /** @description 平台标识 */
                platform_code?: string | null;
                /** @description 能源类型 */
                energy_type?: string | null;
                /** @description 车间 */
                workshop?: string | null;
                /** @description 是否启用 */
                is_enabled?: boolean | null;
                /** @description 页码 */
                page?: number;
                /** @description 每页条数 */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_device_config_api_v1_energy_devices_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EnergyDeviceConfigCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_device_config_api_v1_energy_devices__config_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                config_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_device_config_api_v1_energy_devices__config_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                config_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EnergyDeviceConfigUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_device_config_api_v1_energy_devices__config_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                config_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_energy_data_api_v1_energy_data_get: {
        parameters: {
            query: {
                /** @description 设备配置ID */
                device_config_id?: string | null;
                /** @description 能源类型 */
                energy_type?: string | null;
                /** @description 车间 */
                workshop?: string | null;
                /** @description 开始时间(ISO格式) */
                start_time: string;
                /** @description 结束时间(ISO格式) */
                end_time: string;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_energy_statistics_api_v1_energy_data_statistics_get: {
        parameters: {
            query: {
                /** @description 分组维度: workshop/production_line/device */
                group_by?: string;
                /** @description 能源类型 */
                energy_type?: string | null;
                /** @description 开始时间(ISO格式) */
                start_time: string;
                /** @description 结束时间(ISO格式) */
                end_time: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    trigger_collection_api_v1_energy_collect_trigger_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CollectTriggerRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_collect_logs_api_v1_energy_collect_logs_get: {
        parameters: {
            query?: {
                /** @description 平台标识 */
                platform_code?: string | null;
                /** @description 状态 */
                status?: string | null;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_module_api_v1_warehouse__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_procurement__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_administration__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_hr__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_research__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_registration__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    read_module_api_v1_quality__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
}
