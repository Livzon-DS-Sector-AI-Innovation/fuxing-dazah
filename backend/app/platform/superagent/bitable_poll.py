"""bitable_poll 内置源 —— Bitable 轮询的 Source 化（读位持久化，重启不重放不漏单）。

幂等设计（自写回声抑制的关键）：
- ``external_id = record_id:相关字段指纹`` —— 督办回写只改 last_modified 不改
  相关字段指纹 → 重拉同批自动 duplicate；相关字段真变 → 新指纹 → 新 Trigger
- 读位 ``last_modified_ms`` 水位：查询用 ``>=`` 水位（边界毫秒重叠重扫，
  依赖指纹去重），推进取批内最大值——只在所覆盖 Trigger 全部落库后（同事务）

依赖方向：平台不 import 业务 Bitable client——各应用在启动时
``register_bitable_fetcher(name, fn)`` 注入拉取函数（含表/筛选器绑定）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.platform.superagent.sources import PollResult, Source, TriggerDraft

logger = logging.getLogger(__name__)

BitableFetcher = Callable[[int], Awaitable[list[dict[str, Any]]]]

_BITABLE_FETCHERS: dict[str, BitableFetcher] = {}


def register_bitable_fetcher(name: str, fetcher: BitableFetcher) -> None:
    if name in _BITABLE_FETCHERS:
        raise ValueError(f"Duplicate bitable fetcher: {name}")
    _BITABLE_FETCHERS[name] = fetcher


def get_bitable_fetcher(name: str) -> BitableFetcher | None:
    return _BITABLE_FETCHERS.get(name)


def relevant_fingerprint(fields: dict[str, Any], relevant: list[str]) -> str:
    """相关字段指纹（字段名排序后稳定序列化 → sha1 前 16 hex）。

    纯函数：同字段值恒同指纹；未声明字段变化不影响（自写回声抑制）。
    """
    canonical = {
        name: _plain_value(fields.get(name))
        for name in sorted(relevant)
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _plain_value(value: Any) -> Any:
    """Bitable 富文本/结构值扁平化（[{"type":"text","text":"x"}] → "x"）。"""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or json.dumps(value, ensure_ascii=False, default=str))
    return value


class BitablePollSource(Source):
    """Bitable 轮询源（config 约定）：

    - ``fetcher``：注册的拉取函数名（应用侧注入，含表与筛选器绑定）
    - ``thread_prefix``：thread_key 前缀（如 "hazard"）
    - ``relevant_fields``：参与指纹的字段（决定何为「相关变化」）
    - ``effect_kind``：可选——落库 Trigger 后直派生该 kind 的 effect
      （无授权语义的自动回写类走直链；研判/任务链路是 1b/1c 的事）
    """

    kind = "bitable_poll"

    async def poll(
        self,
        session: Any,
        source_row: Any,
        cursors: dict[str, Any],
    ) -> PollResult:
        cfg = source_row.config or {}
        fetcher_name = cfg.get("fetcher", "")
        fetcher = get_bitable_fetcher(fetcher_name)
        if fetcher is None:
            logger.error("bitable_poll 源 %s 引用未注册 fetcher: %s", source_row.name, fetcher_name)
            return PollResult()

        prefix = cfg.get("thread_prefix") or source_row.name
        relevant = list(cfg.get("relevant_fields") or [])

        cursor_val = cursors.get("last_modified_ms")
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        if cursor_val in (None, ""):
            # 首见：登记基准零回溯（防启用瞬间全表洪泛；存量语义由应用侧首扫承接）
            return PollResult(rebase=True, cursor_updates={"last_modified_ms": now_ms})

        watermark = int(cursor_val)
        records = await fetcher(watermark)
        drafts: list[TriggerDraft] = []
        max_ms = watermark
        for rec in records:
            record_id = rec.get("record_id", "")
            if not record_id:
                continue
            fields = rec.get("fields") or {}
            lms = int(rec.get("last_modified_time") or 0)
            max_ms = max(max_ms, lms)
            fp = relevant_fingerprint(fields, relevant)
            drafts.append(TriggerDraft(
                external_id=f"{record_id}:{fp}",
                thread_key=f"bitable:{prefix}:{record_id}",
                actor={"id": record_id, "type": "bitable_record"},
                human=False,
                addressed=False,
                payload={
                    "record_id": record_id,
                    "fields": fields,
                    "last_modified_time": lms,
                    "fingerprint": fp,
                    "channel": {"kind": "bitable", "record_id": record_id},
                },
            ))

        cursor_updates = {"last_modified_ms": max_ms} if records else {}
        return PollResult(drafts=drafts, cursor_updates=cursor_updates)
