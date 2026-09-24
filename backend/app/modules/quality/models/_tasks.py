"""Quality ORM 模型 —— 检验记录、杂质明细、报告单。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class QualityTestTask(BaseModel):
    """检验任务（检阅单）：选产品+批号+日期，从标准库快照全部检验项目行。"""

    __tablename__ = "quality_test_tasks"
    __table_args__ = (
        Index(
            "uq_quality_test_task_product_batch",
            "product_name",
            "batch_number",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_test_task_product", "product_name"),
        Index("ix_quality_test_task_status", "status"),
        Index("ix_quality_test_task_report_date", "report_date"),
        {"schema": "quality"},
    )

    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    batch_number: Mapped[str] = mapped_column(String(100), comment="批号")
    production_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="生产日期（YYYY-MM-DD）"
    )
    expiry_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="效期（生产日期+x年-1天，YYYY-MM-DD）"
    )
    form_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="COA 表格编号，如 EX-HA-5246-001"
    )
    report_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="出报日期（YYYY-MM-DD，可后补；关联当日机器人任务推送）"
    )
    specification: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="本批规格（从标准文档规格中选定，如 5kg/听）"
    )
    standard_document_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="快照来源标准文档，逻辑引用 quality.quality_standard_documents.id（多文档时为主文档）",
    )
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress", server_default="in_progress",
        comment="任务状态：in_progress 填报中 / completed 已完成 / void 已作废",
    )

class QualityTaskAttachment(BaseModel):
    """检验任务原始证据附件：计算表/电子图谱等，MinIO 持久化随时调取。"""

    __tablename__ = "quality_task_attachments"
    __table_args__ = (
        Index("ix_quality_task_attachment_task", "task_id"),
        {"schema": "quality"},
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联检验任务，逻辑引用 quality.quality_test_tasks.id"
    )
    filename: Mapped[str] = mapped_column(String(255), comment="原始文件名")
    content_type: Mapped[str] = mapped_column(
        String(100), default="application/octet-stream", server_default="application/octet-stream"
    )
    object_key: Mapped[str] = mapped_column(
        String(500), comment="MinIO 对象键/本地相对路径（attachments/{task_id}/{uuid}_{filename}）"
    )
    size: Mapped[int] = mapped_column(Integer, default=0, server_default="0", comment="文件大小（字节）")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="上传人，逻辑引用 identity.users.id"
    )
    source: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual",
        comment="来源：manual 人工上传 / parse 液相计算表自动归档",
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")

class QualityTaskReview(BaseModel):
    """任务复核记录：两名不同复核人通过后任务完成（电子审核）。"""

    __tablename__ = "quality_task_reviews"
    __table_args__ = (
        Index("ix_quality_task_review_task", "task_id"),
        Index(
            "uq_quality_task_review_task_reviewer",
            "task_id",
            "reviewer_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联检验任务，逻辑引用 quality.quality_test_tasks.id"
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(comment="复核人，逻辑引用 identity.users.id")
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="复核备注")

class QualityTestResult(BaseModel):
    """检验任务结果行：标准快照 + 填报结果（一手数据本体）。"""

    __tablename__ = "quality_test_results"
    __table_args__ = (
        Index("ix_quality_test_result_task", "task_id"),
        Index("ix_quality_test_result_standard_item", "standard_item_id"),
        Index("ix_quality_test_result_item_name", "item_name"),
        Index(
            "uq_quality_test_result_task_sop",
            "task_id",
            "sop_no",
            "item_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联检验任务，逻辑引用 quality.quality_test_tasks.id"
    )
    standard_item_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="快照来源标准行，逻辑引用 quality.quality_standard_items.id（临时新增行为空）",
    )
    # ── 标准快照（建任务时定格，标准修订不影响历史任务）──
    seq: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="标准库序号快照（排序用）"
    )
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="检验项目大类快照"
    )
    item_name: Mapped[str] = mapped_column(String(200), comment="项目名称快照")
    sop_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="SOP 号快照（P1 解析映射键之一）"
    )
    standard_text: Mapped[str | None] = mapped_column(
        String(300), nullable=True, comment="合格标准原文快照（文字标准为纯文字）"
    )
    operator: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="比较运算符快照：≤ ≥ < > 范围"
    )
    limit_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="限度下限快照"
    )
    limit_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="限度上限快照"
    )
    method_source: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="方法来源快照"
    )
    remark: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注快照，如 加*每年仅1批"
    )
    # ── 填报结果 ──
    result_text: Mapped[str | None] = mapped_column(
        String(300), nullable=True, comment="填报结果原文（文字型判定用）"
    )
    result_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="填报数值（数值型判定用）"
    )
    is_pass: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="合格判定（未填报为 NULL）"
    )
    judge_mode: Mapped[str] = mapped_column(
        String(10), default="auto", server_default="auto",
        comment="判定方式：auto 数值自动判定 / manual 人工判定",
    )
    # ── P1 解析预留 ──
    source: Mapped[str] = mapped_column(
        String(10), default="manual", server_default="manual",
        comment="数据来源：manual 手工填报 / parse 液相解析映射",
    )
    inspection_record_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="关联液相解析记录，逻辑引用 quality.inspection_records.id（P1 预留）",
    )
    filled_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="最近填报人，逻辑引用 identity.users.id（P0 不注入）"
    )
    filled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近填报时间"
    )
