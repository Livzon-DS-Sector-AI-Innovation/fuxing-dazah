from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class User(BaseModel):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("employee_no", name="uq_identity_users_employee_no"),
        UniqueConstraint("feishu_user_id", name="uq_identity_users_feishu_user_id"),
        {"schema": "identity"},
    )

    name: Mapped[str] = mapped_column(String(100))
    employee_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feishu_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feishu_open_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    feishu_department_ids: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="飞书部门ID列表，JSON数组"
    )
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Department(BaseModel):
    """飞书组织架构部门（本地同步副本）"""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint(
            "feishu_department_id",
            name="uq_identity_departments_feishu_id",
        ),
        {"schema": "identity"},
    )

    feishu_department_id: Mapped[str] = mapped_column(
        String(64), unique=True, comment="飞书部门 open_department_id"
    )
    name: Mapped[str] = mapped_column(String(200), comment="部门名称")
    parent_feishu_department_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="父部门 ID"
    )
    leader_user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="部门主管 user_id"
    )
    member_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="部门成员数"
    )
    status_is_deleted: Mapped[bool | None] = mapped_column(
        comment="飞书侧是否已删除", nullable=True, default=False
    )
    path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="部门路径 JSON，如 [{'name':'公司','id':'xxx'},...]",
    )
    order: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="同级排序"
    )
