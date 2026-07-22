from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleDefinition:
    code: str
    name: str
    path: str
    db_schema: str
    owner_hint: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "name": self.name,
            "path": self.path,
            "db_schema": self.db_schema,
            "owner_hint": self.owner_hint,
            "description": self.description,
        }


BUSINESS_MODULES: tuple[ModuleDefinition, ...] = (
    ModuleDefinition(
        code="production",
        name="生产管理",
        path="/production",
        db_schema="production",
        owner_hint="生产技术/车间工艺负责人",
        description="批次、工序、产量、生产过程记录等生产侧数据入口。",
    ),
    ModuleDefinition(
        code="equipment",
        name="设备管理",
        path="/equipment",
        db_schema="equipment",
        owner_hint="设备工程/维修负责人",
        description="设备台账、保养、维修、巡检和备件关联数据入口。",
    ),
    ModuleDefinition(
        code="safety",
        name="安全管理",
        path="/safety",
        db_schema="safety",
        owner_hint="安全管理负责人",
        description="隐患、作业票、风险点、培训和安全检查数据入口。",
    ),
    ModuleDefinition(
        code="environment",
        name="环保管理",
        path="/environment",
        db_schema="environment",
        owner_hint="环保管理负责人",
        description="三废、监测、排放、环保设施运行和台账数据入口。",
    ),
    ModuleDefinition(
        code="energy",
        name="能源管理",
        path="/energy",
        db_schema="energy",
        owner_hint="能源/动力负责人",
        description="水、电、汽、冷量、能耗统计和能源指标数据入口。",
    ),
    ModuleDefinition(
        code="warehouse",
        name="仓储管理",
        path="/warehouse",
        db_schema="warehouse",
        owner_hint="仓储/物流负责人",
        description="原辅料、包材、中间体、成品库存和出入库数据入口。",
    ),
    ModuleDefinition(
        code="procurement",
        name="采购管理",
        path="/procurement",
        db_schema="procurement",
        owner_hint="采购负责人",
        description="采购需求、供应商、询价、订单和到货协同数据入口。",
    ),
    ModuleDefinition(
        code="administration",
        name="行政管理",
        path="/administration",
        db_schema="administration",
        owner_hint="行政负责人",
        description="行政事务、资产、后勤和公共服务事项数据入口。",
    ),
    ModuleDefinition(
        code="hr",
        name="人事管理",
        path="/hr",
        db_schema="hr",
        owner_hint="人事负责人",
        description="人员、岗位、培训、考勤等人事业务数据入口。",
    ),
    ModuleDefinition(
        code="research",
        name="研发管理",
        path="/research",
        db_schema="research",
        owner_hint="研发负责人",
        description="研发项目、试验批、处方工艺和研发记录数据入口。",
    ),
    ModuleDefinition(
        code="registration",
        name="注册管理",
        path="/registration",
        db_schema="registration",
        owner_hint="注册事务负责人",
        description="注册资料、申报进度、变更事项和法规跟踪数据入口。",
    ),
    ModuleDefinition(
        code="quality",
        name="质量管理",
        path="/quality",
        db_schema="quality",
        owner_hint="QA/QC 负责人",
        description="偏差、CAPA、检验、放行、变更和质量体系数据入口。",
    ),
    ModuleDefinition(
        code="meter",
        name="仪表管理",
        path="/meter",
        db_schema="meter",
        owner_hint="仪表/计量负责人",
        description="计量器具台账、有毒有害可燃探测器、检测报告和检定到期提醒。",
    ),
)

MODULES_BY_CODE = {module.code: module for module in BUSINESS_MODULES}
BUSINESS_SCHEMAS = tuple(module.db_schema for module in BUSINESS_MODULES)
