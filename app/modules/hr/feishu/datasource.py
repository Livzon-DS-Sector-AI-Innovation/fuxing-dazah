"""Generic Feishu Bitable datasource adapter.

可以把任意多维表格当作数据源进行 CRUD + 批量同步操作。
用法类似简化版 ORM，但底层走飞书 API。
"""

import logging
from datetime import date, datetime
from typing import Any

from app.modules.hr.feishu.bitable import BitableClient, _to_ms_timestamp

logger = logging.getLogger(__name__)


class BitableDataSource:
    """通用多维表格数据源封装。

    Example:
        ds = BitableDataSource(
            app_token="KHLsboPBGaah6Vs3EpgcpvzsnuH",
            table_id="tblrcSHfS5ivun7e",
        )

        # 查询
        rows = await ds.query(filter_str='CurrentValue.[状态] = "活跃"')

        # 新增
        new_id = await ds.create({"姓名": "张三", "年龄": 25})

        # 更新
        await ds.update(record_id="recXxx", {"年龄": 26})

        # 删除
        await ds.delete(record_id="recXxx")
    """

    def __init__(self, app_token: str, table_id: str) -> None:
        self.client = BitableClient()
        # 覆盖 app_token，支持操作任意表格（不仅限于配置中的默认表格）
        self.client.app_token = app_token
        self.table_id = table_id
        self.app_token = app_token

    # ─── 基础 CRUD ───

    async def create(self, fields: dict[str, Any]) -> str:
        """新增一行，返回 record_id。"""
        record = await self.client.create_record(self.table_id, fields)
        rid = record.get("record_id", "")
        logger.info("[BitableDS] created record %s in %s", rid, self.table_id)
        return rid

    async def update(self, record_id: str, fields: dict[str, Any]) -> None:
        """更新指定行。"""
        await self.client.update_record(self.table_id, record_id, fields)
        logger.info("[BitableDS] updated record %s in %s", record_id, self.table_id)

    async def delete(self, record_id: str) -> None:
        """删除指定行。"""
        await self.client.delete_record(self.table_id, record_id)
        logger.info("[BitableDS] deleted record %s from %s", record_id, self.table_id)

    async def query(
        self,
        *,
        filter_str: str | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """按条件查询，返回原始 records 列表。"""
        return await self.client.search_records(
            self.table_id,
            filter_str=filter_str,
            page_size=page_size,
        )

    async def get_by_field(self, field_name: str, value: str) -> dict[str, Any] | None:
        """根据单个字段精确查找一行。"""
        # 注意：field_name 是飞书字段名，如果包含特殊字符建议用 field_id
        items = await self.query(
            filter_str=f'CurrentValue.[{field_name}] = "{value}"'
        )
        return items[0] if items else None

    # ─── 批量同步（本地 PostgreSQL ↔ 多维表格） ───

    async def upsert_by_key(
        self,
        *,
        key_field: str,
        key_value: str,
        fields: dict[str, Any],
    ) -> str:
        """根据 key_field 查找，存在则更新，不存在则创建。"""
        existing = await self.get_by_field(key_field, key_value)
        if existing:
            rid = existing["record_id"]
            await self.update(rid, fields)
            return rid
        else:
            return await self.create(fields)

    async def bulk_upsert(
        self,
        *,
        key_field: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """批量 upsert。

        Args:
            key_field: 用于判断唯一性的字段名（如"工号"）
            rows: 每行必须包含 key_field 对应的值

        Returns:
            {"created": [...], "updated": [...]}
        """
        created: list[str] = []
        updated: list[str] = []

        for row in rows:
            key_value = str(row.pop(key_field, ""))
            if not key_value:
                continue
            rid = await self.upsert_by_key(
                key_field=key_field,
                key_value=key_value,
                fields=row,
            )
            # 简单判断：如果能查到已有记录则为 update，否则 create
            # 实际上 upsert_by_key 内部已处理
            existing = await self.get_by_field(key_field, key_value)
            if existing and existing.get("record_id") == rid:
                updated.append(rid)
            else:
                created.append(rid)

        return {"created": created, "updated": updated}

    # ─── 字段类型转换辅助 ───

    @staticmethod
    def prepare_fields(raw: dict[str, Any], date_fields: set[str] | None = None) -> dict[str, Any]:
        """将 Python 原生类型转换为飞书多维表格接受的格式。

        自动处理：
        - datetime/date -> 毫秒时间戳
        - bool -> bool
        - 其他 -> 保持原样（str/int/float）
        """
        date_fields = date_fields or set()
        prepared: dict[str, Any] = {}
        for k, v in raw.items():
            if v is None:
                continue
            if k in date_fields and isinstance(v, (date, datetime, str)):
                prepared[k] = _to_ms_timestamp(v)
            else:
                prepared[k] = v
        return prepared
