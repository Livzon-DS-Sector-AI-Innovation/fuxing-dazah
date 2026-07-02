// ============ Enums ============

export enum CheckType {
  DAILY = 'daily',
  SPECIAL = 'special',
  COMPREHENSIVE = 'comprehensive',
  HOLIDAY = 'holiday',
  MONTHLY = 'monthly',
  SEASONAL = 'seasonal',
  PRE_HOLIDAY = 'pre_holiday',
  LEADERSHIP_DUTY = 'leadership_duty',
  DEPT_CROSS = 'dept_cross',
  WEEKLY = 'weekly',
  RESUMPTION = 'resumption',
  CHANGE_ACCEPTANCE = 'change_acceptance',
  LIGHTNING = 'lightning',
  SAFETY_VALVE = 'safety_valve',
  POST_HOLIDAY = 'post_holiday',
  HEATSTROKE_PREVENTION = 'heatstroke_prevention',
}

export const CHECK_TYPE_OPTIONS = [
  { value: CheckType.DAILY, label: '日常检查', color: 'blue' },
  { value: CheckType.SPECIAL, label: '专项检查', color: 'orange' },
  { value: CheckType.COMPREHENSIVE, label: '综合检查', color: 'purple' },
  { value: CheckType.HOLIDAY, label: '节假日检查', color: 'red' },
  { value: CheckType.MONTHLY, label: '月度安全检查', color: 'blue' },
  { value: CheckType.SEASONAL, label: '季节性安全检查', color: 'cyan' },
  { value: CheckType.PRE_HOLIDAY, label: '节前安全检查', color: 'orange' },
  { value: CheckType.LEADERSHIP_DUTY, label: '领导干部值班检查', color: 'gold' },
  { value: CheckType.DEPT_CROSS, label: '部门互查', color: 'green' },
  { value: CheckType.WEEKLY, label: '周检', color: 'blue' },
  { value: CheckType.RESUMPTION, label: '复工复产安全检查', color: 'orange' },
  { value: CheckType.CHANGE_ACCEPTANCE, label: '变更验收', color: 'purple' },
  { value: CheckType.LIGHTNING, label: '防雷检查', color: 'yellow' },
  { value: CheckType.SAFETY_VALVE, label: '安全阀专项检查', color: 'red' },
  { value: CheckType.POST_HOLIDAY, label: '节后复工检查', color: 'orange' },
  { value: CheckType.HEATSTROKE_PREVENTION, label: '防暑降温专项', color: 'volcano' },
]

export enum HazardType {
  UNSAFE_CONDITION = 'unsafe_condition',
  UNSAFE_ACTION = 'unsafe_action',
  MANAGEMENT_DEFECT = 'management_defect',
  ENVIRONMENTAL = 'environmental',
}

export const HAZARD_TYPE_OPTIONS = [
  { value: HazardType.UNSAFE_ACTION, label: '人的不安全行为', color: 'red' },
  { value: HazardType.UNSAFE_CONDITION, label: '物的不安全状态', color: 'orange' },
  { value: HazardType.ENVIRONMENTAL, label: '环境的不安全因素', color: 'blue' },
  { value: HazardType.MANAGEMENT_DEFECT, label: '管理的缺陷', color: 'purple' },
]

export enum HazardLevel {
  GENERAL = 'general',
  SERIOUS = 'serious',
  MAJOR = 'major',
}

export const HAZARD_LEVEL_OPTIONS = [
  { value: HazardLevel.GENERAL, label: '一般隐患', color: 'blue' },
  { value: HazardLevel.SERIOUS, label: '较大隐患', color: 'orange' },
  { value: HazardLevel.MAJOR, label: '重大隐患', color: 'red' },
]

export enum HazardCategory {
  EQUIPMENT = 'equipment',
  HAZARDOUS_STORAGE = 'hazardous_storage',
  EMERGENCY_MGMT = 'emergency_mgmt',
  INSTRUMENT_ELECTRICAL = 'instrument_electrical',
  LIGHTNING_ANTISTATIC = 'lightning_antistatic',
  OCCUPATIONAL_HEALTH = 'occupational_health',
  VIOLATION_OPERATION = 'violation_operation',
  SIX_S = 'six_s',
  LABEL_SIGNAGE = 'label_signage',
  PROCESS_MGMT = 'process_mgmt',
  CONTRACTOR_DEFECT = 'contractor_defect',
  DOCUMENTATION = 'documentation',
  SPECIAL_OPERATION = 'special_operation',
}

export const HAZARD_CATEGORY_OPTIONS = [
  { value: HazardCategory.EQUIPMENT, label: '设备设施' },
  { value: HazardCategory.HAZARDOUS_STORAGE, label: '危化储存' },
  { value: HazardCategory.EMERGENCY_MGMT, label: '应急管理' },
  { value: HazardCategory.INSTRUMENT_ELECTRICAL, label: '仪表+电气' },
  { value: HazardCategory.LIGHTNING_ANTISTATIC, label: '防雷防静电' },
  { value: HazardCategory.OCCUPATIONAL_HEALTH, label: '职业健康+劳保防护' },
  { value: HazardCategory.VIOLATION_OPERATION, label: '三违作业' },
  { value: HazardCategory.SIX_S, label: '6S' },
  { value: HazardCategory.LABEL_SIGNAGE, label: '标签标识' },
  { value: HazardCategory.PROCESS_MGMT, label: '工艺管理' },
  { value: HazardCategory.CONTRACTOR_DEFECT, label: '承包商缺陷' },
  { value: HazardCategory.DOCUMENTATION, label: '内页资料' },
  { value: HazardCategory.SPECIAL_OPERATION, label: '特殊作业' },
]

// ============ Special Operations Enums ============

export enum SpecialOperationType {
  HOT_WORK = 'hot_work',
  CONFINED_SPACE = 'confined_space',
  BLIND_PLATE = 'blind_plate',
  HEIGHT_WORK = 'height_work',
  LIFTING = 'lifting',
  TEMPORARY_ELECTRICITY = 'temporary_electricity',
  EXCAVATION = 'excavation',
  ROAD_BREAKING = 'road_breaking',
}

export const OPERATION_TYPE_OPTIONS = [
  { value: SpecialOperationType.HOT_WORK, label: '动火作业', color: 'red' },
  { value: SpecialOperationType.CONFINED_SPACE, label: '受限空间作业', color: 'red' },
  { value: SpecialOperationType.BLIND_PLATE, label: '盲板抽堵作业', color: 'orange' },
  { value: SpecialOperationType.HEIGHT_WORK, label: '高处作业', color: 'red' },
  { value: SpecialOperationType.LIFTING, label: '吊装作业', color: 'orange' },
  { value: SpecialOperationType.TEMPORARY_ELECTRICITY, label: '临时用电作业', color: 'blue' },
  { value: SpecialOperationType.EXCAVATION, label: '动土作业', color: 'orange' },
  { value: SpecialOperationType.ROAD_BREAKING, label: '断路作业', color: 'blue' },
]

export enum OperationLevel {
  SPECIAL = 'special',
  GRADE1 = 'grade1',
  GRADE2 = 'grade2',
}

export const OPERATION_LEVEL_OPTIONS = [
  { value: OperationLevel.SPECIAL, label: '特级', color: 'red' },
  { value: OperationLevel.GRADE1, label: '一级', color: 'orange' },
  { value: OperationLevel.GRADE2, label: '二级', color: 'blue' },
]

export enum PersonnelStatus {
  ACTIVE = 'active',
  EXPIRED = 'expired',
  REVOKED = 'revoked',
}

export const PERSONNEL_STATUS_OPTIONS = [
  { value: PersonnelStatus.ACTIVE, label: '有效', color: 'green' },
  { value: PersonnelStatus.EXPIRED, label: '已过期', color: 'orange' },
  { value: PersonnelStatus.REVOKED, label: '已撤销', color: 'red' },
]

export enum PermitStatus {
  DRAFT = 'draft',
  SUBMITTED = 'submitted',
  APPROVED = 'approved',
  REJECTED = 'rejected',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  ARCHIVED = 'archived',
}

export const PERMIT_STATUS_OPTIONS = [
  { value: PermitStatus.DRAFT, label: '草稿', color: 'default' },
  { value: PermitStatus.SUBMITTED, label: '已提交', color: 'blue' },
  { value: PermitStatus.APPROVED, label: '已审批', color: 'green' },
  { value: PermitStatus.REJECTED, label: '已驳回', color: 'red' },
  { value: PermitStatus.IN_PROGRESS, label: '作业中', color: 'orange' },
  { value: PermitStatus.COMPLETED, label: '已完工', color: 'cyan' },
  { value: PermitStatus.ARCHIVED, label: '已归档', color: 'default' },
]

export enum CompletionMethod {
  NORMAL = 'normal',
  EARLY_TERMINATION = 'early_termination',
}

export const COMPLETION_METHOD_OPTIONS = [
  { value: CompletionMethod.NORMAL, label: '正常完工' },
  { value: CompletionMethod.EARLY_TERMINATION, label: '提前终止' },
]

export enum KnowledgeCategory {
  LAWS_REGULATIONS = 'laws_regulations',
  STANDARDS = 'standards',
  MANAGEMENT_SYSTEMS = 'management_systems',
  ACCIDENT_CASES = 'accident_cases',
  EMERGENCY_PLANS = 'emergency_plans',
  SDS = 'sds',
  TRAINING_MATERIALS = 'training_materials',
  OTHER = 'other',
}

export const KNOWLEDGE_CATEGORY_OPTIONS = [
  { value: KnowledgeCategory.LAWS_REGULATIONS, label: '法律法规' },
  { value: KnowledgeCategory.STANDARDS, label: '标准规范' },
  { value: KnowledgeCategory.MANAGEMENT_SYSTEMS, label: '安全管理制度' },
  { value: KnowledgeCategory.ACCIDENT_CASES, label: '事故案例' },
  { value: KnowledgeCategory.EMERGENCY_PLANS, label: '应急预案' },
  { value: KnowledgeCategory.SDS, label: 'SDS/MSDS' },
  { value: KnowledgeCategory.TRAINING_MATERIALS, label: '培训资料' },
  { value: KnowledgeCategory.OTHER, label: '其他' },
]

export enum AccidentType {
  INJURY = 'injury',
  FIRE = 'fire',
  EXPLOSION = 'explosion',
  LEAKAGE = 'leakage',
  EQUIPMENT = 'equipment',
  NEAR_MISS = 'near_miss',
  ENVIRONMENTAL = 'environmental',
  OCCUPATIONAL_DISEASE = 'occupational_disease',
  TRAFFIC = 'traffic',
  OTHER = 'other',
}

export const ACCIDENT_TYPE_OPTIONS = [
  { value: AccidentType.INJURY, label: '工伤事故' },
  { value: AccidentType.FIRE, label: '火灾' },
  { value: AccidentType.EXPLOSION, label: '爆炸' },
  { value: AccidentType.LEAKAGE, label: '泄漏' },
  { value: AccidentType.EQUIPMENT, label: '设备事故' },
  { value: AccidentType.NEAR_MISS, label: '未遂事件' },
  { value: AccidentType.ENVIRONMENTAL, label: '环境事件' },
  { value: AccidentType.OCCUPATIONAL_DISEASE, label: '职业病' },
  { value: AccidentType.TRAFFIC, label: '交通事故' },
  { value: AccidentType.OTHER, label: '其他' },
]

export enum AccidentLevel {
  GENERAL = 'general',
  SERIOUS = 'serious',
  MAJOR = 'major',
  CATASTROPHIC = 'catastrophic',
}

export const ACCIDENT_LEVEL_OPTIONS = [
  { value: AccidentLevel.GENERAL, label: '一般事故', color: 'blue' },
  { value: AccidentLevel.SERIOUS, label: '较大事故', color: 'orange' },
  { value: AccidentLevel.MAJOR, label: '重大事故', color: 'red' },
  { value: AccidentLevel.CATASTROPHIC, label: '特别重大事故', color: 'magenta' },
]

export enum AccidentStatus {
  REPORTED = 'reported',
  INVESTIGATING = 'investigating',
  INVESTIGATED = 'investigated',
  CAPA_IN_PROGRESS = 'capa_in_progress',
  CLOSED = 'closed',
}

export const ACCIDENT_STATUS_OPTIONS = [
  { value: AccidentStatus.REPORTED, label: '已报告', color: 'blue' },
  { value: AccidentStatus.INVESTIGATING, label: '调查中', color: 'orange' },
  { value: AccidentStatus.INVESTIGATED, label: '调查完成', color: 'cyan' },
  { value: AccidentStatus.CAPA_IN_PROGRESS, label: 'CAPA进行中', color: 'purple' },
  { value: AccidentStatus.CLOSED, label: '已关闭', color: 'green' },
]

export enum InjurySeverity {
  DEATH = 'death',
  SERIOUS_INJURY = 'serious_injury',
  MINOR_INJURY = 'minor_injury',
  NO_INJURY = 'no_injury',
}

export const INJURY_SEVERITY_OPTIONS = [
  { value: InjurySeverity.DEATH, label: '死亡', color: 'red' },
  { value: InjurySeverity.SERIOUS_INJURY, label: '重伤', color: 'orange' },
  { value: InjurySeverity.MINOR_INJURY, label: '轻伤', color: 'yellow' },
  { value: InjurySeverity.NO_INJURY, label: '无伤害', color: 'green' },
]

// ============ Contractor Enums ============

export enum ContractorStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
  BLACKLISTED = 'blacklisted',
}

export const CONTRACTOR_STATUS_OPTIONS = [
  { value: ContractorStatus.ACTIVE, label: '活跃', color: 'green' },
  { value: ContractorStatus.INACTIVE, label: '停用', color: 'default' },
  { value: ContractorStatus.BLACKLISTED, label: '黑名单', color: 'red' },
]

export enum QualificationTypeEnum {
  CONSTRUCTION = 'construction',
  INSTALLATION = 'installation',
  MAINTENANCE = 'maintenance',
  CLEANING = 'cleaning',
  SECURITY = 'security',
  OTHER = 'other',
}

export const QUALIFICATION_TYPE_OPTIONS = [
  { value: QualificationTypeEnum.CONSTRUCTION, label: '建筑施工' },
  { value: QualificationTypeEnum.INSTALLATION, label: '设备安装' },
  { value: QualificationTypeEnum.MAINTENANCE, label: '检维修' },
  { value: QualificationTypeEnum.CLEANING, label: '保洁' },
  { value: QualificationTypeEnum.SECURITY, label: '安保' },
  { value: QualificationTypeEnum.OTHER, label: '其他' },
]

export enum QualificationLevelEnum {
  GRADE_A = 'grade_a',
  GRADE_B = 'grade_b',
  GRADE_C = 'grade_c',
}

export const QUALIFICATION_LEVEL_OPTIONS = [
  { value: QualificationLevelEnum.GRADE_A, label: '甲级/一级' },
  { value: QualificationLevelEnum.GRADE_B, label: '乙级/二级' },
  { value: QualificationLevelEnum.GRADE_C, label: '丙级/三级' },
]

export enum ContractorTrainingStatusEnum {
  UNTRAINED = 'untrained',
  IN_PROGRESS = 'in_progress',
  PASSED = 'passed',
  EXPIRED = 'expired',
}

export const CONTRACTOR_TRAINING_STATUS_OPTIONS = [
  { value: ContractorTrainingStatusEnum.UNTRAINED, label: '未培训', color: 'default' },
  { value: ContractorTrainingStatusEnum.IN_PROGRESS, label: '培训中', color: 'processing' },
  { value: ContractorTrainingStatusEnum.PASSED, label: '已通过', color: 'green' },
  { value: ContractorTrainingStatusEnum.EXPIRED, label: '已过期', color: 'red' },
]

export enum WorkRecordStatusEnum {
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  EVALUATED = 'evaluated',
}

export const WORK_RECORD_STATUS_OPTIONS = [
  { value: WorkRecordStatusEnum.IN_PROGRESS, label: '施工中', color: 'processing' },
  { value: WorkRecordStatusEnum.COMPLETED, label: '已完成', color: 'green' },
  { value: WorkRecordStatusEnum.EVALUATED, label: '已评价', color: 'blue' },
]

export enum TrainingType {
  INDUCTION = 'induction',
  ANNUAL = 'annual',
  SPECIAL = 'special',
  EMERGENCY = 'emergency',
  CONTRACTOR = 'contractor',
  REFRESHER = 'refresher',
}

export const TRAINING_TYPE_OPTIONS = [
  { value: TrainingType.INDUCTION, label: '入职培训' },
  { value: TrainingType.ANNUAL, label: '年度培训' },
  { value: TrainingType.SPECIAL, label: '专项培训' },
  { value: TrainingType.EMERGENCY, label: '应急培训' },
  { value: TrainingType.CONTRACTOR, label: '承包商培训' },
  { value: TrainingType.REFRESHER, label: '复训' },
]

export enum TrainingMode {
  ONLINE = 'online',
  OFFLINE = 'offline',
  BLENDED = 'blended',
}

export const TRAINING_MODE_OPTIONS = [
  { value: TrainingMode.ONLINE, label: '线上' },
  { value: TrainingMode.OFFLINE, label: '线下' },
  { value: TrainingMode.BLENDED, label: '混合' },
]

export enum TrainingLevel {
  COMPANY = 'company',
  DEPT = 'dept',
  TEAM = 'team',
}

export const TRAINING_LEVEL_OPTIONS = [
  { value: TrainingLevel.COMPANY, label: '公司级' },
  { value: TrainingLevel.DEPT, label: '部门级' },
  { value: TrainingLevel.TEAM, label: '班组级' },
]

export enum CertificateStatus {
  VALID = 'valid',
  EXPIRING = 'expiring',
  EXPIRED = 'expired',
}

export const CERTIFICATE_STATUS_OPTIONS = [
  { value: CertificateStatus.VALID, label: '有效', color: 'success' },
  { value: CertificateStatus.EXPIRING, label: '即将到期', color: 'warning' },
  { value: CertificateStatus.EXPIRED, label: '已过期', color: 'error' },
]

// ── 检查类别（隐患台账 Bitable 多选字段 16 种预设）──
export const INSPECTION_CATEGORY_OPTIONS = [
  { value: '月度安全检查', label: '月度安全检查' },
  { value: '节前安全检查', label: '节前安全检查' },
  { value: '专项安全检查', label: '专项安全检查' },
  { value: '领导干部值班检查', label: '领导干部值班检查' },
  { value: '部门安全检查', label: '部门安全检查' },
  { value: '季节性安全检查', label: '季节性安全检查' },
  { value: '周检', label: '周检' },
  { value: '复工复产安全检查', label: '复工复产安全检查' },
  { value: '部门互查', label: '部门互查' },
  { value: '变更验收', label: '变更验收' },
  { value: '防雷检查', label: '防雷检查' },
  { value: '安全阀专项检查', label: '安全阀专项检查' },
  { value: '节后复工检查', label: '节后复工检查' },
  { value: '防暑降温专项', label: '防暑降温专项' },
  { value: '电气专项检查', label: '电气专项检查' },
  { value: '关键风险作业专项检查', label: '关键风险作业专项检查' },
]

// ── 责任部门（Bitable「责任部门」SingleSelect 27个预设选项，与后端 DEPARTMENT_CONFIG 对齐）──
export const DEPARTMENT_OPTIONS = [
  { value: '合规监察部', label: '合规监察部' },
  { value: '生产管理部', label: '生产管理部' },
  { value: '仓储部', label: '仓储部' },
  { value: '菌种中心', label: '菌种中心' },
  { value: '设备工程部', label: '设备工程部' },
  { value: '动力部', label: '动力部' },
  { value: '发酵工程部', label: '发酵工程部' },
  { value: '提炼工程一部', label: '提炼工程一部' },
  { value: '提炼工程三部', label: '提炼工程三部' },
  { value: '提炼工程二部', label: '提炼工程二部' },
  { value: '精制工程一部', label: '精制工程一部' },
  { value: '提炼工程四部', label: '提炼工程四部' },
  { value: '提炼工程五部', label: '提炼工程五部' },
  { value: '提炼工程六部', label: '提炼工程六部' },
  { value: '提炼技术精进中心', label: '提炼技术精进中心' },
  { value: '质量控制部（QC部）', label: '质量控制部（QC部）' },
  { value: '质量保证部（QA部）', label: '质量保证部（QA部）' },
  { value: '法规注册部（RA部）', label: '法规注册部（RA部）' },
  { value: '环保工程中心', label: '环保工程中心' },
  { value: '安全工程中心', label: '安全工程中心' },
  { value: 'AI创新部', label: 'AI创新部' },
  { value: '发酵工程中心', label: '发酵工程中心' },
  { value: '提炼半合成工程中心', label: '提炼半合成工程中心' },
  { value: '人力资源部', label: '人力资源部' },
  { value: '行政后勤部', label: '行政后勤部' },
  { value: '采购部', label: '采购部' },
  { value: '财务部', label: '财务部' },
]

// ── 检查人员部门（Bitable「检查人员.部门」MultiSelect 60个预设选项）──
export const INSPECTOR_DEPARTMENT_OPTIONS = [
  { value: 'EHS部', label: 'EHS部' },
  { value: '环保工程中心', label: '环保工程中心' },
  { value: '设备工程部', label: '设备工程部' },
  { value: '行政后勤部', label: '行政后勤部' },
  { value: '安全工程中心', label: '安全工程中心' },
  { value: '精制工程一部', label: '精制工程一部' },
  { value: '法规注册部', label: '法规注册部' },
  { value: '菌种中心', label: '菌种中心' },
  { value: '提炼工程一部', label: '提炼工程一部' },
  { value: '质量保证部（QA部）', label: '质量保证部（QA部）' },
  { value: '提炼半合成工程中心', label: '提炼半合成工程中心' },
  { value: '财务部', label: '财务部' },
  { value: '发酵工程中心', label: '发酵工程中心' },
  { value: '提炼工程六部', label: '提炼工程六部' },
  { value: '提炼工程五部', label: '提炼工程五部' },
  { value: '发酵工程部', label: '发酵工程部' },
  { value: '人力资源部', label: '人力资源部' },
  { value: '现场QA', label: '现场QA' },
  { value: '检测组', label: '检测组' },
  { value: '提炼工程二部', label: '提炼工程二部' },
  { value: '仓储部', label: '仓储部' },
  { value: '提炼工程四部', label: '提炼工程四部' },
  { value: '提炼二期', label: '提炼二期' },
  { value: '质量控制部（QC部）', label: '质量控制部（QC部）' },
  { value: '发酵工程二部', label: '发酵工程二部' },
  { value: '仪表班组', label: '仪表班组' },
  { value: '提炼技术精进中心', label: '提炼技术精进中心' },
  { value: '采购部', label: '采购部' },
  { value: '生产部', label: '生产部' },
  { value: '动力部', label: '动力部' },
  { value: '外派财务人员', label: '外派财务人员' },
  { value: '管理层', label: '管理层' },
  { value: '研发组', label: '研发组' },
  { value: '项目部', label: '项目部' },
  { value: '合规监察部', label: '合规监察部' },
  { value: '电工班组', label: '电工班组' },
  { value: '生产管理部', label: '生产管理部' },
  { value: '生产管理中心', label: '生产管理中心' },
  { value: 'AI创新部', label: 'AI创新部' },
]

export const CHECK_RESULT_OPTIONS = [
  { value: 'qualified', label: '合格', color: 'success' },
  { value: 'unqualified', label: '不合格', color: 'error' },
  { value: 'need_rectification', label: '需整改', color: 'warning' },
]

export const RECTIFICATION_STATUS_OPTIONS = [
  { value: 'pending', label: '待整改', color: 'processing' },
  { value: 'in_progress', label: '整改中', color: 'processing' },
  { value: 'replied', label: '待复核', color: 'default' },
  { value: 'ai_reviewing', label: 'AI 初审中', color: 'processing' },
  { value: 'level1_approved', label: '一级已通过', color: 'default' },
  { value: 'level2_approved', label: '二级已通过', color: 'default' },
  { value: 'level3_approved', label: '三级已通过', color: 'default' },
  { value: 'rejected', label: '已驳回', color: 'error' },
  { value: 'closed', label: '已关闭', color: 'default' },
  { value: 'verified', label: '已验证', color: 'default' },
  { value: 'under_review', label: '复核中', color: 'warning' },
  { value: 'completed', label: '已关闭', color: 'success' },
]

export const VERIFY_LEVEL_OPTIONS = [
  { value: 1, label: '部门负责人复核' },
  { value: 2, label: '分管领导复核' },
  { value: 3, label: '检查人员复核' },
]

export const VERIFY_LEVEL_STATUS_OPTIONS = [
  { value: 'pending', label: '待复核', color: 'default' },
  { value: 'approved', label: '已通过', color: 'success' },
  { value: 'rejected', label: '已驳回', color: 'error' },
  { value: 'no_review_needed', label: '无需复核', color: 'default' },
]

export const HAZARD_STATUS_OPTIONS = [
  { value: 'open', label: '待处理', color: 'default' },
  { value: 'closed', label: '已关闭', color: 'success' },
]

export const AI_NODE_PROGRESS_OPTIONS_HAZARD = [
  { value: 'pending_input', label: '待输入', color: 'default' },
  { value: 'pending_script1', label: '待AI识别', color: 'processing' },
  { value: 'pending_script2', label: '待AI整改建议', color: 'processing' },
  { value: 'completed', label: 'AI完成', color: 'success' },
]

export const OVERALL_STATUS_OPTIONS_HAZARD = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'ai_processing', label: 'AI处理中', color: 'processing' },
  { value: 'completed', label: 'AI完成(待审核)', color: 'warning' },
  { value: 'reviewed', label: '已审核', color: 'success' },
  { value: 'cancelled', label: '已取消', color: 'default' },
]

export const HAZARD_SOURCE_OPTIONS = [
  { value: 'ai', label: 'AI识别', color: 'purple' },
  { value: 'manual', label: '人工录入', color: 'default' },
]

export const CHECK_STATUS_OPTIONS = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'submitted', label: '已提交', color: 'blue' },
  { value: 'reviewed', label: '已审核', color: 'success' },
  { value: 'closed', label: '已关闭', color: 'default' },
]

export const TRAINING_STATUS_OPTIONS = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'in_progress', label: '进行中', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
  { value: 'archived', label: '已归档', color: 'default' },
]
