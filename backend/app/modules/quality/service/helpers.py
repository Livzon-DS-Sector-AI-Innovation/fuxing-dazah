"""Quality 业务逻辑编排。"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# fire-and-forget 后台任务集合：持引用防 GC 回收（CPython 官方警告场景），
# 完成后自动移除；异常只记日志不向调用方冒泡
_BG_TASKS: set[asyncio.Task] = set()


def spawn_background(coro) -> None:
    """以 fire-and-forget 方式调度后台任务（飞书推送等不阻塞主流程的场景）。"""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BG_TASKS.discard(t)
        if not t.cancelled():
            exc = t.exception()  # 必须取一次，避免「Task exception was never retrieved」告警
            if exc:
                logger.exception("后台任务异常: %s", exc)

    task.add_done_callback(_done)


def _norm_date_str(s: str | None) -> str | None:
    """日期字符串分隔符归一化：2026.01.01 / 2026/01/01 → 2026-01-01。"""
    if not s:
        return None
    return s.strip().replace(".", "-").replace("/", "-")


@dataclass(frozen=True)
class ParserEntry:
    """解析器注册条目。"""

    name: str  # 产品名称（如"盐酸万古霉素"）
    description: str  # 简介


# 解析器注册表：后续新增产品在此注册
# 当前只有盐酸万古霉素，使用默认解析器
PARSER_REGISTRY: dict[str, ParserEntry] = {
    "盐酸万古霉素": ParserEntry(
        name="盐酸万古霉素",
        description="USP 标准（EX-HA-5246-001），支持 EP/CP 扩展",
    ),
}
