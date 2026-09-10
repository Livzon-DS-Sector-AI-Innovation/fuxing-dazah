"""危险源辨识自动化 Bitable 事件处理器。

Ticket 06：监听「危险源辨识自动化」多维表格变更事件，驱动平台 AI 脚本流转，
并维护平台镜像（HazardIdentification）。

事件 → 流程（spec.md §9）：
    record_added / record_edited → 读完整记录 → advance_record（判定 + AI 执行 + 回写映射）
        → 有回写字段则写 Bitable + 更新镜像
    record_deleted → 镜像软删除

防护（spec.md §9 / 铁律）：
    - 按 app_token + table_id 过滤目标表（防串表）
    - **状态级去重（60s 窗口）**：key = record_id:节点。节点推进后 key 变化 → 级联事件不被误去重；
      同一节点重复投递（飞书 at-least-once）→ 丢弃
    - **记录级互斥（120s）**：串行化同一记录的并发触发，防止重复 AI 调用
    - 事件处理器只做薄包装：client/service/redis/mirror 均可注入，测试用 fake

边界（spec.md §10）：
    - 平台只写 Bitable 的（AI）输出字段 + AI流程节点进度；绝不写（人工）/公式/人员字段
    - AI 流程不发飞书通知
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.modules.safety.ai_audit import ai_audit_scope
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.service.hazard_identification_bitable import _NODE_TO_SCRIPT

logger = logging.getLogger(__name__)


def _hazard_id_conn() -> ConnectionView | None:
    """危险源辨识连接配置（配置中心 store 读取；未启用/缺失返回 None）。"""
    return store.get_connection("hazard_id", "identification")


def _hazard_id_app_token() -> str:
    conn = _hazard_id_conn()
    return conn.app_token if conn and conn.enabled else ""


def _hazard_id_table_id() -> str:
    conn = _hazard_id_conn()
    return conn.table_id if conn and conn.enabled else ""

# 去重/互斥 Redis key 前缀
_DEDUP_PREFIX = "bitable:event:hazard_id"
_LOCK_PREFIX = "bitable:lock:hazard_id"

# 节点进度字段名（与 bitable_service 一致）
_NODE_FIELD = "AI流程节点进度"


@on_event("drive.file.bitable_record_changed_v1")
async def handle_hazard_id_record_changed(event: dict[str, Any]) -> None:
    """危险源辨识 Bitable 记录变更事件入口（薄包装，仅过滤 + 分发）。

    飞书 v2 payload（dispatch 已剥离信封，handler 直接收到内层数据）：
    {
        "file_token": "<app_token>", "table_id": "tblxxx",
        "action_list": [
            {"action": "record_added|record_edited|record_deleted", "record_id": "recxxx", ...}
        ]
    }
    """
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")

    # 过滤：仅处理目标 Bitable（防串表）
    if (
        file_token != _hazard_id_app_token()
        or table_id != _hazard_id_table_id()
    ):
        logger.debug("忽略非目标表事件: file_token=%s table_id=%s", file_token, table_id)
        return

    # ── v2 action_list 格式 ──
    action_list = event.get("action_list") or []
    if action_list:
        for item in action_list:
            record_id = item.get("record_id", "")
            action = item.get("action", "")
            if not record_id:
                logger.warning("危险源辨识 action_list 项缺少 record_id: action=%s", action)
                continue
            logger.info("危险源辨识 Bitable 事件: action=%s record_id=%s", action, record_id)
            try:
                if action == "record_deleted":
                    await _handle_delete(record_id)
                else:
                    await _handle_upsert(record_id)
            except Exception:
                logger.exception("处理危险源辨识 Bitable 事件失败: record_id=%s", record_id)
        return

    # ── 兼容旧 flat 格式 ──
    record_id = event.get("record_id", "")
    if not record_id:
        return
    action = event.get("action", "")
    logger.info("危险源辨识 Bitable 事件(flat): action=%s record_id=%s", action, record_id)
    try:
        if action == "record_deleted":
            await _handle_delete(record_id)
        else:
            await _handle_upsert(record_id)
    except Exception:
        logger.exception("处理危险源辨识 Bitable 事件失败: record_id=%s", record_id)


# ── 事件处理（可注入依赖，便于薄包装测试）──


async def _handle_upsert(
    record_id: str,
    *,
    client: Any | None = None,
    service: Any | None = None,
    redis: Any | None = None,
    mirror: Callable[[str, dict[str, Any]], Any] | None = None,
    attachment_parser: Callable[[str | dict], Any] | None = None,
) -> None:
    """事件入口：委托 advance_bitable_record（channel=system，保留去重）。"""
    await advance_bitable_record(
        record_id,
        client=client,
        service=service,
        redis=redis,
        mirror=mirror,
        attachment_parser=attachment_parser,
        channel="system",
    )


async def advance_bitable_record(
    record_id: str,
    *,
    client: Any | None = None,
    service: Any | None = None,
    redis: Any | None = None,
    mirror: Callable[[str, dict[str, Any]], Any] | None = None,
    attachment_parser: Callable[[str | dict], Any] | None = None,
    channel: str = "system",
    skip_dedup: bool = False,
) -> dict[str, Any]:
    """读记录 → 去重 → 互斥 → advance_record → 有回写则写 Bitable + 更新镜像。

    事件驱动与手动触发（API 兜底）共用同一路径（spec.md §9）。
    返回执行结果：
        {"status": "advanced", "next_node": str, "script": int | None}
        {"status": "noop", "reason": "empty_record|dedup|busy|completed|precondition", "message": str}

    注入点（测试用 fake，生产用默认）：
        client: 暴露 get_record / update_record 的飞书客户端（默认 SafetyBitableClient）
        service: 暴露 advance_record(fields) -> 回写 dict | None 的纯逻辑服务
        redis: 暴露 set/delete 的 Redis 客户端（默认 app.core.redis.redis_client）
        mirror: async (record_id, fields) -> None 的镜像 upsert（默认 _upsert_mirror）
        channel: 审计 channel（system=事件驱动 / web=手动触发）
        skip_dedup: 手动触发强制重试时跳过 60s 状态级去重（仍保留 120s 互斥）
    """
    from app.core.redis import redis_client
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    client = client or SafetyBitableClient(
        app_token=_hazard_id_app_token(), table_id=_hazard_id_table_id()
    )
    service = service or _build_service(attachment_parser=attachment_parser)
    redis = redis or redis_client
    mirror = mirror or _upsert_mirror

    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("危险源辨识 Bitable 记录读取为空: record_id=%s", record_id)
        return {"status": "noop", "reason": "empty_record", "message": "Bitable 记录读取为空"}

    # 状态级去重（60s）：同一节点+同一审核指纹重复投递 → 丢弃。
    # 审核指纹加入 key：审核驱动下脚本产出后节点不变，若人工在 60s 内审核通过，
    # 审核状态变化 → 指纹变化 → 去重键变化，保证「审核通过」事件不被误去重（否则对账永不触发）。
    node = _node_of(fields)
    if not skip_dedup and await _is_duplicate(
        record_id, node, _review_fingerprint(fields), redis=redis
    ):
        logger.info("危险源辨识事件去重命中，跳过: record_id=%s node=%s", record_id, node)
        return {"status": "noop", "reason": "dedup", "message": "同节点已在处理中，请稍后再试"}

    # 记录级互斥（120s）：串行化同一记录的并发触发，防止重复 AI 调用
    lock_key = f"{_LOCK_PREFIX}:advance:{record_id}"
    try:
        if not await redis.set(lock_key, "1", ex=120, nx=True):
            logger.info("危险源辨识记录互斥命中，跳过: record_id=%s", record_id)
            return {"status": "noop", "reason": "busy", "message": "该记录正在处理中，请稍后再试"}
    except Exception:
        logger.warning("Redis 不可用，跳过互斥", exc_info=True)
    try:
        with ai_audit_scope(
            scenario="hazard_id_bitable",
            channel=channel,
            resource_type="hazard_identification",
            extra={"bitable_record_id": record_id, "manual": channel == "web"},
        ):
            writeback = await service.advance_record(fields, record_id=record_id)
        if not writeback:
            # 无回写（未达触发条件/附件缺失/AI 失败）→ 仅镜像当前状态，不动 Bitable
            await mirror(record_id, fields)
            if node == "AI 流程结束":
                return {"status": "noop", "reason": "completed", "message": "AI 流程已结束，无脚本可执行"}
            return {
                "status": "noop",
                "reason": "precondition",
                "message": "当前节点前置条件不满足或 AI 执行未产出",
            }
        # 写回 Bitable（仅（AI）字段 + 节点进度，service 已强制边界）
        await client.update_record(record_id, writeback)
        fields.update(writeback)
        await mirror(record_id, fields)
        logger.info(
            "危险源辨识记录已推进: record_id=%s 节点=%s",
            record_id, writeback.get("AI流程节点进度"),
        )
        return {
            "status": "advanced",
            "next_node": writeback.get("AI流程节点进度") or node,
            "script": _NODE_TO_SCRIPT.get(node),
        }
    finally:
        try:
            await redis.delete(lock_key)
        except Exception:
            logger.warning("Redis 释放互斥失败", exc_info=True)


async def _handle_delete(
    record_id: str,
    *,
    mirror: Callable[[str], Any] | None = None,
) -> None:
    """record_deleted 事件 → 镜像软删除。"""
    from sqlalchemy import update

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardIdentification

    async def _default_mirror_delete(rid: str) -> None:
        async with async_session_factory() as session:
            await session.execute(
                update(HazardIdentification)
                .where(
                    HazardIdentification.feishu_record_id == rid,
                    HazardIdentification.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True)
            )
            await session.commit()

    mirror = mirror or _default_mirror_delete
    await mirror(record_id)


# ── 镜像维护 ──


def _build_service(attachment_parser: Callable[[str | dict], Any] | None = None) -> Any:
    """生产 service：纯逻辑服务 + 真实 run_script 适配器 + 真实附件解析器。"""
    from app.modules.safety.service.hazard_attachment_parser import (
        HazardAttachmentParser,
    )
    from app.modules.safety.service.hazard_identification_bitable import (
        HazardIdentificationBitableService,
    )
    from app.modules.safety.service.hazard_identification_runner import (
        HazardIdentificationScriptRunner,
    )

    # 附件解析器依赖 client（惰性构建，避免 import 时缺配置）
    def _make_attachment_parser() -> HazardAttachmentParser:
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        client = SafetyBitableClient(
            app_token=_hazard_id_app_token(), table_id=_hazard_id_table_id()
        )
        return HazardAttachmentParser(client)

    return HazardIdentificationBitableService(
        run_script=HazardIdentificationScriptRunner(),
        attachment_parser=attachment_parser or _make_attachment_parser(),
    )


async def _upsert_mirror(record_id: str, fields: dict[str, Any]) -> None:
    """Bitable 记录字段 → 平台 HazardIdentification 镜像 upsert（按 feishu_record_id 匹配）。"""
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardIdentification
    from app.modules.safety.service.hazard_identification_bitable import (
        map_bitable_to_model,
    )

    async with async_session_factory() as session:
        # Bitable 无「部门」字段 → 从提交人员派生（spec.md §5），派不到置空
        department = await _resolve_department_for_submitter(session, fields)
        mapped = map_bitable_to_model(
            fields,
            feishu_record_id=record_id,
            feishu_table_id=_hazard_id_table_id(),
            department=department,
        )
        # Bitable 无编号字段，镜像表 hazard_id_no NOT NULL → 由 record_id 派生
        mapped["hazard_id_no"] = f"HI-{record_id[-12:]}"
        stmt = select(HazardIdentification).where(
            HazardIdentification.feishu_record_id == record_id,
            HazardIdentification.is_deleted == False,  # noqa: E712
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            # 全字段镜像（含 None）：Bitable 字段被清空时镜像同步清空，避免残留旧值，
            # 与同步脚本（sync_hazard_id_bitable_to_platform.py）口径一致（spec.md §12）
            for k, v in mapped.items():
                if k not in ("feishu_record_id", "hazard_id_no"):
                    setattr(existing, k, v)
        else:
            session.add(HazardIdentification(**mapped))
        await session.commit()
        logger.info("危险源辨识镜像已同步: record_id=%s", record_id)


async def _resolve_department_for_submitter(
    session: Any, fields: dict[str, Any],
) -> str | None:
    """从 Bitable 提交人员姓名 → identity.users 部门（spec.md §5）。

    策略与 IdentityResolver._find_user_by_name 一致：精确匹配姓名，取第一条的部门；
    多人同名时无法消歧 → 返回 None（镜像置空，不阻塞同步）。
    """
    from sqlalchemy import select

    from app.modules.safety.service.hazard_identification_bitable import (
        _person_name,
    )

    submitter = _person_name(fields.get("提交人员"))
    if not submitter:
        return None
    from app.platform.identity.models import User as IdentityUser

    stmt = select(IdentityUser.department).where(
        IdentityUser.name == submitter,
        IdentityUser.is_deleted == False,  # noqa: E712
    )
    result = await session.execute(stmt)
    dept = result.scalars().first()
    return dept if dept else None


# ═══════════════════════════════════════════════════════════════
# 文档事件订阅
# ═══════════════════════════════════════════════════════════════

async def ensure_hazard_id_bitable_subscribed() -> bool:
    """订阅危险源辨识多维表格云文档事件（飞书要求先订阅才能收到 Bitable 事件）。"""
    if not _hazard_id_app_token():
        logger.info("危险源辨识 Bitable app_token 未配置，跳过文档事件订阅")
        return False
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{_hazard_id_app_token()}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info(
                    "危险源辨识 Bitable 文档事件订阅成功: file_token=%s",
                    _hazard_id_app_token(),
                )
                return True
            logger.error(
                "危险源辨识 Bitable 文档事件订阅失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return False
    except Exception:
        logger.exception("危险源辨识 Bitable 文档事件订阅异常")
        return False


# ── 辅助 ──


def _node_of(fields: dict[str, Any]) -> str:
    """提取记录当前节点进度（用于状态级去重）。"""
    raw = fields.get(_NODE_FIELD)
    if isinstance(raw, list):
        parts = [str(x.get("text", "") if isinstance(x, dict) else x) for x in raw]
        return "".join(parts).strip()
    if isinstance(raw, dict):
        return str(raw.get("text", "") or "").strip()
    return str(raw or "").strip()


def _review_fingerprint(fields: dict[str, Any]) -> str:
    """8 个脚本人工审核状态拼接指纹：任一审核状态变化 → 指纹变化（去重键变化）。

    审核驱动下脚本产出后节点不变，审核通过事件靠指纹区分于产出事件，避免 60s 误去重。
    """
    return "|".join(
        str(fields.get(f"脚本{i}（人工审核状态）") or "") for i in range(1, 9)
    )


async def _is_duplicate(
    record_id: str, node: str, fingerprint: str, ttl: int = 60, *, redis: Any | None = None,
) -> bool:
    """状态级 Redis 去重。返回 True 表示重复（TTL 窗口内同 record+节点+审核指纹只处理一次）。"""
    from app.core.redis import redis_client

    redis = redis or redis_client
    key = f"{_DEDUP_PREFIX}:{record_id}:{node or 'no-node'}:{fingerprint or 'no-fp'}"
    try:
        return not await redis.set(key, "1", ex=ttl, nx=True)
    except Exception:
        logger.warning("Redis 不可用，跳过去重", exc_info=True)
        return False
