"""《危险品日报表》电子表格直读读取器（chemical-inventory-sheet-source P1-T1）。

数据源：飞书电子表格（人维护的唯一事实源），子表按产品线/单元/职能部门拆分，
表头驱动自适应两种版式（产品线子表带标题行+表头在 r2；部门子表无标题行+表头在 r1，
如 环保工程中心/精制工程部/QC/仓库 等 2026-10-19 实测）。与 InventoryBitableReader
同协议（InventoryRecordsReader.fetch_all(strict)），经 open_reader() 按源开关注入，
下游（风险规则/每日分析/快照/速递/API/驾驶舱）零改动复用。

读取管线：
1. metainfo 枚举子表（revision 供 D6「数据未更新」判定；注意 rowCount 是网格行数，
   实测空表也 ~200，空表判定只能靠「前 N 行找不到表头锚点」）；
2. 逐子表 read_sheet(range)（窗口由 metainfo 维度驱动，500 行上限截断时 strict 上抛）；
3. 表头驱动列映射：扫前 5 行找含「危险品名称」的表头行，按列名关键词建映射，
   未知列忽略；无锚点视为空/异常表跳过；
4. 行 → InventoryView：危险品名称空跳过；数量/上限带单位解析（单元格后缀
   '3000g'/'1L' > 显式「单位」列 > 未映射列裸单位词 > 表头 /kg 默认），质量单位
   （kg/g/T）归一 total_quantity_t 与 max_limit（T，与 R01-R03 同口径），体积单位
   （L/ml）不可折吨、total_quantity_t=None；规格透传不解析；危险性关键词映射
   （「易燃易爆」→仅 flammable 复合规则，_hazard_classes 迁自 excel_parser 并扩展）。

口径铁律：不回写源表；未映射子表标题原样透传 + anomalies 告警（编排层上送日报
标注列异常）。行标识 "{sheet_id}:{行号}" 稳定且可追溯回单元格；updated_at 落
读取时刻（revision 才是行级新鲜度之上的真信号，见 D6）。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.safety.chemical_inventory.enum_maps import (
    _DEPT_LABEL_TO_ENUM,
    _text,
)
from app.modules.safety.service.chemical_inventory_direct.views import (
    InventoryView,
    sort_like_inventory,
)

__all__ = ["SheetsInventoryReader"]

logger = logging.getLogger(__name__)

# 表头扫描窗口（产品线子表标题 r1+表头 r2；部门子表表头 r1；留裕量）
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
    # 部门子表（提炼技术精进中心实测）：显式「单位」列（kg/g/L/ml 逐行）
    ("单位", "unit"),
)

# 危险性关键词 → 枚举（迁自 excel_parser._HAZARD_TEXT_MAP，P2 退役随引擎删码；
# 扩展：致癌/粉尘 为 2026-10-19 部门子表新标签，additive 不动旧值）
_HAZARD_TEXT_MAP: list[tuple[str, str]] = [
    ("易制毒", "precursor_drug"),
    ("易制爆", "precursor_explosive"),
    ("易燃", "flammable"),
    ("易爆", "explosive"),
    ("氧化", "oxidizer"),
    ("腐蚀", "corrosive"),
    ("毒性", "toxic"),
    ("刺激", "irritant"),
    ("致癌", "carcinogenic"),
    ("粉尘", "dust"),
]

# 单位词归一（大小写/全角变体 → 标准枚举；体积 L/ml 不可折吨）
_UNIT_TOKENS: dict[str, str] = {
    "kg": "kg", "Kg": "kg", "KG": "kg", "g": "g", "G": "g",
    "T": "T", "t": "T",
    "L": "L", "l": "L", "ml": "ml", "mL": "ml", "ML": "ml",
}
_MASS_UNITS = {"kg", "g", "T"}

# 数值+可选单位后缀（'3000g' / '1L' / '10' / '4.5'）
_NUM_UNIT_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?|\.[0-9]+)\s*([A-Za-z]{1,2})?\s*$")

# 质量单位 → 吨换算因子（kg÷1000、g÷1e6、T×1；体积不换算）
_TONNES_FACTOR = {"kg": Decimal("0.001"), "g": Decimal("0.000001"), "T": Decimal("1")}

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


def _hazard_classes(text: Any) -> list[str]:
    """危险性文本 → 枚举列表（迁自 excel_parser，行为保留）。

    「易燃易爆」为口语化标签，指易燃液体（如乙醇/丙酮），并非易爆品——
    只映射为 flammable，避免把常见溶剂误标为 explosive。
    """
    if not text:
        return []
    s = str(text)
    result: list[str] = []
    composite_explosive = "易燃易爆" in s
    for kw, enum in _HAZARD_TEXT_MAP:
        if kw in s and enum not in result:
            if enum == "explosive" and composite_explosive:
                continue
            result.append(enum)
    return result


def _num_with_unit(raw: Any) -> tuple[Decimal | None, str | None]:
    """解析「数值+可选单位后缀」：'3000g'→(3000,'g')，'10'→(10,None)。

    非数值/非白名单单位（如 '暂未使用'、'kg/桶'）→ (None, None)，不猜。
    """
    if raw is None or raw == "":
        return None, None
    m = _NUM_UNIT_RE.match(str(raw))
    if m is None:
        return None, None
    value = Decimal(m.group(1))
    suffix = _UNIT_TOKENS.get(m.group(2)) if m.group(2) else None
    if m.group(2) and suffix is None:
        return None, None  # 后缀不是已知单位（如 'x'），整值不猜
    return value, suffix


def _bare_unit_token(value: Any) -> str | None:
    """裸单位词判定（'ml'/'L'/'kg'）：部门子表无表头的行级单位列用。"""
    s = _text(value)
    return _UNIT_TOKENS.get(s) if s else None


def _to_tonnes(value: Decimal, unit: str) -> Decimal | None:
    """质量单位 → 吨；体积单位（L/ml）不可折吨返回 None。"""
    factor = _TONNES_FACTOR.get(unit)
    return value * factor if factor is not None else None


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
            return []  # 整表全空（预留子表）：预期状态，静默跳过
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

        # 行级单位解析（优先级：单元格后缀 > 显式「单位」列 > 未映射列裸单位词；
        # 缺省 kg——产品线子表表头「当前数量/kg」的口径）
        quantity, qty_unit = _num_with_unit(cell("quantity"))
        max_raw, limit_unit = _num_with_unit(cell("max_limit"))
        row_unit = _bare_unit_token(cell("unit"))
        if row_unit is None:
            # 部门子表存在无表头的行级单位列（提炼半合成实测：危险性后第 10 列 'ml'）：
            # 未映射列里的裸单位词兜底识别，防止把 ml/L 数值当 kg
            used_cols = set(columns.values())
            for idx, value in enumerate(row):
                if idx in used_cols:
                    continue
                token = _bare_unit_token(value)
                if token is not None:
                    row_unit = token
                    break
        qty_unit = qty_unit or row_unit or "kg"
        limit_unit = limit_unit or row_unit or "kg"

        record_id = f"{sheet_id}:{row_no}"
        hazard = _hazard_classes(cell("hazard_classes")) or None
        location = _clean_location(_text(cell("storage_location")) or "")

        # 质量单位（kg/g/T）归一为吨参与 R01-R03 超量口径；体积（L/ml）不折吨
        total_t = _to_tonnes(quantity, qty_unit) if quantity is not None else None
        if limit_unit in _MASS_UNITS and max_raw is not None:
            max_limit_t: Decimal | None = _to_tonnes(max_raw, limit_unit)
            max_limit_unit: str | None = "T"
        else:
            # 体积上限保留原值原单位（展示用；超量规则按质量口径自然跳过）
            max_limit_t = max_raw
            max_limit_unit = limit_unit if max_raw is not None else None

        return InventoryView(
            id=record_id,
            feishu_record_id=record_id,
            created_at=None,
            updated_at=self.last_read_at,
            is_deleted=False,
            department=department,
            storage_location=location or None,
            material_name=material_name,
            package_spec=_text(cell("package_spec")),
            quantity=quantity,
            unit=qty_unit if quantity is not None else None,
            total_quantity_t=total_t,
            # 一昼夜使用量：数值部分透传（体积行无 kg 语义，展示字段）
            daily_usage_kg=_num_with_unit(cell("daily_usage_kg"))[0],
            max_limit=max_limit_t,
            max_limit_unit=max_limit_unit,
            hazard_classes=hazard,
            category=_text(cell("category")),
            last_updated_at=self.last_read_at,
        )
