"""采集源抽象与锅炉群消息实现（facilities-p2 票 03）。

TelemetrySourceAdapter：数据源出口的唯一抽象（DESIGN §5.1——将来锅炉上
数采出口，加 HTTP/网关实现，快照表与判定报警链全不变）。群消息实现为
本期唯一实现：im 消息列表 API 增量拉取（start_time 过滤 + 分页 + 升序），
游标持久化到 app_config（SAFETY_TELEMETRY_CURSOR），重启安全。

「since 上条 message_id」实现说明：im 列表 API 只支持时间过滤，不支持
message_id 定位——游标记录 (last_message_id, create_time)，拉取用
start_time=cursor 时间，同秒内已处理消息由 DB 侧 raw_message_id 防重
（at-least-once 语义，幂等落库兜底）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# 无游标时的回看窗口：首拉/游标丢失只回看 24h（更早历史不追）
DEFAULT_LOOKBACK_SECONDS = 24 * 3600


class TelemetrySourceError(RuntimeError):
    """源拉取失败（配置了源群但调不通：无权限/未进群/网络）。"""


@dataclass(frozen=True)
class SourceMessage:
    """归一化群消息（采集→解析的传递对象）。"""

    message_id: str
    sender_id: str
    sender_name: str
    msg_type: str            # text / image / file
    text: str | None         # 文本内容（text 消息）
    image_key: str | None    # 图片/文件 key（image/file 消息）
    create_time: datetime


class TelemetrySourceAdapter:
    """采集源出口抽象。实现须：升序返回新消息、不重复已游标过的批次。"""

    async def fetch_new_messages(self) -> list[SourceMessage]:
        raise NotImplementedError


def source_chat_id() -> str:
    """锅炉群 chat_id（空 = 未接入 → 采集 no_source）。"""
    from app.modules.safety.app_config.store import store

    return store.get_str("SAFETY_TELEMETRY_SOURCE_CHAT_ID", "")


def load_cursor() -> tuple[str, int] | None:
    """读游标 (last_message_id, create_time_epoch)。"""
    from app.modules.safety.app_config.store import store

    raw = store.get_str("SAFETY_TELEMETRY_CURSOR", "")
    if not raw or "|" not in raw:
        return None
    mid, _, ts = raw.rpartition("|")
    try:
        return mid, int(ts)
    except ValueError:
        return None


async def save_cursor(message_id: str, create_time_epoch: int) -> bool:
    """写游标（独立短会话 + 审计；失败仅告警——下轮重拉由幂等防重兜底）。"""
    try:
        from app.core.database import async_session_factory
        from app.modules.safety.app_config.store import store

        async with async_session_factory() as session:
            await store.set_value(
                session,
                "SAFETY_TELEMETRY_CURSOR",
                f"{message_id}|{create_time_epoch}",
                operator_name="telemetry_collector",
            )
            await session.commit()
        return True
    except Exception:
        logger.warning("采集游标写入失败（下轮将重拉，幂等防重兜底）", exc_info=True)
        return False


class GroupMessageSource(TelemetrySourceAdapter):
    """锅炉群消息实现（im 列表 API）。

    fetch_client 注入点供测试替换真实 lark 调用。
    """

    def __init__(
        self,
        chat_id: str,
        *,
        page_size: int = 50,
        lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS,
        fetch_client=None,
        now: datetime | None = None,
    ) -> None:
        self._chat_id = chat_id
        self._page_size = page_size
        self._lookback = lookback_seconds
        self._fetch_client = fetch_client
        self._now = now

    async def fetch_new_messages(self) -> list[SourceMessage]:
        cursor = load_cursor()
        now = self._now or datetime.now(UTC)
        start_ts = (
            cursor[1] if cursor
            else int(now.timestamp()) - self._lookback
        )
        fetcher = self._fetch_client or self._fetch_page
        messages: list[SourceMessage] = []
        page_token: str | None = None
        while True:
            items, page_token = await fetcher(start_ts, page_token)
            messages.extend(items)
            if not page_token or len(messages) >= 500:
                break
        messages.sort(key=lambda m: (m.create_time, m.message_id))
        return messages

    async def _fetch_page(
        self, start_ts: int, page_token: str | None
    ) -> tuple[list[SourceMessage], str | None]:
        """真实拉取一页（lark im/v1/messages 列表）。"""
        from app.modules.safety.feishu.client import (
            get_safety_feishu_client,
            get_safety_tenant_token,
        )
        from lark_oapi.api.im.v1 import ListMessageRequest

        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)
        builder = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(self._chat_id)
            .sort_type("ByCreateTimeAsc")
            .start_time(str(start_ts))
            .page_size(self._page_size)
        )
        if page_token:
            builder = builder.page_token(page_token)
        req = builder.build()
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.alist(req)
        if not resp.success():
            raise TelemetrySourceError(
                f"群消息拉取失败: code={resp.code} msg={resp.msg}"
            )
        items: list[SourceMessage] = []
        data = resp.data
        for m in getattr(data, "items", None) or []:
            try:
                msg = _to_source_message(m)
            except Exception:
                logger.warning(
                    "群消息归一失败跳过: message_id=%s",
                    getattr(m, "message_id", "?"), exc_info=True,
                )
                continue
            items.append(msg)
        next_token = getattr(data, "page_token", None) or None
        return items, next_token or None if getattr(data, "has_more", False) else None


def _to_source_message(m: object) -> SourceMessage:
    """lark message 对象 → 归一消息（text/image/file 三类）。"""
    import json

    msg_type = str(getattr(m, "msg_type", "") or "")
    if msg_type not in ("text", "image", "file"):
        raise ValueError(f"不支持的消息类型: {msg_type}")
    body = getattr(m, "body", None)
    content_raw = getattr(body, "content", None) if body is not None else None
    text: str | None = None
    resource_key: str | None = None
    if content_raw:
        try:
            content = json.loads(content_raw)
        except (json.JSONDecodeError, TypeError):
            content = {}
        if msg_type == "text":
            text = str(content.get("text", "") or "")
        else:
            resource_key = (
                content.get("image_key") or content.get("file_key") or None
            )
    sender = getattr(m, "sender", None)
    sender_id = str(getattr(sender, "id", "") or "") if sender is not None else ""
    sender_type = str(getattr(sender, "sender_type", "") or "") if sender is not None else ""
    if sender_type == "app" or not sender_id:
        raise ValueError("机器人/空发送人消息跳过")
    create_time = datetime.fromtimestamp(int(getattr(m, "create_time", "0")), tz=UTC)
    return SourceMessage(
        message_id=str(getattr(m, "message_id", "") or ""),
        sender_id=sender_id,
        sender_name="",  # lark 消息体不含发送人姓名（需另查通讯录，暂留空）
        msg_type=msg_type,
        text=text,
        image_key=resource_key,
        create_time=create_time,
    )
