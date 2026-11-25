"""劳动合同模块系统设置：hr.system_settings KV，键前缀 hr_contract.。

全部键均可缺省（缺省值兜底，库里没配也能跑），不新增环境变量：
- hr_contract.renewal_pipeline_enabled    新续签流程总开关，缺省 true。
  置 true 后旧「合同到期提醒」（reminder/contract_scheduled.py，只发 HR、
  数据源宽表）自动退出，避免迁移窗口期双源重复提醒。
- hr_contract.announcement_days_ahead     公告期提前天数，缺省 50。
- hr_contract.renewal_approval_code       飞书原生审批定义编码。
  为空时部门审批自动降级为站内台账勾选（无需审批定义即可上线）。
- hr_contract.hr_copy_open_ids            HR 抄送接收人（姓名或 open_id，逗号分隔）。
- hr_contract.sign_page_base_url          员工线上签字 H5 页基地址（如 https://host/api/contract-sign）。
- hr_contract.contact_info                通知卡片中的联系人文案，缺省「人力资源部」。
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SystemSetting

logger = logging.getLogger(__name__)

KEY_PIPELINE_ENABLED = "hr_contract.renewal_pipeline_enabled"
KEY_DAYS_AHEAD = "hr_contract.announcement_days_ahead"
KEY_APPROVAL_CODE = "hr_contract.renewal_approval_code"
KEY_HR_COPY_OPEN_IDS = "hr_contract.hr_copy_open_ids"
KEY_SIGN_BASE_URL = "hr_contract.sign_page_base_url"
KEY_CONTACT_INFO = "hr_contract.contact_info"

DEFAULT_DAYS_AHEAD = 50
DEFAULT_CONTACT_INFO = "人力资源部"

_SETTING_KEYS = (
    KEY_PIPELINE_ENABLED,
    KEY_DAYS_AHEAD,
    KEY_APPROVAL_CODE,
    KEY_HR_COPY_OPEN_IDS,
    KEY_SIGN_BASE_URL,
    KEY_CONTACT_INFO,
)


async def load_contract_settings(db: AsyncSession) -> dict[str, str]:
    """一次读取全部 hr_contract.* 键，缺失键返回空串（调用方自行兜底）。"""
    rows = (await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_(_SETTING_KEYS),
            SystemSetting.is_deleted.is_(False),
        )
    )).scalars().all()
    return {r.key: (r.value or "") for r in rows}


def pipeline_enabled(settings: dict[str, str]) -> bool:
    """新续签流程总开关，缺省 true（迁移完成后即接管）。"""
    return settings.get(KEY_PIPELINE_ENABLED, "true").strip().lower() != "false"


def days_ahead(settings: dict[str, str]) -> int:
    raw = settings.get(KEY_DAYS_AHEAD, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_DAYS_AHEAD


def approval_code(settings: dict[str, str]) -> str:
    return settings.get(KEY_APPROVAL_CODE, "").strip()


def contact_info(settings: dict[str, str]) -> str:
    return settings.get(KEY_CONTACT_INFO, "").strip() or DEFAULT_CONTACT_INFO


async def save_contract_settings(db: AsyncSession, kv: dict[str, str]) -> None:
    """保存配置（system_settings 唯一键 upsert）。"""
    for key, value in kv.items():
        if key not in _SETTING_KEYS:
            continue
        row = (await db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )).scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            db.add(SystemSetting(key=key, value=str(value)))
    await db.commit()
