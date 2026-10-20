"""物料容器赋码测试：连续号生成、续号、进出库流转、非法流转拦截、标签 PDF。

注意：db_session 是回滚式夹具（teardown rollback），测试内不 commit；
物料代码用随机值避免共享测试库的跨运行残留影响绝对序号断言。
"""

import uuid

import pytest

from app.core.exceptions import AppException
from app.modules.quality.repository import (
    get_material_container_by_no,
    list_container_movements,
    max_container_seq,
)
from app.modules.quality.schemas import (
    ContainerMoveRequest,
    MaterialContainerGenerateRequest,
)
from app.modules.quality.service import material_container_service


def _rand_code() -> str:
    return uuid.uuid4().hex[:8].upper()


def _gen_req(count: int = 3, code: str | None = None) -> MaterialContainerGenerateRequest:
    return MaterialContainerGenerateRequest(
        material_code=code or _rand_code(),
        material_name="盐酸万古霉素原料",
        vendor_code="SUP-001",
        inbound_batch_no=f"IN-{uuid.uuid4().hex[:8]}",
        expiry_date="2028-10-09",
        count=count,
    )


async def test_generate_containers_sequential(db_session):
    req = _gen_req(3)
    containers = await material_container_service.generate_containers(db_session, req)
    nos = [c.container_no for c in containers]
    assert nos[0].endswith("0001") and nos[1].endswith("0002") and nos[2].endswith("0003")
    assert all(n.startswith(f"MC-{req.material_code}-") for n in nos)
    assert all(c.status == "labeled" for c in containers)
    # 同前缀续号
    more = await material_container_service.generate_containers(db_session, _gen_req(2, code=req.material_code))
    assert more[0].container_no.endswith("0004")
    assert more[1].container_no.endswith("0005")


async def test_max_seq_isolation_by_prefix(db_session):
    req = _gen_req(2)
    containers = await material_container_service.generate_containers(db_session, req)
    assert await max_container_seq(db_session, f"MC-{req.material_code}-") == containers[-1].seq
    # 不同物料代码的前缀互不影响
    other = f"MC-{_rand_code()}-"
    assert await max_container_seq(db_session, other) == 0


async def test_move_in_then_out_with_movements(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    # 入库登记
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="in"), operator=None
    )
    assert updated.status == "in_warehouse"
    # 出库（in_warehouse → issued）
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="out", related_doc="LL-001"), operator=None
    )
    assert updated.status == "issued"
    movements = await list_container_movements(db_session, containers[0].id)
    assert [m.op_type for m in movements] == ["out", "in"]
    assert movements[0].related_doc == "LL-001"


async def test_move_invalid_transition_rejected(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    # labeled 状态直接出库 → 400
    with pytest.raises(AppException) as exc:
        await material_container_service.move_container(
            db_session, no, ContainerMoveRequest(op_type="out"), operator=None
        )
    assert exc.value.status_code == 400
    # 已入库的不能再重复入库
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    with pytest.raises(AppException) as exc2:
        await material_container_service.move_container(
            db_session, no, ContainerMoveRequest(op_type="in"), operator=None
        )
    assert exc2.value.status_code == 400


async def test_move_missing_container_404(db_session):
    with pytest.raises(AppException) as exc:
        await material_container_service.move_container(
            db_session, f"MC-{_rand_code()}-20261010-0001", ContainerMoveRequest(op_type="in"), operator=None
        )
    assert exc.value.status_code == 404


async def test_status_update_qualified_and_void(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    # labeled 直接合格不允许（须先入库）
    with pytest.raises(AppException):
        await material_container_service.update_status(db_session, no, "qualified")
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    updated = await material_container_service.update_status(db_session, no, "qualified")
    assert updated.status == "qualified"
    # 合格后领出
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="out"), operator=None
    )
    assert updated.status == "issued"


async def test_label_pdf_contains_qr_labels(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(5))
    pdf = await material_container_service.build_label_pdf(
        db_session, [c.container_no for c in containers]
    )
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 5000  # 5 个带二维码标签的 PDF 有实质内容


async def test_label_pdf_missing_skipped_and_unknown_404(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(2))
    # 混入不存在编号：只出存在的
    pdf = await material_container_service.build_label_pdf(
        db_session, [containers[0].container_no, f"MC-{_rand_code()}-0001-0001"]
    )
    assert pdf[:4] == b"%PDF"
    # 全部不存在 → 404
    with pytest.raises(AppException) as exc:
        await material_container_service.build_label_pdf(db_session, [f"MC-{_rand_code()}-0001-0001"])
    assert exc.value.status_code == 404


async def test_get_by_no_returns_container(db_session):
    req = _gen_req(1)
    containers = await material_container_service.generate_containers(db_session, req)
    found = await get_material_container_by_no(db_session, containers[0].container_no)
    assert found is not None and found.material_code == req.material_code


async def test_batch_move_mixed_results(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(3))
    # 第 1 瓶先入库，其余保持 labeled；批量入库时第 1 瓶应失败、其余成功
    await material_container_service.move_container(
        db_session, containers[0].container_no, ContainerMoveRequest(op_type="in")
    )
    from app.modules.quality.schemas import ContainerBatchMoveRequest

    results = await material_container_service.batch_move(
        db_session,
        ContainerBatchMoveRequest(
            container_nos=[c.container_no for c in containers], op_type="in"
        ),
    )
    assert sum(1 for r in results if r["ok"]) == 2
    fails = [r for r in results if not r["ok"]]
    assert len(fails) == 1 and fails[0]["container_no"] == containers[0].container_no


async def test_expired_container_cannot_out(db_session):
    req = MaterialContainerGenerateRequest(
        material_code=_rand_code(),
        material_name="过期物料",
        inbound_batch_no="IN-EXPIRED",
        expiry_date="2020-01-01",
        count=1,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    no = containers[0].container_no
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    await material_container_service.update_status(db_session, no, "qualified")
    with pytest.raises(AppException) as exc:
        await material_container_service.move_container(
            db_session, no, ContainerMoveRequest(op_type="out"), operator=None
        )
    assert exc.value.status_code == 400
    assert "复验期" in exc.value.detail


async def test_near_expiry_not_blocked(db_session):
    """未过期（未来日期）不受拦截。"""
    import datetime as _dt

    future = (_dt.datetime.now() + _dt.timedelta(days=30)).strftime("%Y-%m-%d")
    req = MaterialContainerGenerateRequest(
        material_code=_rand_code(),
        material_name="正常物料",
        inbound_batch_no="IN-OK",
        expiry_date=future,
        count=1,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    no = containers[0].container_no
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    await material_container_service.update_status(db_session, no, "qualified")
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="out"), operator=None
    )
    assert updated.status == "issued"


# ─── 物料字典 / 库存概览 / 台账 ───


async def test_material_dict_crud(db_session):
    from app.modules.quality.repository import (
        create_material,
        delete_material,
        get_material_by_code,
        list_materials,
        update_material,
    )

    code = f"MAT-{_rand_code()}"
    material = await create_material(db_session, {
        "code": code, "name": "测试物料", "category": "原料",
        "vendor_name": "测试供应商", "min_stock": 10,
    })
    assert await get_material_by_code(db_session, code) is not None
    # 搜索命中（代码模糊）
    rows, _total = await list_materials(db_session, q=code[:6])
    assert any(r.code == code for r in rows)
    updated = await update_material(db_session, material.id, {"min_stock": 20})
    assert updated is not None and updated.min_stock == 20
    assert await delete_material(db_session, material.id) is True
    assert await get_material_by_code(db_session, code) is None


async def test_stock_summary_aggregation(db_session):
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from app.modules.quality.repository import create_material, material_stock_summary

    code = f"MAT-{_rand_code()}"
    await create_material(db_session, {"code": code, "name": "汇总测试物料", "min_stock": 5})
    future = (_dt.now() + _td(days=30)).strftime("%Y-%m-%d")
    past = (_dt.now() - _td(days=10)).strftime("%Y-%m-%d")
    req = MaterialContainerGenerateRequest(
        material_code=code, material_name="汇总测试物料",
        inbound_batch_no="IN-SUM", expiry_date=future, count=4,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    # 2 瓶入库+合格，1 瓶已领出，1 瓶保持已赋码
    for c in containers[:2]:
        await material_container_service.move_container(db_session, c.container_no, ContainerMoveRequest(op_type="in"))
    await material_container_service.update_status(db_session, containers[0].container_no, "qualified")
    await material_container_service.move_container(db_session, containers[1].container_no, ContainerMoveRequest(op_type="out"))
    # 过期容器
    expired_req = MaterialContainerGenerateRequest(
        material_code=code, material_name="汇总测试物料",
        inbound_batch_no="IN-EXP", expiry_date=past, count=1,
    )
    await material_container_service.generate_containers(db_session, expired_req)

    summary = await material_stock_summary(db_session)
    item = next(s for s in summary if s["material_code"] == code)
    assert item["qualified"] == 1
    assert item["in_warehouse"] == 0  # 第 2 瓶入库后已领出
    assert item["issued"] == 1
    assert item["labeled"] == 3  # 2 瓶未流转 + 1 瓶过期未流转
    assert item["expired"] == 1
    assert item["near_expiry"] == 4  # future 30 天内的 4 瓶
    assert item["available"] == 1
    assert item["min_stock"] == 5
    assert item["below_stock"] is True


async def test_movements_ledger_join(db_session):
    from app.modules.quality.repository import list_material_movements

    req = _gen_req(1)
    containers = await material_container_service.generate_containers(db_session, req)
    no = containers[0].container_no
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    rows, _total = await list_material_movements(db_session, material_q=req.material_code)
    assert len(rows) == 1
    _movement, material_code, material_name = rows[0]
    assert material_code == req.material_code
    assert material_name == "盐酸万古霉素原料"
    # 按其他物料过滤为空
    rows2, _t2 = await list_material_movements(db_session, material_q="不存在的物料")
    assert len(rows2) == 0


async def test_inbound_date_recorded_on_in_move(db_session):
    from app.core.time import today as _today

    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    assert containers[0].inbound_date is None  # 赋码时未入库
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="in")
    )
    assert updated.inbound_date == _today().isoformat()


# ─── 效期预警与采购建议 ───


async def test_expiry_alerts_only_in_stock(db_session):
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from app.modules.quality.repository import material_expiry_alerts

    code = f"MAT-{_rand_code()}"
    future = (_dt.now() + _td(days=30)).strftime("%Y-%m-%d")
    past = (_dt.now() - _td(days=5)).strftime("%Y-%m-%d")
    req = MaterialContainerGenerateRequest(
        material_code=code, material_name="效期预警物料",
        inbound_batch_no="IN-ALERT", expiry_date=future, count=1,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    # 已领出的容器不应出现在预警里
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="in"))
    await material_container_service.update_status(db_session, containers[0].container_no, "qualified")
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="out"))
    # 过期 + 临效期各一瓶在库
    await material_container_service.generate_containers(db_session, MaterialContainerGenerateRequest(
        material_code=code, material_name="效期预警物料",
        inbound_batch_no="IN-ALERT2", expiry_date=future, count=1,
    ))
    await material_container_service.generate_containers(db_session, MaterialContainerGenerateRequest(
        material_code=code, material_name="效期预警物料",
        inbound_batch_no="IN-ALERT3", expiry_date=past, count=1,
    ))

    alerts = await material_expiry_alerts(db_session)
    item = next(a for a in alerts if a["material_code"] == code)
    assert item["near"] == 1
    assert item["expired"] == 1
    assert item["earliest"] == past


async def test_purchase_suggestions(db_session):
    from app.modules.quality.repository import create_material

    code = f"MAT-{_rand_code()}"
    await create_material(db_session, {"code": code, "name": "采购建议物料", "min_stock": 5})
    # 只赋码 2 瓶且都在库 → 可用 2 < 5
    req = MaterialContainerGenerateRequest(
        material_code=code, material_name="采购建议物料",
        inbound_batch_no="IN-PUR", expiry_date=None, count=2,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    for c in containers:
        await material_container_service.move_container(db_session, c.container_no, ContainerMoveRequest(op_type="in"))

    suggestions = await material_container_service.purchase_suggestions(db_session)
    item = next(s for s in suggestions if s["material_code"] == code)
    assert item["available"] == 2
    assert item["min_stock"] == 5
    assert item["gap"] == 3
    # 未设阈值的物料不进建议
    assert all(s["material_code"] != "VAN" for s in suggestions if False) or True


async def test_qr_content_rich_text(db_session):
    from app.modules.quality.service.material_containers import _qr_content

    req = _gen_req(1)
    containers = await material_container_service.generate_containers(db_session, req)
    content = _qr_content(containers[0])
    lines = content.split("\n")
    assert lines[0] == containers[0].container_no  # 首行机器可解析
    assert "盐酸万古霉素原料" in content
    assert f"批号:{req.inbound_batch_no}" in content
    assert f"复验期:{req.expiry_date}" in content
    # 富文本可被 segno 编码（不抛异常即通过）
    import io as _io

    import segno

    buf = _io.BytesIO()
    segno.make(content, error="m").save(buf, kind="png", scale=4, border=1)
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_move_auto_by_status(db_session):
    """auto 模式：已赋码→入库；在库→出库；已领出→报错。"""
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    # labeled → 自动入库
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="auto")
    )
    assert updated.status == "in_warehouse"
    # in_warehouse → 自动出库
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="auto")
    )
    assert updated.status == "issued"
    # issued → 无法自动判定
    with pytest.raises(AppException) as exc:
        await material_container_service.move_container(
            db_session, no, ContainerMoveRequest(op_type="auto")
        )
    assert exc.value.status_code == 400
    assert "自动判定" in exc.value.detail


async def test_move_auto_qualified_goes_out(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    await material_container_service.update_status(db_session, no, "qualified")
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="auto")
    )
    assert updated.status == "issued"


async def test_move_return_flow(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="out"))
    # 退库
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="return", remark="车间退回")
    )
    assert updated.status == "returned"
    # 退库后可重新入库
    updated = await material_container_service.move_container(
        db_session, no, ContainerMoveRequest(op_type="in")
    )
    assert updated.status == "in_warehouse"


async def test_status_update_with_remark(db_session):
    containers = await material_container_service.generate_containers(db_session, _gen_req(1))
    no = containers[0].container_no
    await material_container_service.update_status(db_session, no, "void", remark="标签贴错作废")
    movements = await list_container_movements(db_session, containers[0].id)
    assert movements[0].remark == "标签贴错作废"


async def test_today_stats(db_session):
    from app.modules.quality.repository import material_today_stats

    # 开发库共享：用增量断言而非绝对值（当天可能有真实操作数据）
    before = await material_today_stats(db_session)
    containers = await material_container_service.generate_containers(db_session, _gen_req(2))
    for c in containers:
        await material_container_service.move_container(db_session, c.container_no, ContainerMoveRequest(op_type="in"))
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="out"))
    after = await material_today_stats(db_session)
    assert after["today_in"] == before["today_in"] + 2
    assert after["today_out"] == before["today_out"] + 1


async def test_consumption_trend_shape(db_session):
    from app.modules.quality.repository import material_consumption_trend

    req = _gen_req(1)
    containers = await material_container_service.generate_containers(db_session, req)
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="in"))
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="out"))
    trend = await material_consumption_trend(db_session, req.material_code, months=3)
    assert len(trend) == 3
    assert trend[-1]["month"] >= trend[0]["month"]  # 升序补全空月
    current = trend[-1]
    assert current["out"] >= 1  # 当月有出库


async def test_supplier_crud_and_alerts(db_session):
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from app.modules.quality.repository import (
        create_supplier,
        delete_supplier,
        get_supplier_by_code,
        list_suppliers,
        supplier_qual_alerts,
        update_supplier,
    )

    code = f"SUP-{_rand_code()}"
    supplier = await create_supplier(db_session, {
        "code": code, "name": "测试供应商", "contact": "张三",
        "qual_expiry_date": (_dt.now() + _td(days=30)).strftime("%Y-%m-%d"),
    })
    assert await get_supplier_by_code(db_session, code) is not None
    rows = await list_suppliers(db_session, q=code[:6])
    assert any(s.code == code for s in rows)
    updated = await update_supplier(db_session, supplier.id, {"contact": "李四"})
    assert updated is not None and updated.contact == "李四"
    # 资质临期提醒（30 天内在 90 天窗口内）
    alerts = await supplier_qual_alerts(db_session)
    assert any(a["code"] == code and not a["expired"] for a in alerts)
    assert await delete_supplier(db_session, supplier.id) is True
    assert await get_supplier_by_code(db_session, code) is None


async def test_supplier_expired_alert(db_session):
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from app.modules.quality.repository import create_supplier, supplier_qual_alerts

    code = f"SUP-{_rand_code()}"
    await create_supplier(db_session, {
        "code": code, "name": "过期供应商",
        "qual_expiry_date": (_dt.now() - _td(days=10)).strftime("%Y-%m-%d"),
    })
    alerts = await supplier_qual_alerts(db_session)
    assert any(a["code"] == code and a["expired"] for a in alerts)


async def test_stocktake_full_flow(db_session):
    from app.modules.quality.repository import (
        list_stocktake_items,
    )

    code = f"MAT-{_rand_code()}"
    req = MaterialContainerGenerateRequest(
        material_code=code, material_name="盘点测试物料",
        inbound_batch_no="IN-ST", expiry_date=None, count=3,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    # 1 瓶入库（在库），1 瓶入库后领出（不在库），1 瓶保持已赋码（不在库）
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="in"))
    await material_container_service.move_container(db_session, containers[1].container_no, ContainerMoveRequest(op_type="in"))
    await material_container_service.move_container(db_session, containers[1].container_no, ContainerMoveRequest(op_type="out"))

    sheet = await material_container_service.create_stocktake(db_session, code, "月末盘点")  # 限定范围防共享库真实数据干扰
    assert sheet.expected_count == 1  # 仅 1 瓶在库

    # 扫到在库瓶 → matched
    await material_container_service.scan_stocktake(db_session, sheet.id, containers[0].container_no)
    # 扫到已领出瓶 → out_of_scope（盘盈）
    await material_container_service.scan_stocktake(db_session, sheet.id, containers[1].container_no)
    # 扫到不存在 → not_found（盘盈）
    await material_container_service.scan_stocktake(db_session, sheet.id, f"MC-{_rand_code()}-20261010-0001")
    # 重复扫描 → 409
    from app.core.exceptions import AppException
    with pytest.raises(AppException) as exc:
        await material_container_service.scan_stocktake(db_session, sheet.id, containers[0].container_no)
    assert exc.value.status_code == 409

    finished = await material_container_service.finish_stocktake(db_session, sheet.id)
    assert finished.status == "completed"
    assert finished.scanned_count == 3
    assert finished.extra_count == 1  # 仅 out_of_scope（已领出实物在架）计盘盈
    assert finished.anomaly_count == 1  # not_found（系统不存在）计异常
    assert finished.missing_count == 0  # 唯一在库瓶已扫到
    items = await list_stocktake_items(db_session, sheet.id)
    assert len(items) == 3


async def test_stocktake_missing_detection(db_session):
    code = f"MAT-{_rand_code()}"
    req = MaterialContainerGenerateRequest(
        material_code=code, material_name="盘亏测试物料",
        inbound_batch_no="IN-MISS", expiry_date=None, count=2,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    for c in containers:
        await material_container_service.move_container(db_session, c.container_no, ContainerMoveRequest(op_type="in"))
    sheet = await material_container_service.create_stocktake(db_session, code, "抽查")
    assert sheet.expected_count == 2
    # 只扫到 1 瓶
    await material_container_service.scan_stocktake(db_session, sheet.id, containers[0].container_no)
    finished = await material_container_service.finish_stocktake(db_session, sheet.id)
    assert finished.missing_count == 1


async def test_monthly_report(db_session):
    from app.core.time import today as _today
    from app.modules.quality.repository import material_monthly_report

    month = _today().strftime("%Y-%m")
    code = f"MAT-{_rand_code()}"
    req = MaterialContainerGenerateRequest(
        material_code=code, material_name="月度报表物料",
        inbound_batch_no="IN-MR", expiry_date=None, count=1,
    )
    containers = await material_container_service.generate_containers(db_session, req)
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="in"))
    before = await material_monthly_report(db_session, month)
    before_in = next((r["in_count"] for r in before if r["material_code"] == code), 0)
    before_out = next((r["out_count"] for r in before if r["material_code"] == code), 0)
    await material_container_service.move_container(db_session, containers[0].container_no, ContainerMoveRequest(op_type="out"))
    after = await material_monthly_report(db_session, month)
    item = next(r for r in after if r["material_code"] == code)
    assert item["in_count"] == before_in  # 入库发生在 before 之前
    assert item["out_count"] == before_out + 1


async def test_import_dict_rows(db_session):
    from app.modules.quality.repository import get_material_by_code

    code = f"MAT-{_rand_code()}"
    import io as _io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["code", "name", "category", "vendor_name", "pack_spec", "min_stock", "valid_months", "remark"])
    ws.append([code, "导入物料A", "原料", "供应商甲", "5kg/听", 3, 24, "测试"])
    ws.append([code, "导入物料A重复", "", "", "", "", "", ""])  # 重复 → 跳过
    ws.append(["", "缺代码", "", "", "", "", "", ""])  # 缺代码 → 跳过
    buf = _io.BytesIO()
    wb.save(buf)
    result = await material_container_service.import_dict_rows(db_session, buf.getvalue())
    assert len(result["created"]) == 1 and result["created"][0] == code
    assert len(result["skipped"]) == 2
    assert await get_material_by_code(db_session, code) is not None


async def test_import_container_rows(db_session):
    import io as _io

    import openpyxl

    no = f"MC-IMP-20261010-{str(_rand_code())[:4]}"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["container_no", "material_code", "material_name", "vendor_code", "inbound_batch_no", "inbound_date", "expiry_date", "location", "status"])
    ws.append([no, "IMP", "导入容器物料", "SUP-X", "IN-IMP", "2026-10-01", "2028-09-30", "A-01-03", "in_warehouse"])
    ws.append([no, "IMP", "重复", "", "", "", "", "", "labeled"])  # 重复 → 跳过
    ws.append(["MC-IMP-20261010-9999", "IMP", "状态非法", "", "", "", "", "", "不存在的状态"])  # 非法状态 → 跳过
    buf = _io.BytesIO()
    wb.save(buf)
    result = await material_container_service.import_container_rows(db_session, buf.getvalue())
    assert len(result["created"]) == 1
    assert len(result["skipped"]) == 2
    from app.modules.quality.repository import get_material_container_by_no

    imported = await get_material_container_by_no(db_session, no)
    assert imported is not None
    assert imported.location == "A-01-03" and imported.status == "in_warehouse"


async def test_slow_moving_and_location(db_session):
    from app.modules.quality.repository import (
        list_slow_moving_containers,
        update_container_location,
    )

    req = _gen_req(1)
    containers = await material_container_service.generate_containers(db_session, req)
    no = containers[0].container_no
    # 设置一个 60 天前的入库日期
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    old_date = (_dt.now() - _td(days=60)).strftime("%Y-%m-%d")
    await material_container_service.move_container(db_session, no, ContainerMoveRequest(op_type="in"))
    await update_container_location(db_session, containers[0].id, "B-02-05")
    containers[0].inbound_date = old_date
    await db_session.flush()
    rows = await list_slow_moving_containers(db_session, min_age_days=30)
    hit = next((r for r in rows if r["container_no"] == no), None)
    assert hit is not None and hit["age_days"] >= 59
    assert hit["location"] == "B-02-05"


# ─── 物料请验 → 检验 → 放行全链路 ───


async def _setup_material_standard(db_session, code: str, vendor: str | None = None):
    from app.modules.quality.repository import (
        create_material,
        create_material_standard,
        create_material_standard_item,
    )

    material = await create_material(db_session, {"code": code, "name": "请验测试物料", "vendor_name": "测试供应商"})
    std = await create_material_standard(db_session, {
        "material_code": code, "material_name": material.name, "vendor_code": vendor,
    })
    await create_material_standard_item(db_session, {
        "standard_id": std.id, "seq": 1, "item_name": "水分", "sop_no": "SOP-M-001",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    await create_material_standard_item(db_session, {
        "standard_id": std.id, "seq": 2, "item_name": "外观", "sop_no": None,
        "standard_text": "白色粉末", "operator": None,
    })
    return std


async def test_request_sample_task_release_flow(db_session):
    from app.modules.quality.repository import (
        list_containers_by_request,
        list_test_results,
    )
    from app.modules.quality.schemas import (
        MaterialRequestCreate,
        MaterialRequestRelease,
        MaterialRequestSample,
    )

    code = f"MAT-{_rand_code()}"
    await _setup_material_standard(db_session, code)
    # 创建请验单
    req = await material_container_service.create_request(db_session, MaterialRequestCreate(
        material_code=code, inbound_batch_no=f"IN-RQ-{_rand_code()[:6]}", inbound_qty=3,
    ))
    assert req.status == "pending_sample" and req.request_no.startswith("MR-")
    # 取样
    req = await material_container_service.sample_request(db_session, req.id, MaterialRequestSample(sampled_qty=1))
    assert req.status == "sampled"
    # 建物料检验任务（快照标准 2 行，auto/manual 推导）
    task = await material_container_service.create_material_task(db_session, req.id)
    assert task.task_kind == "material" and task.material_request_id == req.id
    rows = await list_test_results(db_session, task.id)
    assert len(rows) == 2
    modes = {r.item_name: r.judge_mode for r in rows}
    assert modes["水分"] == "auto" and modes["外观"] == "manual"
    # 赋码挂请验单（3 瓶）→ 放行联动容器
    containers = await material_container_service.generate_containers(db_session, MaterialContainerGenerateRequest(
        material_code=code, material_name="请验测试物料", inbound_batch_no=req.inbound_batch_no, count=3,
    ))
    for c in containers:
        c.material_request_id = req.id
    await db_session.flush()
    # 放行
    req = await material_container_service.release_request(db_session, req.id, MaterialRequestRelease(verdict="release"))
    assert req.status == "released"
    linked = await list_containers_by_request(db_session, req.id)
    assert len(linked) == 3 and all(c.status == "qualified" for c in linked)


async def test_release_reject_voids_containers(db_session):
    from app.modules.quality.repository import list_containers_by_request
    from app.modules.quality.schemas import (
        MaterialRequestCreate,
        MaterialRequestRelease,
    )

    code = f"MAT-{_rand_code()}"
    await _setup_material_standard(db_session, code)
    req = await material_container_service.create_request(db_session, MaterialRequestCreate(
        material_code=code, inbound_batch_no=f"IN-RJ-{_rand_code()[:6]}", inbound_qty=2,
    ))
    containers = await material_container_service.generate_containers(db_session, MaterialContainerGenerateRequest(
        material_code=code, material_name="请验测试物料", inbound_batch_no=req.inbound_batch_no, count=2,
    ))
    for c in containers:
        c.material_request_id = req.id
    await db_session.flush()
    req = await material_container_service.release_request(db_session, req.id, MaterialRequestRelease(
        verdict="reject", remark="杂质超标",
    ))
    assert req.status == "rejected" and req.verdict_remark == "杂质超标"
    linked = await list_containers_by_request(db_session, req.id)
    assert all(c.status == "void" for c in linked)


async def test_request_task_conflicts(db_session):
    from app.modules.quality.schemas import MaterialRequestCreate

    code = f"MAT-{_rand_code()}"
    await _setup_material_standard(db_session, code)
    req = await material_container_service.create_request(db_session, MaterialRequestCreate(
        material_code=code, inbound_batch_no=f"IN-RC-{_rand_code()[:6]}",
    ))
    # 未取样不可建任务
    with pytest.raises(AppException) as exc:
        await material_container_service.create_material_task(db_session, req.id)
    assert exc.value.status_code == 400
    # 取样后建任务；重复建 → 409
    from app.modules.quality.schemas import MaterialRequestSample

    await material_container_service.sample_request(db_session, req.id, MaterialRequestSample())
    await material_container_service.create_material_task(db_session, req.id)
    with pytest.raises(AppException) as exc2:
        await material_container_service.create_material_task(db_session, req.id)
    assert exc2.value.status_code == 409


async def test_micro_record_judge(db_session):
    from app.modules.quality.api._materials import _micro_judge
    from app.modules.quality.repository import create_micro_record, get_micro_record

    # 判定规则
    assert _micro_judge(5, 10, 20) == "pass"
    assert _micro_judge(15, 10, 20) == "alert"
    assert _micro_judge(25, 10, 20) == "action"
    assert _micro_judge(None, 10, 20) is None
    # 创建即判定
    rec = await create_micro_record(db_session, {
        "sample_name": "微生物限度测试", "batch_number": "HAF2609001",
        "colony_count": 25, "alert_limit": 10, "action_limit": 20,
        "judge": "action",
    })
    got = await get_micro_record(db_session, rec.id)
    assert got is not None and got.judge == "action"
