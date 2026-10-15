"""《危险品日报表》电子表格直读读取器（chemical-inventory-sheet-source P1-T1）。

数据源：飞书电子表格（人维护的唯一事实源），13 子表按产品线/单元拆分，列结构统一
（唯一例外：危废库缺「一昼夜使用量」列）。与 InventoryBitableReader 同协议
（InventoryRecordsReader.fetch_all(strict)），经 open_reader() 按源开关注入，
下游（风险规则/每日分析/快照/速递/API/驾驶舱）零改动复用。

读取管线：
1. metainfo 枚举子表（revision 供 D6「数据未更新」判定；注意 rowCount 是网格行数，
   实测空表也 ~200，空表判定只能靠「前 N 行找不到表头锚点」）；
2. 逐子表 read_sheet(range)（窗口由 metainfo 维度驱动，500 行上限截断时 strict 上抛）；
3. 表头驱动列映射：扫前 5 行找含「危险品名称」的表头行，按列名关键词建映射，
   未知列忽略（替考孤例备注列自然吞掉）；无锚点视为空/异常表跳过；
4. 行 → InventoryView：危险品名称空跳过；kg 数量 ÷1000 归一 total_quantity_t、
   库存上限 ÷1000 归一 T（与 R01-R03 同口径）；规格透传不解析；
   危险性复用 excel_parser._hazard_classes（「易燃易爆」→仅 flammable 等既有规则）。

口径铁律：不回写源表；未映射子表标题/未映射危险性标签原样透传 + anomalies 告警
（编排层上送日报标注列异常）。行标识 "{sheet_id}:{行号}" 稳定且可追溯回单元格；
updated_at 落读取时刻（revision 才是行级新鲜度之上的真信号，见 D6）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.safety.chemical_inventory.enum_maps import (
    _DEPT_LABEL_TO_ENUM,
    _num,
    _text,
)
from app.modules.safety.chemical_inventory.excel_parser import _hazard_classes
from app.modules.safety.service.chemical_inventory_direct.views import (
    InventoryView,
    sort_like_inventory,
)

__all__ = ["SheetsInventoryReader"]

logger = logging.getLogger(__name__)

# 表头扫描窗口（设计 D3：扫前 5 行；实测表头恒在第 2 行，第 1 行是「xx危险化学品库存」标题）
_HEADER_SCAN_ROWS = 5

# 列名关键词 → InventoryView 字段（首个命中列生效；未知列忽略）
# 「危险品名称」同时是表头锚点：无锚点 = 空/异常表，整表跳过。
_HEADER_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("存放部位", "storage_location"),
    ("危险品名称", "material_name"),
    ("规格", "package_spec"),
    ("管理类别", "category"),
    ("当前数量", "quantity"),
    ("一昼夜使用量", "daily_usage_kg"),
    ("库存上限", "max_limit"),
    ("危险性", "hazard_classes"),
)

_KG_PER_TONNE = Decimal("1000")

# metainfo rowCount / read_sheet 行数上限（防源表异常膨胀拖垮日报：超限 strict 上抛）
_MAX_ROWS = 500
_MAX_COLS = 100


def _column_letter(index: int) -> str:
    """1-based 列号 → Excel 列字母（19→S，20→T）。"""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _clean_location(value: str) -> str:
    """存放部位清理：去换行（达巴 row29 尾部换行实测）与首尾空白。"""
    return value.replace("\r", "").replace("\n", "").strip()


def _detect_header(rows: list[list[Any]]) -> tuple[int, dict[str, int]] | None:
    """在前 N 行找表头锚点行，返回 (行下标, 字段→列下标映射)；找不到返回 None。"""
    for idx, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any("危险品名称" in c for c in cells):
            continue
        columns: dict[str, int] = {}
        for col, cell in enumerate(cells):
            for keyword, field in _HEADER_KEYWORDS:
                if keyword in cell and field not in columns:
                    columns[field] = col
                    break
        return idx, columns
    return None


class SheetsInventoryReader:
    """《危险品日报表》电子表格直读读取器（client 可注入，测试零真机依赖）。

    strict 语义照 bitable reader：False（查询/统计容错：metainfo 失败返回空、
    单子表读失败跳过）、True（日报编排：任一 IO 失败聚合上抛 RuntimeError →
    调度器标 failed 补发）。

    每次成功 fetch_all 后暴露 last_revision / last_read_at（D6 revision 记录）；
    anomalies 为**当次读取**的异常清单（未映射子表/无表头跳表/数据列缺失，
    每次 fetch_all 重置），供编排层上送日报标注。
    """

    def __init__(self, client: Any, spreadsheet_token: str) -> None:
        self._client = client
        self._token = spreadsheet_token
        self.last_revision: int | None = None
        self.last_read_at: datetime | None = None
        self.anomalies: list[str] = []

    async def fetch_all(self, *, strict: bool = False) -> list[InventoryView]:
        self.anomalies = []  # 每次读取重累计（open_reader 进程内单例复用本实例）
        meta = await self._fetch_metainfo(strict)
        if meta is None:
            return []
        self.last_revision = meta.get("revision")
        self.last_read_at = datetime.now(UTC)

        views: list[InventoryView] = []
        for sheet in meta.get("sheets") or []:
            views.extend(await self._fetch_sheet(sheet, strict=strict))
        return sort_like_inventory(views)

    async def _fetch_metainfo(self, strict: bool) -> dict[str, Any] | None:
        """metainfo 一次（revision + 子表清单）；失败按 strict 语义处理。"""
        result = await self._client.read_sheet_metainfo(self._token)
        if result.kind == "error" or not isinstance(result.content, dict):
            message = result.error or "metainfo 返回结构异常"
            if strict:
                raise RuntimeError(f"危险品日报表 metainfo 读取失败: {message}")
            logger.warning("危险品日报表 metainfo 读取失败（容错返回空）: %s", message)
            return None
        return result.content

    async def _fetch_sheet(
        self, sheet: dict[str, Any], *, strict: bool
    ) -> list[InventoryView]:
        sheet_id = str(sheet.get("sheetId") or "")
        title = str(sheet.get("title") or "")
        rows_total = int(sheet.get("rowCount") or 0)
        cols_n = min(int(sheet.get("columnCount") or 1), _MAX_COLS)
        if not sheet_id or rows_total <= 0:
            return []
        if rows_total > _MAX_ROWS:
            # rowCount 是网格行数（空表也 ~200），超限意味着真实数据行远超预期：
            # 截断读会静默丢行，日报口径不可接受
            if strict:
                raise RuntimeError(
                    f"危险品日报表子表行数超过读取上限 {_MAX_ROWS} [{sheet_id} {title}] "
                    f"rowCount={rows_total}"
                )
            logger.warning(
                "危险品日报表子表行数超过读取上限，按窗口截断读取 [%s %s] rowCount=%s",
                sheet_id, title, rows_total,
            )
        rows_n = min(rows_total, _MAX_ROWS)

        sheet_range = f"{sheet_id}!A1:{_column_letter(cols_n)}{rows_n}"
        result = await self._client.read_sheet(self._token, sheet_range)
        if result.kind == "error" or not isinstance(result.content, list):
            message = result.error or "values 返回结构异常"
            if strict:
                raise RuntimeError(f"危险品日报表子表读取失败 [{sheet_id} {title}]: {message}")
            logger.warning("危险品日报表子表读取失败，跳过 [%s %s]: %s", sheet_id, title, message)
            return []
        if result.truncated:
            # 行数窗口截断：数据不完整，日报口径不可静默接受
            if strict:
                raise RuntimeError(
                    f"危险品日报表子表行数超过读取窗口 [{sheet_id} {title}]"
                )
            logger.warning("危险品日报表子表截断，结果可能不完整 [%s %s]", sheet_id, title)

        return self._parse_sheet(sheet_id, title, result.content)

    def _parse_sheet(
        self, sheet_id: str, title: str, rows: list[list[Any]]
    ) -> list[InventoryView]:
        if all(v in (None, "") for row in rows for v in row):
            return []  # 整表全空（预留子表，实测发酵/提炼/Sheet12）：预期状态，静默跳过
        header = _detect_header(rows)
        if header is None:
            self.anomalies.append(f"子表[{title or sheet_id}]有内容但未找到表头（前 {_HEADER_SCAN_ROWS} 行无「危险品名称」），已跳过")
            logger.warning("危险品日报表子表无表头锚点，跳过: sheet_id=%s title=%s", sheet_id, title)
            return []
        header_idx, columns = header
        if "quantity" not in columns:
            self.anomalies.append(f"子表[{title}]缺少「当前数量」列")
            logger.warning("危险品日报表子表缺「当前数量」列: sheet_id=%s title=%s", sheet_id, title)

        department = _DEPT_LABEL_TO_ENUM.get(title, title)
        if title and title not in _DEPT_LABEL_TO_ENUM:
            self.anomalies.append(f"子表[{title}]未映射部门枚举，标签原样透传")
            logger.warning("危险品日报表出现未映射子表标题，department 透传: %s", title)

        views: list[InventoryView] = []
        for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            view = self._row_to_view(sheet_id, department, columns, row, row_idx)
            if view is not None:
                views.append(view)
        return views

    def _row_to_view(
        self,
        sheet_id: str,
        department: str,
        columns: dict[str, int],
        row: list[Any],
        row_no: int,
    ) -> InventoryView | None:
        def cell(field: str) -> Any:
            col = columns.get(field)
            return row[col] if col is not None and col < len(row) else None

        material_name = _text(cell("material_name"))
        if not material_name:
            return None  # 空行/标题行自然跳过（D3：非空才成行）

        record_id = f"{sheet_id}:{row_no}"
        quantity = _num(cell("quantity"))
        max_limit = _num(cell("max_limit"))
        hazard = _hazard_classes(cell("hazard_classes")) or None
        location = _clean_location(_text(cell("storage_location")) or "")
        spec = _text(cell("package_spec"))

        return InventoryView(
            id=record_id,
            feishu_record_id=record_id,
            created_at=None,
            updated_at=self.last_read_at,
            is_deleted=False,
            department=department,
            storage_location=location or None,
            material_name=material_name,
            package_spec=spec,
            quantity=quantity,
            unit="kg" if quantity is not None else None,
            total_quantity_t=(
                quantity / _KG_PER_TONNE if quantity is not None else None
            ),
            daily_usage_kg=_num(cell("daily_usage_kg")),
            max_limit=max_limit / _KG_PER_TONNE if max_limit is not None else None,
            max_limit_unit="T" if max_limit is not None else None,
            hazard_classes=hazard,
            category=_text(cell("category")),
            last_updated_at=self.last_read_at,
        )
