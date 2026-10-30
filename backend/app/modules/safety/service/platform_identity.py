"""3.x 平台身份卡（F3）— OH 个人档案第 6 源：单人平台身份解析。

匹配链（关联键=工号 > 姓名+部门；身份证键不可用，平台侧证件号恒空）：

  OH person（直读行/镜像行均可，duck-type .employee_no/.name/.department）
    ├─ employee_no 非空 → account/query(jobNo=)   ← 主路径，精确
    ├─ miss → account/query(nickname=name) → 多条时按 deptName==department 收窄
    │         仍多条/零条 → unmatched（P3：不猜测同名）
    └─ 命中 → user/detail(id) → 身份卡字段组

信封口径沿用 org_directory/contractor_workers 三态 + unmatched：
  live=本次（或 TTL 窗口内缓存）成功；degraded=平台失败回退缓存（保留时点）；
  empty=失败且无缓存；unmatched=平台可达但未唯一确定匹配（同样进缓存，
  避免同名未匹配者反复打平台）。

隐私：个人明细不落库、不打明细日志（仅计数/异常类名日志）；idCardNo
不出现在任何输出（平台侧本就恒空）。缓存=进程内按匹配入参组合键 TTL
（默认 600s，SAFETY_PLATFORM_IDENTITY_CACHE_TTL_SECONDS，对齐
contractor_workers 人员缓存窗口）；1400 主档全集不为此重拉。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.modules.safety.service.bitable_direct import gates

logger = logging.getLogger(__name__)

__all__ = [
    "PlatformIdentityService",
    "build_identity_person",
    "cache_ttl_seconds",
    "match_platform_user",
    "open_platform_identity_service",
]

STATUS_LIVE = "live"
STATUS_DEGRADED = "degraded"
STATUS_EMPTY = "empty"
STATUS_UNMATCHED = "unmatched"

BASIS_JOB_NO = "job_no"
BASIS_NAME_DEPT = "name_dept"


def cache_ttl_seconds() -> int:
    """身份卡进程内 TTL 缓存秒数（默认 600；0=关）。

    平台主档低频变动（HR 侧同步），10 分钟窗口内档案页刷新共用缓存，
    避免同一人反复 account/query + user/detail 双跳打平台。
    """
    return gates.int_env(
        "SAFETY_PLATFORM_IDENTITY_CACHE_TTL_SECONDS", 600, minimum=0
    )


def match_platform_user(
    person_fields: dict[str, str],
    account_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """从 account/query 结果行中挑出唯一确定的平台人员；不猜测。

    规则（P3）：零行 → None；一行 → 该行；多行 → 按
    deptName==person.department 收窄，收窄后仍非唯一 → None。
    注意实测 account/query 行内 deptName 恒空——同名多命中实际几乎
    必然收窄失败而放弃，属设计内的保守行为（宁可不匹配，不猜同名）。
    """
    rows = [r for r in account_rows if isinstance(r, dict)]
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    dept = str(person_fields.get("department") or "").strip()
    if dept:
        narrowed = [
            r for r in rows if str(r.get("deptName") or "").strip() == dept
        ]
        if len(narrowed) == 1:
            return narrowed[0]
    return None


def _clean(value: Any) -> str | None:
    text = str(value if value is not None else "").strip()
    return text or None


def build_identity_person(detail: dict[str, Any]) -> dict[str, Any]:
    """user/detail → 身份卡字段组（只投影展示字段；idCardNo 等敏感键一律不含）。"""
    raw_status = detail.get("status")
    status_text = _clean(raw_status)
    if status_text == "1":
        status_text = "在职"
    elif status_text == "0":
        status_text = "离职"
    return {
        "platform_id": str(detail.get("id") or "").strip(),
        "post_name": _clean(detail.get("postName")),
        "dept_name": _clean(detail.get("deptName")),
        "dept_whole_name": _clean(detail.get("deptWholeName")),
        "direct_leader": _clean(detail.get("directLeaderName")),
        "job_no": _clean(detail.get("jobNo")),
        "telephone": _clean(detail.get("telephone")),
        "email": _clean(detail.get("email")),
        "status": status_text,
        "entry_date": _clean(detail.get("entryDate")),
    }


def _person_fields(person: Any) -> dict[str, str]:
    """duck-type 抽取匹配入参（直读 OhRowView 与镜像 OhPerson 均适用）。"""
    return {
        "employee_no": str(getattr(person, "employee_no", None) or "").strip(),
        "name": str(getattr(person, "name", None) or "").strip(),
        "department": str(getattr(person, "department", None) or "").strip(),
    }


def _unmatched_payload(fetched_at: str) -> dict[str, Any]:
    return {
        "status": STATUS_UNMATCHED,
        "fetched_at": fetched_at,
        "match_basis": None,
        "person": None,
        "message": "平台未唯一确定匹配（同名多人或零命中，未自动匹配）",
    }


@dataclass
class _Entry:
    at: float
    payload: dict[str, Any]


def _copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """信封返回拷贝（与 org_directory/contractor_workers 口径一致），
    防消费方原地改写污染进程内共享缓存。"""
    copied = dict(payload)
    person = copied.get("person")
    if isinstance(person, dict):
        copied["person"] = dict(person)
    return copied


class PlatformIdentityService:
    """单人平台身份解析：匹配链 + 进程内 TTL 缓存 + 三态信封（client 可注入）。"""

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
        self._cache: dict[str, _Entry] = {}

    async def get_identity(self, person: Any) -> dict[str, Any]:
        """解析单人平台身份；信封自身不抛（平台失败→degraded/empty）。"""
        fields = _person_fields(person)
        key = "|".join(
            (fields["employee_no"], fields["name"], fields["department"])
        )
        now = self._clock()
        entry = self._cache.get(key)
        if self._ttl > 0 and entry and now - entry.at < self._ttl:
            return _copy_payload(entry.payload)
        try:
            payload = await self._resolve(fields)
        except Exception as exc:
            # 隐私红线：仅记异常类名，不打个人明细（姓名/工号不入日志）
            logger.warning("平台身份卡解析失败（不记个人明细）：%s", exc.__class__.__name__)
            if entry is not None:
                cached = entry.payload
                return _copy_payload({
                    "status": STATUS_DEGRADED,
                    "fetched_at": cached.get("fetched_at"),
                    "match_basis": cached.get("match_basis"),
                    "person": cached.get("person"),
                    "message": (
                        "3.x 平台接口暂不可用，当前展示缓存数据"
                        f"（缓存时点 {cached.get('fetched_at')}）"
                    ),
                })
            return {
                "status": STATUS_EMPTY,
                "fetched_at": None,
                "match_basis": None,
                "person": None,
                "message": "平台身份拉取失败且无缓存：3.x 平台接口暂不可用，请稍后重试",
            }
        self._cache[key] = _Entry(at=now, payload=payload)
        return _copy_payload(payload)

    async def _resolve(self, fields: dict[str, str]) -> dict[str, Any]:
        """匹配链 + 详情拉取。真实 client 每次解析新建、随用随关
        （平台 token 不跨缓存窗口长寿命复用，避免过期后信封恒 degraded）。"""
        client = self._client
        if client is None:
            from app.modules.safety.workticket_review.client import (
                WorkTicketPlatformClient,
            )

            async with WorkTicketPlatformClient() as owned:
                return await self._resolve_with(owned, fields)
        return await self._resolve_with(client, fields)

    async def _resolve_with(
        self, client: Any, fields: dict[str, str]
    ) -> dict[str, Any]:
        employee_no = fields["employee_no"]
        name = fields["name"]
        row: dict[str, Any] | None = None
        basis: str | None = None
        if employee_no:
            rows = await client.query_account({"jobNo": employee_no})
            row = match_platform_user(fields, rows)
            if row is not None:
                basis = BASIS_JOB_NO
        if row is None and name:
            rows = await client.query_account({"nickname": name})
            row = match_platform_user(fields, rows)
            if row is not None:
                basis = BASIS_NAME_DEPT
        platform_id = str(row.get("id") or "").strip() if row else ""
        if not platform_id:
            return _unmatched_payload(self._now_fn().isoformat())
        detail = await client.user_detail(platform_id)
        return {
            "status": STATUS_LIVE,
            "fetched_at": self._now_fn().isoformat(),
            "match_basis": basis,
            "person": build_identity_person(detail),
            "message": None,
        }


_service: PlatformIdentityService | None = None


def open_platform_identity_service() -> PlatformIdentityService:
    """进程内单例（profile 端点与后续消费方共用同一缓存实例）。"""
    global _service
    if _service is None:
        _service = PlatformIdentityService()
    return _service
