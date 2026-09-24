"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    CoaTemplateBinding,
    QualityStandardDocument,
    QualityStandardItem,
)

# ─── 质量标准文档 / 项目行（SOP 号为匹配键）───


async def list_standard_documents(
    db: AsyncSession,
    product_name: str | None = None,
) -> list[QualityStandardDocument]:
    stmt = select(QualityStandardDocument).where(
        QualityStandardDocument.is_deleted == False  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(QualityStandardDocument.product_name.ilike(f"%{product_name}%"))
    stmt = stmt.order_by(QualityStandardDocument.product_name, QualityStandardDocument.file_no)
    return list((await db.execute(stmt)).scalars())


async def get_standard_document_by_file_no(
    db: AsyncSession, file_no: str
) -> QualityStandardDocument | None:
    """按文件编号查标准文档（表号↔标准文档映射用）。

    取最近创建的一条（软删后重建的历史数据可能多行，scalar_one_or_none 会 500）。
    """
    stmt = (
        select(QualityStandardDocument)
        .where(
            QualityStandardDocument.file_no == file_no,
            QualityStandardDocument.is_deleted == False,  # noqa: E712
        )
        .order_by(QualityStandardDocument.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def get_standard_document(
    db: AsyncSession, doc_id: uuid.UUID
) -> QualityStandardDocument | None:
    stmt = select(QualityStandardDocument).where(
        QualityStandardDocument.id == doc_id,
        QualityStandardDocument.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_standard_document(
    db: AsyncSession, data: dict
) -> QualityStandardDocument:
    doc = QualityStandardDocument(**data)
    db.add(doc)
    await db.flush()
    return doc


async def update_standard_document(
    db: AsyncSession, doc_id: uuid.UUID, **kwargs
) -> QualityStandardDocument | None:
    doc = await get_standard_document(db, doc_id)
    if not doc:
        return None
    for key, val in kwargs.items():
        if hasattr(doc, key) and val is not None:
            setattr(doc, key, val)
    await db.flush()
    return doc


async def delete_standard_document(
    db: AsyncSession, doc_id: uuid.UUID
) -> QualityStandardDocument | None:
    doc = await get_standard_document(db, doc_id)
    if not doc:
        return None
    doc.is_deleted = True
    items = await list_standard_items(db, doc_id)
    for it in items:
        it.is_deleted = True
    await db.flush()
    return doc


async def list_standard_items(
    db: AsyncSession, doc_id: uuid.UUID
) -> list[QualityStandardItem]:
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.document_id == doc_id,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    ).order_by(QualityStandardItem.seq, QualityStandardItem.created_at)
    return list((await db.execute(stmt)).scalars())


async def create_standard_item(
    db: AsyncSession, doc_id: uuid.UUID, data: dict
) -> QualityStandardItem:
    item = QualityStandardItem(document_id=doc_id, **data)
    db.add(item)
    await db.flush()
    return item


async def update_standard_item(
    db: AsyncSession, item_id: uuid.UUID, **kwargs
) -> QualityStandardItem | None:
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.id == item_id,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    for key, val in kwargs.items():
        if hasattr(item, key) and val is not None:
            setattr(item, key, val)
    await db.flush()
    return item


async def delete_standard_item(
    db: AsyncSession, item_id: uuid.UUID
) -> QualityStandardItem | None:
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.id == item_id,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if not item:
        return None
    item.is_deleted = True
    await db.flush()
    return item


async def get_standard_item_by_sop(
    db: AsyncSession, sop_no: str
) -> list[QualityStandardItem]:
    """按 SOP 号查标准行（同名项目不同 SOP 的匹配入口）。"""
    stmt = select(QualityStandardItem).where(
        QualityStandardItem.sop_no == sop_no,
        QualityStandardItem.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def list_standard_documents_by_product(
    db: AsyncSession, product_name: str
) -> list[QualityStandardDocument]:
    """按产品名称查询全部标准文档（忽略名称中的空白差异，如半角空格）。

    同一产品的不同文档可能因导入批次不同而名称写法略有差异（如
    「Vancomycin Hydrochloride」vs「VancomycinHydrochloride」），
    建任务快照时必须全部命中，否则漏其他代号的项目行。
    """
    norm = re.sub(r"\s+", "", product_name)
    stmt = select(QualityStandardDocument).where(
        func.regexp_replace(QualityStandardDocument.product_name, r"\s", "", "g") == norm,
        QualityStandardDocument.is_deleted == False,  # noqa: E712
    ).order_by(QualityStandardDocument.created_at.desc())
    return list((await db.execute(stmt)).scalars())


# ─── COA 模板 ↔ 标准文档绑定（COA 唯一，SOP 可多 COA）───


async def list_coa_bindings(db: AsyncSession) -> list[CoaTemplateBinding]:
    stmt = select(CoaTemplateBinding).where(
        CoaTemplateBinding.is_deleted == False,  # noqa: E712
    ).order_by(CoaTemplateBinding.template_path)
    return list((await db.execute(stmt)).scalars())


async def get_coa_binding_by_template(
    db: AsyncSession, template_path: str
) -> CoaTemplateBinding | None:
    stmt = select(CoaTemplateBinding).where(
        CoaTemplateBinding.template_path == template_path,
        CoaTemplateBinding.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_coa_binding(
    db: AsyncSession,
    template_path: str,
    standard_document_id: uuid.UUID | None = None,
    sop_no: str | None = None,
    description: str | None = None,
) -> CoaTemplateBinding:
    """按模板路径 upsert（COA 唯一性）；返回 UPDATE 后 re-fetch 对象。"""
    binding = await get_coa_binding_by_template(db, template_path)
    if binding:
        binding.standard_document_id = standard_document_id or binding.standard_document_id
        binding.sop_no = sop_no or binding.sop_no
        if description is not None:
            binding.description = description
        await db.flush()
    else:
        binding = CoaTemplateBinding(
            template_path=template_path,
            standard_document_id=standard_document_id,
            sop_no=sop_no,
            description=description,
        )
        db.add(binding)
        await db.flush()
    stmt = select(CoaTemplateBinding).where(CoaTemplateBinding.id == binding.id)
    return (await db.execute(stmt)).scalar_one()


async def delete_coa_binding(
    db: AsyncSession, template_path: str
) -> CoaTemplateBinding | None:
    binding = await get_coa_binding_by_template(db, template_path)
    if not binding:
        return None
    binding.is_deleted = True
    await db.flush()
    stmt = select(CoaTemplateBinding).where(CoaTemplateBinding.id == binding.id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_coa_bindings_by_docs(
    db: AsyncSession, doc_ids: list[uuid.UUID]
) -> list[CoaTemplateBinding]:
    if not doc_ids:
        return []
    stmt = select(CoaTemplateBinding).where(
        CoaTemplateBinding.standard_document_id.in_(doc_ids),
        CoaTemplateBinding.is_deleted == False,  # noqa: E712
    ).order_by(CoaTemplateBinding.created_at)
    return list((await db.execute(stmt)).scalars())
