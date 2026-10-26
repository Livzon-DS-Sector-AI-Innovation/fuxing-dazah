"""岗位字典（3.x 平台全员主档去重，F1）。

人源字典，不是个人主数据：平台主档 idCardNo 恒空，个人级强匹配不可行，
dazah 人员主数据仍在飞书（hr/oh/持证表）。本模块只产出岗位维度清单
（postName 分组 × deptName 聚合 + 人数），个人明细不落库不返回（隐私）。

通道：WorkTicketPlatformClient.list_org_users() 全量（~1400 人）→
build_post_rows 纯函数去重 → 日级 TTL 进程内缓存（独立于
contractor_workers 的 10 分钟人员缓存）。信封三态口径同
contractor_workers：live / degraded（缓存时点）/ empty。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.modules.safety.service.bitable_direct import gates

logger = logging.getLogger(__name__)

__all__ = [
    "OrgPostsService",
    "build_post_rows",
    "cache_ttl_seconds",
    "open_org_posts_service",
]

STATUS_LIVE = "live"
STATUS_DEGRADED = "degraded"
STATUS_EMPTY = "empty"


def build_post_rows(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """主档内存行 → 岗位字典行（postName 分组、deptName 聚合、人数）。

    空 postName 跳过（无岗位信息不进字典）；只输出岗位维度字段，
    任何个人级字段（姓名/工号/账号）不得出现在输出里。
    """
    grouped: dict[str, dict[str, Any]] = {}
    for user in users:
        post = str(user.get("postName") or "").strip()
        if not post:
            continue
        dept = str(user.get("deptName") or "").strip()
        entry = grouped.setdefault(
            post, {"post_name": post, "_depts": set(), "_count": 0}
        )
        entry["_count"] += 1
        if dept:
            entry["_depts"].add(dept)
    return [
        {
            "post_name": post,
            "dept_names": sorted(entry["_depts"]),
            "headcount": entry["_count"],
        }
        for post, entry in sorted(grouped.items())
    ]


def cache_ttl_seconds() -> int:
    """岗位字典进程内 TTL 缓存秒数（默认 86400=日级；0=关）。

    组织岗位变动极低频，日级窗口足够；Agent 与页面共用单例。
    """
    return gates.int_env(
        "SAFETY_ORG_DIRECTORY_CACHE_TTL_SECONDS", 86_400, minimum=0
    )


@dataclass
class _Entry:
    at: float
    posts: list[dict[str, Any]]
    fetched_at: str


class OrgPostsService:
    """全员主档 → 岗位字典：日级 TTL 缓存 + 三态信封（client 可注入）。"""

    def __init__(
        self,
        *,
        client: Any = None,
        ttl_seconds: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._ttl = int(ttl_seconds if ttl_seconds is not None else cache_ttl_seconds())
        self._clock = clock
        self._now_fn = now_fn or (lambda: datetime.now().astimezone())
        self._entry: _Entry | None = None

    async def get_payload(
        self, *, dept: str | None = None, keyword: str | None = None
    ) -> dict[str, Any]:
        """岗位字典（可按部门/关键词过滤；过滤不重拉，走同一缓存）。"""
        now = self._clock()
        if not (self._ttl > 0 and self._entry and now - self._entry.at < self._ttl):
            try:
                client = _real_client() if self._client is None else self._client
                users = await client.list_org_users()
            except Exception:
                logger.exception("全员主档拉取失败（岗位字典）")
                if self._entry is not None:
                    entry = self._entry
                    return {
                        "status": STATUS_DEGRADED,
                        "fetched_at": entry.fetched_at,
                        "message": (
                            "全员主档拉取失败，当前展示缓存数据"
                            f"（缓存时点 {entry.fetched_at}）"
                        ),
                        "posts": list(entry.posts),
                    }
                return {
                    "status": STATUS_EMPTY,
                    "fetched_at": None,
                    "message": "岗位字典拉取失败且无缓存：3.x 平台接口暂不可用，请稍后重试",
                    "posts": [],
                }
            posts = build_post_rows(users)
            fetched_at = self._now_fn().isoformat()
            self._entry = _Entry(at=now, posts=posts, fetched_at=fetched_at)
            logger.info("岗位字典构建完成: posts=%d（主档 %d 人）", len(posts), len(users))

        entry = self._entry
        assert entry is not None
        posts = _filter_posts(entry.posts, dept=dept, keyword=keyword)
        return {
            "status": STATUS_LIVE,
            "fetched_at": entry.fetched_at,
            "message": None,
            "posts": posts,
        }


def _filter_posts(
    posts: list[dict[str, Any]],
    *,
    dept: str | None,
    keyword: str | None,
) -> list[dict[str, Any]]:
    dept_kw = (dept or "").strip()
    post_kw = (keyword or "").strip()
    result = posts
    if dept_kw:
        result = [p for p in result if any(dept_kw in d for d in p["dept_names"])]
    if post_kw:
        result = [p for p in result if post_kw in p["post_name"]]
    return result


def _real_client() -> Any:
    """真实平台 client 惰性装配（避免模块导入期建连；注入替身则不触发）。"""
    from app.modules.safety.workticket_review.client import WorkTicketPlatformClient

    return WorkTicketPlatformClient()


_service: OrgPostsService | None = None


def open_org_posts_service() -> OrgPostsService:
    """进程内单例（org-posts 端点与 Agent 工具共用同一缓存实例）。"""
    global _service
    if _service is None:
        _service = OrgPostsService()
    return _service
