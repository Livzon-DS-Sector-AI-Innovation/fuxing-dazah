"""Safety ORM models."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。

# ==================== Enums ====================


class CheckType(str, PyEnum):
    """检查类型枚举（16种）"""

    DAILY = "daily"  # 日常检查
    SPECIAL = "special"  # 专项检查
    COMPREHENSIVE = "comprehensive"  # 综合检查
    HOLIDAY = "holiday"  # 节假日检查
    MONTHLY = "monthly"  # 月度安全检查
    SEASONAL = "seasonal"  # 季节性安全检查
    PRE_HOLIDAY = "pre_holiday"  # 节前安全检查
    LEADERSHIP_DUTY = "leadership_duty"  # 领导干部值班检查
    DEPT_CROSS = "dept_cross"  # 部门互查
    WEEKLY = "weekly"  # 周检
    RESUMPTION = "resumption"  # 复工复产安全检查
    CHANGE_ACCEPTANCE = "change_acceptance"  # 变更验收
    LIGHTNING = "lightning"  # 防雷检查
    SAFETY_VALVE = "safety_valve"  # 安全阀专项检查
    POST_HOLIDAY = "post_holiday"  # 节后复工检查
    HEATSTROKE_PREVENTION = "heatstroke_prevention"  # 防暑降温专项


class ChangeType(str, PyEnum):
    """变更类型枚举（三大类）"""

    PROCESS_TECH = "process_tech"  # 工艺技术变更
    EQUIPMENT_FACILITY = "equipment_facility"  # 设备设施变更
    MANAGEMENT = "management"  # 管理变更


class ChangeGrade(str, PyEnum):
    """变更等级枚举"""

    MAJOR = "major"  # 重大变更
    GENERAL = "general"  # 一般变更


class ChangeDuration(str, PyEnum):
    """变更期限枚举"""

    PERMANENT = "permanent"  # 永久性
    TEMPORARY = "temporary"  # 临时性
    EMERGENCY = "emergency"  # 紧急


class EhsChangeStatus(str, PyEnum):
    """EHS变更状态枚举"""

    DRAFT = "draft"  # 草稿
    UNDER_REVIEW = "under_review"  # 审核中
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已驳回
    IN_PROGRESS = "in_progress"  # 实施中
    COMMISSIONED = "commissioned"  # 已投用
    CLOSED = "closed"  # 已关闭


class RiskAssessmentMethod(str, PyEnum):
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


class RiskLevel(str, PyEnum):
    """风险等级枚举"""

    LEVEL_1 = "level_1"  # 一级/重大风险
    LEVEL_2 = "level_2"  # 二级/较大风险
    LEVEL_3 = "level_3"  # 三级/一般风险
    LEVEL_4 = "level_4"  # 四级/低风险


class ApprovalDecision(str, PyEnum):
    """审批决定枚举"""

    PENDING = "pending"  # 待审批
    APPROVED = "approved"  # 同意
    REJECTED = "rejected"  # 驳回


class ActionItemStatus(str, PyEnum):
    """行动项状态枚举"""

    PENDING = "pending"  # 待完成
    IN_PROGRESS = "in_progress"  # 进行中
    COMPLETED = "completed"  # 已完成


class PSSRResult(str, PyEnum):
    """PSSR检查结果枚举"""

    PASS = "pass"  # 通过
    FAIL = "fail"  # 不通过
    NA = "na"  # 不适用


class HazardType(str, PyEnum):
    """隐患类型枚举（人/物/环/管）"""

    UNSAFE_CONDITION = "unsafe_condition"  # 物的不安全状态
    UNSAFE_ACTION = "unsafe_action"  # 人的不安全行为
    MANAGEMENT_DEFECT = "management_defect"  # 管理缺陷
    ENVIRONMENTAL = "environmental"  # 环境因素


class HazardLevel(str, PyEnum):
    """隐患等级枚举（三级）"""

    GENERAL = "general"  # 一般隐患
    SERIOUS = "serious"  # 较大隐患
    MAJOR = "major"  # 重大隐患


class HazardCategory(str, PyEnum):
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


class AccidentType(str, PyEnum):
    """事故类型枚举"""

    INJURY = "injury"  # 工伤事故
    FIRE = "fire"  # 火灾
    EXPLOSION = "explosion"  # 爆炸
    LEAKAGE = "leakage"  # 泄漏
    EQUIPMENT = "equipment"  # 设备事故
    NEAR_MISS = "near_miss"  # 未遂事件
    ENVIRONMENTAL = "environmental"  # 环境事件
    OCCUPATIONAL_DISEASE = "occupational_disease"  # 职业病
    TRAFFIC = "traffic"  # 交通事故
    OTHER = "other"  # 其他


class AccidentLevel(str, PyEnum):
    """事故等级枚举"""

    GENERAL = "general"  # 一般事故
    SERIOUS = "serious"  # 较大事故
    MAJOR = "major"  # 重大事故
    CATASTROPHIC = "catastrophic"  # 特别重大事故


class AccidentStatus(str, PyEnum):
    """事故处理状态枚举"""

    REPORTED = "reported"  # 已报告
    INVESTIGATING = "investigating"  # 调查中
    INVESTIGATED = "investigated"  # 调查完成
    CAPA_IN_PROGRESS = "capa_in_progress"  # CAPA进行中
    CLOSED = "closed"  # 已关闭


class InjurySeverity(str, PyEnum):
    """伤害程度枚举"""

    DEATH = "death"  # 死亡
    SERIOUS_INJURY = "serious_injury"  # 重伤
    MINOR_INJURY = "minor_injury"  # 轻伤
    NO_INJURY = "no_injury"  # 无伤害


class ContractorStatus(str, PyEnum):
    """承包商状态枚举"""

    ACTIVE = "active"  # 活跃
    INACTIVE = "inactive"  # 停用
    BLACKLISTED = "blacklisted"  # 黑名单


class QualificationType(str, PyEnum):
    """承包资质类型枚举"""

    CONSTRUCTION = "construction"  # 建筑施工
    INSTALLATION = "installation"  # 设备安装
    MAINTENANCE = "maintenance"  # 检维修
    CLEANING = "cleaning"  # 保洁
    SECURITY = "security"  # 安保
    OTHER = "other"  # 其他


class QualificationLevel(str, PyEnum):
    """资质等级枚举"""

    GRADE_A = "grade_a"  # 甲级/一级
    GRADE_B = "grade_b"  # 乙级/二级
    GRADE_C = "grade_c"  # 丙级/三级


class ContractorTrainingStatus(str, PyEnum):
    """承包商培训状态枚举"""

    UNTRAINED = "untrained"  # 未培训
    IN_PROGRESS = "in_progress"  # 培训中
    PASSED = "passed"  # 已通过
    EXPIRED = "expired"  # 已过期


class WorkRecordStatus(str, PyEnum):
    """施工记录状态枚举"""

    IN_PROGRESS = "in_progress"  # 施工中
    COMPLETED = "completed"  # 已完成
    EVALUATED = "evaluated"  # 已评价


class TrainingType(str, PyEnum):
    """培训类型枚举"""

    INDUCTION = "induction"  # 入职培训
    ANNUAL = "annual"  # 年度培训
    SPECIAL = "special"  # 专项培训
    EMERGENCY = "emergency"  # 应急培训
    CONTRACTOR = "contractor"  # 承包商培训
    REFRESHER = "refresher"  # 复训


class TrainingLevel(str, PyEnum):
    """培训级别枚举"""

    COMPANY = "company"  # 公司级
    DEPT = "dept"  # 部门级
    TEAM = "team"  # 班组级


class CertificateStatus(str, PyEnum):
    """证书状态枚举"""

    VALID = "valid"  # 有效
    EXPIRING = "expiring"  # 即将到期
    EXPIRED = "expired"  # 已过期


class TrainingMode(str, PyEnum):
    """培训方式枚举"""

    ONLINE = "online"  # 线上
    OFFLINE = "offline"  # 线下
    BLENDED = "blended"  # 混合


class RevisionType(str, PyEnum):
    """操规修订类型枚举"""

    MANUAL = "manual"  # 人工修订
    AI = "ai"  # AI修订


class RevisionScope(str, PyEnum):
    """修订范围枚举"""

    PROCESS = "process"  # 工艺
    SAFETY_REQUIREMENT = "safety_requirement"  # 安全要求


class ReviewOpinion(str, PyEnum):
    """审核意见枚举"""

    PENDING = "pending"  # 待审核
    APPROVED = "approved"  # 已审核


class OperationType(str, PyEnum):
    """特殊作业类型枚举（GB 30871-2022 八大特殊作业）"""

    HOT_WORK = "hot_work"  # 动火作业
    CONFINED_SPACE = "confined_space"  # 受限空间作业
    BLIND_PLATE = "blind_plate"  # 盲板抽堵作业
    HEIGHT_WORK = "height_work"  # 高处作业
    LIFTING = "lifting"  # 吊装作业
    TEMPORARY_ELECTRICITY = "temporary_electricity"  # 临时用电作业
    EXCAVATION = "excavation"  # 动土作业
    ROAD_BREAKING = "road_breaking"  # 断路作业


class OperationLevel(str, PyEnum):
    """特殊作业级别枚举"""

    SPECIAL = "special"  # 特级
    GRADE1 = "grade1"  # 一级
    GRADE2 = "grade2"  # 二级
    NOT_APPLICABLE = "not_applicable"  # 不涉及


class PersonnelStatus(str, PyEnum):
    """人员资质状态枚举"""

    ACTIVE = "active"  # 有效
    EXPIRED = "expired"  # 已过期
    REVOKED = "revoked"  # 已撤销


class PermitStatus(str, PyEnum):
    """作业票状态枚举"""

    DRAFT = "draft"  # 草稿
    SUBMITTED = "submitted"  # 已提交
    APPROVED = "approved"  # 已审批
    REJECTED = "rejected"  # 已驳回
    IN_PROGRESS = "in_progress"  # 作业中
    COMPLETED = "completed"  # 已完工
    ARCHIVED = "archived"  # 已归档


class CompletionMethod(str, PyEnum):
    """完工方式枚举"""

    NORMAL = "normal"  # 正常完工
    EARLY_TERMINATION = "early_termination"  # 提前终止


class KnowledgeCategory(str, PyEnum):
    """安全知识库分类枚举"""

    LAWS_REGULATIONS = "laws_regulations"  # 法律法规
    STANDARDS = "standards"  # 标准规范
    MANAGEMENT_SYSTEMS = "management_systems"  # 管理制度
    ACCIDENT_CASES = "accident_cases"  # 事故案例
    EMERGENCY_PLANS = "emergency_plans"  # 应急预案
    SDS = "sds"  # 化学品安全技术说明书
    TRAINING_MATERIALS = "training_materials"  # 培训教材
    OTHER = "other"  # 其他


class DetectionType(str, PyEnum):
    """检测类型枚举"""

    REGULAR = "regular"  # 定期检测
    COMMISSIONED = "commissioned"  # 委托检测
    EVALUATION = "evaluation"  # 评价检测
    ACCIDENT = "accident"  # 事故调查检测


class HazardFactorCategory(str, PyEnum):
    """危害因素类别枚举"""

    DUST = "dust"  # 粉尘（总尘/呼尘）
    CHEMICAL = "chemical"  # 化学物质（有机溶剂、有毒气体、重金属）
    PHYSICAL = "physical"  # 物理因素（噪声、高温、振动、辐射、照度）


class OELComplianceStatus(str, PyEnum):
    """OEL合规状态枚举"""

    COMPLIANT = "compliant"  # 符合
    EXCEEDING = "exceeding"  # 超标
    MARGINAL = "marginal"  # 临界（接近限值）


class MonitorStatus(str, PyEnum):
    """监测状态枚举"""

    DRAFT = "draft"  # 草稿
    IN_PROGRESS = "in_progress"  # 检测中
    COMPLETED = "completed"  # 已完成
    VERIFIED = "verified"  # 已验证


class ExamType(str, PyEnum):
    """体检类型枚举"""

    PRE_EMPLOYMENT = "pre_employment"  # 上岗前
    PERIODIC = "periodic"  # 在岗期间
    POST_EMPLOYMENT = "post_employment"  # 离岗时
    EMERGENCY = "emergency"  # 应急/事故后


class ExamConclusion(str, PyEnum):
    """体检结论枚举"""

    NORMAL = "normal"  # 未见异常
    ABNORMAL_OTHER = "abnormal_other"  # 其他异常（非职业病）
    SUSPECTED_OD = "suspected_od"  # 疑似职业病
    OD_DIAGNOSED = "od_diagnosed"  # 职业病确诊
    CONTRAINDICATED = "contraindicated"  # 职业禁忌证
    RE_EXAMINATION = "re_examination"  # 复查


class ExamStatus(str, PyEnum):
    """体检状态枚举"""

    SCHEDULED = "scheduled"  # 已安排
    IN_PROGRESS = "in_progress"  # 体检中
    COMPLETED = "completed"  # 已完成
    ARCHIVED = "archived"  # 已归档


class AbnormalityStatus(str, PyEnum):
    """异常处置状态枚举"""

    OPEN = "open"  # 待处理
    INVESTIGATING = "investigating"  # 调查中
    CORRECTED = "corrected"  # 已纠正
    CLOSED = "closed"  # 已关闭


class RegulationStatus(str, PyEnum):
    """操规标准化生成状态"""

    DRAFT = "draft"          # 初始状态
    GENERATED = "generated"  # 已生成标准化 Markdown
    REVIEWED = "reviewed"    # 人工编辑审核完成
    EXPORTED = "exported"    # 已导出 PDF


class ReportStatus(str, PyEnum):
    """报备状态枚举"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


# ==================== 安全检查 ====================


class SafetyCheck(BaseModel):
    """安全检查表"""

    __tablename__ = "safety_checks"
    __table_args__ = (
        Index("uq_safety_checks_check_no", "check_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    check_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="检查编号")
    check_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="daily", server_default="daily", comment="检查类型"
    )
    check_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="检查日期"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="检查部门")
    inspector: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="检查人"
    )
    inspector_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="检查人姓名")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="检查地点")
    findings: Mapped[str | None] = mapped_column(Text, nullable=True, comment="检查发现")
    result: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="检查结果: qualified/unqualified/need_rectification"
    )
    rectification_required: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否需要整改")
    rectification_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改期限"
    )
    rectification_status: Mapped[str | None] = mapped_column(
        String(32), default="pending", nullable=True, comment="整改进度"
    )
    inspector_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="检查人员确认"
    )
    safety_officer_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="安全办确认"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, comment="状态"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    hazards: Mapped[list["HazardReport"]] = relationship(
        "HazardReport", back_populates="safety_check", lazy="selectin"
    )


# ==================== 隐患排查 ====================


class HazardReport(BaseModel):
    """隐患报告表"""

    __tablename__ = "hazard_reports"
    __table_args__ = (
        Index("uq_hazard_reports_hazard_no", "hazard_no", unique=True, postgresql_where=text("is_deleted = false")),
        Index(
            "uq_hazard_reports_feishu_record_id",
            "feishu_record_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        ),
        {"schema": "safety"},
    )

    hazard_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="隐患编号")
    inspection_category: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="检查类别（Bitable 多选，逗号分隔，如「月度安全检查, 周检」）"
    )
    hazard_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="隐患分类（AI）：人的不安全行为/物的不安全状态/环境的不安全因素/管理的缺陷"
    )
    hazard_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="general", comment="隐患等级（AI）：一般隐患/较大隐患/重大隐患"
    )
    hazard_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="隐患类别（AI）：设备设施/危化储存/仪表+电气/…（13种）"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="隐患描述")
    discovered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="发现人"
    )
    discovered_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="检查人员姓名")
    inspector_department: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="检查人员部门（Bitable 多选，逗号分隔，如「EHS部, 生产部」）"
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=None, nullable=False, comment="检查日期"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="责任部门")
    major_hazard_basis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="隐患判定依据（AI）"
    )
    key_defect: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="隐患描述（AI）"
    )
    defect_photos: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="缺陷图片JSON数组"
    )
    rectification_responsible_person: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="整改责任人（FK → identity.users）"
    )
    rectification_responsible_person_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="整改责任人姓名（Bitable「责任人」）"
    )
    corrective_preventive_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI整改建议"
    )
    rectification_reply: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="整改回复内容"
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改期限"
    )
    actual_completion_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改完成时间"
    )
    rectification_photos: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="整改后图片JSON数组"
    )
    rectification_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False, comment="整改进度"
    )
    # ── 三级复核 ──
    verify_level_1_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False,
        comment="部门负责人复核状态 (Bitable「部门负责人复核」): pending/approved/rejected"
    )
    verify_level_2_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False,
        comment="分管领导复核状态 (Bitable「分管领导复核」): pending/approved/rejected/no_review_needed"
    )
    verify_level_3_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False,
        comment="检查人员复核状态 (Bitable「检查人员复核」): pending/approved/rejected"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="open", server_default="open", nullable=False, comment="状态"
    )
    check_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.safety_checks.id"), nullable=True, comment="关联检查ID"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── AI 流程状态 ──
    ai_node_progress: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending_input",
        server_default="pending_input",
        comment="AI流程节点进度(pending_input/pending_script1/review_script1/pending_script2/review_script2/completed)",
    )
    overall_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="整体状态(draft/ai_processing/completed/cancelled)",
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 脚本执行错误信息"
    )
    script1_review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        comment="AI隐患识别审核状态(pending/approved/rejected)",
    )
    script2_review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        comment="AI整改建议审核状态(pending/approved/rejected)",
    )
    ai_generated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="是否AI生成",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书多维表格记录 ID，双向同步关联"
    )

    # ── AI 整改初审 ──
    ai_review_result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="AI 整改初审结果 JSON（RectificationReviewOutput 完整输出）"
    )
    ai_review_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False,
        comment="AI 初审状态: pending / processing / completed / failed"
    )
    ai_review_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="AI 初审完成时间"
    )

    # ── 飞书通知追踪 ──
    rectification_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改通知最近发送时间"
    )
    rectification_notify_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="整改通知状态: success / failed"
    )
    rectification_notify_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="整改通知失败原因"
    )
    review_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="复核通知最近发送时间"
    )
    review_notified_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="复核通知级别: 1/2/3"
    )
    review_notify_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="复核通知状态: success / failed"
    )
    review_notify_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="复核通知失败原因"
    )

    # 关系
    safety_check: Mapped["SafetyCheck | None"] = relationship(
        "SafetyCheck", back_populates="hazards"
    )


# ==================== 事故管理 ====================


class Accident(BaseModel):
    """事故登记表"""

    __tablename__ = "accidents"
    __table_args__ = (
        Index("uq_accidents_accident_no", "accident_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    accident_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="事故编号")
    accident_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="事故类型")
    accident_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general", comment="事故等级"
    )
    happened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="发生时间"
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="发生地点")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="发生部门")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="事故描述")
    casualties: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="伤亡情况汇总")
    property_damage: Mapped[float | None] = mapped_column(Float, nullable=True, comment="财产损失(元)")
    loss_work_days: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="损失工作日")
    # ── 伤员详情 ──
    injury_details: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="伤员详情 JSON [{\"name\",\"position\",\"injury_part\",\"severity\",\"hospital\"}]"
    )
    # ── 调查信息 ──
    investigation_team: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="调查组 JSON [{\"name\",\"role\"}]"
    )
    investigation_method: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="调查方法: 5-Why/FTA/Event Tree/BowTie等"
    )
    investigation_findings: Mapped[str | None] = mapped_column(Text, nullable=True, comment="调查发现")
    investigation_report_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="调查报告文件路径"
    )
    direct_cause: Mapped[str | None] = mapped_column(Text, nullable=True, comment="直接原因")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True, comment="根本原因")
    handling_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处理措施")
    corrective_actions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="纠正预防措施")
    # ── CAPA 跟踪 ──
    corrective_action_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="CAPA截止日期"
    )
    corrective_action_responsible: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="CAPA责任人"
    )
    corrective_action_status: Mapped[str | None] = mapped_column(
        String(32), default="pending", nullable=True, comment="CAPA状态: pending/in_progress/completed/verified"
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="CAPA验证人"
    )
    verified_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="验证人姓名")
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="验证时间"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="reported", server_default="reported", nullable=False,
        comment="状态: reported/investigating/investigated/capa_in_progress/closed"
    )
    reported_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="报告人"
    )
    reported_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="报告人姓名")
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="报告时间"
    )
    investigator: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="调查人"
    )
    investigator_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="调查人姓名")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 安全培训 ====================


class SafetyTraining(BaseModel):
    """安全培训表"""

    __tablename__ = "safety_trainings"
    __table_args__ = (
        Index("uq_safety_trainings_training_no", "training_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    training_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="培训编号")
    training_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="培训名称")
    training_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="annual", comment="培训类型"
    )
    training_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="offline", comment="培训方式"
    )
    training_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="dept", server_default="dept", comment="培训级别: company/dept/team"
    )
    trainer: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="培训讲师"
    )
    trainer_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="讲师姓名")
    training_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="培训日期"
    )
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True, comment="培训时长(小时)")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="培训地点")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="培训内容")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="培训部门")
    exam_passing_score: Mapped[float | None] = mapped_column(
        Float, default=60, server_default="60", nullable=True, comment="及格分数线"
    )
    course_material_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="课程资料路径"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, comment="状态"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    records: Mapped[list["TrainingRecord"]] = relationship(
        "TrainingRecord", back_populates="training", lazy="selectin"
    )


class TrainingRecord(BaseModel):
    """培训记录（签到/考核）子表"""

    __tablename__ = "training_records"
    __table_args__ = {"schema": "safety"}

    training_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.safety_trainings.id"),
        nullable=False,
        comment="培训ID",
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="员工ID"
    )
    employee_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="员工姓名")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门")
    position: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="岗位")
    attendance: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否出席")
    score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="考核成绩")
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="是否合格")
    certificate_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="证书编号")
    certificate_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="证书有效期至"
    )
    certificate_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="证书状态: valid/expiring/expired"
    )
    certificate_file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="证书文件路径"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    training: Mapped["SafetyTraining"] = relationship("SafetyTraining", back_populates="records")


# ==================== 危险源辨识 ====================


class HazardIdentification(BaseModel):
    """危险源辨识与评价表"""

    __tablename__ = "hazard_identifications"
    __table_args__ = (
        Index("uq_hazard_identifications_no", "hazard_id_no", unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_hazard_identifications_regulation_batch", "regulation_id", "batch_id"),
        {"schema": "safety"},
    )

    # ── 基础信息（人工输入） ──
    hazard_id_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="危险源编号")
    department: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门")
    position: Mapped[str] = mapped_column(String(100), nullable=False, comment="岗位")
    production_step: Mapped[str] = mapped_column(Text, nullable=False, comment="生产步骤")
    attachment_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="岗位资料附件路径"
    )
    attachment_original_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="附件原始文件名"
    )
    regulation_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="引用的安全操作规程 ID（替代附件上传）"
    )
    regulation_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="引用的安全操作规程名称"
    )

    # ── 多工段辨识（batch / per-stage）──
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="批次ID，同一regulation多工段同时创建时共享"
    )
    stage_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="工艺阶段名称（Chapter 7 H2 标题）"
    )
    chapter7_context: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="该工段对应的 Chapter 7 节选 Markdown（供Script 1使用）"
    )

    # ── 脚本1 输出：附件解析（AI → 人工审核） ──
    specific_activity: Mapped[str | None] = mapped_column(Text, nullable=True, comment="具体作业活动")
    equipment_facilities: Mapped[str | None] = mapped_column(Text, nullable=True, comment="设备设施")
    raw_auxiliary_materials: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原辅料")
    operation_frequency: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业频次"
    )
    operator_count: Mapped[int | None] = mapped_column(nullable=True, comment="操作人数")

    # ── 脚本2 输出：AI危险源辨识（AI → 人工审核） ──
    hazard_type: Mapped[str | None] = mapped_column(Text, nullable=True, comment="危险类型（人机料法环）")
    possible_accident: Mapped[str | None] = mapped_column(Text, nullable=True, comment="可能导致事故")
    unsafe_behavior: Mapped[str | None] = mapped_column(Text, nullable=True, comment="不规范作业行为表现")

    # ── 脚本3 输出：固有风险 LEC（AI → 人工审核） ──
    l_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="可能性L（固有）")
    e_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="暴露频率E（固有）")
    c_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="严重性C（固有）")
    d_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="风险值D（固有）")
    inherent_risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="固有风险等级"
    )
    inherent_risk_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="固有风险等级中文名"
    )

    # ── 脚本4 输出：现有控制措施（AI → 人工审核） ──
    existing_engineering_controls: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有工程控制措施"
    )
    existing_management_controls: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有管理控制措施"
    )
    existing_ppe: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有个人防护措施"
    )
    existing_emergency_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有应急措施"
    )

    # ── 脚本5 输出：残余风险（AI → 人工审核） ──
    l_residual: Mapped[float | None] = mapped_column(nullable=True, comment="可能性L（残余）")
    e_residual: Mapped[float | None] = mapped_column(nullable=True, comment="暴露频率E（残余）")
    c_residual: Mapped[float | None] = mapped_column(nullable=True, comment="严重性C（残余）")
    d_residual: Mapped[float | None] = mapped_column(nullable=True, comment="风险值D（残余）")
    residual_risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="残余风险等级"
    )
    residual_risk_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="残余风险等级中文名"
    )

    # ── 脚本6 输出：建议措施（AI → 人工审核） ──
    needs_recommendation: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="是否需提出建议措施（是/否/待人工确认）"
    )
    recommendation_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="建议措施类型"
    )
    recommendation_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="建议措施内容"
    )
    recommendation_priority: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="建议措施优先级（高/中/低）"
    )

    # ── 脚本7 输出：建议措施后风险（AI → 人工审核） ──
    l_post: Mapped[float | None] = mapped_column(nullable=True, comment="可能性L（建议措施后）")
    e_post: Mapped[float | None] = mapped_column(nullable=True, comment="暴露频率E（建议措施后）")
    c_post: Mapped[float | None] = mapped_column(nullable=True, comment="严重性C（建议措施后）")
    d_post: Mapped[float | None] = mapped_column(nullable=True, comment="风险值D（建议措施后）")
    post_risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="建议措施后风险等级"
    )
    post_risk_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="建议措施后风险等级中文名"
    )

    # ── 管控层级（根据风险等级自动填充） ──
    control_level: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="管控层级（公司级/部门级/班组级）"
    )
    responsible_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="责任人"
    )

    # ── AI 流程状态 ──
    ai_node_progress: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending_input",
        server_default="pending_input",
        comment="AI流程节点进度",
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 脚本执行错误信息"
    )
    overall_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="整体状态（draft/in_progress/completed/cancelled）",
    )

    # ── 各脚本人工审核状态 ──
    script1_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本1审核状态"
    )
    script2_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本2审核状态"
    )
    script3_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本3审核状态"
    )
    script4_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本4审核状态"
    )
    script5_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本5审核状态"
    )
    script6_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本6审核状态"
    )
    script7_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本7审核状态"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 安全操作规程 ====================


class OperationRegulation(BaseModel):
    """安全操作规程表 - 操规文档管理主表"""

    __tablename__ = "operation_regulations"
    __table_args__ = (
        Index("uq_operation_regulations_no", "regulation_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    regulation_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="操规编号")
    regulation_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="操规名称")
    document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="操规文档路径（当前最新版本）"
    )
    document_original_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="文档原始文件名"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位（达托/达巴，逗号分隔）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 标准化生成字段 ──
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="标准化 Markdown 内容（9 章完整操规）"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=RegulationStatus.DRAFT.value,
        server_default="draft",
        nullable=False,
        comment="操规状态: draft/generated/reviewed/exported",
    )
    source_document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="原始上传的旧版操规文件路径"
    )

    # 关系
    revisions: Mapped[list["RegulationRevision"]] = relationship(
        "RegulationRevision", back_populates="regulation", lazy="selectin"
    )


# ==================== 操规修订记录 ====================


class RegulationRevision(BaseModel):
    """修订记录表 - 修订流程记录"""

    __tablename__ = "regulation_revisions"
    __table_args__ = (
        Index("uq_regulation_revisions_no", "revision_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    revision_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="修订编号")
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.operation_regulations.id"),
        nullable=False,
        comment="关联操规ID",
    )
    regulation_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="安全操规名称")
    old_document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="旧文档路径"
    )
    reviser: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="修订人"
    )
    reviser_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="修订人姓名")
    revision_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="修订时间"
    )
    revision_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual", comment="修订类型: manual/ai"
    )
    revision_opinion: Mapped[str | None] = mapped_column(Text, nullable=True, comment="修订意见/内容")
    revision_scope: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="修订范围（逗号分隔: process/safety_requirement）"
    )
    review_opinion: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False, comment="审核意见: pending/approved"
    )
    new_document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="新文档路径"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    regulation: Mapped["OperationRegulation"] = relationship(
        "OperationRegulation", back_populates="revisions"
    )


# ==================== 特殊作业人员资质 ====================


class SpecialOperationPersonnel(BaseModel):
    """特殊作业人员资质表"""

    __tablename__ = "special_operation_personnel"
    __table_args__ = (
        Index("uq_special_op_personnel_no", "personnel_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    personnel_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="人员编号")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="姓名")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="所属部门")
    certificate_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="证书类型（对应8种特殊作业）"
    )
    certificate_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="证书编号"
    )
    issuing_authority: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="发证机关"
    )
    issue_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发证日期"
    )
    expiry_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="有效期至"
    )
    certificate_file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="证书文件路径"
    )
    qualification_scope: Mapped[str | None] = mapped_column(Text, nullable=True, comment="资质范围")
    status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active", nullable=False,
        comment="状态: active/expired/revoked"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 特殊作业票 ====================


class SpecialOperationPermit(BaseModel):
    """特殊作业票表"""

    __tablename__ = "special_operation_permits"
    __table_args__ = (
        Index("uq_special_op_permits_permit_no", "permit_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    permit_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="作业票编号")
    operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="作业类型（8种）"
    )
    operation_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="grade2", server_default="grade2",
        comment="作业级别: special/grade1/grade2"
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业地点")
    equipment_tag: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="设备位号"
    )
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作业内容描述")
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    actual_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始时间"
    )
    actual_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际结束时间"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请人姓名"
    )
    work_leader_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业负责人姓名"
    )
    operator_names: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="作业人员姓名（逗号分隔）"
    )
    guardian_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="监护人姓名"
    )
    approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批人姓名"
    )
    safety_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="安全措施")
    emergency_equipment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急消防器材"
    )
    gas_analysis: Mapped[str | None] = mapped_column(Text, nullable=True, comment="气体分析结果")
    risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="风险评估")
    safety_briefing_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="安全交底确认"
    )
    safety_briefing_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="安全交底时间"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="驳回原因")
    completion_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="完工方式: normal/early_termination"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, comment="状态"
    )
    check_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.safety_checks.id"), nullable=True,
        comment="关联安全检查ID"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 安全知识库 ====================


class SafetyKnowledgeArticle(BaseModel):
    """安全知识库文章表"""

    __tablename__ = "knowledge_articles"
    __table_args__ = {"schema": "safety"}

    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="文章标题")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="正文内容")
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="标签（逗号分隔）")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="other", server_default="other", comment="分类"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False,
        comment="状态: draft/published/archived"
    )
    view_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False, comment="浏览次数"
    )
    attachment_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="附件路径"
    )
    attachment_original_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="附件原始文件名"
    )
    # ── AI 知识增强字段 ──
    knowledge_card: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="AI 知识卡片 JSON（结构化法规摘要，供 AI 识别注入 prompt）"
    )
    card_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="知识卡片生成时间"
    )
    card_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False, comment="知识卡片版本号"
    )


# ==================== 风险作业报备 ====================


class SpecialOperationReport(BaseModel):
    """八大特殊作业报备表"""

    __tablename__ = "special_operation_reports"
    __table_args__ = (
        Index("uq_special_operation_reports_no", "report_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="报备编号")
    permit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.special_operation_permits.id"),
        nullable=True,
        comment="关联作业票ID",
    )
    operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="作业类型（8种）"
    )
    operation_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="grade2", server_default="grade2",
        comment="作业级别: special/grade1/grade2"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="报备部门")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业地点")
    equipment_tag: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="设备位号"
    )
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作业内容描述")
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    work_leader_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业负责人姓名"
    )
    operator_names: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="作业人员姓名（逗号分隔）"
    )
    guardian_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="监护人姓名"
    )
    risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="风险等级: level_1/level_2/level_3/level_4"
    )
    safety_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="安全措施")
    emergency_equipment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急消防器材"
    )
    gas_analysis: Mapped[str | None] = mapped_column(Text, nullable=True, comment="气体分析结果")
    risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="风险评估描述")
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="报备申请人姓名"
    )
    approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批人姓名"
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="驳回原因")
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False,
        comment="状态: draft/submitted/approved/rejected"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    is_critical: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="是否关键作业（AI自动判定+可手动修改）"
    )
    is_critical_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关键作业判定理由"
    )
    is_critical_updated_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="手动修改关键作业标记的操作人"
    )

    # 关系
    permit: Mapped["SpecialOperationPermit | None"] = relationship(
        "SpecialOperationPermit", foreign_keys=[permit_id]
    )


class DailyRiskReport(BaseModel):
    """每日风险作业报备表"""

    __tablename__ = "daily_risk_reports"
    __table_args__ = (
        Index("uq_daily_risk_reports_no", "report_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="报备编号")
    report_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="报备作业日期"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="报备部门")
    hazard_identification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.hazard_identifications.id"),
        nullable=True,
        comment="关联危险源辨识ID",
    )
    operation_description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="风险作业描述"
    )
    operation_steps: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作业步骤")
    hazard_factors: Mapped[str | None] = mapped_column(Text, nullable=True, comment="危险因素")
    risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="风险等级: level_1/level_2/level_3/level_4"
    )
    control_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="控制措施")
    responsible_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业负责人"
    )
    operator_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="作业人数")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业地点")
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="报备申请人姓名"
    )
    approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批人姓名"
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="驳回原因")
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False,
        comment="状态: draft/submitted/approved/rejected"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    hazard_identification: Mapped["HazardIdentification | None"] = relationship(
        "HazardIdentification", foreign_keys=[hazard_identification_id]
    )


# ==================== EHS变更管理 (MOC) ====================


class EhsChange(BaseModel):
    """EHS变更管理 / Management of Change（基于 T/CCSAS 007-2020）"""

    __tablename__ = "ehs_changes"
    __table_args__ = (
        Index("uq_ehs_changes_change_no", "change_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety", "comment": "EHS变更管理表"},
    )

    # ── 核心标识 ──
    change_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="变更编号"
    )

    # ── 基础信息 ──
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="变更标题"
    )
    change_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="变更类型: process_tech/equipment_facility/management"
    )
    change_grade: Mapped[str] = mapped_column(
        String(16), nullable=False, default="general", server_default="general", comment="变更等级: major/general"
    )
    change_duration: Mapped[str] = mapped_column(
        String(16), nullable=False, default="permanent", server_default="permanent", comment="变更期限: permanent/temporary/emergency"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请部门"
    )
    location_unit: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="所在单元/装置"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="变更描述（变更前/变更后对比）"
    )
    technical_basis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="变更技术依据"
    )
    expected_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="预期开始日期"
    )
    expected_completion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="预期完成日期"
    )
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始日期"
    )
    actual_completion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际完成日期"
    )
    expected_effect: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="预期效果"
    )

    # ── 状态与申请人 ──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", comment="状态"
    )
    applicant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="申请人ID"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请人姓名"
    )

    # ── JSON 辅助字段 ──
    equipment_tags: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="关联设备位号 JSON数组"
    )
    documents_to_update: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="需更新的文件清单 JSON数组 [{name, number}]"
    )
    attachments: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="附件列表 JSON数组 [{name, path}]"
    )

    # ── JSON 子记录 ──
    risk_assessments: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="风险评估 JSON数组 [{method, severity, likelihood, risk_level, description, control_measures, assessed_by, assessed_date, participants}]"
    )
    approval_chain: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="审批链 JSON数组 [{level, approver_role, approver, decision, comments, decided_at}]"
    )
    action_items: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="行动项 JSON数组 [{task, owner, due_date, status, completed_at}]"
    )
    pssr_checklist: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="PSSR清单 JSON数组 [{item, result, checked_by, checked_at, remarks}]"
    )
    verification: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="变更验证 {expected_effect_achieved, comments, psi_updated, documents_updated, accepted_by, accepted_date}"
    )
    closure: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="变更关闭 {closed_by, closed_date, temp_expiry_date, restored_date}"
    )

    # ── 关联 ──
    linked_safety_check_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.safety_checks.id"), nullable=True, comment="关联安全检查ID（变更验收）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 关系 ──
    applicant: Mapped["User | None"] = relationship(
        "app.platform.identity.models.User", foreign_keys=[applicant_id]
    )
    linked_safety_check: Mapped["SafetyCheck | None"] = relationship(
        "SafetyCheck", foreign_keys=[linked_safety_check_id]
    )


# ==================== 职业危害因素监测 ====================


class OhHazardMonitor(BaseModel):
    """职业危害因素监测 / Occupational Hazard Factor Monitoring（基于 GBZ 159, GBZ 2.1/2.2）"""

    __tablename__ = "oh_hazard_monitors"
    __table_args__ = (
        Index("uq_oh_hazard_monitors_monitor_no", "monitor_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety", "comment": "职业危害因素监测表"},
    )

    # ── 核心标识 ──
    monitor_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="监测编号"
    )

    # ── 监测点信息 ──
    workplace: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="监测场所/车间"
    )
    location: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="具体监测点位"
    )
    equipment_info: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="关联设备/岗位"
    )

    # ── 检测信息 ──
    detection_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="检测类型: regular/commissioned/evaluation/accident"
    )
    detection_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="检测日期"
    )
    detection_agency: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="检测机构"
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", comment="状态"
    )

    # ── 责任人 ──
    inspector_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="检测人员"
    )
    verifier_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="验证人员"
    )

    # ── JSON 子记录：检测结果数组 ──
    detection_results: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="检测结果 JSON数组 [{factor_name, factor_category, detection_value, unit, oel_limit, compliance_status, sampling_method, standard_ref}]"
    )

    # ── JSON：异常处置记录 ──
    abnormality_records: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="异常处置记录 JSON数组 [{abnormality_desc, corrective_action, responsible_person, deadline, status, completed_at, remarks}]"
    )

    # ── JSON：附件 ──
    attachments: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="附件列表 JSON数组 [{name, path}]"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 职业健康体检 ====================


class OhHealthExam(BaseModel):
    """职业健康体检管理 / Occupational Health Examination Management（基于 GBZ 188）"""

    __tablename__ = "oh_health_exams"
    __table_args__ = (
        Index("uq_oh_health_exams_exam_no", "exam_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety", "comment": "职业健康体检表"},
    )

    # ── 核心标识 ──
    exam_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="体检编号"
    )

    # ── 人员信息 ──
    employee_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="员工姓名"
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="关联用户ID"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    job_position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位"
    )

    # ── 体检类型与状态 ──
    exam_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="体检类型: pre_employment/periodic/post_employment/emergency"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="scheduled", server_default="scheduled", comment="状态"
    )

    # ── 体检信息 ──
    exam_agency: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="体检机构"
    )
    scheduled_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划体检日期"
    )
    exam_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际体检日期"
    )
    report_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="报告日期"
    )

    # ── 暴露因素关联 ──
    hazard_factors: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="关联的危害因素列表 [string]"
    )

    # ── 个人体检结论 ──
    overall_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="综合体检结论"
    )

    # ── JSON 子记录：体检项目结果 ──
    exam_items: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="体检项目结果 JSON数组 [{item_name, category, result, reference_range, is_abnormal, remarks}]"
    )

    # ── JSON：异常处置记录 ──
    abnormality_records: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="异常处置记录 JSON数组"
    )

    # ── JSON：附件 ──
    attachments: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="附件列表"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 承包商管理 ====================


class Contractor(BaseModel):
    """承包商管理表"""

    __tablename__ = "contractors"
    __table_args__ = (
        Index("uq_contractors_contractor_no", "contractor_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    contractor_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="承包商编号")
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="公司名称")
    legal_representative: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="法定代表人"
    )
    contact_person: Mapped[str] = mapped_column(String(100), nullable=False, comment="联系人")
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="联系电话")
    business_scope: Mapped[str | None] = mapped_column(Text, nullable=True, comment="经营范围")
    qualification_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="other", server_default="other", comment="资质类型"
    )
    qualification_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="资质等级: grade_a/grade_b/grade_c"
    )
    qualification_cert_no: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="资质证书编号"
    )
    qualification_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="资质有效期至"
    )
    safety_license_no: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="安全生产许可证编号"
    )
    safety_license_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="安全生产许可证有效期"
    )
    insurance_info: Mapped[str | None] = mapped_column(Text, nullable=True, comment="保险信息")
    insurance_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="保险有效期至"
    )
    safety_officer_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="安全负责人"
    )
    safety_officer_phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="安全负责人电话"
    )
    special_op_personnel: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="特种作业人员列表 [{\"name\",\"cert_type\",\"cert_no\",\"expiry\"}]"
    )
    training_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="untrained", server_default="untrained",
        comment="培训状态: untrained/in_progress/passed/expired"
    )
    training_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近培训日期"
    )
    safety_performance_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="安全绩效评分（0-100）"
    )
    blacklisted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, comment="是否黑名单"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active",
        comment="状态: active/inactive/blacklisted"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    work_records: Mapped[list["ContractorWorkRecord"]] = relationship(
        "ContractorWorkRecord", back_populates="contractor", lazy="selectin"
    )


class ContractorWorkRecord(BaseModel):
    """施工记录表（承包商子表）"""

    __tablename__ = "contractor_work_records"
    __table_args__ = {"schema": "safety"}

    contractor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.contractors.id"),
        nullable=False,
        comment="关联承包商ID",
    )
    work_content: Mapped[str] = mapped_column(Text, nullable=False, comment="施工内容")
    work_location: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="施工地点"
    )
    planned_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="计划开始时间"
    )
    planned_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="计划结束时间"
    )
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始时间"
    )
    actual_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际结束时间"
    )
    permit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.special_operation_permits.id"),
        nullable=True,
        comment="关联特殊作业票ID",
    )
    leading_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="带班负责人"
    )
    worker_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="施工人数")
    safety_briefing_done: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="安全交底确认"
    )
    violations: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="违章记录 [{\"date\",\"description\",\"severity\",\"handler\",\"result\"}]"
    )
    evaluation: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="评价 {\"score\",\"comments\",\"evaluator\",\"date\"}"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="in_progress", server_default="in_progress",
        comment="状态: in_progress/completed/evaluated"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    contractor: Mapped["Contractor"] = relationship(
        "Contractor", back_populates="work_records"
    )
    permit: Mapped["SpecialOperationPermit | None"] = relationship(
        "SpecialOperationPermit", foreign_keys=[permit_id]
    )
