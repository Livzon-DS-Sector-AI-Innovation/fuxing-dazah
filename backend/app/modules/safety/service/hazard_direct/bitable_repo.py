"""隐患直读模式 — 多维表格仓储层（唯一数据源，不落库）。

职责：
- 按「待处理条件」查询 Bitable 记录（官方 records/search，非系统字段过滤）；
- 字段解析（person / select / multi_select / 日期 / 富文本）；
- per-record Redis 锁（防同一条被并发处理）；
- 写回 AI 字段（① 识别 / ② 初审）；
- 编号分配（HZ-YYYYMMDD-NNN，与现有规则一致）。

硬约束（实测）：
- 系统字段（修改时间/最后更新时间/创建时间）**不能**作为 filter 条件（1254018 InvalidFilter）；
- 只有业务日期字段（检查日期、整改完成时间）可过滤；
- Bitable 单表写操作不支持并发（1254291 / 1254607），写入必须串行 + 间隔。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.redis import redis_client
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.bitable_handler import (
    HAZARD_CATEGORY_REVERSE,
    HAZARD_LEVEL_REVERSE,
    HAZARD_TYPE_REVERSE,
    _extract_person_info,
    _extract_rich_text,
    _extract_select_values,
    _format_bitable_select_value,
    _ms_to_datetime,
)
from app.modules.safety.service.hazard_direct import config

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 字段名常量（与多维表格实际列名一致）
# ═══════════════════════════════════════════════════════════════

F_NO = "隐患编号"
F_DESC = "隐患描述"
F_DESC_AI = "隐患描述（AI）"
F_PHOTO_DEFECT = "缺陷图片"
F_PHOTO_RECTIFY = "整改后图片"
F_DATE = "检查日期"
F_INSPECTOR = "检查人员"
F_INSPECTOR_DEPT = "检查人员.部门"
F_INSPECTION_CATEGORY = "检查类别"
F_DEPT = "整改责任人.部门"
F_RESPONSIBLE = "整改责任人"
F_LEVEL_MANUAL = "隐患级别"
F_TYPE_AI = "隐患分类（AI）"
F_LEVEL_AI = "隐患级别（AI）"
F_CATEGORY_AI = "隐患类别（AI）"
F_BASIS_AI = "隐患判定依据（AI）"
F_ADVICE_AI = "整改建议（AI）"
F_SUPERVISION = "督办等级"
F_RECTIFY_STATUS = "整改状态"
F_RECTIFY_REPLY = "纠正预防措施"
F_RECTIFY_DONE_AT = "整改完成时间"
F_DEADLINE = "整改期限"
F_PROGRESS = "目前进展"
F_REVIEW_RESULT = "AI初审结果"
F_REVIEW_NOTE = "AI初审说明"

# ── ① 待处理判据：AI 识别输出字段为空 ──
COND_AI_PENDING: list[dict[str, Any]] = [
    {"field_name": F_TYPE_AI, "operator": "isEmpty", "value": []},
]

# ── ② 待审核判据：已填整改回复 且 未被 AI 初审 且 尚未关闭 ──
COND_REVIEW_PENDING: list[dict[str, Any]] = [
    {"field_name": F_RECTIFY_REPLY, "operator": "isNotEmpty", "value": []},
    {"field_name": F_REVIEW_RESULT, "operator": "isEmpty", "value": []},
    {"field_name": F_RECTIFY_STATUS, "operator": "isNot", "value": ["已关闭"]},
]

# ── ③ 日报：未闭环台账 ──
COND_OPEN: list[dict[str, Any]] = [
    {"field_name": F_RECTIFY_STATUS, "operator": "is", "value": ["未关闭"]},
    {"field_name": F_RECTIFY_STATUS, "operator": "is", "value": ["整改中"]},
]

# AI 初审结论 → 多维表格「AI初审结果」选项（以字段值为准）
REVIEW_CONCLUSION_MAP: dict[str, str] = {
    "通过": "已通过",
    "不通过": "未通过",
    "无需整改": "无需整改",
}

_HZ_RE = re.compile(r"^HZ-(\d{8})-(\d{3})$")
# 旧的失败标记（ERROR:...）—— 视为"未分配编号"
_ERROR_PREFIX = "ERROR:"


def _and(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"conjunction": "and", "conditions": conditions}


def _or(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"conjunction": "or", "conditions": conditions}


# ═══════════════════════════════════════════════════════════════
# 字段解析
# ═══════════════════════════════════════════════════════════════


def f_text(fields: dict[str, Any], name: str) -> str:
    """文本字段 → 纯字符串（富文本数组自动拼接）。"""
    return (_extract_rich_text(fields.get(name)) or "").strip()


def f_select(fields: dict[str, Any], name: str) -> str:
    """单选/多选字段 → 逗号拼接字符串。"""
    return (_extract_select_values(fields.get(name)) or "").strip()


def f_person(fields: dict[str, Any], name: str) -> str:
    """人员字段 → 姓名（无姓名时回退 id）。"""
    info = _extract_person_info(fields.get(name))
    return (info.get("name") or info.get("id") or "").strip()


def f_datetime(fields: dict[str, Any], name: str) -> datetime | None:
    """日期字段 → datetime（缺失返回 None）。"""
    return _ms_to_datetime(fields.get(name))


def f_attachments(fields: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """附件字段 → 附件元数据列表。"""
    raw = fields.get(name)
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict) and a.get("file_token")]


def is_placeholder_no(value: str) -> bool:
    """是否为「未分配编号」占位（空 或 旧的 ERROR 标记）。"""
    return (not value) or value.startswith(_ERROR_PREFIX)


# 外审类检查类别关键词（仅看「检查类别」，不看描述/人员，避免误判）
AUDIT_CATEGORY_KEYWORDS: tuple[str, ...] = ("审计", "政府", "管委会", "应急局")


def is_audit_record(fields: dict[str, Any]) -> bool:
    """是否为外审记录（按「检查类别」判定）。

    实测（2026-09-09）：平台库有 **126 条**外审记录（集团EHS审计 / 事业部EHS审计 /
    政府安全检查等），但**全部不在隐患主表（多维表格）中** —— 主表 2,051 条里
    没有任何外审类别。因此直读多维表格的督办计算 / 督办通报 / 未更新进展催办
    **天然不会统计外审记录**。

    此处保留防御性过滤：若将来外审类别出现在主表，督办与催办会自动排除，
    无需再改业务代码。
    """
    category = f_select(fields, F_INSPECTION_CATEGORY)
    return any(keyword in category for keyword in AUDIT_CATEGORY_KEYWORDS)


@dataclass
class HazardView:
    """轻量隐患视图对象。

    仅为复用既有纯函数而存在：
    - ``service.hazard_supervision.calculate_supervision_level``
    - ``feishu.progress_card.build_progress_card``
    - 通报渲染（本模块 ``bulletin``）

    字段名与 ``HazardReport`` 对齐，但**不落库、不参与 ORM**。
    ``id`` / ``feishu_record_id`` 为属性，统一返回多维表格 record_id
    （直读模式下它就是唯一标识）。
    """

    record_id: str = ""
    hazard_no: str = ""
    description: str = ""
    department: str | None = None
    responsible_person: str | None = None
    rectification_responsible_person_name: str | None = None
    inspection_category: str | None = None
    hazard_level_manual: str | None = None
    hazard_level: str | None = None
    discovered_at: datetime | None = None
    rectification_status: str = "pending"
    status: str = "open"
    deadline: datetime | None = None
    rectify_reply: str = ""
    review_result: str = ""
    # ── 督办相关 ──
    supervision_level: str = ""
    supervision_progress_status: str | None = None
    progress_note: str = ""
    progress_note_updated_at: datetime | None = None
    major_hazard_basis: str = ""
    # 多维表格无 notes 字段（外审判定依赖它，直读模式下恒为空）
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """记录唯一标识（= 多维表格 record_id）。"""
        return self.record_id

    @property
    def feishu_record_id(self) -> str:
        """飞书记录 ID（= record_id，供记录链接/卡片复用）。"""
        return self.record_id


def to_view(record: dict[str, Any]) -> HazardView:
    """Bitable 记录 → HazardView。"""
    fields: dict[str, Any] = record.get("fields", {}) or {}
    status_cn = f_select(fields, F_RECTIFY_STATUS)
    status_map = {"已关闭": "closed", "未关闭": "pending", "整改中": "in_progress"}
    rect_status = status_map.get(status_cn, "pending")
    return HazardView(
        record_id=record.get("record_id", ""),
        hazard_no=f_text(fields, F_NO),
        description=f_text(fields, F_DESC),
        department=f_select(fields, F_DEPT) or None,
        responsible_person=f_person(fields, F_RESPONSIBLE) or None,
        rectification_responsible_person_name=f_person(fields, F_RESPONSIBLE) or None,
        inspection_category=f_select(fields, F_INSPECTION_CATEGORY) or None,
        hazard_level_manual=f_select(fields, F_LEVEL_MANUAL) or None,
        hazard_level=f_select(fields, F_LEVEL_AI) or None,
        discovered_at=f_datetime(fields, F_DATE),
        rectification_status=rect_status,
        status="closed" if rect_status == "closed" else "open",
        deadline=f_datetime(fields, F_DEADLINE),
        rectify_reply=f_text(fields, F_RECTIFY_REPLY),
        review_result=f_select(fields, F_REVIEW_RESULT),
        supervision_level=f_select(fields, F_SUPERVISION),
        progress_note=f_text(fields, F_PROGRESS),
        major_hazard_basis=f_text(fields, F_BASIS_AI),
        raw=fields,
    )


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════


async def search_pending_ai(
    client: SafetyBitableClient, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """① 待 AI 识别记录（隐患分类（AI）为空）。"""
    records = await client.list_all_records(
        filter_info=_and(COND_AI_PENDING),
        page_size=500,
        strict=True,
    )
    return records[: (limit or config.batch_limit())]


async def search_pending_review(
    client: SafetyBitableClient, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """② 待 AI 初审记录（已填回复 且 未初审 且 未关闭）。"""
    records = await client.list_all_records(
        filter_info=_and(COND_REVIEW_PENDING),
        page_size=500,
        strict=True,
    )
    return records[: (limit or config.batch_limit())]


async def search_open_hazards(client: SafetyBitableClient) -> list[dict[str, Any]]:
    """③ 未闭环台账（未关闭 或 整改中）。"""
    return await client.list_all_records(
        filter_info=_or(COND_OPEN), page_size=500, strict=True
    )


async def search_created_since(
    client: SafetyBitableClient, days: int
) -> list[dict[str, Any]]:
    """③ 近 N 天新增（按业务字段「检查日期」过滤；系统字段不可过滤）。"""
    since = datetime.now(UTC) - timedelta(days=days)
    ms = int(since.timestamp() * 1000)
    return await client.list_all_records(
        filter_info=_and(
            [{"field_name": F_DATE, "operator": "isGreater", "value": ["ExactDate", str(ms)]}]
        ),
        page_size=500,
        strict=True,
    )


async def search_closed_since(
    client: SafetyBitableClient, days: int
) -> list[dict[str, Any]]:
    """③ 近 N 天关闭（按「整改完成时间」过滤）。"""
    since = datetime.now(UTC) - timedelta(days=days)
    ms = int(since.timestamp() * 1000)
    return await client.list_all_records(
        filter_info=_and(
            [
                {"field_name": F_RECTIFY_STATUS, "operator": "is", "value": ["已关闭"]},
                {
                    "field_name": F_RECTIFY_DONE_AT,
                    "operator": "isGreater",
                    "value": ["ExactDate", str(ms)],
                },
            ]
        ),
        page_size=500,
        strict=True,
    )


# ═══════════════════════════════════════════════════════════════
# 查询（供 Agent 只读工具使用，替代平台库查询）
# ═══════════════════════════════════════════════════════════════

# 平台内部整改状态 → Bitable「整改状态」选项
_RECTIFY_CN = {"closed": "已关闭", "pending": "未关闭", "in_progress": "整改中"}


def _date_cond(field: str, value: str, *, lower: bool) -> dict[str, Any] | None:
    """日期过滤条件（ExactDate 毫秒时间戳）。

    Bitable 日期字段不支持 isGreaterEqual/isLessEqual，故下界用 isGreater、
    上界用 isLess（调用方负责把上界设为「次日 00:00」）。
    """
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return {
        "field_name": field,
        "operator": "isGreater" if lower else "isLess",
        "value": ["ExactDate", str(int(dt.timestamp() * 1000))],
    }


def _base_conditions(
    *,
    department: str | None = None,
    rectification_status: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """构造扁平 AND 条件列表（不含关键词）。"""
    conds: list[dict[str, Any]] = []
    if department:
        conds.append({"field_name": F_DEPT, "operator": "is", "value": [department]})

    cn_status = _RECTIFY_CN.get((rectification_status or "").strip())
    if cn_status:
        conds.append({"field_name": F_RECTIFY_STATUS, "operator": "is", "value": [cn_status]})
    elif status == "closed":
        conds.append({"field_name": F_RECTIFY_STATUS, "operator": "is", "value": ["已关闭"]})
    elif status == "open":
        conds.append(
            {"field_name": F_RECTIFY_STATUS, "operator": "isNot", "value": ["已关闭"]}
        )

    for value, lower in ((date_from, True), (date_to, False)):
        if value:
            cond = _date_cond(F_DATE, value, lower=lower)
            if cond:
                conds.append(cond)
    return conds


def _flat(conds: list[dict[str, Any]], conjunction: str = "and") -> dict[str, Any] | None:
    """扁平条件组（None = 无过滤）。

    注意：实测该 records/search 接口**不支持嵌套 children/conditions**
    （传嵌套结构返回 99992402 field validation failed），故所有条件必须扁平。
    """
    return {"conjunction": conjunction, "conditions": conds} if conds else None


async def query_hazards(
    client: SafetyBitableClient,
    *,
    department: str | None = None,
    rectification_status: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> tuple[list[HazardView], int]:
    """按条件查询隐患（直读多维表格）。返回 (视图列表, 命中总数)。

    关键词匹配策略（接口不支持嵌套 OR，故只选一个字段）：
    - 关键词形如 ``HZ-...`` → 匹配「隐患编号」
    - 其余 → 匹配「隐患描述」

    ``total`` 取自 search 接口返回的精确总数（不受 limit 影响）。
    """
    conds = _base_conditions(
        department=department,
        rectification_status=rectification_status,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    kw = (keyword or "").strip()
    if kw:
        field = F_NO if kw.upper().startswith("HZ-") else F_DESC
        conds.append({"field_name": field, "operator": "contains", "value": [kw]})

    limit = max(1, min(limit, 500))
    result = await client.search_records(
        filter_info=_flat(conds),
        sort=[{"field_name": F_DATE, "desc": True}],
        page_size=limit,
        strict=True,
    )
    records = result.get("items") or []
    total = int(result.get("total") or len(records))

    views = [to_view(rec) for rec in records]
    # 过滤异常占位记录（人工误创建/删除）
    views = [
        v for v in views if (v.description or "").strip() not in ("", "待AI填写")
    ]
    return views[:limit], total


async def count_hazards(
    client: SafetyBitableClient,
    *,
    department: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    """隐患统计（直读多维表格，用 search 的 total 精确计数）。

    返回 {total, closed, unclosed, abnormal_records}。
    口径：整改状态三选项「已关闭/未关闭/整改中」→ closed=已关闭，
    unclosed=未关闭+整改中；abnormal=描述为空或「待AI填写」。
    """
    base: dict[str, Any] = {
        "department": department,
        "date_from": date_from,
        "date_to": date_to,
    }

    async def _count(**extra: Any) -> int:
        result = await client.search_records(
            page_size=1,
            filter_info=_flat(_base_conditions(**{**base, **extra})),
            strict=True,
        )
        return int(result.get("total") or 0)

    total = await _count()
    closed = await _count(rectification_status="closed")
    unclosed = await _count(status="open")

    abnormal = 0
    for cond in (
        {"field_name": F_DESC, "operator": "isEmpty", "value": []},
        {"field_name": F_DESC, "operator": "is", "value": ["待AI填写"]},
    ):
        conds: list[dict[str, Any]] = [cond]
        if department:
            conds.insert(
                0, {"field_name": F_DEPT, "operator": "is", "value": [department]}
            )
        for value, lower in ((date_from, True), (date_to, False)):
            if value:
                dc = _date_cond(F_DATE, value, lower=lower)
                if dc:
                    conds.append(dc)
        result = await client.search_records(
            page_size=1, filter_info=_flat(conds), strict=True
        )
        abnormal += int(result.get("total") or 0)

    return {
        "total": total,
        "closed": closed,
        "unclosed": unclosed,
        "abnormal_records": abnormal,
    }


# ═══════════════════════════════════════════════════════════════
# 编号分配
# ═══════════════════════════════════════════════════════════════


class HazardNoAllocator:
    """HZ-YYYYMMDD-NNN 编号分配器（每轮初始化一次，内存递增）。

    与既有规则一致（``audit/service.py:_gen_hazard_no`` / ``service/hazard.py:288``），
    但数据源改为多维表格：扫描当日已有编号取最大值 + 1。
    """

    def __init__(self, client: SafetyBitableClient) -> None:
        self._client = client
        self._date_str = date.today().strftime("%Y%m%d")
        self._next = 0

    async def _ensure_loaded(self) -> None:
        if self._next:
            return
        prefix = f"HZ-{self._date_str}-"
        records = await self._client.list_all_records(
            filter_info=_and(
                [
                    {
                        "field_name": F_NO,
                        "operator": "contains",
                        "value": [prefix],
                    }
                ]
            ),
            page_size=500,
            strict=True,
        )
        max_seq = 0
        for rec in records:
            text = f_text(rec.get("fields", {}), F_NO)
            match = _HZ_RE.match(text)
            if match and match.group(1) == self._date_str:
                max_seq = max(max_seq, int(match.group(2)))
        self._next = max_seq + 1
        logger.info("编号分配器初始化: 前缀=%s 已有最大值=%d", prefix, max_seq)

    async def next_no(self) -> str:
        """分配下一个编号。"""
        await self._ensure_loaded()
        value = f"HZ-{self._date_str}-{self._next:03d}"
        self._next += 1
        return value


# ═══════════════════════════════════════════════════════════════
# per-record 锁
# ═══════════════════════════════════════════════════════════════


def _lock_key(record_id: str) -> str:
    return f"safety:hazard:direct:lock:{record_id}"


@asynccontextmanager
async def record_lock(record_id: str) -> AsyncIterator[bool]:
    """按记录加锁（Redis SET NX EX）。

    yield True = 抢到锁；False = 已被其他轮次/实例处理，调用方应跳过。
    正常结束后释放，失败记录下一轮可重试。
    """
    key = _lock_key(record_id)
    try:
        acquired = bool(
            await redis_client.set(key, "1", ex=config.record_lock_ttl(), nx=True)
        )
    except Exception:
        logger.warning("Redis 不可用，跳过记录锁: record_id=%s", record_id, exc_info=True)
        acquired = True
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis_client.delete(key)
            except Exception:
                logger.debug("释放记录锁失败: record_id=%s", record_id, exc_info=True)


# ═══════════════════════════════════════════════════════════════
# 写回
# ═══════════════════════════════════════════════════════════════


async def write_ai_analysis(
    client: SafetyBitableClient,
    record_id: str,
    *,
    hazard_no: str | None,
    output: dict[str, Any],
    supervision_label: str | None = None,
) -> bool:
    """① 写回 AI 识别结果（7 个字段 + 督办等级）。

    只写多维表格，不写数据库。
    """
    writeback: dict[str, Any] = {}
    if hazard_no:
        writeback[F_NO] = hazard_no
    if output.get("hazard_type"):
        writeback[F_TYPE_AI] = _format_bitable_select_value(
            F_TYPE_AI, HAZARD_TYPE_REVERSE.get(output["hazard_type"], output["hazard_type"])
        )
    if output.get("hazard_level"):
        writeback[F_LEVEL_AI] = _format_bitable_select_value(
            F_LEVEL_AI, HAZARD_LEVEL_REVERSE.get(output["hazard_level"], output["hazard_level"])
        )
    if output.get("hazard_category"):
        writeback[F_CATEGORY_AI] = _format_bitable_select_value(
            F_CATEGORY_AI,
            HAZARD_CATEGORY_REVERSE.get(output["hazard_category"], output["hazard_category"]),
        )
    if output.get("key_defect"):
        writeback[F_DESC_AI] = output["key_defect"]
    if output.get("major_hazard_basis"):
        writeback[F_BASIS_AI] = output["major_hazard_basis"]
    if output.get("advice_text"):
        writeback[F_ADVICE_AI] = output["advice_text"]
    if supervision_label:
        writeback[F_SUPERVISION] = _format_bitable_select_value(
            F_SUPERVISION, supervision_label
        )
    if not writeback:
        logger.warning("① 无字段可写回，跳过: record_id=%s", record_id)
        return False
    return await client.update_record(record_id, writeback)


async def write_review(
    client: SafetyBitableClient,
    record_id: str,
    *,
    conclusion: str,
    summary: str,
) -> bool:
    """② 写回 AI 初审结果（结论 + 说明）。

    conclusion 必须是「AI初审结果」字段的既有选项之一；未知结论由调用方拦截，不写。
    """
    return await client.update_record(
        record_id, {F_REVIEW_RESULT: conclusion, F_REVIEW_NOTE: summary}
    )


# ═══════════════════════════════════════════════════════════════
# 附件下载（复用 bitable_handler 既有实现）
# ═══════════════════════════════════════════════════════════════


# 附件下载并发上限：官方素材下载 5 QPS + 10,000 次/天 → 取 3 保守值
_DOWNLOAD_SEM = asyncio.Semaphore(3)
# 字段名 → field_id 缓存（仅回退下载路径需要 extra 时用，进程内一次）
_field_id_cache: dict[str, str] = {}


async def _field_id_of(client: SafetyBitableClient, field_name: str) -> str:
    """取字段 field_id（进程内缓存；失败返回空串，回退路径将不带 extra）。"""
    if field_name in _field_id_cache:
        return _field_id_cache[field_name]
    try:
        value = await client.get_field_id_by_name(field_name) or ""
    except Exception:
        logger.debug("获取 field_id 失败: %s", field_name, exc_info=True)
        value = ""
    _field_id_cache[field_name] = value
    return value


async def download_photos(
    client: SafetyBitableClient,
    fields: dict[str, Any],
    *,
    record_id: str,
) -> dict[str, list[str]]:
    """下载缺陷图 / 整改后图到统一存储，返回 {"defect": [...], "rectification": [...]}。

    **不再调用 ``get_record``**：``records/search`` 返回的附件元数据已含
    ``url``（内嵌 bitablePerm extra）与 ``tmp_url``，可直接下载。

    为什么重要：``get_record`` 在并发读同一张多维表格时会触发
    官方文档所述的「单表不支持并发」→ ``1254607 Data not ready`` 或
    15 秒 ``ReadTimeout``（实测 18 条并发 3 → 7 条超时失败）。

    三级回退：预签名 url → tmp_url → file_token + extra（Drive API）。
    """
    from app.modules.safety.attachment_store import store_bytes
    from app.modules.safety.feishu.bitable_handler import _build_attachment_extra

    saved: dict[str, list[str]] = {"defect": [], "rectification": []}

    for field_name, key in ((F_PHOTO_DEFECT, "defect"), (F_PHOTO_RECTIFY, "rectification")):
        for att in f_attachments(fields, field_name):
            file_token = str(att.get("file_token") or "")
            file_name = str(att.get("name") or "unknown")
            data: bytes | None = None

            # 策略 1/2：预签名 url → tmp_url
            for url in (att.get("url"), att.get("tmp_url")):
                if data or not url:
                    continue
                async with _DOWNLOAD_SEM:
                    try:
                        data = await client.download_attachment_from_url(str(url))
                    except Exception:
                        logger.warning(
                            "附件 URL 下载异常: record_id=%s file_token=%s",
                            record_id, file_token, exc_info=True,
                        )

            # 策略 3：file_token + extra（Drive API）
            if not data and file_token:
                extra: str | None = None
                field_id = await _field_id_of(client, field_name)
                if field_id:
                    extra = _build_attachment_extra(
                        client.table_id, record_id, field_id, file_token
                    )
                async with _DOWNLOAD_SEM:
                    try:
                        data = await client.download_attachment(file_token, extra=extra)
                    except Exception:
                        logger.warning(
                            "附件 Drive API 下载异常: record_id=%s file_token=%s",
                            record_id, file_token, exc_info=True,
                        )

            if not data:
                logger.error(
                    "附件下载失败（所有策略耗尽）: record_id=%s field=%s file_token=%s name=%s",
                    record_id, field_name, file_token, file_name,
                )
                continue

            try:
                safe_name = file_name.replace("\\", "/").split("/")[-1]
                stored = store_bytes(
                    "hazard",
                    f"direct_{record_id}_{file_token[:12]}_{safe_name}",
                    data,
                    content_type=str(att.get("type") or "application/octet-stream"),
                )
                saved[key].append(stored)
            except Exception:
                logger.exception(
                    "附件保存失败: record_id=%s name=%s", record_id, file_name
                )

    logger.info(
        "附件下载完成: record_id=%s defect=%d rectification=%d",
        record_id, len(saved["defect"]), len(saved["rectification"]),
    )
    return saved


def photos_to_data_uris(paths: list[str]) -> list[str]:
    """本地路径列表 → 视觉模型可用的 data URI 列表（限 4 张）。"""
    from app.modules.safety.vision.utils import (
        filter_relevant_images,
        resolve_photo_urls,
    )

    if not paths:
        return []
    uris = resolve_photo_urls(json.dumps(paths), logger_instance=logger)
    return filter_relevant_images(uris)
