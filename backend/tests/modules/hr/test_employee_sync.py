"""员工档案多维表格同步测试：值转换、upsert 复活、白名单脱敏、事件路由、对账。

bitable API 全部 monkeypatch（不真连飞书）；Redis 锁/去重 monkeypatch 放行。
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as hr_models
from app.modules.hr.employee_sync import bitable_client as bc
from app.modules.hr.employee_sync import config as sync_config
from app.modules.hr.employee_sync import handler as sync_handler
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
             "企业文化培训日期": 42671, "部门": ["optABC"]},
            reset_missing=False,
        )
        assert data["employee_number"] == "111000002"
        assert data["hire_date"] == date(2016, 10, 24)
        assert data["culture_training_date"] == date(2016, 10, 28)
        assert data["actual_department"] == "optABC"  # 无翻译表时原样保留

    def test_option_maps_translate_single_select_ids(self):
        maps = {"部门": {"optABC": "财务部"}}
        data = convert_source_fields(
            {"工号": "E1", "部门": ["optABC"]}, reset_missing=False, option_maps=maps,
        )
        assert data["actual_department"] == "财务部"

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
            {"工号": "E001", "入职日期": "1705276800000", "资格": '["药师","工程师"]'},
            reset_missing=False,
        )
        assert data["hire_date"] == date(2024, 1, 15)
        assert data["qualifications"] == ["药师", "工程师"]

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
            phone="13800000000", bank_account="6222020000000000",
            qualifications=["药师"], education="本科",
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
        assert row["qualifications"] == ["药师"]
        # 敏感字段绝不出接口（整个 key 不存在，而非置空）
        for key in ("school", "major", "id_card", "phone", "bank_account",
                    "birth_year", "political_status", "marital_status",
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
    """绕过 Redis 同步锁与去重。"""
    monkeypatch.setattr(sync_service.EmployeeSyncService, "acquire_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(sync_service.EmployeeSyncService, "release_lock", AsyncMock())
    monkeypatch.setattr(sync_handler, "_redis_set", AsyncMock(return_value=True))
    monkeypatch.setattr(sync_handler, "_redis_get", AsyncMock(return_value=None))


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


def _ready_config() -> sync_config.EmployeeSyncConfig:
    return sync_config.EmployeeSyncConfig(
        enabled=True, app_token="app_test_token", source_table_id="tbl_source",
    )


class TestEventRouting:
    async def test_non_source_table_events_ignored(self, monkeypatch, _no_lock):
        """同 Base 内脱敏表/其他表的事件一律忽略（防环 + 防误写）。"""
        applied = AsyncMock()
        monkeypatch.setattr(
            sync_service.EmployeeSyncService, "apply_event_record", applied,
        )
        monkeypatch.setattr(
            sync_handler, "load_config", AsyncMock(return_value=_ready_config()),
        )
        monkeypatch.setattr(
            sync_handler, "_get_field_map", AsyncMock(return_value={}),
        )
        await sync_handler.handle_record_changed(
            "app_test_token", "tbl_training",
            [{"action": "record_added", "record_id": "rec_x", "after_value": {"工号": "E1"}}],
        )
        await sync_handler.handle_record_changed(
            "other_token", "tbl_source",
            [{"action": "record_added", "record_id": "rec_y", "after_value": {"工号": "E1"}}],
        )
        applied.assert_not_called()

    async def test_source_table_event_applied(self, monkeypatch, _no_lock):
        """源表事件正常分发给 service（field_id 经 field_map 转列名）。"""
        applied = AsyncMock(return_value="applied")
        monkeypatch.setattr(
            sync_service.EmployeeSyncService, "apply_event_record", applied,
        )
        monkeypatch.setattr(
            sync_handler, "load_config", AsyncMock(return_value=_ready_config()),
        )
        monkeypatch.setattr(
            sync_handler, "_get_field_map", AsyncMock(return_value={"fld_1": "姓名"}),
        )
        await sync_handler.handle_record_changed(
            "app_test_token", "tbl_source",
            [{"action": "record_edited", "record_id": "rec_ok",
              "after_value": {"fld_1": "张三"}}],
        )
        applied.assert_awaited_once()
        args = applied.await_args.args
        assert args[0] == "record_edited"
        assert args[2] == {"姓名": "张三"}

    async def test_deleted_event_soft_deletes_local(
        self, db_session: AsyncSession,
    ):
        number = f"E{_rand()}"
        employee = hr_models.Employee(
            name="钱七", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1), feishu_record_id="rec_del",
        )
        db_session.add(employee)
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        result = await service.apply_event_record("record_deleted", "rec_del", {})
        assert result == "deleted"

        repo = EmployeeRepository(db_session)
        assert await repo.get_by_employee_number(number) is None
        hidden = await repo.get_by_employee_number(number, include_deleted=True)
        assert hidden is not None and hidden.is_deleted is True

    async def test_edited_without_number_patches_existing(
        self, db_session: AsyncSession,
    ):
        """edited 事件只带变更字段（无工号）时按 record_id 定位本地行。"""
        number = f"E{_rand()}"
        db_session.add(hr_models.Employee(
            name="孙八", employee_number=number, department="测试部", position="QC",
            status="在职", hire_date=date(2024, 1, 1), feishu_record_id="rec_edit",
        ))
        await db_session.flush()

        service = sync_service.EmployeeSyncService(db_session)
        result = await service.apply_event_record(
            "record_edited", "rec_edit", {"体现部门": "工程部"},
        )
        assert result == "applied"
        repo = EmployeeRepository(db_session)
        row = await repo.get_by_employee_number(number)
        assert row is not None and row.department == "工程部"
