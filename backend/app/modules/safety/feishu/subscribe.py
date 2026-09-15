"""Bitable 文档事件订阅辅助（飞书要求：接收 Bitable 事件前必须先订阅文档）。

坑位说明（2026-09-11 排查结论）：
    wiki 挂载的多维表格，从知识库 URL 复制到的 app_token 实为 wiki 节点 token。
    Bitable 读写 API 直接接受 wiki token，但 **drive 文档订阅 API 不认**，报
    ``code=1069604 document not found``——文档在 drive 层不可见。

    解法：``GET /bitable/v1/apps/{token}`` 的响应 ``data.app.app_token`` 会回显
    底层真实 Base 的 app_token（wiki token 输入 → obj_token 输出；普通 Base 输入
    → 原值输出）。用回显值订阅即可成功，且事件 payload 的 file_token 与之一致。

各 ensure_*_subscribed() 统一经 :func:`subscribe_bitable_document_events` 订阅。
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

SUBSCRIBE_URL = "https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/subscribe"
BITABLE_APP_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"

# drive subscribe 对 wiki 节点 token 的报错码（document not found）
_DOCUMENT_NOT_FOUND = 1069604


async def resolve_canonical_app_token(
    http: httpx.AsyncClient, bearer: str, app_token: str
) -> str:
    """返回可被 drive 订阅 API 识别的底层 app_token。

    wiki 挂载表格 → 底层 Base 的 obj_token（经 bitable 元信息回显）；
    普通 Base → 原值。查询失败时返回原值（订阅自行报错，不在此处放大）。
    """
    try:
        resp = await http.get(
            BITABLE_APP_URL.format(app_token=app_token),
            headers={"Authorization": f"Bearer {bearer}"},
        )
        data = resp.json()
        canonical = ((data.get("data") or {}).get("app") or {}).get("app_token", "")
        if data.get("code") == 0 and canonical:
            if canonical != app_token:
                logger.info(
                    "app_token 为 wiki 节点 token，已解析底层 Base token: %s → %s",
                    app_token, canonical,
                )
            return canonical
        logger.warning(
            "bitable 元信息查询失败（code=%s msg=%s），按原 token 订阅: %s",
            data.get("code"), data.get("msg"), app_token,
        )
    except Exception:  # noqa: BLE001 — 解析失败不阻断订阅主流程
        logger.exception("bitable 元信息查询异常，按原 token 订阅: %s", app_token)
    return app_token


async def subscribe_bitable_document_events(
    bearer: str,
    app_token: str,
    *,
    label: str = "Bitable",
    file_type: str = "bitable",
) -> bool:
    """订阅一个多维表格文档的云文档事件（幂等，重复调用无害）。

    - token 为 wiki 节点 token 时自动解析底层 Base token 后订阅（见模块说明）；
    - 返回 True = 订阅成功；False = 失败（已记 ERROR 日志）。

    Args:
        bearer: tenant_access_token（调用方获取，多个文档订阅复用同一 token）
        app_token: 多维表格 app_token（wiki 节点 token 亦可）
        label: 日志前缀（如 "知识库" / "持证台账"）
        file_type: 订阅文件类型，固定 bitable
    """
    async with httpx.AsyncClient(timeout=15) as http:
        file_token = await resolve_canonical_app_token(http, bearer, app_token)
        resp = await http.post(
            SUBSCRIBE_URL.format(file_token=file_token),
            headers={"Authorization": f"Bearer {bearer}"},
            params={"file_type": file_type},
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info("%s 文档事件订阅成功: file_token=%s", label, file_token)
            return True
        logger.error(
            "%s 文档事件订阅失败: code=%s msg=%s file_token=%s",
            label, data.get("code"), data.get("msg"), file_token,
        )
        return False
