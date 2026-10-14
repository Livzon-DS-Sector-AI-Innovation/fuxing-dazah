"""外来人员预报备审批表直读（visitor_insurance）。

数据源：飞书多维表格「外来人员安全培训通知单 - 预报备审批流程」
（registry 域 visitor_notice / kind notice）。纯只读周报：无事件订阅、
无进程内缓存，每次执行 strict 全量拉取（百条量级，单页 500 即完）。

字段语义（2026-10-14 实测 144 条）：
- 一条记录 = 一份已走完审批的预报备申请，可含多名外来人员；
- 保险（保险有效期至 / 保险凭证）按**申请单（单位）**维度填写，
  不按人拆分——预警粒度与申请单一致；
- 表内还混有变更管理字段（变更名称/分类等），本报告不消费。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader

logger = logging.getLogger(__name__)

# 预报备审批表字段（field_names 投影，只请求本报告消费的列）
F_STATUS = "申请状态"
F_INSURANCE_END = "保险有效期至"
F_ENTRY_START = "进厂开始时间"
F_ENTRY_END = "进厂结束时间"
F_NAMES = "进厂外来人员姓名"
F_COMPANY = "单位名称"
F_WORK_CONTENT = "作业内容"
F_WORK_SCOPE = "作业范围"
F_PEOPLE = "预计进厂人数(人)"

REQUEST_FIELD_NAMES: tuple[str, ...] = (
    F_STATUS, F_INSURANCE_END, F_ENTRY_START, F_ENTRY_END,
    F_NAMES, F_COMPANY, F_WORK_CONTENT, F_WORK_SCOPE, F_PEOPLE,
)

STATUS_APPROVED = "已通过"

# registry 域/kind（bitable_config 配置中心；registry 默认连接即生产表）
DOMAIN = "visitor_notice"
KIND = "notice"


@dataclass
class VisitorNoticeView:
    """一条预报备申请的内存视图（不落库、不参与 ORM）。"""

    record_id: str
    company: str = ""
    names: str = ""
    people_count: int = 0
    work_content: str = ""
    work_scope: str = ""
    status: str = ""
    entry_start: date | None = None
    entry_end: date | None = None
    insurance_end: date | None = None


def to_view(record: dict[str, Any]) -> VisitorNoticeView | None:
    """API 记录 → 视图。

    无单位名称的行跳过（预警按单位聚合、处置找单位，缺名无法落地）。
    """
    fields = record.get("fields") or {}
    company = (bd_fields.select(fields, F_COMPANY) or "").strip()
    if not company:
        return None

    def _d(name: str) -> date | None:
        dt = bd_fields.datetime_ms(fields, name)
        return dt.date() if dt else None

    try:
        people = int(fields.get(F_PEOPLE) or 0)
    except (TypeError, ValueError):
        people = 0

    return VisitorNoticeView(
        record_id=str(record.get("record_id") or ""),
        company=company,
        names=bd_fields.text(fields, F_NAMES) or "",
        people_count=people,
        work_content=bd_fields.text(fields, F_WORK_CONTENT) or "",
        work_scope=bd_fields.text(fields, F_WORK_SCOPE) or "",
        status=bd_fields.select(fields, F_STATUS) or "",
        entry_start=_d(F_ENTRY_START),
        entry_end=_d(F_ENTRY_END),
        insurance_end=_d(F_INSURANCE_END),
    )


class VisitorNoticeReader:
    """预报备审批表全量读取器（page client 可注入，测试用替身）。"""

    def __init__(self, client: bd_reader.BitablePageClient | None = None) -> None:
        self._client = client

    async def fetch_all(self) -> list[VisitorNoticeView]:
        """全量拉取 → 视图列表（strict：查询失败上抛，由调度器记 failed 补发）。"""
        client = self._client or bd_reader.resolve_client(DOMAIN, KIND)
        records = await bd_reader.fetch_all_records(
            client,
            field_names=REQUEST_FIELD_NAMES,
            strict=True,
        )
        views = [v for v in (to_view(r) for r in records) if v is not None]
        logger.info("外来人员预报备直读完成: records=%d views=%d", len(records), len(views))
        return views


def open_reader() -> VisitorNoticeReader:
    """组装真实读取器（每周一次低频调用，不设进程内缓存）。"""
    return VisitorNoticeReader(bd_reader.resolve_client(DOMAIN, KIND))
