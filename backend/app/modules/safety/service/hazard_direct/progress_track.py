"""「未更新进展」跟踪 — 内容哈希 + Redis 记录首次出现时间（方案 B）。

背景：改造前的判定依赖 DB 字段 ``progress_note_updated_at``（同步在「目前进展」
内容变化时刷新）。直读多维表格后没有这个时间戳，改用 Redis 跟踪：

    key   : safety:hazard:progress:{record_id}
    value : {"hash": <目前进展文本 MD5>, "since": <该内容首次出现时间 ISO>}

判定：
- 内容变化 → since = now
- 内容未变 → 保留 since
- 内容为空 → 按「检查日期」起算（不写 Redis）
- 未关闭 + 整改中排除 + 督办中 + (now - since) > 7 天 → 标记「未更新进展」

冷启动基线：Redis 无该记录时，尝试读平台库 ``hazard_reports.progress_note_updated_at``
作为 since（历史时间戳仍在，避免上线后 7 天内全部漏标）；查不到则用 now。

Redis 不可用时降级为「按检查日期」判定（fail-open，宁少标不错标）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

from app.core.redis import redis_client
from app.modules.safety.service.hazard_direct import bitable_repo

logger = logging.getLogger(__name__)

PROGRESS_STALE_DAYS = 7
PROGRESS_STATUS_NOT_UPDATED = "未更新进展"
_KEY_PREFIX = "safety:hazard:progress:"
_KEY_TTL = 180 * 24 * 3600  # 180 天


def _key(record_id: str) -> str:
    return f"{_KEY_PREFIX}{record_id}"


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


async def _db_baseline(record_id: str) -> datetime | None:
    """从平台库取历史进展更新时间作为冷启动基线（只读，best-effort）。"""
    try:
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.modules.safety.models import HazardReport

        async with async_session_factory() as session:
            value = await session.scalar(
                select(HazardReport.progress_note_updated_at).where(
                    HazardReport.feishu_record_id == record_id
                )
            )
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    except Exception:
        logger.debug("读取进展基线失败（忽略）: record_id=%s", record_id, exc_info=True)
        return None


async def _since_for(record_id: str, text: str, now: datetime) -> datetime:
    """返回「当前进展内容首次出现时间」。"""
    key = _key(record_id)
    current_hash = _hash(text)
    try:
        raw = await redis_client.get(key)
    except Exception:
        raw = None

    if raw:
        try:
            data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
            data = {}
        if data.get("hash") == current_hash:
            try:
                return datetime.fromisoformat(data["since"])
            except (KeyError, ValueError):
                pass
        # 内容确实变化 → 重置基线，并回写新 hash/since，否则下一轮仍与旧 hash
        # 比对不上、永远返回 now，该记录会永久豁免「未更新进展」判定。
        await _persist(record_id, text, now)
        return now

    # 冷启动：优先用平台库的历史时间戳，避免上线后 7 天全部漏标
    since = await _db_baseline(record_id) or now
    try:
        await redis_client.set(
            key,
            json.dumps({"hash": current_hash, "since": since.isoformat()}),
            ex=_KEY_TTL,
        )
    except Exception:
        logger.debug("写入进展基线失败（忽略）: record_id=%s", record_id, exc_info=True)
    return since


async def _persist(record_id: str, text: str, since: datetime) -> None:
    """内容变化后回写基线（供下次比对）。"""
    try:
        await redis_client.set(
            _key(record_id),
            json.dumps({"hash": _hash(text), "since": since.isoformat()}),
            ex=_KEY_TTL,
        )
    except Exception:
        logger.debug("写入进展基线失败（忽略）: record_id=%s", record_id, exc_info=True)


async def compute_marks(
    views: list[bitable_repo.HazardView], *, now: datetime | None = None
) -> dict[str, str | None]:
    """批量计算「未更新进展」标记。

    Returns:
        {record_id: "未更新进展" | None}
    """
    base = now or datetime.now(UTC)
    stale = timedelta(days=PROGRESS_STALE_DAYS)
    out: dict[str, str | None] = {}

    for view in views:
        rid = view.record_id
        if not rid:
            continue
        # 仅督办中、未关闭、非整改中的记录参与
        if view.supervision_level not in ("红色预警", "一般预警"):
            out[rid] = None
            continue
        if view.rectification_status in ("closed", "in_progress"):
            out[rid] = None
            continue

        text = (view.progress_note or "").strip()
        if not text:
            # 从未填写进展 → 按检查日期起算
            if view.discovered_at is not None:
                discovered = (
                    view.discovered_at
                    if view.discovered_at.tzinfo
                    else view.discovered_at.replace(tzinfo=UTC)
                )
                out[rid] = (
                    PROGRESS_STATUS_NOT_UPDATED if base - discovered > stale else None
                )
            else:
                out[rid] = None
            continue

        since = await _since_for(rid, text, base)
        out[rid] = PROGRESS_STATUS_NOT_UPDATED if base - since > stale else None

    marked = sum(1 for v in out.values() if v)
    logger.info(
        "进展标记计算: 参与=%d 标记=%d 未标记=%d",
        len(out), marked, len(out) - marked,
    )
    return out


__all__ = [
    "PROGRESS_STALE_DAYS",
    "PROGRESS_STATUS_NOT_UPDATED",
    "compute_marks",
]
