"""为所有员工根据岗位自动创建培训台账（入职日期之后）"""
import asyncio, sys
sys.path.insert(0, '.')
from app.core.database import async_session_factory
from sqlalchemy import text

async def sync():
    async with async_session_factory() as session:
        # Step 1: 为没有台账页面的员工创建台账页面
        r0 = await session.execute(text('''
            INSERT INTO hr.training_ledger_pages (id, employee_number, employee_name, created_at)
            SELECT gen_random_uuid(), e.employee_number, e.name, now()
            FROM hr.employees e
            WHERE e.is_deleted = false AND e.status != '离职'
            AND NOT EXISTS (
                SELECT 1 FROM hr.training_ledger_pages p
                WHERE p.employee_number = e.employee_number AND p.is_deleted = false
            )
        '''))

        # Step 2: 根据岗位自动创建培训台账记录
        r = await session.execute(text('''
            INSERT INTO hr.training_ledgers (id, employee_number, training_subject, training_method,
                trainer, training_date, created_at)
            SELECT DISTINCT ON (e.employee_number, pt.training_category)
                gen_random_uuid(), e.employee_number, pt.training_category,
                pt.training_method, pt.trainer,
                e.hire_date, now()
            FROM hr.employees e
            JOIN hr.position_trainings pt ON pt.position_name = e.position AND pt.department = e.department
            WHERE e.is_deleted = false AND e.status != '离职'
            AND NOT EXISTS (
                SELECT 1 FROM hr.training_ledgers tl
                WHERE tl.employee_number = e.employee_number
                AND tl.training_subject = pt.training_category
                AND tl.is_deleted = false
            )
        '''))
        await session.commit()
        print(f'Pages created: {r0.rowcount}')
        print(f'Training records created: {r.rowcount}')

        r2 = await session.execute(text('''
            SELECT count(*), count(DISTINCT employee_number)
            FROM hr.training_ledgers WHERE is_deleted = false
        '''))
        total, emps = r2.fetchone()
        print(f'Total: {total} records for {emps} employees')

asyncio.run(sync())

