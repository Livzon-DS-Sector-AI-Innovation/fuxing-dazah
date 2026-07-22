"""Safety request and response schemas."""

from enum import Enum


class ChangeType(str, Enum):
    """变更类型枚举"""

    PROCESS_TECH = "process_tech"
    EQUIPMENT_FACILITY = "equipment_facility"
    MANAGEMENT = "management"


CHANGE_TYPE_OPTIONS = [
    {"value": ChangeType.PROCESS_TECH, "label": "工艺技术变更"},
    {"value": ChangeType.EQUIPMENT_FACILITY, "label": "设备设施变更"},
    {"value": ChangeType.MANAGEMENT, "label": "管理变更"},
]


class ChangeGrade(str, Enum):
    """变更等级枚举"""

    MAJOR = "major"
    GENERAL = "general"


CHANGE_GRADE_OPTIONS = [
    {"value": ChangeGrade.MAJOR, "label": "重大变更", "color": "red"},
    {"value": ChangeGrade.GENERAL, "label": "一般变更", "color": "blue"},
]


class ChangeDuration(str, Enum):
    """变更期限枚举"""

    PERMANENT = "permanent"
    TEMPORARY = "temporary"
    EMERGENCY = "emergency"


CHANGE_DURATION_OPTIONS = [
    {"value": ChangeDuration.PERMANENT, "label": "永久性"},
    {"value": ChangeDuration.TEMPORARY, "label": "临时性"},
    {"value": ChangeDuration.EMERGENCY, "label": "紧急", "color": "red"},
]


class EhsChangeStatusEnum(str, Enum):
    """EHS变更状态枚举"""

    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMMISSIONED = "commissioned"
    CLOSED = "closed"


EHS_CHANGE_STATUS_OPTIONS = [
    {"value": EhsChangeStatusEnum.DRAFT, "label": "草稿", "color": "default"},
    {"value": EhsChangeStatusEnum.UNDER_REVIEW, "label": "审核中", "color": "processing"},
    {"value": EhsChangeStatusEnum.APPROVED, "label": "已批准", "color": "green"},
    {"value": EhsChangeStatusEnum.REJECTED, "label": "已驳回", "color": "red"},
    {"value": EhsChangeStatusEnum.IN_PROGRESS, "label": "实施中", "color": "orange"},
    {"value": EhsChangeStatusEnum.COMMISSIONED, "label": "已投用", "color": "cyan"},
    {"value": EhsChangeStatusEnum.CLOSED, "label": "已关闭", "color": "default"},
]


class RiskAssessmentMethodEnum(str, Enum):
    """风险评估方法枚举"""

    LEC = "LEC"
    LS = "LS"
    JHA = "JHA"
    HAZOP = "HAZOP"
    FMEA = "FMEA"
    SCL = "SCL"
    PHA = "PHA"
    LOPA = "LOPA"
    OTHER = "other"


RISK_ASSESSMENT_METHOD_OPTIONS = [
    {"value": RiskAssessmentMethodEnum.LEC, "label": "LEC评价法"},
    {"value": RiskAssessmentMethodEnum.LS, "label": "LS风险矩阵"},
    {"value": RiskAssessmentMethodEnum.JHA, "label": "JHA工作危害分析"},
    {"value": RiskAssessmentMethodEnum.HAZOP, "label": "HAZOP分析"},
    {"value": RiskAssessmentMethodEnum.FMEA, "label": "FMEA失效模式分析"},
    {"value": RiskAssessmentMethodEnum.SCL, "label": "SCL安全检查表"},
    {"value": RiskAssessmentMethodEnum.PHA, "label": "PHA预先危险性分析"},
    {"value": RiskAssessmentMethodEnum.LOPA, "label": "LOPA保护层分析"},
    {"value": RiskAssessmentMethodEnum.OTHER, "label": "其他"},
]


class RiskLevelEnum(str, Enum):
    """风险等级枚举"""

    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"
    LEVEL_4 = "level_4"


RISK_LEVEL_OPTIONS = [
    {"value": RiskLevelEnum.LEVEL_1, "label": "一级/重大风险", "color": "red"},
    {"value": RiskLevelEnum.LEVEL_2, "label": "二级/较大风险", "color": "orange"},
    {"value": RiskLevelEnum.LEVEL_3, "label": "三级/一般风险", "color": "yellow"},
    {"value": RiskLevelEnum.LEVEL_4, "label": "四级/低风险", "color": "blue"},
]


class ApprovalDecisionEnum(str, Enum):
    """审批决定枚举"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


APPROVAL_DECISION_OPTIONS = [
    {"value": ApprovalDecisionEnum.PENDING, "label": "待审批", "color": "default"},
    {"value": ApprovalDecisionEnum.APPROVED, "label": "同意", "color": "green"},
    {"value": ApprovalDecisionEnum.REJECTED, "label": "驳回", "color": "red"},
]


class ActionItemStatusEnum(str, Enum):
    """行动项状态枚举"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


ACTION_ITEM_STATUS_OPTIONS = [
    {"value": ActionItemStatusEnum.PENDING, "label": "待完成"},
    {"value": ActionItemStatusEnum.IN_PROGRESS, "label": "进行中"},
    {"value": ActionItemStatusEnum.COMPLETED, "label": "已完成"},
]


class PSSRResultEnum(str, Enum):
    """PSSR检查结果枚举"""

    PASS = "pass"
    FAIL = "fail"
    NA = "na"


PSSR_RESULT_OPTIONS = [
    {"value": PSSRResultEnum.PASS, "label": "通过", "color": "green"},
    {"value": PSSRResultEnum.FAIL, "label": "不通过", "color": "red"},
    {"value": PSSRResultEnum.NA, "label": "不适用", "color": "default"},
]


class CheckType(str, Enum):
    """检查类型枚举（16种）"""

    DAILY = "daily"
    SPECIAL = "special"
    COMPREHENSIVE = "comprehensive"
    HOLIDAY = "holiday"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    PRE_HOLIDAY = "pre_holiday"
    LEADERSHIP_DUTY = "leadership_duty"
    DEPT_CROSS = "dept_cross"
    WEEKLY = "weekly"
    RESUMPTION = "resumption"
    CHANGE_ACCEPTANCE = "change_acceptance"
    LIGHTNING = "lightning"
    SAFETY_VALVE = "safety_valve"
    POST_HOLIDAY = "post_holiday"
    HEATSTROKE_PREVENTION = "heatstroke_prevention"


CHECK_TYPE_OPTIONS = [
    {"value": CheckType.DAILY, "label": "日常检查"},
    {"value": CheckType.SPECIAL, "label": "专项检查"},
    {"value": CheckType.COMPREHENSIVE, "label": "综合检查"},
    {"value": CheckType.HOLIDAY, "label": "节假日检查"},
    {"value": CheckType.MONTHLY, "label": "月度安全检查"},
    {"value": CheckType.SEASONAL, "label": "季节性安全检查"},
    {"value": CheckType.PRE_HOLIDAY, "label": "节前安全检查"},
    {"value": CheckType.LEADERSHIP_DUTY, "label": "领导干部值班检查"},
    {"value": CheckType.DEPT_CROSS, "label": "部门互查"},
    {"value": CheckType.WEEKLY, "label": "周检"},
    {"value": CheckType.RESUMPTION, "label": "复工复产安全检查"},
    {"value": CheckType.CHANGE_ACCEPTANCE, "label": "变更验收"},
    {"value": CheckType.LIGHTNING, "label": "防雷检查"},
    {"value": CheckType.SAFETY_VALVE, "label": "安全阀专项检查"},
    {"value": CheckType.POST_HOLIDAY, "label": "节后复工检查"},
    {"value": CheckType.HEATSTROKE_PREVENTION, "label": "防暑降温专项"},
]


# ── 检查类别（隐患台账 Bitable 多选字段的 16 种预设选项）──
INSPECTION_CATEGORY_OPTIONS = [
    {"value": "月度安全检查", "label": "月度安全检查"},
    {"value": "节前安全检查", "label": "节前安全检查"},
    {"value": "专项安全检查", "label": "专项安全检查"},
    {"value": "领导干部值班检查", "label": "领导干部值班检查"},
    {"value": "部门安全检查", "label": "部门安全检查"},
    {"value": "季节性安全检查", "label": "季节性安全检查"},
    {"value": "周检", "label": "周检"},
    {"value": "复工复产安全检查", "label": "复工复产安全检查"},
    {"value": "部门互查", "label": "部门互查"},
    {"value": "变更验收", "label": "变更验收"},
    {"value": "防雷检查", "label": "防雷检查"},
    {"value": "安全阀专项检查", "label": "安全阀专项检查"},
    {"value": "节后复工检查", "label": "节后复工检查"},
    {"value": "防暑降温专项", "label": "防暑降温专项"},
    {"value": "电气专项检查", "label": "电气专项检查"},
    {"value": "关键风险作业专项检查", "label": "关键风险作业专项检查"},
]


class HazardType(str, Enum):
    """隐患类型枚举"""

    UNSAFE_CONDITION = "unsafe_condition"
    UNSAFE_ACTION = "unsafe_action"
    MANAGEMENT_DEFECT = "management_defect"
    ENVIRONMENTAL = "environmental"


HAZARD_TYPE_OPTIONS = [
    {"value": HazardType.UNSAFE_ACTION, "label": "人的不安全行为"},
    {"value": HazardType.UNSAFE_CONDITION, "label": "物的不安全状态"},
    {"value": HazardType.ENVIRONMENTAL, "label": "环境的不安全因素"},
    {"value": HazardType.MANAGEMENT_DEFECT, "label": "管理的缺陷"},
]


class HazardLevel(str, Enum):
    """隐患等级枚举（三级）"""

    GENERAL = "general"    # 一般隐患
    SERIOUS = "serious"    # 较大隐患
    MAJOR = "major"        # 重大隐患


HAZARD_LEVEL_OPTIONS = [
    {"value": HazardLevel.GENERAL, "label": "一般隐患"},
    {"value": HazardLevel.SERIOUS, "label": "较大隐患"},
    {"value": HazardLevel.MAJOR, "label": "重大隐患"},
]


class HazardCategory(str, Enum):
    """隐患类别枚举（13种）"""

    EQUIPMENT = "equipment"
    HAZARDOUS_STORAGE = "hazardous_storage"
    EMERGENCY_MGMT = "emergency_mgmt"
    INSTRUMENT_ELECTRICAL = "instrument_electrical"
    LIGHTNING_ANTISTATIC = "lightning_antistatic"
    OCCUPATIONAL_HEALTH = "occupational_health"
    VIOLATION_OPERATION = "violation_operation"
    SIX_S = "six_s"
    LABEL_SIGNAGE = "label_signage"
    PROCESS_MGMT = "process_mgmt"
    CONTRACTOR_DEFECT = "contractor_defect"
    DOCUMENTATION = "documentation"
    SPECIAL_OPERATION = "special_operation"


HAZARD_CATEGORY_OPTIONS = [
    {"value": HazardCategory.EQUIPMENT, "label": "设备设施"},
    {"value": HazardCategory.HAZARDOUS_STORAGE, "label": "危化储存"},
    {"value": HazardCategory.EMERGENCY_MGMT, "label": "应急管理"},
    {"value": HazardCategory.INSTRUMENT_ELECTRICAL, "label": "仪表+电气"},
    {"value": HazardCategory.LIGHTNING_ANTISTATIC, "label": "防雷防静电"},
    {"value": HazardCategory.OCCUPATIONAL_HEALTH, "label": "职业健康+劳保防护"},
    {"value": HazardCategory.VIOLATION_OPERATION, "label": "三违作业"},
    {"value": HazardCategory.SIX_S, "label": "6S"},
    {"value": HazardCategory.LABEL_SIGNAGE, "label": "标签标识"},
    {"value": HazardCategory.PROCESS_MGMT, "label": "工艺管理"},
    {"value": HazardCategory.CONTRACTOR_DEFECT, "label": "承包商缺陷"},
    {"value": HazardCategory.DOCUMENTATION, "label": "内页资料"},
    {"value": HazardCategory.SPECIAL_OPERATION, "label": "特殊作业"},
]


class AccidentType(str, Enum):
    """事故类型枚举"""

    INJURY = "injury"
    FIRE = "fire"
    EXPLOSION = "explosion"
    LEAKAGE = "leakage"
    EQUIPMENT = "equipment"
    NEAR_MISS = "near_miss"
    ENVIRONMENTAL = "environmental"
    OCCUPATIONAL_DISEASE = "occupational_disease"
    TRAFFIC = "traffic"
    OTHER = "other"


ACCIDENT_TYPE_OPTIONS = [
    {"value": AccidentType.INJURY, "label": "工伤事故"},
    {"value": AccidentType.FIRE, "label": "火灾"},
    {"value": AccidentType.EXPLOSION, "label": "爆炸"},
    {"value": AccidentType.LEAKAGE, "label": "泄漏"},
    {"value": AccidentType.EQUIPMENT, "label": "设备事故"},
    {"value": AccidentType.NEAR_MISS, "label": "未遂事件"},
    {"value": AccidentType.ENVIRONMENTAL, "label": "环境事件"},
    {"value": AccidentType.OCCUPATIONAL_DISEASE, "label": "职业病"},
    {"value": AccidentType.TRAFFIC, "label": "交通事故"},
    {"value": AccidentType.OTHER, "label": "其他"},
]


class AccidentLevel(str, Enum):
    """事故等级枚举"""

    GENERAL = "general"
    SERIOUS = "serious"
    MAJOR = "major"
    CATASTROPHIC = "catastrophic"


ACCIDENT_LEVEL_OPTIONS = [
    {"value": AccidentLevel.GENERAL, "label": "一般事故"},
    {"value": AccidentLevel.SERIOUS, "label": "较大事故"},
    {"value": AccidentLevel.MAJOR, "label": "重大事故"},
    {"value": AccidentLevel.CATASTROPHIC, "label": "特别重大事故"},
]


class AccidentStatus(str, Enum):
    """事故处理状态枚举"""

    REPORTED = "reported"
    INVESTIGATING = "investigating"
    INVESTIGATED = "investigated"
    CAPA_IN_PROGRESS = "capa_in_progress"
    CLOSED = "closed"


ACCIDENT_STATUS_OPTIONS = [
    {"value": AccidentStatus.REPORTED, "label": "已报告", "color": "blue"},
    {"value": AccidentStatus.INVESTIGATING, "label": "调查中", "color": "orange"},
    {"value": AccidentStatus.INVESTIGATED, "label": "调查完成", "color": "cyan"},
    {"value": AccidentStatus.CAPA_IN_PROGRESS, "label": "CAPA进行中", "color": "purple"},
    {"value": AccidentStatus.CLOSED, "label": "已关闭", "color": "green"},
]


class InjurySeverity(str, Enum):
    """伤害程度枚举"""

    DEATH = "death"
    SERIOUS_INJURY = "serious_injury"
    MINOR_INJURY = "minor_injury"
    NO_INJURY = "no_injury"


INJURY_SEVERITY_OPTIONS = [
    {"value": InjurySeverity.DEATH, "label": "死亡", "color": "red"},
    {"value": InjurySeverity.SERIOUS_INJURY, "label": "重伤", "color": "orange"},
    {"value": InjurySeverity.MINOR_INJURY, "label": "轻伤", "color": "yellow"},
    {"value": InjurySeverity.NO_INJURY, "label": "无伤害", "color": "green"},
]


class TrainingType(str, Enum):
    """培训类型枚举"""

    INDUCTION = "induction"
    ANNUAL = "annual"
    SPECIAL = "special"
    EMERGENCY = "emergency"
    CONTRACTOR = "contractor"
    REFRESHER = "refresher"


TRAINING_TYPE_OPTIONS = [
    {"value": TrainingType.INDUCTION, "label": "入职培训"},
    {"value": TrainingType.ANNUAL, "label": "年度培训"},
    {"value": TrainingType.SPECIAL, "label": "专项培训"},
    {"value": TrainingType.EMERGENCY, "label": "应急培训"},
    {"value": TrainingType.CONTRACTOR, "label": "承包商培训"},
    {"value": TrainingType.REFRESHER, "label": "复训"},
]


class TrainingMode(str, Enum):
    """培训方式枚举"""

    ONLINE = "online"
    OFFLINE = "offline"
    BLENDED = "blended"


class TrainingLevel(str, Enum):
    """培训级别枚举"""

    COMPANY = "company"
    DEPT = "dept"
    TEAM = "team"


TRAINING_LEVEL_OPTIONS = [
    {"value": TrainingLevel.COMPANY, "label": "公司级"},
    {"value": TrainingLevel.DEPT, "label": "部门级"},
    {"value": TrainingLevel.TEAM, "label": "班组级"},
]


class CertificateStatus(str, Enum):
    """证书状态枚举"""

    VALID = "valid"
    EXPIRING = "expiring"
    EXPIRED = "expired"


CERTIFICATE_STATUS_OPTIONS = [
    {"value": CertificateStatus.VALID, "label": "有效", "color": "green"},
    {"value": CertificateStatus.EXPIRING, "label": "即将到期", "color": "orange"},
    {"value": CertificateStatus.EXPIRED, "label": "已过期", "color": "red"},
]


TRAINING_MODE_OPTIONS = [
    {"value": TrainingMode.ONLINE, "label": "线上"},
    {"value": TrainingMode.OFFLINE, "label": "线下"},
    {"value": TrainingMode.BLENDED, "label": "混合"},
]


class RevisionType(str, Enum):
    """修订类型枚举"""

    MANUAL = "manual"
    AI = "ai"


REVISION_TYPE_OPTIONS = [
    {"value": RevisionType.MANUAL, "label": "人工修订"},
    {"value": RevisionType.AI, "label": "AI修订"},
]


class RevisionScope(str, Enum):
    """修订范围枚举"""

    PROCESS = "process"
    SAFETY_REQUIREMENT = "safety_requirement"


REVISION_SCOPE_OPTIONS = [
    {"value": RevisionScope.PROCESS, "label": "工艺"},
    {"value": RevisionScope.SAFETY_REQUIREMENT, "label": "安全要求"},
]


class ReviewOpinion(str, Enum):
    """审核意见枚举"""

    PENDING = "pending"
    APPROVED = "approved"


REVIEW_OPINION_OPTIONS = [
    {"value": ReviewOpinion.PENDING, "label": "待审核"},
    {"value": ReviewOpinion.APPROVED, "label": "已审核"},
]




class OperationType(str, Enum):
    """特殊作业类型枚举（GB 30871-2022）"""

    HOT_WORK = "hot_work"
    CONFINED_SPACE = "confined_space"
    BLIND_PLATE = "blind_plate"
    HEIGHT_WORK = "height_work"
    LIFTING = "lifting"
    TEMPORARY_ELECTRICITY = "temporary_electricity"
    EXCAVATION = "excavation"
    ROAD_BREAKING = "road_breaking"


OPERATION_TYPE_OPTIONS = [
    {"value": OperationType.HOT_WORK, "label": "动火作业"},
    {"value": OperationType.CONFINED_SPACE, "label": "受限空间作业"},
    {"value": OperationType.BLIND_PLATE, "label": "盲板抽堵作业"},
    {"value": OperationType.HEIGHT_WORK, "label": "高处作业"},
    {"value": OperationType.LIFTING, "label": "吊装作业"},
    {"value": OperationType.TEMPORARY_ELECTRICITY, "label": "临时用电作业"},
    {"value": OperationType.EXCAVATION, "label": "动土作业"},
    {"value": OperationType.ROAD_BREAKING, "label": "断路作业"},
]


class OperationLevel(str, Enum):
    """特殊作业级别枚举"""

    SPECIAL = "special"
    GRADE1 = "grade1"
    GRADE2 = "grade2"
    NOT_APPLICABLE = "not_applicable"


OPERATION_LEVEL_OPTIONS = [
    {"value": OperationLevel.SPECIAL, "label": "特级"},
    {"value": OperationLevel.GRADE1, "label": "一级"},
    {"value": OperationLevel.GRADE2, "label": "二级"},
    {"value": OperationLevel.NOT_APPLICABLE, "label": "不涉及"},
]


class PersonnelStatus(str, Enum):
    """人员资质状态枚举"""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


PERSONNEL_STATUS_OPTIONS = [
    {"value": PersonnelStatus.ACTIVE, "label": "有效"},
    {"value": PersonnelStatus.EXPIRED, "label": "已过期"},
    {"value": PersonnelStatus.REVOKED, "label": "已撤销"},
]


class PermitStatus(str, Enum):
    """作业票状态枚举"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


PERMIT_STATUS_OPTIONS = [
    {"value": PermitStatus.DRAFT, "label": "草稿"},
    {"value": PermitStatus.SUBMITTED, "label": "已提交"},
    {"value": PermitStatus.APPROVED, "label": "已审批"},
    {"value": PermitStatus.REJECTED, "label": "已驳回"},
    {"value": PermitStatus.IN_PROGRESS, "label": "作业中"},
    {"value": PermitStatus.COMPLETED, "label": "已完工"},
    {"value": PermitStatus.ARCHIVED, "label": "已归档"},
]


class CompletionMethod(str, Enum):
    """完工方式枚举"""

    NORMAL = "normal"
    EARLY_TERMINATION = "early_termination"


COMPLETION_METHOD_OPTIONS = [
    {"value": CompletionMethod.NORMAL, "label": "正常完工"},
    {"value": CompletionMethod.EARLY_TERMINATION, "label": "提前终止"},
]


class KnowledgeCategory(str, Enum):
    """安全知识库分类枚举"""

    LAWS_REGULATIONS = "laws_regulations"  # 法律法规
    STANDARDS = "standards"  # 标准规范
    MANAGEMENT_SYSTEMS = "management_systems"  # 管理制度
    ACCIDENT_CASES = "accident_cases"  # 事故案例
    EMERGENCY_PLANS = "emergency_plans"  # 应急预案
    SDS = "sds"  # 化学品安全技术说明书
    TRAINING_MATERIALS = "training_materials"  # 培训教材
    OTHER = "other"  # 其他


KNOWLEDGE_CATEGORY_OPTIONS = [
    {"value": KnowledgeCategory.LAWS_REGULATIONS, "label": "法律法规"},
    {"value": KnowledgeCategory.STANDARDS, "label": "标准规范"},
    {"value": KnowledgeCategory.MANAGEMENT_SYSTEMS, "label": "管理制度"},
    {"value": KnowledgeCategory.ACCIDENT_CASES, "label": "事故案例"},
    {"value": KnowledgeCategory.EMERGENCY_PLANS, "label": "应急预案"},
    {"value": KnowledgeCategory.SDS, "label": "化学品安全技术说明书"},
    {"value": KnowledgeCategory.TRAINING_MATERIALS, "label": "培训教材"},
    {"value": KnowledgeCategory.OTHER, "label": "其他"},
]


class DetectionTypeEnum(str, Enum):
    """检测类型枚举"""

    REGULAR = "regular"
    COMMISSIONED = "commissioned"
    EVALUATION = "evaluation"
    ACCIDENT = "accident"


DETECTION_TYPE_OPTIONS = [
    {"value": DetectionTypeEnum.REGULAR, "label": "定期检测"},
    {"value": DetectionTypeEnum.COMMISSIONED, "label": "委托检测"},
    {"value": DetectionTypeEnum.EVALUATION, "label": "评价检测"},
    {"value": DetectionTypeEnum.ACCIDENT, "label": "事故调查检测"},
]


class HazardFactorCategoryEnum(str, Enum):
    """危害因素类别枚举"""

    DUST = "dust"
    CHEMICAL = "chemical"
    PHYSICAL = "physical"


HAZARD_FACTOR_CATEGORY_OPTIONS = [
    {"value": HazardFactorCategoryEnum.DUST, "label": "粉尘（总尘/呼尘）"},
    {"value": HazardFactorCategoryEnum.CHEMICAL, "label": "化学物质"},
    {"value": HazardFactorCategoryEnum.PHYSICAL, "label": "物理因素"},
]


class OELComplianceStatusEnum(str, Enum):
    """OEL合规状态枚举"""

    COMPLIANT = "compliant"
    EXCEEDING = "exceeding"
    MARGINAL = "marginal"


OEL_COMPLIANCE_STATUS_OPTIONS = [
    {"value": OELComplianceStatusEnum.COMPLIANT, "label": "符合", "color": "green"},
    {"value": OELComplianceStatusEnum.EXCEEDING, "label": "超标", "color": "red"},
    {"value": OELComplianceStatusEnum.MARGINAL, "label": "临界", "color": "orange"},
]


class MonitorStatusEnum(str, Enum):
    """监测状态枚举"""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"


MONITOR_STATUS_OPTIONS = [
    {"value": MonitorStatusEnum.DRAFT, "label": "草稿", "color": "default"},
    {"value": MonitorStatusEnum.IN_PROGRESS, "label": "检测中", "color": "processing"},
    {"value": MonitorStatusEnum.COMPLETED, "label": "已完成", "color": "green"},
    {"value": MonitorStatusEnum.VERIFIED, "label": "已验证", "color": "cyan"},
]


class ExamTypeEnum(str, Enum):
    """体检类型枚举"""

    PRE_EMPLOYMENT = "pre_employment"
    PERIODIC = "periodic"
    POST_EMPLOYMENT = "post_employment"
    EMERGENCY = "emergency"


EXAM_TYPE_OPTIONS = [
    {"value": ExamTypeEnum.PRE_EMPLOYMENT, "label": "上岗前"},
    {"value": ExamTypeEnum.PERIODIC, "label": "在岗期间"},
    {"value": ExamTypeEnum.POST_EMPLOYMENT, "label": "离岗时"},
    {"value": ExamTypeEnum.EMERGENCY, "label": "应急/事故后"},
]


class ExamConclusionEnum(str, Enum):
    """体检结论枚举"""

    NORMAL = "normal"
    ABNORMAL_OTHER = "abnormal_other"
    SUSPECTED_OD = "suspected_od"
    OD_DIAGNOSED = "od_diagnosed"
    CONTRAINDICATED = "contraindicated"
    RE_EXAMINATION = "re_examination"


EXAM_CONCLUSION_OPTIONS = [
    {"value": ExamConclusionEnum.NORMAL, "label": "未见异常", "color": "green"},
    {"value": ExamConclusionEnum.ABNORMAL_OTHER, "label": "其他异常", "color": "orange"},
    {"value": ExamConclusionEnum.SUSPECTED_OD, "label": "疑似职业病", "color": "red"},
    {"value": ExamConclusionEnum.OD_DIAGNOSED, "label": "职业病确诊", "color": "red"},
    {"value": ExamConclusionEnum.CONTRAINDICATED, "label": "职业禁忌证", "color": "red"},
    {"value": ExamConclusionEnum.RE_EXAMINATION, "label": "复查", "color": "blue"},
]


class ExamStatusEnum(str, Enum):
    """体检状态枚举"""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


EXAM_STATUS_OPTIONS = [
    {"value": ExamStatusEnum.SCHEDULED, "label": "已安排", "color": "default"},
    {"value": ExamStatusEnum.IN_PROGRESS, "label": "体检中", "color": "processing"},
    {"value": ExamStatusEnum.COMPLETED, "label": "已完成", "color": "green"},
    {"value": ExamStatusEnum.ARCHIVED, "label": "已归档", "color": "default"},
]


class AbnormalityStatusEnum(str, Enum):
    """异常处置状态枚举"""

    OPEN = "open"
    INVESTIGATING = "investigating"
    CORRECTED = "corrected"
    CLOSED = "closed"


ABNORMALITY_STATUS_OPTIONS = [
    {"value": AbnormalityStatusEnum.OPEN, "label": "待处理", "color": "red"},
    {"value": AbnormalityStatusEnum.INVESTIGATING, "label": "调查中", "color": "orange"},
    {"value": AbnormalityStatusEnum.CORRECTED, "label": "已纠正", "color": "green"},
    {"value": AbnormalityStatusEnum.CLOSED, "label": "已关闭", "color": "default"},
]


