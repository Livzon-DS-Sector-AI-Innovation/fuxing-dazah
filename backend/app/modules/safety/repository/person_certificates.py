"""Safety database queries."""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    PersonCertificate,
)


class PersonCertificateRepository:
    """人员持证台账数据访问（预警派生由 CertWarningEngine 在 Service 层计算）。

    只读写不派生业务语义（CLAUDE.md repository 职责规则）。status_level /
    days_within 的派生过滤统一在 Service 层用 CertWarningEngine.calculate() 完成。
    async 铁律：INSERT → flush 返回；UPDATE → 用 update(...).returning() re-fetch。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_warnings(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        status_level: str | None = None,
        department: str | None = None,
        cert_category: str | None = None,
        days_within: int | None = None,
    ) -> tuple[list[PersonCertificate], int]:
        """活行查询（is_deleted=false）+ 部门/类别 SQL 过滤 + 日期升序排序。

        status_level / days_within 不在 SQL 层过滤（引擎派生后由 Service 切片）。
        拉全量候选（持证台账预估 < 1000 条）→ Python 引擎计算 → 内存过滤 → 切片。
        """
        filters = [PersonCertificate.is_deleted.is_(False)]  # noqa: E712
        if department:
            filters.append(PersonCertificate.department == department)
        if cert_category:
            filters.append(PersonCertificate.cert_category == cert_category)

        base = select(PersonCertificate).where(*filters).order_by(
            PersonCertificate.cert_category.asc(),
            PersonCertificate.next_review_date.asc().nulls_last(),
            PersonCertificate.should_renew_date.asc().nulls_last(),
            PersonCertificate.created_at.desc(),
        )
        result = await self.session.execute(base)
        all_rows = list(result.scalars().all())
        return all_rows, len(all_rows)

    async def get_all_active(self) -> list[PersonCertificate]:
        """全量活行（定时任务/汇总用，无分页，按 cert_category, next_review_date 排序）。"""
        query = (
            select(PersonCertificate)
            .where(PersonCertificate.is_deleted.is_(False))  # noqa: E712
            .order_by(
                PersonCertificate.cert_category.asc(),
                PersonCertificate.next_review_date.asc().nulls_last(),
                PersonCertificate.should_renew_date.asc().nulls_last(),
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, cert_id: uuid.UUID) -> PersonCertificate | None:
        """按 id 取活行（renew 端点用）。"""
        row = await self.session.get(PersonCertificate, cert_id)
        if row is None or row.is_deleted:
            return None
        return row

    async def renew(
        self, cert_id: uuid.UUID, data: dict[str, Any]
    ) -> PersonCertificate | None:
        """UPDATE 回填 renewed_date / next_review_date / notes。

        async 铁律：UPDATE 后必须 re-fetch 返回（flush 不回填 onupdate 的
        updated_at，否则序列化触发 MissingGreenlet）。用 update(...).returning()。
        """
        query = (
            update(PersonCertificate)
            .where(
                PersonCertificate.id == cert_id,
                PersonCertificate.is_deleted.is_(False),  # noqa: E712
            )
            .values(**data, updated_at=func.now())
            .returning(PersonCertificate)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def upsert_from_bitable(
        self, values: dict[str, Any], record_id: str
    ) -> PersonCertificate | None:
        """Bitable 镜像 upsert（活行 WHERE is_deleted=false）。

        模式复用 oh_bitable_handler._upsert：
          1. 查 existing（feishu_record_id 匹配，活行）
          2. existing → 应用新值 + commit
          3. 无 existing → INSERT（flush 返回）
        返回 upsert 后的对象。
        """
        existing = await self.session.scalar(
            select(PersonCertificate).where(
                PersonCertificate.feishu_record_id == record_id,
                PersonCertificate.is_deleted.is_(False),  # noqa: E712
            )
        )
        mapped = dict(values)
        mapped["feishu_record_id"] = record_id
        if existing is not None:
            self._apply_values(existing, mapped)
            await self.session.commit()
            return existing
        row = PersonCertificate(**mapped)
        self.session.add(row)
        await self.session.flush()
        return row

    def _apply_values(self, row: PersonCertificate, values: dict[str, Any]) -> None:
        """把 dict 字段应用到 ORM 行（镜像 upsert / 回填共用）。"""
        for key, value in values.items():
            setattr(row, key, value)

    async def soft_delete_by_feishu_id(self, record_id: str) -> bool:
        """软删除 Bitable 来源记录 + 清空唯一键（防重复添加→删除→添加隐形 bug）。

        清空 feishu_record_id（本表唯一约束只有 feishu_record_id），保证软删后
        record_id 可再次被唯一索引占用。
        """
        query = (
            update(PersonCertificate)
            .where(
                PersonCertificate.feishu_record_id == record_id,
                PersonCertificate.source == "bitable",
                PersonCertificate.is_deleted.is_(False),  # noqa: E712
            )
            .values(is_deleted=True, feishu_record_id=None)
        )
        result = await self.session.execute(query)
        return (cast(CursorResult[Any], result).rowcount or 0) > 0

