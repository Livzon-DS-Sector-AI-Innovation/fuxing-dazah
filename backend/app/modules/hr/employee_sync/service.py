"""员工档案多维表格同步服务。

单向：飞书源表 → hr.employees（每天定时全量对账 + 手动同步，无实时事件）。
培训专用的脱敏名单是独立数据集 hr.training_roster_profiles：人员随总表增减、
进名单时按白名单复制一次初值，此后除 status 外字段独立维护、不被同步覆盖。
"""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.employee_sync import bitable_client as bitable
from app.modules.hr.employee_sync.config import (
    KEY_APP_TOKEN,
    KEY_DEPARTURE_TABLE_ID,
    KEY_DEPARTURE_TABLE_NAME,
    KEY_ENABLED,
    KEY_HEADCOUNT_TABLE_ID,
    KEY_HEADCOUNT_TABLE_NAME,
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
    _parse_date_like,
    build_option_maps,
    convert_source_fields,
    normalize_cell,
)
from app.modules.hr.employee_sync.report_level import (
    REPORT_LEVEL_FIELD,
    compute_report_level,
)
from app.modules.hr.models import (
    DepartureRecord,
    Employee,
    EmployeeTag,
    HeadcountPlan,
    TrainingRosterProfile,
)
from app.modules.hr.repository import EmployeeRepository
from app.modules.hr.service import EmployeeService

logger = logging.getLogger(__name__)

_LOCK_KEY = "employee_sync:reconcile_lock"
_LOCK_TTL = 900  # 与定时任务 timeout 一致；批量对账后单轮远小于该值
_ERROR_CAP = 20  # 错误列表上限（防超大 payload）
_CHUNK_SIZE = 50  # 批量落库粒度：批量失败后自动逐行降级，坏行只影响本行
# 只删自己的锁：TTL 过期后锁可能已被下一轮持有，GET+DEL 两步有竞态，用 Lua 保证原子
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
# 离职台账表预取结果：(records, schema)
_DepartureFetch = tuple[list[dict[str, Any]], list[dict[str, Any]]]

# ── 离职人员管理表 → DepartureRecord 字段映射 ──
# 文本列（normalize_cell 直接得到字符串）
_DEPARTURE_TEXT_FIELDS: dict[str, str] = {
    "工号": "employee_number", "姓名": "name", "职级": "rank", "性别": "gender",
    "毕业院校": "school", "专业": "major", "身份证号": "id_card", "籍贯": "native_place",
    "居住地址": "residence_address", "联系电话": "phone",
    "紧急联系人-姓名": "emergency_contact_name",
    "紧急联系人-联系电话": "emergency_contact_phone",
    "紧急联系人-关系": "emergency_contact_relation",
    "任命与岗位调动": "transfer_history", "证书": "certificates",
    "司龄": "company_tenure_at_leave",
}
# 单选列（值是选项ID，需 option_maps 翻译）
_DEPARTURE_SELECT_FIELDS: dict[str, str] = {
    "部门": "department", "岗位": "position", "职务": "duty",
    "岗位职级": "rank_category", "人力资源分析": "status_category",
    "员工性质": "employee_category",
    "学历": "education", "学位类型": "degree_type", "全日制": "classification",
    "民族": "ethnicity", "户口类型": "household_type", "婚姻状况": "marital_status",
    "合同类型": "contract_type", "离职原因": "offboarding_type",
}
# 日期列（毫秒时间戳/文本 → date，东八区语义）
_DEPARTURE_DATE_FIELDS: dict[str, str] = {
    "入职日期": "livo_entry_date", "参加工作时间": "work_start_date",
    "离职日期": "offboarding_date", "身份证有效期": "id_card_expiry",
    "合同开始日期": "contract_start_date", "合同结束日期": "contract_end_date",
}


class SyncInProgressError(Exception):
    """已有一次同步正在执行（手动同步与定时对账共用一把锁）。"""


def config_payload(cfg: EmployeeSyncConfig) -> dict[str, Any]:
    """同步配置的前端展示形态（GET /config 与保存后回显共用）。"""
    return {
        "enabled": cfg.enabled,
        "app_token": cfg.app_token,
        "source_table_id": cfg.source_table_id,
        "source_table_name": cfg.source_table_name,
        "headcount_table_id": cfg.headcount_table_id,
        "headcount_table_name": cfg.headcount_table_name,
        "headcount_ready": cfg.headcount_ready,
        "departure_table_id": cfg.departure_table_id,
        "departure_table_name": cfg.departure_table_name,
        "departure_ready": cfg.departure_ready,
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


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("record_id") or "")


def _record_number(record: dict[str, Any]) -> str:
    """源表记录的工号（单元格归一化并去空白；缺失为空串）。"""
    fields = record.get("fields") or {}
    return str(normalize_cell(fields.get("工号")) or "").strip()


class EmployeeSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmployeeRepository(session)
        self.employee_service = EmployeeService(session)

    # ── 并发锁（Redis 不可用时降级为无锁） ──

    async def acquire_lock(self) -> str | None:
        """获取同步锁，返回持锁令牌（None=已有同步在执行）。"""
        token = uuid4().hex
        try:
            from app.core.redis import redis_client

            if await redis_client.set(_LOCK_KEY, token, ex=_LOCK_TTL, nx=True):
                return token
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 不可用，同步不加锁: %s", exc)
            return token

    async def release_lock(self, token: str) -> None:
        try:
            from app.core.redis import redis_client

            # redis-py 的 async/sync 共用类型签名，运行时一定是协程
            await cast(
                Awaitable[Any],
                redis_client.eval(_RELEASE_LUA, 1, _LOCK_KEY, token),
            )
        except Exception:  # noqa: BLE001
            pass

    # ── 绑定配置保存（校验连通 + 列匹配报告） ──

    async def _validate_optional_table(
        self, app_token: str, tables: list[dict[str, Any]], table_id: str,
        label: str, required_columns: tuple[str, ...],
    ) -> str:
        """可选附加表（定编/离职台账）绑定校验：表存在 + 必需列齐 + 应用可读。

        返回表名；失败抛 ValueError（含高级权限的授权指引）。
        """
        matched = next(
            (t for t in tables if str(t.get("table_id")) == table_id), None,
        )
        if matched is None:
            available = "、".join(
                f"{t.get('name')}({t.get('table_id')})" for t in tables[:10]
            )
            raise ValueError(
                f"Base 中不存在{label}数据表 {table_id}。Base 内可用的数据表：{available}",
            )
        table_name = str(matched.get("name") or "")
        try:
            fields = [
                str(f.get("field_name") or "")
                for f in await bitable.list_fields(app_token, table_id)
            ]
        except bitable.BitableAPIError as exc:
            if "RolePermNotAllow" in str(exc):
                raise ValueError(
                    f"应用无「{table_name}」表的读取权限"
                    "（Base 开启了高级权限，应用仅被授权部分数据表）。"
                    "请在 多维表格右上角「···」→ 高级权限 → 协作者管理中，"
                    f"为应用 {bitable.active_app_id()} 勾选该数据表权限。",
                ) from exc
            raise
        missing = [c for c in required_columns if c not in fields]
        if missing:
            raise ValueError(f"{label}表缺少必需列：{'、'.join(missing)}")
        return table_name

    async def save_binding_config(
        self, *, enabled: bool, app_token: str, source_table_id: str,
        headcount_table_id: str = "", departure_table_id: str = "",
    ) -> dict[str, Any]:
        """保存绑定配置：连通性校验、列匹配报告。

        app_token / 各 table_id 需先经 routes 层清洗（容忍粘贴完整链接）。
        定编表、离职台账表为可选附加项：留空即不同步。
        校验失败抛 ValueError（路由层转 400）；返回前端展示 payload。
        """
        if enabled and (not app_token or not source_table_id):
            raise ValueError("启用同步前必须填写 app_token 和源数据表 table_id")

        table_name = ""
        headcount_table_name = ""
        departure_table_name = ""
        column_report: dict[str, Any] = {
            "mapped": [], "ignored": [], "has_employee_number": False, "mapped_count": 0,
        }
        if app_token and (source_table_id or headcount_table_id or departure_table_id):
            try:
                tables = await bitable.list_tables(app_token)
                if not tables:
                    raise ValueError(
                        "应用已是该 Base 协作者，但读不到任何数据表（RolePermNotAllow）。"
                        "多半是 Base 开启了「高级权限」：请在 右上角「···」→ 高级权限 → "
                        f"协作者管理中，为应用 {bitable.active_app_id()} 授予数据表权限"
                        "（可编辑或可管理）；否则请把应用的文档权限改为「可编辑」。",
                    )
                if source_table_id:
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
                if headcount_table_id:
                    headcount_table_name = await self._validate_optional_table(
                        app_token, tables, headcount_table_id,
                        "定编数", ("部门", "部门定编"),
                    )
                if departure_table_id:
                    departure_table_name = await self._validate_optional_table(
                        app_token, tables, departure_table_id,
                        "离职台账", ("工号", "姓名", "离职日期"),
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
            KEY_HEADCOUNT_TABLE_ID: headcount_table_id,
            KEY_HEADCOUNT_TABLE_NAME: headcount_table_name,
            KEY_DEPARTURE_TABLE_ID: departure_table_id,
            KEY_DEPARTURE_TABLE_NAME: departure_table_name,
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

        token = await self.acquire_lock()
        if token is None:
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
            await self.release_lock(token)

    async def _reconcile_source(self, cfg: EmployeeSyncConfig) -> dict[str, Any]:
        """全量对账（源表 + 附加的定编数表 / 离职台账表）。

        定编表、离职表的拉取与源表并行启动：它们不依赖员工对账结果，只是落库
        排在主循环之后。结果延后到消费点才 await——拉取异常在那里原样抛出，
        仍由各自的 SAVEPOINT 块降级为 stats 错误；主流程提前失败/被取消时在
        finally 里取消，不留孤儿任务。
        """
        headcount_fetch: asyncio.Task[list[dict[str, Any]]] | None = (
            asyncio.create_task(
                bitable.list_all_records(cfg.app_token, cfg.headcount_table_id),
            )
            if cfg.headcount_ready
            else None
        )
        departure_fetch: asyncio.Task[_DepartureFetch] | None = (
            asyncio.create_task(self._fetch_departures(cfg))
            if cfg.departure_ready
            else None
        )
        prefetch: list[asyncio.Task[Any]] = [
            task for task in (headcount_fetch, departure_fetch) if task is not None
        ]
        try:
            return await self._reconcile_tables(cfg, headcount_fetch, departure_fetch)
        finally:
            for task in prefetch:
                task.cancel()
            await asyncio.gather(*prefetch, return_exceptions=True)

    async def _reconcile_tables(
        self,
        cfg: EmployeeSyncConfig,
        headcount_fetch: asyncio.Task[list[dict[str, Any]]] | None,
        departure_fetch: asyncio.Task[_DepartureFetch] | None,
    ) -> dict[str, Any]:
        # 源记录与 schema 并行拉取；schema 只拉一次（选项翻译 + 人员状态列判断共用）
        records, schema = await asyncio.gather(
            bitable.list_all_records(cfg.app_token, cfg.source_table_id),
            bitable.list_fields(cfg.app_token, cfg.source_table_id),
        )
        option_maps = await self._build_option_maps(cfg, schema)
        has_status_column = any(
            str(f.get("field_name") or "") == "人员状态" for f in schema
        )

        # 预加载一次员工索引（含软删行）：循环内不再逐行 SELECT。
        # 同步启用期间档案只读（EmployeeService._ensure_employees_writable），
        # 快照不会被并发修改。
        all_rows = (await self.session.execute(select(Employee))).scalars().all()
        by_number = {e.employee_number: e for e in all_rows}
        by_record_id: dict[str, list[Employee]] = defaultdict(list)
        for row in all_rows:
            if row.feishu_record_id:
                by_record_id[row.feishu_record_id].append(row)

        created = updated = 0
        errors: list[str] = []
        remote_record_ids: set[str] = set()
        remote_numbers: set[str] = set()
        reported_missing: set[str] = set()

        async def _reload_employees(numbers: set[str], record_ids: set[str]) -> None:
            """失败回滚会 expire 本批对象；重载索引后再重放。

            异步会话下直接读过期属性会触发 MissingGreenlet，必须先 SELECT 载入。
            回滚只 expire 保存点内改过的对象，范围不超出这批记录涉及的工号与
            record_id（被顶替的旧行按 record_id 找），按此重载即可——坏行再多
            也不会退化成逐行整表重载。
            """
            numbers = {n for n in numbers if n}
            record_ids = {r for r in record_ids if r}
            if not numbers and not record_ids:
                return
            conditions = [Employee.employee_number.in_(sorted(numbers))] if numbers else []
            if record_ids:
                conditions.append(Employee.feishu_record_id.in_(sorted(record_ids)))
            refreshed = (await self.session.execute(
                select(Employee).where(or_(*conditions))
                .execution_options(populate_existing=True)
            )).scalars().all()
            for key in numbers:
                by_number.pop(key, None)
            for key in record_ids:
                by_record_id.pop(key, None)
            # 回滚掉的待插入对象已变游离态：索引只认库里实际存在的行
            by_rid: dict[str, list[Employee]] = defaultdict(list)
            for row in refreshed:
                by_number[row.employee_number] = row
                if row.feishu_record_id in record_ids:
                    by_rid[row.feishu_record_id].append(row)
            by_record_id.update(by_rid)

        async def _apply(record: dict[str, Any]) -> bool | None:
            """应用一条源表记录（纯内存改动），返回是否新建；跳过返回 None。"""
            record_id = _record_id(record)
            fields = record.get("fields") or {}
            if not record_id:
                return None
            # record_id 先入集合：工号临时为空时该记录仍算「源表存在」，
            # 不能把它当已删除而清掉本地员工/培训名单
            remote_record_ids.add(record_id)
            employee_number = _record_number(record)
            if not employee_number:
                # 失败批会逐行重放，同一记录的报错只记一次
                if record_id not in reported_missing:
                    reported_missing.add(record_id)
                    if len(errors) < _ERROR_CAP:
                        errors.append(f"记录 {record_id} 缺少「工号」列，已跳过")
                return None
            remote_numbers.add(employee_number)

            data = convert_source_fields(
                dict(fields), reset_missing=True, option_maps=option_maps,
                has_status_column=has_status_column,
            )
            _ensure_required(data)  # 与 Excel 上传一致：NOT NULL 字段兜底
            employee, is_new = await self.repo.upsert_from_bitable(
                data, record_id, by_number=by_number,
                by_record_id=by_record_id, flush=False,
            )
            if is_new:
                # no_autoflush：否则培训台账查询会把批内积压改动提前冲掉
                with self.session.no_autoflush:
                    # 与手动新建员工一致：自动生成培训台账页与岗位培训记录
                    await self.employee_service._sync_employee_training(employee)
            return is_new

        for start in range(0, len(records), _CHUNK_SIZE):
            chunk = records[start:start + _CHUNK_SIZE]
            chunk_created = chunk_updated = 0
            try:
                # 上一批已 flush，进入 savepoint 时无积压改动；
                # 批尾一次性落库，单批失败整体回滚到 savepoint
                async with self.session.begin_nested():
                    for record in chunk:
                        is_new = await _apply(record)
                        if is_new is True:
                            chunk_created += 1
                        elif is_new is False:
                            chunk_updated += 1
                    await self.session.flush()
            except Exception:  # noqa: BLE001
                # 失败批已被回滚：expire/expunge 掉的对象先重载索引，
                # 再逐行重放恢复「单行失败只跳过本行」的隔离粒度
                await _reload_employees(
                    {_record_number(record) for record in chunk},
                    {_record_id(record) for record in chunk},
                )
                for record in chunk:
                    record_id, number = _record_id(record), _record_number(record)
                    try:
                        async with self.session.begin_nested():
                            is_new = await _apply(record)
                            await self.session.flush()
                    except Exception as exc:  # noqa: BLE001
                        await _reload_employees({number}, {record_id})
                        if len(errors) < _ERROR_CAP:
                            detail = f"工号 {number}" if number else f"记录 {record_id}"
                            errors.append(f"{detail}: {exc}")
                        continue
                    if is_new is True:
                        created += 1
                    elif is_new is False:
                        updated += 1
                continue
            created += chunk_created
            updated += chunk_updated

        deleted = await self._soft_delete_missing(remote_record_ids, remote_numbers)
        await self.employee_service._sync_departments_from_employees()
        roster_added, roster_removed, roster_status_synced = (
            await self.sync_roster_membership()
        )

        # 定编数表：与员工档案同一 Base，一次同步顺带拉取（未绑定则跳过）。
        # 独立 SAVEPOINT：定编表失败（如表级权限未授权）只降级为 stats 错误，
        # 不回滚也不阻断本轮员工档案同步。
        headcount_stats: dict[str, Any] | None = None
        if headcount_fetch is not None:
            try:
                headcount_records = await headcount_fetch
                async with self.session.begin_nested():
                    headcount_stats = await self._reconcile_headcount(headcount_records)
            except Exception as exc:  # noqa: BLE001
                logger.error("定编表同步失败（不影响员工档案同步）: %s", exc)
                headcount_stats = {"error": str(exc)}

        # 离职人员管理表 → 离职台账（hr.departure_records），同一模式
        departure_stats: dict[str, Any] | None = None
        if departure_fetch is not None:
            try:
                departure_records, departure_schema = await departure_fetch
                async with self.session.begin_nested():
                    departure_stats = await self._reconcile_departures(
                        departure_records, departure_schema,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("离职台账同步失败（不影响员工档案同步）: %s", exc)
                departure_stats = {"error": str(exc)}

        stats = {
            "created": created, "updated": updated, "deleted": deleted,
            "total": len(records), "errors": errors,
            "roster_added": roster_added,
            "roster_removed": roster_removed,
            "roster_status_synced": roster_status_synced,
        }
        if headcount_stats is not None:
            stats["headcount"] = headcount_stats
        if departure_stats is not None:
            stats["departures"] = departure_stats
        return stats

    async def _build_option_maps(
        self, cfg: EmployeeSyncConfig, schema: list[dict[str, Any]],
    ) -> dict[str, dict[str, str]]:
        """选项ID→选项名 翻译表：源表 schema 优先，再扫 Base 全表补齐。

        单选值可能是 lookup 引用（如「部门」引用其他表的选项），选项定义
        不在源表 schema 里，需跨表汇总；同名列以源表选项优先。
        schema 为源表 list_fields 结果（调用方已拉取，避免重复请求）。
        """
        maps = build_option_maps(schema)
        table_ids = [
            str(table.get("table_id") or "")
            for table in await bitable.list_tables(cfg.app_token)
            if table.get("table_id") and str(table.get("table_id")) != cfg.source_table_id
        ]
        if not table_ids:
            return maps
        sem = asyncio.Semaphore(5)  # 限并发，避免触发飞书限流

        async def _fetch(table_id: str) -> dict[str, dict[str, str]]:
            async with sem:
                try:
                    return build_option_maps(
                        await bitable.list_fields(cfg.app_token, table_id)
                    )
                except bitable.BitableAPIError as exc:
                    logger.warning("拉取选项定义失败（跳过该表）: %s error=%s", table_id, exc)
                    return {}

        # 各表 schema 并行拉取：串行时 Base 表数 × 单次请求耗时全部叠加
        for other in await asyncio.gather(*(_fetch(tid) for tid in table_ids)):
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

    # ── 定编数表同步（员工档案同一 Base 的附加数据表） ──

    @staticmethod
    def _to_int(value: Any) -> int | None:
        """单元格值 → int（飞书数字列返回 number；容错字符串数字）。"""
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None

    async def _reconcile_headcount(
        self, records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """定编数表 → hr.headcount_plans（按部门 upsert，部门为业务主键）。

        records 为调用方预取好的源记录（拉取与员工对账并行，见 _reconcile_source）。
        现有人数/缺编不在源表取值：页面用 hr.employees 实时统计，
        手填「现有人数」仅存 source_current_count 供对账。
        """
        today = datetime.now().date()
        existing = (await self.session.execute(
            select(HeadcountPlan)  # 含软删行：复活判断需要
        )).scalars().all()
        by_department = {p.department: p for p in existing}

        created = updated = deleted = 0
        errors: list[str] = []
        remote_departments: set[str] = set()

        for record in records:
            record_id = str(record.get("record_id") or "")
            fields = record.get("fields") or {}
            department = str(normalize_cell(fields.get("部门")) or "").strip()
            if not department:
                if len(errors) < _ERROR_CAP:
                    errors.append(f"定编记录 {record_id or '(无record_id)'} 缺少「部门」，已跳过")
                continue
            remote_departments.add(department)
            quota = self._to_int(normalize_cell(fields.get("部门定编"))) or 0
            plan = by_department.get(department)
            if plan is None:
                plan = HeadcountPlan(department=department)
                self.session.add(plan)
                by_department[department] = plan
                created += 1
            elif plan.is_deleted:
                plan.is_deleted = False
                updated += 1
            else:
                updated += 1
            plan.department_quota = quota
            plan.position_detail = str(
                normalize_cell(fields.get("岗位明细")) or ""
            ).strip()
            plan.sort_order = self._to_int(normalize_cell(fields.get("排序"))) or 0
            plan.source_current_count = self._to_int(
                normalize_cell(fields.get("现有人数"))
            )
            plan.feishu_record_id = record_id or None
            plan.feishu_synced_at = today

        # 软删源表已不存在的部门（空拉取防御：权限/绑错表不得清空全部定编）
        if remote_departments:
            for plan in existing:
                if (
                    not plan.is_deleted
                    and plan.feishu_record_id is not None
                    and plan.department not in remote_departments
                ):
                    plan.is_deleted = True
                    deleted += 1
        else:
            logger.error("定编表拉取结果为空，跳过软删以保护本地定编数据")

        await self.session.flush()
        return {
            "created": created, "updated": updated, "deleted": deleted,
            "total": len(records), "errors": errors,
        }

    # ── 离职人员管理表 → 离职台账（hr.departure_records） ──

    async def _fetch_departures(self, cfg: EmployeeSyncConfig) -> _DepartureFetch:
        """离职表的 (records, schema)；供 _reconcile_source 提前并行拉取。"""
        return (
            await bitable.list_all_records(cfg.app_token, cfg.departure_table_id),
            await bitable.list_fields(cfg.app_token, cfg.departure_table_id),
        )

    async def _reconcile_departures(
        self, records: list[dict[str, Any]], schema: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """离职人员管理表 → hr.departure_records 全量对账。

        records / schema 为调用方预取好的离职表数据（见 _reconcile_source）。
        upsert 认领顺序：先按 feishu_record_id，再按工号（把历史手动建的行
        自动认领合并）；软删仅针对有 record_id 且源表消失的行；空拉取防御
        不清库。cert_sign_* 离职证明签署字段是本地数据，同步不触碰。
        """
        option_maps = build_option_maps(schema)

        today = datetime.now().date()
        existing = (await self.session.execute(
            select(DepartureRecord)  # 含软删行：复活/认领判断需要
        )).scalars().all()
        by_record_id = {
            r.feishu_record_id: r for r in existing if r.feishu_record_id
        }
        by_number = {
            r.employee_number: r for r in existing if r.employee_number
        }

        created = updated = deleted = 0
        errors: list[str] = []
        remote_record_ids: set[str] = set()

        for record in records:
            record_id = str(record.get("record_id") or "")
            fields = record.get("fields") or {}
            data = self._convert_departure_fields(fields, option_maps)
            name = str(data.get("name") or "").strip()
            if not name:
                if len(errors) < _ERROR_CAP:
                    errors.append(f"离职记录 {record_id or '(无record_id)'} 缺少「姓名」，已跳过")
                continue
            remote_record_ids.add(record_id)

            row = by_record_id.get(record_id)
            if row is None:
                # 工号认领：手动建的行（无 record_id）或曾被软删的历史行按工号
                # 合并/复活（保住离职证明签署等本地字段），避免同人重复行
                number = str(data.get("employee_number") or "").strip()
                claimed = by_number.get(number) if number else None
                if claimed is not None and (
                    not claimed.feishu_record_id or claimed.is_deleted
                ):
                    row = claimed
                    claimed.is_deleted = False
                    updated += 1
                else:
                    row = DepartureRecord(name=name)
                    self.session.add(row)
                    by_record_id[record_id] = row
                    if number:
                        by_number[number] = row
                    created += 1
            else:
                if row.is_deleted:
                    row.is_deleted = False
                updated += 1

            # NOT NULL 兜底（与员工同步一致）
            data.setdefault("department", "未分类")
            data.setdefault("position", "")
            for attr, value in data.items():
                setattr(row, attr, value)
            row.feishu_record_id = record_id or None
            row.feishu_synced_at = today

        # 软删源表已删除的行（空拉取防御：权限/绑错表不得清空台账）
        if remote_record_ids:
            for row in existing:
                if (
                    not row.is_deleted
                    and row.feishu_record_id is not None
                    and row.feishu_record_id not in remote_record_ids
                ):
                    row.is_deleted = True
                    deleted += 1
        else:
            logger.error("离职表拉取结果为空，跳过软删以保护本地离职台账")

        await self.session.flush()
        return {
            "created": created, "updated": updated, "deleted": deleted,
            "total": len(records), "errors": errors,
        }

    def _convert_departure_fields(
        self, fields: dict[str, Any], option_maps: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        """飞书离职表字段 → DepartureRecord ORM 值（仅产出有值字段）。"""
        data: dict[str, Any] = {}
        for column, attr in _DEPARTURE_TEXT_FIELDS.items():
            value = normalize_cell(fields.get(column))
            if isinstance(value, str) and value.strip():
                data[attr] = value.strip()
        for column, attr in _DEPARTURE_SELECT_FIELDS.items():
            value = normalize_cell(fields.get(column))
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            # 单选原始值是选项ID（normalize 解包后为标量），翻译成选项名
            translated = (option_maps.get(column) or {}).get(text, text)
            data[attr] = translated
        for column, attr in _DEPARTURE_DATE_FIELDS.items():
            value = normalize_cell(fields.get(column))
            parsed = _parse_date_like(value)
            if parsed is not None:
                data[attr] = parsed
        return data

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

        department 非空时只按体现部门取人（实际部门/兼任部门命中不带入）；
        「厂级」例外——厂级培训取全厂名单，但「未分类」不是体现部门
        （同步兜底占位），不带这类人。
        scoped_departments 非空时按用户数据范围过滤（体现部门或实际部门
        在授权范围内的行），与员工档案/SOP二级表共用「用户多部门访问授权」。
        返回 (rows, total)。rows 每行 dict 的 key 为 ORM 字段名，
        另带 tags（该人的分类标签名列表）。
        """
        stmt = select(TrainingRosterProfile).where(
            TrainingRosterProfile.is_deleted.is_(False)
        )
        count_stmt = select(func.count()).select_from(TrainingRosterProfile).where(
            TrainingRosterProfile.is_deleted.is_(False)
        )
        if department == "厂级":
            conds = [
                TrainingRosterProfile.department.isnot(None),
                TrainingRosterProfile.department != "",
                TrainingRosterProfile.department != "未分类",
            ]
            for cond in conds:
                stmt = stmt.where(cond)
                count_stmt = count_stmt.where(cond)
        elif department:
            cond = TrainingRosterProfile.department.ilike(f"{department}%")
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
        tags_by_employee = await self._roster_tags([p.employee_number for p in profiles])

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
            row["tags"] = tags_by_employee.get(profile.employee_number, [])
            rows.append(row)
        return rows, total

    async def _roster_tags(self, employee_numbers: list[str]) -> dict[str, list[str]]:
        """名单在页人员的分类标签，一次 IN 查询带回（页面不再逐行补查）。

        不限创建人：与 /employee-tags/by-employee 同口径（转培训自动打上的标签也要显示）。
        """
        if not employee_numbers:
            return {}
        rows = (await self.session.execute(
            select(EmployeeTag.employee_number, EmployeeTag.tag_name)
            .where(
                EmployeeTag.employee_number.in_(employee_numbers),
                EmployeeTag.is_deleted.is_(False),
            )
            .order_by(EmployeeTag.created_at, EmployeeTag.tag_name)
        )).all()
        tags: dict[str, list[str]] = {}
        for employee_number, tag_name in rows:
            tags.setdefault(employee_number, []).append(tag_name)
        return tags

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
