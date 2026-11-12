"""员工档案多维表格同步服务。

单向：飞书源表 → hr.employees（每天定时全量对账 + 手动同步，无实时事件）。
培训专用的脱敏名单是独立数据集 hr.training_roster_profiles：人员随总表增减、
进名单时按白名单复制一次初值，此后除 status 外字段独立维护、不被同步覆盖。
"""

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.employee_sync import bitable_client as bitable
from app.modules.hr.employee_sync.config import (
    KEY_APP_TOKEN,
    KEY_ENABLED,
    KEY_LAST_STATS,
    KEY_LAST_SYNC_AT,
    KEY_SOURCE_TABLE_ID,
    KEY_SOURCE_TABLE_NAME,
    ROSTER_FILL_IF_EMPTY_FIELDS,
    ROSTER_INITIAL_FIELDS,
    ROSTER_ORG_REFRESH_FIELDS,
    TRAINING_ROSTER_FIELDS,
    EmployeeSyncConfig,
    load_config,
    save_config_values,
)
from app.modules.hr.employee_sync.mapping import (
    COLUMN_MAP,
    build_option_maps,
    convert_source_fields,
    normalize_cell,
)
from app.modules.hr.employee_sync.report_level import (
    REPORT_LEVEL_FIELD,
    compute_report_level,
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


def config_payload(cfg: EmployeeSyncConfig) -> dict[str, Any]:
    """同步配置的前端展示形态（GET /config 与保存后回显共用）。"""
    return {
        "enabled": cfg.enabled,
        "app_token": cfg.app_token,
        "source_table_id": cfg.source_table_id,
        "source_table_name": cfg.source_table_name,
        "is_ready": cfg.is_ready,
        "last_sync_at": cfg.last_sync_at or None,
        "last_stats": cfg.last_stats or None,
    }


def _column_report(field_names: list[str]) -> dict[str, Any]:
    """源表列 ↔ 系统字段的匹配结果（保存配置时反馈给前端）。"""
    mapped = [c for c in field_names if c in COLUMN_MAP]
    ignored = [c for c in field_names if c not in COLUMN_MAP]
    return {
        "mapped": mapped,
        "ignored": ignored,
        "has_employee_number": "工号" in mapped,
        "mapped_count": len(mapped),
    }


def _ensure_required(data: dict[str, Any]) -> None:
    """NOT NULL 字段兜底（与 Excel 上传语义一致：缺失/置空 → 默认值）。

    注意：hire_date 可空，不做兜底——today 兜底只应作用于新建分支
    （repository.upsert_from_bitable 的 insert 侧），否则源表无该列/单元格
    为空时，每轮对账都会把存量员工的入职日期刷成当天。
    """
    if not data.get("department"):
        data["department"] = "未分类"
    if not data.get("position"):
        data["position"] = ""
    if not data.get("name"):
        data["name"] = ""


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

    # ── 绑定配置保存（校验连通 + 列匹配报告） ──

    async def save_binding_config(
        self, *, enabled: bool, app_token: str, source_table_id: str,
    ) -> dict[str, Any]:
        """保存绑定配置：连通性校验、列匹配报告。

        app_token / source_table_id 需先经 routes 层清洗（容忍粘贴完整链接）。
        校验失败抛 ValueError（路由层转 400）；返回前端展示 payload。
        """
        if enabled and (not app_token or not source_table_id):
            raise ValueError("启用同步前必须填写 app_token 和源数据表 table_id")

        table_name = ""
        column_report: dict[str, Any] = {
            "mapped": [], "ignored": [], "has_employee_number": False, "mapped_count": 0,
        }
        if app_token and source_table_id:
            try:
                tables = await bitable.list_tables(app_token)
                if not tables:
                    raise ValueError(
                        "应用已是该 Base 协作者，但读不到任何数据表（RolePermNotAllow）。"
                        "多半是 Base 开启了「高级权限」：请在 右上角「···」→ 高级权限 → "
                        f"协作者管理中，为应用 {bitable.active_app_id()} 授予数据表权限"
                        "（可编辑或可管理）；否则请把应用的文档权限改为「可编辑」。",
                    )
                matched = next(
                    (t for t in tables if str(t.get("table_id")) == source_table_id), None,
                )
                if matched is None:
                    available = "、".join(
                        f"{t.get('name')}({t.get('table_id')})" for t in tables[:10]
                    )
                    raise ValueError(
                        f"Base 中不存在数据表 {source_table_id}。Base 内可用的数据表：{available}",
                    )
                table_name = str(matched.get("name") or "")
                fields = await bitable.list_fields(app_token, source_table_id)
                column_report = _column_report(
                    [str(f.get("field_name") or "") for f in fields],
                )
                # 缺「工号」列时启用同步会导致下一轮全部记录被跳过，
                # 而空远端集合会软删全员（培训名单也随之清空）
                if enabled and not column_report.get("has_employee_number"):
                    raise ValueError(
                        "源数据表缺少「工号」列，无法启用同步（避免全量对账误删员工）",
                    )
            except ValueError:
                raise
            except bitable.BitableAPIError as exc:
                raise ValueError(
                    f"连接飞书多维表格失败：{exc}。"
                    f"请确认该 Base 已共享给应用「{bitable.active_app_id()}」"
                    f"（多维表格右上角「···」→ 添加文档应用，权限选可编辑）。",
                ) from exc

        await save_config_values(self.session, {
            KEY_ENABLED: "true" if enabled else "false",
            KEY_APP_TOKEN: app_token,
            KEY_SOURCE_TABLE_ID: source_table_id,
            KEY_SOURCE_TABLE_NAME: table_name,
        })
        await self.session.commit()

        cfg = await load_config(self.session)
        data = config_payload(cfg)
        data["column_report"] = column_report
        return data

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

        # schema 只拉一次：选项翻译表构建 + 「人员状态」列存在性判断共用
        schema = await bitable.list_fields(cfg.app_token, cfg.source_table_id)
        option_maps = await self._build_option_maps(cfg, schema)
        has_status_column = any(
            str(f.get("field_name") or "") == "人员状态" for f in schema
        )

        created = updated = deleted = 0
        errors: list[str] = []
        remote_record_ids: set[str] = set()
        remote_numbers: set[str] = set()

        for record in records:
            record_id = str(record.get("record_id") or "")
            fields = record.get("fields") or {}
            if not record_id:
                continue
            # record_id 先入集合：工号临时为空时该记录仍算「源表存在」，
            # 不能把它当已删除而清掉本地员工/培训名单
            remote_record_ids.add(record_id)
            employee_number = str(normalize_cell(fields.get("工号")) or "").strip()
            if not employee_number:
                if len(errors) < _ERROR_CAP:
                    errors.append(f"记录 {record_id} 缺少「工号」列，已跳过")
                continue
            remote_numbers.add(employee_number)

            data = convert_source_fields(
                dict(fields), reset_missing=True, option_maps=option_maps,
                has_status_column=has_status_column,
            )
            _ensure_required(data)  # 与 Excel 上传一致：NOT NULL 字段兜底
            try:
                # 行级 SAVEPOINT：单行 DB 错误只回滚本行，不毒化整轮同步
                async with self.session.begin_nested():
                    employee, is_new = await self.repo.upsert_from_bitable(data, record_id)
                    if is_new:
                        # 与手动新建员工一致：自动生成培训台账页与岗位培训记录
                        await self.employee_service._sync_employee_training(employee)
                if is_new:
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

    async def _build_option_maps(
        self, cfg: EmployeeSyncConfig, schema: list[dict[str, Any]],
    ) -> dict[str, dict[str, str]]:
        """选项ID→选项名 翻译表：源表 schema 优先，再扫 Base 全表补齐。

        单选值可能是 lookup 引用（如「部门」引用其他表的选项），选项定义
        不在源表 schema 里，需跨表汇总；同名列以源表选项优先。
        schema 为源表 list_fields 结果（调用方已拉取，避免重复请求）。
        """
        maps = build_option_maps(schema)
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
        # 防御：空/残缺拉取（权限、分页截断、绑定错表）不得清空全员
        if not remote_record_ids and not remote_numbers:
            logger.error("远端记录集合为空，跳过软删以保护本地员工与培训名单")
            return 0
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

    def _copy_roster_initial(
        self, profile: TrainingRosterProfile, employee: Employee,
    ) -> TrainingRosterProfile:
        """从员工行复制名单初值（新进名单 / 复活时刷新）。

        复制字段 = 白名单 + level（level 不外显，但 report_level 分级依赖它）。
        """
        profile.employee_number = employee.employee_number
        for attr in ROSTER_INITIAL_FIELDS:
            setattr(profile, attr, getattr(employee, attr, None))
        # 名单侧 NOT NULL 兜底：员工行部门/职位/姓名缺失时不至于整轮同步崩掉
        if not profile.department:
            profile.department = "未分类"
        if not profile.position:
            profile.position = ""
        if not profile.name:
            profile.name = ""
        profile.is_deleted = False
        return profile

    async def refresh_roster_org_fields(self, *, dry_run: bool = True) -> dict[str, Any]:
        """换数据源后的一次性名单对齐：组织字段从员工档案刷新。

        - 刷新 ROSTER_ORG_REFRESH_FIELDS（部门/职位/学历/日期等跟随档案）；
        - certificates 仅在名单为空时补齐（不覆盖本地编辑；qualifications
          员工表已随新数据源下线，名单侧保留本地值不补齐）；
        - 品种/培训编号/一级培训师/4 个培训字段等一律保留名单本地值；
        - status 不动（由每轮对账自动同步）。

        dry_run=True 只统计不落库。返回 {total, changed, field_changes, dry_run}。
        """
        employees = (await self.session.execute(
            select(Employee).where(Employee.is_deleted.is_(False))
        )).scalars().all()
        profiles = (await self.session.execute(
            select(TrainingRosterProfile).where(
                TrainingRosterProfile.is_deleted.is_(False)
            )
        )).scalars().all()
        employee_by_number = {e.employee_number: e for e in employees}

        field_changes: dict[str, int] = {}
        changed_rows = 0
        for profile in profiles:
            employee = employee_by_number.get(profile.employee_number)
            if employee is None:
                continue
            row_changed = False
            for attr in ROSTER_ORG_REFRESH_FIELDS:
                new_value = getattr(employee, attr, None)
                if getattr(profile, attr, None) != new_value:
                    if not dry_run:
                        setattr(profile, attr, new_value)
                    field_changes[attr] = field_changes.get(attr, 0) + 1
                    row_changed = True
            for attr in ROSTER_FILL_IF_EMPTY_FIELDS:
                new_value = getattr(employee, attr, None)
                if new_value and not getattr(profile, attr, None):
                    if not dry_run:
                        setattr(profile, attr, new_value)
                    field_changes[attr] = field_changes.get(attr, 0) + 1
                    row_changed = True
            if row_changed:
                changed_rows += 1
        if not dry_run and (changed_rows or field_changes):
            await self.session.flush()
        return {
            "total": len(profiles),
            "changed": changed_rows,
            "field_changes": dict(sorted(
                field_changes.items(), key=lambda kv: -kv[1]
            )),
            "dry_run": dry_run,
        }

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
            # 报表用职级：按职级+岗位类别+职务即时计算
            #（原始「级别」不在脱敏白名单内，不外显）
            row[REPORT_LEVEL_FIELD] = compute_report_level(
                profile.level, profile.duty, profile.job_category,
            )
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
        # 写入的新部门值也必须在授权范围内，防止把人员改到未授权部门
        if scoped_departments is not None:
            for key in ("department", "actual_department"):
                new_val = data.get(key)
                if new_val and new_val not in scoped_departments:
                    raise PermissionError(
                        f"数据范围限制：无权将人员调整到部门 '{new_val}'",
                    )
        # status 随总表自动同步，不开放手动编辑（改了也会被下轮对账覆盖）；
        # level 不在白名单（不外显）但允许编辑——report_level 分级输入
        allowed = (
            set(TRAINING_ROSTER_FIELDS.values()) | {"level"}
        ) - {"employee_number", "status"}
        for key, value in data.items():
            if key in allowed:
                setattr(profile, key, value)
        if updated_by:
            profile.updated_by = updated_by
        await self.session.flush()
        return profile
