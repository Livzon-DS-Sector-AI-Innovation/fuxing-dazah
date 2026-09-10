"""Safety ORM models."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.identity.models import User
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。

# ==================== Enums ====================


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
    AI_REVIEWED = "ai_reviewed"  # AI 审核修正完成
    REVIEWED = "reviewed"    # 人工编辑审核完成
    EXPORTED = "exported"    # 已导出 PDF


class ReportStatus(str, PyEnum):
    """报备状态枚举"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class AdmissionReviewStatus(str, PyEnum):
    """相关方准入 AI 审核状态（平台内部状态机，英文 value）"""

    NONE = "none"            # 未审核
    PROCESSING = "processing"  # 审核中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败（可重审）


class AdmissionConclusion(str, PyEnum):
    """相关方准入 AI 审核总体结论（中文 value，与 Bitable 单选选项一致，回填直传）"""

    APPROVED = "审核通过"
    NEEDS_SUPPLEMENT = "需补充完善"
    REJECTED = "审核不通过"


class RelatedPartyType(str, PyEnum):
    """相关方类型（中文 value，与 Bitable 单选选项一致）"""

    CONTRACTOR = "承包商"
    COOPERATIVE = "合作类相关方"
    LABOR_DISPATCH = "劳务派遣"
    OTHER = "其他相关方"


class AdmissionSubmitStatus(str, PyEnum):
    """提交状态（中文 value，与 Bitable 单选选项一致）"""

    COMPLETED = "已完成"
    IN_PROGRESS = "进行中"
    NOT_STARTED = "未开始"


class AdmissionTrainingStatus(str, PyEnum):
    """培训状态（中文 value，与 Bitable 单选选项一致）"""

    COMPLETED = "已完结"
    TRAINED_NEED_MATERIAL = "已培训待补材"
    NOT_TRAINED = "未培训"


# ==================== 安全检查 ====================


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
    hazard_level_manual: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="隐患等级（人工）：一般隐患/较大隐患/重大隐患（Bitable 隐患级别字段同步，督办判定以此为准）"
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
    defect_substance: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="缺陷实质评估: substantive / procedural / uncertain"
    )
    defect_substance_reasoning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="缺陷实质评估理由"
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
    ai_review_result: Mapped[dict[str, Any] | None] = mapped_column(
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

    # ── 督办等级 ──
    supervision_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="督办等级: 红色预警 / 一般预警 / closed(已关闭)"
    )

    # ── 督办进展监控（「未更新进展」机制）──
    progress_note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="目前进展（Bitable「目前进展」字段同步，责任人填写的整改进展）"
    )
    progress_note_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="目前进展最后更新时间（Bitable 同步落库时刻，进展内容变化时记录）"
    )
    supervision_progress_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="督办进展状态: 未更新进展 / NULL(正常)"
    )



# ==================== 事故管理 ====================


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
        Index("uq_hazard_identifications_feishu_id", "feishu_record_id", unique=True, postgresql_where=text("feishu_record_id IS NOT NULL AND is_deleted = false")),
        Index("ix_hazard_identifications_regulation_batch", "regulation_id", "batch_id"),
        {"schema": "safety"},
    )

    # ── 基础信息（人工输入） ──
    hazard_id_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="危险源编号")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门（Bitable 无此字段，镜像时从提交人员派生）")
    position: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="岗位")
    production_step: Mapped[str | None] = mapped_column(Text, nullable=True, comment="生产步骤")
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

    # ── 脚本3.5 输出：福建固有风险等级（脚本3 附属，不进状态机/审核） ──
    inherent_risk_level_fj: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="固有风险等级（福建）"
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

    # ── Bitable 镜像同步（危险源辨识自动化多维表格）──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    feishu_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="飞书 Bitable 记录 URL"
    )
    feishu_table_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 表 ID"
    )
    submitter_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="提交人员姓名"
    )
    submitter_feishu_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="提交人员飞书 ID"
    )
    reviewer_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审核人员姓名"
    )
    reviewer_feishu_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审核人员飞书 ID"
    )
    # ── 脚本8：四类排查内容（AI 生成 + 人工审核 各一列）──
    engineering_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工程措施排查内容（AI）"
    )
    engineering_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工程措施排查内容（人工）"
    )
    management_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="管理措施排查内容（AI）"
    )
    management_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="管理措施排查内容（人工）"
    )
    ppe_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="个人防护措施排查内容（AI）"
    )
    ppe_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="个人防护措施排查内容（人工）"
    )
    emergency_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急措施排查内容（AI）"
    )
    emergency_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急措施排查内容（人工）"
    )
    bitable_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Bitable 完整字段快照（AI/人工双份 + 公式结果）"
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

    # ── AI 审核字段（生成后对照源文档审核，落库审核状态与说明）──
    ai_review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
        comment="AI 审核状态: pending/reviewing/completed/failed",
    )
    ai_review_note: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="AI 审核说明 {summary, dimensions, chapter_fixes, reviewed_at}",
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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 安全知识库 ====================


class SafetyKnowledgeArticle(BaseModel):
    """安全知识库文章表"""

    __tablename__ = "knowledge_articles"
    __table_args__ = {"schema": "safety"}

    # ── Columns present in DB ──
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

    article_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="文档编号")
    feishu_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True, comment="飞书Bitable记录ID")
    source: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="来源/出处")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作者/发布单位")
    publish_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, comment="发布日期")
    implementation_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, comment="实施日期")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False, comment="版本号")
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, comment="被替代为（指向新版本文档）")
    knowledge_card: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="知识卡片JSON")
    card_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="卡片生成时间")
    card_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False, comment="知识卡片版本号")
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="全文内容")
    full_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="全文Hash")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False, comment="chunk数量")
    feishu_table_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="飞书多维表格ID")
    feishu_shared_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="飞书记录分享链接")


class RegulationChunk(BaseModel):
    """法规条款分块（RAG 检索目标）"""

    __tablename__ = "regulation_chunks"
    __table_args__ = (
        Index("ix_regulation_chunks_article_id", "article_id"),
        Index("ix_regulation_chunks_chunk_index", "chunk_index"),
        Index("ix_regulation_chunks_doc_category", "doc_category"),
        Index("ix_regulation_chunks_priority", "priority"),
        {"schema": "safety"},
    )

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.knowledge_articles.id"), nullable=False,
        comment="所属法规文档 ID",
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, comment="条款原文")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="在文档中的序号")
    doc_title: Mapped[str] = mapped_column(String(500), nullable=False, comment="文档标题")
    doc_category: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="文档类别")
    chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="章节标题")
    article_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="条款编号")
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True, comment="向量嵌入（JSON 数组字符串）")
    priority: Mapped[str] = mapped_column(
        String(2), nullable=False, default="P2", server_default="P2", comment="优先级"
    )
    cites_chunk_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="引用的其他 chunk ID")
    cited_by_chunk_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="被其他 chunk 引用")
    entity_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="关联实体 ID 列表")


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

    # ── Bitable 同步字段 ──

    source: Mapped[str] = mapped_column(
        String(16), default="manual", server_default="manual", nullable=False,
        comment="数据来源: manual(手动)/bitable(飞书同步)"
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    personnel_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="作业人员类型: 公司人员/非公司人员/其他相关方"
    )
    work_duration_hours: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="作业时长（小时）"
    )
    has_other_operations: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="是否涉及其他特殊作业: 是/否"
    )
    other_operation_types: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="涉及特殊作业类型列表"
    )
    is_weekend_holiday: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="周末节假日/非上班时段: 是/否"
    )
    is_national_holiday: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="是否国家法定节假日: 是/否"
    )
    holiday_period: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="非上班时间段/节假日"
    )
    report_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="报备类型: planned/unplanned"
    )
    initiator_department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发起人部门"
    )
    initiator_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发起人姓名"
    )
    approver_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="作业票审批人类型"
    )
    safety_approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="安全工程中心审批人姓名"
    )
    approval_no: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="飞书申请编号（审批 URL）"
    )
    work_plan_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="作业计划 URL"
    )
    work_scheme_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="作业方案 URL"
    )
    approved_permit_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="已签批的特殊作业票及关联票 URL"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发起时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间"
    )
    approval_node: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="当前审批节点"
    )

    # ── V3.5 新增字段（Bitable 同步）──

    fire_work_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="动火方式: 电焊/气割/氩弧焊/切割机/电钻/塑料焊/其他"
    )
    height_work_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="高处作业方式（多选）"
    )
    work_height: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="作业高度(米)"
    )
    lifting_weight: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="吊物质量(吨)"
    )
    contractor_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="施工单位"
    )

    # ── 日报分析字段 ──

    daily_risk_level: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="日报风险等级: high/medium/low"
    )
    daily_risk_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="日报风险判定依据"
    )
    inferred_operation_types: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="AI 推断的额外特殊作业类型"
    )
    inferred_operation_detail: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 类型推断说明"
    )
    is_excluded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="是否被日报排除规则过滤"
    )
    exclusion_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="日报排除原因"
    )
    daily_report_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="所属日报日期"
    )

    # 关系
    permit: Mapped["SpecialOperationPermit | None"] = relationship(
        "SpecialOperationPermit", foreign_keys=[permit_id]
    )


class KeyRiskOperationReport(BaseModel):
    """每日关键风险操作预报备表（飞书 Bitable 同步，只读）。

    数据源: 飞书多维表格「每日关键风险操作预报备（审批）」
    base: LTZ1buQJaaLMxKsNcF2c13QPnrh / 表: tblEnatX5fxfwMlI
    同步以 feishu_record_id 为主键 upsert，平台侧只读展示，不提供审批。
    """

    __tablename__ = "key_risk_operation_reports"
    __table_args__ = (
        Index(
            "uq_key_risk_operation_reports_no", "report_no",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_key_risk_op_feishu_record_id", "feishu_record_id",
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    # ── 来源与主键 ──
    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="申请编号文本（如 202511280372）")
    approval_no_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="申请编号链接")
    source: Mapped[str] = mapped_column(
        String(16), default="bitable", server_default="bitable", nullable=False,
        comment="数据来源: bitable(飞书同步)",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）")

    # ── 审批字段 ──
    apply_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="申请状态: 已通过/审批中/已拒绝/已取消/已终止/已撤回")
    approval_node: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="审批节点")
    approval_flow: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="审批流程名称")
    current_handler: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="当前处理人")
    initiator_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="发起人姓名")
    initiator_department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="发起人部门")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发起时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="完成时间")

    # ── 作业主信息 ──
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门")
    area: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="区域")
    operation_content: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业内容")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="作业开始时间")
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="作业结束时间")
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True, comment="作业时长（小时）")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 安全措施（主作业）──
    personal_protection: Mapped[str | None] = mapped_column(Text, nullable=True, comment="个人防护")
    preparation_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="准备措施")
    operation_precautions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作注意事项")
    emergency_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="应急措施")
    guardian: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="现场作业监护人")
    site_guardian: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="现场监护人（User）")
    dept_safety_officer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门安全员（User）")

    # ── 多作业块（xxx1/xxx2 → 最多 2 条附加作业）──
    operations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="附加作业块数组[{department,area,operation_content,personal_protection,preparation_measures,operation_precautions,emergency_measures,guardian,time_slot}]")

    # ── 三阶段现场确认 ──
    phase_before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="作业前现场确认 {date,photo_url,issue_desc}")
    phase_ongoing: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="作业中现场确认 {date,photo_url,issue_desc}")
    phase_after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="作业后现场确认 {date,photo_url,issue_desc}")

    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="飞书 SourceID")


# ==================== EHS变更管理 (MOC) ====================


class EhsChange(BaseModel):
    """EHS变更管理 / Management of Change（基于 T/CCSAS 007-2020）"""

    __tablename__ = "ehs_changes"
    __table_args__ = (
        Index("uq_ehs_changes_change_no", "change_no", unique=True, postgresql_where=text("is_deleted = false")),
        Index("uq_ehs_changes_feishu_record_id", "feishu_record_id", unique=True, postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL")),
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
    change_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="变更类型: process_tech/equipment_facility/management（Bitable 验收表无此列可为空）"
    )
    change_grade: Mapped[str] = mapped_column(
        String(16), nullable=False, default="general", server_default="general", comment="变更等级: major/general"
    )
    change_duration: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="变更期限: permanent/temporary/emergency（Bitable 验收表无此列可为空）"
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
    equipment_tags: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="关联设备位号 JSON数组"
    )
    documents_to_update: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="需更新的文件清单 JSON数组 [{name, number}]"
    )
    attachments: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="附件列表 JSON数组 [{name, path}]"
    )

    # ── JSON 子记录 ──
    risk_assessments: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="风险评估 JSON数组 [{method, severity, likelihood, risk_level, description, control_measures, assessed_by, assessed_date, participants}]"
    )
    approval_chain: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="审批链 JSON数组 [{level, approver_role, approver, decision, comments, decided_at}]"
    )
    action_items: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="行动项 JSON数组 [{task, owner, due_date, status, completed_at}]"
    )
    pssr_checklist: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="PSSR清单 JSON数组 [{item, result, checked_by, checked_at, remarks}]"
    )
    verification: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="变更验证 {expected_effect_achieved, comments, psi_updated, documents_updated, accepted_by, accepted_date}"
    )
    closure: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="变更关闭 {closed_by, closed_date, temp_expiry_date, restored_date}"
    )

    # ── 关联 ──
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── Bitable 同步字段 ──
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual",
        comment="数据来源: manual(手动)/bitable(飞书同步)",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    feishu_table_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="飞书表类型: approval(变更审批)/acceptance(变更验收)"
    )
    bt_change_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 变更申请编号/变更编号（展示用）"
    )
    bt_change_status: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 变更状态（待安装/问题整改中等，审批表专用）"
    )
    bt_plan_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bitable 变更计划内容（审批表专用）"
    )
    bt_risk_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bitable 变更风险评估及建议措施（审批表专用）"
    )
    bt_acceptance_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bitable 验收意见（验收表专用，可另附验收报告）"
    )
    bt_extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Bitable 其他字段 JSONB（can_reflect/gmp_change_no/current_handler/approval_node/source_id/related_approval/approval_flow/acceptance_date）"
    )
    ai_review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", server_default="none",
        comment="AI审核状态: none/completed（审批表专用）",
    )
    ai_review_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="AI审核结果 JSONB（审批表四维度）{reason:{conclusion,report}, plan:{...}, effect:{...}, risk:{...}, pre_review:..., regulations:[...]}"
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI审核失败信息（failed 时记录，completed 时清空）"
    )

    # ── 关系 ──
    applicant: Mapped["User | None"] = relationship(
        "app.platform.identity.models.User", foreign_keys=[applicant_id]
    )


# ==================== 职业健康管理（OH） ====================
# 数据源：飞书多维表格 Bitable 业务表（Bitable 镜像），safety schema。
# 软删除铁律：唯一约束全部使用部分唯一索引（WHERE is_deleted = false），
# 软删时清空唯一键字段 + 置 is_deleted=true（见 CLAUDE.md「软删除隐形 bug」注意事项）。
# 不建数据库级外键（CLAUDE.md 铁律），关联键以 UUID 列承载（无 FK）。


class OhPerson(BaseModel):
    """职业健康人员汇总台账（Bitable 镜像，一人一条）"""

    __tablename__ = "oh_persons"
    __table_args__ = (
        Index("uq_oh_persons_name_idcard", "name", "id_card_no",
              unique=True, postgresql_where=text("is_deleted = false AND id_card_no IS NOT NULL")),
        Index("uq_oh_persons_employee_no", "employee_no",
              unique=True, postgresql_where=text("is_deleted = false AND employee_no IS NOT NULL")),
        Index("ix_oh_persons_feishu", "feishu_record_id"),
        Index("ix_oh_persons_dept", "department"),
        {"schema": "safety", "comment": "职业健康人员汇总台账（Bitable 镜像）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（同步主键）"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )

    # ── 人员信息 ──
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="员工姓名"
    )
    id_card_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证号（关联键，98% 覆盖）"
    )
    employee_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="工号（业务键，43% 缺失）"
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 identity.users.id（无 FK，可空）"
    )
    open_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 open_id（Bitable 人员字段解析）"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位"
    )
    gender: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="性别"
    )
    age: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="年龄（Bitable 公式同步）"
    )
    marital_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="婚姻状况"
    )
    phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="电话"
    )
    total_work_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="总工龄（年.月折算）"
    )
    hazard_exposure_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="接害工龄（年.月折算）"
    )

    # ── 危害因素与体检状态（平台回填）──
    hazard_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="接触危害因素 [标准名]（按岗位从 oh_positions 同步）"
    )
    last_exam_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后体检时间（平台回填）"
    )
    last_exam_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="最后体检类别: pre_employment/periodic/post_employment/transfer/emergency"
    )
    last_exam_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="最后体检结论（ai_conclusion 归一）"
    )
    last_exam_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最后体检摘要（AI summary_text）"
    )
    exam_record_ids: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="体检记录 ID 数组（对应 Bitable link 关联）"
    )
    safety_officer: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门安全员（与申请表对齐）"
    )
    work_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="在岗状态: on_post/off_post/pre_employment/transfer（原「最后体检状态」更名）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhHealthExam(BaseModel):
    """职业健康体检记录（Bitable 镜像 + AI 解析字段）"""

    __tablename__ = "oh_health_exams"
    __table_args__ = (
        Index("uq_oh_health_exams_exam_no", "exam_no",
              unique=True, postgresql_where=text("is_deleted = false AND exam_no IS NOT NULL")),
        Index("uq_oh_health_exams_feishu", "feishu_record_id",
              unique=True, postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL")),
        Index("uq_oh_exams_source", "source_table", "source_record_id",
              unique=True,
              postgresql_where=text(
                  "is_deleted = false AND source_table IS NOT NULL AND source_record_id IS NOT NULL"
              )),
        Index("ix_oh_health_exams_person", "person_id"),
        Index("ix_oh_health_exams_status", "status"),
        Index("ix_oh_health_exams_exam_type", "exam_type"),
        {"schema": "safety", "comment": "职业健康体检记录（Bitable 镜像 + AI 解析字段）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    exam_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="体检号（Bitable 自动编号字段）"
    )

    # ── 人员信息（冗余，便于查询）──
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 oh_persons.id（无 FK）"
    )
    employee_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="员工姓名（冗余，便于查询）"
    )
    id_card_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证号（关联键冗余）"
    )
    employee_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="工号（冗余）"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位（原 Bitable「工种」更名）"
    )
    gender: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="性别"
    )
    age: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="年龄（公式）"
    )
    marital_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="婚姻状况"
    )
    phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="电话"
    )

    # ── 体检信息 ──
    exam_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="体检类型: pre_employment/periodic/post_employment/transfer/emergency"
    )
    exam_agency: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="体检机构"
    )
    scheduled_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="登记时间（Bitable「登记时间」）"
    )
    exam_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际体检日期"
    )
    report_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="报告日期"
    )

    # ── 危害因素与工龄 ──
    hazard_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="危害因素 [标准名]（多选）"
    )
    protection_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="防护措施（Bitable 公式）"
    )
    total_work_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="总工龄"
    )
    hazard_exposure_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="接害工龄"
    )

    # ── 体检结果（AI 输入①）──
    exam_result: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="体检结果（大段文本，AI 输入①）"
    )
    exam_conclusion: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="检查结论（大段文本，AI 输入①）"
    )
    treatment_advice_raw: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处理意见原文（AI 输入①）"
    )
    paper_report_kept: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="纸质报告留存: yes/no"
    )
    synced_to_summary: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="是否已同步汇总表（平台回写 Bitable）"
    )
    source_table: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable Source Table（推断 exam_type 用）"
    )
    source_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable Source Record ID"
    )
    attachments: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="体检报告附件 [{name,file_token,url,...}]"
    )
    attachment_paths: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="附件本地路径 [string]"
    )

    # ── 机器状态（兼容旧前端）──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending",
        comment="机器状态（兼容旧前端）: pending/scheduled/in_progress/completed/archived"
    )

    # ── AI 解析字段（平台独占，防止平台写回触发重新解析）──
    ai_parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
        comment="AI 解析状态: pending/parsing/parsed/failed"
    )
    ai_parse_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="解析失败原因"
    )
    ai_parse_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="OhExamReportParseOutput 全量（abnormal_indicators/conclusion_category/...）"
    )
    ai_interpretation: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI智能解读文本（回写 Bitable）"
    )
    ai_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="AI 结论分类: normal/abnormal_other/contraindicated/suspected_od/od_diagnosed/re_examination"
    )
    ai_contraindication_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="AI 职业禁忌证涉及危害因素 [标准名]"
    )
    ai_fitness: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="AI 适配: fit/fit_with_restriction/unfit"
    )

    # ── 人工覆盖结论（留痕）──
    ai_override_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="人工覆盖结论备注（留痕）"
    )
    override_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="人工覆盖结论（非空表示已覆盖 AI）"
    )
    override_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="覆盖人 identity.users.id"
    )
    override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="覆盖时间"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhPosition(BaseModel):
    """岗位危害因素台账（Bitable 镜像）"""

    __tablename__ = "oh_positions"
    __table_args__ = (
        Index("uq_oh_positions_dept_pos", "department", "position",
              unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_oh_positions_feishu", "feishu_record_id"),
        {"schema": "safety", "comment": "岗位危害因素台账（Bitable 镜像）"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位"
    )
    job_title: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="职务"
    )
    hazard_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="危害因素 [标准名]（多选 43 项）"
    )
    hazard_factors_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="filled/empty/inferred（二期 AI 推断用）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhHazardFactor(BaseModel):
    """危害因素 PPE 映射字典（Bitable 镜像）"""

    __tablename__ = "oh_hazard_factors"
    __table_args__ = (
        Index("uq_oh_hazard_factors_name", "factor_name",
              unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_oh_hazard_factors_feishu", "feishu_record_id"),
        {"schema": "safety", "comment": "危害因素 PPE 映射字典（Bitable 镜像）"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    factor_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="危害因素标准名（43 项之一）"
    )
    ppe_respiratory: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="呼吸防护用品（半面罩/全面罩两档）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhExamApplication(BaseModel):
    """职业健康体检申请（转岗/离岗审批流入口）"""

    __tablename__ = "oh_exam_applications"
    __table_args__ = (
        Index("uq_oh_exam_applications_no", "application_no",
              unique=True, postgresql_where=text("is_deleted = false AND application_no IS NOT NULL")),
        Index("uq_oh_exam_applications_feishu", "feishu_record_id",
              unique=True, postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL")),
        Index("ix_oh_exam_applications_status", "apply_status"),
        {"schema": "safety", "comment": "职业健康体检申请（转岗/离岗审批流入口）"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    application_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="申请编号（文本/URL）"
    )
    apply_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="申请状态: 已通过/审批中/已拒绝/已取消/已终止/已撤回/已删除"
    )
    approval_flow: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批流程名称"
    )
    approval_node: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="当前审批节点"
    )
    current_handler: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="当前处理人"
    )
    initiator_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发起人姓名"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发起时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间"
    )
    transfer_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="transfer/post_employment（转岗/离岗）"
    )
    exam_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="体检类型: 离岗体检/转岗体检"
    )
    employee_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="员工姓名"
    )
    id_card_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证号"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="原部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="原岗位"
    )
    new_department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="转入部门"
    )
    new_position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="转入岗位"
    )
    transfer_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="转岗日期"
    )
    leave_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="离岗日期"
    )
    dept_safety_officer: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门安全员"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请人"
    )
    apply_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="申请日期"
    )

    # ── AI 差异分析（工作流②）──
    diff_analyze_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none",
        comment="差异分析状态: none/parsing/analyzed/failed"
    )
    diff_analyze_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="差异分析失败原因"
    )
    diff_analyze_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="OhTransferDiffOutput 全量"
    )
    diff_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="差异分析摘要（回写 Bitable「差异分析结论」）"
    )
    needs_exam: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="是否需体检（AI 输出）"
    )
    exam_suggestion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="建议体检类型: pre_employment/periodic/transfer"
    )
    created_exam_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="自动创建的体检登记 oh_health_exams.id（联动）"
    )
    bt_extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Bitable 脏字段（备案残留等，镜像忽略主字段后兜底）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhFollowup(BaseModel):
    """职业健康异常随访（平台侧新增，闭环管理）"""

    __tablename__ = "oh_followups"
    __table_args__ = (
        Index("uq_oh_followups_exam_indicator", "exam_id", "indicator_name",
              unique=True, postgresql_where=text("is_deleted = false AND exam_id IS NOT NULL")),
        Index("ix_oh_followups_person", "person_id"),
        Index("ix_oh_followups_status", "status"),
        Index("ix_oh_followups_due", "followup_date"),
        {"schema": "safety", "comment": "职业健康异常随访（平台侧新增，闭环管理）"},
    )

    exam_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 oh_health_exams.id（无 FK）"
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 oh_persons.id（无 FK）"
    )
    person_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="人员姓名（冗余）"
    )
    indicator_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="异常指标名"
    )
    indicator_value: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="指标值（保留原文+单位）"
    )
    reference_range: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="参考范围"
    )
    abnormal_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="异常程度: mild/moderate/severe"
    )
    category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="指标类别: lab/vision/hearing/physique/other"
    )
    followup_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="随访类型: re_examination/specialist_referral/transfer_post/health_monitor"
    )
    followup_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="建议复查/处置日期（到期派生）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open",
        comment="随访状态: open/followed/closed/expired"
    )
    action_taken: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处置记录"
    )
    responsible: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="责任人"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="关闭时间"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ai", server_default="ai", comment="来源: ai/manual"
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
    special_op_personnel: Mapped[list[Any] | None] = mapped_column(
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
    violations: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="违章记录 [{\"date\",\"description\",\"severity\",\"handler\",\"result\"}]"
    )
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(
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


# ═══════════════════════════════════════════════════════════
# 应急演练管理
# ═══════════════════════════════════════════════════════════


class EmergencyDrillRecord(BaseModel):
    """应急演练记录（Bitable 单表镜像）。

    一行 = 一次演练的完整生命周期：计划 → 实施 → 复核。
    通过 feishu_record_id 与 Bitable 同步。
    """

    __tablename__ = "emergency_drill_records"
    __table_args__ = (
        Index("idx_drill_feishu_record", "feishu_record_id"),
        Index("idx_drill_department", "department"),
        Index("idx_drill_execution_time", "execution_time"),
        Index("idx_drill_status", "status"),
        {"schema": "safety"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（同步主键）"
    )

    # ── 计划阶段（13 字段）──
    plan_time: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="计划时间")
    plan_time_ref: Mapped[date | None] = mapped_column(Date, nullable=True, comment="计划时间参考")
    drill_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="演练类型")
    drill_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="演练内容")
    organizer: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="组织人")
    department: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="演练部门")
    organizer_person: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="组织人(人员)")
    participants: Mapped[str | None] = mapped_column(Text, nullable=True, comment="参演人员")
    coop_department: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="配合部门")
    duration: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="课时")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    alert_person: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="提醒人员")
    alert_person_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="提醒人员(人员) — 含 open_id"
    )

    # ── 实施阶段（5 字段）──
    execution_time: Mapped[date | None] = mapped_column(Date, nullable=True, comment="实施时间")
    drill_plan_file: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="演练方案附件"
    )
    plan_final_file: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="演练方案（定稿）附件"
    )
    signin_file: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="签到表附件"
    )
    eval_form_file: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="演练评估表附件"
    )
    drill_record_file: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="演练记录表附件"
    )
    eval_ai_file: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="演练评估表（AI）附件"
    )
    eval_source_record_file_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="最近一次AI评估所用演练记录表 file_token（触发去重依据）"
    )

    # ── 复核阶段（5 字段）──
    issues: Mapped[str | None] = mapped_column(Text, nullable=True, comment="演练问题")
    rectification_time: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="整改时间"
    )
    rectification_person: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="整改责任人姓名"
    )
    rectification_person_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="整改责任人(人员) — 含 open_id"
    )
    confirmer: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="确认人姓名")
    confirmer_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="确认人(人员) — 含 open_id"
    )
    status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="复核状态: 已完成/未完成"
    )


class EmergencyDrillDocument(BaseModel):
    """AI 生成的演练方案文档。"""

    __tablename__ = "emergency_drill_documents"
    __table_args__ = (
        Index("idx_drill_docs_resource", "resource_type", "resource_id"),
        {"schema": "safety"},
    )

    resource_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="drill_record", comment="关联类型"
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="关联 EmergencyDrillRecord.id"
    )
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="drill_plan", comment="drill_plan"
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="文档标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Markdown 正文")
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="结构化内容")
    generation_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="生成参数")
    cited_regulations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="引用法规")
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="AI 模型")
    ai_tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Token 消耗")
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="版本号"
    )
    doc_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft", comment="draft/published"
    )
    feishu_doc_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书云文档 ID (document token)"
    )
    feishu_doc_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="飞书云文档链接"
    )
    feishu_doc_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="飞书文档状态: created/synced/failed"
    )


class DrillHazardLink(BaseModel):
    """演练记录 ↔ 隐患报告 关联表。"""

    __tablename__ = "drill_hazard_links"
    __table_args__ = (
        Index("idx_dhl_drill", "drill_record_id"),
        Index("idx_dhl_hazard", "hazard_report_id"),
        {"schema": "safety"},
    )

    drill_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="EmergencyDrillRecord.id"
    )
    hazard_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="HazardReport.id"
    )


class DrillCollectionRecord(BaseModel):
    """演练计划收录记录（Bitable 镜像 + 平台专属解析字段）。

    Bitable 字段：日期 / 演练计划附件 / 人员 / 部门
    平台字段：parse_status / parse_result / stats_record_id
    """

    __tablename__ = "drill_collection_records"
    __table_args__ = (
        Index("idx_dcr_feishu_record", "feishu_record_id"),
        Index("idx_dcr_parse_status", "parse_status"),
        {"schema": "safety"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（收录表同步主键）"
    )

    # Bitable 字段
    upload_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="日期")
    attachment: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="演练计划附件")
    person_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="人员(含 open_id)"
    )
    department: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="部门(多选文本)")

    # 平台专属字段
    parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default="pending", comment="解析状态: pending/parsed/failed"
    )
    parse_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="AI 解析结果 JSON"
    )
    stats_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="写入统计表的 feishu_record_id"
    )


# ==================== 相关方准入条件审核（Bitable 镜像）====================


class ContractorAdmission(BaseModel):
    """相关方准入条件审核（Bitable 镜像表）。

    数据源：飞书多维表格「相关方准入」表（bitable.record.created/changed/deleted 事件同步）。
    AI 审核：下载协议/营业执照/保险凭证附件 → 文本提取 + 视觉补充 → 三维度 AI 审核 →
            回填 Bitable 3 字段（AI审核结论/AI审核报告/AI不符合项）。
    软删除铁律：唯一约束全部使用部分唯一索引（WHERE is_deleted = false）。
    """

    __tablename__ = "contractor_admissions"
    __table_args__ = (
        Index(
            "uq_contractor_admissions_admission_no",
            "admission_no",
            unique=True,
            postgresql_where=text("is_deleted = false AND admission_no IS NOT NULL"),
        ),
        Index(
            "uq_contractor_admissions_feishu_record_id",
            "feishu_record_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        ),
        Index("ix_contractor_admissions_company", "company_name"),
        Index("ix_contractor_admissions_type", "related_party_type"),
        Index("ix_contractor_admissions_submit", "submit_status"),
        Index("ix_contractor_admissions_review", "ai_review_status"),
        Index("ix_contractor_admissions_entry_date", "entry_date"),
        {"schema": "safety", "comment": "相关方准入条件审核表（Bitable 镜像）"},
    )

    # ── 业务编号（平台自动生成，Bitable 无此列）──
    admission_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="准入编号（平台自动生成 CA-YYYYMMDD-####）"
    )

    # ── 业务字段（直接映射 Bitable）──
    company_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="作业单位名称"
    )
    related_party_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="相关方类型: 承包商/合作类相关方/劳务派遣/其他相关方"
    )
    contact_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="承包商负责人"
    )
    contact_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="承包商负责人联系电话"
    )
    liaison_user_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="对接人员飞书 open_id/user_id（Bitable user 字段）"
    )
    liaison_user_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="对接人员姓名"
    )

    # ── 日期（Bitable datetime 字段，平台存日期部分）──
    entry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="入厂日期"
    )
    start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="开始日期"
    )
    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="结束日期"
    )
    material_expiry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="材料失效日期"
    )
    actual_submit_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="实际提交日期"
    )
    actual_complete_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="实际完成日期"
    )

    # ── 状态（中文 value 直存，与 Bitable 单选选项一致）──
    submit_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="提交状态: 已完成/进行中/未开始"
    )
    training_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="培训状态: 已完结/已培训待补材/未培训"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 附件（存平台本地路径数组，JSON；元素结构 {name, path, file_token}）
    #    协议附件按 related_party_type 三选一映射到同一字段：
    #    承包商→safety_agreement_files（来源「承包商安全管理协议」）
    #    合作类→safety_agreement_files（来源「合作类安全管理协议」）
    #    劳务派遣→safety_agreement_files（来源「劳务派遣安全管理协议」）
    safety_agreement_files: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="安全管理协议附件 [{name,path,file_token}]（按 type 取对应 Bitable 字段）"
    )
    business_license_files: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="企业营业执照附件 [{name,path,file_token}]"
    )
    insurance_files: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="现场作业保险凭证附件 [{name,path,file_token}]"
    )
    assessment_rules_files: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="承包商考核细则附件 [{name,path,file_token}]"
    )
    employee_cert_files: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="员工证明盖章文件附件 [{name,path,file_token}]"
    )
    on_site_leader_stamp_files: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="现场负责人盖章文件附件 [{name,path,file_token}]"
    )

    # ── Bitable 同步字段 ──
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable(飞书同步)/manual(手动)",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    feishu_table_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="飞书表 ID（单表恒为 admission）"
    )
    feishu_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="Bitable 记录跳转链接"
    )

    # ── AI 审核（三维度 + overall，同 EhsChange 模式扩展）──
    ai_review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", server_default="none",
        comment="AI审核状态: none/processing/completed/failed",
    )
    ai_review_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="AI审核结果 JSONB {agreement:{conclusion,report,defects}, license:{...}, insurance:{...}, overall_conclusion, overall_report, defect_categories:[], regulations:[...]}"
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI审核失败信息（failed 时记录，completed 时清空）"
    )
    ai_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次 AI 审核完成时间"
    )


# ==================== URS 智能审核（EHS 设备采购合规审核）====================


class URSReport(BaseModel):
    """URS 审核主表 — 一行 = 一次设备 URS 审核的全生命周期。

    五维风险画像 → 三级标准适配 → 逐条审核 → 结论（评分/等级/整改要求）。
    无审批链：AI 出结论直接落地；置信度 < 0.8 时人工复核画像（复核兜底）。
    """

    __tablename__ = "urs_reports"
    __table_args__ = (
        Index(
            "uq_urs_reports_urs_no", "urs_no",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
        Index("idx_urs_reports_department", "department"),
        Index("idx_urs_reports_status", "review_status"),
        {"schema": "safety"},
    )

    # ── 编号与基本信息 ──
    urs_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="URS 编号 URS-YYYYMMDD-001"
    )
    equipment_name: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="设备名称"
    )
    equipment_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="设备类别"
    )
    department: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="申请部门"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="申请人姓名"
    )
    applicant_open_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="申请人飞书 open_id（通知唯一对象）"
    )
    procurement_purpose: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="采购用途: 新增/更换/技术改造"
    )
    urs_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="URS 正文（从文档解析或对话补全）"
    )
    attachment_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="URS 文档附件路径"
    )
    source_chat_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="来源飞书会话（回访用）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 五维风险画像（AI Step1 输出）──
    risk_profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="五维画像 {mechanical:{level,indicators,evidence}, electrical, data, environmental, chemical}"
    )
    overall_risk_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="综合风险等级: high/medium/low"
    )
    risk_profile_reasoning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 综合定级理由"
    )
    ai_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="适用性评估置信度（0-1），<0.8 触发人工复核"
    )
    human_review_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="人工复核意见"
    )

    # ── AI 审核结论（Step4 输出）──
    review_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="审核结论 {score, grade, conclusion, summary, veto_break}"
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="百分制评分")
    grade: Mapped[str | None] = mapped_column(
        String(2), nullable=True, comment="等级: A≥90/B≥75/C≥60/D<60"
    )
    conclusion: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="结论: approved/rejected"
    )
    rectification_requirements: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="整改要求 [{item_no, requirement, responsible, deadline}]"
    )

    # ── 状态机与 AI 流程状态 ──
    review_status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False,
        comment="draft/pending_assessment/assessing/failed/assessment_confirmed/human_review/adapting/item_review/conclusion/approved/rejected/appeal/closed"
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 执行错误信息"
    )
    ai_assessment_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False,
        comment="评估状态: pending/processing/completed/failed"
    )
    ai_assessment_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="评估完成时间"
    )

    # ── 申诉 ──
    appeal_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="申诉理由"
    )
    appeal_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="重评结果 {reassessed_risk, delta, basis}"
    )

    # ── 飞书通知追踪 ──
    notify_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="通知状态: success/failed"
    )
    notify_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="通知失败原因"
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近通知时间"
    )


class URSStandardItem(BaseModel):
    """URS 审核标准条目 — 一行 = 一个标准条款在某台设备上的适配与审核结果。

    source: seed（内置通用条款）/ knowledge（知识库 RAG 补充）
    否决项（is_veto）由代码强制 mandatory，AI 不可改。
    """

    __tablename__ = "urs_standard_items"
    __table_args__ = (
        Index("idx_urs_items_urs", "urs_id"),
        Index("idx_urs_items_applicability", "applicability"),
        {"schema": "safety"},
    )

    urs_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="关联 urs_reports.id"
    )
    item_no: Mapped[str] = mapped_column(String(16), nullable=False, comment="标准条目编号 S1.1")
    category: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="条款类别: data_integrity/motion_guard/fire_explosion/environmental/safety_distance/loto/…"
    )
    risk_dimension: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="关联风险维度: mechanical/electrical/data/environmental/chemical/none"
    )
    standard_title: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="标准条款标题（中文）"
    )
    standard_ref: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="法规标准引用"
    )
    is_veto: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, comment="是否否决项（代码强制）"
    )
    source: Mapped[str] = mapped_column(
        String(16), default="seed", server_default="seed", nullable=False,
        comment="来源: seed/knowledge"
    )

    # ── 适配结果（AI Step2 输出，人工可改）──
    applicability: Mapped[str] = mapped_column(
        String(16), default="recommended", server_default="recommended", nullable=False,
        comment="适配等级: mandatory/recommended/not_applicable"
    )
    applicability_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="适配依据"
    )

    # ── 逐条审核结果（Step3：AI 预填 + 人工确认）──
    review_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False,
        comment="审核状态: pending/passed/failed/skipped"
    )
    review_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="审核意见"
    )
    ai_suggestion: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 预填建议"
    )
    rectification_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, comment="是否需整改"
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="确认人姓名"
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="确认时间"
    )


class URSReviewDocument(BaseModel):
    """AI 生成的 URS 审核文档（风险画像/适配清单/审核报告）。"""

    __tablename__ = "urs_review_documents"
    __table_args__ = (
        Index("idx_urs_docs_resource", "resource_type", "resource_id"),
        {"schema": "safety"},
    )

    resource_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="urs_report", comment="关联类型"
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="关联 URSReport.id"
    )
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="risk_assessment/adaptation/review_report"
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, comment="文档标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Markdown 正文")
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="结构化内容")
    generation_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="生成参数")
    cited_regulations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="引用法规")
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="AI 模型")
    ai_tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Token 消耗")
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="版本号"
    )
    feishu_doc_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书云文档 ID"
    )
    feishu_doc_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="飞书云文档链接"
    )
    feishu_doc_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="飞书文档状态: created/synced/failed"
    )


# ==================== MSDS 智能提取入库 ====================


class MsdsCollectionRecord(BaseModel):
    """供应商资料采集记录（「供应商资料」表 Bitable 镜像 + 平台解析字段）。

    Bitable 字段：日期 / 供应商资料附件 / 人员
    平台字段：parse_status / parse_result（AI 提取 28 字段【数组】）/ msds_table_record_ids
    1 条采集记录 → 按化学品拆分为 N 条 MSDS 台账（1:N）。
    """

    __tablename__ = "msds_collection_records"
    __table_args__ = (
        Index("idx_msds_collect_feishu", "feishu_record_id"),
        Index("idx_msds_collect_status", "parse_status"),
        {"schema": "safety"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（供应商资料表同步主键）"
    )
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="上传日期")
    attachment: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="供应商资料附件")
    attachment_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="附件本地下载路径"
    )
    person_data: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="人员(供应商联系人, 含 open_id)"
    )

    # 平台解析字段
    parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default="pending", comment="解析状态: pending/parsed/failed"
    )
    parse_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="解析失败原因"
    )
    parse_result: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="AI 提取的 28 字段【数组】, 一个化学品一条"
    )
    msds_table_record_ids: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="创建的 MSDS 表记录 feishu_record_id 数组（回写，1:N）"
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="写回 MSDS 表时间"
    )


class MsdsDocument(BaseModel):
    """MSDS 标准化台账（「MSDS」表 Bitable 镜像）。

    字段与 MSDS 表 29 列一一对应；1 供应商资料记录 → N 行（每行一个化学品）。
    同 CAS 写回时 UPDATE 刷新，不制造重复。
    """

    __tablename__ = "msds_documents"
    __table_args__ = (
        Index("idx_msds_feishu_record", "feishu_record_id"),
        Index("idx_msds_cas_no", "cas_no"),
        Index("idx_msds_name", "name"),
        Index("idx_msds_review_status", "review_status"),
        {"schema": "safety"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（MSDS 表同步主键）"
    )
    collection_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 msds_collection_records.id（溯源）"
    )
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="日期")

    # ── 基础标识 ──
    name: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="物质名称")
    cas_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="CAS号")
    molecular_formula: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="分子式"
    )
    un_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="UN编号")
    hazard_class: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="危险分级: normal/hazardous_1/hazardous_2（分发阶段用）"
    )

    # ── 危险性概述 ──
    hazard_statement: Mapped[str | None] = mapped_column(Text, nullable=True, comment="危险性说明")
    label_elements: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="标签要素（仅平台存档, 写回 Bitable 丢弃）"
    )

    # ── 理化特性（10）──
    appearance: Mapped[str | None] = mapped_column(Text, nullable=True, comment="外观与现状")
    solubility: Mapped[str | None] = mapped_column(Text, nullable=True, comment="溶解性")
    melting_point: Mapped[str | None] = mapped_column(Text, nullable=True, comment="熔点")
    boiling_point: Mapped[str | None] = mapped_column(Text, nullable=True, comment="沸点")
    flash_point: Mapped[str | None] = mapped_column(Text, nullable=True, comment="闪点")
    relative_density: Mapped[str | None] = mapped_column(Text, nullable=True, comment="相对密度")
    explosion_upper_limit: Mapped[str | None] = mapped_column(Text, nullable=True, comment="爆炸上限(%)")
    explosion_lower_limit: Mapped[str | None] = mapped_column(Text, nullable=True, comment="爆炸下限(%)")
    autoignition_temperature: Mapped[str | None] = mapped_column(Text, nullable=True, comment="自燃温度")
    decomposition_temperature: Mapped[str | None] = mapped_column(Text, nullable=True, comment="分解温度")

    # ── 职业接触限值（3）──
    pc_twa: Mapped[str | None] = mapped_column(Text, nullable=True, comment="PC-TWA (mg/m3)")
    pc_stel: Mapped[str | None] = mapped_column(Text, nullable=True, comment="PC-STEL (mg/m3)")
    mac: Mapped[str | None] = mapped_column(Text, nullable=True, comment="MAC (mg/m3)")

    # ── 健康与环境危害（2）──
    health_hazard: Mapped[str | None] = mapped_column(Text, nullable=True, comment="健康危害")
    environmental_hazard: Mapped[str | None] = mapped_column(Text, nullable=True, comment="环境危害")

    # ── 应急响应（4）──
    first_aid: Mapped[str | None] = mapped_column(Text, nullable=True, comment="急救措施")
    fire_fighting: Mapped[str | None] = mapped_column(Text, nullable=True, comment="消防措施")
    leakage_response: Mapped[str | None] = mapped_column(Text, nullable=True, comment="泄漏应急处理")
    waste_disposal: Mapped[str | None] = mapped_column(Text, nullable=True, comment="废弃处置")

    # ── 防护与控制（3）──
    exposure_controls: Mapped[str | None] = mapped_column(Text, nullable=True, comment="接触控制与个体防护")
    handling_storage: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作处置与储存注意事项")
    stability_reactivity: Mapped[str | None] = mapped_column(Text, nullable=True, comment="稳定性和反应性")

    # ── 附件 ──
    msds_attachment: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="「MSDS附件」= 平台生成的标准模板文件"
    )
    msds_attachment_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="标准 docx 本地路径"
    )

    # ── 状态 ──
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default="pending", comment="复核状态: pending/approved/rejected（本期默认 pending）"
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="复核人")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="复核时间"
    )
    archive_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default="pending", comment="归档状态: pending/archived"
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="归档时间"
    )


class MsdsTrainingTask(BaseModel):
    """MSDS 学习任务（仅建表预留，分发/培训闭环阶段使用，本期无接口无逻辑）。"""

    __tablename__ = "msds_training_tasks"
    __table_args__ = (
        Index("idx_msds_task_doc", "msds_document_id"),
        Index("idx_msds_task_user", "target_open_id"),
        Index("idx_msds_task_status", "status"),
        {"schema": "safety"},
    )

    msds_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 msds_documents.id"
    )
    target_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="目标人姓名")
    target_open_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书 open_id"
    )
    department: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="部门")
    deadline: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="截止日期（普通5工作日/危化品2工作日）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default="pending", comment="状态: pending/read/overdue"
    )
    remind_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="已提醒次数"
    )
    confirm_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书确认表单消息 ID"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="确认时间"
    )


class SchedulerJobRun(BaseModel):
    """定时任务触发状态（重启去重 + 失败重试补发）。

    - status='success' 且 fired_date=今天 → 当天已完成，不再执行（重启后去重）
    - status='failed' → 进入失败重试：每 RETRY_INTERVAL 重试，补发窗口内持续尝试，
      达失败阈值后发告警给管理员
    """

    __tablename__ = "scheduler_job_runs"
    __table_args__ = (
        Index("uq_scheduler_job_runs_job_name", "job_name", unique=True),
        {"schema": "safety"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="调度任务名（对应 SCHEDULED_JOBS.name）"
    )
    fired_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="最近一次执行日期（status=success 时表示完成日期）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success",
        server_default="success",
        comment="当天任务状态: success=已成功(去重不再跑) / failed=失败(待重试补发)",
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="最近一次执行尝试时间（用于失败重试退避间隔判断）",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="当天连续失败次数（成功时清零，达阈值触发失败告警）",
    )
    alerted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="当天是否已发送失败告警（成功后重置）",
    )


class FireAlarmRecord(BaseModel):
    """消防报警记录（飞书消防数据多维表格镜像 + AI 分析字段）。

    数据源: 飞书 Bitable「火灾报警信息」表（消防数据多维表格）。
    同步以 feishu_record_id 为主键 upsert，平台侧只读展示 + AI 分析回写。
    """

    __tablename__ = "fire_alarm_records"
    __table_args__ = (
        # 软删除下唯一键：部分唯一索引（is_deleted=false 才生效）
        # 软删除时清空 feishu_record_id（设为 NULL），避免重复添加→删除→添加触发约束冲突
        Index(
            "uq_fire_alarm_feishu_record_id", "feishu_record_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        ),
        # 报警时间索引（日报/周报按时间窗口筛选 + 分页排序）
        Index("ix_fire_alarm_alarm_time", "alarm_time"),
        # 部门索引（@提及解析、周报部门分布）
        Index("ix_fire_alarm_department", "department"),
        # AI 维度索引（前端按维度筛选）
        Index("ix_fire_alarm_ai_dimension", "ai_dimension"),
        {"schema": "safety", "comment": "消防报警记录（Bitable 镜像 + AI 分析字段）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键；软删时置 NULL）"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable(飞书同步) / manual(预留)"
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后同步时间（事件/全量同步回写）"
    )

    # ── 报警基础字段（原始文本/时间戳，字段名以 spec 文档为准）──
    alarm_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="报警时间"
    )
    alarm_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="报警类型"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="报警部门"
    )
    department_leader_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="报警部门负责人姓名"
    )
    building: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="报警楼栋"
    )
    location: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="报警部位"
    )
    alarm_nature: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="报警性质"
    )
    cause_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="报警原因分类（人工填写）"
    )
    cause_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="具体报警原因（人工填写，AI 分析输入）"
    )
    # 预留：联调时若 Bitable 实际列名与上述映射不一致，仅调整 map_bitable_fields 映射函数
    bt_extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Bitable 多余字段兜底（联调用，不参与分析）"
    )

    # ── AI 分析字段组（日报生成时回写，前端列表展示）──
    ai_dimension: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="AI 维度分类: process(工艺) / operation(人员操作) / equipment(设备设施) / other(其他)"
    )
    ai_reason_analysis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 原因分析（自然语言，40-120 字）"
    )
    ai_rectification_direction: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 整改方向（针对性与可操作性，30-80 字）"
    )
    ai_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="AI 分析完成时间（回写时间戳）"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PersonCertificate(BaseModel):
    """人员持证台账（Bitable 镜像 + 预警计算输入）。

    统一表，用 cert_category 区分特种作业证 / 监护人 A 证 / 监护人 B 证；
    差异日期字段以 nullable 列共存（特种作业证用 next_review_date / review_frequency；
    监护人证用 first_review_deadline / second_review_deadline / should_renew_date /
    renewed_date）。
    """

    __tablename__ = "person_certificates"
    __table_args__ = (
        # 部分唯一索引：软删除/空 record_id 不参与唯一约束
        # （防「重复添加→删除→添加→删除」隐形 bug，遵循 CLAUDE.md 软删除铁律）
        Index(
            "uq_person_certs_feishu_rid",
            "feishu_record_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        ),
        Index("ix_person_certs_next_review", "next_review_date"),
        Index("ix_person_certs_should_renew", "should_renew_date"),
        Index("ix_person_certs_first_review", "first_review_deadline"),
        Index("ix_person_certs_dept", "department"),
        Index("ix_person_certs_category", "cert_category"),
        Index("ix_person_certs_feishu", "feishu_record_id"),
        {"schema": "safety", "comment": "人员持证台账（Bitable 镜像 + 预警计算输入）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（镜像同步主键；软删时置 NULL）"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable(飞书同步) / manual(手动)",
    )

    # ── 证件类别 ──
    cert_category: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="证件类别: special_op(特种作业证) / guardian_a(监护人A证) / guardian_b(监护人B证)",
    )

    # ── 人员信息 ──
    person_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="姓名")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门")
    employee_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="工号")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="联系方式")

    # ── 证件通用信息 ──
    operation_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="作业类别（特种作业证用，对应 OperationType 8 类: hot_work 等）",
    )
    project: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="项目（如电工、焊接、高处）",
    )
    certificate_no: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="证件编号",
    )
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="取证日期")
    certificate_file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="证件附件路径",
    )

    # ── 特种作业证专用（复审周期）──
    next_review_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="再复审时间（特种作业证用）",
    )
    review_frequency: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="复审频次（如'3年'、'无需复审'）",
    )

    # ── 监护人 A/B 证专用（多节点 + 换证周期）──
    first_review_deadline: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第一次复审截止日期（监护人证用）",
    )
    second_review_deadline: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="第二次复审截止日期（监护人证用）",
    )
    should_renew_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="应换证日期（监护人证用）",
    )
    renewed_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment="已换证日期（监护人证用，回填后以 renewed_date 为新 issue_date 重算下一周期）",
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class CentralAlarmRecord(BaseModel):
    """中控报警记录（飞书「中控报警统计」Base 15 张同构表镜像 + AI 分析字段）。

    数据源: 飞书 Bitable「中控报警统计」Base（15 张表，按车间×产线划分）。
    同步以 feishu_record_id 为主键 upsert；workshop/line 从 Bitable 表名推导。
    平台侧只读展示 + AI 分析回写。
    """

    __tablename__ = "central_alarm_records"
    __table_args__ = (
        # 软删除下唯一键：部分唯一索引（is_deleted=false 才生效）
        Index(
            "uq_central_alarm_feishu_record_id", "feishu_record_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        ),
        Index("ix_central_alarm_alarm_date", "alarm_date"),
        Index("ix_central_alarm_workshop", "workshop"),
        Index("ix_central_alarm_ai_pattern", "ai_pattern"),
        Index("ix_central_alarm_ai_dimension", "ai_dimension"),
        {"schema": "safety", "comment": "中控报警记录（Bitable 镜像 + AI 分析字段）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键；软删时置 NULL）"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable(飞书同步) / manual(预留)"
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后同步时间（事件/全量同步回写）"
    )

    # ── Bitable 原始字段（字段名以 spec/bitable 实际列名对齐）──
    alarm_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="报警日期（Bitable「日期」列，datetime）"
    )
    post: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="岗位（Bitable「岗位」单选列）"
    )
    alarm_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="报警情况说明（自由文本，AI 分析输入）"
    )
    special_note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="特殊情况说明（自由文本，少数记录）"
    )
    # ── 车间/产线标识（从 Bitable 表名推导）──
    workshop: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="车间（如 车间一/车间二/车间四/新罐区）"
    )
    line: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="产线/区域（如 达托/达巴/雷帕/乙醇纳滤）"
    )
    # 预留：联调时若字段列名不同，仅调整 map_bitable_fields 映射函数
    bt_extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Bitable 多余字段兜底（联调用，不参与分析）"
    )

    # ── AI 分析字段组（日报生成时回写，前端列表展示）──
    ai_alarm_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="AI 结构化报警类型: 高液位/低液位/高温/低温/空罐/误报/联锁/其他"
    )
    ai_equipment: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="AI 抽取设备（如 R19150B 层析上柱罐）"
    )
    ai_pattern: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="AI 异常模式: normal_transient(正常瞬报)/repeated(重复报警)/false_alarm(误报)/anomalous(异常依赖)"
    )
    ai_dimension: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="AI 维度: process(工艺)/operation(人员操作)/equipment(设备设施)/other(其他)"
    )
    ai_reason_analysis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 原因分析（自然语言，40-120 字）"
    )
    ai_rectification_direction: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 整改方向（30-80 字）"
    )
    ai_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="AI 分析完成时间（回写时间戳）"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 危化品库存管理 Enums ====================


class ChemicalDepartmentType(str, PyEnum):
    """危化品库存部门枚举（14 部门 + 其他）。"""

    WAREHOUSE = "warehouse"              # 仓储部
    EXTRACTION_1 = "extraction_1"        # 提炼一部
    EXTRACTION_2 = "extraction_2"        # 提炼二期
    EXTRACTION_2B = "extraction_2b"      # 提炼二部
    FERMENTATION_1 = "fermentation_1"    # 发酵一部
    FERMENTATION_2 = "fermentation_2"    # 发酵二部
    STRAIN = "strain"                    # 菌种中心
    QC = "qc"                            # QC
    ENV = "env"                          # 环保
    PURIFICATION = "purification"        # 精制
    SEMI_SYNTHESIS = "semi_synth"        # 提炼半合成工程中心
    TECH_REFINEMENT = "tech_refine"      # 提炼技术精进中心
    OTHER = "other"


class ChemicalUnitType(str, PyEnum):
    """危化品库存单位枚举。"""

    KG = "kg"
    G = "g"
    T = "T"
    L = "L"
    ML = "ml"
    BOTTLE = "bottle"


class HazardClassType(str, PyEnum):
    """危险性类别（多选）。"""

    FLAMMABLE = "flammable"                        # 易燃
    EXPLOSIVE = "explosive"                        # 易爆
    PRECURSOR_DRUG = "precursor_drug"              # 易制毒
    PRECURSOR_EXPLOSIVE = "precursor_explosive"    # 易制爆
    CORROSIVE = "corrosive"                        # 腐蚀
    TOXIC = "toxic"                                # 毒性
    OXIDIZER = "oxidizer"                          # 氧化剂
    IRRITANT = "irritant"                          # 刺激性


class RiskFlagType(str, PyEnum):
    """库存记录风险标记（系统回填，二元：正常/预警）。"""

    NORMAL = "normal"
    WARN = "warn"


# ==================== 危化品库存管理 Models ====================


class ChemicalInventoryRecord(BaseModel):
    """危化品库存记录（「危化品库存总表」Bitable 镜像）。"""

    __tablename__ = "chemical_inventory_records"
    __table_args__ = (
        Index("idx_cir_feishu_record", "feishu_record_id"),
        Index("idx_cir_dept_loc", "department", "storage_location"),
        Index(
            "uq_cir_feishu_record",
            "feishu_record_id",
            unique=True,
            postgresql_where=text("feishu_record_id IS NOT NULL AND is_deleted = false"),
        ),
        Index(
            "uq_cir_dept_loc_name",
            "department", "storage_location", "material_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    department: Mapped[str] = mapped_column(String(32), nullable=False, comment="部门")
    storage_location: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="存放部位"
    )
    material_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="物料名称"
    )
    package_spec: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="包装规格"
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="库存数量"
    )
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="单位")
    total_quantity_t: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="现场物料总量(T)"
    )
    max_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="库存上限"
    )
    max_limit_unit: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="上限单位"
    )
    hazard_classes: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="危险性(多选)"
    )
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="品类")
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后更新时间（Bitable 系统字段）"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    risk_flag: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal",
        comment="风险标记(正常/预警)"
    )
    risk_note: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="风险说明(预警类型多选)"
    )


class ChemicalInventorySnapshot(BaseModel):
    """危化品库存快照（每周/每日落一份，用于周趋势与每日环比分析）。"""

    __tablename__ = "chemical_inventory_snapshots"
    __table_args__ = (
        Index("idx_cisnap_date_dept", "snapshot_date", "department"),
        Index(
            "uq_cisnap_key",
            "snapshot_date", "snapshot_kind", "department", "storage_location", "material_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
    snapshot_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="weekly", server_default="weekly",
        comment="快照类型(daily/weekly)",
    )
    department: Mapped[str] = mapped_column(String(32), nullable=False, comment="部门")
    storage_location: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="存放部位"
    )
    material_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="物料名称"
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="库存数量"
    )
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="单位")
    total_quantity_t: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="现场物料总量(T)"
    )
    risk_flag: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal",
        comment="风险标记(正常/预警)"
    )

# ==================== 作业票审核 ====================


class WorkTicketReview(BaseModel):
    """作业票审核摘要表（每日标准 8 类作业票规则审核结果）。"""

    __tablename__ = "work_ticket_reviews"
    __table_args__ = (
        Index(
            "uq_work_ticket_reviews_date",
            "date",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_work_ticket_reviews_date", "date"),
        {"schema": "safety"},
    )

    date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="审核日期（作业日期，Asia/Shanghai）"
    )
    total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="当日拉取到的标准 8 类作业票总数",
    )
    reviewed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="已具备开始时间、纳入规则审核的票数",
    )
    violation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="违规票数（含违规条数的票数，非条数）",
    )
    compliant_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="合格票数（有开始时间且无任何违规）",
    )
    data_insufficient: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="数据不足票数（缺开始时间/关键字段，审核窗口未满足）",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", server_default="success",
        comment="审核状态: pending/success/failed",
    )
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="当日平台原始工作流数据快照",
    )
    report_markdown: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="生成的可读 Markdown 报告",
    )
    pushed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="是否已推送群",
    )
    push_message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书卡片 message_id",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间",
    )


class WorkTicketReviewViolation(BaseModel):
    """作业票审核逐票违规明细表。"""

    __tablename__ = "work_ticket_review_violations"
    __table_args__ = (
        Index("ix_wt_review_violations_review_id", "review_id"),
        Index("ix_wt_review_violations_ticket_no", "ticket_no"),
        Index("ix_wt_review_violations_rule_no", "rule_no"),
        {"schema": "safety"},
    )

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="逻辑外键 → work_ticket_reviews.id（不建物理 FK）",
    )
    ticket_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="作业票号")
    ticket_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="作业类型: hot_work/confined_space/height_work/..."
    )
    rule_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="规则编号: TIME_ORDER/GAS_VALIDITY/DURATION/GAS_INTERVAL"
    )
    rule_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="规则中文名")
    detail: Mapped[str] = mapped_column(Text, nullable=False, comment="违规/不适用描述")
    key_times: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="关键时间点 {申请/审批/开始/结束/验收/气体分析等}"
    )
    not_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="true 表示该规则对该票「不适用」而非违规",
    )


# ==================== 定时任务配置 ====================


class SchedulerTaskConfig(BaseModel):
    """定时任务配置覆写表（与 SCHEDULED_JOBS 按 job_name 匹配，NULL = 使用代码默认值）。"""

    __tablename__ = "scheduler_task_configs"
    __table_args__ = (
        Index(
            "uq_scheduler_task_configs_job_name",
            "job_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="调度任务名（对应 SCHEDULED_JOBS.name）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用",
    )
    hour: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="执行小时 0-23")
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="执行分钟 0-59")
    dow: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="星期 0-6（周一-周日），NULL=每天"
    )
    target_chat_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书群聊 chat_id"
    )
    target_chat_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="群名（冗余，前端展示）"
    )
    retry_until_hour: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="补发窗口截止小时"
    )
    retry_until_minute: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="补发窗口截止分钟"
    )


class SchedulerConfigAudit(BaseModel):
    """定时任务配置变更审计表（append-only）。"""

    __tablename__ = "scheduler_config_audits"
    __table_args__ = (
        Index("idx_scheduler_config_audits_job_created", "job_name", "created_at"),
        {"schema": "safety"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="任务名（对应 SCHEDULED_JOBS.name）"
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable/run 等"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前配置（compact）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后配置（compact）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人（当前用户 name，无则 None）"
    )


# ==================== Bitable 配置中心 ====================


class BitableConnection(BaseModel):
    """Bitable 连接配置表（一行一表）。DB 为唯一权威；缺行/停用时 store 回退 registry 默认值。"""

    __tablename__ = "bitable_connections"
    __table_args__ = (
        Index(
            "uq_bitable_connections_domain_kind",
            "domain",
            "kind",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_bitable_connections_domain", "domain"),
        {"schema": "safety"},
    )

    domain: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="域 key（registry 注册，如 oh）"
    )
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="表类型 key（如 exam_registry）"
    )
    app_token: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="飞书多维表格 app_token（base/wiki 文档 token）"
    )
    table_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="表 table_id（central_alarm 为白名单主表）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（为 false 时 store 不返回给 handler，视为停用）",
    )
    extra_table_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="仅 central_alarm：白名单其余表 table_id 列表（不含主表）"
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class BitableFieldMapping(BaseModel):
    """字段映射表（一行一域一 kind，JSONB 全量替换）。

    多表域（oh×6、msds×2、ehs×2、cert×3、drill×2）各表映射完全不同，按 kind 分行。
    """

    __tablename__ = "bitable_field_mappings"
    __table_args__ = (
        Index(
            "uq_bitable_field_mappings_domain_kind",
            "domain",
            "kind",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    domain: Mapped[str] = mapped_column(String(64), nullable=False, comment="域 key")
    kind: Mapped[str] = mapped_column(String(64), nullable=False, comment="表类型 key")
    mappings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, comment="字段映射列表，见 backend-design §2.2 JSONB 结构"
    )


class BitableConfigAudit(BaseModel):
    """Bitable 配置变更审计表（append-only，软删字段沿用但业务不做删除）。"""

    __tablename__ = "bitable_config_audits"
    __table_args__ = (
        Index("idx_bitable_config_audits_domain_created", "domain", "created_at"),
        {"schema": "safety"},
    )

    domain: Mapped[str] = mapped_column(String(64), nullable=False, comment="域 key")
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="表类型 key（域级操作时为 '*'）"
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable/resubscribe 等"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


# ==================== AI 配置中心 ====================


class AiModelProfile(BaseModel):
    """AI 模型配置表（一行一组配置）。DB 为唯一权威；缺行/停用时 store 回退 env/registry 默认值。"""

    __tablename__ = "ai_model_profiles"
    __table_args__ = (
        Index(
            "uq_ai_model_profiles_profile",
            "profile",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_ai_model_profiles_profile", "profile"),
        {"schema": "safety"},
    )

    profile: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="profile key（registry 注册，如 text/text_backup/vision/embedding/rerank）",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="模型配置（默认值来自 registry.default_config，api_key 恒为空串不回显）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false 时读路径整行回落 env/registry 默认）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AiConfigAudit(BaseModel):
    """AI 配置变更审计表（append-only，软删字段沿用但业务不做删除）。"""

    __tablename__ = "ai_config_audits"
    __table_args__ = (
        Index("idx_ai_config_audits_profile_created", "profile", "created_at"),
        Index("idx_ai_config_audits_created", "created_at"),
        {"schema": "safety"},
    )

    profile: Mapped[str] = mapped_column(String(32), nullable=False, comment="profile key")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，api_key 已脱敏为 ****后4位）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact，api_key 已脱敏为 ****后4位）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class AiScenarioConfig(BaseModel):
    """AI 场景配置表（一行一场景，只能改值不能新增场景）。

    缺行 = 默认开启（enabled=true、model_profile=NULL 按场景类型派生），无歧义；
    软删复刻 AiModelProfile 惯例（部分唯一索引防「软删→重建同场景」冲突）。
    """

    __tablename__ = "ai_scenario_configs"
    __table_args__ = (
        Index(
            "uq_ai_scenario_configs_scenario",
            "scenario",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_ai_scenario_configs_scenario", "scenario"),
        {"schema": "safety"},
    )

    scenario: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="场景 key（registry 注册，DB 只能改值不能新增场景）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false = 熔断，统一入口抛 ScenarioDisabledError）",
    )
    model_profile: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="绑定 profile 名（text/text_backup/vision/embedding/rerank）；NULL = 按场景默认",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AiScenarioConfigAudit(BaseModel):
    """AI 场景配置变更审计表（append-only，软删字段沿用但业务不做删除）。

    相位不存任何密钥，``before_json``/``after_json`` 无需脱敏（复刻 AiConfigAudit）。
    """

    __tablename__ = "ai_scenario_config_audits"
    __table_args__ = (
        Index("idx_ai_scenario_config_audits_scenario_created", "scenario", "created_at"),
        Index("idx_ai_scenario_config_audits_created", "created_at"),
        {"schema": "safety"},
    )

    scenario: Mapped[str] = mapped_column(String(64), nullable=False, comment="对应场景")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，{enabled, model_profile, note}，无密钥）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact，{enabled, model_profile, note}，无密钥）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )

