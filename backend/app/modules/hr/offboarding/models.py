"""离职管理 ORM 模型：办结单状态机 + 清退交接项 + 台账保存视图 + 导出留痕。

流程主干 OffboardingCase 一次离职一行；员工签字沿用 DepartureRecord.cert_sign_*
（已建好、employee_sync 同步不触碰），Case 经 departure_record_id 逻辑关联读写。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class OffboardingCase(BaseModel):
    """离职办结单。

    状态机：
        draft 申请登记（体检门禁：required 且未登记完成不可发起审批）
        → approving 离职审批（飞书原生审批编排，未配置定义降级站内登记）
        → clearing 清退会签（清退交接飞书审批 + 平台清退单明细）
        → cert_issuing 证明开具（HR 核对生成 PDF 并自动发邮件）
        → delivering 送达（电子版：员工 H5 手写签字；纸质两联版：当面签收登记）
        → signed 已签字 → closed 办结（四联动：档案/证件/花名册/台账）
        closed 前任意阶段可 canceled 取消。
    """

    __tablename__ = "offboarding_cases"
    __table_args__ = (
        Index("uq_offboarding_cases_case_no", "case_no", unique=True),
        Index("ix_offboarding_cases_employee_id", "employee_id"),
        Index("ix_offboarding_cases_status", "status"),
        Index("ix_offboarding_cases_department", "department"),
        Index("ix_offboarding_cases_offboarding_date", "offboarding_date"),
        {"schema": "hr"},
    )

    # ─── 状态机 ───
    STATUS_DRAFT = "draft"
    STATUS_APPROVING = "approving"
    STATUS_CLEARING = "clearing"
    STATUS_CERT_ISSUING = "cert_issuing"
    STATUS_DELIVERING = "delivering"
    STATUS_SIGNED = "signed"
    STATUS_CLOSED = "closed"
    STATUS_CANCELED = "canceled"
    STATUS_LABELS = {
        STATUS_DRAFT: "待发起审批",
        STATUS_APPROVING: "离职审批中",
        STATUS_CLEARING: "清退会签中",
        STATUS_CERT_ISSUING: "待开具证明",
        STATUS_DELIVERING: "证明送达中",
        STATUS_SIGNED: "已签字确认",
        STATUS_CLOSED: "已办结",
        STATUS_CANCELED: "已取消",
    }
    # 推进链（canceled/closed 除外）
    FLOW_ORDER = (
        STATUS_DRAFT, STATUS_APPROVING, STATUS_CLEARING,
        STATUS_CERT_ISSUING, STATUS_DELIVERING, STATUS_SIGNED, STATUS_CLOSED,
    )

    # ─── 离职类型（与离职台账口径一致）───
    TYPE_RESIGN = "辞职"
    TYPE_DISMISS = "辞退"
    TYPE_CONTRACT_END = "合同到期"
    TYPE_RETIRE = "退休"
    TYPE_OTHER = "其他"
    TYPE_LABELS = (TYPE_RESIGN, TYPE_DISMISS, TYPE_CONTRACT_END, TYPE_RETIRE, TYPE_OTHER)

    # ─── 审批轨（按职级路由飞书审批定义）───
    TRACK_STAFF = "staff"
    TRACK_DIRECTOR = "director"

    # ─── 证明模板 ───
    CERT_ELECTRONIC = "electronic"
    CERT_PAPER = "paper"

    # ─── 关联与编号 ───
    case_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="申请编号（LB-YYYYMMDD-XXXX）",
    )
    employee_id: Mapped[UUID] = mapped_column(
        nullable=False, comment="员工档案ID（逻辑关联，无外键）",
    )
    departure_record_id: Mapped[UUID | None] = mapped_column(
        nullable=True, comment="关联离职台账记录ID（发起时 upsert 建立，逻辑关联）",
    )

    # ─── 员工快照（办结后档案会变，列表展示用快照）───
    employee_number: Mapped[str] = mapped_column(String(32), nullable=False, comment="工号")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门")
    position: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="岗位")
    level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="级别（职级路由快照）")
    initiator_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="发起人姓名快照（台账「发起人」列）",
    )

    # ─── 离职信息 ───
    offboarding_date: Mapped[date] = mapped_column(Date, nullable=False, comment="离职日期")
    offboarding_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TYPE_RESIGN, server_default=TYPE_RESIGN,
        comment="离职类型: 辞职/辞退/合同到期/退休/其他",
    )
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="离职原因")
    employee_category: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="用工类型（员工性质快照）",
    )
    application_submitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否递交离职申请",
    )

    # ─── 状态机 ───
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=STATUS_DRAFT, server_default=STATUS_DRAFT,
        comment="状态: draft/approving/clearing/cert_issuing/delivering/signed/closed/canceled",
    )

    # ─── 审批编排 ───
    approval_track: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="审批轨: staff/director（按 level 前缀路由）",
    )
    approval_attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="审批发起次数（两阶段共用计数，幂等键后缀，撤销后重发递增）",
    )
    resignation_instance_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="离职审批飞书实例 Code",
    )
    resignation_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="离职审批办结时间",
    )
    clearance_instance_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="清退交接飞书实例 Code",
    )
    clearance_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="清退会签办结时间",
    )

    # ─── 离岗体检（重点岗位门禁）───
    health_check_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="是否需离岗体检（取员工 is_key_position，可改）",
    )
    health_check_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="离岗体检已完成登记",
    )
    health_check_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="离岗体检完成日期",
    )
    health_check_file_key: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="体检报告对象存储 key",
    )
    health_check_file_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="体检报告原始文件名",
    )

    # ─── 证明开具 ───
    cert_template: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="证明模板: electronic 电子单张（链接线上签收）/ paper 纸质两联（当面签收）",
    )
    cert_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="证明开具时间",
    )
    cert_storage_key: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="证明 PDF 对象存储 key",
    )
    cert_issued_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="开具人（HR 经办人姓名快照）",
    )

    # ─── 送达 ───
    mail_recipient: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="送达邮箱",
    )
    mail_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="邮件发送时间",
    )
    mail_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="邮件状态: sent/failed",
    )
    sms_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="短信接收号码（送达留痕）",
    )
    sms_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="短信状态: sent/not_configured/failed（通道预留）",
    )
    delivery_channel: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="签收渠道: mail/sms/paper",
    )

    # ─── 纸质两联版签收登记 ───
    paper_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="纸质证明当面签收时间",
    )
    paper_signed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="纸质证明签收人（员工本人）",
    )

    # ─── 办结 ───
    account_deactivated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="飞书账号已注销（HR 办结时勾选确认）",
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="办结时间",
    )
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="备注")

    # ─── 只读辅助 ───
    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def flow_index(self) -> int:
        """在推进链中的序号（canceled 视作 draft 位）。"""
        try:
            return self.FLOW_ORDER.index(self.status)
        except ValueError:
            return 0


class OffboardingClearanceItem(BaseModel):
    """清退交接明细项：四部门维度（行政后勤/财务/人力资源/工作部门），平台为工作数据源。

    数据来源：进入清退阶段落的默认清单（seed）、HR 手工登记（manual）；
    飞书清退审批实例办结后可按控件名约定回读存档（feishu_form）。
    扣补金额：deduction 扣款 / supplement 补发（台账「清退与结算」从本表聚合）。
    """

    __tablename__ = "offboarding_clearance_items"
    __table_args__ = (
        Index("ix_clearance_items_case", "case_id"),
        Index("ix_clearance_items_category", "category"),
        {"schema": "hr"},
    )

    CATEGORY_ADMIN = "admin"
    CATEGORY_FINANCE = "finance"
    CATEGORY_HR = "hr"
    CATEGORY_WORK = "work"
    CATEGORY_LABELS = {
        CATEGORY_ADMIN: "行政后勤部",
        CATEGORY_FINANCE: "财务部",
        CATEGORY_HR: "人力资源部",
        CATEGORY_WORK: "工作部门",
    }
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_DEDUCTED = "deducted"
    STATUS_LABELS = {
        STATUS_PENDING: "待确认",
        STATUS_CONFIRMED: "已清退",
        STATUS_DEDUCTED: "有扣补",
    }
    SOURCE_MANUAL = "manual"
    SOURCE_FEISHU = "feishu_form"
    SOURCE_SEED = "seed"

    case_id: Mapped[UUID] = mapped_column(
        nullable=False, comment="所属离职办结单ID（逻辑关联）",
    )
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="部门维度: admin/finance/hr/work",
    )
    item_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="清退事项")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING, server_default=STATUS_PENDING,
        comment="状态: pending/confirmed/deducted",
    )
    deduction_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True, comment="扣款金额",
    )
    supplement_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True, comment="补发金额",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
    confirmed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="确认人（经办人姓名）",
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="确认时间",
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SOURCE_MANUAL, server_default=SOURCE_MANUAL,
        comment="来源: manual 平台登记 / feishu_form 实例回读 / seed 进入清退时落的默认清单",
    )


class DepartureSavedView(BaseModel):
    """离职台账保存视图：个人维度，筛选条件与导出字段一键调用。"""

    __tablename__ = "departure_saved_views"
    __table_args__ = (
        Index("ix_departure_views_owner", "owner_user_id"),
        {"schema": "hr"},
    )

    owner_user_id: Mapped[UUID] = mapped_column(nullable=False, comment="归属用户ID")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="视图名称")
    filters: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="筛选条件（键=后端筛选参数名）",
    )
    columns: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="导出字段 key 列表",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", comment="默认视图",
    )


class HrExportLog(BaseModel):
    """HR 台账导出留痕（通用设计，module 区分台账；需求「导出行为留存记录」）。"""

    __tablename__ = "export_logs"
    __table_args__ = (
        Index("ix_export_logs_module", "module"),
        Index("ix_export_logs_created_at", "created_at"),
        {"schema": "hr"},
    )

    module: Mapped[str] = mapped_column(String(32), nullable=False, comment="台账: departure 起步")
    operator_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="操作人用户ID")
    operator_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="操作人姓名",
    )
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="筛选条件")
    columns: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="导出字段")
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="导出条数",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
