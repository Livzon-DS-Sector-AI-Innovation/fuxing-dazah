"""安全模块专属 Bitable（多维表格）API 客户端。

使用安全模块独立飞书应用凭证，不依赖 lark_oapi SDK。
提供记录 CRUD、附件下载等基础操作。
"""

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.modules.safety.feishu.client import get_safety_tenant_token

logger = logging.getLogger(__name__)

# 安全模块独立读取 .env 中的 Bitable 配置（不经过全局 config.py）
_env_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
_app_env = os.getenv("APP_ENV", "development")
_env_path = _env_dir / f".env.{_app_env}"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

SAFETY_BITABLE_APP_TOKEN = os.getenv("SAFETY_FEISHU_BITABLE_APP_TOKEN", "")
SAFETY_BITABLE_HAZARD_TABLE_ID = os.getenv("SAFETY_FEISHU_BITABLE_HAZARD_TABLE_ID", "")

BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"


class SafetyBitableClient:
    """安全模块多维表格 API 客户端。"""

    def __init__(
        self,
        app_token: str | None = None,
        table_id: str | None = None,
    ) -> None:
        self.app_token = app_token or SAFETY_BITABLE_APP_TOKEN
        self.table_id = table_id or SAFETY_BITABLE_HAZARD_TABLE_ID

    def _record_url(self, table_id: str | None = None, record_id: str = "") -> str:
        tid = table_id or self.table_id
        base = f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records"
        return f"{base}/{record_id}" if record_id else base

    async def _token(self) -> str:
        return await get_safety_tenant_token()

    async def get_record(
        self, record_id: str, table_id: str | None = None,
        *, field_name_type: str = "name",
    ) -> dict[str, Any]:
        """获取单条记录。返回 fields dict。

        默认 field_name_type="name" 确保返回中文 field_name 作为 key，
        以兼容后续代码中的 _map_bitable_fields / _download_and_save_attachments。
        """
        token = await self._token()
        url = self._record_url(table_id, record_id)
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"field_name_type": field_name_type},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Bitable get_record 失败: code=%s msg=%s record_id=%s",
                    data.get("code"), data.get("msg"), record_id,
                )
                return {}
            fields = data.get("data", {}).get("record", {}).get("fields", {})
            logger.debug(
                "Bitable get_record 成功: record_id=%s fields=%d keys=%s",
                record_id, len(fields), list(fields.keys())[:10],
            )
            return fields

    async def update_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        table_id: str | None = None,
    ) -> bool:
        """更新单条记录的字段。返回是否成功。"""
        if not fields:
            return True
        token = await self._token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.put(
                self._record_url(table_id, record_id),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"fields": fields},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Bitable update_record 失败: record_id=%s code=%s msg=%s",
                    record_id, data.get("code"), data.get("msg"),
                )
                return False
            logger.info("Bitable update_record 成功: record_id=%s fields=%s", record_id, list(fields.keys()))
            return True

    async def download_attachment(
        self, file_token: str, extra: str | None = None,
    ) -> bytes | None:
        """下载附件内容。返回文件字节，失败返回 None。

        使用飞书 Drive API 下载 Bitable 附件。
        优先使用 extra（从 Bitable API 返回的 url 中提取）；若无 extra 则直接尝试。
        单次请求超时 120s，失败自动重试最多 3 次（指数退避）。
        """
        import asyncio

        token = await self._token()
        base_url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"

        async def _try_download(url: str) -> bytes | None:
            last_error = None
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(
                        timeout=120, follow_redirects=True,
                    ) as http:
                        resp = await http.get(
                            url,
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if resp.status_code == 200:
                            return resp.content
                        logger.warning(
                            "Bitable 下载附件失败: url=%s... status=%s body=%s (attempt %d/3)",
                            url[:100], resp.status_code, (resp.text or "")[:200], attempt + 1,
                        )
                        last_error = f"HTTP {resp.status_code}"
                except Exception as exc:
                    logger.warning(
                        "Bitable 下载附件异常: url=%s... error=%s (attempt %d/3)",
                        url[:100], exc, attempt + 1,
                    )
                    last_error = str(exc)

                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s 退避

            logger.error(
                "Bitable 下载附件最终失败(3次重试耗尽): url=%s... last_error=%s",
                url[:100], last_error,
            )
            return None

        # 1. 有 extra → 直接用 extra 下载
        if extra:
            result = await _try_download(f"{base_url}?extra={extra}")
            if result is not None:
                return result

        # 2. 无 extra → 直接下载
        result = await _try_download(base_url)
        if result is not None:
            return result

        logger.error("Bitable 下载附件最终失败: file_token=%s", file_token)
        return None

    async def download_attachment_from_url(self, download_url: str) -> bytes | None:
        """通过 Bitable API 返回的预签名 URL 下载附件。

        策略（依次尝试）：
        1. 带 Authorization header 请求（兼容 open.feishu.cn 域名）
        2. 不带 Authorization header 请求（兼容内部预签名 URL，auth 已内嵌在 query）
        3. 验证 Content-Type 是图片/文件，避免将 HTML 错误页误存为图片

        单次请求超时 120s，失败自动重试最多 3 次（指数退避）。
        """
        import asyncio

        token = await self._token()

        async def _try(headers: dict | None = None) -> bytes | None:
            h = headers if headers is not None else {}
            last_error = None
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(
                        timeout=120, follow_redirects=True,
                    ) as http:
                        resp = await http.get(download_url, headers=h)
                        if resp.status_code != 200:
                            logger.warning(
                                "Bitable URL 下载附件失败: url=%s... status=%s body=%s (attempt %d/3)",
                                download_url[:120], resp.status_code,
                                (resp.text or "")[:200], attempt + 1,
                            )
                            last_error = f"HTTP {resp.status_code}"
                            if attempt < 2:
                                await asyncio.sleep(2 ** attempt)
                            continue
                        content = resp.content
                        ct = resp.headers.get("content-type", "")
                        # 验证：拒绝空内容 或 明显是 JSON/HTML 错误响应
                        if not content:
                            logger.warning(
                                "Bitable URL 下载到空内容: url=%s... (attempt %d/3)",
                                download_url[:120], attempt + 1,
                            )
                            last_error = "Empty content"
                            if attempt < 2:
                                await asyncio.sleep(2 ** attempt)
                            continue
                        if ct.startswith("application/json") or ct.startswith("text/html"):
                            text = content[:500].decode(errors="replace")
                            logger.warning(
                                "Bitable URL 返回非文件内容(ct=%s): url=%s... body=%s (attempt %d/3)",
                                ct, download_url[:120], text, attempt + 1,
                            )
                            last_error = f"Bad content-type: {ct}"
                            if attempt < 2:
                                await asyncio.sleep(2 ** attempt)
                            continue
                        logger.debug(
                            "Bitable URL 下载成功: size=%d ct=%s url=%s...",
                            len(content), ct, download_url[:120],
                        )
                        return content
                except Exception as exc:
                    logger.warning(
                        "Bitable URL 下载异常: url=%s... error=%s (attempt %d/3)",
                        download_url[:120], exc, attempt + 1,
                    )
                    last_error = str(exc)
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)

            logger.error(
                "Bitable URL 下载最终失败(3次重试耗尽): url=%s... last_error=%s",
                download_url[:120], last_error,
            )
            return None

        # 策略1: 带 Authorization header
        result = await _try({"Authorization": f"Bearer {token}"})
        if result is not None:
            return result

        # 策略2: 不带 Authorization（预签名 URL 可能不需要）
        logger.info("Bitable URL 尝试无 Auth 下载: url=%s...", download_url[:120])
        result = await _try()
        if result is not None:
            return result

        return None

    async def search_records(
        self,
        table_id: str | None = None,
        *,
        filter_str: str | None = None,
        page_size: int = 100,
        page_token: str | None = None,
        automatic_fields: bool = False,
        filter_info: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """搜索记录。

        返回 {"items": [...], "has_more": bool, "page_token": str|None, "total": int|None}.

        filter_str: 字符串公式过滤（如 'CurrentValue.[状态]="待整改"'）
        filter_info: 结构化过滤（与 filter_str 互斥，优先使用 filter_info）
            格式: {"conjunction": "and",
                   "conditions": [{"field_name": "...", "operator": "...", "value": [...]}]}
        sort: 排序条件列表 [{"field_name": "字段名", "desc": true}]
            注意：飞书 search API 不支持对系统字段（修改时间等）排序
        automatic_fields: 是否返回系统字段
            （created_time, last_modified_time, created_by, last_modified_by）
        page_token: 分页游标，首次请求不传
        """
        token = await self._token()
        tid = table_id or self.table_id
        payload: dict[str, Any] = {"page_size": page_size}
        if filter_info:
            payload["filter"] = filter_info
        elif filter_str:
            payload["filter"] = filter_str
        if automatic_fields:
            payload["automatic_fields"] = True
        if sort:
            payload["sort"] = sort
        if page_token:
            payload["page_token"] = page_token

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records/search",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                params={"field_name_type": "name"},
                json=payload,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Bitable search_records 失败: %s", data.get("msg"))
                return {
                    "items": [], "has_more": False,
                    "page_token": None, "total": None,
                }
            result = data.get("data", {})
            return {
                "items": result.get("items", []),
                "has_more": result.get("has_more", False),
                "page_token": result.get("page_token"),
                "total": result.get("total"),
            }

    async def list_all_records(
        self,
        table_id: str | None = None,
        *,
        filter_str: str | None = None,
        filter_info: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        """分页拉取全部匹配记录。

        返回 [{"record_id": "...", "fields": {...}, ...}, ...]。
        自动处理分页，直至 has_more=false 或 page_token 为空。
        """
        all_items: list[dict[str, Any]] = []
        pt: str | None = None
        page_count = 0

        while True:
            page_count += 1
            result = await self.search_records(
                table_id=table_id,
                filter_str=filter_str,
                filter_info=filter_info,
                sort=sort,
                automatic_fields=automatic_fields,
                page_size=page_size,
                page_token=pt,
            )
            items = result.get("items", [])
            all_items.extend(items)
            logger.debug(
                "Bitable list_all_records page %d: %d items (total=%s, has_more=%s)",
                page_count, len(items), result.get("total"), result.get("has_more"),
            )

            if not result.get("has_more"):
                break
            pt = result.get("page_token")
            if not pt:
                break

        logger.info(
            "Bitable list_all_records 完成: %d 页 %d 条记录",
            page_count, len(all_items),
        )
        return all_items

    async def list_fields(self, table_id: str | None = None) -> list[dict[str, Any]]:
        """列出表格的所有字段。"""
        token = await self._token()
        tid = table_id or self.table_id
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/fields",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 50},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Bitable list_fields 失败: %s", data.get("msg"))
                return []
            return data.get("data", {}).get("items", [])

    async def create_field(
        self,
        field_name: str,
        field_type: int,
        table_id: str | None = None,
        *,
        property_: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建表格字段。返回创建的字段信息 dict，失败返回 {}。"""
        token = await self._token()
        tid = table_id or self.table_id
        payload: dict[str, Any] = {
            "field_name": field_name,
            "type": field_type,
        }
        if property_ is not None:
            payload["property"] = property_
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/fields",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Bitable create_field 失败: field=%s code=%s msg=%s",
                    field_name, data.get("code"), data.get("msg"),
                )
                return {}
            field = data.get("data", {}).get("field", {})
            logger.info("Bitable create_field 成功: %s (id=%s)", field_name, field.get("field_id"))
            return field

    async def update_field(
        self,
        field_id: str,
        table_id: str | None = None,
        *,
        field_name: str | None = None,
        field_type: int | None = None,
        property_: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """更新表格字段（名称、类型、属性）。返回更新后的字段 dict，失败返回 {}。"""
        token = await self._token()
        tid = table_id or self.table_id
        payload: dict[str, Any] = {}
        if field_name is not None:
            payload["field_name"] = field_name
        if field_type is not None:
            payload["type"] = field_type
        if property_ is not None:
            payload["property"] = property_
        if not payload:
            return {}
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.put(
                f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/fields/{field_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Bitable update_field 失败: field_id=%s code=%s msg=%s",
                    field_id, data.get("code"), data.get("msg"),
                )
                return {}
            field = data.get("data", {}).get("field", {})
            logger.info("Bitable update_field 成功: field_id=%s", field_id)
            return field

    async def list_tables(
        self,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出应用下的所有数据表。

        返回 [{"table_id": "...", "name": "...", "revision": 0}, ...]。
        自动处理分页。
        """
        token = await self._token()
        all_items: list[dict[str, Any]] = []
        pt = page_token

        async with httpx.AsyncClient(timeout=15) as http:
            while True:
                params: dict[str, Any] = {"page_size": page_size}
                if pt:
                    params["page_token"] = pt
                resp = await http.get(
                    f"{BITABLE_BASE}/apps/{self.app_token}/tables",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(
                        "Bitable list_tables 失败: code=%s msg=%s",
                        data.get("code"), data.get("msg"),
                    )
                    return []
                result = data.get("data", {})
                items = result.get("items", [])
                all_items.extend(items)
                if not result.get("has_more"):
                    break
                pt = result.get("page_token")
                if not pt:
                    break

        logger.info("Bitable list_tables 完成: %d 个表", len(all_items))
        return all_items
