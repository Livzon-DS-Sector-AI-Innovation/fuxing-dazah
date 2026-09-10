"""安全模块专属 Bitable（多维表格）API 客户端。

使用安全模块独立飞书应用凭证，不依赖 lark_oapi SDK。
提供记录 CRUD、附件下载等基础操作。
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.client import get_safety_tenant_token

logger = logging.getLogger(__name__)

# 安全模块独立读取 .env 中的 Bitable 配置（不经过全局 config.py）
_env_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
_app_env = os.getenv("APP_ENV", "development")
_env_path = _env_dir / f".env.{_app_env}"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"

# 飞书 Bitable 错误码：字段不存在（对目标表更新不存在的字段时返回）
# 属于良性/预期场景（如向无 article_no 字段的表回写编号），不应记为 ERROR 噪音
BITABLE_ERR_FIELD_NOT_FOUND = 1254045


class BitableQueryError(RuntimeError):
    """Bitable 查询失败（飞书返回非 0 code）。

    默认情况下 ``search_records`` 会把失败吞成空列表（历史行为，兼容事件同步等
    调用方）。直读多维表格的定时任务必须区分「查询失败」与「确实没有数据」，
    因此这些调用点传 ``strict=True``，让失败向上抛出，由调度器记为 failed 并重试/
    告警，而不是静默当成「无待处理记录」。
    """

    def __init__(self, code: int | str | None, msg: str | None) -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"Bitable 查询失败: code={code} msg={msg}")


def _build_attachment_extra(
    table_id: str,
    record_id: str,
    field_id: str,
    file_token: str,
) -> str:
    """构建高级权限多维表格附件下载的 extra 鉴权参数（URL-encoded JSON）。

    飞书要求格式：
    {"bitablePerm": {"tableId": "...", "attachments": {"fldXXX": {"recXXX": ["file_token"]}}}}
    与 `bitable_handler._build_attachment_extra` 保持同一结构（照片下载回退策略复用）。
    """
    import json as _json
    import urllib.parse as _urlparse

    payload = {
        "bitablePerm": {
            "tableId": table_id,
            "attachments": {
                field_id: {record_id: [file_token]},
            },
        },
    }
    return _urlparse.quote(_json.dumps(payload, separators=(",", ":")))


def _materialize_upload_path(file_path: str) -> tuple[Path, bool]:
    """解析上传源为本地可读文件，返回 (本地路径, 是否临时文件需清理)。

    兼容两种传入语义：
      - 本地文件（``resolve_local_path`` 三种约定命中）→ 原样返回，无需清理；
      - MinIO object key → 经 ``attachment_store.read_bytes`` 取字节写临时文件，
        上传后由调用方清理；读不到时抛出清晰异常。
    """
    from app.modules.safety.attachment_store import read_bytes, resolve_local_path

    local = resolve_local_path(file_path)
    if local is not None:
        return Path(local), False

    data = read_bytes(file_path)
    if data is None:
        raise FileNotFoundError(
            f"上传源不存在（本地与 MinIO 均未命中）: {file_path!r}"
        )
    suffix = os.path.splitext(file_path)[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
    finally:
        tmp.close()
    return Path(tmp.name), True


def _cleanup_upload_temp(path: Path, is_temp: bool) -> None:
    """清理上传临时文件（仅清理物化产生的临时文件，静默失败）。"""
    if not is_temp:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class SafetyBitableClient:
    """安全模块多维表格 API 客户端。"""

    def __init__(
        self,
        app_token: str | None = None,
        table_id: str | None = None,
    ) -> None:
        # 默认凭证延迟读 store（hazard/hazard 连接）：改表 ID 后新事件/回写立即用新值。
        # 未配置/停用时回退空串，保留现有降级分支语义。
        conn = store.get_connection("hazard", "hazard")
        if conn is not None and conn.status != "disabled":
            self.app_token = app_token or conn.app_token
            self.table_id = table_id or conn.table_id
        else:
            self.app_token = app_token or ""
            self.table_id = table_id or ""

    def _record_url(self, table_id: str | None = None, record_id: str = "") -> str:
        tid = table_id or self.table_id
        base = f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records"
        return f"{base}/{record_id}" if record_id else base

    async def _token(self) -> str:
        return await get_safety_tenant_token()

    async def _resolve_app_token(self, token: str) -> str:
        """获取真实 app_token（Drive API 上传时需要 parent_node）。

        飞书多维表格的 Drive 上传 API 需要 Bitable 的真实 node_token 作为 parent_node，
        这个 token 不同于环境变量里的 app_token（可能是分享链接标识）。
        """
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    node = data.get("data", {}).get("app", {}).get("app_token", "")
                    if node:
                        return node
        except Exception:
            pass
        return self.app_token

    async def get_record_shared_url(
        self, record_id: str, table_id: str | None = None,
    ) -> str:
        """获取记录分享链接（调用飞书 API，返回 /record/ 格式）。"""
        token = await self._token()
        tid = table_id or self.table_id
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(
                    f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records/batch_get",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"record_ids": [record_id], "with_shared_url": True},
                )
                data = resp.json()
                if data.get("code") == 0:
                    records = data.get("data", {}).get("records", [])
                    if records:
                        return records[0].get("shared_url", "")
        except Exception:
            logger.exception("获取 shared_url 失败: record_id=%s", record_id)
        return ""

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
                if data.get("code") == BITABLE_ERR_FIELD_NOT_FOUND:
                    logger.warning(
                        "Bitable update_record 字段不存在（跳过）: record_id=%s code=%s msg=%s",
                        record_id, data.get("code"), data.get("msg"),
                    )
                else:
                    logger.error(
                        "Bitable update_record 失败: record_id=%s code=%s msg=%s",
                        record_id, data.get("code"), data.get("msg"),
                    )
                return False
            logger.info("Bitable update_record 成功: record_id=%s fields=%s", record_id, list(fields.keys()))
            return True

    async def create_record(
        self,
        fields: dict[str, Any],
        table_id: str | None = None,
    ) -> dict | None:
        """创建单条记录。返回 {"record_id": "...", "shared_url": "..."} 或 None。"""
        token = await self._token()
        tid = table_id or self.table_id
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records",
                params={"with_shared_url": "true"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"fields": fields},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Bitable create_record 失败: code=%s msg=%s",
                    data.get("code"), data.get("msg"),
                )
                return None
            record = data.get("data", {}).get("record", {})
            shared_url = record.get("shared_url", "")
            logger.info(
                "Bitable create_record 成功: record_id=%s shared_url=%s fields=%s",
                record.get("record_id", ""), shared_url[:60], list(fields.keys()),
            )
            return {"record_id": record.get("record_id", ""), "shared_url": shared_url}

    async def delete_record(
        self,
        record_id: str,
        table_id: str | None = None,
    ) -> bool:
        """删除单条记录。返回是否成功。"""
        token = await self._token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.delete(
                self._record_url(table_id, record_id),
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Bitable delete_record 失败: record_id=%s code=%s msg=%s",
                    record_id, data.get("code"), data.get("msg"),
                )
                return False
            logger.info("Bitable delete_record 成功: record_id=%s", record_id)
            return True

    async def upload_drive_file(
        self, file_path: str, file_name: str,
    ) -> dict | None:
        """上传普通文件到飞书 Drive 根目录。返回 {"file_token": "...", "name": "..."} 或 None。

        与 `upload_media`（`parent_type=bitable_file` 媒体 token，需附件注册 + extra 才能下载）不同，
        `files/upload_all` + `parent_type=explorer`（无 parent_node，上传到应用 Drive 根）返回
        **Drive 普通文件 token**，可直接经 `download_drive_file`（`drive/v1/files/{token}/download`）下载。
        「岗位资料附件（人工）」字段存量为 `file/` 链接即此类 token，测试上传也走此路径。

        ``file_path`` 兼容本地路径与 MinIO object key（key 经 attachment_store 物化后上传）。
        """
        local_path, is_temp = _materialize_upload_path(file_path)
        try:
            token = await self._token()
            file_size = local_path.stat().st_size
            with open(local_path, "rb") as f:
                async with httpx.AsyncClient(timeout=120) as http:
                    resp = await http.post(
                        "https://open.feishu.cn/open-apis/drive/v1/files/upload_all",
                        headers={"Authorization": f"Bearer {token}"},
                        data={
                            "file_name": file_name,
                            "parent_type": "explorer",
                            "size": str(file_size),
                        },
                        files={"file": (file_name, f)},
                    )
        finally:
            _cleanup_upload_temp(local_path, is_temp)
        data = resp.json()
        if data.get("code") != 0:
            logger.error(
                "Bitable upload_drive_file 失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return None
        file_token = data.get("data", {}).get("file_token", "")
        logger.info(
            "upload_drive_file 成功: name=%s file_token=%s size=%d",
            file_name, file_token, file_size,
        )
        return {"file_token": file_token, "name": file_name} if file_token else None

    async def upload_media(
        self,
        file_path: str,
        file_name: str,
        parent_type: str = "bitable_file",
    ) -> dict | None:
        """上传文件到飞书 Drive。返回 {"file_token": "...", "name": "..."} 或 None。

        ``file_path`` 兼容本地路径与 MinIO object key（key 经 attachment_store 物化后上传）。
        """
        local_path, is_temp = _materialize_upload_path(file_path)
        try:
            token = await self._token()
            file_size = local_path.stat().st_size
            parent_node = await self._resolve_app_token(token)

            with open(local_path, "rb") as f:
                async with httpx.AsyncClient(timeout=120) as http:
                    resp = await http.post(
                        "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
                        headers={"Authorization": f"Bearer {token}"},
                        data={
                            "file_name": file_name,
                            "parent_type": parent_type,
                            "parent_node": parent_node,
                            "size": str(file_size),
                        },
                        files={"file": (file_name, f)},
                    )
        finally:
            _cleanup_upload_temp(local_path, is_temp)
        data = resp.json()
        if data.get("code") != 0:
            logger.error(
                "Bitable upload_media 失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return None
        file_token = data.get("data", {}).get("file_token", "")
        logger.info(
            "upload_media 成功: name=%s file_token=%s size=%d",
            file_name, file_token, file_size,
        )
        return {"file_token": file_token, "name": file_name} if file_token else None

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

    async def download_drive_file(self, file_token: str) -> bytes | None:
        """下载飞书 Drive 普通文件（`https://xxx.feishu.cn/file/{token}` 或裸 token）。

        与 Bitable 媒体附件（`drive/v1/medias/{token}/download`，需 extra/附件注册）不同，
        Drive 普通文件走 `drive/v1/files/{token}/download`，安全应用有访问权限即可下载
        （「岗位资料附件（人工）」字段存量为 `file/` 链接，即此类 token）。失败返回 None。
        """
        import asyncio

        token = await self._token()
        url = f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/download"
        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=120, follow_redirects=True,
                ) as http:
                    resp = await http.get(
                        url, headers={"Authorization": f"Bearer {token}"},
                    )
                    if resp.status_code == 200:
                        return resp.content
                    last_error = f"HTTP {resp.status_code}"
                    logger.warning(
                        "Bitable Drive 文件下载失败: file_token=%s status=%s body=%s (attempt %d/3)",
                        file_token, resp.status_code, (resp.text or "")[:200], attempt + 1,
                    )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Bitable Drive 文件下载异常: file_token=%s error=%s (attempt %d/3)",
                    file_token, exc, attempt + 1,
                )
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s 退避
        logger.error(
            "Bitable Drive 文件下载最终失败(3次重试耗尽): file_token=%s last_error=%s",
            file_token, last_error,
        )
        return None

    async def download_docx_raw(self, document_id: str) -> str | None:
        """经 docx raw_content API 取飞书云文档纯文本（`/docx/` 链接）。

        「岗位资料附件（人工）」字段可能粘贴飞书云文档链接（`https://xxx.feishu.cn/docx/{token}`），
        这类 token 走 drive/media 下载接口不可达（docx 不是普通文件/媒体附件），
        但 `docx/v1/documents/{id}/raw_content` 可直接返回文档纯文本。
        失败返回 None（调用方回退其他下载路径）。
        """
        import asyncio

        token = await self._token()
        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{document_id}/raw_content"
        )
        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=120, follow_redirects=True,
                ) as http:
                    resp = await http.get(
                        url, headers={"Authorization": f"Bearer {token}"},
                    )
                    data = resp.json()
                    if data.get("code") == 0:
                        content = (data.get("data") or {}).get("content") or ""
                        if content:
                            return content
                        last_error = "code=0 but empty content"
                    else:
                        last_error = f"code={data.get('code')} msg={data.get('msg')}"
                        logger.warning(
                            "Bitable docx raw_content 获取失败: document_id=%s code=%s "
                            "msg=%s (attempt %d/3)",
                            document_id, data.get("code"), data.get("msg"), attempt + 1,
                        )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Bitable docx raw_content 异常: document_id=%s error=%s (attempt %d/3)",
                    document_id, exc, attempt + 1,
                )
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s 退避
        logger.error(
            "Bitable docx raw_content 最终失败(3次重试耗尽): document_id=%s last_error=%s",
            document_id, last_error,
        )
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
        strict: bool = False,
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
        strict: True 时查询失败抛 ``BitableQueryError``；False（默认）时返回空结果
            （保持旧行为，仅供能容忍「失败=无数据」的调用方使用）
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

        # page_token 必须放在 URL query 参数中（放 body 会被飞书忽略，
        # 导致分页永远返回第一页、has_more 恒为 True，list_all_records 死循环）
        params: dict[str, str] = {"field_name_type": "name"}
        if page_token:
            params["page_token"] = page_token

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records/search",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                params=params,
                json=payload,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Bitable search_records 失败: %s", data.get("msg"))
                if strict:
                    raise BitableQueryError(data.get("code"), data.get("msg"))
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
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        """分页拉取全部匹配记录。

        返回 [{"record_id": "...", "fields": {...}}, ...]。
        自动处理分页，直至 has_more=false 或 page_token 为空。

        strict: 透传给 ``search_records``；True 时查询失败抛 ``BitableQueryError``，
        避免把「接口失败」误当成「没有记录」（定时任务静默漏发卡）。
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
                strict=strict,
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

    async def list_records_bounded(
        self,
        table_id: str | None = None,
        *,
        page_size: int = 100,
        max_records: int = 500,
        view_id: str | None = None,
    ) -> dict[str, Any]:
        """按上限分页读取记录（GET /records，保留 view_id 能力）。

        供 office_client.read_base_records 复用，行为与其原实现一致：
        - page_size 收敛到 [1, 100]
        - max_records 收敛到 >= 1，达到上限后截断并标记 truncated
        - 返回 {"records": [...], "total": ..., "has_more": ..., "truncated": ...}
        - 失败返回 {"error": "code=... msg=...", "records": [], ...}
        """
        token = await self._token()
        tid = table_id or self.table_id
        page_size = max(1, min(int(page_size), 100))
        max_records = max(1, int(max_records))

        url = f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/records"
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        has_more = False
        total: int | None = None
        truncated = False

        async with httpx.AsyncClient(timeout=30) as http:
            while len(records) < max_records:
                params: dict[str, Any] = {
                    "page_size": min(page_size, max_records - len(records)),
                    "field_name_type": "name",
                }
                if view_id:
                    params["view_id"] = view_id
                if page_token:
                    params["page_token"] = page_token

                resp = await http.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                data = resp.json()

                if data.get("code") != 0:
                    return {
                        "error": f"code={data.get('code')} msg={data.get('msg')}",
                        "records": records,
                        "total": total,
                        "has_more": has_more,
                        "truncated": truncated,
                    }

                payload = data.get("data") or {}
                page = payload.get("items") or []
                records.extend(page)
                total = payload.get("total", total)
                has_more = bool(payload.get("has_more"))
                page_token = payload.get("page_token")

                if len(records) >= max_records:
                    records = records[:max_records]
                    truncated = has_more or (
                        total is not None and total > max_records
                    )
                    break
                if not has_more or not page_token:
                    break

        return {
            "records": records,
            "total": total,
            "has_more": has_more,
            "truncated": truncated,
        }

    async def list_fields(self, table_id: str | None = None) -> list[dict[str, Any]]:
        """列出表格的所有字段（自动分页）。

        表字段可能超过单页上限（50/100），必须走分页；否则字段名 → field_id
        解析会因截断而找不到目标字段。
        """
        token = await self._token()
        tid = table_id or self.table_id
        all_items: list[dict[str, Any]] = []
        pt: str | None = None
        async with httpx.AsyncClient(timeout=15) as http:
            while True:
                params: dict[str, Any] = {"page_size": 100}
                if pt:
                    params["page_token"] = pt
                resp = await http.get(
                    f"{BITABLE_BASE}/apps/{self.app_token}/tables/{tid}/fields",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error("Bitable list_fields 失败: %s", data.get("msg"))
                    return all_items or []
                result = data.get("data", {})
                items = result.get("items", [])
                all_items.extend(items)
                if not result.get("has_more"):
                    break
                pt = result.get("page_token")
                if not pt:
                    break
        logger.info("Bitable list_fields 完成: %d 个字段", len(all_items))
        return all_items

    async def get_field_id_by_name(
        self, field_name: str, table_id: str | None = None,
    ) -> str | None:
        """按字段名查找 field_id（用于附件下载 extra 位权限定）。找不到返回 None。"""
        for f in await self.list_fields(table_id):
            if f.get("field_name") == field_name:
                return f.get("field_id")
        return None

    async def download_bitable_attachment(
        self,
        file_token: str,
        record_id: str,
        field_id: str,
        table_id: str | None = None,
    ) -> bytes | None:
        """下载 Bitable 附件（构建 bitablePerm extra 鉴权）。

        飞书对 `bitable_file` 类型媒体（upload_all parent_type=bitable_file 上传）要求
        下载时带 extra（含 tableId/attachments 位权限定），裸 token 会返回 400
        「Missing access token for bitable_file media」。与 `bitable_handler`
        照片下载回退策略一致：构建 extra → `download_attachment(token, extra)`。
        """
        extra = _build_attachment_extra(
            table_id or self.table_id, record_id, field_id, file_token,
        )
        return await self.download_attachment(file_token, extra=extra)

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
