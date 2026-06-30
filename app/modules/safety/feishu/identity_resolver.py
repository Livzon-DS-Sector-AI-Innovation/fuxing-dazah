"""隐患通知身份解析器。

职责：将隐患记录中的姓名/部门文本字段解析为飞书 open_id，
     供 send_user_card() 发送 DM 通知。

所有查询基于本地 identity.users / identity.departments 表（每日同步自飞书），
不直接调用飞书 Contact API，保持安全模块独立。

解析链路：
  ① 责任人        ← rectification_responsible_person_name
  ② 部门负责人    ← department → 部门 leader
  ③ 分管领导      ← department → 父部门 leader
  ④ 隐患发现人    ← discovered_by_name / discovered_by
  ⑤ 分管安全员    ← department → DEPT_CONFIG safety_officer
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.safety.models import HazardReport
    from app.platform.identity.models import Department, User

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 返回类型
# ═══════════════════════════════════════════════════════════════


@dataclass
class ResolvedPerson:
    """身份解析结果 — 包含发送飞书通知所需的全部标识。"""

    open_id: str
    user_id: str
    name: str
    department: str | None = None
    id: str = ""  # identity.users UUID

    def to_dict(self) -> dict[str, str | None]:
        return {
            "open_id": self.open_id,
            "user_id": self.user_id,
            "name": self.name,
            "department": self.department,
            "id": self.id or None,
        }

    def __repr__(self) -> str:
        return (
            f"ResolvedPerson(open_id={self.open_id!r}, "
            f"user_id={self.user_id!r}, name={self.name!r})"
        )


# ═══════════════════════════════════════════════════════════════
# 身份解析器
# ═══════════════════════════════════════════════════════════════


class IdentityResolver:
    """隐患通知身份解析器。

    用法：
        resolver = IdentityResolver(session)
        person = await resolver.resolve_department_leader("生产部")
        if person:
            await send_user_card(open_id=person.open_id, ...)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── 公开方法 ──────────────────────────────────────────────

    async def resolve_by_name(
        self,
        name: str,
        department_hint: str | None = None,
    ) -> ResolvedPerson | None:
        """按姓名查找用户 → open_id。

        Args:
            name: 用户姓名（如 Bitable「责任人」字段值）
            department_hint: 部门提示，多命中时用于消歧

        Returns:
            ResolvedPerson | None
        """
        if not name or not name.strip():
            logger.warning("resolve_by_name: name 为空，跳过")
            return None

        name = name.strip()
        user = await self._find_user_by_name(name, department_hint)
        if user is None:
            logger.warning("resolve_by_name: 未找到用户 name=%r", name)
            return None

        return self._user_to_person(user)

    async def resolve_department_leader(
        self,
        department_name: str,
    ) -> ResolvedPerson | None:
        """按部门名称查找部门负责人 → open_id。

        查找链路（配置优先）：
          1. DEPT_CONFIG → 命中则用 leader 姓名 → resolve_by_name
          2. identity.departments → 匹配部门 → 取 leader_user_id → _find_user_by_user_id

        Args:
            department_name: 部门名称（如 HazardReport.department）

        Returns:
            ResolvedPerson | None
        """
        dept = await self._find_department_by_name(department_name)
        if dept is None:
            logger.warning(
                "resolve_department_leader: 未找到部门 %r", department_name
            )
            return None

        # ── 配置优先：Bitable 人工维护的部门负责人 ──
        config = DEPARTMENT_CONFIG.get(dept.name)
        if config and config.get("leader"):
            leader_name = config["leader"]
            logger.info(
                "resolve_department_leader: %r → config leader %r",
                department_name, leader_name,
            )
            return await self.resolve_by_name(leader_name, department_hint=dept.name)

        # ── 回退：identity.departments 的 leader_user_id ──
        if not dept.leader_user_id:
            logger.warning(
                "resolve_department_leader: 部门 %r 无 leader_user_id", dept.name
            )
            return None

        leader = await self._find_user_by_user_id(dept.leader_user_id)
        if leader is None:
            logger.warning(
                "resolve_department_leader: leader %r 不在 identity.users",
                dept.leader_user_id,
            )
            return None

        logger.info(
            "resolve_department_leader: %r → %r (leader of %r)",
            department_name, leader.name, dept.name,
        )
        return self._user_to_person(leader, dept.name)

    async def resolve_supervising_leader(
        self,
        department_name: str,
    ) -> ResolvedPerson | None:
        """按部门名称查找分管领导 → open_id。

        查找链路（配置优先）：
          1. DEPT_CONFIG → 命中且有 supervisor → 用 supervisor 姓名 → resolve_by_name
          2. identity.departments → 父部门 leader → _find_user_by_user_id

        Args:
            department_name: 部门名称（如 HazardReport.department）

        Returns:
            ResolvedPerson | None
        """
        dept = await self._find_department_by_name(department_name)
        if dept is None:
            logger.warning(
                "resolve_supervising_leader: 未找到部门 %r", department_name
            )
            return None

        # ── 配置优先：Bitable 人工维护的分管领导 ──
        config = DEPARTMENT_CONFIG.get(dept.name)
        if config and config.get("supervisor"):
            supervisor_name = config["supervisor"]
            logger.info(
                "resolve_supervising_leader: %r → config supervisor %r",
                department_name, supervisor_name,
            )
            return await self.resolve_by_name(supervisor_name, department_hint=dept.name)

        # ── 回退：identity.departments 的父部门 leader ──
        if not dept.parent_feishu_department_id:
            logger.info(
                "resolve_supervising_leader: %r 无父部门，无分管领导", dept.name
            )
            return None

        parent_dept = await self._find_department_by_id(
            dept.parent_feishu_department_id
        )
        if parent_dept is None:
            logger.warning(
                "resolve_supervising_leader: 父部门 %r 不在 identity.departments",
                dept.parent_feishu_department_id,
            )
            return None

        if not parent_dept.leader_user_id:
            logger.warning(
                "resolve_supervising_leader: 父部门 %r 无 leader_user_id",
                parent_dept.name,
            )
            return None

        leader = await self._find_user_by_user_id(parent_dept.leader_user_id)
        if leader is None:
            logger.warning(
                "resolve_supervising_leader: 父部门 leader %r 不在 identity.users",
                parent_dept.leader_user_id,
            )
            return None

        logger.info(
            "resolve_supervising_leader: %r → 父部门 %r → leader %r",
            department_name, parent_dept.name, leader.name,
        )
        return self._user_to_person(leader, parent_dept.name)

    async def resolve_safety_officer(
        self,
        department_name: str,
    ) -> ResolvedPerson | None:
        """按部门名称查找分管安全员 → open_id。

        查找链路（仅配置）：
          1. DEPT_CONFIG → 命中且有 safety_officer → 用姓名 → resolve_by_name
          2. 无配置 → 返回 None（不报错，部门可能暂未指定安全员）

        Args:
            department_name: 部门名称（如 HazardReport.department）

        Returns:
            ResolvedPerson | None
        """
        dept = await self._find_department_by_name(department_name)
        if dept is None:
            logger.warning(
                "resolve_safety_officer: 未找到部门 %r", department_name
            )
            return None

        config = DEPARTMENT_CONFIG.get(dept.name)
        if not config or not config.get("safety_officer"):
            logger.info(
                "resolve_safety_officer: 部门 %r 未配置安全员", dept.name
            )
            return None

        officer_name = config["safety_officer"]
        logger.info(
            "resolve_safety_officer: %r → config safety_officer %r",
            department_name, officer_name,
        )
        return await self.resolve_by_name(officer_name, department_hint=dept.name)

    # ── 隐患模型便捷方法 ──────────────────────────────────────

    async def resolve_responsible_person(
        self, hazard: HazardReport,
    ) -> ResolvedPerson | None:
        """① 责任人：rectification_responsible_person_name → open_id。"""
        if not hazard.rectification_responsible_person_name:
            logger.warning(
                "hazard %s: rectification_responsible_person_name 为空",
                hazard.hazard_no,
            )
            return None
        return await self.resolve_by_name(
            hazard.rectification_responsible_person_name,
            department_hint=hazard.department,
        )

    async def resolve_hazard_department_leader(
        self, hazard: HazardReport,
    ) -> ResolvedPerson | None:
        """② 部门负责人：hazard.department → 部门 leader → open_id。"""
        if not hazard.department:
            logger.warning(
                "hazard %s: department 为空", hazard.hazard_no,
            )
            return None
        return await self.resolve_department_leader(hazard.department)

    async def resolve_hazard_supervising_leader(
        self, hazard: HazardReport,
    ) -> ResolvedPerson | None:
        """③ 分管领导：hazard.department → 父部门 leader → open_id。"""
        if not hazard.department:
            logger.warning(
                "hazard %s: department 为空", hazard.hazard_no,
            )
            return None
        return await self.resolve_supervising_leader(hazard.department)

    async def resolve_discoverer(
        self, hazard: HazardReport,
    ) -> ResolvedPerson | None:
        """④ 隐患发现人：discovered_by_name → open_id。"""
        if not hazard.discovered_by_name:
            logger.warning(
                "hazard %s: discovered_by_name 为空", hazard.hazard_no,
            )
            return None
        return await self.resolve_by_name(
            hazard.discovered_by_name,
            department_hint=hazard.department,
        )

    async def resolve_hazard_safety_officer(
        self, hazard: HazardReport,
    ) -> ResolvedPerson | None:
        """⑤ 分管安全员：hazard.department → DEPT_CONFIG safety_officer → open_id。"""
        if not hazard.department:
            logger.warning(
                "hazard %s: department 为空", hazard.hazard_no,
            )
            return None
        return await self.resolve_safety_officer(hazard.department)

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _user_to_person(
        user: User,
        department: str | None = None,
    ) -> ResolvedPerson:
        """将 identity.User ORM 对象转为 ResolvedPerson。"""
        return ResolvedPerson(
            open_id=user.feishu_open_id or "",
            user_id=user.feishu_user_id or "",
            name=user.name,
            department=department or user.department,
            id=str(user.id) if user.id else "",
        )

    async def _find_user_by_name(
        self,
        name: str,
        department_hint: str | None = None,
    ) -> User | None:
        """在 identity.users 中按姓名查找用户。

        策略：
          1. 精确匹配 name
          2. 命中 1 个 → 直接返回
          3. 命中 > 1 个且有 department_hint → 用部门消歧
          4. 命中 0 个 → 返回 None
        """
        from app.platform.identity.models import User as IdentityUser

        stmt = select(IdentityUser).where(
            IdentityUser.name == name,
            IdentityUser.is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        users = list(result.scalars().all())

        if not users:
            return None

        if len(users) == 1:
            return users[0]

        # 多人同名，尝试用部门提示消歧
        if department_hint:
            filtered = [
                u for u in users
                if u.department and department_hint in u.department
            ]
            if len(filtered) == 1:
                logger.info(
                    "_find_user_by_name: %r 多命中 %d，部门消歧 → %r",
                    name, len(users), filtered[0].name,
                )
                return filtered[0]
            if filtered:
                logger.warning(
                    "_find_user_by_name: %r 部门消歧后仍有 %d 人，取第一个",
                    name, len(filtered),
                )
                return filtered[0]

        logger.warning(
            "_find_user_by_name: %r 匹配 %d 人，无法消歧，取第一个",
            name, len(users),
        )
        return users[0]

    async def _find_user_by_user_id(self, user_id: str) -> User | None:
        """按 feishu_user_id 查找用户，失败时回退 feishu_open_id。

        部门表中的 leader_user_id 可能是 user_id 或 open_id 格式，
        取决于飞书 API 调用时的 user_id_type 参数。
        """
        from app.platform.identity.models import User as IdentityUser

        # 先按 user_id 查
        stmt = select(IdentityUser).where(
            IdentityUser.feishu_user_id == user_id,
            IdentityUser.is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        # 回退按 open_id 查
        stmt2 = select(IdentityUser).where(
            IdentityUser.feishu_open_id == user_id,
            IdentityUser.is_deleted == False,  # noqa: E712
        )
        result2 = await self._session.execute(stmt2)
        user2 = result2.scalar_one_or_none()
        if user2 is not None:
            return user2

        return None

    async def _find_user_by_email(self, email: str) -> User | None:
        """按 email 查找用户（Bitable open_id 与 identity.users open_id 不匹配时的回退）。"""
        from app.platform.identity.models import User as IdentityUser

        if not email:
            return None
        stmt = select(IdentityUser).where(
            IdentityUser.email == email,
            IdentityUser.is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_department_by_name(self, name: str) -> Department | None:
        """在 identity.departments 中模糊匹配部门。

        策略（按优先级）：
          1. 精确匹配 name
          2. name 以查询结尾（如 '生产部' 匹配 '原料药生产部'）
          3. name 包含查询
          4. 多个匹配 → 取第一个 + warning
        """
        from app.platform.identity.models import Department as IdentityDept

        if not name or not name.strip():
            return None

        name = name.strip()

        # 策略 1: 精确匹配
        stmt = select(IdentityDept).where(
            IdentityDept.name == name,
            IdentityDept.is_deleted == False,  # noqa: E712
            IdentityDept.status_is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        dept = result.scalar_one_or_none()
        if dept is not None:
            return dept

        # 策略 2+3: 模糊匹配
        stmt = select(IdentityDept).where(
            IdentityDept.is_deleted == False,  # noqa: E712
            IdentityDept.status_is_deleted == False,  # noqa: E712
            or_(
                IdentityDept.name.ilike(f"%{name}"),
                IdentityDept.name.ilike(f"%{name}%"),
            ),
        ).order_by(IdentityDept.order, IdentityDept.name)
        result = await self._session.execute(stmt)
        depts = list(result.scalars().all())

        if not depts:
            return None

        if len(depts) > 1:
            logger.warning(
                "_find_department_by_name: %r 模糊匹配 %d 个部门，取第一个 %r",
                name, len(depts), depts[0].name,
            )

        return depts[0]

    async def _find_department_by_id(
        self, feishu_department_id: str,
    ) -> Department | None:
        """按 feishu_department_id 精确查找部门。"""
        from app.platform.identity.models import Department as IdentityDept

        stmt = select(IdentityDept).where(
            IdentityDept.feishu_department_id == feishu_department_id,
            IdentityDept.is_deleted == False,  # noqa: E712
            IdentityDept.status_is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
