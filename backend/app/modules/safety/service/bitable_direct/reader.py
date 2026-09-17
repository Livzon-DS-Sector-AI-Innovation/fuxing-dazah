"""底座读取协议与批量分页实现（禁止逐条读）。

职责：

1. 定义 page 级协议 BitablePageClient 与 domain 级协议 BitableRecordsReader，
   两者都只暴露批量查询；测试可注入替身。
2. fetch_all_records 按 has_more / page_token 分页取完，带页数上限保护；
   只请求 field_names 里的字段，减小返回体积。
3. resolve_client / open_reader 从 bitable_config.store 解析连接；
   未配置或已停用时抛 BitableConfigError，绝不静默返回空结果。
4. API 返回非 0 code 时统一抛底座 BitableQueryError，信息包含 code 与 msg。

实测约束（写进实现）：

- 单条读（get_record / batch_get）实测 4.4 至 5.6 秒且高频 Data not ready，
  因此底座只走批量 search 接口，不提供任何逐条读入口。
- page_token 必须放 URL query（客户端已处理）；本模块只消费 has_more / page_token。
- search 单页上限 500；超过页数上限抛错，绝不静默截断。

本模块不做业务字段语义，不 import 任何域包。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_client import (
    BitableQueryError as ClientQueryError,
)
from app.modules.safety.feishu.bitable_client import (
    SafetyBitableClient,
)
from app.modules.safety.service.bitable_direct import fields
from app.modules.safety.service.bitable_direct.errors import (
    BitableConfigError,
    BitableQueryError,
)

logger = logging.getLogger(__name__)

# 飞书 search 接口单页上限（超过会被 API 拒绝）
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 500

# 页数上限：防 page_token 未推进导致死循环；超过即抛错，绝不静默截断
DEFAULT_MAX_PAGES = 100


class BitablePageClient(Protocol):
    """page 级读取协议（真实实现为 SafetyBitableClient，单测注入替身）。

    只暴露批量 search；协议里没有也不需要任何单条读方法。
    """

    async def search_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_token: str | None = None,
        strict: bool = True,
    ) -> dict[str, Any]: ...


class BitableRecordsReader(Protocol):
    """domain 级读取协议：一次调用返回窗口内全部记录（内部自动分页）。"""

    async def list_all_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = DEFAULT_PAGE_SIZE,
        strict: bool = True,
    ) -> list[dict[str, Any]]: ...


async def _search_page(
    client: BitablePageClient,
    *,
    table_id: str | None,
    filter_info: dict[str, Any] | None,
    field_names: list[str] | None,
    sort: list[dict[str, Any]] | None,
    automatic_fields: bool,
    page_size: int,
    page_token: str | None,
) -> dict[str, Any]:
    """取一页；把客户端异常统一翻译成底座 BitableQueryError（含 code 与 msg）。"""
    try:
        return await client.search_records(
            table_id=table_id,
            filter_info=filter_info,
            field_names=field_names,
            sort=sort,
            automatic_fields=automatic_fields,
            page_size=page_size,
            page_token=page_token,
            strict=True,
        )
    except BitableQueryError:
        raise
    except ClientQueryError as exc:
        raise BitableQueryError(
            f"Bitable 查询失败: code={exc.code} msg={exc.msg}"
        ) from exc


async def fetch_all_records(
    client: BitablePageClient,
    *,
    table_id: str | None = None,
    filter_info: dict[str, Any] | None = None,
    field_names: Sequence[str] | None = None,
    sort: list[dict[str, Any]] | None = None,
    automatic_fields: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """分页拉取全部匹配记录（批量 search，逐条读一律禁止）。

    - field_names 透传给 API，只请求需要的字段
    - page_size 收敛到 [1, 500]；max_pages 收敛到 >= 1
    - strict=True（默认）时 API 失败向上抛底座 BitableQueryError；
      strict=False 时按旧口径返回已拉到的部分（兼容既有非严格调用方，新代码不该用）
    - 超过 max_pages 仍未拉完 -> 抛 BitableQueryError，绝不静默截断
    - has_more=True 但 page_token 为空 -> 视为 API 异常并抛错（避免悄悄少拉）
    """
    effective_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    effective_max = max(1, int(max_pages))
    names = list(field_names) if field_names is not None else None

    records: list[dict[str, Any]] = []
    page_token: str | None = None

    for page_no in range(1, effective_max + 1):
        try:
            result = await _search_page(
                client,
                table_id=table_id,
                filter_info=filter_info,
                field_names=names,
                sort=sort,
                automatic_fields=automatic_fields,
                page_size=effective_size,
                page_token=page_token,
            )
        except BitableQueryError:
            if strict:
                raise
            logger.warning(
                "Bitable 查询失败，strict=False 返回已拉取记录: page=%d records=%d",
                page_no,
                len(records),
            )
            return records

        items = result.get("items") or []
        records.extend(items)
        logger.debug(
            "Bitable 分页: page=%d items=%d records=%d has_more=%s",
            page_no,
            len(items),
            len(records),
            result.get("has_more"),
        )

        if not result.get("has_more"):
            return records
        next_token = result.get("page_token")
        if not next_token:
            raise BitableQueryError(
                "Bitable 分页异常: has_more=True 但 page_token 为空"
                f"（已拉取 {len(records)} 条）"
            )
        page_token = str(next_token)

    raise BitableQueryError(
        f"Bitable 分页超过上限 max_pages={effective_max}"
        f"（已拉取 {len(records)} 条），疑似 page_token 未推进"
    )


async def fetch_window_records(
    client: BitablePageClient,
    *,
    time_field: str,
    start: datetime,
    end: datetime,
    table_id: str | None = None,
    filter_info: dict[str, Any] | None = None,
    field_names: Sequence[str] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    automatic_fields: bool = False,
) -> list[dict[str, Any]]:
    """按时间字段倒序分页，取回落在 [start, end) 内的记录（见到更早的即停）。

    为什么这样取：Bitable 的日期过滤只有 ExactDate（天粒度、没有区间算子），
    逐天查询会让「默认 30 天」变成 30 次请求；按时间倒序 + 提前终止后，
    单页 500 条通常就覆盖完一个月的窗口。

    约定：
    - time_field 必须是可排序的业务日期字段（系统字段不能排序）；
    - filter_info 只能放与窗口正交的条件（放日期条件会让提前终止不成立）；
    - 时间字段为空或无法解析的记录不参与窗口判定、也不会被返回
      （与旧「按天过滤」行为一致：它们本来就进不了任何窗口）；
    - 页数超过 max_pages 抛 BitableQueryError，绝不静默截断。
    """
    effective_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    effective_max = max(1, int(max_pages))
    names = list(field_names) if field_names is not None else None
    sort = [{"field_name": time_field, "desc": True}]
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    collected: list[dict[str, Any]] = []
    page_token: str | None = None

    for _page_no in range(1, effective_max + 1):
        result = await _search_page(
            client,
            table_id=table_id,
            filter_info=filter_info,
            field_names=names,
            sort=sort,
            automatic_fields=automatic_fields,
            page_size=effective_size,
            page_token=page_token,
        )
        items = result.get("items") or []
        oldest_ms: int | None = None
        for item in items:
            millis = fields.to_millis((item.get("fields") or {}).get(time_field))
            if millis is None:
                continue
            if oldest_ms is None or millis < oldest_ms:
                oldest_ms = millis
            if start_ms <= millis < end_ms:
                collected.append(item)

        # 本页已出现早于窗口起点的记录 -> 后续页只会更早，可安全停止
        if oldest_ms is not None and oldest_ms < start_ms:
            return collected
        if not result.get("has_more"):
            return collected
        next_token = result.get("page_token")
        if not next_token:
            raise BitableQueryError(
                "Bitable 分页异常: has_more=True 但 page_token 为空"
                f"（窗口拉取已收 {len(collected)} 条）"
            )
        page_token = str(next_token)

    raise BitableQueryError(
        f"Bitable 窗口分页超过上限 max_pages={effective_max}"
        f"（已收 {len(collected)} 条），疑似排序未生效或 page_token 未推进"
    )


def resolve_client(
    domain: str,
    kind: str,
    *,
    table_id: str | None = None,
) -> SafetyBitableClient:
    """按配置中心解析连接并创建客户端；未配置 / 已停用抛 BitableConfigError。

    未知 domain / kind 由 registry 抛 ValueError（编程错误，不伪装成配置缺失）。
    """
    conn = store.get_connection(domain, kind)
    if conn is None or not conn.enabled:
        raise BitableConfigError(f"Bitable 连接未配置或已停用: {domain}/{kind}")
    return SafetyBitableClient(
        app_token=conn.app_token,
        table_id=table_id or conn.table_id,
    )


@dataclass(frozen=True)
class ClientRecordsReader:
    """把 page 级客户端适配成 domain 级 list_all_records 读取器。"""

    client: BitablePageClient
    table_id: str | None = None
    max_pages: int = DEFAULT_MAX_PAGES

    async def list_all_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: Sequence[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = DEFAULT_PAGE_SIZE,
        strict: bool = True,
    ) -> list[dict[str, Any]]:
        return await fetch_all_records(
            self.client,
            table_id=table_id or self.table_id,
            filter_info=filter_info,
            field_names=field_names,
            sort=sort,
            automatic_fields=automatic_fields,
            page_size=page_size,
            max_pages=self.max_pages,
            strict=strict,
        )


def open_reader(
    domain: str,
    kind: str,
    *,
    table_id: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> ClientRecordsReader:
    """真实实现：解析连接后返回可分页批量读取的 reader。"""
    client = resolve_client(domain, kind, table_id=table_id)
    return ClientRecordsReader(
        client=client,
        table_id=table_id,
        max_pages=max_pages,
    )
