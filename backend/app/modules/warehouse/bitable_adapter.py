"""warehouse 凭证下的飞书多维表格读写封装（S0 ticket 04）。

复用 ``platform/integrations/feishu/bitable.py`` 的 ``_request`` 传输层，
传入仓储专属飞书应用凭证（WAREHOUSE_FEISHU_APP_ID/SECRET，token 缓存按
凭证隔离）——platform 文件零改动。单条 create/get/delete 与 records/search
platform 未封装，本模块经同一 ``_request`` 拼装 OpenAPI 路径。

写契约见 ``bitable_schema.py`` 模块注释（V1.0-5，实测）：
- 写入前先本地校验（``validate_write_fields``）：只读字段拒写、
  单选必须为选项集内的**纯字符串**（读取返回数组，读写不对称）；
- 错误统一包装为 :class:`WarehouseBitableError`，保留飞书业务码分类
  （91403 权限 / 1254045 字段名 / 1254062 选项值 / 1254291 并发）——
  platform 的 FeishuAPIError 仅把 code 放在 message 文本中，此处解析保留。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.modules.warehouse.bitable_schema import (
    TABLES as _TABLES,
)
from app.modules.warehouse.bitable_schema import (
    FieldMeta,
    TableMeta,
    WarehouseBitableError,
    apply_runtime_fields,
    validate_write_fields,
)
from app.platform.integrations.feishu.bitable import (
    BITABLE_BASE,
    BitableAPIError,
    _request,
    list_fields,
)

# 飞书业务码（写入失败分类，V1.0-5 契约表）
CODE_NO_PERMISSION = 91403  # 应用无该 Base 权限
CODE_FIELD_NOT_FOUND = 1254045  # 字段名不存在（含误用 field_id）
CODE_INVALID_OPTION = 1254062  # 单选选项值非法 / 数组写单选
CODE_CONCURRENT_CONFLICT = 1254291  # 同表并发写冲突

_CODE_RE = re.compile(r"code=(-?\d+)")


def _parse_code(exc: BaseException) -> int | None:
    """从 platform 异常 message（`... code=<n> msg=...`）解析业务码。

    网络层异常的 message 无 code 段，返回 None。
    """
    match = _CODE_RE.search(str(exc))
    return int(match.group(1)) if match else None


class WarehouseBitableAdapter:
    """仓储 Agent 专用 Base 读写适配器（7 张核心表，测试版坐标）。

    凭证默认读 Settings 的 WAREHOUSE_FEISHU_APP_ID/SECRET 与
    WAREHOUSE_FEISHU_BITABLE_*_APP_TOKEN；构造参数 ``app_id``/``app_secret``/
    ``base_tokens``（{base_key: app_token}）可注入覆盖，便于测试。
    """

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        base_tokens: dict[str, str] | None = None,
    ) -> None:
        settings = get_settings()
        self._app_id = app_id or settings.WAREHOUSE_FEISHU_APP_ID
        self._app_secret = app_secret or settings.WAREHOUSE_FEISHU_APP_SECRET
        self._base_tokens = dict(base_tokens) if base_tokens else {}
        if not self._app_id or not self._app_secret:
            raise WarehouseBitableError(
                "缺少仓储飞书应用凭证（WAREHOUSE_FEISHU_APP_ID/SECRET），"
                "请在 env 配置或构造参数注入",
                code="missing_credentials",
            )

    # ── 内部工具 ──

    def _table(self, table_key: str) -> TableMeta:
        meta = _TABLES.get(table_key)
        if meta is None:
            raise WarehouseBitableError(
                f"未知的表坐标: {table_key!r}（可选: {sorted(_TABLES)}）",
                code="unknown_table",
            )
        return meta

    def _base_token(self, table_key: str) -> str:
        meta = self._table(table_key)
        token = self._base_tokens.get(meta.base_key) or getattr(
            get_settings(), meta.base_token_setting, ""
        )
        if not token:
            raise WarehouseBitableError(
                f"缺少 {meta.base_key} Base 的 app_token"
                f"（Settings.{meta.base_token_setting} 为空）",
                code="missing_credentials",
            )
        return token

    def _wrap(self, exc: BitableAPIError) -> WarehouseBitableError:
        return WarehouseBitableError(str(exc), code=_parse_code(exc))

    async def _call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """统一经 platform `_request` 发请求并包装错误（保留 code 分类）。"""
        try:
            return await _request(
                method,
                url,
                app_id=self._app_id,
                app_secret=self._app_secret,
                **kwargs,
            )
        except BitableAPIError as exc:
            raise self._wrap(exc) from exc

    # ── 读 ──

    async def query_records(
        self,
        table_key: str,
        filter_json: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询记录，返回 [{"record_id": str, "fields": {字段名: 值}}]。

        走 POST ``records/search``（支持结构化 filter_json，如
        ``{"conjunction": "and", "conditions": [{"field_name": "客户",
        "operator": "contains", "value": ["X"]}]}``，value 须为数组）；
        field_names 为返回字段名白名单；limit 即 page_size（≤500）。
        该接口必须携带 JSON body（无过滤条件时传空对象，实测缺 body 返
        9499 Invalid request parameters）。
        """
        meta = self._table(table_key)
        body: dict[str, Any] = {}
        if field_names:
            body["field_names"] = list(field_names)
        if filter_json:
            body["filter"] = filter_json
        data = await self._call(
            "POST",
            f"{BITABLE_BASE}/apps/{self._base_token(table_key)}"
            f"/tables/{meta.table_id}/records/search",
            json_body=body,
            params={"page_size": max(1, min(int(limit), 500))},
        )
        items = data.get("items") or []  # 无匹配时飞书返回 items: null
        return [
            {
                "record_id": str(item.get("record_id", "")),
                "fields": dict(item.get("fields") or {}),
            }
            for item in items
        ]

    async def get_record(self, table_key: str, record_id: str) -> dict[str, Any]:
        """按 record_id 取单条记录，返回 {"record_id": str, "fields": {...}}。

        记录不存在抛 WarehouseBitableError（飞书业务码 1254040）。
        """
        meta = self._table(table_key)
        data = await self._call(
            "GET",
            f"{BITABLE_BASE}/apps/{self._base_token(table_key)}"
            f"/tables/{meta.table_id}/records/{record_id}",
        )
        record = data.get("record") or {}
        return {
            "record_id": str(record.get("record_id", record_id)),
            "fields": dict(record.get("fields") or {}),
        }

    # ── 写（先本地契约校验，再发请求） ──

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """新建记录：先 ``validate_write_fields``（本地快速失败），再写入。

        单选字段传纯字符串（读写不对称，禁止数组）；字段键用字段名。
        返回 {"record_id": str, "fields": {回读字段: 值}}。
        """
        meta = self._table(table_key)
        validate_write_fields(table_key, fields)
        data = await self._call(
            "POST",
            f"{BITABLE_BASE}/apps/{self._base_token(table_key)}"
            f"/tables/{meta.table_id}/records",
            json_body={"fields": fields},
        )
        record = data.get("record") or {}
        return {
            "record_id": str(record.get("record_id", "")),
            "fields": dict(record.get("fields") or {}),
        }

    async def delete_record(self, table_key: str, record_id: str) -> None:
        """删除单条记录（测试数据清理用）。"""
        meta = self._table(table_key)
        await self._call(
            "DELETE",
            f"{BITABLE_BASE}/apps/{self._base_token(table_key)}"
            f"/tables/{meta.table_id}/records/{record_id}",
        )

    # ── 字段定义刷新（选项集缓存） ──

    async def refresh_table_fields(self, table_key: str) -> dict[str, Any]:
        """拉最新字段定义并刷新进程内选项集缓存（TTL 300s）。

        写前校验优先读该缓存，用于消化 Base 侧字段/选项变更，
        避免静态快照滞后。返回 {"table_key", "table_id", "field_count",
        "fields": {字段名: {"type": 类型码, "options": [选项]}}}。
        """
        meta = self._table(table_key)
        raw = await list_fields(
            self._base_token(table_key),
            meta.table_id,
            app_id=self._app_id,
            app_secret=self._app_secret,
        )
        parsed: dict[str, FieldMeta] = apply_runtime_fields(table_key, raw)
        return {
            "table_key": table_key,
            "table_id": meta.table_id,
            "field_count": len(parsed),
            "fields": {
                name: {"type": fm.type, "options": list(fm.options)}
                for name, fm in parsed.items()
            },
        }
