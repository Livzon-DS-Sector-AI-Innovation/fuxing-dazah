"""Quality ORM 模型 —— 检验记录、杂质明细、报告单。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class InspectionRecord(BaseModel):
    """液相解析检验记录。"""

    __tablename__ = "inspection_records"
    __table_args__ = (
        Index(
            "uq_quality_inspection_records_batch",
            "product_name",
            "batch_number",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_inspection_records_product", "product_name"),
        Index("ix_quality_inspection_records_created", "created_at"),
        {"schema": "quality"},
    )

    # 基本信息
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    batch_number: Mapped[str] = mapped_column(String(100), comment="批号")
    form_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="表格编号（如 EX-HA-5246-001）"
    )
    standard_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="标准类型：USP、EP、CP"
    )

    # 供试液 A 峰面积
    total_peak_area_a_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 总峰面积 第一份"
    )
    total_peak_area_a_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 总峰面积 第二份"
    )
    main_peak_area_a_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 主峰面积 第一份"
    )
    main_peak_area_a_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 主峰面积 第二份"
    )
    total_impurity_area_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="杂质总峰面积 At 第一份"
    )
    total_impurity_area_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="杂质总峰面积 At 第二份"
    )
    any_unknown_impurity_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="任何未知杂质 Ax 第一份"
    )
    any_unknown_impurity_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="任何未知杂质 Ax 第二份"
    )

    # 供试液 B 峰面积
    main_peak_area_b_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液B 主峰面积 Ab 第一份"
    )
    main_peak_area_b_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液B 主峰面积 Ab 第二份"
    )

    # 判定结果
    all_pass: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否全部合格"
    )

    # 原始数据与文件
    raw_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="完整原始解析数据备份"
    )
    excel_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="上传的原始 Excel 文件名"
    )


class InspectionImpurity(BaseModel):
    """检验杂质明细（一对多关联检验记录）。"""

    __tablename__ = "inspection_impurities"
    __table_args__ = (
        Index("ix_quality_impurities_record", "inspection_record_id"),
        {"schema": "quality"},
    )

    inspection_record_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联检验记录，逻辑引用 quality.inspection_records.id"
    )
    name: Mapped[str] = mapped_column(String(100), comment="杂质名称（如 RS1、杂质A）")
    first_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="第一份百分比"
    )
    second_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="第二份百分比"
    )
    limit_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="合格限度值"
    )
    is_pass: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="合格判定"
    )


class ReportRecord(BaseModel):
    """报告单记录（生成的 COA 文件）。"""

    __tablename__ = "report_records"
    __table_args__ = (
        Index("ix_quality_report_record_inspection", "inspection_record_id"),
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
    file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="生成的 docx 文件存储路径（本地或 MinIO）"
    )
    file_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="文件大小（字节）"
    )


class QualityStandardDocument(BaseModel):
    """质量标准文档（一个产品代号一份，如 SOP.02.3292.003 ↔ 代号 HAS）。"""

    __tablename__ = "quality_standard_documents"
    __table_args__ = (
        Index(
            "uq_quality_std_doc_file_no",
            "file_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_std_doc_product", "product_name"),
        {"schema": "quality"},
    )

    file_no: Mapped[str] = mapped_column(
        String(100), comment="文件编号，如 SOP.02.3292.003"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    product_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="产品代号，如 HAS"
    )
    product_internal_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="产品代码，如 30205"
    )
    specification: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="产品规格，如 5kg/听"
    )
    valid_years: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="有效期，如 36个月"
    )
    effective_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="生效日期"
    )
    version: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="版本号，如 003"
    )
    template_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="绑定的 COA 报告模板路径（如 万古霉素/3205.docx）"
    )


class QualityStandardItem(BaseModel):
    """标准项目行：以 SOP 号为匹配键；数值标准自动判定，纯文字标准保留（operator/limit 为空，人工判定）。"""

    __tablename__ = "quality_standard_items"
    __table_args__ = (
        Index("ix_quality_std_item_doc", "document_id"),
        Index(
            "uq_quality_std_item_sop",
            "document_id",
            "sop_no",
            "item_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联标准文档，逻辑引用 quality.quality_standard_documents.id"
    )
    seq: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="序号（文档中的检验项目序号）"
    )
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="检验项目大类，如 性状/有关物质"
    )
    item_name: Mapped[str] = mapped_column(
        String(200), comment="子项目名称（仅展示参考，匹配以 SOP 号为准）"
    )
    sop_no: Mapped[str] = mapped_column(
        String(64), comment="检验方法 SOP 编号（匹配键）"
    )
    standard_text: Mapped[str] = mapped_column(
        String(300), comment="合格标准原文，如 ≤3.0%"
    )
    operator: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="比较运算符：≤ ≥ < > 范围"
    )
    limit_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="限度下限（范围时使用）"
    )
    limit_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="限度上限"
    )
    method_source: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="方法来源：IP / Ph.Eur. / USP / 内部"
    )
    remark: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注，如 加*每年仅1批"
    )


class CoaTemplateBinding(BaseModel):
    """COA 模板 ↔ 标准文档绑定（业务规则：一份 COA 唯一绑定一份 SOP；
    一份 SOP 可绑定多份 COA）。绑定关系存在 COA 一侧。"""

    __tablename__ = "quality_coa_template_bindings"
    __table_args__ = (
        Index(
            "uq_quality_coa_binding_template",
            "template_path",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_coa_binding_doc", "standard_document_id"),
        {"schema": "quality"},
    )

    template_path: Mapped[str] = mapped_column(
        String(500), comment="COA 模板路径（如 3205.docx），唯一"
    )
    standard_document_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="绑定的标准文档，逻辑引用 quality.quality_standard_documents.id"
    )
    sop_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="绑定的 SOP 号快照（标准文档 file_no）"
    )
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注，如 赞比亚专用"
    )


class LcTemplateConfig(BaseModel):
    """液相计算表模板配置：以表号（EX-xx-xxxx-vvv）为键，描述取值位置。"""

    __tablename__ = "quality_lc_template_configs"
    __table_args__ = (
        Index(
            "uq_quality_lc_template_table_no",
            "table_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    table_no: Mapped[str] = mapped_column(
        String(50), comment="计算表表号，如 EX-HA-8329-002（模板识别键）"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称（与标准库一致）")
    sop_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="表号对应的检测 SOP 号（一般 1:1 映射，例外清单另行整理）",
    )
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="模板描述，如 万古霉素冻干粉-赞比亚"
    )
    config: Mapped[dict] = mapped_column(
        JSONB, comment="取值配置 JSON：批号标签、组分区块（名称列/结果列/行距/平均规则/值格式）"
    )


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


class QualityTestResult(BaseModel):
    """检验任务结果行：标准快照 + 填报结果（一手数据本体）。"""

    __tablename__ = "quality_test_results"
    __table_args__ = (
        Index("ix_quality_test_result_task", "task_id"),
        Index("ix_quality_test_result_standard_item", "standard_item_id"),
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


