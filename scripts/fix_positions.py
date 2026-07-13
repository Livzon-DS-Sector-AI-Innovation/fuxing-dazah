#!/usr/bin/env python3
import asyncio, sys
sys.path.insert(0, '.')
from app.core.database import async_session_factory
from sqlalchemy import text

async def fix():
    async with async_session_factory() as session:
        r = await session.execute(text('''
            UPDATE hr.employees SET position = substring(position, length(department) + 1)
            WHERE is_deleted = false AND department IS NOT NULL AND department != ''
            AND position LIKE department || '%' AND position != department
        '''))
        await session.commit()
        print(f'Updated {r.rowcount} employees')
        r2 = await session.execute(text('SELECT name, department, position FROM hr.employees LIMIT 5'))
        for row in r2:
            print(f'  [{row[1]}] {row[0]} -> {row[2]}')

if __name__ == '__main__':
    asyncio.run(fix())
