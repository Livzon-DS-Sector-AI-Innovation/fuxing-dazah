"""Safety ORM models."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


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


