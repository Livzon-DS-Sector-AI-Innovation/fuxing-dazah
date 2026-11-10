"""员工档案多维表格同步配置（SystemSetting KV 存储，无独立表）。

绑定信息（app_token / 数据表 id）与运行状态（上次同步时间/统计）都存
hr.system_settings 键值表，改绑定无需改代码或重启服务。
"""

import json
import logging
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
KEY_LAST_SYNC_AT = "employee_sync.last_sync_at"
KEY_LAST_STATS = "employee_sync.last_stats"

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


@dataclass(frozen=True, slots=True)
class EmployeeSyncConfig:
    """同步绑定的内存形态（is_ready = 可执行同步）。"""

    enabled: bool = False
    app_token: str = ""
    source_table_id: str = ""
    source_table_name: str = ""
    last_sync_at: str = ""
    last_stats: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.app_token and self.source_table_id)


async def load_config(session: AsyncSession) -> EmployeeSyncConfig:
    """读取全部同步 KV（单次查询，缺失键回落默认值）。"""
    keys = [
        KEY_ENABLED, KEY_APP_TOKEN, KEY_SOURCE_TABLE_ID, KEY_SOURCE_TABLE_NAME,
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
