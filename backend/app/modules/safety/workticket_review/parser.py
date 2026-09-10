"""作业票解析器（WorkTicketParser）。

把工作流原始 variables（含子表/子表单数组）按《作业票字段映射.md》归一化为规范 WorkTicket，
隔离平台字段变化对规则引擎的影响。时间统一转为 Asia/Shanghai aware datetime。

字段 ID 集中维护在本文件常量中，平台调整字段时只需改这里。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.workticket_review.client import TICKET_TYPE_KEYS

TZ = ZoneInfo("Asia/Shanghai")

# ── 语义字段 → fieldId（来自 作业票字段映射.md / grill-notes 2026-09-01 实测） ──
# 键：apply_time / approve_time / start_time / end_time / finish_time /
#     level / work_site / work_content / guardian / apply_unit
# work_site / work_content 的 fieldId 由真实平台数据探查得出（2026-08-27）；
# 动土/断路/盲板抽堵三类近期无票，work_site / work_content 字段 ID 暂缺；
# guardian / apply_unit 8 类票 fieldId 由 start-form-properties 实测确认（grill-notes.md）。
FIELD_MAP: dict[str, dict[str, str]] = {
    "hot_work": {
        "apply_time": "a165650258429577527",
        "approve_time": "a166419575104497385",
        "start_time": "a166452480843974469",
        "end_time": "a170041634227259322",
        "finish_time": "a165630881894418049",
        "level": "a165650253075756898",
        "work_site": "a165630293247793609",
        "work_content": "a17004237047999564",
        "guardian": "a170252536882522756",
        "apply_unit": "a165630121327216736",
        "mode": "a165630136371848108",
    },
    "confined_space": {
        "apply_time": "a16641060774353234",
        "approve_time": "a166410758162945511",
        "start_time": "a166453188464160986",
        "end_time": "a170042229891083000",
        "finish_time": "a166410776737522241",
        "work_site": "a166410609024835397",
        "work_content": "a166410613064325902",
        "guardian": "a166410620739930378",
        "apply_unit": "a166410606207583945",
    },
    "height_work": {
        "apply_time": "a166408729356021698",
        "approve_time": "a166436843500716619",
        "start_time": "a166452791850159946",
        "end_time": "a177848359402613260",
        "finish_time": "a166409624671435562",
        "level": "a16640875432179735",
        "work_site": "a166408737588058926",
        "work_content": "a177864973070780254",
        "guardian": "a166408791521312347",
        "apply_unit": "a166408724179080906",
    },
    "lifting": {
        "apply_time": "a166408729356021698",
        "approve_time": "a166411175918929660",
        "start_time": "a166479946544515540",
        "end_time": "a177848849477682484",
        "finish_time": "a166409624671435562",
        "level": "a169269029480488045",
        "work_site": "a166408737588058926",
        "work_content": "a166408741502483696",
        "guardian": "a166408791521312347",
        "apply_unit": "a166408724179080906",
    },
    "temporary_electricity": {
        "apply_time": "a166383861113656766",
        "approve_time": "a177848303150752064",
        "start_time": "a170041805999891768",
        "end_time": "a170041805749718609",
        "finish_time": "a166410489854421267",
        "work_site": "a166409978406846947",
        "work_content": "a166383875593414023",
        "guardian": "a16641028864938014",
        "apply_unit": "a166383857539164012",
    },
    "excavation": {
        "apply_time": "a166408729356021698",
        "approve_time": "a166479736368110262",
        "start_time": "a166452913254510286",
        "end_time": "a177855271968335527",
        "finish_time": "a166409624671435562",
        "guardian": "a166408791521312347",
        "apply_unit": "a166408724179080906",
        # work_site / work_content 待有真实票后补 fieldId。
    },
    "road_breaking": {
        "apply_time": "a17785549722689677",
        "approve_time": "a166420312995199239",
        "start_time": "a166478570334536959",
        "end_time": "a170042270360247393",
        "finish_time": "a166409624671435562",
        "guardian": "a166408791521312347",
        "apply_unit": "a166408724179080906",
        # work_site / work_content 待有真实票后补 fieldId。
    },
    "blind_plate": {
        "apply_time": "a170042282670256499",
        "approve_time": "a177849085922113675",
        "start_time": "a170042295009091843",
        "guardian": "a166411393618150378",
        "apply_unit": "a166410983710826629",
        # 盲板抽堵无单一「结束/验收」字段，end_time / finish_time 无映射。
        # work_site / work_content 待有真实票后补 fieldId。
    },
}

# 无气体分析子表的类型
GASLESS_TYPES: frozenset[str] = frozenset({
    "height_work",
    "blind_plate",
    "excavation",
    "road_breaking",
    "lifting",
})

# 气体分析子表单数组键（动火/受限/临电）
GAS_ARRAY_KEYS: dict[str, str] = {
    "hot_work": "a172363237973025304",
    "confined_space": "a166410665378134029",
    "temporary_electricity": "a177848236214587756",
}

# 气体子表列映射（列 fieldId：time/gas_name/point/value/operator/O2/CO/H2S/LEL/flam）
GAS_COLUMNS: dict[str, dict[str, str]] = {
    "hot_work": {
        "time": "a172363239131846707",
        "gas_name": "a178209307785154295",
        "point": "a172363241848930141",
        "value": "a178105953631186497",
        "operator": "a172363244087761084",
        "LEL": "a178105953631186497",
        "flam": "a178105953631186497",
    },
    "confined_space": {
        "time": "a16645280308068256",
        "point": "a178123009097044840",
        "operator": "a166452702345263",
        "CO": "a178122990256724485",
        "H2S": "a178151594361358704",
        "LEL": "a17812299375743341",
        "flam": "a17812299375743341",
        "O2": "a178122997925123872",
    },
    "temporary_electricity": {
        "time": "a177848237194078709",
        "point": "a177848239637796101",
        "value": "a178107199973030298",
        "operator": "a177848241621543172",
        "LEL": "a178107199973030298",
        "flam": "a178107199973030298",
    },
}

# 人员子表单数组键（动火实测 2026-09-08；其他票种表单未探查，待有票后补）
PERSONNEL_ARRAY_KEYS: dict[str, str] = {
    "hot_work": "a167100942578186627",
}

# 人员子表列映射（列 fieldId：role=人员类型 / name=作业人员 / cert_no=特种作业证件）
PERSONNEL_COLUMNS: dict[str, dict[str, str]] = {
    "hot_work": {
        "role": "a177848145226757987",
        "name": "a167100943924123367",
        "cert_no": "a170252523934992609",
    },
}

_TIME_FIELDS: tuple[str, ...] = (
    "apply_time",
    "approve_time",
    "start_time",
    "end_time",
    "finish_time",
)


@dataclass
class GasRecord:
    """单行气体分析记录（归一化为通用字段 + 原始行）。"""

    analysis_time: datetime | None = None
    point: str | None = None
    gas_name: str | None = None
    value: str | None = None
    operator: str | None = None
    o2: str | None = None
    co: str | None = None
    h2s: str | None = None
    lel: str | None = None
    flam: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def location(self) -> str | None:
        """兼容字段映射中的「分析点/部位」叫法。"""
        return self.point


@dataclass
class PersonnelRecord:
    """单行作业人员记录（人员子表归一化，列取 $ 显示值优先）。"""

    role: str = ""
    name: str = ""
    cert_no: str = ""


@dataclass
class WorkTicket:
    """规范化工票（原始工作流 variables → 本结构）。"""

    ticket_type: str
    ticket_no: str = ""
    process_instance_id: str = ""
    apply_time: datetime | None = None
    approve_time: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    finish_time: datetime | None = None
    level: str | None = None
    work_site: str | None = None
    work_content: str | None = None
    work_mode: str | None = None
    guardian: str = ""
    apply_unit: str = ""
    gas_analysis: list[GasRecord] = field(default_factory=list)
    personnel: list[PersonnelRecord] = field(default_factory=list)
    gasless: bool = False
    missing: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    create_time: datetime = field(default_factory=lambda: datetime.now(TZ))
    status: str = ""
    @property
    def is_void(self) -> bool:
        """废案判定：流程已终止(wf_process_terminate=true) 或 几乎无任何信息。"""
        raw = self.raw or {}
        vars_: Any = raw.get("variables") if isinstance(raw.get("variables"), dict) else raw
        if str(vars_.get("wf_process_terminate", "") or raw.get("wf_process_terminate", "")).lower() == "true":
            return True
        has_info = any([
            self.ticket_no, self.apply_time, self.approve_time, self.start_time,
            self.end_time, self.finish_time, self.level, self.work_site,
            self.work_content, self.gas_analysis,
        ])
        return not has_info


def _as_text(value: Any) -> str | None:
    """把值转成去空格字符串；空值/None 返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_NAME_SEPARATORS = re.compile(r"[\s\u3000,，、;；/|]+")


def _field_display_value(variables: dict[str, Any], field_id: str) -> Any:
    """取平台变量值：优先 `$<fieldId>` 显示值，缺失/为空时回退 `<fieldId>` 原始值。

    start-form-properties 实测同时返回 `a...`（原始值）与 `$a...`（中文显示值），
    人员/单位字段尤其需要显示值（原始值可能是内部 id）。
    """
    if not field_id:
        return None
    shown = variables.get(f"${field_id}")
    if shown is not None and str(shown).strip():
        return shown
    return variables.get(field_id)


# ── level 归一化（对齐 service/subsidy.py 的 SUBSIDY_RATES 键形：特级/一级/二级/三级/四级） ──
_LEVEL_CANONICAL: frozenset[str] = frozenset({"特级", "一级", "二级", "三级", "四级"})

# 括注剥离：'Ⅰ级（2≤h≤5m）' → 'Ⅰ级'；'一级(特种设备)' → '一级'
_LEVEL_PAREN_RE = re.compile(r"[（(【\[][^（()）\[\]【】]*[）)】\]]")

# 前缀清洗：'作业级别：二级' / '级别二级' / '动火级别：一级' → 裸级别
_LEVEL_PREFIX_RE = re.compile(
    r"^(?:作业|危险|票种|特殊作业|动火|登高|高处|吊装)?(?:级别|等级)\s*[:：\-—_—]*"
)

# 数字/罗马数字 → 中文数字（长 token 优先，避免 'II级' 被拆成 'I'+'I'）
_LEVEL_NUMERALS: dict[str, str] = {
    "Ⅴ": "五", "Ⅳ": "四", "Ⅲ": "三", "Ⅱ": "二", "Ⅰ": "一",
    "ⅴ": "五", "ⅳ": "四", "ⅲ": "三", "ⅱ": "二", "ⅰ": "一",
    "V": "五", "IV": "四", "III": "三", "II": "二", "I": "一",
    "v": "五", "iv": "四", "iii": "三", "ii": "二", "i": "一",
    "５": "五", "４": "四", "３": "三", "２": "二", "１": "一",
    "5": "五", "4": "四", "3": "三", "2": "二", "1": "一",
    "五": "五", "四": "四", "三": "三", "二": "二", "一": "一",
}


def _normalize_level(value: str | None) -> str:
    """把作业票级别归一化为 SUBSIDY_RATES 键形（特级/一级/二级/三级/四级）。

    平台返回的 level 可能形态（2026-08-31 E2E 实测 + 设计 3.1）：
      - 内部编号：'1' / '2' / '3'（动火/高处/吊装实测）；
      - 罗马数字/阿拉伯数字：'Ⅰ级（2≤h≤5m）'、'II级'、'1级'、'I 级'；
      - 已中文化：'二级'、'特级'（原样通过）；
      - 带前缀：'作业级别：二级'、'级别 二级'。
    处理顺序：空白去除 → 剥离括注 → 前缀清洗 → 特级/规范中文直通 →
    数字/罗马字典映射。无法识别（含无费率的五级）返回 ''，由补贴侧走默认费率。
    """
    if value is None:
        return ""
    text = "".join(str(value).split())
    if not text:
        return ""
    text = _LEVEL_PAREN_RE.sub("", text)
    if not text:
        return ""
    text = _LEVEL_PREFIX_RE.sub("", text)
    text = "".join(text.split())
    if not text:
        return ""
    if text in _LEVEL_CANONICAL:
        return text
    if text in ("特", "特殊"):
        return "特级"
    # 长 token 优先匹配：'II级' → token 'II' 非 'I'
    for token, cn in sorted(_LEVEL_NUMERALS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if text.startswith(token) and text[len(token):] in ("", "级", "等级"):
            if cn == "五":
                return ""  # 无五级费率，走默认
            return f"{cn}级"
    return ""


def _extract_person_name(value: Any) -> str:
    """从平台「监护人」字段值容错抽取单个姓名。

    可能形态：
      - str：名单文本（可能含空格/逗号/顿号等分隔，取第一位）；空串返回 ""；
      - list/tuple：递归抽取第一个可解析元素；
      - dict：取 name/text/label/value 键。
    无法解析时返回 ""。
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("name", "text", "label", "value"):
            if key in value:
                name = _extract_person_name(value[key])
                if name:
                    return name
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            name = _extract_person_name(item)
            if name:
                return name
        return ""
    text = str(value).strip()
    if not text:
        return ""
    parts = [part.strip() for part in _NAME_SEPARATORS.split(text) if part.strip()]
    return parts[0] if parts else ""


def _as_list(value: Any) -> list[Any]:
    """从变量值中尽量抽取列表（子表单数组可能以多种结构返回）。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
    if isinstance(value, dict):
        for key in ("list", "records", "rows", "data", "items", "values"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def _parse_datetime(value: Any) -> datetime | None:
    """把字符串/毫秒时间戳/数字/datetime 统一转为 Asia/Shanghai aware datetime。"""
    if value is None:
        return None
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=TZ)
        except (OSError, OverflowError, ValueError):
            dt = None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            return _parse_datetime(float(text))
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                except ValueError:
                    continue
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
    if dt is None:
        return None
    return dt.astimezone(TZ)


def _resolve_type_key(type_key: str) -> str:
    """解析 ticket_type：接受英文枚举或平台 processDefinitionKey。"""
    if type_key in FIELD_MAP:
        return type_key
    for ticket_type, process_key in TICKET_TYPE_KEYS.items():
        if process_key == type_key:
            return ticket_type
    return type_key


def _get_variables(record: dict[str, Any]) -> dict[str, Any]:
    """从记录中抽取 variables 字典。"""
    if isinstance(record, dict):
        variables = record.get("variables")
        if isinstance(variables, dict):
            return variables
        variables = record.get("formVariables")
        if isinstance(variables, dict):
            return variables
        return record
    return {}


class WorkTicketParser:
    """归一化原始 variables → WorkTicket。"""

    def normalize(self, record: dict[str, Any], type_key: str) -> WorkTicket:
        """把一条平台记录归一化为 WorkTicket。

        record 需包含 variables（至少），可选 processInstanceId / serialNumber /
        createTime / status；type_key 为英文枚举（如 hot_work）或 processDefinitionKey。
        """
        ticket_type = _resolve_type_key(type_key)
        variables = _get_variables(record)
        field_map = FIELD_MAP.get(ticket_type, {})

        missing: list[str] = []

        def _field(name: str) -> Any:
            field_id = field_map.get(name, "")
            if not field_id:
                return None
            return variables.get(field_id)

        times: dict[str, datetime | None] = {}
        for name in _TIME_FIELDS:
            parsed = _parse_datetime(_field(name))
            times[name] = parsed
            if parsed is None:
                missing.append(name)

        # level：优先 $<fieldId> 显示值（如 'Ⅰ级（2≤h≤5m）'），回退原始值，
        # 再归一化为 SUBSIDY_RATES 键形；无法识别 → ''（走默认费率，不误改 missing）。
        level_raw = self._none_or_text(
            _field_display_value(variables, field_map.get("level", ""))
        )
        level = _normalize_level(level_raw) if level_raw is not None else None
        if field_map.get("level") and level is None:
            missing.append("level")

        work_site = self._none_or_text(_field_display_value(variables, field_map.get("work_site", "")))
        work_content = self._none_or_text(_field_display_value(variables, field_map.get("work_content", "")))
        if field_map.get("work_site") and work_site is None:
            missing.append("work_site")
        if field_map.get("work_content") and work_content is None:
            missing.append("work_content")

        # work_mode（动火方式）：缺失不写 missing（guardian 同理，由规则自行判定数据不足）
        work_mode = self._none_or_text(_field_display_value(variables, field_map.get("mode", "")))

        # guardian / apply_unit 缺失**不**写入 missing（missing 已被作业票审核规则
        # 引擎消费，追加会污染既有功能）；缺失语义由补贴侧 SubsidyPlanBuilder 诊断。
        guardian = _extract_person_name(
            _field_display_value(variables, field_map.get("guardian", ""))
        )
        apply_unit = (
            _as_text(
                _field_display_value(variables, field_map.get("apply_unit", ""))
            )
            or ""
        )

        ticket_no = self._pick_ticket_no(record, variables)
        process_instance_id = str(
            record.get("processInstanceId")
            or record.get("processInstanceID")
            or record.get("id")
            or ""
        )
        create_time = _parse_datetime(record.get("createTime")) or datetime.now(TZ)
        status = str(record.get("status") or "")

        gas_analysis, gasless = self._parse_gas(ticket_type, variables, missing)
        personnel = self._parse_personnel(ticket_type, variables)

        missing = list(dict.fromkeys(missing))

        return WorkTicket(
            ticket_type=ticket_type,
            ticket_no=ticket_no,
            process_instance_id=process_instance_id,
            apply_time=times["apply_time"],
            approve_time=times["approve_time"],
            start_time=times["start_time"],
            end_time=times["end_time"],
            finish_time=times["finish_time"],
            level=level,
            work_site=work_site,
            work_content=work_content,
            work_mode=work_mode,
            guardian=guardian,
            apply_unit=apply_unit,
            gas_analysis=gas_analysis,
            personnel=personnel,
            gasless=gasless,
            missing=missing,
            raw=dict(record),
            create_time=create_time,
            status=status,
        )

    @staticmethod
    def _none_or_text(value: Any) -> str | None:
        return _as_text(value)

    def _pick_ticket_no(self, record: dict[str, Any], variables: dict[str, Any]) -> str:
        value = (
            record.get("serialNumber")
            or record.get("serialNo")
            or record.get("ticketNo")
            or record.get("businessKey")
            or record.get("processInstanceCode")
            or variables.get("serialNumber")
            or variables.get("ticketNo")
            or ""
        )
        return str(value)

    def _parse_gas(
        self,
        ticket_type: str,
        variables: dict[str, Any],
        missing: list[str],
    ) -> tuple[list[GasRecord], bool]:
        """解析气体子表；无气体类型返回 ([], True)。"""
        array_key = GAS_ARRAY_KEYS.get(ticket_type)
        if not array_key:
            return [], True

        rows = _as_list(variables.get(array_key))
        if not rows:
            missing.append("gas_analysis")
            return [], False

        records: list[GasRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            gas = self._parse_gas_row(ticket_type, row)
            if gas.analysis_time is not None:
                records.append(gas)

        if not records:
            missing.append("gas_analysis")
        return records, False

    def _parse_personnel(
        self,
        ticket_type: str,
        variables: dict[str, Any],
    ) -> list[PersonnelRecord]:
        """解析人员子表；无该子表的类型/缺数组返回 []（缺失语义由规则五判定）。"""
        array_key = PERSONNEL_ARRAY_KEYS.get(ticket_type)
        if not array_key:
            return []

        rows = _as_list(variables.get(array_key))
        columns = PERSONNEL_COLUMNS.get(ticket_type, {})

        records: list[PersonnelRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            def col(name: str) -> Any:
                return _field_display_value(row, columns.get(name, ""))

            records.append(
                PersonnelRecord(
                    role=_as_text(col("role")) or "",
                    name=_as_text(col("name")) or "",
                    cert_no=_as_text(col("cert_no")) or "",
                )
            )
        return records

    def _parse_gas_row(self, ticket_type: str, row: dict[str, Any]) -> GasRecord:
        columns = GAS_COLUMNS.get(ticket_type, {})

        def col(name: str) -> Any:
            field_id = columns.get(name)
            if not field_id:
                return None
            return row.get(field_id)

        gas = GasRecord(
            analysis_time=_parse_datetime(col("time")),
            point=_as_text(col("point")),
            gas_name=_as_text(col("gas_name")),
            value=_as_text(col("value")),
            operator=_as_text(col("operator")),
            o2=_as_text(col("O2")),
            co=_as_text(col("CO")),
            h2s=_as_text(col("H2S")),
            lel=_as_text(col("LEL")),
            flam=_as_text(col("flam")),
            raw=dict(row),
        )
        return gas


__all__ = [
    "TZ",
    "FIELD_MAP",
    "GAS_ARRAY_KEYS",
    "GAS_COLUMNS",
    "GASLESS_TYPES",
    "PERSONNEL_ARRAY_KEYS",
    "PERSONNEL_COLUMNS",
    "GasRecord",
    "PersonnelRecord",
    "WorkTicket",
    "WorkTicketParser",
]
