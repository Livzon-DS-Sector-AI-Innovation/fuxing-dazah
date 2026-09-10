"""office_client 多维表格（Bitable）资源方法。

读取记录复用 SafetyBitableClient（安全模块专属 Bitable 客户端），
创建应用 / 表 / 字段走统一 _post helper。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.office_client._base import OfficeResult

logger = logging.getLogger(__name__)


class _BitableOfficeMixin:
    """Bitable 读取与创建。"""

    async def read_base_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int = 100,
        max_records: int = 500,
        view_id: str | None = None,
    ) -> OfficeResult:
        """读取多维表格（Bitable）记录。"""
        try:
            client = SafetyBitableClient(app_token=app_token)
            result = await client.list_records_bounded(
                table_id=table_id,
                page_size=page_size,
                max_records=max_records,
                view_id=view_id,
            )
            if result.get("error"):
                return OfficeResult.failure(
                    f"读取多维表格记录失败：{result['error']}"
                )

            records = result.get("records") or []
            return OfficeResult.data(
                records,
                truncated=bool(result.get("truncated")),
                meta={
                    "app_token": app_token,
                    "table_id": table_id,
                    "total": result.get("total"),
                    "returned_records": len(records),
                    "has_more": result.get("has_more"),
                },
            )
        except Exception as exc:
            return self._failure("读取多维表格记录", exc)

    async def create_base(
        self,
        title: str,
        *,
        folder_token: str | None = None,
        tables: list[dict[str, Any]] | None = None,
    ) -> OfficeResult:
        """创建多维表格（Bitable），可选建表/字段。"""
        try:
            body: dict[str, Any] = {"name": title}
            if folder_token:
                body["folder_token"] = folder_token

            resp = await self._post(
                f"{self._base_url}/bitable/v1/apps", json=body, timeout=60,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"创建多维表格失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            app = (data.get("data") or {}).get("app") or {}
            app_token = app.get("app_token") or ""
            if not app_token:
                return OfficeResult.failure("创建多维表格成功但未返回 app_token")

            url = app.get("url") or self._file_url(app_token, "bitable")
            result = OfficeResult.link(
                url, file_token=app_token, message=f"已创建多维表格《{title}》",
            )

            if tables:
                table_count = 0
                field_count = 0
                for spec in tables:
                    if not isinstance(spec, dict):
                        continue
                    table_id = await self._create_base_table(app_token, spec)
                    if not table_id:
                        continue
                    table_count += 1
                    fields = spec.get("fields") or []
                    field_count += await self._create_base_fields(
                        app_token, table_id, fields,
                    )
                result.message = (
                    f"已创建多维表格《{title}》，含 {table_count} 张数据表、"
                    f"{field_count} 个字段"
                )
            return result
        except Exception as exc:
            return self._failure("创建多维表格", exc)

    async def _create_base_table(
        self,
        app_token: str,
        spec: dict[str, Any],
    ) -> str | None:
        """在 Bitable 内创建数据表，返回 table_id。失败返回 None。"""
        try:
            name = spec.get("name") or spec.get("table_name") or "数据表"
            resp = await self._post(
                f"{self._base_url}/bitable/v1/apps/{app_token}/tables",
                json={"table": {"name": name}},
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "创建 Bitable 数据表失败: code=%s msg=%s",
                    data.get("code"),
                    data.get("msg"),
                )
                return None
            return ((data.get("data") or {}).get("table") or {}).get("table_id")
        except Exception as exc:
            logger.warning("创建 Bitable 数据表异常: %s", exc)
            return None

    async def _create_base_fields(
        self,
        app_token: str,
        table_id: str,
        fields: list[dict[str, Any]],
    ) -> int:
        """批量创建 Bitable 字段，返回成功字段数。"""
        created = 0
        for field in fields:
            if not isinstance(field, dict):
                continue
            body = {
                "field_name": field.get("field_name") or field.get("name"),
                "type": field.get("type", 1),
            }
            if not body["field_name"]:
                continue
            try:
                resp = await self._post(
                    f"{self._base_url}/bitable/v1/apps/{app_token}"
                    f"/tables/{table_id}/fields",
                    json=body,
                    timeout=30,
                )
                data = resp.json()
                if data.get("code") == 0:
                    created += 1
                else:
                    logger.warning(
                        "创建 Bitable 字段失败: field=%s code=%s msg=%s",
                        body["field_name"],
                        data.get("code"),
                        data.get("msg"),
                    )
            except Exception as exc:
                logger.warning("创建 Bitable 字段异常: %s", exc)
        return created
