import asyncio, sys
sys.path.insert(0, '.')
from app.core.database import async_session_factory
from sqlalchemy import text

async def fix():
    async with async_session_factory() as session:
        r = await session.execute(text('''
            UPDATE hr.annual_training_plan_items
            SET tracking_status = '完成'
            WHERE is_deleted = false
            AND (tracking_status IS NULL OR tracking_status = '')
            AND month IS NOT NULL
            AND (month LIKE '%1月%' OR month LIKE '%2月%' OR month LIKE '%3月%'
                 OR month LIKE '%4月%' OR month LIKE '%5月%' OR month LIKE '%6月%')
        '''))
        await session.commit()
        print(f'Updated {r.rowcount} items to 完成')

asyncio.run(fix())
