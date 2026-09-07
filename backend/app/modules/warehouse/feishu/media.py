"""仓储 Base 附件上传/下载 + im 图片资源下载（S2 ticket 04/05，spec 决策 3/8）。

upload_image：POST /open-apis/drive/v1/medias/upload_all（multipart，
parent_type=bitable_image + parent_node=目标 Base app_token——实测该参数
必传，缺省 material_receipt 的 Base，否则 1061044；WAREHOUSE_* 凭证的
tenant token）→ file_token；submit 时写入 material_receipt「外包装/厂家
报告单/送货单照片」附件列（fields 值形态 ``[{"file_token": ...}]``，
type=17 附件字段契约）。

download_attachment：GET /drive/v1/medias/{file_token}/download —— 自
scripts/build_recognition_dataset.py 的 AttachmentDownloader 抽取（票01
实测契约，2026-09-07）：下载**多维表格里的附件**必须携带 extra 查询参数
``{"bitablePerm": {"tableId": <表 id>}}``（声明 Base 权限上下文），否则
batch_get_tmp_download_url 静默返回空数组、直连 download 返 400；
下载失败重试 1 次（tenant token 失效场景）。

download_im_image（票05）：GET /open-apis/im/v1/messages/{message_id}/
resources/{file_key}?type=image —— 下载用户发到 im 会话的图片消息原图
（gateway 图片识别链路第一步，im:resource 权限已开通）。手机拍照多为
HEIC：内容经 :func:`sniff_image_format` 嗅探（magic 字节），非 jpeg/png
由调用方降级提示（vision 网关仅可靠支持这两种格式）。

传输层为 httpx 直发（platform feishu_request 仅支持 JSON body，multipart
不支持）；tenant token 复用 platform get_tenant_token（按凭证缓存）。
错误统一抛 :class:`WarehouseBitableError`（复用 bitable_schema 异常，
code 分类：飞书业务码 int / missing_credentials / empty_file /
no_file_token / network_error / download_failed）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.modules.warehouse.bitable_schema import TABLES, WarehouseBitableError
from app.platform.integrations.feishu.http import get_tenant_token

logger = logging.getLogger(__name__)

DRIVE_BASE = "https://open.feishu.cn/open-apis/drive/v1"
IM_BASE = "https://open.feishu.cn/open-apis/im/v1"

# 附件上传 parent_type（飞书「上传素材」API：bitable 图片素材类型）
PARENT_TYPE_BITABLE_IMAGE = "bitable_image"

# vision 识别可靠支持的图片格式（gateway 下载后嗅探，其余降级提示）
SUPPORTED_IMAGE_FORMATS: tuple[str, ...] = ("jpeg", "png")

# AsyncClient 按事件循环复用（pytest-asyncio 每测试新建 loop，仿 platform/http.py）
_client_cache: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def _get_http() -> httpx.AsyncClient:
    """按当前事件循环取共享 AsyncClient（连接保活；无 loop 时一次性客户端）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    client = _client_cache.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        _client_cache[loop] = client
    return client


def _credentials(app_id: str | None = None, app_secret: str | None = None) -> tuple[str, str]:
    """WAREHOUSE_* 凭证（参数优先，缺省 Settings）；缺失抛 missing_credentials。"""
    settings = get_settings()
    resolved_id = app_id or settings.WAREHOUSE_FEISHU_APP_ID
    resolved_secret = app_secret or settings.WAREHOUSE_FEISHU_APP_SECRET
    if not resolved_id or not resolved_secret:
        raise WarehouseBitableError(
            "缺少仓储飞书应用凭证（WAREHOUSE_FEISHU_APP_ID/SECRET），"
            "请在 env 配置或构造参数注入",
            code="missing_credentials",
        )
    return resolved_id, resolved_secret


async def upload_image(
    file_bytes: bytes,
    filename: str,
    *,
    parent_node: str | None = None,
) -> str:
    """上传图片到飞书素材（parent_type=bitable_image），返回 file_token。

    multipart 要素：file_name / parent_type / **parent_node** / size（须与
    字节数一致）/ file。实测契约（2026-09-07）：parent_type=bitable_image
    时 parent_node 必传且为**目标 Base 的 app_token**（素材挂到该 Base 名下），
    缺省取 material_receipt 的 Base——否则飞书返 1061044 parent node not
    exist。业务码非 0 / 响应缺 file_token 一律抛
    :class:`WarehouseBitableError`（code 保留飞书业务码）。
    """
    if not file_bytes:
        raise WarehouseBitableError("附件上传内容为空", code="empty_file")
    resolved_node = parent_node
    if not resolved_node:
        settings = get_settings()
        resolved_node = str(
            getattr(settings, TABLES["material_receipt"].base_token_setting, "") or ""
        )
    if not resolved_node:
        raise WarehouseBitableError(
            "附件上传缺少 parent_node（目标 Base app_token），"
            "且 Settings.WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN 为空",
            code="missing_credentials",
        )
    app_id, app_secret = _credentials()
    token = await get_tenant_token(app_id, app_secret)
    http = _get_http()
    try:
        resp = await http.post(
            f"{DRIVE_BASE}/medias/upload_all",
            data={
                "file_name": filename,
                "parent_type": PARENT_TYPE_BITABLE_IMAGE,
                "parent_node": resolved_node,
                "size": str(len(file_bytes)),
            },
            files={"file": (filename, file_bytes)},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        raise WarehouseBitableError(
            f"附件上传网络异常: {type(exc).__name__}", code="network_error"
        ) from exc
    if resp.status_code != 200:
        raise WarehouseBitableError(
            f"附件上传 HTTP {resp.status_code}: {resp.text[:200]}",
            code=resp.status_code,
        )
    try:
        data: dict[str, Any] = resp.json()
    except ValueError as exc:
        raise WarehouseBitableError(
            f"附件上传响应非 JSON: {resp.text[:200]}", code="bad_response"
        ) from exc
    if data.get("code") != 0:
        raise WarehouseBitableError(
            f"附件上传失败: code={data.get('code')} msg={data.get('msg')}",
            code=data.get("code"),
        )
    file_token = str((data.get("data") or {}).get("file_token") or "")
    if not file_token:
        raise WarehouseBitableError("附件上传响应缺少 file_token", code="no_file_token")
    logger.info(
        "附件上传成功: filename=%s size=%d file_token=%s",
        filename, len(file_bytes), file_token[:20],
    )
    return file_token


async def download_attachment(
    file_token: str,
    *,
    table_id: str | None = None,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> bytes:
    """下载 Base 附件字节（票01 实测契约：extra 携带 bitablePerm.tableId）。

    table_id 缺省 material_receipt（识别原图的来源表）；下载失败重试 1 次
    （token 失效场景，重试时经 get_tenant_token 缓存兜底），仍失败抛
    :class:`WarehouseBitableError`（code="download_failed"）。
    """
    resolved_table = table_id or TABLES["material_receipt"].table_id
    resolved_id, resolved_secret = _credentials(app_id, app_secret)
    extra = json.dumps({"bitablePerm": {"tableId": resolved_table}})
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            token = await get_tenant_token(resolved_id, resolved_secret)
            resp = await _get_http().get(
                f"{DRIVE_BASE}/medias/{file_token}/download",
                params={"extra": extra},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                raise WarehouseBitableError(
                    f"附件下载 HTTP {resp.status_code}: {resp.text[:200]}",
                    code=resp.status_code,
                )
            content = resp.content
            if not content:
                raise WarehouseBitableError("附件下载内容为空", code="empty_file")
            return content
        except Exception as exc:  # noqa: BLE001 — 单附件失败重试 1 次（票01 契约）
            last_error = exc
    raise WarehouseBitableError(
        f"附件下载失败（重试后仍失败）: {file_token}: {last_error}",
        code="download_failed",
    )


# ── 图片格式嗅探（magic 字节；scripts/build_recognition_dataset.py 同款契约）──


def sniff_image_format(content: bytes) -> str:
    """图片字节 → 格式名：jpeg/png/gif/bmp/webp/heic/unknown。

    手机拍照多为 HEIC（ISO BMFF 容器，magic = 4 偏移 ftyp 盒）；vision
    网关仅可靠支持 jpeg/png（``SUPPORTED_IMAGE_FORMATS``），调用方据此
    降级提示。
    """
    if not content or len(content) < 12:
        return "unknown"
    if content[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if content[:3] == b"GIF":
        return "gif"
    if content[:2] == b"BM":
        return "bmp"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    if content[4:8] == b"ftyp":  # ISO BMFF 容器：HEIC/HEIF/AVIF 等
        return "heic"
    return "unknown"


async def download_im_image(message_id: str, file_key: str) -> bytes:
    """下载 im 图片消息原图（票05：gateway 图片识别链路第一步）。

    GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=image
    （WAREHOUSE_* 凭证，im:resource 权限）。下载失败重试 1 次（tenant
    token 失效场景），仍失败抛 :class:`WarehouseBitableError`
    （code="download_failed"）。**不校验图片格式**——调用方经
    :func:`sniff_image_format` 嗅探后自行降级（便于区分网络失败与
    格式不支持两种话术）。
    """
    resolved_id, resolved_secret = _credentials()
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            token = await get_tenant_token(resolved_id, resolved_secret)
            resp = await _get_http().get(
                f"{IM_BASE}/messages/{message_id}/resources/{file_key}",
                params={"type": "image"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                raise WarehouseBitableError(
                    f"im 图片下载 HTTP {resp.status_code}: {resp.text[:200]}",
                    code=resp.status_code,
                )
            content = resp.content
            if not content:
                raise WarehouseBitableError("im 图片下载内容为空", code="empty_file")
            return content
        except Exception as exc:  # noqa: BLE001 — 单图片失败重试 1 次（token 失效场景）
            last_error = exc
    raise WarehouseBitableError(
        f"im 图片下载失败（重试后仍失败）: message_id={message_id} "
        f"file_key={file_key}: {last_error}",
        code="download_failed",
    )
