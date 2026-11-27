"""离职管理模块系统设置：hr.system_settings KV，键前缀 hr_offboarding.。

全部键均可缺省（缺省值兜底，库里没配也能跑），不新增环境变量：
- hr_offboarding.resignation_approval_code_staff     离职审批定义编码（一般员工~M4）。
- hr_offboarding.resignation_approval_code_director  离职审批定义编码（M5+ 总监级）。
- hr_offboarding.clearance_approval_code_staff       清退交接定义编码（一般员工~M4）。
- hr_offboarding.clearance_approval_code_director    清退交接定义编码（M5+ 总监级）。
  四个编码任一为空时对应环节自动降级「站内登记办结」（HR 在办理抽屉手动推进）。
- hr_offboarding.director_levels                     总监级职级前缀，逗号分隔，缺省 M5,M6,M7,M8。
- hr_offboarding.hr_copy_open_ids                    HR 通知接收人（姓名或 open_id，逗号分隔）。
- hr_offboarding.contact_info                        通知/短信落款联系人，缺省「人力资源部」。
- hr_offboarding.lead_warn_days_resigned             转正员工须提前天数，缺省 30（发起时校验提示）。
- hr_offboarding.lead_warn_days_probation            试用期员工须提前天数，缺省 3。
- hr_offboarding.clearance_items                     四部门清退事项清单（JSON：{"admin": [...], ...}），
  未配置或配置不可用时用需求列明的默认清单。
- hr_offboarding.sms_template                        离职证明短信文案，占位符 {联系人}。
  系统只部署在公司内网，员工在手机上打不开本系统的链接，所以短信只做通知、不带签署链接。

节点提醒走人事提醒框架的键（reminders.py / scheduled.py）：
- hr_reminder.offboarding_lead.{enabled,open_ids,days_ahead}          离职发起时限提醒（每天 09:20）。
- hr_reminder.offboarding_clearance_due.{enabled,open_ids}            离职手续催办（每天 09:30）。

读写走通用的 /hr/system-settings KV 接口（系统配置 →「离职管理」页签）。
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SystemSetting
from app.modules.hr.offboarding.clearance import DEFAULT_ITEMS

logger = logging.getLogger(__name__)

KEY_RESIGN_CODE_STAFF = "hr_offboarding.resignation_approval_code_staff"
KEY_RESIGN_CODE_DIRECTOR = "hr_offboarding.resignation_approval_code_director"
KEY_CLEARANCE_CODE_STAFF = "hr_offboarding.clearance_approval_code_staff"
KEY_CLEARANCE_CODE_DIRECTOR = "hr_offboarding.clearance_approval_code_director"
KEY_DIRECTOR_LEVELS = "hr_offboarding.director_levels"
KEY_HR_COPY_OPEN_IDS = "hr_offboarding.hr_copy_open_ids"
KEY_CONTACT_INFO = "hr_offboarding.contact_info"
KEY_LEAD_DAYS_RESIGNED = "hr_offboarding.lead_warn_days_resigned"
KEY_LEAD_DAYS_PROBATION = "hr_offboarding.lead_warn_days_probation"
KEY_CLEARANCE_ITEMS = "hr_offboarding.clearance_items"
KEY_SMS_TEMPLATE = "hr_offboarding.sms_template"

DEFAULT_DIRECTOR_LEVELS = "M5,M6,M7,M8"
DEFAULT_DIRECTOR_MIN_LEVEL = 5
DEFAULT_CONTACT_INFO = "人力资源部"
DEFAULT_LEAD_DAYS_RESIGNED = 30
DEFAULT_LEAD_DAYS_PROBATION = 3
# 对齐公司现行短信样式的口吻（以人力资源部某位同事的名义）；员工到公司当面签收，不带链接
DEFAULT_SMS_TEMPLATE = (
    "你好，我是丽珠福兴人力资源部{联系人}，您的离职证明已经开具，"
    "请您到人力资源部签收。"
)

_SETTING_KEYS = (
    KEY_RESIGN_CODE_STAFF,
    KEY_RESIGN_CODE_DIRECTOR,
    KEY_CLEARANCE_CODE_STAFF,
    KEY_CLEARANCE_CODE_DIRECTOR,
    KEY_DIRECTOR_LEVELS,
    KEY_HR_COPY_OPEN_IDS,
    KEY_CONTACT_INFO,
    KEY_LEAD_DAYS_RESIGNED,
    KEY_LEAD_DAYS_PROBATION,
    KEY_CLEARANCE_ITEMS,
    KEY_SMS_TEMPLATE,
)


async def load_offboarding_settings(db: AsyncSession) -> dict[str, str]:
    """一次读取全部 hr_offboarding.* 键，缺失键返回空串（调用方自行兜底）。"""
    rows = (await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_(_SETTING_KEYS),
            SystemSetting.is_deleted.is_(False),
        )
    )).scalars().all()
    return {r.key: (r.value or "") for r in rows}


def director_levels(settings: dict[str, str]) -> list[str]:
    raw = settings.get(KEY_DIRECTOR_LEVELS, "").strip()
    parts = [x.strip().upper() for x in raw.split(",") if x.strip()]
    return parts or [x.strip() for x in DEFAULT_DIRECTOR_LEVELS.split(",")]


def resolve_track(settings: dict[str, str], level: str | None) -> str:
    """按职级判定审批轨（员工离职流程：一般员工至 M4 / M5+ 总监级）。

    管理岗职级形如 M5、M12：按数字比较，「M5 及以上」都走总监轨（逐个枚举前缀
    会漏掉 M9 以上）；其余职级体系（S/P…）沿用配置里的前缀匹配。
    """
    lv = (level or "").strip().upper()
    for prefix in director_levels(settings):
        if lv.startswith(prefix):
            return "director"
    matched = re.fullmatch(r"M(\d+)", lv)
    if matched and int(matched.group(1)) >= _director_min_level(settings):
        return "director"
    return "staff"


def _director_min_level(settings: dict[str, str]) -> int:
    """配置的总监级前缀里最小的 M 序号（M5,M6,M7,M8 → 5）；配置里没有 M 序号时用缺省 5。"""
    numbers = [
        int(matched.group(1))
        for matched in (re.fullmatch(r"M(\d+)", prefix) for prefix in director_levels(settings))
        if matched
    ]
    return min(numbers) if numbers else DEFAULT_DIRECTOR_MIN_LEVEL


def approval_code_for(settings: dict[str, str], *, track: str, stage: str) -> str:
    """stage: resignation / clearance → 对应轨的定义编码（未配置返回空串）。"""
    if stage == "resignation":
        key = KEY_RESIGN_CODE_DIRECTOR if track == "director" else KEY_RESIGN_CODE_STAFF
    else:
        key = KEY_CLEARANCE_CODE_DIRECTOR if track == "director" else KEY_CLEARANCE_CODE_STAFF
    return settings.get(key, "").strip()


def contact_info(settings: dict[str, str]) -> str:
    return settings.get(KEY_CONTACT_INFO, "").strip() or DEFAULT_CONTACT_INFO


def lead_days(settings: dict[str, str], *, probation: bool) -> int:
    raw = settings.get(KEY_LEAD_DAYS_PROBATION if probation else KEY_LEAD_DAYS_RESIGNED, "").strip()
    default = DEFAULT_LEAD_DAYS_PROBATION if probation else DEFAULT_LEAD_DAYS_RESIGNED
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


def hr_copy_entries(settings: dict[str, str]) -> list[str]:
    return [x.strip() for x in settings.get(KEY_HR_COPY_OPEN_IDS, "").split(",") if x.strip()]


def stage_configured(
    settings: dict[str, str], *, stage: str, track: str | None = None, level: str | None = None,
) -> bool:
    """某办结单在某环节是否走飞书原生审批（未配置定义编码 → 站内登记）。"""
    resolved = track or resolve_track(settings, level)
    return bool(approval_code_for(settings, track=resolved, stage=stage))


def clearance_items(settings: dict[str, str]) -> dict[str, list[str]]:
    """四部门清退事项清单：系统配置优先，未配置或配置不可用时用需求列明的默认清单。

    配置是 JSON 对象 {部门 key: [事项, ...]}；部门 key 不认识、事项为空串的条目丢弃，
    丢弃后一个事项都不剩视为配置无效（一条坏配置不能把清退单清空）。
    """
    default = {category: list(names) for category, names in DEFAULT_ITEMS.items()}
    try:
        raw = json.loads(settings.get(KEY_CLEARANCE_ITEMS, "") or "")
    except ValueError:
        return default
    if not isinstance(raw, dict):
        return default
    normalized = {
        category: names for category in default
        if isinstance(raw.get(category), list)
        and (names := [str(name).strip() for name in raw[category] if str(name).strip()])
    }
    return normalized or default


def sms_template(settings: dict[str, str]) -> str:
    return settings.get(KEY_SMS_TEMPLATE, "").strip() or DEFAULT_SMS_TEMPLATE


def render_sms_text(template: str, *, contact: str) -> str:
    """短信文案：替换 {联系人} 占位符（模板里没写的占位符原样保留）。"""
    return template.replace("{联系人}", contact)
