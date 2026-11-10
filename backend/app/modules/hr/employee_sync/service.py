"""员工档案多维表格同步服务。

单向：飞书源表 → hr.employees（全量对账 + 事件增量）。
培训专用的脱敏名单不做数据复制——由 training_roster 按白名单字段
直接从本地员工表输出（敏感字段在接口层即被过滤）。
"""

import json
import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.employee_sync import bitable_client as bitable
from app.modules.hr.employee_sync.config import (
    KEY_LAST_STATS,
    KEY_LAST_SYNC_AT,
    TRAINING_ROSTER_FIELDS,
    EmployeeSyncConfig,
    load_config,
    save_config_values,
)
from app.modules.hr.employee_sync.mapping import (
    build_option_maps,
    convert_source_fields,
    normalize_cell,
)
from app.modules.hr.models import Employee, TrainingRosterProfile
from app.modules.hr.repository import EmployeeRepository
from app.modules.hr.service import EmployeeService

logger = logging.getLogger(__name__)

_LOCK_KEY = "employee_sync:reconcile_lock"
_LOCK_TTL = 280  # 略小于定时任务 timeout，防止任务超时后死锁
_ERROR_CAP = 20  # 错误列表上限（防超大 payload）


class SyncInProgressError(Exception):
    """已有一次同步正在执行（手动同步与定时对账共用一把锁）。"""


def _ensure_required(data: dict[str, Any]) -> None:
    """NOT NULL 字段兜底（与 Excel 上传语义一致：缺失/置空 → 默认值）。"""
    if not data.get("department"):
        data["department"] = "未分类"
    if not data.get("position"):
        data["position"] = ""
    if not data.get("name"):
        data["name"] = ""
    if not data.get("hire_date"):
        data["hire_date"] = date.today()


class EmployeeSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmployeeRepository(session)
        self.employee_service = EmployeeService(session)

    # ── 并发锁（Redis 不可用时降级为无锁） ──

    async def acquire_lock(self) -> bool:
        try:
            from app.core.redis import redis_client

            return bool(await redis_client.set(_LOCK_KEY, "1", ex=_LOCK_TTL, nx=True))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 不可用，同步不加锁: %s", exc)
            return True

    async def release_lock(self) -> None:
        try:
            from app.core.redis import redis_client

            await redis_client.delete(_LOCK_KEY)
        except Exception:  # noqa: BLE001
            pass

    # ── 全量对账：源表 → 本地 ──

    async def reconcile(self, cfg: EmployeeSyncConfig | None = None) -> dict[str, Any]:
        """全量对账（源表 → hr.employees）。

        返回统计 {created, updated, deleted, total, errors}。
        并发冲突抛 SyncInProgressError。
        """
        if cfg is None:
            cfg = await load_config(self.session)
        if not cfg.is_ready:
            return {"skipped": "同步未启用或绑定不完整"}

        if not await self.acquire_lock():
            raise SyncInProgressError("同步正在执行中，请稍后再试")
        try:
            stats = await self._reconcile_source(cfg)
            await self.session.commit()
            await save_config_values(self.session, {
                KEY_LAST_SYNC_AT: datetime.now().isoformat(timespec="seconds"),
                KEY_LAST_STATS: json.dumps(stats, ensure_ascii=False),
            })
            logger.info("员工档案同步完成: %s", stats)
            return stats
        finally:
            await self.release_lock()

    async def _reconcile_source(self, cfg: EmployeeSyncConfig) -> dict[str, Any]:
        records = await bitable.list_all_records(cfg.app_token, cfg.source_table_id)

        option_maps = await self._build_option_maps(cfg)

        created = updated = deleted = 0
        errors: list[str] = []
        remote_record_ids: set[str] = set()
        remote_numbers: set[str] = set()

        for record in records:
            record_id = str(record.get("record_id") or "")
            fields = record.get("fields") or {}
            if not record_id:
                continue
            employee_number = str(normalize_cell(fields.get("工号")) or "").strip()
            if not employee_number:
                if len(errors) < _ERROR_CAP:
                    errors.append(f"记录 {record_id} 缺少「工号」列，已跳过")
                continue
            remote_record_ids.add(record_id)
            remote_numbers.add(employee_number)

            data = convert_source_fields(
                dict(fields), reset_missing=True, option_maps=option_maps,
            )
            _ensure_required(data)  # 与 Excel 上传一致：NOT NULL 字段兜底
            try:
                employee, is_new = await self.repo.upsert_from_bitable(data, record_id)
                if is_new:
                    # 与手动新建员工一致：自动生成培训台账页与岗位培训记录
                    await self.employee_service._sync_employee_training(employee)
                    created += 1
                else:
                    updated += 1
            except Exception as exc:  # noqa: BLE001
                if len(errors) < _ERROR_CAP:
                    errors.append(f"工号 {employee_number}: {exc}")

        deleted = await self._soft_delete_missing(remote_record_ids, remote_numbers)
        await self.employee_service._sync_departments_from_employees()
        roster_added, roster_removed, roster_status_synced = (
            await self.sync_roster_membership()
        )

        return {
            "created": created, "updated": updated, "deleted": deleted,
            "total": len(records), "errors": errors,
            "roster_added": roster_added,
            "roster_removed": roster_removed,
            "roster_status_synced": roster_status_synced,
        }

    async def _build_option_maps(self, cfg: EmployeeSyncConfig) -> dict[str, dict[str, str]]:
        """选项ID→选项名 翻译表：源表 schema 优先，再扫 Base 全表补齐。

        单选值可能是 lookup 引用（如「部门」引用其他表的选项），选项定义
        不在源表 schema 里，需跨表汇总；同名列以源表选项优先。
        """
        maps = build_option_maps(
            await bitable.list_fields(cfg.app_token, cfg.source_table_id)
        )
        for table in await bitable.list_tables(cfg.app_token):
            table_id = str(table.get("table_id") or "")
            if not table_id or table_id == cfg.source_table_id:
                continue
            try:
                other = build_option_maps(
                    await bitable.list_fields(cfg.app_token, table_id)
                )
            except bitable.BitableAPIError as exc:
                logger.warning("拉取选项定义失败（跳过该表）: %s error=%s", table_id, exc)
                continue
            for col, mapping in other.items():
                merged = maps.setdefault(col, {})
                for opt_id, name in mapping.items():
                    merged.setdefault(opt_id, name)
        return maps

    async def _soft_delete_missing(
        self, remote_record_ids: set[str], remote_numbers: set[str]
    ) -> int:
        """软删除飞书侧已不存在的同步员工（不动手动创建、从未同步过的行）。"""
        result = await self.session.execute(
            select(Employee).where(
                Employee.is_deleted.is_(False),
                Employee.feishu_record_id.is_not(None),
            )
        )
        count = 0
        for employee in result.scalars().all():
            still_remote = (
                employee.feishu_record_id in remote_record_ids
                or (employee.employee_number in remote_numbers)
            )
            if not still_remote:
                employee.is_deleted = True
                count += 1
        if count:
            await self.session.flush()
        return count

    # ── 事件增量应用（本地库） ──

    async def apply_event_record(
        self, action: str, record_id: str, fields: dict[str, Any],
    ) -> str:
        """应用单条记录事件，返回 applied|deleted|skipped。"""
        data = convert_source_fields(fields, reset_missing=False)
        employee_number = str(data.get("employee_number") or "").strip()

        if action == "record_deleted":
            if await self.repo.soft_delete_by_feishu_record_id(record_id):
                await self._remove_roster_for_number(str(data.get("employee_number") or ""))
                return "deleted"
            return "skipped"

        # edited 事件只带变更字段，可能不含工号：按 record_id 定位已有行
        if not employee_number:
            existing = await self.repo.get_by_feishu_record_id(record_id)
            if existing is None:
                return "skipped"  # 新行首事件必带全量字段；缺工号的孤儿事件由对账兜底
            data.pop("employee_number", None)
            for key, value in data.items():
                setattr(existing, key, value)
            existing.feishu_synced_at = date.today()
            await self.session.flush()
            await self._sync_roster_status(existing)
            return "applied"

        employee, is_new = await self.repo.upsert_from_bitable(data, record_id)
        if is_new:
            await self.employee_service._sync_employee_training(employee)
            await self._ensure_roster_for_employee(employee)
        else:
            await self._sync_roster_status(employee)
        return "applied"

    # ── 培训专用脱敏名单（独立数据集：人员随总表增减，字段独立维护） ──

    async def sync_roster_membership(self) -> tuple[int, int, int]:
        """名单成员随总表（本地有效员工）增减；人员状态随总表同步。

        例外原则：status 是动态事实（病假/产假/离职等），每轮对账从总表
        覆盖；其余字段独立维护、一律不更新。复活语义：软删过的 profile
        行在员工重新出现时复活并刷新初值（视为一次全新进入名单）。
        返回 (added, removed, status_synced)。
        """
        employees = (await self.session.execute(
            select(Employee).where(Employee.is_deleted.is_(False))
        )).scalars().all()
        profiles = (await self.session.execute(
            select(TrainingRosterProfile)  # 含软删行：复活判断需要
        )).scalars().all()
        profile_by_number = {p.employee_number: p for p in profiles}
        active_numbers = {e.employee_number for e in employees}

        added = removed = status_synced = 0
        for employee in employees:
            profile = profile_by_number.get(employee.employee_number)
            if profile is None:
                self.session.add(self._copy_roster_initial(
                    TrainingRosterProfile(), employee,
                ))
                added += 1
            elif profile.is_deleted:
                # 员工重新出现：复活并刷新初值（视为一次全新进入名单）
                self._copy_roster_initial(profile, employee)
                added += 1
            elif profile.status != employee.status:
                # 人员状态随总表同步（动态事实）；其余字段独立维护不覆盖
                profile.status = employee.status
                status_synced += 1
        for profile in profiles:
            if not profile.is_deleted and profile.employee_number not in active_numbers:
                profile.is_deleted = True
                removed += 1
        if added or removed or status_synced:
            await self.session.flush()
        return added, removed, status_synced

    async def _sync_roster_status(self, employee: Employee) -> None:
        """人员状态随总表同步（唯一随总表更新的名单字段）。"""
        profile = (await self.session.execute(
            select(TrainingRosterProfile).where(
                TrainingRosterProfile.employee_number == employee.employee_number,
                TrainingRosterProfile.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if profile is not None and profile.status != employee.status:
            profile.status = employee.status
            await self.session.flush()

    async def _ensure_roster_for_employee(self, employee: Employee) -> None:
        """单个员工进入名单（事件路径新建员工时调用）。"""
        existing = (await self.session.execute(
            select(TrainingRosterProfile).where(
                TrainingRosterProfile.employee_number == employee.employee_number,
            )
        )).scalar_one_or_none()
        if existing is None:
            self.session.add(self._copy_roster_initial(
                TrainingRosterProfile(), employee,
            ))
        elif existing.is_deleted:
            self._copy_roster_initial(existing, employee)
        await self.session.flush()

    async def _remove_roster_for_number(self, employee_number: str) -> None:
        """单个员工移出名单（事件路径删除员工时调用；工号未知时按 record_id 已删，跳过）。"""
        if not employee_number:
            return
        profile = (await self.session.execute(
            select(TrainingRosterProfile).where(
                TrainingRosterProfile.employee_number == employee_number,
                TrainingRosterProfile.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if profile is not None:
            profile.is_deleted = True
            await self.session.flush()

    def _copy_roster_initial(
        self, profile: TrainingRosterProfile, employee: Employee,
    ) -> TrainingRosterProfile:
        """从员工行复制名单初值（新进名单 / 复活时刷新）。"""
        profile.employee_number = employee.employee_number
        for _label, attr in TRAINING_ROSTER_FIELDS.items():
            setattr(profile, attr, getattr(employee, attr, None))
        profile.is_deleted = False
        return profile

    async def training_roster(
        self,
        *,
        department: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        scoped_departments: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """培训专用脱敏名单：读独立数据集，仅输出白名单字段。

        scoped_departments 非空时按用户数据范围过滤（体现部门或实际部门
        在授权范围内的行），与员工档案/SOP二级表共用「用户多部门访问授权」。
        返回 (rows, total)。rows 每行 dict 的 key 为 ORM 字段名。
        """
        stmt = select(TrainingRosterProfile).where(
            TrainingRosterProfile.is_deleted.is_(False)
        )
        count_stmt = select(func.count()).select_from(TrainingRosterProfile).where(
            TrainingRosterProfile.is_deleted.is_(False)
        )
        if department:
            cond = or_(
                TrainingRosterProfile.department.ilike(f"{department}%"),
                TrainingRosterProfile.actual_department.ilike(f"{department}%"),
            )
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        if scoped_departments is not None:
            scope_cond = or_(
                TrainingRosterProfile.department.in_(scoped_departments),
                TrainingRosterProfile.actual_department.in_(scoped_departments),
            )
            stmt = stmt.where(scope_cond)
            count_stmt = count_stmt.where(scope_cond)
        if keyword:
            like = f"%{keyword}%"
            cond = or_(
                TrainingRosterProfile.name.ilike(like),
                TrainingRosterProfile.employee_number.ilike(like),
            )
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = (await self.session.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(
            TrainingRosterProfile.department, TrainingRosterProfile.employee_number,
        ).offset((page - 1) * page_size).limit(page_size)
        profiles = (await self.session.execute(stmt)).scalars().all()

        rows = []
        for profile in profiles:
            row: dict[str, Any] = {}
            for _label, attr in TRAINING_ROSTER_FIELDS.items():
                row[attr] = getattr(profile, attr, None)
            rows.append(row)
        return rows, total

    async def update_roster_entry(
        self, employee_number: str, data: dict[str, Any],
        scoped_departments: set[str] | None = None,
        updated_by: UUID | None = None,
    ) -> TrainingRosterProfile:
        """编辑名单条目（工号不可改；仅接受白名单字段）。

        scoped_departments 非空时校验条目部门在授权范围内（越权 403）。
        """
        profile = (await self.session.execute(
            select(TrainingRosterProfile).where(
                TrainingRosterProfile.employee_number == employee_number,
                TrainingRosterProfile.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if profile is None:
            raise ValueError(f"名单中不存在工号 {employee_number}")
        if scoped_departments is not None and not any(
            d in scoped_departments
            for d in (profile.department, profile.actual_department) if d
        ):
            raise PermissionError(f"数据范围限制：仅可操作授权部门（{profile.department}）")
        # status 随总表自动同步，不开放手动编辑（改了也会被下轮对账覆盖）
        allowed = set(TRAINING_ROSTER_FIELDS.values()) - {"employee_number", "status"}
        for key, value in data.items():
            if key in allowed:
                setattr(profile, key, value)
        if updated_by:
            profile.updated_by = updated_by
        await self.session.flush()
        return profile
