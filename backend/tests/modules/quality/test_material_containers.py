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
