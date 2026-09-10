"""监护补贴计划整理（平台作业票 → 补贴计划）。

核心接缝：``SubsidyPlanBuilder.build`` 为**纯函数** —— 输入平台工票列表 +
证书映射 + 部门关键词 + 年月，输出补贴请求记录、待核对名单、跳过清单与统计；
不碰 DB、不碰网络；仅依赖 ``service/subsidy.py`` 的公开常量
``PER_OCCURRENCE_TYPES``（按次计费票种判定，同层 import）。

模块内两类职责：

- ``build_certificate_map``：**DB 依赖**（person_certificates 查询），仅供
  Agent 工具 / Service 层调用；匹配规则本身在纯函数内完成。

补贴标准见 ``service/subsidy.py`` 的 ``SUBSIDY_RATES``：中文标签须与其键值
完全一致（本文件下方 ``_OP_TYPE_LABEL`` 即按现有常量对齐）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import PersonCertificate
from app.modules.safety.schemas.subsidy import SubsidyRecordInput
from app.modules.safety.service.subsidy import PER_OCCURRENCE_TYPES
from app.modules.safety.workticket_review.parser import WorkTicket

# ── 证书级别标签（与 subsidy 汇总口径一致） ──
_LEVEL_A = "A证"
_LEVEL_B = "B证"

# ── 作业类型中文标签 ──
# 与 service/subsidy.py 的 SUBSIDY_RATES / _SUMMARY_OP_TYPES 键值对齐：
# height_work → 「登高作业」（SUBSIDY_RATES 同时保留「高处作业」别名键，值相同）。
_OP_TYPE_LABEL: dict[str, str] = {
    "hot_work": "动火作业",
    "confined_space": "受限空间",
    "height_work": "登高作业",
    "lifting": "吊装作业",
    "temporary_electricity": "临时用电",
    "excavation": "动土",
    "road_breaking": "断路",
    "blind_plate": "抽堵盲板",
}

# ── 跳过原因 ──
_REASON_VOID = "作废/数据不足"
_REASON_MISSING_START = "缺少开始时间"
_REASON_MISSING_END = "缺少结束时间"
_REASON_NO_GUARDIAN = "无监护人"
_REASON_UNKNOWN_OP = "未知作业类型"


def _normalize_name(name: str) -> str:
    """姓名归一化：去除所有空白字符（含全角空格/制表符）。

    证书台账 ``person_name`` 与票面 ``guardian`` 均需先归一再精确匹配。
    """
    return "".join(name.split())


def _dedup_overlapping_records(
    records: list[SubsidyRecordInput],
) -> tuple[list[SubsidyRecordInput], list[SkippedTicket]]:
    """同监护人同日时间重叠去重：一次作业多张票只按补贴最高的一张计。

    - 归组：同 ``guardian_name`` + 同开始日期 + 时间区间重叠（两两重叠取
      连通分量：A∩B、B∩C 归同组，即使 A∩C 不直接重叠）；
    - 组内保留 ``subsidy_amount`` 最高的一张（金额经 SubsidyService 实算，
      与许可 clamp/午休扣除口径一致），金额并列时保留开始时间较早者；
    - 其余票移出 records，作为 ``SkippedTicket``（原因注明并入哪张票），
      随「待核对-跳过说明」页透明展示。

    Returns:
        (去重后的 records, 淘汰票的 skipped 列表)
    """
    from app.modules.safety.service.subsidy import SubsidyService

    if len(records) < 2:
        return records, []

    def _amount(rec: SubsidyRecordInput) -> float:
        return SubsidyService._calc_single(rec).subsidy_amount

    def _start(rec: SubsidyRecordInput) -> datetime:
        return datetime.fromisoformat(rec.start_time)

    def _end(rec: SubsidyRecordInput) -> datetime:
        return datetime.fromisoformat(rec.end_time)

    # 发酵工程部受限空间按张计费、不参与重叠去重 → 排除在去重逻辑外
    ferment = "发酵工程部"
    buckets: dict[tuple[str, date], list[int]] = {}
    for idx, rec in enumerate(records):
        if rec.department == ferment and rec.operation_type == "受限空间":
            continue
        buckets.setdefault((rec.guardian_name, _start(rec).date()), []).append(idx)

    removed: dict[int, str] = {}  # idx -> 保留票的 ticket_no
    for idx_list in buckets.values():
        if len(idx_list) < 2:
            continue
        # 并查集求连通分量
        parent = {i: i for i in idx_list}

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for a_pos in range(len(idx_list)):
            for b_pos in range(a_pos + 1, len(idx_list)):
                a, b = idx_list[a_pos], idx_list[b_pos]
                if _start(records[a]) < _end(records[b]) and _start(records[b]) < _end(records[a]):
                    parent[find(a)] = find(b)

        components: dict[int, list[int]] = {}
        for i in idx_list:
            components.setdefault(find(i), []).append(i)

        for members in components.values():
            if len(members) < 2:
                continue
            # 保留金额最高；并列取开始较早；再并列取票号小者（稳定）
            keep = max(
                members,
                key=lambda i: (_amount(records[i]), -_start(records[i]).timestamp(),
                               -(records[i].ticket_no or "").__len__()),
            )
            keep_no = records[keep].ticket_no or records[keep].operation_type
            for i in members:
                if i != keep:
                    removed[i] = keep_no

    if not removed:
        return records, []

    kept = [rec for idx, rec in enumerate(records) if idx not in removed]
    skipped = [
        SkippedTicket(
            records[idx].ticket_no or "",
            records[idx].operation_type,
            f"与{keep_no}同日时间重叠，按最高计",
        )
        for idx, keep_no in sorted(removed.items())
    ]
    return kept, skipped


async def build_certificate_map(db: AsyncSession) -> dict[str, str]:
    """从 person_certificates 提取「姓名 → 监护人证书级别」映射。

    **DB 依赖**（非纯函数）：一次性查询 ``cert_category in (guardian_a,
    guardian_b)`` 的活行，``person_name`` 去空白后作键；同名同时持有 A/B 证时
    **A 优先**。工具/Service 层调用，纯函数 builder 不触 DB。
    """
    result = await db.execute(
        select(PersonCertificate.person_name, PersonCertificate.cert_category).where(
            PersonCertificate.is_deleted.is_(False),  # noqa: E712
            PersonCertificate.cert_category.in_(("guardian_a", "guardian_b")),
        )
    )
    cert_map: dict[str, str] = {}
    for person_name, category in result.all():
        key = _normalize_name(person_name)
        if not key:
            continue
        level = _LEVEL_A if category == "guardian_a" else _LEVEL_B
        existing = cert_map.get(key)
        if existing == _LEVEL_A:
            continue  # A 优先：已持有 A 证时不降级
        if existing is None or level == _LEVEL_A:
            cert_map[key] = level
    return cert_map


@dataclass
class UnmatchedGuardian:
    """证书未匹配的监护人（不计入补贴，进待核对页展示）。"""

    name: str
    ticket_count: int
    operation_types: list[str] = field(default_factory=list)


@dataclass
class SkippedTicket:
    """被跳过的作业票（无监护人 / 缺时间 / 未知类型 / 作废）。"""

    ticket_no: str
    ticket_type: str
    reason: str


@dataclass
class ReviewNotes:
    """Excel「待核对/跳过说明」页入参：证书未匹配监护人 + 跳过票清单。

    复用 :class:`UnmatchedGuardian` / :class:`SkippedTicket`（ticket 03 类型），
    由 generate 工具从 ``SubsidyPlan`` 组装，经 ``SubsidyService.export_excel``
    渲染到主表之后的第二页；两个列表均为空等价于不传（单页向后兼容）。
    """

    unmatched: list[UnmatchedGuardian] = field(default_factory=list)
    skipped: list[SkippedTicket] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """是否没有需要列出的待核对/跳过内容。"""
        return not self.unmatched and not self.skipped


@dataclass
class SubsidyPlan:
    """补贴计划：records / unmatched / skipped + 统计。"""

    records: list[SubsidyRecordInput]
    unmatched: list[UnmatchedGuardian]
    skipped: list[SkippedTicket]
    departments: set[str]
    total_tickets: int
    domain_tickets: int
    matched_tickets: int
    unmatched_tickets: int
    skipped_tickets: int

    @property
    def guardian_count(self) -> int:
        """已计入补贴的去重监护人数量。"""
        return len({record.guardian_name for record in self.records})


class SubsidyPlanBuilder:
    """把平台工票列表整理成补贴计划（纯函数，无 DB/网络依赖）。"""

    @staticmethod
    def build(
        tickets: list[WorkTicket],
        certificate_map: dict[str, str],
        dept_keyword: str,
        year: int,
        month: int,
    ) -> SubsidyPlan:
        """按设计 3.2 顺序执行：部门 → 月份 → 作废 → 结束时间 → 无监护人 → 证书 → 类型 → 记录。

        关键语义（P-2/P-3 审查修复）：
        - **skipped 域内口径**：仅在「目标部门」域内判定跳过；非目标部门/
          非目标月票直接忽略，不进入 skipped / unmatched / 预览统计。
        - **按次/块/罐票种缺 end_time 不跳过**：``PER_OCCURRENCE_TYPES``
          （临时用电、抽堵盲板）end_time 为 None 时以 ``start_time`` 兜底
          （按次计费，时长不影响金额）；仍缺 start_time 则跳过（无时间基线）。
        - ``domain_tickets`` = 目标部门 + 目标月命中且非作废的票数
          （不含缺开始时间/域外票；含待核对/无监护人/缺结束时间等）。
          ``total_tickets`` 仍为窗口全局（预览「拉取 N 张」口径）。
        """
        records: list[SubsidyRecordInput] = []
        unmatched: list[UnmatchedGuardian] = []
        skipped: list[SkippedTicket] = []
        departments: set[str] = set()
        unmatched_by_name: dict[str, UnmatchedGuardian] = {}
        unmatched_tickets = 0
        domain_tickets = 0
        keyword = dept_keyword.lower()

        for ticket in tickets:
            if ticket.apply_unit:
                departments.add(ticket.apply_unit.strip())

            # 1. 部门包含匹配（大小写不敏感，中文不受影响）；空 apply_unit → 不命中
            apply_unit = ticket.apply_unit or ""
            if keyword not in apply_unit.lower():
                continue

            # 2. 月份过滤（按开始时间）；缺 start_time → 跳过（已属目标部门域，月不明）
            if ticket.start_time is None:
                skipped.append(SkippedTicket(ticket.ticket_no, ticket.ticket_type, _REASON_MISSING_START))
                continue
            if ticket.start_time.year != year or ticket.start_time.month != month:
                continue

            # 3. 作废票跳过（目标部门+目标月域内）
            if ticket.is_void:
                skipped.append(SkippedTicket(ticket.ticket_no, ticket.ticket_type, _REASON_VOID))
                continue

            domain_tickets += 1  # 目标部门 + 目标月命中（非 void）

            # 4. 作业类型中文标签（提前取值：按次计费兜底判定用；未知名在证书匹配后跳过）
            operation_type = _OP_TYPE_LABEL.get(ticket.ticket_type)

            # 5. 结束时间：按次/块/罐计费票种缺 end_time → 以 start_time 兜底
            end_time = ticket.end_time
            if end_time is None:
                if operation_type in PER_OCCURRENCE_TYPES:
                    end_time = ticket.start_time
                else:
                    skipped.append(SkippedTicket(ticket.ticket_no, ticket.ticket_type, _REASON_MISSING_END))
                    continue

            # 6. 无监护人跳过
            if not ticket.guardian or not ticket.guardian.strip():
                skipped.append(SkippedTicket(ticket.ticket_no, ticket.ticket_type, _REASON_NO_GUARDIAN))
                continue

            guardian_name = _normalize_name(ticket.guardian)
            if not guardian_name:
                skipped.append(SkippedTicket(ticket.ticket_no, ticket.ticket_type, _REASON_NO_GUARDIAN))
                continue

            # 7. 证书匹配（未匹配 → 待核对，不计金额）
            level = certificate_map.get(guardian_name)
            if level is None:
                unmatched_tickets += 1
                op_label = operation_type or ticket.ticket_type
                entry = unmatched_by_name.get(guardian_name)
                if entry is None:
                    entry = UnmatchedGuardian(name=guardian_name, ticket_count=0)
                    unmatched_by_name[guardian_name] = entry
                    unmatched.append(entry)
                entry.ticket_count += 1
                if op_label not in entry.operation_types:
                    entry.operation_types.append(op_label)
                continue

            # 8. 作业类型中文标签（未知名跳过）
            if operation_type is None:
                skipped.append(SkippedTicket(ticket.ticket_no, ticket.ticket_type, _REASON_UNKNOWN_OP))
                continue

            # 9. 构造补贴记录（地点+内容拼接容忍空；间隔恒 0）
            location_content = f"{ticket.work_site or ''} {ticket.work_content or ''}".strip()
            records.append(
                SubsidyRecordInput(
                    guardian_name=guardian_name,
                    guardian_level=level,
                    ticket_no=ticket.ticket_no or None,
                    department=ticket.apply_unit or None,
                    operation_type=operation_type,
                    operation_level=ticket.level or "",
                    location_content=location_content,
                    start_time=ticket.start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    interval_hours="0",
                )
            )

        # 10. 同监护人同日重叠去重：一次作业多张票只按补贴最高的一张计。
        #     归组 = 同监护人 + 同开始日期 + 时间区间重叠（连通分量）；
        #     组内保留 subsidy_amount 最高者，其余移入 skipped（透明可查）。
        records, dedup_skipped = _dedup_overlapping_records(records)
        skipped.extend(dedup_skipped)

        return SubsidyPlan(
            records=records,
            unmatched=unmatched,
            skipped=skipped,
            departments=departments,
            total_tickets=len(tickets),
            domain_tickets=domain_tickets,
            matched_tickets=len(records),
            unmatched_tickets=unmatched_tickets,
            skipped_tickets=len(skipped),
        )


__all__ = [
    "SubsidyPlan",
    "SubsidyPlanBuilder",
    "UnmatchedGuardian",
    "SkippedTicket",
    "ReviewNotes",
    "build_certificate_map",
    "_OP_TYPE_LABEL",
]
