"""环境监测模型：洁净区监测点台账与监测记录。"""

import uuid
from typing import Any

from sqlalchemy import Float, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class QualityEnvPoint(BaseModel):
    """监测点台账：房间/点位 + 监测类型 + 警戒限/行动限。"""

    __tablename__ = "quality_env_points"
    __table_args__ = (
        Index("ix_quality_env_point_room", "room"),
        Index("ix_quality_env_point_no", "point_no"),
        {"schema": "quality"},
    )

    room: Mapped[str] = mapped_column(String(128), nullable=False, comment="房间/区域")
    point_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="点位编号")
    monitor_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="settle 沉降菌 / float 浮游菌 / particle 悬浮粒子 / temp_humidity 温湿度 / pressure 压差",
    )
    frequency: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="监测频次 per_batch 每批 / weekly 每周 / monthly 每月（3b 周期计划用）"
    )
    alert_limit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="警戒限")
    action_limit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="行动限")
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", comment="active 启用 / inactive 停用"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityEnvRecord(BaseModel):
    """监测记录：按点位填报结果，快照当时警戒限/行动限并判定三态。"""

    __tablename__ = "quality_env_records"
    __table_args__ = (
        Index("ix_quality_env_record_point", "point_id"),
        Index("ix_quality_env_record_date", "record_date"),
        {"schema": "quality"},
    )

    point_id: Mapped[uuid.UUID] = mapped_column(nullable=False, comment="监测点，逻辑引用 quality_env_points.id")
    record_date: Mapped[str] = mapped_column(String(32), nullable=False, comment="监测日期 YYYY-MM-DD")
    result_value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="检测结果值")
    alert_limit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="判定时警戒限快照")
    action_limit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="判定时行动限快照")
    judge: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="pass 合格 / alert 超警戒 / action 超行动"
    )
    handle_status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open",
        comment="open 未处理 / handled 已处理（仅超行动限记录需要闭环）",
    )
    handled_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="处理日期 YYYY-MM-DD")
    handled_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="处理人，逻辑引用 identity.users.id")
    handled_remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="处理说明")
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="填报人，逻辑引用 identity.users.id")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityShiftTeam(BaseModel):
    """排班班组：固定成员，轮换当班（一般两个班组同时当班，每三天交替）。"""

    __tablename__ = "quality_shift_teams"
    __table_args__ = (
        Index("ix_quality_shift_team_seq", "seq"),
        {"schema": "quality"},
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="班组名")
    group_key: Mapped[str] = mapped_column(
        String(32), default="仪器组", server_default="仪器组",
        comment="班组归属组别（仪器组/生物组/理化组，互相独立轮换）",
    )
    member_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="班组成员（identity.users.id 字符串列表）"
    )
    seq: Mapped[int] = mapped_column(Integer, default=0, comment="排序（轮换顺序按 seq）")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityShiftConfig(BaseModel):
    """排班轮换配置（单行，key=rotation）：基准日期 + 轮换周期天数 + 同时当班班组数。"""

    __tablename__ = "quality_shift_configs"
    __table_args__ = (
        Index("uq_quality_shift_config_key", "key", unique=True,
              postgresql_where=text("is_deleted = false")),
        {"schema": "quality"},
    )

    key: Mapped[str] = mapped_column(String(32), nullable=False, comment="配置键（rotation）")
    value: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="{start_date, period_days, duty_teams}"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityBatchRelease(BaseModel):
    """批放行记录：已完成检验任务发起放行，快照检验汇总，专员放行留痕。"""

    __tablename__ = "quality_batch_releases"
    __table_args__ = (
        Index("ix_quality_release_batch", "batch_no"),
        Index("ix_quality_release_status", "status"),
        {"schema": "quality"},
    )

    batch_no: Mapped[str] = mapped_column(String(100), nullable=False, comment="批号")
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="产品名称")
    task_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="关联检验任务（逻辑引用）")
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="发起时检验汇总快照（判定/复核/报告单/留样）"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", comment="pending 待放行 / released 已放行 / void 已作废"
    )
    released_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="放行人")
    released_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="放行日期 YYYY-MM-DD")
    release_remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="放行备注")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityEnvPlan(BaseModel):
    """环境监测周期计划（3b）：每日为应测点位生成计划行，完成状态按当日记录派生。"""

    __tablename__ = "quality_env_plans"
    __table_args__ = (
        Index("ix_quality_env_plan_date", "plan_date"),
        Index(
            "uq_quality_env_plan_point_date", "point_id", "plan_date",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    plan_date: Mapped[str] = mapped_column(String(10), nullable=False, comment="应测日期 YYYY-MM-DD")
    point_id: Mapped[uuid.UUID] = mapped_column(nullable=False, comment="监测点，逻辑引用 quality_env_points.id")
    room: Mapped[str] = mapped_column(String(128), nullable=False, comment="房间快照")
    point_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="点位编号快照")
    monitor_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="监测类型快照")
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="频次快照")
