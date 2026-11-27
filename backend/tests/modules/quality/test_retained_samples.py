"""留样台账测试：登记/更新/软删除、到期提醒查询。

注意：db_session 是回滚式夹具（teardown rollback），测试内不 commit。
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as _app_today
from app.modules.quality.repository import (
    create_retained_sample,
    delete_retained_sample,
    get_retained_sample,
    list_retained_samples,
    list_retained_samples_with_names,
    retained_destroy_alerts,
    update_retained_sample,
)


def _due(offset_days: int) -> str:
    return (_app_today() + timedelta(days=offset_days)).isoformat()


def _sample(**kw: Any) -> dict:
    base = {
        "source_type": "product",
        "batch_no": f"HAF{uuid.uuid4().hex[:6].upper()}",
        "sample_name": "盐酸万古霉素原料",
        "qty": "2 瓶",
        "location": "柜 A",
        "retained_at": _app_today().isoformat(),
        "destroy_due_date": _due(365),
    }
    base.update(kw)
    return base


async def test_retained_sample_crud(db_session: AsyncSession) -> None:
    rec = await create_retained_sample(db_session, _sample())
    got = await get_retained_sample(db_session, rec.id)
    assert got is not None and got.batch_no == rec.batch_no
    assert got.status == "active"

    # 更新
    await update_retained_sample(db_session, rec.id, {"location": "柜 B", "qty": "3 瓶"})
    got2 = await get_retained_sample(db_session, rec.id)
    assert got2 is not None and got2.location == "柜 B" and got2.qty == "3 瓶"

    # 列表过滤：批号模糊 / 类型 / 状态
    rows = await list_retained_samples(db_session, batch_no=rec.batch_no[:6])
    assert any(r.id == rec.id for r in rows)
    rows_material = await list_retained_samples(db_session, source_type="material")
    assert all(r.source_type == "material" for r in rows_material)
    rows_destroyed = await list_retained_samples(db_session, status="destroyed")
    assert all(r.status == "destroyed" for r in rows_destroyed)

    # 联姓名列表（销毁人未填时姓名为 None）
    items = await list_retained_samples_with_names(db_session, batch_no=rec.batch_no)
    assert any(i["id"] == rec.id and i["destroyed_by_name"] is None for i in items)

    # 软删除
    assert await delete_retained_sample(db_session, rec.id) is True
    assert await get_retained_sample(db_session, rec.id) is None
    assert await delete_retained_sample(db_session, rec.id) is False


async def test_retained_destroy_alerts(db_session: AsyncSession) -> None:
    # 已过期 / 30 天内到期 / 无到期日 / 已销毁 / 远期：只有前两类提醒
    await create_retained_sample(db_session, _sample(batch_no="EXPIRED01", destroy_due_date=_due(-1)))
    await create_retained_sample(db_session, _sample(batch_no="SOON01", destroy_due_date=_due(10)))
    await create_retained_sample(db_session, _sample(batch_no="NODUE01", destroy_due_date=None))
    await create_retained_sample(db_session, _sample(batch_no="GONE01", destroy_due_date=_due(-5), status="destroyed"))
    await create_retained_sample(db_session, _sample(batch_no="FAR01", destroy_due_date=_due(400)))

    alerts = await retained_destroy_alerts(db_session)
    by_batch = {a["batch_no"]: a for a in alerts}
    assert set(by_batch) == {"EXPIRED01", "SOON01"}
    assert by_batch["EXPIRED01"]["expired"] is True
    assert by_batch["SOON01"]["expired"] is False
    assert by_batch["SOON01"]["location"] == "柜 A"

    # 按到期日升序：过期在前
    assert alerts[0]["destroy_due_date"] <= alerts[1]["destroy_due_date"]
