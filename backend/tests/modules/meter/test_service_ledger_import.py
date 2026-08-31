"""Excel 台账导入 service 层功能测试。

契约要点：
- 表头标准化/部门解析/日期转换/行映射为纯函数，直接测；
- 标准器具导入按 asset_number upsert（命中旧记录→更新保留 id；新编号→插入；
  文件中未出现的旧记录→软删除）；器具名称/资产编号/器具编号任一为空的行被跳过；
- 探测器导入按 product_number upsert；
- import_* 内部调用 db.commit()，测试中禁掉以配合回滚 fixture，不污染 dev 库。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter import repository as repo
from app.modules.meter import service
from tests.modules.meter.conftest import build_xlsx, create_instrument


class TestNormalizeHeader:
    def test_removes_whitespace_and_newlines(self) -> None:
        """表头标准化应去除换行、空格与全角空白。"""
        assert service._normalize_header("器具名称\n  ") == "器具名称"

    def test_fullwidth_parens_to_halfwidth(self) -> None:
        """表头标准化应把全角括号统一为半角，保证与列映射匹配。"""
        assert service._normalize_header("检定周期（月）") == "检定周期(月)"

    def test_strips_trailing_colons(self) -> None:
        """表头标准化应去掉末尾冒号。"""
        assert service._normalize_header("部门：") == "部门"


class TestParseDepartment:
    def test_prefix_format(self) -> None:
        """第 2 行"部门：XXX"格式应提取出 XXX。"""
        assert service._parse_department("部门：质量控制部") == "质量控制部"
        assert service._parse_department("部门:安全部") == "安全部"

    def test_plain_colon_split(self) -> None:
        """含冒号的任意前缀文本应取冒号后部分。"""
        assert service._parse_department("所在部门：环保部") == "环保部"

    def test_plain_text_returned_as_is(self) -> None:
        """无冒号的纯文本应原样作为部门名。"""
        assert service._parse_department("质量控制部") == "质量控制部"

    def test_empty_and_none(self) -> None:
        """空串与 None 应返回 None。"""
        assert service._parse_department("") is None
        assert service._parse_department(None) is None  # type: ignore[arg-type]


class TestExcelSerialToDate:
    def test_known_serial(self) -> None:
        """Excel 序列号应按 xlrd 1900 日期系统转换为 date。"""
        assert service._excel_serial_to_date(2.0) == date(1900, 1, 2)

    def test_returns_date_for_positive_serial(self) -> None:
        """正常序列号应稳定返回 date 对象。"""
        assert isinstance(service._excel_serial_to_date(1.0), date)


class TestMapAndConvertRows:
    def _sheet(
        self,
        headers: list[str],
        rows: list[list[object]],
        name: str = "S1",
        dept: str | None = None,
    ) -> dict[str, Any]:
        return {"name": name, "headers": headers, "rows": rows, "dept": dept, "datemode": 0}

    def test_basic_mapping(self) -> None:
        """列头映射到 DB 字段；标准器具用 sheet 名作部门。"""
        sheet = self._sheet(
            ["资产编号", "器具名称", "使用地点"],
            [["A-1", "压力表", "一车间"]],
            name="仪表",
        )
        mapped, warnings, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert warnings == []
        assert mapped[0]["asset_number"] == "A-1"
        assert mapped[0]["instrument_name"] == "压力表"
        assert mapped[0]["location"] == "一车间"
        assert mapped[0]["department"] == "仪表"
        assert mapped[0]["sheet_name"] == "仪表"

    def test_department_from_row2_when_not_sheet_name(self) -> None:
        """探测器模式优先取第 2 行部门名。"""
        sheet = self._sheet(["器具名称"], [["探测器"]], name="Sheet0", dept="安全部")
        mapped, _, _skipped = service._map_and_convert_rows([sheet], service.GAS_DETECTOR_COLUMN_MAP)
        assert mapped[0]["department"] == "安全部"

    def test_missing_fields_warned_but_not_blocked(self) -> None:
        """未传 required_fields 时缺失字段只记 warning，不跳过行。"""
        sheet = self._sheet(
            ["资产编号", "器具名称", "使用地点"],
            [["A-2", "", None]],
            name="仪表",
        )
        mapped, warnings, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert len(mapped) == 1
        assert mapped[0]["instrument_name"] == ""
        assert len(warnings) == 1
        assert "器具名称" in warnings[0]["missing_fields"]
        assert "使用地点" in warnings[0]["missing_fields"]
        assert warnings[0]["row"] == 5  # 第一行数据 = Excel 第 5 行

    def test_required_fields_skip_row(self) -> None:
        """required_fields 任一为空时跳过该行并给出跳过 warning。"""
        sheet = self._sheet(
            ["资产编号", "器具名称", "器具编号"],
            [["A-3", "压力表", ""]],  # 器具编号为空
            name="仪表",
        )
        mapped, warnings, _skipped = service._map_and_convert_rows(
            [sheet],
            service.INSTRUMENT_COLUMN_MAP,
            use_sheet_name_as_dept=True,
            required_fields=("instrument_name", "asset_number", "serial_number"),
        )
        assert mapped == []
        assert any("已跳过该行" in w["message"] for w in warnings)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2026-08-01", date(2026, 8, 1)),
            ("2026/08/01", date(2026, 8, 1)),
            ("2026.08.01", date(2026, 8, 1)),
            ("2026年08月01日", date(2026, 8, 1)),
        ],
    )
    def test_date_string_formats(self, text: str, expected: date) -> None:
        """四种常用日期字符串格式均应解析为 date。"""
        sheet = self._sheet(["器具名称", "检定日期"], [["压力表", text]], name="仪表")
        mapped, warnings, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert warnings == []
        assert mapped[0]["calibration_date"] == expected

    def test_date_serial_number(self) -> None:
        """数值型日期单元格应按 Excel 序列号转换。"""
        sheet = self._sheet(["器具名称", "检定日期"], [["压力表", 46000.0]], name="仪表")
        mapped, _, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert mapped[0]["calibration_date"] is not None

    def test_float_integers_become_plain_strings(self) -> None:
        """Excel 把整数读成 float（4699.0），应转为 "4699" 而不是 "4699.0"。"""
        sheet = self._sheet(["器具名称", "器具编号"], [["压力表", 4699.0]], name="仪表")
        mapped, _, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert mapped[0]["serial_number"] == "4699"

    def test_cycle_months_parsed_as_int(self) -> None:
        """检定周期应解析为 int。"""
        sheet = self._sheet(["器具名称", "检定周期(月)"], [["压力表", "12"]], name="仪表")
        mapped, _, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert mapped[0]["calibration_cycle_months"] == 12

    def test_auto_calc_next_date_during_mapping(self) -> None:
        """映射时应自动计算下次检定日期（检定日期+周期-1天）。"""
        sheet = self._sheet(
            ["器具名称", "检定日期", "检定周期(月)"],
            [["压力表", "2026-01-31", 12]],
            name="仪表",
        )
        mapped, _, _skipped = service._map_and_convert_rows(
            [sheet], service.INSTRUMENT_COLUMN_MAP, use_sheet_name_as_dept=True
        )
        assert mapped[0]["next_calibration_date"] == date(2027, 1, 30)


class TestImportInstrumentLedger:
    def _ledger_xlsx(self, marker: str, with_detector_sheet: bool = True) -> bytes:
        """构造标准器具台账：第 1 行标题、第 2 行部门、第 3 行表头、之后数据。"""
        sheets = [
            {
                "name": "仪表台账",
                "rows": [
                    ["计量器具台账"],
                    ["部门："],
                    ["资产编号", "器具名称", "器具编号", "检定日期", "检定周期(月)"],
                    [f"IM-{marker}-1", f"压力表{marker}", f"SN-{marker}-1", "2026-01-01", 12],
                    [f"IM-{marker}-2", f"真空表{marker}", f"SN-{marker}-2", "2026-02-01", 6],
                ],
            },
        ]
        if with_detector_sheet:
            sheets.append(
                {
                    "name": "可燃气体探测器",
                    "rows": [
                        ["探测器台账"],
                        ["部门：安全部"],
                        ["器具名称", "检定时间"],
                        [f"探测器{marker}", "2026-03-01"],
                    ],
                }
            )
        return build_xlsx(sheets)

    async def test_insert_new_rows_and_delete_stale(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """新编号插入；文件中未出现的旧记录软删除；结果计数正确。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        old = await create_instrument(db_session, asset_number=f"STALE-{marker}")

        result = await service.import_instrument_ledger(
            db_session, self._ledger_xlsx(marker), f"台账-{marker}.xlsx"
        )

        assert result["imported_count"] == 2
        assert result["updated_count"] == 0
        assert result["deleted_count"] >= 1  # 包含测试旧记录（dev 库存量未出现也会被删）
        assert result["sheet_count"] == 1  # 探测器 sheet 被跳过
        assert result["sheet_details"][0]["sheet_name"] == "仪表台账"

        # 文件未出现的旧记录被软删除
        assert await repo.get_instrument_by_id(db_session, old.id) is None

        # 新记录已入库，探测器数据未被导入
        _, total = await repo.list_instruments(
            db_session, keyword=marker, page_size=200
        )
        assert total == 2

        # 部门已同步到 departments 表
        dept = await repo.get_department_by_source_and_name(
            db_session, "instrument", "仪表台账"
        )
        assert dept is not None

    async def test_existing_asset_number_updates_in_place(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """资产编号命中旧记录时更新字段并保留原 id（报告关联不断链）。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        old = await create_instrument(
            db_session,
            asset_number=f"IM-{marker}-1",
            instrument_name=f"压力表{marker}",
            location="旧地点",
        )
        report = None
        from tests.modules.meter.conftest import create_report

        report = await create_report(db_session, instrument_id=old.id)

        result = await service.import_instrument_ledger(
            db_session, self._ledger_xlsx(marker, with_detector_sheet=False), "台账.xlsx"
        )
        assert result["updated_count"] == 1
        assert result["imported_count"] == 1  # 第二条是新编号

        updated = await repo.get_instrument_by_id(db_session, old.id)
        assert updated is not None  # id 保留
        assert updated.instrument_name == f"压力表{marker}"

        # 报告关联未断链
        assert report.id in [r.id for r in await repo.list_reports_by_instrument(db_session, old.id)]

    async def test_skipped_row_does_not_delete_existing_record(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """必填字段为空被跳过的行，其已存在的旧记录不应被软删除。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        old = await create_instrument(
            db_session,
            asset_number=f"IM-{marker}",
            instrument_name=f"压力表{marker}",
            serial_number="SN-OLD",
        )

        xlsx = build_xlsx(
            [
                {
                    "name": "仪表台账",
                    "rows": [
                        ["计量器具台账"],
                        ["部门："],
                        ["资产编号", "器具名称", "器具编号"],
                        [f"IM-{marker}", f"压力表{marker}", ""],  # 器具编号为空 → 跳过
                        [f"IM-{marker}-2", f"压力表{marker}2", "SN-2"],  # 有效行
                    ],
                }
            ]
        )
        result = await service.import_instrument_ledger(db_session, xlsx, "台账.xlsx")
        assert result["imported_count"] == 1

        # 被跳过行对应的旧记录保留（不软删除）
        kept = await repo.get_instrument_by_id(db_session, old.id)
        assert kept is not None
        assert kept.serial_number == "SN-OLD"

    async def test_row_missing_required_field_skipped(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """资产编号/器具名称/器具编号任一为空的行被跳过并给出 warning。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        xlsx = build_xlsx(
            [
                {
                    "name": "仪表台账",
                    "rows": [
                        ["计量器具台账"],
                        ["部门："],
                        ["资产编号", "器具名称", "器具编号"],
                        [f"IM-{marker}", f"压力表{marker}", ""],  # 器具编号为空
                    ],
                }
            ]
        )
        with pytest.raises(ValueError):  # 有效行数为 0
            await service.import_instrument_ledger(db_session, xlsx, "台账.xlsx")

    async def test_unsupported_extension_rejected(self, db_session: AsyncSession) -> None:
        """不支持的扩展名应抛 ValueError。"""
        with pytest.raises(ValueError):
            await service.import_instrument_ledger(db_session, b"", "台账.doc")

    async def test_unmatched_header_sheet_preserves_existing_records(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """表头无法匹配的 sheet 其旧记录不能被「文件未出现即软删除」清理误删。"""
        from sqlalchemy import select as sa_select

        from app.modules.meter.models import InstrumentRecord

        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        # 旧记录：一条属于表头正常的 sheet 部门，一条属于表头漂移的 sheet 部门
        await create_instrument(
            db_session, department=f"正常部门{marker}", asset_number=f"GOOD-{marker}"
        )
        bad = await create_instrument(
            db_session, department=f"坏表头部门{marker}", asset_number=f"BAD-{marker}"
        )
        xlsx = build_xlsx(
            [
                {
                    "name": f"正常部门{marker}",
                    "rows": [
                        [f"标准计量器具台账{marker}"],
                        ["部门："],
                        ["资产编号", "器具名称", "器具编号"],
                        [f"GOOD-{marker}", "压力表", "SN-1"],
                    ],
                },
                {
                    "name": f"坏表头部门{marker}",
                    "rows": [
                        ["其他台账"],
                        ["部门："],
                        ["其他列A", "其他列B"],
                        ["x", "y"],
                    ],
                },
            ]
        )
        result = await service.import_instrument_ledger(db_session, xlsx, "台账.xlsx")
        # 其他旧记录按「文件未出现」清理是导入语义本身，这里只关心坏表头 sheet 的旧记录不被误删
        bad_row = (
            await db_session.execute(
                sa_select(InstrumentRecord).where(InstrumentRecord.id == bad.id)
            )
        ).scalar_one()
        assert bad_row.is_deleted is False
        assert any("表头列名无法匹配" in w.get("message", "") for w in result["warnings"])

    async def test_no_instrument_sheet_rejected(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """文件中只有探测器 sheet 时应抛 ValueError。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        xlsx = build_xlsx(
            [
                {
                    "name": "可燃气体探测器",
                    "rows": [
                        ["探测器台账"],
                        ["部门：安全部"],
                        ["器具名称", "检定时间"],
                        [f"探测器{marker}", "2026-03-01"],
                    ],
                }
            ]
        )
        with pytest.raises(ValueError):
            await service.import_instrument_ledger(db_session, xlsx, "台账.xlsx")

    async def test_corrupted_xlsx_raises_parse_error(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """伪造的 .xlsx（内容不是 Excel）应抛携带解析原因的 ValueError。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        with pytest.raises(ValueError, match="无法打开文件"):
            await service.import_instrument_ledger(
                db_session, b"this is not a real excel file", "台账.xlsx"
            )


class TestImportGasDetectorLedger:
    def _detector_xlsx(self, marker: str) -> bytes:
        """构造含仪表 sheet 与探测器 sheet 的台账文件。"""
        return build_xlsx(
            [
                {
                    "name": "仪表台账",
                    "rows": [
                        ["计量器具台账"],
                        ["部门："],
                        ["资产编号", "器具名称"],
                        [f"IM-{marker}", f"压力表{marker}"],
                    ],
                },
                {
                    "name": "有毒气体探测器台账",
                    "rows": [
                        ["探测器台账"],
                        ["部门：安全部"],
                        ["器具名称", "检定时间", "产品编号"],
                        [f"探测器{marker}", "2026-03-01", f"PN-{marker}"],
                    ],
                },
            ]
        )

    async def test_picks_detector_sheet_by_keyword(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """按关键词选择探测器 sheet，第 2 行部门名进入结果。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        result = await service.import_gas_detector_ledger(
            db_session, self._detector_xlsx(marker), "探测器台账.xlsx"
        )
        assert result["imported_count"] == 1
        assert result["sheet_details"][0]["sheet_name"] == "有毒气体探测器台账"
        assert result["sheet_details"][0]["department"] == "安全部"

    async def test_falls_back_to_first_sheet(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无关键词匹配 sheet 时应回退到第一个 sheet。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]
        xlsx = build_xlsx(
            [
                {
                    "name": "随便一个sheet",
                    "rows": [
                        ["标题"],
                        ["部门：测试部"],
                        ["器具名称", "检定时间"],
                        [f"探测器{marker}", "2026-03-01"],
                    ],
                }
            ]
        )
        result = await service.import_gas_detector_ledger(db_session, xlsx, "f.xlsx")
        assert result["imported_count"] == 1

    async def test_existing_product_number_updates_in_place(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产品编号命中旧记录时更新并保留 id。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        from tests.modules.meter.conftest import create_gas_detector

        marker = uuid4().hex[:8]
        old = await create_gas_detector(
            db_session,
            product_number=f"PN-{marker}",
            instrument_name=f"探测器{marker}",
            detection_model="旧型号",
        )
        result = await service.import_gas_detector_ledger(
            db_session, self._detector_xlsx(marker), "探测器台账.xlsx"
        )
        assert result["updated_count"] == 1
        updated = await repo.get_gas_detector_by_id(db_session, old.id)
        assert updated is not None  # id 保留

    async def test_unsupported_extension_rejected(self, db_session: AsyncSession) -> None:
        """不支持的扩展名应抛 ValueError。"""
        with pytest.raises(ValueError):
            await service.import_gas_detector_ledger(db_session, b"", "f.csv")


class TestImportDateTypedCells:
    async def test_date_typed_cell_imports(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """日期格式单元格的检定日期应被导入台账。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        marker = uuid4().hex[:8]

        import io

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["标题行"])
        ws.append(["部门："])
        ws.append(["资产编号", "器具名称", "器具编号", "检定日期"])
        ws.append([f"IM-DT-{marker}", f"日期表{marker}", f"SN-DT-{marker}", datetime(2026, 8, 15)])
        ws.cell(row=4, column=4).number_format = "yyyy-mm-dd"

        buf = io.BytesIO()
        wb.save(buf)
        xlsx = buf.getvalue()

        result = await service.import_instrument_ledger(db_session, xlsx, "日期台账.xlsx")
        assert result["imported_count"] == 1
        records, _ = await repo.list_instruments(db_session, keyword=marker, page_size=200)
        assert records[0].calibration_date == date(2026, 8, 15)
