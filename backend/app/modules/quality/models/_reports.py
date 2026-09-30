"""Quality ORM 模型 —— 检验记录、杂质明细、报告单。"""

import uuid

from sqlalchemy import Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class ReportRecord(BaseModel):
    """报告单记录（生成的 COA 文件）。"""

    __tablename__ = "report_records"
    __table_args__ = (
        Index("ix_quality_report_record_inspection", "inspection_record_id"),
        Index("ix_quality_report_record_task", "test_task_id"),
        Index("ix_quality_report_record_created", "created_at"),
        # 流水号唯一（并发生成 COA 时数据库兜底防重号；历史空号记录不受约束）
        Index(
            "uq_quality_report_record_serial",
            "serial_no",
            unique=True,
            postgresql_where=text("serial_no IS NOT NULL"),
        ),
        {"schema": "quality"},
    )

    inspection_record_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="关联检验记录，逻辑引用 quality.inspection_records.id（任务驱动 COA 时为空）"
    )
    test_task_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="关联检验任务，逻辑引用 quality.quality_test_tasks.id（P2 任务驱动 COA）"
    )
    template_path: Mapped[str] = mapped_column(
        String(500), comment="使用的模板路径（如 万古霉素/3205.docx）"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    batch_number: Mapped[str] = mapped_column(String(100), comment="批号")
    serial_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="流水号（年月日+当日序号，如 26091801）"
    )
    file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="生成的 docx 文件存储路径（本地或 MinIO）"
    )
    file_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="文件大小（字节）"
    )
