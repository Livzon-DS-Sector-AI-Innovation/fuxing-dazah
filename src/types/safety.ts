// safety module TypeScript types

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  meta?: {
    page?: number
    page_size?: number
    total?: number
  }
}

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
  { value: CheckType.DAILY, label: '日常检查' },
  { value: CheckType.SPECIAL, label: '专项检查' },
  { value: CheckType.COMPREHENSIVE, label: '综合检查' },
  { value: CheckType.HOLIDAY, label: '节假日检查' },
  { value: CheckType.MONTHLY, label: '月度安全检查' },
  { value: CheckType.SEASONAL, label: '季节性安全检查' },
  { value: CheckType.PRE_HOLIDAY, label: '节前安全检查' },
  { value: CheckType.LEADERSHIP_DUTY, label: '领导干部值班检查' },
  { value: CheckType.DEPT_CROSS, label: '部门互查' },
  { value: CheckType.WEEKLY, label: '周检' },
  { value: CheckType.RESUMPTION, label: '复工复产安全检查' },
  { value: CheckType.CHANGE_ACCEPTANCE, label: '变更验收' },
  { value: CheckType.LIGHTNING, label: '防雷检查' },
  { value: CheckType.SAFETY_VALVE, label: '安全阀专项检查' },
  { value: CheckType.POST_HOLIDAY, label: '节后复工检查' },
  { value: CheckType.HEATSTROKE_PREVENTION, label: '防暑降温专项' },
]

export enum HazardType {
  UNSAFE_CONDITION = 'unsafe_condition',
  UNSAFE_ACTION = 'unsafe_action',
  MANAGEMENT_DEFECT = 'management_defect',
  ENVIRONMENTAL = 'environmental',
}

export const HAZARD_TYPE_OPTIONS = [
  { value: HazardType.UNSAFE_ACTION, label: '人的不安全行为' },
  { value: HazardType.UNSAFE_CONDITION, label: '物的不安全状态' },
  { value: HazardType.ENVIRONMENTAL, label: '环境的不安全因素' },
  { value: HazardType.MANAGEMENT_DEFECT, label: '管理的缺陷' },
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

export enum OperationType {
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
  { value: OperationType.HOT_WORK, label: '动火作业' },
  { value: OperationType.CONFINED_SPACE, label: '受限空间作业' },
  { value: OperationType.BLIND_PLATE, label: '盲板抽堵作业' },
  { value: OperationType.HEIGHT_WORK, label: '高处作业' },
  { value: OperationType.LIFTING, label: '吊装作业' },
  { value: OperationType.TEMPORARY_ELECTRICITY, label: '临时用电作业' },
  { value: OperationType.EXCAVATION, label: '动土作业' },
  { value: OperationType.ROAD_BREAKING, label: '断路作业' },
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
  { value: 'pending', label: '整改中', color: 'processing' },
  { value: 'under_review', label: '复核中', color: 'warning' },
  { value: 'completed', label: '已关闭', color: 'success' },
  { value: 'replied', label: '待复核(旧)', color: 'default' },
  { value: 'level1_approved', label: '一级已通过(旧)', color: 'default' },
  { value: 'level2_approved', label: '二级已通过(旧)', color: 'default' },
  { value: 'level3_approved', label: '三级已通过(旧)', color: 'default' },
  { value: 'rejected', label: '已驳回', color: 'error' },
  { value: 'closed', label: '已关闭(旧)', color: 'default' },
  { value: 'verified', label: '已验证(旧)', color: 'default' },
  { value: 'in_progress', label: '整改中(旧)', color: 'default' },
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

// ============ SafetyCheck Types ============

export interface SafetyCheck {
  id: string
  check_no: string
  check_type: CheckType
  check_date: string
  department?: string
  inspector?: string
  inspector_name?: string
  location?: string
  findings?: string
  result?: string
  rectification_required: boolean
  rectification_deadline?: string
  rectification_status?: string
  inspector_confirmed: boolean
  safety_officer_confirmed: boolean
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface SafetyCheckFormData {
  check_no: string
  check_type: CheckType
  check_date: string
  department?: string
  inspector?: string
  inspector_name?: string
  location?: string
  findings?: string
  result?: string
  rectification_required?: boolean
  rectification_deadline?: string
  notes?: string
}

export interface SafetyCheckQueryParams {
  page?: number
  page_size?: number
  status?: string
  check_type?: string
  department?: string
}

// ============ HazardReport Types ============

export interface HazardReport {
  id: string
  hazard_no: string
  inspection_category?: string
  hazard_type: HazardType
  hazard_level: HazardLevel
  hazard_category?: HazardCategory
  description: string
  discovered_by?: string
  discovered_by_name?: string
  inspector_department?: string
  discovered_at: string
  department?: string
  major_hazard_basis?: string
  key_defect?: string
  defect_photos?: string
  rectification_responsible_person?: string
  rectification_responsible_person_name?: string
  corrective_preventive_measures?: string
  rectification_reply?: string
  deadline?: string
  actual_completion_date?: string
  rectification_photos?: string
  rectification_status: string
  // 三级复核（仅状态，审核人/时间由系统自动记录）
  verify_level_1_status: string
  verify_level_2_status: string
  verify_level_3_status: string
  status: string
  check_id?: string
  notes?: string
  // ── AI 流程字段 ──
  ai_node_progress: string
  overall_status: string
  ai_error_message?: string
  ai_generated: boolean
  script1_review_status: string
  script2_review_status: string
  created_at: string
  updated_at: string
}

export interface HazardReportFormData {
  hazard_no: string
  inspection_category?: string
  hazard_type?: HazardType
  hazard_level?: HazardLevel
  hazard_category?: HazardCategory
  description?: string
  discovered_by?: string
  discovered_by_name?: string
  discovered_at?: string
  department?: string
  major_hazard_basis?: string
  key_defect?: string
  defect_photos?: string
  rectification_responsible_person?: string
  rectification_responsible_person_name?: string
  corrective_preventive_measures?: string
  rectification_reply?: string
  deadline?: string
  actual_completion_date?: string
  rectification_photos?: string
  check_id?: string
  notes?: string
  overall_status?: string
}

export interface HazardReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  rectification_status?: string
  overall_status?: string
  hazard_type?: string
  hazard_level?: string
  hazard_category?: string
  inspection_category?: string
  department?: string
  keyword?: string
}

export interface HazardStats {
  total: number
  pending_review: number
  pending: number
  in_progress: number
  replied: number
  verifying: number
  rejected: number
  closed: number
  overdue: number
}

export interface RectificationReplyRequest {
  reply_content: string
  rectification_photos?: string
  corrective_preventive_measures?: string
  rectification_reply?: string
  actual_completion_date?: string
}

export interface VerifyLevelRequest {
  level: number
  action: 'approved' | 'rejected'
  opinion?: string
}

export interface ConfirmCheckRequest {
  role: 'inspector' | 'safety_officer'
}

// ============ Accident Types ============

export interface Accident {
  id: string
  accident_no: string
  accident_type: AccidentType
  accident_level: AccidentLevel
  happened_at: string
  location?: string
  department?: string
  description: string
  casualties?: string
  property_damage?: number
  loss_work_days?: number
  injury_details?: { name: string; position: string; injury_part: string; severity: string; hospital?: string }[]
  investigation_team?: { name: string; role: string }[]
  investigation_method?: string
  investigation_findings?: string
  investigation_report_path?: string
  direct_cause?: string
  root_cause?: string
  handling_measures?: string
  corrective_actions?: string
  corrective_action_deadline?: string
  corrective_action_responsible?: string
  corrective_action_status?: string
  status: string
  reported_by?: string
  reported_by_name?: string
  reported_at: string
  investigator?: string
  investigator_name?: string
  verified_by?: string
  verified_by_name?: string
  verified_at?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface AccidentFormData {
  accident_no: string
  accident_type: AccidentType
  accident_level: AccidentLevel
  happened_at: string
  location?: string
  department?: string
  description: string
  casualties?: string
  property_damage?: number
  loss_work_days?: number
  injury_details?: { name: string; position: string; injury_part: string; severity: string; hospital?: string }[]
  investigation_team?: { name: string; role: string }[]
  investigation_method?: string
  investigation_findings?: string
  investigation_report_path?: string
  direct_cause?: string
  root_cause?: string
  handling_measures?: string
  corrective_actions?: string
  corrective_action_deadline?: string
  corrective_action_responsible?: string
  corrective_action_status?: string
  reported_by?: string
  reported_by_name?: string
  reported_at: string
  notes?: string
}

export interface AccidentQueryParams {
  page?: number
  page_size?: number
  status?: string
  accident_type?: string
  accident_level?: string
  department?: string
  date_from?: string
  date_to?: string
  keyword?: string
}

// ============ Contractor Types ============

export interface Contractor {
  id: string
  contractor_no: string
  company_name: string
  legal_representative?: string
  contact_person: string
  contact_phone?: string
  business_scope?: string
  qualification_type: QualificationTypeEnum
  qualification_level?: QualificationLevelEnum
  qualification_cert_no?: string
  qualification_expiry?: string
  safety_license_no?: string
  safety_license_expiry?: string
  insurance_info?: string
  insurance_expiry?: string
  safety_officer_name?: string
  safety_officer_phone?: string
  special_op_personnel?: { name: string; cert_type: string; cert_no: string; expiry?: string }[]
  training_status: string
  training_date?: string
  safety_performance_score?: number
  blacklisted: boolean
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface ContractorFormData {
  contractor_no: string
  company_name: string
  legal_representative?: string
  contact_person: string
  contact_phone?: string
  business_scope?: string
  qualification_type: QualificationTypeEnum
  qualification_level?: QualificationLevelEnum
  qualification_cert_no?: string
  qualification_expiry?: string
  safety_license_no?: string
  safety_license_expiry?: string
  insurance_info?: string
  insurance_expiry?: string
  safety_officer_name?: string
  safety_officer_phone?: string
  special_op_personnel?: { name: string; cert_type: string; cert_no: string; expiry?: string }[]
  notes?: string
}

export interface ContractorQueryParams {
  page?: number
  page_size?: number
  status?: string
  qualification_type?: string
  training_status?: string
  keyword?: string
}

export interface ContractorWorkRecord {
  id: string
  contractor_id: string
  work_content: string
  work_location?: string
  planned_start: string
  planned_end: string
  actual_start?: string
  actual_end?: string
  permit_id?: string
  leading_person?: string
  worker_count?: number
  safety_briefing_done: boolean
  violations?: { date: string; description: string; severity: string; handler?: string; result?: string }[]
  evaluation?: { score: number; comments?: string; evaluator?: string; date?: string }
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface ContractorWorkRecordFormData {
  work_content: string
  work_location?: string
  planned_start: string
  planned_end: string
  actual_start?: string
  actual_end?: string
  permit_id?: string
  leading_person?: string
  worker_count?: number
  safety_briefing_done: boolean
  violations?: { date: string; description: string; severity: string; handler?: string; result?: string }[]
  notes?: string
}

// ============ SafetyTraining Types ============

export interface SafetyTraining {
  id: string
  training_no: string
  training_name: string
  training_type: TrainingType
  training_mode: TrainingMode
  training_level?: string
  trainer?: string
  trainer_name?: string
  training_date: string
  duration_hours?: number
  location?: string
  content?: string
  department?: string
  exam_passing_score?: number
  course_material_path?: string
  status: string
  notes?: string
  created_at: string
  updated_at: string
  records?: TrainingRecord[]
}

export interface SafetyTrainingFormData {
  training_no: string
  training_name: string
  training_type: TrainingType
  training_mode: TrainingMode
  training_level?: string
  trainer?: string
  trainer_name?: string
  training_date: string
  duration_hours?: number
  location?: string
  content?: string
  department?: string
  exam_passing_score?: number
  course_material_path?: string
  notes?: string
}

export interface SafetyTrainingQueryParams {
  page?: number
  page_size?: number
  status?: string
  training_type?: string
  department?: string
}

// ============ TrainingRecord Types ============

export interface TrainingRecord {
  id: string
  training_id: string
  employee_id?: string
  employee_name?: string
  department?: string
  position?: string
  attendance: boolean
  score?: number
  passed?: boolean
  certificate_no?: string
  certificate_expiry?: string
  certificate_status?: string
  certificate_file_path?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface TrainingRecordFormData {
  employee_id?: string
  employee_name?: string
  department?: string
  position?: string
  attendance?: boolean
  score?: number
  passed?: boolean
  certificate_no?: string
  certificate_expiry?: string
  certificate_file_path?: string
  notes?: string
}

// ============ HazardIdentification Types ============

export interface HazardIdentification {
  id: string
  hazard_id_no: string
  department: string
  position: string
  production_step: string
  attachment_path?: string
  attachment_original_name?: string
  // Script 1
  specific_activity?: string
  equipment_facilities?: string
  raw_auxiliary_materials?: string
  operation_frequency?: string
  operator_count?: number
  // Script 2
  hazard_type?: string
  possible_accident?: string
  unsafe_behavior?: string
  // Script 3
  l_inherent?: number
  e_inherent?: number
  c_inherent?: number
  d_inherent?: number
  inherent_risk_level?: string
  inherent_risk_label?: string
  // Script 4
  existing_engineering_controls?: string
  existing_management_controls?: string
  existing_ppe?: string
  existing_emergency_measures?: string
  // Script 5
  l_residual?: number
  e_residual?: number
  c_residual?: number
  d_residual?: number
  residual_risk_level?: string
  residual_risk_label?: string
  // Script 6
  needs_recommendation?: string
  recommendation_type?: string
  recommendation_content?: string
  recommendation_priority?: string
  // Script 7
  l_post?: number
  e_post?: number
  c_post?: number
  d_post?: number
  post_risk_level?: string
  post_risk_label?: string
  // Control info
  control_level?: string
  responsible_person?: string
  // Workflow status
  ai_node_progress: string
  ai_error_message?: string
  overall_status: string
  script1_review_status: string
  script2_review_status: string
  script3_review_status: string
  script4_review_status: string
  script5_review_status: string
  script6_review_status: string
  script7_review_status: string
  // Meta
  notes?: string
  created_at: string
  updated_at: string
}

export interface HazardIdentificationFormData {
  hazard_id_no: string
  department: string
  position: string
  production_step: string
  notes?: string
}

export interface HazardIdentificationQueryParams {
  page?: number
  page_size?: number
  department?: string
  overall_status?: string
  ai_node_progress?: string
  keyword?: string
  position?: string
  risk_level?: string
  date_from?: string
  date_to?: string
}

export interface HazardIdentificationStats {
  total_draft: number
  total_in_progress: number
  total_pending_review: number
  total_completed: number
}

export interface HazardLedgerStats {
  total: number
  level_1: number
  level_2: number
  level_3: number
  level_4: number
}

export const AI_NODE_PROGRESS_OPTIONS = [
  { value: 'pending_input', label: '待填写基础信息', color: 'default' },
  { value: 'pending_script1', label: '待解析附件', color: 'processing' },
  { value: 'pending_script2', label: '待危险源辨识', color: 'processing' },
  { value: 'pending_script3', label: '待固有风险评价', color: 'processing' },
  { value: 'pending_script4', label: '待控制措施', color: 'processing' },
  { value: 'pending_script5', label: '待残余风险评价', color: 'processing' },
  { value: 'pending_script6', label: '待建议措施', color: 'processing' },
  { value: 'pending_script7', label: '待措施后评价', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
]

// ============ Hazard Identification Export Types ============

export interface HazardLedgerExportRequest {
  natural_query?: string
  department?: string
  position?: string
  risk_level?: string
  date_from?: string
  date_to?: string
  keyword?: string
}

export interface HazardLedgerExportParsedFilters {
  department?: string
  position?: string
  risk_level?: string
  date_from?: string
  date_to?: string
  keyword?: string
  explanation: string
}

export const OVERALL_STATUS_OPTIONS_HI = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'in_progress', label: '进行中', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
  { value: 'cancelled', label: '已取消', color: 'error' },
]

export const REVIEW_STATUS_OPTIONS = [
  { value: 'pending', label: '待审核', color: 'default' },
  { value: 'approved', label: '已审核', color: 'success' },
  { value: 'rejected', label: '已驳回', color: 'error' },
]

export const RECOMMENDATION_PRIORITY_OPTIONS = [
  { value: '高', label: '高', color: 'red' },
  { value: '中', label: '中', color: 'orange' },
  { value: '低', label: '低', color: 'blue' },
]

export interface SafetyDashboardStats {
  total_checks: number
  pending_checks: number
  open_hazards: number
  overdue_hazards: number
  recent_accidents: number
  upcoming_trainings: number
}

// ============ Regulation Enums ============

export enum RevisionType {
  MANUAL = 'manual',
  AI = 'ai',
}

export const REVISION_TYPE_OPTIONS = [
  { value: RevisionType.MANUAL, label: '人工修订' },
  { value: RevisionType.AI, label: 'AI修订' },
]

export enum RevisionScope {
  PROCESS = 'process',
  SAFETY_REQUIREMENT = 'safety_requirement',
}

export const REVISION_SCOPE_OPTIONS = [
  { value: RevisionScope.PROCESS, label: '工艺' },
  { value: RevisionScope.SAFETY_REQUIREMENT, label: '安全要求' },
]

export enum ReviewOpinion {
  PENDING = 'pending',
  APPROVED = 'approved',
}

export const REVIEW_OPINION_OPTIONS = [
  { value: ReviewOpinion.PENDING, label: '待审核', color: 'default' },
  { value: ReviewOpinion.APPROVED, label: '已审核', color: 'success' },
]


// ============ OperationRegulation Types ============

export interface OperationRegulation {
  id: string
  regulation_no: string
  regulation_name: string
  document_path?: string
  document_original_name?: string
  position?: string
  notes?: string
  content?: string        // SOP standardized markdown content
  status?: string         // draft | generated | reviewed | exported
  source_document_path?: string  // original uploaded draft path
  created_at: string
  updated_at: string
}

export interface OperationRegulationFormData {
  regulation_no: string
  regulation_name: string
  position?: string
  notes?: string
}

export interface OperationRegulationQueryParams {
  page?: number
  page_size?: number
  position?: string
  keyword?: string
  status?: string
}

// ============ RegulationRevision Types ============

export interface RegulationRevision {
  id: string
  revision_no: string
  regulation_id: string
  regulation_name: string
  old_document_path?: string
  reviser?: string
  reviser_name?: string
  revision_time: string
  revision_type: RevisionType
  revision_opinion?: string
  revision_scope?: string
  review_opinion: ReviewOpinion
  new_document_path?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface RegulationRevisionFormData {
  revision_no: string
  regulation_id: string
  revision_type: RevisionType
  revision_opinion?: string
  reviser?: string
  reviser_name?: string
  notes?: string
}

export interface RegulationRevisionQueryParams {
  page?: number
  page_size?: number
  regulation_id?: string
  revision_type?: string
  review_opinion?: string
  revision_scope?: string
}

// ============ SOP Generator Types ============

export interface SopMeta {
  product_name: string
  post_name: string
  department: string
  doc_number: string
  effective_date: string
  company_name: string
}

export interface SopGenerateResult {
  regulation_id: string
  meta: SopMeta
  content: string
  status: string
}

// ============ AI Workflow Config Types ============

/** 调用文档附件项 */
export interface ReferenceAttachment {
  id: string
  /** 附件类型: file（文件上传）/ knowledge（知识库引用） */
  type: 'file' | 'knowledge'
  /** 显示名称 */
  name: string
  /** 预览 URL（浏览器直接打开） */
  url: string
  /** 原始文件名（type=file 时） */
  original_name?: string
  /** 文件类型: pdf / docx / xlsx / txt / md */
  file_type?: string
  /** 文件大小（字节） */
  file_size?: number
  /** 后端转换后的 MD 文件路径（AI 读取用） */
  markdown_path?: string
  /** 知识库文章 ID（type=knowledge 时） */
  knowledge_id?: string
  /** 创建时间 ISO 字符串 */
  created_at: string
}

/** 调用文档完整值 */
export interface ReferenceDocsValue {
  /** 自由文本（标准引用、Skill 说明等） */
  text: string
  /** 附件列表 */
  attachments: ReferenceAttachment[]
}

/** AI 工作流步骤配置（4 字段结构化提示词） */
export interface WorkflowStepItem {
  script_number: number
  name: string
  /** 输入信息 — 工作流需要读取哪些信息 */
  input_info: string
  /** 工作规则 — 明确目的、要求和限制 */
  work_rules: string
  /** 调用文档 — 关联的知识库、参考标准、Skill 等（支持字符串或 {text, attachments} 对象） */
  reference_docs: string | ReferenceDocsValue
  /** 输出格式 — 期望 AI 输出的内容格式 */
  output_format: string
  /** 预期输出键（后端预设，前端不展示） */
  expected_keys: string[]
  is_enabled: boolean
  description?: string
  /** @deprecated 旧格式单 prompt 字段，新格式使用上述 4 字段 */
  prompt_template?: string
}

/** @deprecated 使用 WorkflowStepItem */
export type ScriptConfigItem = WorkflowStepItem

export interface AIWorkflowConfig {
  id: string
  module_code: string
  workflow_name: string
  workflow_description?: string
  trigger_event?: string
  is_enabled: boolean
  script_configs?: WorkflowStepItem[]
  sort_order: number
  notes?: string
  created_at: string
  updated_at: string
}

export interface AIWorkflowConfigFormData {
  module_code: string
  workflow_name: string
  workflow_description?: string
  trigger_event?: string
  is_enabled?: boolean
  script_configs?: WorkflowStepItem[]
  sort_order?: number
  notes?: string
}

export interface AIWorkflowConfigQueryParams {
  page?: number
  page_size?: number
  module_code?: string
  is_enabled?: boolean
}

export const SAFETY_MODULE_OPTIONS = [
  { value: 'hazard-identification', label: '危险源AI辨识', icon: '🤖' },
  { value: 'regulation', label: '安全操规管理', icon: '📋' },
  { value: 'check', label: '安全检查', icon: '✅' },
]

export const TRIGGER_EVENT_OPTIONS = [
  { value: 'submit', label: '提交时触发' },
  { value: 'revision_created', label: '修订创建时触发' },
  { value: 'manual_start', label: '手动启动' },
  { value: 'auto_trigger', label: '自动触发' },
  { value: 'schedule', label: '定时触发' },
]

// ═══════════════════════════════════════════
// AI 工作流 → 菜单分级映射
// ═══════════════════════════════════════════

export interface MenuMapEntry {
  group: string
  subgroup: string
  path: string
}

export const WORKFLOW_MENU_MAP: Record<string, MenuMapEntry> = {
  'hazard-identification': {
    group: '风险与隐患',
    subgroup: '风险分级管控',
    path: '/safety/hazard-identification',
  },
  'special-ops-critical': {
    group: '作业安全',
    subgroup: '特殊作业管理',
    path: '/safety/special-ops',
  },
  'special-ops-export': {
    group: '作业安全',
    subgroup: '特殊作业管理',
    path: '/safety/special-ops',
  },
  'hazard-identification-export': {
    group: '风险与隐患',
    subgroup: '风险分级管控',
    path: '/safety/hazard-identification',
  },
}

export const WORKFLOW_ICONS: Record<string, string> = {
  'hazard-identification': '🤖',
  'special-ops-critical': '🏗️',
  'special-ops-export': '📊',
  'hazard-identification-export': '📋',
}

// ============ SpecialOperationPersonnel Types ============

export interface SpecialOperationPersonnel {
  id: string
  personnel_no: string
  name: string
  department?: string | null
  certificate_type: string
  certificate_number?: string | null
  issuing_authority?: string | null
  issue_date?: string | null
  expiry_date?: string | null
  certificate_file_path?: string | null
  qualification_scope?: string | null
  status: string
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface SpecialOperationPersonnelFormData {
  personnel_no: string
  name: string
  department?: string
  certificate_type: OperationType
  certificate_number?: string
  issuing_authority?: string
  issue_date?: string
  expiry_date?: string
  certificate_file_path?: string
  qualification_scope?: string
  notes?: string
}

export interface SpecialOperationPersonnelQueryParams {
  page?: number
  page_size?: number
  status?: string
  certificate_type?: string
  department?: string
  keyword?: string
}

// ============ SpecialOperationPermit Types ============

export interface SpecialOperationPermit {
  id: string
  permit_no: string
  operation_type: string
  operation_level: string
  location?: string | null
  equipment_tag?: string | null
  work_description?: string | null
  planned_start_time?: string | null
  planned_end_time?: string | null
  actual_start_time?: string | null
  actual_end_time?: string | null
  applicant_name?: string | null
  work_leader_name?: string | null
  operator_names?: string | null
  guardian_name?: string | null
  approver_name?: string | null
  safety_measures?: string | null
  emergency_equipment?: string | null
  gas_analysis?: string | null
  risk_assessment?: string | null
  safety_briefing_confirmed: boolean
  safety_briefing_time?: string | null
  rejection_reason?: string | null
  completion_method?: string | null
  status: string
  check_id?: string | null
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface SpecialOperationPermitFormData {
  permit_no: string
  operation_type: OperationType
  operation_level?: OperationLevel
  location?: string
  equipment_tag?: string
  work_description?: string
  planned_start_time?: string
  planned_end_time?: string
  applicant_name?: string
  work_leader_name?: string
  operator_names?: string
  guardian_name?: string
  approver_name?: string
  safety_measures?: string
  emergency_equipment?: string
  gas_analysis?: string
  risk_assessment?: string
  check_id?: string
  notes?: string
}

export interface SpecialOperationPermitQueryParams {
  page?: number
  page_size?: number
  status?: string
  operation_type?: string
  operation_level?: string
  keyword?: string
}

// ============ Safety Knowledge Article Types ============

export interface SafetyKnowledgeArticle {
  id: string
  article_no: string
  title: string
  category: string
  summary?: string | null
  content?: string | null
  tags?: string | null
  source?: string | null
  author?: string | null
  publish_date?: string | null
  attachment_path?: string | null
  attachment_original_name?: string | null
  view_count: number
  status: string
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface SafetyKnowledgeArticleFormData {
  article_no: string
  title: string
  category: KnowledgeCategory
  summary?: string
  content?: string
  tags?: string
  source?: string
  author?: string
  publish_date?: string
  notes?: string
}

export interface SafetyKnowledgeArticleQueryParams {
  page?: number
  page_size?: number
  category?: string
  status?: string
  keyword?: string
}

// ==================== 风险作业报备 ====================

export enum ReportStatus {
  DRAFT = 'draft',
  SUBMITTED = 'submitted',
  APPROVED = 'approved',
  REJECTED = 'rejected',
}

export const REPORT_STATUS_OPTIONS = [
  { value: ReportStatus.DRAFT, label: '草稿', color: 'default' },
  { value: ReportStatus.SUBMITTED, label: '已提交', color: 'blue' },
  { value: ReportStatus.APPROVED, label: '已审批', color: 'green' },
  { value: ReportStatus.REJECTED, label: '已驳回', color: 'red' },
]

export const REPORT_TYPE_OPTIONS = [
  { value: 'regular', label: '常规作业', color: 'blue' },
  { value: 'non_regular', label: '非常规作业', color: 'orange' },
]

// ── 八大特殊作业报备 ──

export interface SpecialOperationReport {
  id: string
  report_no: string
  permit_id?: string
  operation_type: string
  operation_level: string
  department?: string
  location?: string
  equipment_tag?: string
  work_description?: string
  planned_start_time?: string
  planned_end_time?: string
  work_leader_name?: string
  operator_names?: string
  guardian_name?: string
  risk_level?: string
  safety_measures?: string
  emergency_equipment?: string
  gas_analysis?: string
  risk_assessment?: string
  applicant_name?: string
  approver_name?: string
  approved_at?: string
  rejection_reason?: string
  status: string
  notes?: string
  is_critical: boolean
  is_critical_reason?: string
  is_critical_updated_by?: string
  created_at: string
  updated_at: string
}

export interface SpecialOperationReportFormData {
  report_no: string
  permit_id?: string
  operation_type: string
  operation_level: string
  department?: string
  location?: string
  equipment_tag?: string
  work_description?: string
  planned_start_time?: string
  planned_end_time?: string
  work_leader_name?: string
  operator_names?: string
  guardian_name?: string
  risk_level?: string
  safety_measures?: string
  emergency_equipment?: string
  gas_analysis?: string
  risk_assessment?: string
  applicant_name?: string
  approver_name?: string
  notes?: string
}

export interface SpecialOperationReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  operation_type?: string
  operation_level?: string
  risk_level?: string
  department?: string
  date_from?: string
  date_to?: string
  keyword?: string
  is_critical?: boolean
}

// ── 特殊作业台账 ──

export interface SpecialOperationLedgerQueryParams {
  page?: number
  page_size?: number
  operation_type?: string
  operation_level?: string
  risk_level?: string
  department?: string
  date_from?: string
  date_to?: string
  keyword?: string
  is_critical?: boolean
}

export interface SpecialOperationLedgerStats {
  operation_type: string
  count: number
  critical_count: number
}

// ── 危险源选项（用于每日风险报备关联） ──

export interface HazardRiskOption {
  id: string
  hazard_id_no: string
  department: string
  position: string
  specific_activity: string
  inherent_risk_level: string
  inherent_risk_label: string
  existing_engineering_controls?: string
  existing_management_controls?: string
  existing_ppe?: string
  existing_emergency_measures?: string
}

// ── 每日风险作业报备 ──

export interface DailyRiskReport {
  id: string
  report_no: string
  report_date: string
  report_type?: string
  department?: string
  hazard_identification_id?: string
  operation_description: string
  operation_steps?: string
  hazard_factors?: string
  risk_level?: string
  control_measures?: string
  responsible_person?: string
  operator_count?: number
  location?: string
  planned_start_time?: string
  planned_end_time?: string
  applicant_name?: string
  approver_name?: string
  approved_at?: string
  rejection_reason?: string
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface DailyRiskReportFormData {
  report_no: string
  report_date: string
  department?: string
  hazard_identification_id?: string
  operation_description: string
  operation_steps?: string
  hazard_factors?: string
  risk_level?: string
  control_measures?: string
  responsible_person?: string
  operator_count?: number
  location?: string
  planned_start_time?: string
  planned_end_time?: string
  applicant_name?: string
  approver_name?: string
  notes?: string
}

export interface DailyRiskReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  department?: string
  report_date?: string
  report_type?: string
  keyword?: string
}


// ============ EHS变更管理 (MOC) ============

// Enums
export enum ChangeType {
  PROCESS_TECH = 'process_tech',
  EQUIPMENT_FACILITY = 'equipment_facility',
  MANAGEMENT = 'management',
}

export const CHANGE_TYPE_OPTIONS = [
  { value: ChangeType.PROCESS_TECH, label: '工艺技术变更' },
  { value: ChangeType.EQUIPMENT_FACILITY, label: '设备设施变更' },
  { value: ChangeType.MANAGEMENT, label: '管理变更' },
]

export enum ChangeGrade {
  MAJOR = 'major',
  GENERAL = 'general',
}

export const CHANGE_GRADE_OPTIONS = [
  { value: ChangeGrade.MAJOR, label: '重大变更', color: 'red' },
  { value: ChangeGrade.GENERAL, label: '一般变更', color: 'blue' },
]

export enum ChangeDuration {
  PERMANENT = 'permanent',
  TEMPORARY = 'temporary',
  EMERGENCY = 'emergency',
}

export const CHANGE_DURATION_OPTIONS = [
  { value: ChangeDuration.PERMANENT, label: '永久性' },
  { value: ChangeDuration.TEMPORARY, label: '临时性' },
  { value: ChangeDuration.EMERGENCY, label: '紧急', color: 'red' },
]

export enum EhsChangeStatus {
  DRAFT = 'draft',
  UNDER_REVIEW = 'under_review',
  APPROVED = 'approved',
  REJECTED = 'rejected',
  IN_PROGRESS = 'in_progress',
  COMMISSIONED = 'commissioned',
  CLOSED = 'closed',
}

export const EHS_CHANGE_STATUS_OPTIONS = [
  { value: EhsChangeStatus.DRAFT, label: '草稿', color: 'default' },
  { value: EhsChangeStatus.UNDER_REVIEW, label: '审核中', color: 'processing' },
  { value: EhsChangeStatus.APPROVED, label: '已批准', color: 'green' },
  { value: EhsChangeStatus.REJECTED, label: '已驳回', color: 'red' },
  { value: EhsChangeStatus.IN_PROGRESS, label: '实施中', color: 'orange' },
  { value: EhsChangeStatus.COMMISSIONED, label: '已投用', color: 'cyan' },
  { value: EhsChangeStatus.CLOSED, label: '已关闭', color: 'default' },
]

export enum RiskLevel {
  LEVEL_1 = 'level_1',
  LEVEL_2 = 'level_2',
  LEVEL_3 = 'level_3',
  LEVEL_4 = 'level_4',
}

export const RISK_LEVEL_OPTIONS = [
  { value: RiskLevel.LEVEL_1, label: '一级/重大风险', color: 'red' },
  { value: RiskLevel.LEVEL_2, label: '二级/较大风险', color: 'orange' },
  { value: RiskLevel.LEVEL_3, label: '三级/一般风险', color: 'yellow' },
  { value: RiskLevel.LEVEL_4, label: '四级/低风险', color: 'blue' },
]

export enum RiskAssessmentMethod {
  LEC = 'LEC',
  LS = 'LS',
  JHA = 'JHA',
  HAZOP = 'HAZOP',
  FMEA = 'FMEA',
  SCL = 'SCL',
  PHA = 'PHA',
  LOPA = 'LOPA',
  OTHER = 'other',
}

export const RISK_ASSESSMENT_METHOD_OPTIONS = [
  { value: RiskAssessmentMethod.LEC, label: 'LEC评价法' },
  { value: RiskAssessmentMethod.LS, label: 'LS风险矩阵' },
  { value: RiskAssessmentMethod.JHA, label: 'JHA工作危害分析' },
  { value: RiskAssessmentMethod.HAZOP, label: 'HAZOP分析' },
  { value: RiskAssessmentMethod.FMEA, label: 'FMEA失效模式分析' },
  { value: RiskAssessmentMethod.SCL, label: 'SCL安全检查表' },
  { value: RiskAssessmentMethod.PHA, label: 'PHA预先危险性分析' },
  { value: RiskAssessmentMethod.LOPA, label: 'LOPA保护层分析' },
  { value: RiskAssessmentMethod.OTHER, label: '其他' },
]

export enum ApprovalDecision {
  PENDING = 'pending',
  APPROVED = 'approved',
  REJECTED = 'rejected',
}

export const APPROVAL_DECISION_OPTIONS = [
  { value: ApprovalDecision.PENDING, label: '待审批', color: 'default' },
  { value: ApprovalDecision.APPROVED, label: '同意', color: 'green' },
  { value: ApprovalDecision.REJECTED, label: '驳回', color: 'red' },
]

export enum ActionItemStatus {
  PENDING = 'pending',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
}

export const ACTION_ITEM_STATUS_OPTIONS = [
  { value: ActionItemStatus.PENDING, label: '待完成' },
  { value: ActionItemStatus.IN_PROGRESS, label: '进行中' },
  { value: ActionItemStatus.COMPLETED, label: '已完成' },
]

export enum PSSRResult {
  PASS = 'pass',
  FAIL = 'fail',
  NA = 'na',
}

export const PSSR_RESULT_OPTIONS = [
  { value: PSSRResult.PASS, label: '通过', color: 'green' },
  { value: PSSRResult.FAIL, label: '不通过', color: 'red' },
  { value: PSSRResult.NA, label: '不适用', color: 'default' },
]

// JSON sub-record interfaces
export interface RiskAssessmentItem {
  method?: string
  severity?: string
  likelihood?: string
  risk_level?: string
  description?: string
  control_measures?: string
  assessed_by?: string
  assessed_date?: string
  participants?: string
}

export interface ApprovalChainItem {
  level: number
  approver_role: string
  approver?: string
  decision?: string
  comments?: string
  decided_at?: string
}

export interface ActionItem {
  task: string
  owner?: string
  due_date?: string
  status?: string
  completed_at?: string
}

export interface PSSRChecklistItem {
  item: string
  result?: string
  checked_by?: string
  checked_at?: string
  remarks?: string
}

export interface VerificationData {
  expected_effect_achieved?: boolean
  comments?: string
  psi_updated?: boolean
  documents_updated?: boolean
  accepted_by?: string
  accepted_date?: string
}

export interface ClosureData {
  closed_by?: string
  closed_date?: string
  temp_expiry_date?: string
  restored_date?: string
}

// Main interfaces
export interface EhsChange {
  id: string
  change_no: string
  title: string
  change_type: string
  change_grade: string
  change_duration: string
  department?: string
  location_unit?: string
  description?: string
  technical_basis?: string
  expected_start?: string
  expected_completion?: string
  actual_start?: string
  actual_completion?: string
  expected_effect?: string
  applicant_id?: string
  applicant_name?: string
  status: string
  equipment_tags?: string[]
  documents_to_update?: { name: string; number?: string }[]
  attachments?: { name: string; path: string }[]
  risk_assessments?: RiskAssessmentItem[]
  approval_chain?: ApprovalChainItem[]
  action_items?: ActionItem[]
  pssr_checklist?: PSSRChecklistItem[]
  verification?: VerificationData
  closure?: ClosureData
  linked_safety_check_id?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface EhsChangeFormData {
  change_no: string
  title: string
  change_type: string
  change_grade?: string
  change_duration?: string
  department?: string
  location_unit?: string
  description?: string
  technical_basis?: string
  expected_start?: string
  expected_completion?: string
  expected_effect?: string
  applicant_name?: string
  equipment_tags?: string[]
  documents_to_update?: { name: string; number?: string }[]
  attachments?: { name: string; path: string }[]
  risk_assessments?: RiskAssessmentItem[]
  approval_chain?: ApprovalChainItem[]
  action_items?: ActionItem[]
  pssr_checklist?: PSSRChecklistItem[]
  verification?: VerificationData
  closure?: ClosureData
  linked_safety_check_id?: string
  notes?: string
}

export interface EhsChangeQueryParams {
  page?: number
  page_size?: number
  status?: string
  change_type?: string
  change_grade?: string
  change_duration?: string
  department?: string
  keyword?: string
}


// ==================== 职业危害因素监测 ====================


export enum DetectionType {
  REGULAR = 'regular',
  COMMISSIONED = 'commissioned',
  EVALUATION = 'evaluation',
  ACCIDENT = 'accident',
}

export const DETECTION_TYPE_OPTIONS = [
  { value: DetectionType.REGULAR, label: '定期检测' },
  { value: DetectionType.COMMISSIONED, label: '委托检测' },
  { value: DetectionType.EVALUATION, label: '评价检测' },
  { value: DetectionType.ACCIDENT, label: '事故调查检测' },
]

export enum HazardFactorCategory {
  DUST = 'dust',
  CHEMICAL = 'chemical',
  PHYSICAL = 'physical',
}

export const HAZARD_FACTOR_CATEGORY_OPTIONS = [
  { value: HazardFactorCategory.DUST, label: '粉尘（总尘/呼尘）' },
  { value: HazardFactorCategory.CHEMICAL, label: '化学物质' },
  { value: HazardFactorCategory.PHYSICAL, label: '物理因素' },
]

export enum OELComplianceStatus {
  COMPLIANT = 'compliant',
  EXCEEDING = 'exceeding',
  MARGINAL = 'marginal',
}

export const OEL_COMPLIANCE_STATUS_OPTIONS = [
  { value: OELComplianceStatus.COMPLIANT, label: '符合', color: 'green' },
  { value: OELComplianceStatus.EXCEEDING, label: '超标', color: 'red' },
  { value: OELComplianceStatus.MARGINAL, label: '临界', color: 'orange' },
]

export enum MonitorStatus {
  DRAFT = 'draft',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  VERIFIED = 'verified',
}

export const MONITOR_STATUS_OPTIONS = [
  { value: MonitorStatus.DRAFT, label: '草稿', color: 'default' },
  { value: MonitorStatus.IN_PROGRESS, label: '检测中', color: 'processing' },
  { value: MonitorStatus.COMPLETED, label: '已完成', color: 'green' },
  { value: MonitorStatus.VERIFIED, label: '已验证', color: 'cyan' },
]

export enum ExamType {
  PRE_EMPLOYMENT = 'pre_employment',
  PERIODIC = 'periodic',
  POST_EMPLOYMENT = 'post_employment',
  EMERGENCY = 'emergency',
}

export const EXAM_TYPE_OPTIONS = [
  { value: ExamType.PRE_EMPLOYMENT, label: '上岗前' },
  { value: ExamType.PERIODIC, label: '在岗期间' },
  { value: ExamType.POST_EMPLOYMENT, label: '离岗时' },
  { value: ExamType.EMERGENCY, label: '应急/事故后' },
]

export enum ExamConclusion {
  NORMAL = 'normal',
  ABNORMAL_OTHER = 'abnormal_other',
  SUSPECTED_OD = 'suspected_od',
  OD_DIAGNOSED = 'od_diagnosed',
  CONTRAINDICATED = 'contraindicated',
  RE_EXAMINATION = 're_examination',
}

export const EXAM_CONCLUSION_OPTIONS = [
  { value: ExamConclusion.NORMAL, label: '未见异常', color: 'green' },
  { value: ExamConclusion.ABNORMAL_OTHER, label: '其他异常', color: 'orange' },
  { value: ExamConclusion.SUSPECTED_OD, label: '疑似职业病', color: 'red' },
  { value: ExamConclusion.OD_DIAGNOSED, label: '职业病确诊', color: 'red' },
  { value: ExamConclusion.CONTRAINDICATED, label: '职业禁忌证', color: 'red' },
  { value: ExamConclusion.RE_EXAMINATION, label: '复查', color: 'blue' },
]

export enum ExamStatus {
  SCHEDULED = 'scheduled',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  ARCHIVED = 'archived',
}

export const EXAM_STATUS_OPTIONS = [
  { value: ExamStatus.SCHEDULED, label: '已安排', color: 'default' },
  { value: ExamStatus.IN_PROGRESS, label: '体检中', color: 'processing' },
  { value: ExamStatus.COMPLETED, label: '已完成', color: 'green' },
  { value: ExamStatus.ARCHIVED, label: '已归档', color: 'default' },
]

export enum AbnormalityStatus {
  OPEN = 'open',
  INVESTIGATING = 'investigating',
  CORRECTED = 'corrected',
  CLOSED = 'closed',
}

export const ABNORMALITY_STATUS_OPTIONS = [
  { value: AbnormalityStatus.OPEN, label: '待处理', color: 'red' },
  { value: AbnormalityStatus.INVESTIGATING, label: '调查中', color: 'orange' },
  { value: AbnormalityStatus.CORRECTED, label: '已纠正', color: 'green' },
  { value: AbnormalityStatus.CLOSED, label: '已关闭', color: 'default' },
]

// JSON 子记录接口
export interface DetectionResultItem {
  factor_name: string
  factor_category: string
  detection_value: number
  unit?: string
  oel_limit?: number
  compliance_status?: string
  sampling_method?: string
  standard_ref?: string
}

export interface ExamResultItem {
  item_name: string
  category?: string
  result?: string
  reference_range?: string
  is_abnormal?: boolean
  remarks?: string
}

export interface AbnormalityRecord {
  abnormality_desc: string
  corrective_action?: string
  responsible_person?: string
  deadline?: string
  status?: string
  completed_at?: string
  remarks?: string
}

// 主实体接口
export interface OhHazardMonitor {
  id: string
  monitor_no: string
  workplace: string
  location?: string
  equipment_info?: string
  detection_type: string
  detection_date?: string
  detection_agency?: string
  status: string
  inspector_name?: string
  verifier_name?: string
  detection_results?: DetectionResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
  created_at: string
  updated_at: string
}

export interface OhHealthExam {
  id: string
  exam_no: string
  employee_name: string
  employee_id?: string
  department?: string
  job_position?: string
  exam_type: string
  status: string
  exam_agency?: string
  scheduled_date?: string
  exam_date?: string
  report_date?: string
  hazard_factors?: string[]
  overall_conclusion?: string
  exam_items?: ExamResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
  created_at: string
  updated_at: string
}

// FormData 接口
export interface OhHazardMonitorFormData {
  monitor_no: string
  workplace: string
  location?: string
  equipment_info?: string
  detection_type: string
  detection_date?: string
  detection_agency?: string
  inspector_name?: string
  detection_results?: DetectionResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
}

export interface OhHealthExamFormData {
  exam_no: string
  employee_name: string
  employee_id?: string
  department?: string
  job_position?: string
  exam_type: string
  exam_agency?: string
  scheduled_date?: string
  exam_date?: string
  report_date?: string
  hazard_factors?: string[]
  overall_conclusion?: string
  exam_items?: ExamResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
}

// QueryParams 接口
export interface OhHazardMonitorQueryParams {
  page?: number
  page_size?: number
  status?: string
  detection_type?: string
  workplace?: string
  keyword?: string
}

export interface OhHealthExamQueryParams {
  page?: number
  page_size?: number
  status?: string
  exam_type?: string
  department?: string
  keyword?: string
}

// ============ Scheduled Tasks (定时任务) ============

export enum TaskStatus {
  RUNNING = 'running',
  SUCCESS = 'success',
  FAILURE = 'failure',
}

export const TASK_STATUS_OPTIONS = [
  { value: TaskStatus.SUCCESS, label: '成功' },
  { value: TaskStatus.FAILURE, label: '失败' },
  { value: TaskStatus.RUNNING, label: '运行中' },
]

export enum HeaderColor {
  BLUE = 'blue',
  ORANGE = 'orange',
  GREEN = 'green',
  RED = 'red',
  PURPLE = 'purple',
}

export const HEADER_COLOR_OPTIONS = [
  { value: HeaderColor.BLUE, label: '蓝色', color: '#1677ff' },
  { value: HeaderColor.ORANGE, label: '橙色', color: '#fa8c16' },
  { value: HeaderColor.GREEN, label: '绿色', color: '#52c41a' },
  { value: HeaderColor.RED, label: '红色', color: '#ff4d4f' },
  { value: HeaderColor.PURPLE, label: '紫色', color: '#722ed1' },
]

export const CRON_PRESETS = [
  { label: '每天上午9点', value: '0 9 * * *', desc: '每天上午 09:00' },
  { label: '每天下午6点', value: '0 18 * * *', desc: '每天下午 18:00' },
  { label: '每周一上午9点', value: '0 9 * * 1', desc: '每周一上午 09:00' },
  { label: '每月1号上午9点', value: '0 9 1 * *', desc: '每月1号上午 09:00' },
  { label: '每小时整点', value: '0 * * * *', desc: '每小时整点' },
]

export interface DataSourceItem {
  key: string
  label: string
  enabled: boolean
}

export interface DataSourceOption {
  key: string
  label: string
  description?: string
  default_enabled: boolean
}

export interface ScheduledTask {
  id: string
  name: string
  description?: string
  cron_expression: string
  cron_desc?: string
  feishu_chat_id: string
  feishu_chat_name?: string
  header_color: string
  data_sources: DataSourceItem[]
  card_template?: string
  is_enabled: boolean
  last_run_at?: string
  last_run_status?: string
  last_error?: string
  next_run_at?: string
  created_at: string
  updated_at: string
}

export interface ScheduledTaskLog {
  id: string
  task_id: string
  started_at: string
  completed_at?: string
  status: string
  data_snapshot?: Record<string, string>
  card_content?: string
  feishu_msg_id?: string
  error_message?: string
  duration_ms?: number
  created_at: string
}

export interface ScheduledTaskFormData {
  name: string
  description?: string
  cron_expression: string
  cron_desc?: string
  feishu_chat_id: string
  feishu_chat_name?: string
  header_color: HeaderColor
  data_sources: DataSourceItem[]
  card_template?: string
  is_enabled: boolean
}

export interface ScheduledTaskQueryParams {
  page?: number
  page_size?: number
  is_enabled?: boolean
  search?: string
}

export interface CardPreviewRequest {
  data_sources: DataSourceItem[]
  card_template: string
  header_color: HeaderColor
}

export interface CardPreviewResponse {
  card_json: string
  markdown_preview: string
  variables: Record<string, string>
}

export interface FeishuChat {
  chat_id: string
  name: string
}
