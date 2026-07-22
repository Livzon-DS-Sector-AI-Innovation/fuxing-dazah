import asyncio, sys
sys.path.insert(0, '.')
from app.core.database import async_session_factory
from sqlalchemy import text

async def fix():
    async with async_session_factory() as session:
        # 先回退12月、7月等被误标的
        r1 = await session.execute(text('''
            UPDATE hr.annual_training_plan_items
            SET tracking_status = NULL
            WHERE is_deleted = false
            AND month IS NOT NULL
            AND (month ~ '1[0-2]月' OR month ~ '[7-9]月')
        '''))

        # 正确标注1-6月（用正则精确匹配，排除12月）
        r2 = await session.execute(text('''
            UPDATE hr.annual_training_plan_items
            SET tracking_status = '完成'
            WHERE is_deleted = false
            AND month IS NOT NULL
            AND month ~ '^[1-6]月' AND month !~ '1[0-2]'
        '''))
        await session.commit()
        print(f'Reverted: {r1.rowcount}, Set complete: {r2.rowcount}')

asyncio.run(fix())
