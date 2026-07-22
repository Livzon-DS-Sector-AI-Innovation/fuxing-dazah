"""
一次性数据修正脚本：将离职台账中已有员工的 status 标记为「离职」。

用法（在服务器上执行）：
    python scripts/fix_departed_employee_status.py
    或
    uv run python scripts/fix_departed_employee_status.py
"""
import asyncio
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app.core.config import settings
    from app.modules.hr.models import Employee, DepartureRecord

    engine = create_async_engine(settings.DATABASE_URL)

    async with AsyncSession(engine) as session:
        # 查询所有未删除的离职记录中的 (name, department) 组合
        dep_result = await session.execute(
            select(DepartureRecord.name, DepartureRecord.department)
            .where(DepartureRecord.is_deleted == False)
            .distinct()
        )
        departed_pairs = set(dep_result.all())
        print(f"离职台账中共有 {len(departed_pairs)} 个不重复的 (姓名, 部门) 组合")

        if not departed_pairs:
            print("没有需要修正的数据")
            return

        count = 0
        for name, department in departed_pairs:
            result = await session.execute(
                update(Employee)
                .where(
                    Employee.name == name,
                    Employee.department == department,
                    Employee.is_deleted == False,
                    Employee.status != "离职",
                )
                .values(status="离职")
            )
            count += result.rowcount

        await session.commit()
        print(f"已修正 {count} 名员工的状态为「离职」")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
