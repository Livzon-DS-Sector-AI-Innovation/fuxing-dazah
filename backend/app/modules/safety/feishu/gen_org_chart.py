"""生成公司组织架构图 (Markdown)。

用法: uv run python -X utf8 -m app.modules.safety.feishu.gen_org_chart
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from app.core.database import async_session_factory
from app.platform.identity.models import Department, User

logger = logging.getLogger(__name__)

_OUTPUT = Path(__file__).resolve().parent.parent.parent.parent.parent / "org_chart.md"


async def generate(output_path: str | Path | None = None) -> str:
    """生成组织架构 Markdown 并写入文件。

    Args:
        output_path: 输出路径，默认项目根目录 org_chart.md

    Returns:
        Markdown 文本
    """
    out_path = Path(output_path) if output_path else _OUTPUT

    async with async_session_factory() as session:
        # 查所有部门
        stmt = select(Department).where(
            Department.is_deleted == False,  # noqa: E712
            Department.status_is_deleted == False,  # noqa: E712
        ).order_by(Department.order, Department.name)
        result = await session.execute(stmt)
        depts = list(result.scalars().all())

        # 查所有用户，双索引 (user_id / open_id)
        stmt2 = select(User).where(User.is_deleted == False)  # noqa: E712
        result2 = await session.execute(stmt2)
        user_list = list(result2.scalars().all())
        user_by_uid = {u.feishu_user_id: u.name for u in user_list if u.feishu_user_id}
        user_by_oid = {u.feishu_open_id: u.name for u in user_list if u.feishu_open_id}

        def _leader_name(leader_id: str | None) -> str:
            if not leader_id:
                return "-"
            return user_by_uid.get(leader_id) or user_by_oid.get(leader_id) or leader_id

        # 构建树
        dept_map = {d.feishu_department_id: d for d in depts}
        children: dict[str, list[Department]] = {}
        roots: list[Department] = []
        for d in depts:
            pid = d.parent_feishu_department_id or ""
            if pid and pid in dept_map:
                children.setdefault(pid, []).append(d)
            else:
                roots.append(d)

        lines = [
            "# 丽珠集团福州福兴医药有限公司 组织架构",
            f"共 {len(depts)} 个部门，{len(user_list)} 人",
            "",
        ]

        def _render(d: Department, indent: int = 0) -> None:
            prefix = "  " * indent
            ln = _leader_name(d.leader_user_id)
            mc = d.member_count or 0
            lines.append(f"{prefix}├─ {d.name}  【{ln}】({mc}人)")
            for child in children.get(d.feishu_department_id, []):
                _render(child, indent + 1)

        for root in sorted(roots, key=lambda d: (d.order or 0, d.name or "")):
            _render(root)

        output = "\n".join(lines)
        out_path.write_text(output, encoding="utf-8")
        logger.info("组织架构图已写入 %s", out_path)
        return output


async def main() -> None:
    output = await generate()
    logger.info(output)


if __name__ == "__main__":
    asyncio.run(main())
