"""五金库 Excel 出入口：入库 Excel 解析 + 领料单导出 + 入库模板（2026-11-12）。

入库方式②定为 Excel 解析（用户拍板：不要截图解析）——上传标准模板 xlsx
→ 行解析 → 名称+规格精确匹配主数据 → 返回预填结构（前端核对后经
POST /receipts 落草稿，source=excel）。出库导出=领料单+明细展平单 sheet。

列驱动解析照 erp_import._read_rows 手法（xlsx/csv 容错）；导出照
planning.export_plan_excel 模式（openpyxl→BytesIO）。
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

# ── 入库模板列（固定顺序；模板下载端点与解析共用此定义）──

RECEIVE_COLUMNS = ["物资名称", "规格型号", "数量", "单位", "供应商", "送货单号", "备注"]

# 2026-11-19 改版：入库文件来自 ERP 导出（非人工模板），build_receipt_template
# 模板生成与 /receipts/excel-template 端点一并退役；本列表保留作列口径文档。


# ── 解析 ──


class ExcelParseError(Exception):
    """Excel 解析失败（结构不符/全空/数量非法）——API 层转 422。"""


def _read_html_table(data: bytes) -> tuple[list[str], list[list[Any]]]:
    """ERP 导出「伪 xls」解析（实为 HTML 表格，与 erp_import._read_html_table 同款）。"""
    import re as _re

    from html import unescape as _unescape

    html = data.decode("utf-8", errors="replace")
    table_m = _re.search(r"<table[^>]*>(.*?)</table>", html, _re.S | _re.I)
    scope = table_m.group(1) if table_m else html
    raw_rows = _re.findall(r"<tr[^>]*>(.*?)</tr>", scope, _re.S | _re.I)
    matrix: list[list[str]] = []
    for tr in raw_rows:
        cells = _re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, _re.S | _re.I)
        cleaned = [
            _unescape(_re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip()
            for c in cells
        ]
        if any(cleaned):
            matrix.append(cleaned)
    if len(matrix) < 2:
        return [], []
    header = matrix[0]
    rows = [r + [""] * (len(header) - len(r)) for r in matrix[1:]]
    return header, rows


def _read_matrix(data: bytes, filename: str) -> tuple[list[str], list[list[Any]]]:
    """(表头, 行二维表)：内容嗅探优先（HTML伪xls/真二进制xls），再按扩展名 xlsx/csv。"""
    # 内容嗅探优先（扩展名不可信——ERP 导出 .xls 实为 HTML）：首 512 字节判定
    head = data[:512].lstrip()
    if head[:5].lower() in (b"<html", b"<!doc") or b"<table" in head.lower():
        return _read_html_table(data)
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise ExcelParseError("旧版二进制 .xls 不支持：请在 ERP 中重新导出后上传（新版导出可直接识别）")
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        for encoding in ("utf-8-sig", "gbk"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        rows = [r for r in reader if any(str(c).strip() for c in r)]
        if not rows:
            return [], []
        return [str(c).strip() for c in rows[0]], rows[1:]
    if lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            matrix = [[cell for cell in row] for row in ws.iter_rows(values_only=True)]
            wb.close()
        except Exception as exc:  # noqa: BLE001 — 损坏/非xlsx内容统一转可读错误（BadZipFile/InvalidFileException族）
            raise ExcelParseError(f"Excel 文件损坏或格式不符: {type(exc).__name__}") from exc
        rows = [r for r in matrix if any(c is not None and str(c).strip() for c in r)]
        if not rows:
            return [], []
        return [str(c).strip() if c is not None else "" for c in rows[0]], rows[1:]
    # 其余（.xls 后缀但内容既非 HTML 也非二进制 xls 等）：报可读错误
    raise ExcelParseError("仅支持 xlsx/xls/csv 文件（ERP 导出的 .xls 可直接上传，已自动识别）")


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _qty(v: Any) -> Decimal | None:
    s = _cell(v)
    if not s:
        return None
    try:
        q = Decimal(s)
    except InvalidOperation:
        return None
    if not q.is_finite():  # NaN/Infinity 防崩溃（Decimal 比较对非有限值抛异常）
        return None
    return q if q > 0 else None


# 列别名归一（2026-11-13）：模板口径与 ERP 流水口径（入库单号/入库日期/
# 物料名称/主计量单位…）共用一套解析——与 erp_import._COLUMN_ALIASES 同款。
# canonical → 变体列表（canonical 本身也参与匹配）。
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "物资名称": ("物资名称", "物料名称", "存货名称", "品名"),
    "数量": ("数量", "入库数量", "出库数量"),
    "规格型号": ("规格型号", "规格"),
    "单位": ("单位", "主计量单位", "计量单位", "库存单位"),
    "供应商": ("供应商", "供应商名称"),
    "送货单号": ("送货单号", "入库单号", "单据号", "出库单号"),
    "备注": ("备注", "备注说明"),
}


def parse_receipt_excel(data: bytes, filename: str) -> dict[str, Any]:
    """入库 Excel → {header, items, errors}：名称+规格+数量为主键逐行解析。

    列按表头名匹配（顺序无关），模板口径与 ERP 流水口径自动兼容
    （COLUMN_ALIASES 归一）；缺「物资名称/数量」列=结构错误；逐行
    数量非法/缺名称落 errors（不阻断其他行）。示例行（备注含"示例"）跳过。
    """
    headers, matrix = _read_matrix(data, filename)
    if not headers:
        raise ExcelParseError("文件为空")
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        idx.setdefault(h.strip(), i)

    def _resolve(canonical: str) -> int | None:
        for alias in COLUMN_ALIASES.get(canonical, (canonical,)):
            if alias in idx:
                return idx[alias]
        return None

    col_idx = {c: _resolve(c) for c in COLUMN_ALIASES}
    if col_idx["物资名称"] is None or col_idx["数量"] is None:
        raise ExcelParseError(
            f"缺少必需列「物资名称/数量」（检测到列: {'、'.join(headers[:10])}）；"
            f"请发送 ERP 导出的入库流水 Excel"
        )

    def col(row: list[Any], name: str) -> Any:
        i = col_idx.get(name)
        return row[i] if i is not None and i < len(row) else None

    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    skipped_example = 0
    for ln, row in enumerate(matrix, start=2):  # Excel 行号从 2（1=表头）
        name = _cell(col(row, "物资名称"))
        remark = _cell(col(row, "备注"))
        if not name:
            continue
        if "示例" in remark:
            skipped_example += 1
            continue
        qty = _qty(col(row, "数量"))
        if qty is None:
            errors.append({"row": ln, "name": name, "reason": "数量缺失或非法"})
            continue
        items.append(
            {
                "name": name,
                "spec": _cell(col(row, "规格型号")) or None,
                "unit": _cell(col(row, "单位")) or None,
                "quantity": str(qty),
                "supplier": _cell(col(row, "供应商")) or None,
                "delivery_note_no": _cell(col(row, "送货单号")) or None,
                "remark": remark or None,
            }
        )
    if not items and not errors:
        raise ExcelParseError("未解析到有效数据行（仅有表头？）")

    # 单头取首行的供应商/送货单号（模板口径：整单一致）
    header = {}
    if items:
        header = {
            "supplier_name": items[0].get("supplier"),
            "delivery_note_no": items[0].get("delivery_note_no"),
        }
    return {
        "header": header,
        "items": items,
        "errors": errors,
        "skipped_example": skipped_example,
    }


def build_parse_documents(
    parsed_rows: list[dict[str, Any]], items: list[Any]
) -> list[dict[str, Any]]:
    """解析行按行级「入库单号」分组 → 单据摘要 dicts（ReceiptParseDocument 形状）。

    2026-11-20 拍板：Web 端对齐机器人通道/ERP 导入的既定分单口径——ERP 流水
    文件天然多单，拍平一张草稿会串单号/供应商。parsed_rows=parse_receipt_excel
    返回的原始行（取 delivery_note_no/supplier）；items=匹配后的结构化行
    （取 managed_class 判 stocked/direct/未匹配；getattr 取值便于测试传桩）。
    无单号行归入同一组（key=""，前端展示「（无单号）」）；mode 沿用既定规则
    （有 stocked 物料行=stocked，否则 direct）。
    """
    groups: dict[str, dict[str, Any]] = {}
    for idx, (row, item) in enumerate(zip(parsed_rows, items)):
        key = (row.get("delivery_note_no") or "").strip()
        g = groups.setdefault(
            key,
            {
                "supplier": row.get("supplier"),
                "indexes": [],
                "stocked": 0,
                "direct": 0,
                "unmatched": 0,
            },
        )
        g["indexes"].append(idx)
        mclass = getattr(item, "managed_class", None)
        if mclass == "stocked":
            g["stocked"] += 1
        elif mclass == "direct":
            g["direct"] += 1
        else:
            g["unmatched"] += 1
    return [
        {
            "key": key,
            "delivery_note_no": key or None,
            "supplier_name": g["supplier"],
            "item_indexes": g["indexes"],
            "stocked_count": g["stocked"],
            "direct_count": g["direct"],
            "unmatched_count": g["unmatched"],
            "all_matched": g["unmatched"] == 0,
            "mode": "stocked" if g["stocked"] > 0 else "direct",
        }
        for key, g in groups.items()
    ]


# ── 领料单导出（出库 Excel）──


def export_requisitions_excel(
    reqs: list[Any], items_by_req: dict[Any, list[dict[str, Any]]]
) -> bytes:
    """领料单+明细展平导出（单 sheet；一明细行一物理行，单头字段随行重复）。

    行列：单号/状态/类别/部门/领用人/申请时间/审批通道/审批结果/发料人/
    发料时间/收料人/物资编码/物资名称/规格/单位/需求数量/实发数量/用途/备注。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    status_labels = {
        "draft": "草稿", "pending": "审批中", "approved": "已批准",
        "rejected": "已驳回", "cancelled": "已取消", "issued": "已发料",
    }
    type_labels = {"normal": "常规", "urgent": "紧急", "excess": "超额"}
    channel_labels = {"feishu": "飞书审批", "manual": "系统代录"}

    def fmt_dt(v: Any) -> str:
        if not v:
            return ""
        if isinstance(v, datetime):
            # timestamptz 读回为 UTC-aware → 转北京时间展示（时区红线：导出早8小时教训）
            if v.tzinfo is not None:
                v = v.astimezone(CN_TZ)
            return v.strftime("%Y-%m-%d %H:%M")
        return str(v)

    wb = Workbook()
    ws = wb.active
    ws.title = "领料出库"
    headers = [
        "单号", "状态", "类别", "部门", "领用人", "申请时间", "审批通道", "审批结果",
        "发料人", "发料时间", "收料人", "物资编码", "物资名称", "规格型号", "单位",
        "需求数量", "实发数量", "用途", "备注",
    ]
    ws.append(headers)
    head_fill = PatternFill("solid", fgColor="1F4E79")
    head_font = Font(color="FFFFFF", bold=True)
    for c, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for req in reqs:
        base = [
            req.req_no,
            status_labels.get(req.status, req.status),
            type_labels.get(req.req_type, req.req_type),
            req.dept_name,
            req.applicant,
            fmt_dt(req.created_at),
            channel_labels.get(req.approval_channel or "manual", req.approval_channel or "-"),
            req.approval_status or "",
            req.issued_by or "",
            fmt_dt(req.issued_at),
            req.received_by or "",
        ]
        rows = items_by_req.get(req.id) or []
        for it in rows:
            ws.append(
                base
                + [
                    it.get("material_code") or "",
                    it.get("material_name") or it.get("name") or "",
                    it.get("spec") or "",
                    it.get("unit") or "",
                    float(it.get("need_qty") or 0),
                    float(it["issued_qty"]) if it.get("issued_qty") is not None else None,
                    req.purpose or "",
                    req.rejected_reason or req.approval_note or "",
                ]
            )
        if not rows:
            ws.append(base + ["", "", "", "", None, None, req.purpose or "", ""])

    widths = [16, 8, 6, 12, 10, 17, 10, 10, 10, 17, 10, 14, 22, 26, 6, 10, 10, 24, 20]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
