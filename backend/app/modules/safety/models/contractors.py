"""Safety ORM models."""

import uuid
from datetime import date, datetime
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
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.modules.safety.models.special_operations import (
    SpecialOperationPermit,  # noqa: F401
)
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


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


