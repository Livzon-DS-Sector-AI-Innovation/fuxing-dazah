"""工单图片域测试：service.work_order_image 与 repository.work_order_image。

覆盖 upload_images（表单上传）、save_photo_from_base64（MCP base64 上传）
的业务校验规则，以及 repository 的增查删（软删）。

断言以业务规则为准（每工单最多 9 张、扩展名白名单、大小上限、magic bytes
识别），而非照抄实现。存储 IO 通过 mock `app.core.storage` 的
`is_enabled`/`upload_object` 隔离，只 mock 存储写入，不 mock 被测校验逻辑。
"""

import base64
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment.models import Equipment, Location, WorkOrder
from app.modules.equipment.models.work_order_image import WorkOrderImage
from app.modules.equipment.repository import work_order as wo_repo
from app.modules.equipment.repository import work_order_image as image_repo
from app.modules.equipment.service import work_order_image as image_service

# ═══════════ 测试用图片字节（每个 ≥ 64 字节，含正确 magic bytes）═══════════

MIN_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
MIN_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
MIN_WEBP = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 56
MIN_BMP = b"BM" + b"\x00" * 62
UNKNOWN_IMG = b"\x01\x02\x03\x04" + b"\x00" * 60  # 无匹配 magic，应回退 jpg


# ═══════════ 辅助工具 ═══════════════════════════════════════════


def _make_upload(
    filename: str,
    content: bytes = MIN_PNG,
    size: int | None = -1,
) -> UploadFile:
    """构造 starlette UploadFile。size=-1 表示自动取 len(content)。"""
    actual = len(content) if size == -1 else size
    return UploadFile(file=BytesIO(content), size=actual, filename=filename)


@contextmanager
def _mock_storage() -> Iterator[MagicMock]:
    """把存储切到 MinIO 分支并 mock 写入，避免真实落盘。

    只拦截存储 IO（is_enabled/upload_object），被测的校验逻辑照常执行。
    """
    with (
        patch("app.core.storage.is_enabled", return_value=True),
        patch("app.core.storage.upload_object") as upload_mock,
    ):
        upload_mock.side_effect = lambda module, object_key, **kw: object_key
        yield upload_mock


# ═══════════ Fixtures ═══════════════════════════════════════════


@pytest.fixture
async def work_order(db_session: AsyncSession) -> WorkOrder:
    """创建一个父工单（含 Location + Equipment），供图片挂载。"""
    location = Location(name="图片车间", code=f"WS-{uuid.uuid4().hex[:8]}")
    db_session.add(location)
    await db_session.flush()

    equipment = Equipment(
        equipment_no=f"EQ-{uuid.uuid4().hex[:8]}",
        name="图片测试设备",
        location_id=location.id,
        status="在用",
    )
    db_session.add(equipment)
    await db_session.flush()

    return await wo_repo.create_work_order(
        db_session,
        {
            "work_order_no": f"WO-IMG-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment.id,
            "order_type": "故障维修",
        },
    )


async def _seed_images(
    db: AsyncSession, work_order_id: uuid.UUID, count: int
) -> None:
    """直接入库 count 张图片（跳过存储层），用于凑满数量上限。"""
    for i in range(count):
        await image_repo.create_image(
            db,
            {
                "work_order_id": work_order_id,
                "file_name": f"seed-{i}.png",
                "file_path": f"work-orders/{work_order_id}/seed-{i}.png",
                "file_size": 128,
            },
        )


# ═══════════ upload_images ═══════════════════════════════════════


async def test_upload_images_work_order_not_found(
    db_session: AsyncSession,
) -> None:
    """工单不存在时上传应抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await image_service.upload_images(
            db_session, uuid.uuid4(), [_make_upload("a.png")]
        )


async def test_upload_images_exceed_nine(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """已有 9 张再传 1 张（合计 10 > 9）应抛 AppException。"""
    await _seed_images(db_session, work_order.id, 9)
    with pytest.raises(AppException) as exc:
        await image_service.upload_images(
            db_session, work_order.id, [_make_upload("a.png")]
        )
    assert "最多上传9张" in exc.value.message


async def test_upload_images_invalid_extension(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """扩展名不在白名单应抛 AppException。"""
    with pytest.raises(AppException) as exc:
        await image_service.upload_images(
            db_session, work_order.id, [_make_upload("a.txt")]
        )
    assert "不支持的文件类型" in exc.value.message


async def test_upload_images_size_none(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """无法获取文件大小（size=None）应抛 AppException。"""
    with pytest.raises(AppException) as exc:
        await image_service.upload_images(
            db_session,
            work_order.id,
            [_make_upload("a.png", size=None)],
        )
    assert "无法获取文件大小" in exc.value.message


async def test_upload_images_exceed_max_size(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """文件大小超过 MAX_UPLOAD_SIZE_MB 应抛 AppException。"""
    from app.core.config import get_settings

    over = get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1
    with pytest.raises(AppException) as exc:
        await image_service.upload_images(
            db_session,
            work_order.id,
            [_make_upload("a.png", size=over)],
        )
    assert "超过限制" in exc.value.message


async def test_upload_images_success_persists(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """合法图片应成功入库，返回对象数量正确且字段落库。"""
    with _mock_storage():
        images = await image_service.upload_images(
            db_session,
            work_order.id,
            [_make_upload("front.png"), _make_upload("back.jpg", MIN_JPG)],
        )
    assert len(images) == 2

    stored = await image_repo.get_images_by_work_order(db_session, work_order.id)
    assert len(stored) == 2
    names = {img.file_name for img in stored}
    assert names == {"front.png", "back.jpg"}
    assert all(img.file_size is not None and img.file_size > 0 for img in stored)


# ═══════════ save_photo_from_base64 ══════════════════════════════


async def test_save_photo_invalid_base64(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """base64 解码失败应抛 AppException。"""
    with pytest.raises(AppException) as exc:
        await image_service.save_photo_from_base64(
            db_session, work_order.id, "!!!not-base64!!!"
        )
    assert "解码失败" in exc.value.message


async def test_save_photo_too_large(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """解码后 > 10MB 应抛 AppException。"""
    big = MIN_PNG + b"\x00" * (10 * 1024 * 1024)
    b64 = base64.b64encode(big).decode()
    with pytest.raises(AppException) as exc:
        await image_service.save_photo_from_base64(db_session, work_order.id, b64)
    assert "超过上限" in exc.value.message


async def test_save_photo_too_small(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """解码后 < 64 字节应抛 AppException。"""
    small = base64.b64encode(b"\x89PNG" + b"\x00" * 40).decode()
    with pytest.raises(AppException) as exc:
        await image_service.save_photo_from_base64(db_session, work_order.id, small)
    assert "过小" in exc.value.message


async def test_save_photo_work_order_not_found(
    db_session: AsyncSession,
) -> None:
    """工单不存在应抛 NotFoundException（大小校验通过后才查工单）。"""
    b64 = base64.b64encode(MIN_PNG).decode()
    with pytest.raises(NotFoundException):
        await image_service.save_photo_from_base64(db_session, uuid.uuid4(), b64)


async def test_save_photo_exceed_nine(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """已有 9 张时再存应抛 AppException。"""
    await _seed_images(db_session, work_order.id, 9)
    b64 = base64.b64encode(MIN_PNG).decode()
    with pytest.raises(AppException) as exc:
        await image_service.save_photo_from_base64(db_session, work_order.id, b64)
    assert "最多上传9张" in exc.value.message


@pytest.mark.parametrize(
    ("content", "expected_ext"),
    [
        (MIN_PNG, ".png"),
        (MIN_JPG, ".jpg"),
        (MIN_WEBP, ".webp"),
        (MIN_BMP, ".bmp"),
        (UNKNOWN_IMG, ".jpg"),  # 无匹配 magic 回退 jpg
    ],
)
async def test_save_photo_magic_detection(
    db_session: AsyncSession,
    work_order: WorkOrder,
    content: bytes,
    expected_ext: str,
) -> None:
    """magic bytes 应正确识别扩展名；未知格式回退 jpg。"""
    b64 = base64.b64encode(content).decode()
    with _mock_storage():
        image = await image_service.save_photo_from_base64(
            db_session, work_order.id, b64
        )
    assert image.file_name.endswith(expected_ext)
    assert image.file_size == len(content)


async def test_save_photo_success_persists(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """成功写库：get_images_by_work_order 能查到该图片。"""
    b64 = base64.b64encode(MIN_PNG).decode()
    with _mock_storage():
        image = await image_service.save_photo_from_base64(
            db_session, work_order.id, b64, filename="site.png"
        )
    assert image.file_name == "site.png"

    stored = await image_repo.get_images_by_work_order(db_session, work_order.id)
    assert [img.id for img in stored] == [image.id]


# ═══════════ repository ══════════════════════════════════════════


async def test_repo_create_and_get_by_work_order(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """create_image 落库，get_images_by_work_order 按上传时间返回。"""
    await _seed_images(db_session, work_order.id, 3)
    images = await image_repo.get_images_by_work_order(db_session, work_order.id)
    assert len(images) == 3
    assert all(img.work_order_id == work_order.id for img in images)


async def test_repo_get_image_by_id(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """get_image_by_id 命中返回对象，随机 ID 返回 None。"""
    created = await image_repo.create_image(
        db_session,
        {
            "work_order_id": work_order.id,
            "file_name": "x.png",
            "file_path": "work-orders/x.png",
            "file_size": 100,
        },
    )
    fetched = await image_repo.get_image_by_id(db_session, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert await image_repo.get_image_by_id(db_session, uuid.uuid4()) is None


async def test_repo_delete_image_soft(
    db_session: AsyncSession, work_order: WorkOrder
) -> None:
    """delete_image 是软删：置 is_deleted，查询不再返回但物理行仍在。"""
    created = await image_repo.create_image(
        db_session,
        {
            "work_order_id": work_order.id,
            "file_name": "del.png",
            "file_path": "work-orders/del.png",
            "file_size": 100,
        },
    )
    await image_repo.delete_image(db_session, created)

    # 软删后正常查询查不到
    assert await image_repo.get_image_by_id(db_session, created.id) is None
    assert await image_repo.get_images_by_work_order(db_session, work_order.id) == []

    # 物理行仍存在且标记为已删除
    row = (
        await db_session.execute(
            select(WorkOrderImage).where(WorkOrderImage.id == created.id)
        )
    ).scalar_one()
    assert row.is_deleted is True
