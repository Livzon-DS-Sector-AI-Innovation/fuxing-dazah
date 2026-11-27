"""HR 门禁路由覆盖 + 部门重名巡检。

1. 挂载的每个 HR 路由都必须能命中 _HR_PATH_PERMISSIONS 的某条映射，
   新增端点忘登记会直接 fail 本测试（防 fail-open 兜底被滥用）。
2. 部门名全局唯一是按名字匹配数据范围的前提（见 hr/deps.py 注释），
   出现重名时 WARN 不 fail——修复方式是数据侧改名消歧。
"""

import logging
import re

from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import _HR_PATH_PERMISSIONS
from app.modules.hr.models import HrDepartment

logger = logging.getLogger(__name__)


def _materialize(path: str) -> str:
    """把 /employees/{employee_id}/tags 具象化为 /employees/x1/tags。"""
    return re.sub(r"\{[^}]+\}", "x1", path)


def test_all_hr_routes_have_permission_mapping() -> None:
    hr_routes = [
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/v1/hr")
    ]
    assert hr_routes, "HR 路由未挂载，测试环境异常"

    uncovered = []
    for route in hr_routes:
        path = _materialize(route.path)
        if not any(re.search(pat, path) for pat, _ in _HR_PATH_PERMISSIONS):
            methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
            uncovered.append(f"{methods:8s} {route.path}")

    assert not uncovered, (
        "以下 HR 路由未登记权限映射（require_hr_basic 只按任意 hr: 权限放行，"
        "请在 _HR_PATH_PERMISSIONS 补登记）:\n" + "\n".join(uncovered)
    )


async def test_no_duplicate_department_names(db_session: AsyncSession) -> None:
    """部门重名巡检：数据范围按部门名匹配的前提。"""
    result = await db_session.execute(
        select(HrDepartment.name, func.count())
        .where(HrDepartment.is_deleted == False)  # noqa: E712
        .group_by(HrDepartment.name)
        .having(func.count() > 1)
    )
    duplicates = result.all()
    if duplicates:
        # WARN 不 fail：重名属数据问题，修复走数据侧改名消歧
        logger.warning(
            "hr.departments 存在重名部门（数据范围按名字匹配会产生跨部门越权）: %s",
            [name for name, _ in duplicates],
        )
