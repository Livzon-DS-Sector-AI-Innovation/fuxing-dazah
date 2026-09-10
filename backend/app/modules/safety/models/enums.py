"""Safety ORM models."""

from enum import StrEnum

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== Enums ====================


class ChangeType(StrEnum):
    """变更类型枚举（三大类）"""

    PROCESS_TECH = "process_tech"  # 工艺技术变更
    EQUIPMENT_FACILITY = "equipment_facility"  # 设备设施变更
    MANAGEMENT = "management"  # 管理变更


class ChangeGrade(StrEnum):
    """变更等级枚举"""

    MAJOR = "major"  # 重大变更
    GENERAL = "general"  # 一般变更


class ChangeDuration(StrEnum):
    """变更期限枚举"""

    PERMANENT = "permanent"  # 永久性
    TEMPORARY = "temporary"  # 临时性
    EMERGENCY = "emergency"  # 紧急


class EhsChangeStatus(StrEnum):
    """EHS变更状态枚举"""

    DRAFT = "draft"  # 草稿
    UNDER_REVIEW = "under_review"  # 审核中
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已驳回
    IN_PROGRESS = "in_progress"  # 实施中
    COMMISSIONED = "commissioned"  # 已投用
    CLOSED = "closed"  # 已关闭


class RiskAssessmentMethod(StrEnum):
    """风险评估方法枚举"""

    LEC = "LEC"  # LEC评价法
    LS = "LS"  # LS风险矩阵
    JHA = "JHA"  # 工作危害分析
    HAZOP = "HAZOP"  # 危险与可操作性分析
    FMEA = "FMEA"  # 失效模式与影响分析
    SCL = "SCL"  # 安全检查表
    PHA = "PHA"  # 预先危险性分析
    LOPA = "LOPA"  # 保护层分析
    OTHER = "other"  # 其他


class RiskLevel(StrEnum):
    """风险等级枚举"""

    LEVEL_1 = "level_1"  # 一级/重大风险
    LEVEL_2 = "level_2"  # 二级/较大风险
    LEVEL_3 = "level_3"  # 三级/一般风险
    LEVEL_4 = "level_4"  # 四级/低风险


class ApprovalDecision(StrEnum):
    """审批决定枚举"""

    PENDING = "pending"  # 待审批
    APPROVED = "approved"  # 同意
    REJECTED = "rejected"  # 驳回


class ActionItemStatus(StrEnum):
    """行动项状态枚举"""

    PENDING = "pending"  # 待完成
    IN_PROGRESS = "in_progress"  # 进行中
    COMPLETED = "completed"  # 已完成


class PSSRResult(StrEnum):
    """PSSR检查结果枚举"""

    PASS = "pass"  # 通过
    FAIL = "fail"  # 不通过
    NA = "na"  # 不适用


class HazardType(StrEnum):
    """隐患类型枚举（人/物/环/管）"""

    UNSAFE_CONDITION = "unsafe_condition"  # 物的不安全状态
    UNSAFE_ACTION = "unsafe_action"  # 人的不安全行为
    MANAGEMENT_DEFECT = "management_defect"  # 管理缺陷
    ENVIRONMENTAL = "environmental"  # 环境因素


class HazardLevel(StrEnum):
    """隐患等级枚举（三级）"""

    GENERAL = "general"  # 一般隐患
    SERIOUS = "serious"  # 较大隐患
    MAJOR = "major"  # 重大隐患


class HazardCategory(StrEnum):
    """隐患类别枚举（13种）"""

    EQUIPMENT = "equipment"  # 设备设施
    HAZARDOUS_STORAGE = "hazardous_storage"  # 危化储存
    EMERGENCY_MGMT = "emergency_mgmt"  # 应急管理
    INSTRUMENT_ELECTRICAL = "instrument_electrical"  # 仪表+电气
    LIGHTNING_ANTISTATIC = "lightning_antistatic"  # 防雷防静电
    OCCUPATIONAL_HEALTH = "occupational_health"  # 职业健康+劳保防护
    VIOLATION_OPERATION = "violation_operation"  # 三违作业
    SIX_S = "six_s"  # 6S
    LABEL_SIGNAGE = "label_signage"  # 标签标识
    PROCESS_MGMT = "process_mgmt"  # 工艺管理
    CONTRACTOR_DEFECT = "contractor_defect"  # 承包商缺陷
    DOCUMENTATION = "documentation"  # 内页资料
    SPECIAL_OPERATION = "special_operation"  # 特殊作业


class InjurySeverity(StrEnum):
    """伤害程度枚举"""

    DEATH = "death"  # 死亡
    SERIOUS_INJURY = "serious_injury"  # 重伤
    MINOR_INJURY = "minor_injury"  # 轻伤
    NO_INJURY = "no_injury"  # 无伤害


class ContractorStatus(StrEnum):
    """承包商状态枚举"""

    ACTIVE = "active"  # 活跃
    INACTIVE = "inactive"  # 停用
    BLACKLISTED = "blacklisted"  # 黑名单


class QualificationType(StrEnum):
    """承包资质类型枚举"""

    CONSTRUCTION = "construction"  # 建筑施工
    INSTALLATION = "installation"  # 设备安装
    MAINTENANCE = "maintenance"  # 检维修
    CLEANING = "cleaning"  # 保洁
    SECURITY = "security"  # 安保
    OTHER = "other"  # 其他


class QualificationLevel(StrEnum):
    """资质等级枚举"""

    GRADE_A = "grade_a"  # 甲级/一级
    GRADE_B = "grade_b"  # 乙级/二级
    GRADE_C = "grade_c"  # 丙级/三级


class ContractorTrainingStatus(StrEnum):
    """承包商培训状态枚举"""

    UNTRAINED = "untrained"  # 未培训
    IN_PROGRESS = "in_progress"  # 培训中
    PASSED = "passed"  # 已通过
    EXPIRED = "expired"  # 已过期


class WorkRecordStatus(StrEnum):
    """施工记录状态枚举"""

    IN_PROGRESS = "in_progress"  # 施工中
    COMPLETED = "completed"  # 已完成
    EVALUATED = "evaluated"  # 已评价


class TrainingType(StrEnum):
    """培训类型枚举"""

    INDUCTION = "induction"  # 入职培训
    ANNUAL = "annual"  # 年度培训
    SPECIAL = "special"  # 专项培训
    EMERGENCY = "emergency"  # 应急培训
    CONTRACTOR = "contractor"  # 承包商培训
    REFRESHER = "refresher"  # 复训


class TrainingLevel(StrEnum):
    """培训级别枚举"""

    COMPANY = "company"  # 公司级
    DEPT = "dept"  # 部门级
    TEAM = "team"  # 班组级


class CertificateStatus(StrEnum):
    """证书状态枚举"""

    VALID = "valid"  # 有效
    EXPIRING = "expiring"  # 即将到期
    EXPIRED = "expired"  # 已过期


class TrainingMode(StrEnum):
    """培训方式枚举"""

    ONLINE = "online"  # 线上
    OFFLINE = "offline"  # 线下
    BLENDED = "blended"  # 混合


class RevisionType(StrEnum):
    """操规修订类型枚举"""

    MANUAL = "manual"  # 人工修订
    AI = "ai"  # AI修订


class RevisionScope(StrEnum):
    """修订范围枚举"""

    PROCESS = "process"  # 工艺
    SAFETY_REQUIREMENT = "safety_requirement"  # 安全要求


class ReviewOpinion(StrEnum):
    """审核意见枚举"""

    PENDING = "pending"  # 待审核
    APPROVED = "approved"  # 已审核


class OperationType(StrEnum):
    """特殊作业类型枚举（GB 30871-2022 八大特殊作业）"""

    HOT_WORK = "hot_work"  # 动火作业
    CONFINED_SPACE = "confined_space"  # 受限空间作业
    BLIND_PLATE = "blind_plate"  # 盲板抽堵作业
    HEIGHT_WORK = "height_work"  # 高处作业
    LIFTING = "lifting"  # 吊装作业
    TEMPORARY_ELECTRICITY = "temporary_electricity"  # 临时用电作业
    EXCAVATION = "excavation"  # 动土作业
    ROAD_BREAKING = "road_breaking"  # 断路作业


class OperationLevel(StrEnum):
    """特殊作业级别枚举"""

    SPECIAL = "special"  # 特级
    GRADE1 = "grade1"  # 一级
    GRADE2 = "grade2"  # 二级
    NOT_APPLICABLE = "not_applicable"  # 不涉及


class PersonnelStatus(StrEnum):
    """人员资质状态枚举"""

    ACTIVE = "active"  # 有效
    EXPIRED = "expired"  # 已过期
    REVOKED = "revoked"  # 已撤销


class PermitStatus(StrEnum):
    """作业票状态枚举"""

    DRAFT = "draft"  # 草稿
    SUBMITTED = "submitted"  # 已提交
    APPROVED = "approved"  # 已审批
    REJECTED = "rejected"  # 已驳回
    IN_PROGRESS = "in_progress"  # 作业中
    COMPLETED = "completed"  # 已完工
    ARCHIVED = "archived"  # 已归档


class CompletionMethod(StrEnum):
    """完工方式枚举"""

    NORMAL = "normal"  # 正常完工
    EARLY_TERMINATION = "early_termination"  # 提前终止


class KnowledgeCategory(StrEnum):
    """安全知识库分类枚举"""

    LAWS_REGULATIONS = "laws_regulations"  # 法律法规
    STANDARDS = "standards"  # 标准规范
    MANAGEMENT_SYSTEMS = "management_systems"  # 管理制度
    ACCIDENT_CASES = "accident_cases"  # 事故案例
    EMERGENCY_PLANS = "emergency_plans"  # 应急预案
    SDS = "sds"  # 化学品安全技术说明书
    TRAINING_MATERIALS = "training_materials"  # 培训教材
    OTHER = "other"  # 其他


class DetectionType(StrEnum):
    """检测类型枚举"""

    REGULAR = "regular"  # 定期检测
    COMMISSIONED = "commissioned"  # 委托检测
    EVALUATION = "evaluation"  # 评价检测
    ACCIDENT = "accident"  # 事故调查检测


class HazardFactorCategory(StrEnum):
    """危害因素类别枚举"""

    DUST = "dust"  # 粉尘（总尘/呼尘）
    CHEMICAL = "chemical"  # 化学物质（有机溶剂、有毒气体、重金属）
    PHYSICAL = "physical"  # 物理因素（噪声、高温、振动、辐射、照度）


class OELComplianceStatus(StrEnum):
    """OEL合规状态枚举"""

    COMPLIANT = "compliant"  # 符合
    EXCEEDING = "exceeding"  # 超标
    MARGINAL = "marginal"  # 临界（接近限值）


class MonitorStatus(StrEnum):
    """监测状态枚举"""

    DRAFT = "draft"  # 草稿
    IN_PROGRESS = "in_progress"  # 检测中
    COMPLETED = "completed"  # 已完成
    VERIFIED = "verified"  # 已验证


class ExamType(StrEnum):
    """体检类型枚举"""

    PRE_EMPLOYMENT = "pre_employment"  # 上岗前
    PERIODIC = "periodic"  # 在岗期间
    POST_EMPLOYMENT = "post_employment"  # 离岗时
    EMERGENCY = "emergency"  # 应急/事故后


class ExamConclusion(StrEnum):
    """体检结论枚举"""

    NORMAL = "normal"  # 未见异常
    ABNORMAL_OTHER = "abnormal_other"  # 其他异常（非职业病）
    SUSPECTED_OD = "suspected_od"  # 疑似职业病
    OD_DIAGNOSED = "od_diagnosed"  # 职业病确诊
    CONTRAINDICATED = "contraindicated"  # 职业禁忌证
    RE_EXAMINATION = "re_examination"  # 复查


class ExamStatus(StrEnum):
    """体检状态枚举"""

    SCHEDULED = "scheduled"  # 已安排
    IN_PROGRESS = "in_progress"  # 体检中
    COMPLETED = "completed"  # 已完成
    ARCHIVED = "archived"  # 已归档


class AbnormalityStatus(StrEnum):
    """异常处置状态枚举"""

    OPEN = "open"  # 待处理
    INVESTIGATING = "investigating"  # 调查中
    CORRECTED = "corrected"  # 已纠正
    CLOSED = "closed"  # 已关闭


class RegulationStatus(StrEnum):
    """操规标准化生成状态"""

    DRAFT = "draft"          # 初始状态
    GENERATED = "generated"  # 已生成标准化 Markdown
    AI_REVIEWED = "ai_reviewed"  # AI 审核修正完成
    REVIEWED = "reviewed"    # 人工编辑审核完成
    EXPORTED = "exported"    # 已导出 PDF


class ReportStatus(StrEnum):
    """报备状态枚举"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class AdmissionReviewStatus(StrEnum):
    """相关方准入 AI 审核状态（平台内部状态机，英文 value）"""

    NONE = "none"            # 未审核
    PROCESSING = "processing"  # 审核中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败（可重审）


class AdmissionConclusion(StrEnum):
    """相关方准入 AI 审核总体结论（中文 value，与 Bitable 单选选项一致，回填直传）"""

    APPROVED = "审核通过"
    NEEDS_SUPPLEMENT = "需补充完善"
    REJECTED = "审核不通过"


class RelatedPartyType(StrEnum):
    """相关方类型（中文 value，与 Bitable 单选选项一致）"""

    CONTRACTOR = "承包商"
    COOPERATIVE = "合作类相关方"
    LABOR_DISPATCH = "劳务派遣"
    OTHER = "其他相关方"


class AdmissionSubmitStatus(StrEnum):
    """提交状态（中文 value，与 Bitable 单选选项一致）"""

    COMPLETED = "已完成"
    IN_PROGRESS = "进行中"
    NOT_STARTED = "未开始"


class AdmissionTrainingStatus(StrEnum):
    """培训状态（中文 value，与 Bitable 单选选项一致）"""

    COMPLETED = "已完结"
    TRAINED_NEED_MATERIAL = "已培训待补材"
    NOT_TRAINED = "未培训"


