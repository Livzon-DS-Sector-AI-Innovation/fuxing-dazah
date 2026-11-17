"""五金库物资目录镜像同步器测试（T1，2026-11-17）。

全部 mock 平台 bitable 函数（monkeypatch app.platform.integrations.feishu.
bitable 模块属性——mirror_sync 惰性导入按调用时绑定），不打真飞书。
共享库口径：物料行带 uuid 后缀圈定测试专属，断言只看自己造的行。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.warehouse.hardware import mirror_sync as ms
from app.modules.warehouse.hardware.models import HardwareMaterial

BASE = "basetok_mirror_test"
TABLE = "tbl_mirror_test"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """镜像坐标钉测试值 + 清进程内缓存（record map / dirty 队列）。"""
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "HARDWARE_MIRROR_BASE_TOKEN", BASE, raising=False)
    monkeypatch.setattr(s, "HARDWARE_MIRROR_TABLE_ID", TABLE, raising=False)
    monkeypatch.setattr(s, "WAREHOUSE_FEISHU_APP_ID", "cli_mirror_test", raising=False)
    monkeypatch.setattr(s, "WAREHOUSE_FEISHU_APP_SECRET", "sec", raising=False)
    ms.invalidate_record_map()
    ms.take_dirty_ids()
    yield
    ms.invalidate_record_map()
    ms.take_dirty_ids()


class _FakeBitable:
    """平台 bitable 函数桩：记录调用 + 内存行存储（模拟镜像表）。"""

    def __init__(self, rows: dict[str, dict] | None = None):
        self.rows: dict[str, dict] = rows or {}  # record_id -> fields
        self._seq = 0
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    async def list_all_records(self, base, table, **kw):
        assert (base, table) == (BASE, TABLE)
        return [
            {"record_id": rid, "fields": fields} for rid, fields in self.rows.items()
        ]

    async def batch_create_records(self, base, table, records, **kw):
        ids = []
        for fields in records:
            self._seq += 1
            rid = f"rec{self._seq}"
            self.rows[rid] = dict(fields)
            self.created.append(dict(fields))
            ids.append(rid)
        return ids

    async def update_record(self, base, table, record_id, fields, **kw):
        self.rows[record_id].update(fields)
        self.updated.append((record_id, dict(fields)))
        return None

    async def delete_record(self, base, table, record_id, **kw):
        self.deleted.append(record_id)
        self.rows.pop(record_id, None)
        return None


def _patch(monkeypatch, fake: _FakeBitable) -> None:
    import app.platform.integrations.feishu.bitable as plat_bitable

    for name in (
        "list_all_records", "batch_create_records", "update_record", "delete_record",
    ):
        monkeypatch.setattr(plat_bitable, name, getattr(fake, name))


async def _mk_material(db, *, name="304不锈钢球阀", spec="DN25", unit="个",
                       code=None, active=True):
    m = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec=spec, unit=unit,
        category="金属阀门", managed_class="stocked", safety_stock=Decimal("0"),
        no_expiry=True, code=code, active=active,
    )
    db.add(m)
    await db.flush()
    return m


# ── 纯函数：fields 构造 ──


def test_build_material_fields_shapes():
    class _M:
        id = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
        name = "316L不锈钢法兰片"
        spec = "DN25 PN10"
        unit = "片"
        category = "金属管件"
        code = "3050012345"

    fields = ms.build_material_fields(_M, Decimal("12"), Decimal("2"))
    assert fields[ms.F_PLATFORM_ID] == str(_M.id)
    assert fields[ms.F_NAME] == "316L不锈钢法兰片"
    assert fields[ms.F_ON_HAND] == 12.0 and fields[ms.F_RESERVED] == 2.0
    assert fields[ms.F_AVAILABLE] == 10.0  # 可领量 = 在手 − 预扣
    assert fields[ms.F_CODE] == "3050012345"

    _M.code = None  # 无码物资：编码列不写键（留空语义）
    fields2 = ms.build_material_fields(_M, Decimal("0"), Decimal("0"))
    assert ms.F_CODE not in fields2
    assert fields2[ms.F_SPEC] == "DN25 PN10"


def test_build_stock_fields_negative_available():
    fields = ms.build_stock_fields(Decimal("3"), Decimal("5"))
    assert fields[ms.F_AVAILABLE] == -2.0  # 超卖校验前预扣可大于在手，原样透出


# ── 单行 upsert / 三值刷新 ──


async def test_sync_material_creates_then_updates(db_session, monkeypatch):
    fake = _FakeBitable()
    _patch(monkeypatch, fake)
    m = await _mk_material(db_session)

    rid = await ms.sync_material(db_session, m.id)
    assert rid and len(fake.created) == 1
    assert fake.created[0][ms.F_PLATFORM_ID] == str(m.id)
    assert fake.created[0][ms.F_NAME] == m.name

    m.unit = "片"  # 平台改动 → 再同步走更新（锚点命中缓存）
    await db_session.flush()
    rid2 = await ms.sync_material(db_session, m.id)
    assert rid2 == rid and not fake.created[1:]
    assert fake.updated and fake.updated[-1][1][ms.F_UNIT] == "片"


async def test_refresh_stock_values_only_touches_dirty(db_session, monkeypatch):
    fake = _FakeBitable({f"rec9": {ms.F_PLATFORM_ID: "pid-ghost"}})
    _patch(monkeypatch, fake)
    m = await _mk_material(db_session, name="镜试物料A")
    # 预置映射缓存：平台 id → rec9 之外的独立行
    fake.rows["rec1"] = {ms.F_PLATFORM_ID: str(m.id), ms.F_ON_HAND: 0}
    ms._record_map = {str(m.id): "rec1", "pid-ghost": "rec9"}

    touched = await ms.refresh_stock_values(db_session, [str(m.id), "pid-ghost"])
    assert touched == 1  # ghost 不在平台三值结果里，跳过
    assert fake.updated and fake.updated[0][0] == "rec1"
    assert set(fake.updated[0][1]) == {ms.F_ON_HAND, ms.F_RESERVED, ms.F_AVAILABLE}


def test_mark_and_take_dirty_ids():
    a, b = uuid4(), uuid4()
    ms.mark_stock_dirty(a, str(b), a)  # UUID/str 双形态 + 去重
    assert ms.take_dirty_ids() == {str(a), str(b)}
    assert ms.take_dirty_ids() == set()  # 取走即清空


# ── 全量对账 ──


class _SynthMaterial:
    """合成平台行（reconcile 测试经 _platform_rows 注入，圈定专属行集）。"""

    def __init__(self, name, spec="DN25", unit="个", code=None):
        self.id = uuid4()
        self.name = name
        self.spec = spec
        self.unit = unit
        self.category = "金属阀门"
        self.code = code


async def test_reconcile_creates_updates_deletes(db_session, monkeypatch):
    keep = _SynthMaterial("镜试对账留", code="3050099001")
    fake = _FakeBitable({
        "recGone": {ms.F_PLATFORM_ID: str(uuid4()), ms.F_NAME: "已删行"},
        "recOrphan": {ms.F_PLATFORM_ID: "orphan-pid", ms.F_NAME: "平台不存在的行"},
    })
    _patch(monkeypatch, fake)

    async def _rows(db):
        return [keep]

    monkeypatch.setattr(ms, "_platform_rows", _rows)
    stats = await ms.reconcile_mirror(db_session)
    assert stats == {
        "created": 1, "updated": 0, "deleted": 2, "platform": 1, "mirror": 2,
    }
    assert fake.created[0][ms.F_PLATFORM_ID] == str(keep.id)
    assert fake.created[0][ms.F_CODE] == "3050099001"
    assert set(fake.deleted) == {"recGone", "recOrphan"}
    assert ms._record_map is None  # 对账后缓存已失效


async def test_reconcile_updates_drifted_row(db_session, monkeypatch):
    m = _SynthMaterial("镜试漂移行", unit="个", code="3050012399")
    fake = _FakeBitable({
        "recD": {
            ms.F_PLATFORM_ID: str(m.id), ms.F_NAME: m.name + "（旧名）",
            ms.F_UNIT: "个", ms.F_ON_HAND: 99.0, ms.F_AVAILABLE: 99.0,
            ms.F_RESERVED: 0,
        },
    })
    _patch(monkeypatch, fake)

    async def _rows(db):
        return [m]

    monkeypatch.setattr(ms, "_platform_rows", _rows)
    stats = await ms.reconcile_mirror(db_session)
    assert stats["created"] == 0 and stats["updated"] == 1 and stats["deleted"] == 0
    assert fake.rows["recD"][ms.F_NAME] == m.name
    assert fake.rows["recD"][ms.F_CODE] == "3050012399"
    assert fake.rows["recD"][ms.F_ON_HAND] == 0.0  # 三值漂移归零修正（DB 无该行=0）


async def test_reconcile_idles_without_target(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "HARDWARE_MIRROR_BASE_TOKEN", "", raising=False)
    fake = _FakeBitable()
    _patch(monkeypatch, fake)
    stats = await ms.reconcile_mirror(None)  # type: ignore[arg-type]
    assert stats == {"created": 0, "updated": 0, "deleted": 0, "platform": 0, "mirror": 0}
    assert not fake.created and not fake.deleted


# ── 定时任务注册 ──


def test_mirror_reconcile_task_registered():
    from app.platform.scheduler.registry import SchedulerRegistry

    from app.modules.warehouse.hardware.scheduled import register_hardware_tasks

    registry = SchedulerRegistry()
    register_hardware_tasks(registry)
    names = set(registry.tasks.keys())
    assert "warehouse.hardware_mirror_reconcile" in names
