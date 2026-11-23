"""五金库月度用量管控表回填测试（2026-11-18）。

全部 mock 平台 bitable 函数（monkeypatch app.platform.integrations.fishu.
bitable 模块属性——usage_control 惰性导入按调用时绑定），不打真飞书。
Fake 按表分派：物资目录表（镜像映射源）/ 用量管控表（同步目标）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.modules.warehouse.hardware import usage_control as uc
from app.modules.warehouse.hardware.models import HardwareMaterial, HardwareMovement

BASE = "basetok_usage_test"
CATALOG_TABLE = "tbl_catalog_test"
USAGE_TABLE = "tbl_usage_test"
CN_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """坐标钉测试值 + 清镜像映射缓存（用量表与镜像共用 record map 缓存）。"""
    from app.core.config import get_settings
    from app.modules.warehouse.hardware import mirror_sync as ms

    s = get_settings()
    monkeypatch.setattr(s, "HARDWARE_MIRROR_BASE_TOKEN", BASE, raising=False)
    monkeypatch.setattr(s, "HARDWARE_MIRROR_TABLE_ID", CATALOG_TABLE, raising=False)
    monkeypatch.setattr(s, "HARDWARE_USAGE_TABLE_ID", USAGE_TABLE, raising=False)
    monkeypatch.setattr(s, "WAREHOUSE_FEISHU_APP_ID", "cli_usage_test", raising=False)
    monkeypatch.setattr(s, "WAREHOUSE_FEISHU_APP_SECRET", "sec", raising=False)
    ms.invalidate_record_map()
    yield
    ms.invalidate_record_map()


class _FakeBitable:
    """平台 bitable 函数桩：按 table 分派内存行（目录表/用量表两坐标）。"""

    def __init__(self):
        self.catalog: dict[str, dict] = {}   # record_id -> fields（目录镜像）
        self.rows: dict[str, dict] = {}      # record_id -> fields（用量管控）
        self._seq = 0
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    async def list_all_records(self, base, table, **kw):
        assert base == BASE
        src = self.catalog if table == CATALOG_TABLE else self.rows
        assert table in (CATALOG_TABLE, USAGE_TABLE)
        return [{"record_id": rid, "fields": f} for rid, f in src.items()]

    async def list_fields(self, base, table, **kw):
        assert (base, table) == (BASE, USAGE_TABLE)
        return [{"field_id": "fldMonth", "field_name": uc.F_MONTH, "type": 3,
                 "property": {"options": [
                     {"name": m} for m in ("2026-09", "2026-10", "2026-11",
                                           "2026-12", "2027-01")]} }]

    async def batch_create_records(self, base, table, records, **kw):
        assert (base, table) == (BASE, USAGE_TABLE)
        ids = []
        for fields in records:
            self._seq += 1
            rid = f"rec{self._seq}"
            self.rows[rid] = dict(fields)
            self.created.append(dict(fields))
            ids.append(rid)
        return ids

    async def update_record(self, base, table, record_id, fields, **kw):
        assert (base, table) == (BASE, USAGE_TABLE)
        self.rows[record_id].update(fields)
        self.updated.append((record_id, dict(fields)))
        return None


def _patch(monkeypatch, fake: _FakeBitable) -> None:
    import app.platform.integrations.feishu.bitable as plat_bitable

    for name in ("list_all_records", "list_fields",
                 "batch_create_records", "update_record"):
        monkeypatch.setattr(plat_bitable, name, getattr(fake, name))


class _SynthMaterial:
    """纯函数测试用轻量物资（不落库）。"""

    def __init__(self, mid, name, *, spec="", unit="个", category="金属阀门",
                 active=True, demands=None):
        self.id = mid
        self.name = name
        self.spec = spec
        self.unit = unit
        self.category = category
        self.active = active
        self.monthly_demands = demands


# ── 纯函数：月份序列 / 部门归一 / 行构造 ──


def test_month_starts_rollover():
    now = datetime(2027, 1, 5, 10, 0, tzinfo=CN_TZ)
    starts = uc.month_starts(now, 1)
    assert [uc.month_key(s) for s in starts] == ["2026-12", "2027-01"]


def test_normalize_dept_buckets():
    assert uc.normalize_dept("发酵") == "发酵"
    assert uc.normalize_dept("发酵车间") == "发酵"
    assert uc.normalize_dept("动力") == "动力机修"  # 反向包含兜底
    assert uc.normalize_dept("办公室") == uc.OTHER_DEPT
    assert uc.normalize_dept("") == uc.OTHER_DEPT
    assert uc.normalize_dept(None) == uc.OTHER_DEPT


def test_build_usage_rows_active_union():
    m1 = _SynthMaterial("m-1", "球阀", demands={"发酵": 10, "提炼一期": 0})
    m2 = _SynthMaterial("m-2", "垫片", demands=None)
    m3 = _SynthMaterial("m-3", "旧阀", active=False, demands={"发酵": 5})
    usage = {("m-1", "发酵"): 12.0, ("m-2", uc.OTHER_DEPT): 3.0}
    rows = uc.build_usage_rows(
        [m1, m2, m3], usage, datetime(2026, 11, 1, tzinfo=CN_TZ),
        {"m-1": "recCat1"},
    )
    by_anchor = {(r[uc.F_PLATFORM_ID], r[uc.F_DEPT]): r for r in rows}
    # 基线0且无用量（m-1×提炼一期）不成行；停用纯基线（m-3）不成行
    assert set(by_anchor) == {("m-1", "发酵"), ("m-2", uc.OTHER_DEPT)}
    r1 = by_anchor[("m-1", "发酵")]
    assert r1[uc.F_MONTH] == "2026-11"
    assert r1[uc.F_DEMAND] == 10.0 and r1[uc.F_ACTUAL] == 12.0
    assert r1[uc.F_LINK] == ["recCat1"]
    assert r1[uc.F_CATEGORY] == "金属阀门"
    r2 = by_anchor[("m-2", uc.OTHER_DEPT)]
    assert r2[uc.F_DEMAND] == 0.0 and r2[uc.F_ACTUAL] == 3.0
    assert uc.F_LINK not in r2  # 未映射不写键
    # 人工列/公式列永不写
    for r in rows:
        assert "处置状态" not in r and "比对结论" not in r


def test_build_usage_rows_material_missing_snapshot_blank():
    """用量指向已删物资（materials 缺位）：快照列留空、数值照常。"""
    rows = uc.build_usage_rows(
        [], {("m-x", "发酵"): 2.0}, datetime(2026, 11, 1, tzinfo=CN_TZ), {},
    )
    assert rows[0][uc.F_NAME] == "" and rows[0][uc.F_ACTUAL] == 2.0


# ── 聚合查询（真库回滚口径）──


async def _mk_material(db, *, demands=None, active=True):
    m = HardwareMaterial(
        name=f"用量物资·{uuid4().hex[:6].upper()}", spec="DN25", unit="个",
        category="金属阀门", managed_class="stocked", safety_stock=Decimal("0"),
        no_expiry=True, monthly_demands=demands, active=active,
    )
    db.add(m)
    await db.flush()
    return m


async def _mk_movement(db, material, *, biz="req_issue", dept="发酵",
                        qty=1, at=None, deleted=False):
    mv = HardwareMovement(
        movement_no=f"MV{uuid4().hex[:10].upper()}",
        direction="return_in" == biz and "inbound" or (
            "outbound" if biz in ("req_issue", "urgent_issue") else "adjust"),
        business_type=biz,
        material_id=material.id,
        material_name=material.name,
        quantity=Decimal(str(qty)),
        occurred_at=at or datetime(2026, 11, 5, 10, 0, tzinfo=CN_TZ),
        dept_name=dept,
        is_deleted=deleted,
    )
    db.add(mv)
    await db.flush()
    return mv


async def test_aggregate_monthly_usage(db_session):
    m = await _mk_material(db_session, demands={"发酵": 10})
    month = datetime(2026, 11, 1, tzinfo=CN_TZ)
    await _mk_movement(db_session, m, dept="发酵车间", qty=4)
    await _mk_movement(db_session, m, dept="发酵", qty=3)
    await _mk_movement(db_session, m, biz="urgent_issue", dept="办公室", qty=2)
    await _mk_movement(db_session, m, biz="return_in", dept="发酵", qty=5)  # 不冲减
    await _mk_movement(db_session, m, dept="发酵", qty=7,
                       at=datetime(2026, 12, 1, 9, 0, tzinfo=CN_TZ))  # 次月出窗
    await _mk_movement(db_session, m, dept="发酵", qty=9, deleted=True)

    usage = await uc.aggregate_monthly_usage(db_session, month)
    # 共享开发库有真实领用流水，断言圈定本测试物资（镜像测试同口径）
    mine = {k: v for k, v in usage.items() if k[0] == str(m.id)}
    assert mine == {(str(m.id), "发酵"): 7.0, (str(m.id), uc.OTHER_DEPT): 2.0}


def test_link_ids_real_read_shape():
    """真机读回形态（2026-11-18 实测）：分段 dict 包复数 record_ids。"""
    real = [{"record_ids": ["recX"], "table_id": "tblCat", "text": "ABS三通"}]
    assert uc._link_ids(real) == ["recX"]
    assert uc._link_ids({"link_record_ids": ["recY"]}) == ["recY"]
    assert uc._link_ids(["recZ"]) == ["recZ"]
    assert uc._link_ids(None) == []


# ── 同步主流程（fake 双表）──


def _scope_seams(monkeypatch, m, usage_by_run: list[dict]):
    """把聚合/物资加载钉到测试数据（共享开发库有真实物资与流水）。"""
    calls = {"i": 0}

    async def _agg(db, month_start):
        idx = min(calls["i"], len(usage_by_run) - 1)
        return dict(usage_by_run[idx])

    async def _agg_counting(db, month_start):
        result = await _agg(db, month_start)
        calls["i"] += 1
        return result

    async def _load(db, involved):
        return [m]

    monkeypatch.setattr(uc, "aggregate_monthly_usage", _agg_counting)
    monkeypatch.setattr(uc, "_load_materials", _load)


async def test_sync_usage_rows_upsert_flow(db_session, monkeypatch):
    fake = _FakeBitable()
    m = await _mk_material(db_session, demands={"发酵": 10})
    fake.catalog["recCat1"] = {"平台ID": str(m.id), "物资名称": m.name}
    _patch(monkeypatch, fake)
    now = datetime(2026, 11, 18, 8, 0, tzinfo=CN_TZ)

    # 三跑用量：12 → 12 → 17（第三跑前涨量）
    _scope_seams(monkeypatch, m, [{(str(m.id), "发酵"): 12.0}] * 2
                 + [{(str(m.id), "发酵"): 17.0}])

    # 首跑：建 1 行（含关联物资映射）
    stats = await uc.sync_usage_rows(db_session, months_back=0, now=now)
    assert stats["enabled"] is True and stats["created"] == 1
    row = fake.created[0]
    assert row[uc.F_PLATFORM_ID] == str(m.id)
    assert row[uc.F_MONTH] == "2026-11" and row[uc.F_DEPT] == "发酵"
    assert row[uc.F_DEMAND] == 10.0 and row[uc.F_ACTUAL] == 12.0
    assert row[uc.F_LINK] == ["recCat1"]
    # 人工列预置后不被同步触碰
    fake.rows["rec1"]["处置状态"] = "已关注"
    fake.rows["rec1"]["备注"] = "人工备注"

    # 二跑无漂移：零写
    stats2 = await uc.sync_usage_rows(db_session, months_back=0, now=now)
    assert stats2["created"] == 0 and stats2["updated"] == 0
    assert fake.updated == []
    assert fake.rows["rec1"]["处置状态"] == "已关注"

    # 用量上涨：只改数值列，人工列原样
    stats3 = await uc.sync_usage_rows(db_session, months_back=0, now=now)
    assert stats3["updated"] == 1 and stats3["created"] == 0
    assert fake.updated[0][1][uc.F_ACTUAL] == 17.0
    assert "处置状态" not in fake.updated[0][1]
    assert fake.rows["rec1"]["备注"] == "人工备注"


async def test_sync_usage_rows_month_options_pending(monkeypatch, db_session):
    """统计月份选项缺失时补选项（缺 → 走 _request PUT 一次）。"""
    fake = _FakeBitable()
    _patch(monkeypatch, fake)
    puts: list[str] = []

    async def _fake_request(method, url, **kw):
        puts.append(f"{method} {url[-20:]}")

    import app.platform.integrations.feishu.bitable as plat_bitable
    monkeypatch.setattr(plat_bitable, "_request", _fake_request)
    monkeypatch.setattr(plat_bitable, "BITABLE_BASE", "https://example.invalid")

    async def _empty_agg(db, month_start):
        return {}

    async def _empty_load(db, involved):
        return []

    monkeypatch.setattr(uc, "aggregate_monthly_usage", _empty_agg)
    monkeypatch.setattr(uc, "_load_materials", _empty_load)

    # now=2027-03 → 月份 "2027-03" 不在 fake 选项里 → 补选项 PUT 一次；无行可写
    stats = await uc.sync_usage_rows(db_session, months_back=0,
                                     now=datetime(2027, 3, 10, tzinfo=CN_TZ))
    assert len(puts) == 1 and puts[0].startswith("PUT")
    assert stats["created"] == 0 and stats["updated"] == 0


async def test_sync_usage_rows_unconfigured(db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "HARDWARE_USAGE_TABLE_ID", "", raising=False)
    fake = _FakeBitable()
    _patch(monkeypatch, fake)
    stats = await uc.sync_usage_rows(db_session, months_back=1)
    assert stats == {"enabled": False}
    assert fake.created == [] and fake.updated == []


def test_usage_sync_task_registered():
    from app.platform.scheduler.registry import SchedulerRegistry

    from app.modules.warehouse.hardware.scheduled import register_hardware_tasks

    registry = SchedulerRegistry()
    register_hardware_tasks(registry)
    assert "warehouse.hardware_usage_sync" in set(registry.tasks.keys())
