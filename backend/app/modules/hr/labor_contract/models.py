"""劳动合同 ORM 模型：一份合同一行，签订次数驱动期限自动计算与续签状态流转。

替代口径：原先合同数据散在 employees.contract_start/end_date（第一次）与
onboarding_records 四组合同起止宽表上，无法表达「签订次数 → 期限规则 →
续签状态机」。本表为劳动合同的唯一事实源；宽表迁移后只读不回写。
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class LaborContract(BaseModel):
    """劳动合同。

    期限规则（服务端按签订次数自动计算落库，前端只读）：第 1 次 3 年、
    第 2 次 6 年（累计满 9 年）、第 3 次起无固定期限，均自该份合同起始日
    起算、不按入职日；存量导入的非标准期限以 term_type='fixed' +
    term_years 记录实际年数。

    状态机：
        active → pending_renewal（公告期，已发起飞书审批/站内待审批）
               → renewing（审批通过，待员工到场签订）
               → 签订后生成 seq+1 新行 active、旧行 superseded
        审批拒绝 → terminated（终止，转离职流程）
        到期未续签 → expired_unrenewed（仍可补办续签）
    归档维度（与状态正交）：archive_status unarchived/archived，合同行上的
    archive_* 是当前版扫描件的冗余快照（台账筛选免 join），版本明细见
    ContractArchiveVersion。

    部分唯一约束 (employee_number, seq_no)：仅约束未删除且非 superseded/
    terminated 的行——同一员工同一签订次数只允许一份有效合同，删除或
    终止后允许重新录入（规避软删除下的重复添加冲突）。
    """

    __tablename__ = "labor_contracts"
    __table_args__ = (
        Index("ix_labor_contracts_employee_number", "employee_number"),
        Index("ix_labor_contracts_status", "status"),
        Index("ix_labor_contracts_department", "department"),
        Index("ix_labor_contracts_end_date", "end_date"),
        Index("ix_labor_contracts_sign_token_hash", "sign_token_hash"),
        Index(
            "uq_labor_contracts_employee_seq",
            "employee_number",
            "seq_no",
            unique=True,
            postgresql_where=text(
                "is_deleted = false AND status NOT IN ('superseded', 'terminated')"
            ),
        ),
        {"schema": "hr"},
    )

    # ─── 状态机 ───
    STATUS_ACTIVE = "active"
    STATUS_PENDING_RENEWAL = "pending_renewal"
    STATUS_RENEWING = "renewing"
    STATUS_SUPERSEDED = "superseded"
    STATUS_TERMINATED = "terminated"
    STATUS_EXPIRED_UNRENEWED = "expired_unrenewed"
    STATUS_LABELS = {
        STATUS_ACTIVE: "生效中",
        STATUS_PENDING_RENEWAL: "公告期",
        STATUS_RENEWING: "续签办理中",
        STATUS_SUPERSEDED: "已续签取代",
        STATUS_TERMINATED: "已终止",
        STATUS_EXPIRED_UNRENEWED: "到期未续签",
    }

    # ─── 期限类型 ───
    TERM_FIXED_3Y = "fixed_3y"
    TERM_FIXED_6Y = "fixed_6y"
    TERM_FIXED = "fixed"  # 存量非标准固定期限（年数见 term_years）
    TERM_OPEN = "open"
    TERM_LABELS = {
        TERM_FIXED_3Y: "3 年",
        TERM_FIXED_6Y: "6 年",
        TERM_FIXED: "固定期限",
        TERM_OPEN: "无固定期限",
    }

    # ─── 审批方式 ───
    APPROVAL_FEISHU = "feishu"
    APPROVAL_MANUAL = "manual"
    DECISION_AGREE = "agree"
    DECISION_DISAGREE = "disagree"

    # ─── 员工快照（录入/续签时固化，员工异动不回写历史合同行）───
    employee_number: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="工号"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门")
    position: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="岗位")

    # ─── 合同本体 ───
    seq_no: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="签订次数（1 起算）"
    )
    term_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="期限类型: fixed_3y/fixed_6y/fixed/open"
    )
    term_years: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="固定期限年数（open 为空；存量非标准期限记实际值）"
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="合同起始日")
    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="合同到期日（无固定期限为空，按期限规则自动计算）"
    )
    sign_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="实际签订日"
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE,
        comment="状态: active/pending_renewal/renewing/superseded/terminated/expired_unrenewed",
    )
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="备注")

    # ─── 部门续签审批 ───
    dept_decision: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="审批结论: agree/disagree"
    )
    dept_decision_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="审批人（站内勾选时为人名，飞书审批固定为'飞书审批'）"
    )
    dept_decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    approval_mode: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="本次公告期的审批方式: feishu/manual"
    )
    approval_instance_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书审批实例 Code（离职台账'审批依据'引用）"
    )
    approval_attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="审批发起次数（幂等键后缀，撤销后重发递增）",
    )

    # ─── 盖章 / 领取 / 员工线上签字 ───
    stamped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="公司盖章完成时间（触发领取通知）"
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="员工领取时间（触发签字提醒）"
    )
    sign_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="员工线上签字确认时间（已领取凭证）"
    )
    sign_token_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="签字一次性 token 的 sha256（确认后清空，重发即作废旧链接）"
    )

    # ─── 终止 ───
    terminated_reason: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="终止原因（部门不同意续签/到期未续签/离职终止等）"
    )
    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="终止时间"
    )
    departure_record_id: Mapped[UUID | None] = mapped_column(
        comment="关联离职台账记录 ID（逻辑关联，无外键）",
        nullable=True,
    )

    # ─── 电子归档（需求归档规则：逐页合并一份、版本保留、未归档标注）───
    ARCHIVE_UNARCHIVED = "unarchived"
    ARCHIVE_ARCHIVED = "archived"
    ARCHIVE_LABELS = {
        ARCHIVE_UNARCHIVED: "未归档",
        ARCHIVE_ARCHIVED: "已归档",
    }
    archive_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ARCHIVE_UNARCHIVED,
        server_default=ARCHIVE_UNARCHIVED,
        comment="归档状态: unarchived/archived（已上传扫描件）",
    )
    archive_file_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="当前版扫描件展示名（工号+姓名+签订次数+起止日期，服务端生成）",
    )
    archive_uploaded_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="最近一次归档人"
    )
    archive_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次归档时间"
    )

    # ─── 只读辅助 ───
    @property
    def term_label(self) -> str:
        if self.term_type == self.TERM_FIXED:
            # term_years 为空仅见于离职台账按起止日期建档的不足一年合同
            return "不足 1 年" if not self.term_years else f"{self.term_years} 年"
        return self.TERM_LABELS.get(self.term_type, self.term_type)

    @property
    def seq_label(self) -> str:
        if self.seq_no <= 1:
            return "第一次签订"
        if self.seq_no == 2:
            return "第二次续签"
        return f"第 {self.seq_no} 次（无固定期限）"

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)


class ContractArchiveVersion(BaseModel):
    """合同扫描件版本：一份合同一个合并文件，换传即升版本（旧行保留可查）。

    当前版唯一：部分唯一索引 (contract_id) WHERE is_current AND NOT is_deleted；
    归档人/时间取 BaseModel 的 created_by/created_at。原件存对象存储
    （storage_key 用英文安全字符），展示/下载名按需求规则由服务端生成。
    """

    __tablename__ = "contract_archive_versions"
    __table_args__ = (
        Index("ix_contract_archive_contract", "contract_id"),
        Index(
            "uq_contract_archive_current",
            "contract_id",
            unique=True,
            postgresql_where=text("is_current = true AND is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    SOURCE_SINGLE = "single"
    SOURCE_BATCH = "batch"

    contract_id: Mapped[UUID] = mapped_column(
        nullable=False, comment="劳动合同 ID（逻辑关联，无外键）"
    )
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="版本号（1 起算）"
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否当前版本",
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="对象存储 key")
    file_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="展示/下载文件名（工号+姓名+签订次数+起止日期）"
    )
    content_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="MIME 类型")
    size: Mapped[int] = mapped_column(Integer, nullable=False, comment="文件大小（字节）")
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="备注")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SOURCE_SINGLE, server_default=SOURCE_SINGLE,
        comment="来源: single 单个上传 / batch 批量挂接",
    )


class ContractAccessLog(BaseModel):
    """合同扫描件调阅/下载留痕（需求归档规则第 8 条：调阅下载留痕）。

    与平台审计双写：平台审计是全站统一流水，本表供合同详情按合同聚合展示。
    """

    __tablename__ = "contract_access_logs"
    __table_args__ = (
        Index("ix_contract_access_contract", "contract_id"),
        Index("ix_contract_access_created", "created_at"),
        {"schema": "hr"},
    )

    ACTION_VIEW = "view"
    ACTION_DOWNLOAD = "download"
    ACTION_LABELS = {ACTION_VIEW: "在线查看", ACTION_DOWNLOAD: "下载"}

    contract_id: Mapped[UUID] = mapped_column(nullable=False, comment="劳动合同 ID（逻辑关联，无外键）")
    version_id: Mapped[UUID | None] = mapped_column(
        nullable=True, comment="被调阅的扫描件版本 ID"
    )
    viewer_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="调阅人用户 ID")
    viewer_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="调阅人姓名")
    action: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="调阅动作: view 在线查看 / download 下载"
    )
