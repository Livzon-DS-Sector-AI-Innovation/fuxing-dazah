"""员工档案多维表格同步配置（SystemSetting KV 存储，无独立表）。

绑定信息（app_token / 数据表 id）与运行状态（上次同步时间/统计）都存
hr.system_settings 键值表，改绑定无需改代码或重启服务。
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SystemSetting

logger = logging.getLogger(__name__)

# ── KV 键 ──
KEY_ENABLED = "employee_sync.enabled"
KEY_APP_TOKEN = "employee_sync.app_token"
KEY_SOURCE_TABLE_ID = "employee_sync.source_table_id"
KEY_SOURCE_TABLE_NAME = "employee_sync.source_table_name"
# 定编数表（可选附加同步：与员工档案同一 Base，一次同步顺带拉取）
KEY_HEADCOUNT_TABLE_ID = "employee_sync.headcount_table_id"
KEY_HEADCOUNT_TABLE_NAME = "employee_sync.headcount_table_name"
# 离职人员管理表（可选附加同步：同 Base，写入 hr.departure_records 离职台账）
KEY_DEPARTURE_TABLE_ID = "employee_sync.departure_table_id"
KEY_DEPARTURE_TABLE_NAME = "employee_sync.departure_table_name"
KEY_LAST_SYNC_AT = "employee_sync.last_sync_at"
KEY_LAST_STATS = "employee_sync.last_stats"
# 培训名单字段「跟随档案」规则（全局字段 + 按工号例外），JSON 存储
KEY_ROSTER_FOLLOW = "employee_sync.roster_follow_config"

# ── 培训专用脱敏名单 ──
# 白名单：显示列名 → ORM 字段（key 兼作前端表头）。系统内培训人员名单接口
# 只输出这些字段；专业/学校/身份证/出生/籍贯/政治面貌/婚姻/户籍/银行卡/
# 联系方式/紧急联系人/合同/性别/级别/域账号/调动历史/备注等一律不输出。
TRAINING_ROSTER_FIELDS: dict[str, str] = {
    "工号": "employee_number",
    "姓名": "name",
    "体现部门": "department",
    "部门": "actual_department",
    "班组": "team",
    "职位": "position",
    "职务": "duty",
    "岗位类别": "job_category",
    "品种": "variety",
    "兼任部门": "concurrent_departments",
    "兼任品种": "concurrent_variety",
    # 教育信息（用户确认保留；学校/专业仍脱敏，需要时在系统内使用全量数据）
    "学历": "education",
    "毕业时间": "graduation_date",
    "用工性质": "status_category",
    "人员状态": "status",
    "参加工作时间": "work_start_date",
    "进厂时间": "factory_entry_date",
    "进丽珠时间": "livo_entry_date",
    "入职日期": "hire_date",
    "离职时间": "departure_date",
    # 资质与培训
    "证书": "certificates",
    "资格": "qualifications",
    "培训编号": "training_id",
    "部门负责人/一级培训师": "dept_head_trainer",
    "入职安全培训日期": "safety_training_date",
    "入职安全培训成绩": "safety_training_score",
    "企业文化培训日期": "culture_training_date",
    "GMP基础培训时间": "gmp_training_date",
}

# 名单初值复制字段 = 白名单 + level。level 不在 TRAINING_ROSTER_FIELDS（不外显），
# 但 report_level 分级依赖它：新进名单若不复制，S/M 序列分级对新成员失效。
ROSTER_INITIAL_FIELDS: tuple[str, ...] = (*TRAINING_ROSTER_FIELDS.values(), "level")

# 「组织字段一次性刷新」的字段分桶（换数据源后对齐新档案，保留培训字段本地编辑）
# - 刷新：组织/身份/教育等跟随档案的字段（actual_department/进厂/入丽珠时间
#   在员工表已下线，名单侧保留各自独立的列与本地值）
# - 仅空值补齐：档案有值但名单为空时补，不覆盖本地编辑
# - 其余（实际部门/班组/品种/培训编号/一级培训师/4 个培训字段/资格等）一律保留名单本地值
ROSTER_ORG_REFRESH_FIELDS: tuple[str, ...] = (
    "name", "department", "position", "duty",
    "job_category", "level", "education", "graduation_date", "status_category",
    "work_start_date",
    "hire_date", "departure_date",
)
ROSTER_FILL_IF_EMPTY_FIELDS: tuple[str, ...] = ("certificates",)

# ── 名单字段「跟随档案」规则 ──
# 可配置为跟随的字段 = 名单列里在员工档案有同名来源的那些。实际部门/班组/兼任部门·
# 品种/品种/进厂·入丽珠时间/培训编号/一级培训师/4 个培训字段/资格在员工档案没有来源
# （换数据源时已下线），只能在名单维护，不在此列。
ROSTER_FOLLOWABLE_FIELDS: tuple[str, ...] = (
    "name", "department", "position", "duty", "job_category", "level",
    "education", "graduation_date", "status_category",
    "work_start_date", "hire_date", "departure_date", "certificates",
)
# 人员状态恒跟随（病假/产假/离职统计都靠它），不开放关闭，
# 由 sync_roster_membership 与离职/复职处维护，不走本配置
ROSTER_LOCKED_FOLLOW_FIELD = "status"
# level 不在显示白名单（不外显），但报表用职级依赖它，配置页单独给标签
_LEVEL_LABEL = "级别（报表用职级）"

# 按工号 / 按部门的例外模式（优先于全局字段规则；人员例外又优先于部门例外）
ROSTER_FOLLOW_MODE_ALL = "follow"   # 全部可跟随字段都跟随档案
ROSTER_FOLLOW_MODE_NONE = "manual"  # 全部手动（人员状态仍跟随）
_ROSTER_FOLLOW_MODES = (ROSTER_FOLLOW_MODE_ALL, ROSTER_FOLLOW_MODE_NONE)
# 部门例外按名单上的「体现部门」名称匹配（与培训模块「按部门取人」同口径）；
# 「未分类」是同步兜底占位、不算部门，不出现在可选清单里
ROSTER_FOLLOW_SOURCE_MEMBER = "member"
ROSTER_FOLLOW_SOURCE_DEPARTMENT = "department"


@dataclass(frozen=True, slots=True)
class RosterFollowConfig:
    """名单字段跟随档案的规则：全局字段 + 部门例外 + 按工号例外。

    优先级：人员例外 > 部门例外 > 全局字段。
    未配置（KV 缺失/为空）时三者皆空，即现状——只有人员状态跟随档案。
    """

    fields: frozenset[str] = frozenset()
    member_modes: Mapping[str, str] = field(default_factory=dict)
    department_modes: Mapping[str, str] = field(default_factory=dict)

    def mode_of(self, employee_number: str, department: str | None = None) -> str:
        """某人生效的例外模式（人员例外优先于部门例外）；空串 = 跟随全局字段。"""
        return (
            self.member_modes.get(employee_number)
            or self.department_modes.get(department or "")
            or ""
        )

    def fields_for(
        self, employee_number: str, department: str | None = None,
    ) -> tuple[str, ...]:
        """某人实际跟随档案的字段（不含恒跟随的人员状态）。"""
        mode = self.mode_of(employee_number, department)
        if mode == ROSTER_FOLLOW_MODE_ALL:
            return ROSTER_FOLLOWABLE_FIELDS
        if mode == ROSTER_FOLLOW_MODE_NONE:
            return ()
        return tuple(f for f in ROSTER_FOLLOWABLE_FIELDS if f in self.fields)

    def source_of(self, employee_number: str, department: str | None = None) -> str:
        """例外来自哪里（member / department）；空串 = 无例外，跟随全局字段。"""
        if employee_number in self.member_modes:
            return ROSTER_FOLLOW_SOURCE_MEMBER
        if department and department in self.department_modes:
            return ROSTER_FOLLOW_SOURCE_DEPARTMENT
        return ""


def roster_follow_options() -> dict[str, list[dict[str, str]]]:
    """配置页的候选项：可配置字段 / 恒跟随字段 / 档案无来源（只能名单维护）的字段。"""
    label_by_attr = {attr: label for label, attr in TRAINING_ROSTER_FIELDS.items()}
    label_by_attr["level"] = _LEVEL_LABEL
    # 白名单里实际部门的列名是「部门」，配置页与「体现部门」并列展示，按名单页的叫法写清楚
    label_by_attr["actual_department"] = "实际部门"

    def _item(attr: str) -> dict[str, str]:
        return {"attr": attr, "label": label_by_attr.get(attr, attr)}

    unsupported = tuple(
        attr for attr in TRAINING_ROSTER_FIELDS.values()
        if attr not in ("employee_number", ROSTER_LOCKED_FOLLOW_FIELD)
        and attr not in ROSTER_FOLLOWABLE_FIELDS
    )
    return {
        "followable": [_item(attr) for attr in ROSTER_FOLLOWABLE_FIELDS],
        "locked": [_item(ROSTER_LOCKED_FOLLOW_FIELD)],
        "unsupported": [_item(attr) for attr in unsupported],
    }


def _parse_modes(raw_modes: Mapping[str, str] | None, label: str) -> dict[str, str]:
    """规范化例外映射（去空白、丢弃空键；未知模式报错，防拼写错误静默失效）。"""
    modes: dict[str, str] = {}
    for raw_key, mode in (raw_modes or {}).items():
        key = str(raw_key).strip()
        if not key:
            continue
        if mode not in _ROSTER_FOLLOW_MODES:
            raise ValueError(f"未知的{label}跟随模式：{mode}")
        modes[key] = mode
    return modes


def parse_roster_follow_config(
    fields: list[str] | None,
    member_modes: dict[str, str] | None,
    department_modes: dict[str, str] | None = None,
) -> RosterFollowConfig:
    """校验并规范化入参（未知字段/未知模式一律报错，防拼写错误静默失效）。"""
    chosen = set(fields or [])
    unknown = sorted(chosen - set(ROSTER_FOLLOWABLE_FIELDS))
    if unknown:
        raise ValueError(f"不可配置为跟随档案的字段：{'、'.join(unknown)}")
    return RosterFollowConfig(
        fields=frozenset(chosen),
        member_modes=_parse_modes(member_modes, "人员"),
        department_modes=_parse_modes(department_modes, "部门"),
    )


async def load_roster_follow_config(session: AsyncSession) -> RosterFollowConfig:
    """读取跟随规则；缺失/损坏按未配置处理，不让一轮对账整体失败。"""
    result = await session.execute(
        select(SystemSetting).where(
            SystemSetting.key == KEY_ROSTER_FOLLOW,
            SystemSetting.is_deleted == False,  # noqa: E712
        )
    )
    row = result.scalar_one_or_none()
    raw = (row.value if row else "") or ""
    if not raw.strip():
        return RosterFollowConfig()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("%s 不是合法 JSON，已忽略", KEY_ROSTER_FOLLOW)
        return RosterFollowConfig()
    if not isinstance(parsed, dict):
        return RosterFollowConfig()
    fields = parsed.get("fields")
    modes = parsed.get("member_modes")
    dept_modes = parsed.get("department_modes")
    # 容错读取：代码演进后遗留的未知字段/模式直接丢弃
    valid_fields = (
        [f for f in fields if f in ROSTER_FOLLOWABLE_FIELDS]
        if isinstance(fields, list) else []
    )

    def _valid_modes(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): mode for key, mode in raw.items()
            if mode in _ROSTER_FOLLOW_MODES
        }

    return RosterFollowConfig(
        fields=frozenset(valid_fields),
        member_modes=_valid_modes(modes),
        department_modes=_valid_modes(dept_modes),
    )


async def save_roster_follow_config(
    session: AsyncSession, cfg: RosterFollowConfig,
) -> None:
    """写入跟随规则（不提交事务）。"""
    await save_config_values(session, {KEY_ROSTER_FOLLOW: json.dumps({
        "fields": sorted(cfg.fields),
        "member_modes": dict(cfg.member_modes),
        "department_modes": dict(cfg.department_modes),
    }, ensure_ascii=False)})


@dataclass(frozen=True, slots=True)
class EmployeeSyncConfig:
    """同步绑定的内存形态（is_ready = 可执行同步）。"""

    enabled: bool = False
    app_token: str = ""
    source_table_id: str = ""
    source_table_name: str = ""
    headcount_table_id: str = ""
    headcount_table_name: str = ""
    departure_table_id: str = ""
    departure_table_name: str = ""
    last_sync_at: str = ""
    last_stats: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.app_token and self.source_table_id)

    @property
    def headcount_ready(self) -> bool:
        """定编表是否可同步（可选附加项，独立于员工档案主绑定）。"""
        return bool(self.enabled and self.app_token and self.headcount_table_id)

    @property
    def departure_ready(self) -> bool:
        """离职人员管理表是否可同步（可选附加项）。"""
        return bool(self.enabled and self.app_token and self.departure_table_id)


async def load_config(session: AsyncSession) -> EmployeeSyncConfig:
    """读取全部同步 KV（单次查询，缺失键回落默认值）。"""
    keys = [
        KEY_ENABLED, KEY_APP_TOKEN, KEY_SOURCE_TABLE_ID, KEY_SOURCE_TABLE_NAME,
        KEY_HEADCOUNT_TABLE_ID, KEY_HEADCOUNT_TABLE_NAME,
        KEY_DEPARTURE_TABLE_ID, KEY_DEPARTURE_TABLE_NAME,
        KEY_LAST_SYNC_AT, KEY_LAST_STATS,
    ]
    result = await session.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_(keys),
            SystemSetting.is_deleted == False,  # noqa: E712
        )
    )
    kv = {row.key: row.value for row in result.scalars().all()}

    stats: dict[str, Any] = {}
    raw_stats = kv.get(KEY_LAST_STATS) or ""
    if raw_stats:
        try:
            parsed = json.loads(raw_stats)
            if isinstance(parsed, dict):
                stats = parsed
        except (TypeError, ValueError):
            logger.warning("employee_sync.last_stats 不是合法 JSON，已忽略")

    return EmployeeSyncConfig(
        enabled=(kv.get(KEY_ENABLED) or "").strip().lower() == "true",
        app_token=(kv.get(KEY_APP_TOKEN) or "").strip(),
        source_table_id=(kv.get(KEY_SOURCE_TABLE_ID) or "").strip(),
        source_table_name=(kv.get(KEY_SOURCE_TABLE_NAME) or "").strip(),
        headcount_table_id=(kv.get(KEY_HEADCOUNT_TABLE_ID) or "").strip(),
        headcount_table_name=(kv.get(KEY_HEADCOUNT_TABLE_NAME) or "").strip(),
        departure_table_id=(kv.get(KEY_DEPARTURE_TABLE_ID) or "").strip(),
        departure_table_name=(kv.get(KEY_DEPARTURE_TABLE_NAME) or "").strip(),
        last_sync_at=(kv.get(KEY_LAST_SYNC_AT) or "").strip(),
        last_stats=stats,
    )


async def save_config_values(session: AsyncSession, values: dict[str, Any]) -> None:
    """写入同步 KV（存在即更新，含复活被软删的行；不提交事务）。"""
    for key, value in values.items():
        text_value = "" if value is None else str(value)
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = text_value
            row.is_deleted = False
            row.description = "员工档案多维表格同步"
        else:
            session.add(SystemSetting(
                key=key, value=text_value, description="员工档案多维表格同步",
            ))
    await session.flush()
