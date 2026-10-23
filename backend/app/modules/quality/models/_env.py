"""环境监测模型：洁净区监测点台账与监测记录。"""

import uuid

from sqlalchemy import Float, Index, String
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
