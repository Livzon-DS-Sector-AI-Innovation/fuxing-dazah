"""底座写入协议、串行回写、字段 ID 解析与幂等建列。

职责：

1. 定义写入协议 BitableRecordWriter（单条 update_record）与字段管理协议
   BitableFieldAdmin（list_fields / create_field）；测试可注入替身。
2. write_serial 串行回写：一次调用内绝不并发写同一张表，条目之间保留可配置的
   安全间隔（默认 0.5 秒，与 special_op 既有实现一致）；单条失败不抛出。
3. FieldIdResolver / resolve_field_id：字段名 -> field_id 带缓存，避免每条记录
   都查一次 list_fields。
4. FieldSpec + ensure_field：幂等建列。已存在则跳过（类型/属性不一致时只报告
   冲突，绝不修改）；dry-run（apply=False）只报告将新建什么，不调用写接口；
   绝不 update_field / 清空已有列。

实测约束（写进实现）：

- 同一张多维表格不支持并发写（1254291 / 1254607），因此回写必须串行 + 间隔。
- list_fields 为空可能意味着接口失败；现状未知时拒绝建列（避免建出重复列）。
- 建列是黄色操作：真实执行必须由域票据在用户确认后显式传 apply=True。

本模块不做业务字段语义，不 import 任何域包。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

# Bitable 同一张表不支持并发写；条目之间留安全间隔（与 special_op 既有值一致）
WRITEBACK_INTERVAL_SECONDS = 0.5


class BitableRecordWriter(Protocol):
    """单条记录写入协议（真实实现为 SafetyBitableClient.update_record）。"""

    async def update_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        table_id: str | None = None,
    ) -> bool: ...


class BitableFieldAdmin(Protocol):
    """字段管理协议（真实实现为 SafetyBitableClient 的 list_fields / create_field）。"""

    async def list_fields(
        self, table_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def create_field(
        self,
        field_name: str,
        field_type: int,
        table_id: str | None = None,
        *,
        property_: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RecordUpdate:
    """一条待回写内容（写请求体只含 fields 里给的列）。"""

    record_id: str
    fields: dict[str, Any]


@dataclass
class WritebackResult:
    """串行回写结果（供编排入口 log warning / 计入告警）。"""

    attempted: int = 0
    written: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


async def write_serial(
    writer: BitableRecordWriter,
    updates: Sequence[RecordUpdate],
    *,
    interval_seconds: float = WRITEBACK_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    table_id: str | None = None,
) -> WritebackResult:
    """串行回写一批记录。

    - 单次调用内严格串行：第 1 条前不 sleep，此后每条之前 sleep(interval_seconds)
    - 空 record_id / 空 fields 跳过（计入 skipped），不报错、不占用间隔
    - 单条返回 False 或抛异常只记 warning 并计入 failed，**不向上抛**
      （回写失败不阻塞推送/主流程，下一轮自然补写）
    - 同一张表的并发调用由调用方保证串行（本函数只保证单次调用内不并发）
    """
    result = WritebackResult()
    pending: list[RecordUpdate] = []
    for update in updates:
        if update.record_id and update.fields:
            pending.append(update)
        else:
            result.skipped += 1

    for index, update in enumerate(pending):
        if index:
            await sleep(interval_seconds)
        result.attempted += 1
        try:
            if table_id is None:
                # 兼容只接受 (record_id, fields) 的旧域替身；与原 special_op 调用形态一致。
                written = await writer.update_record(update.record_id, update.fields)
            else:
                written = await writer.update_record(
                    update.record_id, update.fields, table_id
                )
        except Exception:
            logger.warning(
                "Bitable 回写异常: record_id=%s", update.record_id, exc_info=True
            )
            written = False
        if written:
            result.written += 1
        else:
            result.failed.append(update.record_id)
            logger.warning("Bitable 回写失败: record_id=%s", update.record_id)

    logger.info(
        "Bitable 串行回写完成: attempted=%d written=%d skipped=%d failed=%d",
        result.attempted,
        result.written,
        result.skipped,
        len(result.failed),
    )
    return result


#
# 字段 ID 解析（带缓存）
#

# 默认进程级缓存：键 (table_id, field_name) -> field_id
_DEFAULT_FIELD_ID_CACHE: dict[tuple[str, str], str] = {}


# Bitable 字段类型（与域包 contract 里的列契约一致）
FIELD_TYPE_TEXT = 1
FIELD_TYPE_SINGLE_SELECT = 3
FIELD_TYPE_MULTI_SELECT = 4


def format_write_value(field_type: int, value: Any) -> Any:
    """按 Bitable 字段类型整形写值。

    - 多选（type=4）：必须传数组，字符串自动包成 [str]
    - 其余类型（文本 / 单选 / 日期 / 人员等）：原样返回

    迁移自 legacy bitable_handler._format_bitable_select_value 的语义（票据 08）。
    """
    if field_type == FIELD_TYPE_MULTI_SELECT and isinstance(value, str):
        return [value]
    return value


async def resolve_field_id(
    client: BitableFieldAdmin,
    field_name: str,
    *,
    table_id: str | None = None,
    cache: MutableMapping[tuple[str, str], str] | None = None,
) -> str | None:
    """字段名 -> field_id（带缓存）；找不到返回 None。

    缓存只按需解析单个字段名，但命中后不再调用 list_fields；因此「同名字段被
    每条记录解析一次」退化为「进程内一次」。传 cache 可复用外部缓存
    （收敛旧包时用域包既有的模块级字典），None 时用进程级默认缓存。
    """
    store = _DEFAULT_FIELD_ID_CACHE if cache is None else cache
    key = (table_id or "", field_name)
    if key in store:
        return store[key] or None

    fields = await client.list_fields(table_id)
    found = ""
    for item in fields:
        if item.get("field_name") == field_name:
            found = str(item.get("field_id") or "")
            break
    store[key] = found
    return found or None


class FieldIdResolver:
    """字段 ID 解析器（每个实例一份缓存；可 invalidate 强制重查）。"""

    def __init__(self, client: BitableFieldAdmin, table_id: str | None = None) -> None:
        self._client = client
        self._table_id = table_id
        self._cache: dict[tuple[str, str], str] = {}

    async def field_id(self, field_name: str) -> str | None:
        return await resolve_field_id(
            self._client, field_name, table_id=self._table_id, cache=self._cache
        )

    def invalidate(self) -> None:
        self._cache.clear()


#
# 幂等建列
#


@dataclass(frozen=True)
class FieldSpec:
    """列契约（列名 / Bitable 类型 / property）。property_ 为期望值的子集匹配。"""

    name: str
    field_type: int
    property_: dict[str, Any] | None = None


EnsureStatus = Literal["exists", "conflict", "would_create", "created", "failed"]


@dataclass
class EnsureFieldResult:
    """建列结果。ok=False 的两种状态（conflict / failed）都需要人工处理。"""

    status: EnsureStatus
    spec: FieldSpec
    field: dict[str, Any] | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("exists", "would_create", "created")

    @property
    def changed(self) -> bool:
        return self.status == "created"


def property_matches(actual: Any, expected: Any) -> bool:
    """expected 是否为 actual 的子集（dict 递归子集；list 同长且逐项匹配）。

    用于容忍飞书回填的额外 key（例如选项对象里多出的 option id）。
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and property_matches(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(
            property_matches(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    return bool(actual == expected)


def field_matches(field: dict[str, Any], spec: FieldSpec) -> bool:
    """列名 / 类型一致，且 spec 声明的 property 是实际 property 的子集。"""
    if field.get("field_name") != spec.name:
        return False
    if field.get("type") != spec.field_type:
        return False
    if spec.property_ is None:
        return True
    return property_matches(field.get("property"), spec.property_)


def extract_option_names(property_: dict[str, Any] | None) -> list[str]:
    """property 里的选项名列表（顺序即展示顺序）；缺失返回空列表。"""
    if not isinstance(property_, dict):
        return []
    options = property_.get("options")
    if not isinstance(options, list):
        return []
    return [
        str(item.get("name") or "")
        for item in options
        if isinstance(item, dict)
    ]


def describe_spec(spec: FieldSpec) -> str:
    """人类可读的列契约摘要（dry-run 打印用）。"""
    text = f"name={spec.name} type={spec.field_type}"
    options = extract_option_names(spec.property_)
    if options:
        text += " options=[" + ", ".join(options) + "]"
    return text


async def ensure_field(
    client: BitableFieldAdmin,
    spec: FieldSpec,
    *,
    apply: bool = False,
    table_id: str | None = None,
) -> EnsureFieldResult:
    """幂等建列：存在即跳过；dry-run 只报告；apply=True 才真正 create_field。

    安全约束：

    - 已存在的列**绝不修改**（类型/属性不一致只返回 conflict，由人工确认）；
    - list_fields 返回空 -> failed（现状未知时拒绝建列，避免重复列）；
    - 只调用 create_field，不调用 update_field / 任何删除接口。
    """
    fields = await client.list_fields(table_id)
    if not fields:
        return EnsureFieldResult(
            "failed",
            spec,
            None,
            "list_fields 返回空，疑似接口失败；拒绝在现状未知时建列",
        )

    existing = next(
        (item for item in fields if item.get("field_name") == spec.name), None
    )
    if existing is not None:
        if field_matches(existing, spec):
            return EnsureFieldResult(
                "exists", spec, existing, f"列已存在且与契约一致，跳过: {spec.name}"
            )
        return EnsureFieldResult(
            "conflict",
            spec,
            existing,
            f"列已存在但与契约不一致，不自动修改: {spec.name}",
        )

    if not apply:
        return EnsureFieldResult(
            "would_create", spec, None, f"dry-run: 将新建 {describe_spec(spec)}"
        )

    created = await client.create_field(
        spec.name, spec.field_type, table_id, property_=spec.property_
    )
    if not created:
        return EnsureFieldResult("failed", spec, None, f"建列失败: {spec.name}")
    if not field_matches(created, spec):
        return EnsureFieldResult(
            "created",
            spec,
            created,
            f"列已创建，但返回结果与契约不一致，请人工核对: {spec.name}",
        )
    return EnsureFieldResult(
        "created", spec, created, f"列已创建并校验通过: {spec.name}"
    )


def open_writer(
    domain: str,
    kind: str,
    *,
    table_id: str | None = None,
) -> BitableRecordWriter:
    """真实写入实现：按配置中心解析连接后返回客户端（update_record 即写入协议）。"""
    from app.modules.safety.service.bitable_direct import reader

    return reader.resolve_client(domain, kind, table_id=table_id)
