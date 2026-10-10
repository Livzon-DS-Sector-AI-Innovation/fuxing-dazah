"""作业票外包人员直读筛查（票面人员 × 平台承包商台账，纯内存比对，零落库）。

数据链路（2026-09-28 实测打通）：
- 票面人员：作业票 detail 的 ``process.variables`` 人员子表。动火票为文本行
  （人员类型/姓名/特种作业证件号，复用 parser 已登记键列）；高处/吊装为
  人员选择器行（原始值为平台人员 id，``$`` 前缀为显示姓名）。
- 承包商台账：``WorkTicketPlatformClient.list_contractor_users``（master-data
  ``client/contractor-user/all-page``），雪花 id 与票面人员选择器 id 同源
  （何胜案例两处同为 2066813165726253069），可 ID 精确匹配。

匹配口径：
- 选择器 id 为雪花长码（>= _SNOWFLAKE_ID_THRESHOLD）→ 台账按 id 精确匹配；
- 选择器 id 为小数字（内部员工账号，如 "8212"）→ internal_user，不比对台账；
- 无 id 的文本行（动火票）→ 按姓名匹配：1 条命中（name_matched，弱匹配）、
  0 条未命中（not_registered，可能为内部人员或未录入实名台账）、多条同名
  （ambiguous，列出候选供人工核对）。

边界约定：
- **零落库**：不写任何数据库表，不写平台，不推送；结果即用即弃。
- 敏感信息（身份证号/手机号）在结果构造时即打码（mask_secret），下游无明文。
- 覆盖票种 = PERSONNEL_SUBFORM_KEYS 登记的票种（受限空间/临时用电/动土/
  盲板经 2026-09-28 抽样确认无人员子表，不在筛查范围）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.safety.workticket_review.client import WorkTicketPlatformClient
from app.modules.safety.workticket_review.parser import (
    PERSONNEL_ARRAY_KEYS,
    PERSONNEL_COLUMNS,
    _as_text,
    _field_display_value,
)

logger = logging.getLogger(__name__)

# 各票种人员子表数组键（动火 = parser 已登记键；高处/吊装 = 2026-09-28 实测辨认，
# 吊装两张子表分别为起重机指挥与司机）
PERSONNEL_SUBFORM_KEYS: dict[str, tuple[str, ...]] = {
    "hot_work": (PERSONNEL_ARRAY_KEYS["hot_work"],),
    "height_work": ("a177848463469993852",),
    "lifting": ("a178149178305678016", "a17784882584521751"),
}

# 雪花 id 阈值：>= 该量级视为承包商台账同源的人员 id；小数字为内部员工账号 id
_SNOWFLAKE_ID_THRESHOLD = 10**12

# 选择器 id 最短长度（过滤掉 _index 之类的短数值列）
_MIN_PICKER_ID_LEN = 4

# 筛查窗口防御上限（天）：防误传大窗口打爆平台分页
_MAX_WINDOW_DAYS = 31

# 结果状态常量（对外口径，勿改字符串）
STATUS_ID_MATCHED = "id_matched"
STATUS_NAME_MATCHED = "name_matched"
STATUS_NOT_REGISTERED = "not_registered"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_INTERNAL_USER = "internal_user"

_ABNORMAL_STATUSES = (STATUS_NOT_REGISTERED, STATUS_AMBIGUOUS)


def mask_secret(value: str | None) -> str:
    """敏感字段打码：保前 3 后 2，过短全遮。"""
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-2:]}"


@dataclass(frozen=True)
class TicketPerson:
    """从票面人员子表抽出的一行人员（统一视图）。"""

    name: str
    person_id: str | None = None  # 选择器原始 id；动火文本行为 None
    role: str = ""  # 动火行的人员类型（普工/特种作业人员）
    cert_no: str = ""  # 动火行的特种作业证件号


def _extract_hot_work_persons(variables: dict[str, Any]) -> list[TicketPerson]:
    """动火票：文本人员子表（复用 parser 已登记键列，取 $ 显示值优先）。"""
    rows = variables.get(PERSONNEL_ARRAY_KEYS.get("hot_work", ""))
    if not isinstance(rows, list):
        return []
    columns = PERSONNEL_COLUMNS.get("hot_work", {})
    persons: list[TicketPerson] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role = _as_text(_field_display_value(row, columns.get("role", ""))) or ""
        name = _as_text(_field_display_value(row, columns.get("name", ""))) or ""
        cert_no = _as_text(_field_display_value(row, columns.get("cert_no", ""))) or ""
        if name:
            persons.append(TicketPerson(name=name, role=role, cert_no=cert_no))
    return persons


def _extract_picker_persons(
    variables: dict[str, Any],
    array_keys: tuple[str, ...],
) -> list[TicketPerson]:
    """选择器型人员子表（高处/吊装）：扫行内「纯数字值 + $ 显示中文名」的列。

    不依赖列业务语义（同一子表内「人员/监护人」等多列选择器一并收），
    同一 (name, person_id) 去重；显示值为纯数字/无汉字的列（证件号列）
    天然被「显示值须含汉字」条件排除。
    """
    persons: list[TicketPerson] = []
    seen: set[tuple[str, str | None]] = set()
    for key in array_keys:
        rows = variables.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for col, val in row.items():
                if col.startswith("$") or not isinstance(val, str):
                    continue
                if not val.isdigit() or len(val) < _MIN_PICKER_ID_LEN:
                    continue
                disp = row.get(f"${col}")
                if not isinstance(disp, str) or not any(
                    "\u4e00" <= ch <= "\u9fff" for ch in disp
                ):
                    continue
                ident = (disp, val)
                if ident in seen:
                    continue
                seen.add(ident)
                persons.append(TicketPerson(name=disp, person_id=val))
    return persons


def extract_ticket_persons(
    ticket_type: str,
    variables: dict[str, Any],
) -> list[TicketPerson]:
    """按票种抽取票面人员行；未登记人员子表的票种返回 []。"""
    if ticket_type == "hot_work":
        return _extract_hot_work_persons(variables)
    keys = PERSONNEL_SUBFORM_KEYS.get(ticket_type)
    if not keys:
        return []
    return _extract_picker_persons(variables, keys)


def _registry_profile(row: dict[str, Any]) -> dict[str, Any]:
    """台账档案的输出形态（敏感字段打码）。"""
    return {
        "name": row.get("name", ""),
        "contractor_name": row.get("contractorName", ""),
        "work_type": row.get("workTypeName", ""),
        "card_no_masked": mask_secret(row.get("cardNo") or None),
        "phone_masked": mask_secret(row.get("telphone") or None),
    }


class ContractorPersonnelScreeningService:
    """直读筛查编排：拉票 + 拉台账 + 内存比对，一次调用一套结果。"""

    def __init__(self, client: WorkTicketPlatformClient | None = None) -> None:
        self._client = client

    async def screen(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """筛查 [start_date, end_date] 窗口内作业票的票面人员。

        Returns:
            见模块 docstring 的口径；``abnormal`` 仅含 not_registered /
            ambiguous 两类需人工跟进的条目。

        Raises:
            ValueError: 窗口为空或超过 _MAX_WINDOW_DAYS。
            RuntimeError: 平台拉取失败（凭证失效/接口异常）。
        """
        if end_date < start_date:
            raise ValueError(f"筛查窗口无效：end {end_date} < start {start_date}")
        if (end_date - start_date).days + 1 > _MAX_WINDOW_DAYS:
            raise ValueError(
                f"筛查窗口超过 {_MAX_WINDOW_DAYS} 天上限，请缩小范围"
            )

        owns = self._client is None
        client = self._client or WorkTicketPlatformClient()
        try:
            records = await client.list_tickets_for_date_range(start_date, end_date)
            registry = await client.list_contractor_users()
        finally:
            if owns:
                await client.close()

        id_index: dict[str, dict[str, Any]] = {}
        name_index: dict[str, list[dict[str, Any]]] = {}
        for row in registry:
            rid = str(row.get("id") or "")
            if rid:
                id_index[rid] = row
            rname = str(row.get("name") or "")
            if rname:
                name_index.setdefault(rname, []).append(row)

        stats = {
            STATUS_ID_MATCHED: 0,
            STATUS_NAME_MATCHED: 0,
            STATUS_NOT_REGISTERED: 0,
            STATUS_AMBIGUOUS: 0,
            STATUS_INTERNAL_USER: 0,
        }
        per_ticket: list[dict[str, Any]] = []
        abnormal: list[dict[str, Any]] = []
        types_scanned: dict[str, int] = {}
        person_rows = 0

        for record in records:
            ticket_type = str(record.get("type") or "")
            types_scanned[ticket_type] = types_scanned.get(ticket_type, 0) + 1
            variables = record.get("variables") or {}
            persons = extract_ticket_persons(ticket_type, variables)
            if not persons:
                continue
            person_rows += len(persons)

            ticket_no = str(record.get("serialNumber") or "")
            person_results: list[dict[str, Any]] = []
            for person in persons:
                status, registry_row, candidates = self._match(
                    person, id_index, name_index
                )
                stats[status] += 1
                entry: dict[str, Any] = {
                    "name": person.name,
                    "status": status,
                }
                if person.role:
                    entry["role"] = person.role
                if person.cert_no:
                    entry["cert_no_masked"] = mask_secret(person.cert_no)
                if registry_row is not None:
                    entry["registry"] = _registry_profile(registry_row)
                if candidates:
                    entry["candidates"] = [
                        _registry_profile(c) for c in candidates[:5]
                    ]
                person_results.append(entry)
                if status in _ABNORMAL_STATUSES:
                    abnormal.append(
                        {
                            "ticket_no": ticket_no,
                            "ticket_type": ticket_type,
                            "person": person.name,
                            "status": status,
                            **({"candidates": entry["candidates"]} if candidates else {}),
                        }
                    )

            per_ticket.append(
                {
                    "ticket_no": ticket_no,
                    "ticket_type": ticket_type,
                    "persons": person_results,
                }
            )

        result = {
            "success": True,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
            "registry_total": len(registry),
            "tickets_scanned": len(records),
            "tickets_with_personnel": len(per_ticket),
            "ticket_types_scanned": types_scanned,
            "covered_types": sorted(PERSONNEL_SUBFORM_KEYS),
            "person_rows": person_rows,
            "stats": stats,
            "abnormal": abnormal,
            "per_ticket": per_ticket,
        }
        logger.info(
            "人员直读筛查完成：窗口 %s~%s，票 %d（含人员 %d），台账 %d 人，"
            "未命中 %d / 同名 %d",
            start_date,
            end_date,
            len(records),
            len(per_ticket),
            len(registry),
            stats[STATUS_NOT_REGISTERED],
            stats[STATUS_AMBIGUOUS],
        )
        return result

    @staticmethod
    def _match(
        person: TicketPerson,
        id_index: dict[str, dict[str, Any]],
        name_index: dict[str, list[dict[str, Any]]],
    ) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
        """单行人员比对，返回 (状态, 命中台账行, 同名候选行)。"""
        pid = person.person_id
        if pid:
            if pid.isdigit() and int(pid) < _SNOWFLAKE_ID_THRESHOLD:
                return STATUS_INTERNAL_USER, None, []
            hit = id_index.get(pid)
            if hit is not None:
                return STATUS_ID_MATCHED, hit, []
            return STATUS_NOT_REGISTERED, None, []
        hits = name_index.get(person.name, [])
        if len(hits) == 1:
            return STATUS_NAME_MATCHED, hits[0], []
        if not hits:
            return STATUS_NOT_REGISTERED, None, []
        return STATUS_AMBIGUOUS, None, hits
