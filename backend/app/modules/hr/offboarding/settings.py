"""离职管理模块系统设置：hr.system_settings KV，键前缀 hr_offboarding.。

全部键均可缺省（缺省值兜底，库里没配也能跑），不新增环境变量：
- hr_offboarding.resignation_approval_code_staff     离职审批定义编码（一般员工~M4）。
- hr_offboarding.resignation_approval_code_director  离职审批定义编码（M5+ 总监级）。
- hr_offboarding.clearance_approval_code_staff       清退交接定义编码（一般员工~M4）。
- hr_offboarding.clearance_approval_code_director    清退交接定义编码（M5+ 总监级）。
  四个编码任一为空时对应环节自动降级「站内登记办结」（HR 在办理抽屉手动推进）。
- hr_offboarding.director_levels                     总监级职级前缀，逗号分隔，缺省 M5,M6,M7,M8。
- hr_offboarding.sign_page_base_url                  证明签字 H5 页基地址（…/api/departure-cert-sign）。
- hr_offboarding.hr_copy_open_ids                    HR 通知接收人（姓名或 open_id，逗号分隔）。
- hr_offboarding.contact_info                        通知/短信落款联系人，缺省「人力资源部」。
- hr_offboarding.lead_warn_days_resigned             转正员工须提前天数，缺省 30（发起时校验提示）。
- hr_offboarding.lead_warn_days_probation            试用期员工须提前天数，缺省 3。

节点提醒走人事提醒框架的键（reminders.py / scheduled.py）：
- hr_reminder.offboarding_lead.{enabled,open_ids,days_ahead}          离职发起时限提醒（每天 09:20）。
- hr_reminder.offboarding_clearance_due.{enabled,open_ids}            离职手续催办（每天 09:30）。

读写走通用的 /hr/system-settings KV 接口（系统配置 →「离职管理」页签）。
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SystemSetting

logger = logging.getLogger(__name__)

KEY_RESIGN_CODE_STAFF = "hr_offboarding.resignation_approval_code_staff"
KEY_RESIGN_CODE_DIRECTOR = "hr_offboarding.resignation_approval_code_director"
KEY_CLEARANCE_CODE_STAFF = "hr_offboarding.clearance_approval_code_staff"
KEY_CLEARANCE_CODE_DIRECTOR = "hr_offboarding.clearance_approval_code_director"
KEY_DIRECTOR_LEVELS = "hr_offboarding.director_levels"
KEY_SIGN_BASE_URL = "hr_offboarding.sign_page_base_url"
KEY_HR_COPY_OPEN_IDS = "hr_offboarding.hr_copy_open_ids"
KEY_CONTACT_INFO = "hr_offboarding.contact_info"
KEY_LEAD_DAYS_RESIGNED = "hr_offboarding.lead_warn_days_resigned"
KEY_LEAD_DAYS_PROBATION = "hr_offboarding.lead_warn_days_probation"

DEFAULT_DIRECTOR_LEVELS = "M5,M6,M7,M8"
DEFAULT_CONTACT_INFO = "人力资源部"
DEFAULT_LEAD_DAYS_RESIGNED = 30
DEFAULT_LEAD_DAYS_PROBATION = 3

_SETTING_KEYS = (
    KEY_RESIGN_CODE_STAFF,
    KEY_RESIGN_CODE_DIRECTOR,
    KEY_CLEARANCE_CODE_STAFF,
    KEY_CLEARANCE_CODE_DIRECTOR,
    KEY_DIRECTOR_LEVELS,
    KEY_SIGN_BASE_URL,
    KEY_HR_COPY_OPEN_IDS,
    KEY_CONTACT_INFO,
    KEY_LEAD_DAYS_RESIGNED,
    KEY_LEAD_DAYS_PROBATION,
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
    """按职级前缀判定审批轨（员工离职流程：一般员工至 M4 / M5+ 总监级）。"""
    lv = (level or "").strip().upper()
    for prefix in director_levels(settings):
        if lv.startswith(prefix):
            return "director"
    return "staff"


def approval_code_for(settings: dict[str, str], *, track: str, stage: str) -> str:
    """stage: resignation / clearance → 对应轨的定义编码（未配置返回空串）。"""
    if stage == "resignation":
        key = KEY_RESIGN_CODE_DIRECTOR if track == "director" else KEY_RESIGN_CODE_STAFF
    else:
        key = KEY_CLEARANCE_CODE_DIRECTOR if track == "director" else KEY_CLEARANCE_CODE_STAFF
    return settings.get(key, "").strip()


def sign_base_url(settings: dict[str, str]) -> str:
    return settings.get(KEY_SIGN_BASE_URL, "").strip().rstrip("/")


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
