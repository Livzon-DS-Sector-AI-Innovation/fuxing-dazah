"""SOP 目录列表：分页不重不漏。

目录按「培训类别、文件名称」排序，而这两列大量并列（同一份「岗位职责」配给上百个岗位）。
只按这两列排序时并列行没有确定先后，执行计划稍有不同（并行度、是否走索引）两次查询的
输出顺序就不一样，OFFSET 翻页会整段漏掉或重复——目录页因此少显示过约 3% 的条目。
排序必须落到唯一键上。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SopCatalog


@pytest.mark.asyncio
async def test_pages_follow_a_total_order(client, db_session: AsyncSession):
    """450 条类别、文件名称完全相同的条目，按岗位名倒序插入（物理顺序与排序结果相反）。
    分 3 页取回的序列必须恰好是「部门 → 岗位 → id」升序：并列行有了确定的先后，
    翻页才不会随执行计划变化而漏行、重行。"""
    department = f"分页测试{uuid.uuid4().hex[:8]}"
    # 倒序插入：排序要是没落到唯一键上，取回的就还是插入顺序（或引擎随意的顺序）
    db_session.add_all([
        SopCatalog(
            file_name="岗位职责",
            category="岗位职责",
            department=department,
            position_name=f"岗位{i % 37:02d}",
            sop_number=f"T-{i:04d}",
        )
        for i in reversed(range(450))
    ])
    await db_session.flush()

    rows: list[dict] = []
    for page in (1, 2, 3):
        res = await client.get(
            "/api/v1/hr/sop-catalog",
            params={"department": department, "page": page, "page_size": 200},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["meta"]["total"] == 450
        rows += body["data"]

    keys = [(row["department"], row["position_name"], row["id"]) for row in rows]
    assert len(keys) == 450, f"翻页取回 {len(keys)} 条，应为 450 条"
    assert len({key[2] for key in keys}) == 450, "并列行在页边界上重复了"
    assert keys == sorted(keys), "并列行的先后没有落到唯一键上：分页序列不是全序"
