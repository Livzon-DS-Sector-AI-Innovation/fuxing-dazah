"""员工档案多维表格同步测试：值转换、upsert 复活、白名单脱敏、全量对账。

bitable API 全部 monkeypatch（不真连飞书）；Redis 锁 monkeypatch 放行。
"""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as hr_models
from app.modules.hr.employee_sync import bitable_client as bc
from app.modules.hr.employee_sync import config as sync_config
from app.modules.hr.employee_sync import scheduled
from app.modules.hr.employee_sync import service as sync_service
from app.modules.hr.employee_sync.mapping import convert_source_fields
from app.modules.hr.repository import EmployeeRepository


def _rand(prefix: str = "") -> str:
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{suffix}" if prefix else suffix


async def _write_config(db_session: AsyncSession, **overrides) -> None:
    """写入完整可用的同步配置。"""
    values = {
        sync_config.KEY_ENABLED: "true",
        sync_config.KEY_APP_TOKEN: "app_test_token",
        sync_config.KEY_SOURCE_TABLE_ID: "tbl_source",
        sync_config.KEY_SOURCE_TABLE_NAME: "员工档案",
    }
    values.update(overrides)
    await sync_config.save_config_values(db_session, values)


# ─── 值转换 ───


class TestTokenCleaning:
    """粘贴完整链接/带查询串的 token 清洗（脏 token 会被飞书路由到元数据接口，表现为空表列表）。"""

    def test_clean_app_token(self):
        assert bc.clean_app_token(" Bic6bL8HHaoqqjs99acc9s1bnMg ") == "Bic6bL8HHaoqqjs99acc9s1bnMg"
        assert bc.clean_app_token("Bic6bL8HHaoqqjs99acc9s1bnMg?table=tbl123&view=vew456") == "Bic6bL8HHaoqqjs99acc9s1bnMg"
        assert (
            bc.clean_app_token("https://j0eukrlohu.feishu.cn/base/Bic6bL8HHaoqqjs99acc9s1bnMg?table=tbl18mDH9QcCdw8a")
            == "Bic6bL8HHaoqqjs99acc9s1bnMg"
        )

    def test_clean_table_id(self):
        assert bc.clean_table_id(" tbl18mDH9QcCdw8a ") == "tbl18mDH9QcCdw8a"
        assert bc.clean_table_id("tbl18mDH9QcCdw8a?view=vewkDkaNxe") == "tbl18mDH9QcCdw8a"
        assert (
            bc.clean_table_id("https://j0eukrlohu.feishu.cn/base/Bic6bL8HHaoqqjs99acc9s1bnMg?table=tbl18mDH9QcCdw8a&view=vewkDkaNxe")
            == "tbl18mDH9QcCdw8a"
        )


class TestMapping:
    def test_ms_timestamp_and_text_dates(self):
        data = convert_source_fields(
            {"工号": "E001", "姓名": "张三", "入职日期": 1705276800000, "毕业时间": "2024/01/15"},
            reset_missing=False,
        )
        assert data["employee_number"] == "E001"
        assert data["hire_date"] == date(2024, 1, 15)
        assert data["graduation_date"] == date(2024, 1, 15)

    def test_segment_text_values_flattened(self):
        """拉取 API 的文本字段值为 segment 数组 [{"text": ...}]，需归一为纯文本。"""
        data = convert_source_fields(
            {"工号": [{"text": "111000002", "type": "text"}],
             "姓名": [{"text": "张", "type": "text"}, {"text": "三", "type": "text"}],
             "身份证号": []},
            reset_missing=False,
        )
        assert data["employee_number"] == "111000002"
        assert data["name"] == "张三"
        assert "id_card" not in data  # 空 segment 不写入

    def test_excel_serial_and_unwrapped_values(self):
        """培训日期列可能是 Excel 序列号（42671）；单选/日期可能是单元素数组包裹。"""
        data = convert_source_fields(
            {"工号": ["111000002"], "入职日期": [1477238400000],
             "毕业时间": 42671, "部门": ["optABC"]},
            reset_missing=False,
        )
        assert data["employee_number"] == "111000002"
        assert data["hire_date"] == date(2016, 10, 24)
        assert data["graduation_date"] == date(2016, 10, 28)
        assert data["department"] == "optABC"  # 无翻译表时原样保留（部门→体现部门）

    def test_option_maps_translate_single_select_ids(self):
        maps = {"部门": {"optABC": "财务部"}}
        data = convert_source_fields(
            {"工号": "E1", "部门": ["optABC"]}, reset_missing=False, option_maps=maps,
        )
        assert data["department"] == "财务部"

    def test_birth_date_column_splits_to_ymd(self):
        """「出生年月」列（内部键 _birth_date）拆为年/月/日，本身不入 data。"""
        data = convert_source_fields(
            {"工号": "E001", "出生年月": 631152000000},  # 1990-01-01
            reset_missing=False,
        )
        assert data["birth_year"] == 1990
        assert data["birth_month"] == 1
        assert data["birth_day"] == 1
        assert "_birth_date" not in data

    def test_event_style_values(self):
        # WS 事件值均为字符串：日期是毫秒串，多选是 JSON 串
        data = convert_source_fields(
            {"工号": "E001", "入职日期": "1705276800000", "司龄": "3年2个月"},
            reset_missing=False,
        )
        assert data["hire_date"] == date(2024, 1, 15)
        assert data["company_tenure"] == "3年2个月"

    def test_status_placeholder_skipped(self):
        data = convert_source_fields({"工号": "E001", "人员状态": "—"}, reset_missing=False)
        assert "status" not in data

    def test_reset_missing_clears_absent_columns(self):
        data = convert_source_fields({"工号": "E001"}, reset_missing=True)
        assert data.get("school") is None
        assert data.get("id_card") is None
        # 增量模式不动未出现的字段
        patch_data = convert_source_fields({"工号": "E001"}, reset_missing=False)
        assert "school" not in patch_data

    def test_sensitive_columns_map_for_local_but_not_copy(self):
        """源表敏感列照常进本地全量表，但脱敏表白名单不含它们。"""
        data = convert_source_fields(
            {"工号": "E001", "专业": "药学", "毕业学校": "某大学", "身份证号": "4401..."},
            reset_missing=False,
        )
        assert data["major"] == "药学"
        assert data["school"] == "某大学"
        assert data["id_card"] == "4401..."
        assert "major" not in sync_config.TRAINING_ROSTER_FIELDS.values()
        assert "school" not in sync_config.TRAINING_ROSTER_FIELDS.values()
        assert "id_card" not in sync_config.TRAINING_ROSTER_FIELDS.values()


# ─── upsert 与软删复活 ───


class TestUpsertFromBitable:
    async def test_soft_deleted_employee_revived(self, db_session: AsyncSession):
        repo = EmployeeRepository(db_session)
        number = f"E{_rand()}"
        employee = hr_models.Employee(
            name="旧名", employee_number=number, department="测试部",
            position="工程师", status="在职", hire_date=date(2020, 1, 1),
        )
        db_session.add(employee)
        await db_session.flush()
        employee.is_deleted = True  # 模拟历史软删除
        await db_session.flush()

        revived, is_new = await repo.upsert_from_bitable(
            convert_source_fields({"工号": number, "姓名": "新名"}, reset_missing=False),
            "rec_new_1",
        )
        assert is_new is False
        assert revived.is_deleted is False
        assert revived.name == "新名"
        assert revived.feishu_record_id == "rec_new_1"

    async def test_create_defaults(self, db_session: AsyncSession):
        repo = EmployeeRepository(db_session)
        number = f"E{_rand()}"
        employee, is_new = await repo.upsert_from_bitable(
            convert_source_fields({"工号": number, "姓名": "李四"}, reset_missing=False),
            "rec_new_2",
        )
        assert is_new is True
        assert employee.department == "未分类"
        assert employee.status == "在职"
        assert employee.hire_date is not None

    async def test_missing_number_rejected(self, db_session: AsyncSession):
        repo = EmployeeRepository(db_session)
        with pytest.raises(ValueError, match="工号"):
            await repo.upsert_from_bitable({"name": "无名"}, "rec_new_3")


# ─── 脱敏白名单字段提取 ───


class TestTrainingRoster:
    async def test_roster_outputs_whitelist_only(
        self, db_session: AsyncSession,
    ):
        """培训脱敏名单：只输出白名单字段，敏感字段绝不出现在响应里。"""
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="王五", employee_number=number, department="质控部", position="QC",
            status="在职", hire_date=date(2023, 6, 1),
            school="某大学", major="药学", id_card="440104199001010000",
            phone="13800000000",
            education="本科",
        ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        added, _removed, _status = await service.sync_roster_membership()
        assert added >= 1  # 至少包含本测试员工（共享库可能有其他新员工）
        rows, total = await service.training_roster(keyword=number)
        assert total == 1
        row = rows[0]
        assert row["employee_number"] == number
        assert row["name"] == "王五"
        assert row["education"] == "本科"
        # 敏感字段绝不出接口（整个 key 不存在，而非置空）
        for key in ("school", "major", "id_card", "phone",
                    "birth_year", "marital_status",
                    "emergency_contact_name", "native_place"):
            assert key not in row


# ─── 全量对账（mock bitable） ───


def _mock_bitable(monkeypatch, *, source_records, source_fields=None):
    """mock 平台 bitable 适配器（源表只读；同步不写飞书）。"""
    source_fields = source_fields if source_fields is not None else []

    async def _list_all_records(app_token, table_id, **kwargs):
        return list(source_records if table_id == "tbl_source" else [])

    async def _list_fields(app_token, table_id, **kwargs):
        return list(source_fields)

    monkeypatch.setattr(sync_service.bitable, "list_all_records", _list_all_records)
    monkeypatch.setattr(sync_service.bitable, "list_fields", _list_fields)
    monkeypatch.setattr(sync_service.bitable, "list_tables", AsyncMock(return_value=[]))


@pytest.fixture
def _no_lock(monkeypatch):
    """绕过 Redis 同步锁。"""
    monkeypatch.setattr(sync_service.EmployeeSyncService, "acquire_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(sync_service.EmployeeSyncService, "release_lock", AsyncMock())


class TestReconcile:
    async def test_full_reconcile_creates_updates_and_deletes(
        self, db_session: AsyncSession, monkeypatch, _no_lock,
    ):
        await _write_config(db_session)
        # reconcile 中途会 commit（源数据先落库），回滚式测试 session 需屏蔽防泄漏
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        number_keep, number_gone, number_new = f"E{_rand()}", f"E{_rand()}", f"E{_rand()}"

        # 本地已有：一个仍在线（远端存在）、一个已从远端删除
        keeper = hr_models.Employee(
            name="旧名", employee_number=number_keep, department="测试部",
            position="工程师", status="在职", hire_date=date(2020, 1, 1),
            feishu_record_id="rec_keep",
        )
        gone = hr_models.Employee(
            name="已删", employee_number=number_gone, department="测试部",
            position="工程师", status="在职", hire_date=date(2020, 1, 1),
            feishu_record_id="rec_gone",
        )
        db_session.add_all([keeper, gone])
        await db_session.flush()
        # 从未同步过的手动行：不受远端缺失影响
        manual = hr_models.Employee(
            name="手动", employee_number=f"E{_rand()}", department="测试部",
            position="工程师", status="在职", hire_date=date(2020, 1, 1),
        )
        db_session.add(manual)
        await db_session.flush()

        source_records = [
            {"record_id": "rec_keep", "fields": {"工号": number_keep, "姓名": "新名"}},
            {"record_id": "rec_new", "fields": {
                "工号": number_new, "姓名": "新人", "体现部门": "生产部", "职位": "操作工",
            }},
            # 缺工号的脏行：跳过并报错
            {"record_id": "rec_bad", "fields": {"姓名": "无工号"}},
        ]
        _mock_bitable(monkeypatch, source_records=source_records)

        service = sync_service.EmployeeSyncService(db_session)
        stats = await service.reconcile()

        assert stats["created"] == 1
        assert stats["updated"] == 1
        # 共享测试库可能已有其他飞书同步员工（不在 mock 远端集合内，同样会被软删）
        assert stats["deleted"] >= 1
        assert any("工号" in e for e in stats["errors"])
        assert stats["roster_added"] >= 1  # 新人进入名单

        repo = EmployeeRepository(db_session)
        keeper_row = await repo.get_by_employee_number(number_keep)
        assert keeper_row is not None and keeper_row.name == "新名"
        gone_row = await repo.get_by_employee_number(number_gone, include_deleted=True)
        assert gone_row is not None and gone_row.is_deleted is True
        manual_row = await repo.get_by_employee_number(manual.employee_number)
        assert manual_row is not None and manual_row.is_deleted is False
        new_row = await repo.get_by_employee_number(number_new)
        assert new_row is not None and new_row.department == "生产部"
        # 新员工自动生成培训台账页
        page = await db_session.execute(
            select(hr_models.TrainingLedgerPage).where(
                hr_models.TrainingLedgerPage.employee_number == number_new)
        )
        assert page.scalar_one_or_none() is not None


    async def test_roster_edit_survives_reconcile(
        self, db_session: AsyncSession, monkeypatch, _no_lock,
    ):
        """名单独立编辑后，总表对账不得覆盖编辑值（总表只影响人员增减）。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="郑九", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1), education="本科",
        ))
        await db_session.flush()
        await _write_config(db_session)

        service = sync_service.EmployeeSyncService(db_session)
        await service.sync_roster_membership()
        await service.update_roster_entry(number, {"education": "硕士"})

        # 总表对账：该员工学历仍是"本科"（模拟远端源表值）
        _mock_bitable(monkeypatch, source_records=[{
            "record_id": "rec_edit_keep", "fields": {"工号": number, "学历": "本科"},
        }])
        await service.reconcile()

        rows, total = await service.training_roster(keyword=number)
        assert total == 1
        assert rows[0]["education"] == "硕士"  # 编辑值未被覆盖

        # 人员移出：员工软删后名单同步移除
        emp = await EmployeeRepository(db_session).get_by_employee_number(number)
        emp.is_deleted = True
        await db_session.flush()
        _added, removed, _status = await service.sync_roster_membership()
        assert removed >= 1
        _rows, total_after = await service.training_roster(keyword=number)
        assert total_after == 0


class TestRosterStatusSync:
    async def test_status_syncs_from_master_but_edits_survive(
        self, db_session: AsyncSession, monkeypatch, _no_lock,
    ):
        """人员状态随总表对账同步；其余编辑字段不被覆盖；status 不可手动编辑。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="周十", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1), education="本科",
        ))
        await db_session.flush()
        await _write_config(db_session)

        service = sync_service.EmployeeSyncService(db_session)
        await service.sync_roster_membership()
        await service.update_roster_entry(number, {"education": "硕士"})

        # 总表状态变为病假 → 对账后名单状态跟随，学历编辑保留
        emp = await EmployeeRepository(db_session).get_by_employee_number(number)
        emp.status = "病假"
        await db_session.flush()
        _mock_bitable(monkeypatch, source_records=[{
            "record_id": "rec_status", "fields": {"工号": number, "姓名": "周十"},
        }])
        await service.reconcile()

        rows, total = await service.training_roster(keyword=number)
        assert total == 1
        assert rows[0]["status"] == "病假"      # 状态随总表同步
        assert rows[0]["education"] == "硕士"   # 编辑字段不被覆盖

        # status 不在可编辑白名单内：尝试修改无效
        await service.update_roster_entry(number, {"status": "离职"})
        rows2, _ = await service.training_roster(keyword=number)
        assert rows2[0]["status"] == "病假"


class TestRosterScope:
    async def test_roster_department_scope(self, db_session: AsyncSession):
        """受限用户（按授权部门）只能看到授权范围内的名单行，且不能越权编辑。"""
        dept_a, dept_b = f"授权甲部{_rand()}", f"授权乙部{_rand()}"
        for name, no, dept in [
            ("范围内甲", f"A{_rand()}", dept_a),
            ("范围外乙", f"B{_rand()}", dept_b),
        ]:
            db_session.add(hr_models.TrainingRosterProfile(
                name=name, employee_number=no, department=dept,
                position="QC", status="在职",
            ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        rows, total = await service.training_roster(scoped_departments={dept_a})
        assert total == 1
        assert rows[0]["department"] == dept_a

        # 越权编辑范围外条目 → PermissionError
        rows_b, _total_b = await service.training_roster(scoped_departments={dept_b})
        out_number = rows_b[0]["employee_number"]
        with pytest.raises(PermissionError):
            await service.update_roster_entry(out_number, {}, scoped_departments={dept_a})
        # 范围内可正常编辑
        in_number = rows[0]["employee_number"]
        await service.update_roster_entry(in_number, {"education": "本科"}, scoped_departments={dept_a})


# ─── 品种列（签到表品种筛选链路） ───


class TestRosterVariety:
    """修复：TrainingRosterProfile 曾缺 variety/concurrent_variety 映射，
    employee-varieties 500、名单编辑品种静默丢失、输出恒 None。"""

    async def test_variety_in_roster_output_and_editable(self, db_session: AsyncSession) -> None:
        number = f"E{_rand()}"
        db_session.add(hr_models.TrainingRosterProfile(
            name="赵一", employee_number=number, department="质控部", position="QC",
            status="在职", variety="胶囊、颗粒",
        ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        rows, total = await service.training_roster(keyword=number)
        assert total == 1
        assert rows[0]["variety"] == "胶囊、颗粒"

        # 名单编辑品种落库（修复前 setattr 到未映射属性，静默不落库）
        await service.update_roster_entry(
            number, {"variety": "原料药", "concurrent_variety": "片剂"},
        )
        db_session.expire_all()
        rows2, _total = await service.training_roster(keyword=number)
        assert rows2[0]["variety"] == "原料药"
        assert rows2[0]["concurrent_variety"] == "片剂"

    async def test_employee_varieties_endpoint(self, db_session: AsyncSession, client) -> None:
        dept = f"质控{_rand()}"
        db_session.add(hr_models.TrainingRosterProfile(
            name="钱二", employee_number=f"E{_rand()}", department=dept, position="QC",
            status="在职", variety="胶囊、颗粒",
        ))
        await db_session.flush()

        res = await client.get(
            "/api/v1/hr/employee-varieties", params={"department": dept},
        )
        assert res.status_code == 200  # 修复前：select 未映射列必 500
        assert res.json()["data"] == sorted(["胶囊", "颗粒"])


# ─── 同步启用期间的只读守卫 ───


class TestEmployeeReadOnlyGuard:
    """修复：同步启用后 create/update/delete 必须后端拦截（前端隐藏不是守卫）。"""

    async def test_writes_blocked_when_sync_ready(self, db_session: AsyncSession) -> None:
        from app.core.exceptions import AppException
        from app.modules.hr.schemas import EmployeeCreate, EmployeeUpdate
        from app.modules.hr.service import EmployeeService

        await _write_config(db_session)  # enabled=true → is_ready
        svc = EmployeeService(db_session)
        number = f"E{_rand()}"

        with pytest.raises(AppException) as ei:
            await svc.create_employee(EmployeeCreate(
                employee_number=number, name="守卫甲",
                department="测试部", position="QC", hire_date=date(2024, 1, 1),
            ))
        assert ei.value.status_code == 409

        # 先关同步建出员工，再开同步验证 update/delete 同样被拦
        await sync_config.save_config_values(
            db_session, {sync_config.KEY_ENABLED: "false"},
        )
        employee = await svc.create_employee(EmployeeCreate(
            employee_number=number, name="守卫甲",
            department="测试部", position="QC", hire_date=date(2024, 1, 1),
        ))
        await _write_config(db_session)
        with pytest.raises(AppException):
            await svc.update_employee(employee.id, EmployeeUpdate(status="离职"))
        with pytest.raises(AppException):
            await svc.delete_employee(employee.id)


# ─── 手工改状态 → 名单即时跟随 ───


class TestManualStatusSync:
    """修复：update_employee 改状态后名单 status 必须即时同步（对账 5 分钟兜底不够）。"""

    async def test_update_employee_status_syncs_roster(self, db_session: AsyncSession) -> None:
        from app.modules.hr.schemas import EmployeeUpdate
        from app.modules.hr.service import EmployeeService

        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="孙三", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1),
        ))
        await db_session.flush()
        await sync_service.EmployeeSyncService(db_session).sync_roster_membership()

        repo = EmployeeRepository(db_session)
        employee = await repo.get_by_employee_number(number)
        await EmployeeService(db_session).update_employee(
            employee.id, EmployeeUpdate(status="产假"),
        )

        rows, _total = await sync_service.EmployeeSyncService(db_session).training_roster(
            keyword=number,
        )
        assert rows[0]["status"] == "产假"


# ─── 源表改工号：record_id 归属迁移 ───


class TestRecordIdMigration:
    """修复：record_id 无唯一约束，源表改工号会遗留重复行且旧行永不被清理。"""

    async def test_record_id_moves_to_new_number(self, db_session: AsyncSession) -> None:
        repo = EmployeeRepository(db_session)
        number_a, number_b = f"A{_rand()}", f"B{_rand()}"
        db_session.add(hr_models.Employee(
            name="甲", employee_number=number_a, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1), feishu_record_id="rec_x",
        ))
        await db_session.flush()

        # 源表把该行工号从 A 改为 B：同一 record_id 现在对应新工号
        emp_b, is_new = await repo.upsert_from_bitable(
            convert_source_fields({"工号": number_b, "姓名": "乙"}, reset_missing=False),
            "rec_x",
        )
        assert is_new is True

        stale = await repo.get_by_employee_number(number_a, include_deleted=True)
        assert stale.is_deleted is True          # 旧行按删除处理，不再悬挂
        assert stale.feishu_record_id is None    # record_id 归属已迁移
        got = await repo.get_by_feishu_record_id("rec_x")
        assert got is not None and got.id == emp_b.id


# ─── 每日一次守卫（调度器 last_run 不跨重启，靠 last_sync_at 去重） ───


class TestSyncedTodayGuard:
    def _cfg(self, last_sync_at: str) -> sync_config.EmployeeSyncConfig:
        return sync_config.EmployeeSyncConfig(
            enabled=True, app_token="app_test_token",
            source_table_id="tbl_source", last_sync_at=last_sync_at,
        )

    def test_never_synced_runs(self):
        assert scheduled._synced_today(self._cfg(""), datetime(2026, 11, 11, 9, 0)) is False

    def test_invalid_last_sync_at_runs(self):
        assert scheduled._synced_today(self._cfg("not-a-date"), datetime(2026, 11, 11, 9, 0)) is False

    def test_synced_after_window_today_skips(self):
        """今天 02:00 后已自动/手动同步过：重启触发立即跳过。"""
        assert scheduled._synced_today(
            self._cfg("2026-11-11T09:30:00"), datetime(2026, 11, 11, 14, 0),
        ) is True

    def test_manual_sync_before_window_today_runs(self):
        """今天凌晨 02:00 前的手动同步不占用当天窗口：02:00 照常对账。"""
        assert scheduled._synced_today(
            self._cfg("2026-11-11T00:30:00"), datetime(2026, 11, 11, 2, 5),
        ) is False

    def test_yesterday_sync_runs(self):
        assert scheduled._synced_today(
            self._cfg("2026-11-10T23:00:00"), datetime(2026, 11, 11, 2, 5),
        ) is False


# ─── hire_date 兜底只作用于新建分支 ───


class TestHireDateNotResetToToday:
    """修复：_ensure_required 曾对缺失 hire_date 填 today，每轮对账把存量员工
    入职日期刷成当天；修复后源表缺失保留本地值（列 NOT NULL），新建行走 insert 兜底。"""

    async def test_reconcile_missing_hire_date_not_today(
        self, db_session: AsyncSession, monkeypatch, _no_lock,
    ) -> None:
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="李九", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2020, 5, 1), feishu_record_id="rec_hd",
        ))
        await db_session.flush()
        await _write_config(db_session)

        # 源表整行无「入职日期」列
        _mock_bitable(monkeypatch, source_records=[{
            "record_id": "rec_hd", "fields": {"工号": number, "姓名": "李九"},
        }])
        await sync_service.EmployeeSyncService(db_session).reconcile()

        employee = await EmployeeRepository(db_session).get_by_employee_number(number)
        assert employee.hire_date == date(2020, 5, 1)  # 保留本地值，不刷成当天


class TestReconcileRowIsolation:
    async def test_bad_row_does_not_abort_following_rows(
        self, db_session: AsyncSession, monkeypatch, _no_lock,
    ) -> None:
        """单行 flush 失败只回滚本行，后续记录仍能落库。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        await _write_config(db_session)
        bad_number, good_number = f"E{_rand()}", f"E{_rand()}"
        _mock_bitable(monkeypatch, source_records=[
            # 姓名超 varchar(64) → flush 失败
            {"record_id": "rec_bad_long", "fields": {"工号": bad_number, "姓名": "x" * 200}},
            {"record_id": "rec_good_after_bad", "fields": {
                "工号": good_number, "姓名": "好人", "体现部门": "生产部", "职位": "操作工",
            }},
        ])

        stats = await sync_service.EmployeeSyncService(db_session).reconcile()
        assert any("工号" in e for e in stats["errors"])
        row = await EmployeeRepository(db_session).get_by_employee_number(good_number)
        assert row is not None and row.name == "好人"


class TestBindingConfigGuard:
    async def test_enable_rejects_table_without_employee_number(
        self, db_session: AsyncSession, monkeypatch,
    ) -> None:
        async def _list_tables(app_token, **kwargs):
            return [{"table_id": "tbl_source", "name": "员工档案"}]

        async def _list_fields(app_token, table_id, **kwargs):
            return [{"field_name": "姓名"}]

        monkeypatch.setattr(sync_service.bitable, "list_tables", _list_tables)
        monkeypatch.setattr(sync_service.bitable, "list_fields", _list_fields)

        service = sync_service.EmployeeSyncService(db_session)
        with pytest.raises(ValueError, match="工号"):
            await service.save_binding_config(
                enabled=True, app_token="app_test_token",
                source_table_id="tbl_source",
            )


# ─── 新数据源（飞书「员工信息表」）列名适配 ───


class TestNewSourceAliases:
    """新数据源列名别名与语义变更：部门→体现部门、岗位→职位等。"""

    def test_department_semantics_changed(self):
        """源表「部门」直接落 department（体现部门），不再进 actual_department。"""
        data = convert_source_fields(
            {"工号": "E001", "部门": "财务部", "岗位": "会计", "职能分类": "职能"},
            reset_missing=False,
        )
        assert data["department"] == "财务部"
        assert data["position"] == "会计"
        assert data["job_category"] == "职能"

    def test_new_alias_columns(self):
        data = convert_source_fields({
            "工号": "E001", "户口类型": "城镇", "出生日期": 631152000000,  # 1990-01-01
            "学习形式": "全日制", "联系电话": "13800000000", "居住地址": "某市某区",
            "紧急联系人-姓名": "张三", "紧急联系人-联系电话": "13900000000",
            "紧急联系人-关系": "配偶", "离职日期": 1705276800000,  # 2024-01-15
            "任命与岗位调动": "2024 调岗", "岗位职级": "技术职级", "司龄": "3年",
            "民族": "汉族", "离职原因": "个人原因",
            "学位类型": "工学学士", "毕业证书": "证书编号X", "人力资源分析": "技术一线",
        }, reset_missing=False)
        assert data["household_type"] == "城镇"
        assert data["birth_year"] == 1990 and data["birth_month"] == 1
        assert data["classification"] == "全日制"
        assert data["phone"] == "13800000000"
        assert data["current_address"] == "某市某区"
        assert data["emergency_contact_name"] == "张三"
        assert data["emergency_contact_phone"] == "13900000000"
        assert data["emergency_contact_relation"] == "配偶"
        assert data["departure_date"] == date(2024, 1, 15)
        assert data["transfer_history"] == "2024 调岗"
        assert data["report_grade"] == "技术职级"
        assert data["company_tenure"] == "3年"
        assert data["ethnicity"] == "汉族"
        assert data["departure_reason"] == "个人原因"
        assert data["degree_type"] == "工学学士"
        assert data["graduation_certificate"] == "证书编号X"
        assert data["hr_analysis"] == "技术一线"

    def test_derive_gender_birth_from_id_card(self):
        """源表未提供 gender/出生日期时从身份证号派生（第17位奇偶、第7-14位）。"""
        # 奇数位 → 男；偶数位 → 女
        data = convert_source_fields({
            "工号": "E001", "身份证号": "440104199001011234",
        }, reset_missing=False)
        assert data["gender"] == "男"  # 第17位 3 → 奇数
        assert data["birth_year"] == 1990 and data["birth_month"] == 1
        assert data["birth_day"] == 1

        data = convert_source_fields({
            "工号": "E002", "身份证号": "440104199202022345",
        }, reset_missing=False)
        assert data["gender"] == "女"  # 第17位 4 → 偶数
        assert data["birth_year"] == 1992 and data["birth_month"] == 2
        assert data["birth_day"] == 2

    def test_derive_does_not_override_source_values(self):
        """源表显式提供的 gender/出生日期优先，派生只补空。"""
        data = convert_source_fields({
            "工号": "E001", "身份证号": "440104199001011234",
            "性别": "女",  # 与身份证奇偶（男）相反：以源表为准
        }, reset_missing=False)
        assert data["gender"] == "女"
        # 出生日期列已给出时不覆盖
        data = convert_source_fields({
            "工号": "E002", "身份证号": "440104199202022345",
            "出生日期": 631152000000,  # 1990-01-01，与身份证(1992-02-02)不同
        }, reset_missing=False)
        assert data["birth_year"] == 1990 and data["birth_month"] == 1

    def test_derive_skips_invalid_id_card(self):
        """15 位老证 / 短号不派生；18 位但日期段非法时只阻断出生派生。"""
        for id_card in ("440104900101123", "123"):  # 15 位老证 / 短号
            data = convert_source_fields({"工号": "E003", "身份证号": id_card},
                                         reset_missing=False)
            assert "gender" not in data
            assert "birth_year" not in data
        # 13 月非法：性别（第 17 位有效）仍派生，出生日期不派生
        data = convert_source_fields({"工号": "E004", "身份证号": "440104199013011234"},
                                     reset_missing=False)
        assert data["gender"] == "男"
        assert "birth_year" not in data

    def test_employee_account_user_field_to_open_id(self):
        """「员工账号」人员列取 users[].id 写 feishu_open_id（不是姓名拼接）。"""
        data = convert_source_fields(
            {"工号": "E001", "员工账号": {"users": [{"id": "ou_abc123", "name": "王五"}]}},
            reset_missing=False,
        )
        assert data["feishu_open_id"] == "ou_abc123"

    def test_option_id_translated_for_new_aliases(self):
        maps = {"部门": {"optD": "财务部"}, "岗位职级": {"optG": "主操"}}
        data = convert_source_fields(
            {"工号": "E001", "部门": "optD", "岗位职级": "optG"},
            reset_missing=False, option_maps=maps,
        )
        assert data["department"] == "财务部"
        assert data["report_grade"] == "主操"

    async def test_reconcile_new_source_columns(
        self, db_session: AsyncSession, monkeypatch, _no_lock,
    ):
        """新数据源全链路：部门/岗位语义、员工账号 open_id、状态派生进名单。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        await _write_config(db_session)
        number = f"E{_rand()}"
        _mock_bitable(
            monkeypatch,
            source_records=[{
                "record_id": "rec_new_src", "fields": {
                    "工号": number, "姓名": "新源",
                    "部门": ["optFIN"], "岗位": ["optACC"],
                    "员工性质": ["optPROB"],
                    "入职日期": 1705276800000,
                    "员工账号": {"users": [{"id": "ou_new_src", "name": "新源"}]},
                },
            }],
            source_fields=[
                {"field_name": "部门", "property": {"options": [
                    {"id": "optFIN", "name": "财务部"},
                ]}},
                {"field_name": "岗位", "property": {"options": [
                    {"id": "optACC", "name": "会计"},
                ]}},
                {"field_name": "员工性质", "property": {"options": [
                    {"id": "optPROB", "name": "试用期"},
                ]}},
            ],
        )
        await sync_service.EmployeeSyncService(db_session).reconcile()

        employee = await EmployeeRepository(db_session).get_by_employee_number(number)
        assert employee.department == "财务部"
        assert employee.position == "会计"
        assert employee.status_category == "试用期"
        assert employee.status == "试用期"  # 派生（源表无「人员状态」列）
        assert employee.feishu_open_id == "ou_new_src"


class TestStatusDerivation:
    """源表无「人员状态」列时按离职日期/员工性质派生。"""

    def test_departure_date_implies_left(self):
        data = convert_source_fields(
            {"工号": "E001", "离职日期": 1705276800000},
            reset_missing=False, has_status_column=False,
        )
        assert data["status"] == "离职"

    def test_probation_category_implies_probation(self):
        for category in ("试用期", "实习转试用", "实习生"):
            data = convert_source_fields(
                {"工号": "E001", "员工性质": category},
                reset_missing=False, has_status_column=False,
            )
            assert data["status"] == "试用期", category

    def test_regular_employee_defaults_active(self):
        data = convert_source_fields(
            {"工号": "E001", "员工性质": "转正员工"},
            reset_missing=False, has_status_column=False,
        )
        assert data["status"] == "在职"

    def test_status_column_present_disables_derivation(self):
        data = convert_source_fields(
            {"工号": "E001", "人员状态": "产假", "离职日期": 1705276800000},
            reset_missing=False, has_status_column=True,
        )
        assert data["status"] == "产假"

    async def test_leave_status_protected_on_upsert(
        self, db_session: AsyncSession,
    ):
        """本地病假/产假不被派生值覆盖；离职始终生效。"""
        repo = EmployeeRepository(db_session)
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="护假", employee_number=number, department="测试部", position="QC",
            status="病假", hire_date=date(2024, 1, 1),
        ))
        await db_session.flush()

        await repo.upsert_from_bitable(
            convert_source_fields(
                {"工号": number, "员工性质": "转正员工"},
                reset_missing=False, has_status_column=False,
            ), "rec_leave_1",
        )
        employee = await repo.get_by_employee_number(number)
        assert employee.status == "病假"

        await repo.upsert_from_bitable(
            convert_source_fields(
                {"工号": number, "离职日期": 1705276800000},
                reset_missing=False, has_status_column=False,
            ), "rec_leave_2",
        )
        employee = await repo.get_by_employee_number(number)
        assert employee.status == "离职"


class TestRosterLevelCopy:
    """修复：新进名单初值缺 level → report_level 的 S/M 分级对新成员失效。"""

    async def test_initial_copy_includes_level(self, db_session: AsyncSession):
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="等 M", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1), level="M2",
        ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        await service.sync_roster_membership()
        rows, total = await service.training_roster(keyword=number)
        assert total == 1
        # level 不在输出白名单（key 不存在），但派生 report_level 已生效
        assert "level" not in rows[0]
        assert rows[0]["report_level"] == "经理级"  # M 序列保底（无 level 时为其他人员）

    async def test_level_editable_via_update(self, db_session: AsyncSession):
        number = f"E{_rand()}"
        db_session.add(hr_models.TrainingRosterProfile(
            name="可编", employee_number=number, department="测试部",
            position="QC", status="在职",
        ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        await service.update_roster_entry(number, {"level": "M2"})
        rows, _total = await service.training_roster(keyword=number)
        assert rows[0]["report_level"] == "经理级"


class TestRosterOrgRefresh:
    """换数据源后的一次性名单对齐：刷新组织字段、保留培训字段、空值补齐。"""

    async def test_refresh_org_fields(self, db_session: AsyncSession):
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="新名", employee_number=number, department="新部门", position="新岗位",
            status="在职", hire_date=date(2024, 1, 1), education="本科",
            certificates="GMP 证书",
        ))
        db_session.add(hr_models.TrainingRosterProfile(
            name="旧名", employee_number=number, department="旧部门",
            position="旧岗位", status="在职", education="大专",
            training_id="PX-001", dept_head_trainer="王培训",
            safety_training_date=date(2024, 3, 1), variety="胶囊",
        ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)

        # dry_run 只统计不落库
        preview = await service.refresh_roster_org_fields(dry_run=True)
        assert preview["dry_run"] is True
        rows, _total = await service.training_roster(keyword=number)
        assert rows[0]["department"] == "旧部门"

        result = await service.refresh_roster_org_fields(dry_run=False)
        assert result["dry_run"] is False
        assert result["changed"] >= 1
        assert "department" in result["field_changes"]
        assert "position" in result["field_changes"]

        rows2, _total2 = await service.training_roster(keyword=number)
        assert rows2[0]["name"] == "新名"
        assert rows2[0]["department"] == "新部门"
        assert rows2[0]["position"] == "新岗位"
        assert rows2[0]["education"] == "本科"
        # 培训字段与品种保留名单本地值
        assert rows2[0]["training_id"] == "PX-001"
        assert rows2[0]["dept_head_trainer"] == "王培训"
        assert rows2[0]["safety_training_date"] == date(2024, 3, 1)
        assert rows2[0]["variety"] == "胶囊"
        # certificates 名单为空时从档案补齐
        assert rows2[0]["certificates"] == "GMP 证书"
