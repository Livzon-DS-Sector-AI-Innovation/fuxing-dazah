"""人事台账 Excel 通用导入骨架（两步预检式：先 precheck 展示重复/错误明细，再 commit 落库）。

设计要点：
- 每个台账一份 LedgerImportSpec（列头→字段映射、必填列、日期列、查重键），
  列头与对应导出端点一致（导出→修改→再导入可闭环）；
- 查重键比对采用「全量拉取键字段 + 内存比对」（台账数据量千级，最简单可靠）；
- 覆盖语义：命中查重键时仅以 Excel **非空**值更新非键字段（空值不动原值，
  避免"我没填"误清已有数据），与 upload_trainers 的 upsert 语义一致；
- 逐行 begin_nested SAVEPOINT：单行失败只回滚本行，不毒化整体；
- 部门权限：allowed_departments 非空时，越权行在预检阶段即标记跳过。

新增台账导入：在本文件加一份 spec 常量并登记 LEDGER_IMPORT_SPECS 即可，
路由层无需改动。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date as date_cls
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import (
    DepartureRecord,
    HrIncidentRecord,
    OnboardingRecord,
    TrainingLedger,
)
from app.modules.hr.service import EmployeeService
from app.modules.hr.xlsx_utils import write_sheet

logger = logging.getLogger(__name__)


# ─── 规格定义 ───

@dataclass(slots=True)
class LedgerColumn:
    """模板列定义。field=None 表示仅展示核对、不落库（如培训台账的姓名列）。"""

    header: str
    field: str | None
    required: bool = False
    is_date: bool = False
    is_float: bool = False
    choices: dict[str, str] | None = None  # 中文取值 → 库值（如 工伤→work_injury）


@dataclass(slots=True)
class LedgerImportSpec:
    code: str
    label: str
    model: type
    columns: list[LedgerColumn]
    dup_key_fields: list[str]  # 查重键（模型字段名）
    dup_key_display: str  # 查重键中文说明（预检明细展示用）
    example_row: list[object]  # 模板示例行（与 columns 一一对应）
    date_str_fields: tuple[str, ...] = ()  # 库中为字符串的日期字段（比对时 isoformat 化）


ONBOARDING_SPEC = LedgerImportSpec(
    code="onboarding",
    label="入职台账",
    model=OnboardingRecord,
    columns=[
        LedgerColumn("工号", "employee_number", required=True),
        LedgerColumn("姓名", "name", required=True),
        LedgerColumn("部门", "department", required=True),
        LedgerColumn("岗位", "position", required=True),
        LedgerColumn("入职日期", "hire_date", required=True, is_date=True),
        LedgerColumn("学历", "education"),
        LedgerColumn("毕业院校", "school"),
        LedgerColumn("专业", "major"),
        LedgerColumn("手机", "phone"),
        LedgerColumn("是否在职", "is_employed"),
    ],
    dup_key_fields=["employee_number"],
    dup_key_display="工号",
    example_row=["10086", "张三", "甲部门", "操作工", "2024-01-15", "大专", "某某学院", "机械制造", "13800000000", "是"],
)

DEPARTURE_SPEC = LedgerImportSpec(
    code="departure",
    label="离职台账",
    model=DepartureRecord,
    columns=[
        LedgerColumn("姓名", "name", required=True),
        LedgerColumn("工号", "employee_number"),
        LedgerColumn("部门", "department", required=True),
        LedgerColumn("班组", "team"),
        LedgerColumn("职位", "position", required=True),
        LedgerColumn("入丽珠时间", "livo_entry_date", is_date=True),
        LedgerColumn("进厂时间", "factory_entry_date", is_date=True),
        LedgerColumn("参加工作时间", "work_start_date", is_date=True),
        LedgerColumn("离职日期", "offboarding_date", is_date=True),
        LedgerColumn("离职时司龄", "company_tenure_at_leave"),
        LedgerColumn("离职类型", "offboarding_type"),
        LedgerColumn("离职原因", "offboarding_reason"),
        LedgerColumn("学历", "education"),
        LedgerColumn("毕业院校", "school"),
        LedgerColumn("手机", "phone"),
    ],
    dup_key_fields=["employee_number"],
    dup_key_display="工号",
    # 工号为空的行无法查重，commit 阶段直接新增
    example_row=["张三", "10086", "甲部门", "一班", "操作工", "2020-03-01", "2020-03-10",
                 "2015-06-01", "2026-01-31", "5年10个月", "辞职", "个人发展", "大专", "某某学院", "13800000000"],
)

TRAINING_SPEC = LedgerImportSpec(
    code="training",
    label="培训台账",
    model=TrainingLedger,
    columns=[
        LedgerColumn("工号", "employee_number", required=True),
        LedgerColumn("姓名", None),  # 仅核对展示：模型无姓名字段，落库以员工档案/名单为准
        LedgerColumn("培训日期", "training_date", required=True, is_date=True),
        LedgerColumn("培训主题", "training_subject", required=True),
        LedgerColumn("培训方式", "training_method"),
        LedgerColumn("课时", "duration_hours", is_float=True),
        LedgerColumn("培训地点", "location"),
        LedgerColumn("培训单位/培训师", "trainer"),
        LedgerColumn("考核成绩", "assessment_result"),
        LedgerColumn("备注", "remarks"),
    ],
    dup_key_fields=["employee_number", "training_date", "training_subject"],
    dup_key_display="工号+培训日期+培训主题",
    example_row=["10086", "张三", "2024-05-20", "安全生产培训", "线下", "4", "一号会议室", "安环部", "合格", ""],
)

INCIDENT_SPEC = LedgerImportSpec(
    code="incident",
    label="工伤/劳动纠纷台账",
    model=HrIncidentRecord,
    columns=[
        LedgerColumn("类型", "incident_type", required=True,
                     choices={"工伤": "work_injury", "劳动纠纷": "labor_dispute"}),
        LedgerColumn("当事人", "employee_name"),
        LedgerColumn("工号", "employee_number"),
        LedgerColumn("部门", "department"),
        LedgerColumn("发生日期", "occurred_date", required=True, is_date=True),
        LedgerColumn("情况描述", "description"),
        LedgerColumn("状态", "status", choices={"处理中": "processing", "已结案": "closed"}),
        LedgerColumn("备注", "remark"),
    ],
    # 工号可空：键取「工号或姓名」+ 发生日期 + 类型；occurred_date 库中为字符串
    dup_key_fields=["employee_number", "employee_name", "occurred_date", "incident_type"],
    dup_key_display="工号(或当事人)+发生日期+类型",
    example_row=["工伤", "李四", "10087", "甲部门", "2026-03-02", "搬运时右手划伤", "处理中", ""],
    date_str_fields=("occurred_date",),
)

LEDGER_IMPORT_SPECS: dict[str, LedgerImportSpec] = {
    s.code: s for s in (ONBOARDING_SPEC, DEPARTURE_SPEC, TRAINING_SPEC, INCIDENT_SPEC)
}


def get_spec(code: str) -> LedgerImportSpec | None:
    return LEDGER_IMPORT_SPECS.get(code)


# ─── 模板生成 ───

def build_template(spec: LedgerImportSpec) -> Workbook:
    """固定模板：表头 + 1 行灰色示例（仅示例，导入时会被忽略说明提醒）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = spec.label.replace("/", "-")  # sheet 名不允许 / 等字符
    headers = [c.header for c in spec.columns]
    write_sheet(ws, headers, [spec.example_row])
    for cell in ws[2]:
        cell.font = Font(color="808080", italic=True)
    return wb


# ─── 解析 ───

@dataclass(slots=True)
class ParsedRow:
    row_no: int  # Excel 实际行号（表头为第 1 行，数据从 2 起）
    data: dict  # 字段名 → 解析后的值（date/str/float）
    dup_key: tuple  # 查重键（用于比对展示）


@dataclass(slots=True)
class ParsedLedger:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 行级错误（缺必填/日期无法解析等）


def _extract_dup_key(spec: LedgerImportSpec, data: dict) -> tuple:
    key: list[object] = []
    for f in spec.dup_key_fields:
        v = data.get(f)
        if isinstance(v, date_cls):
            v = v.isoformat()  # 统一键的日期形态（库中 occurred_date 等为字符串）
        key.append(v)
    # 工伤类查重键首两位为（工号, 姓名）：工号为空时以姓名兜底，库中/文件口径一致
    if spec.code == "incident" and key and (key[0] is None or key[0] == ""):
        key[0] = key[1] if len(key) > 1 else None
    return tuple(key)


def _dup_key_display(key: tuple) -> str:
    return "+".join(str(v) if v not in (None, "") else "空" for v in key)


async def parse_ledger_excel(file_bytes: bytes, spec: LedgerImportSpec) -> ParsedLedger:
    """解析 Excel → 行数据 + 行级错误。表头按列名匹配（列顺序无关）。"""
    wb = await asyncio.to_thread(load_workbook, BytesIO(file_bytes), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("文件为空")

    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col_map: dict[int, LedgerColumn] = {}
    for idx, h in enumerate(header):
        if not h:
            continue
        for c in spec.columns:
            if c.header == h:
                col_map[idx] = c
                break
    if not col_map:
        raise ValueError(f"未识别到模板表头，请使用「下载模板」的固定列头（需包含：{'、'.join(c.header for c in spec.columns)}）")

    missing_required = [c.header for c in spec.columns if c.required and c.field and c.field not in
                        {cc.field for cc in col_map.values()}]
    if missing_required:
        raise ValueError(f"缺少必填列：{'、'.join(missing_required)}")

    parsed = ParsedLedger()
    for row_no, row in enumerate(rows[1:], start=2):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        data: dict = {}
        row_errors: list[str] = []
        for idx, col in col_map.items():
            if col.field is None:
                continue
            v = row[idx] if idx < len(row) else None
            if v is None or (isinstance(v, str) and not v.strip()):
                if col.required:
                    row_errors.append(f"「{col.header}」为空")
                continue
            if isinstance(v, str):
                v = v.strip()
            if col.is_date:
                parsed_date = EmployeeService._parse_date_value(v)
                if parsed_date is None:
                    row_errors.append(f"「{col.header}」日期无法解析：{v}")
                    continue
                # 库中为字符串的日期列（如工伤台账 occurred_date）落 isoformat 字符串
                v = parsed_date.isoformat() if col.field in spec.date_str_fields else parsed_date
            elif col.is_float:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    row_errors.append(f"「{col.header}」应为数字：{v}")
                    continue
            elif col.choices is not None:
                mapped = col.choices.get(str(v))
                if mapped is None:
                    row_errors.append(f"「{col.header}」仅支持：{'、'.join(col.choices)}")
                    continue
                v = mapped
            data[col.field] = v
        if row_errors:
            parsed.errors.append(f"第 {row_no} 行：" + "；".join(row_errors))
            continue
        parsed.rows.append(ParsedRow(
            row_no=row_no,
            data=data,
            dup_key=_extract_dup_key(spec, data),
        ))
    return parsed


# ─── 查重 ───

async def _load_existing_by_key(spec: LedgerImportSpec, db: AsyncSession) -> dict[tuple, object]:
    """全量拉取库中未软删行 → {查重键: 实例}。

    键统一经 _extract_dup_key 归一化（日期 isoformat、工伤类工号空以姓名兜底）；
    台账量级千行内，内存比对最直接，也规避了字符串日期列无法 SQL 精确匹配的问题。
    """
    model = spec.model
    instances = (await db.execute(
        select(model).where(model.is_deleted.is_(False))
    )).scalars().all()
    return {
        _extract_dup_key(spec, {f: getattr(inst, f) for f in spec.dup_key_fields}): inst
        for inst in instances
    }


@dataclass(slots=True)
class DuplicateHit:
    row_no: int
    key_display: str


async def find_duplicates(
    spec: LedgerImportSpec, parsed: ParsedLedger, db: AsyncSession
) -> list[DuplicateHit]:
    """返回与库中或文件内部查重键冲突的行（文件内部同键多行按重复处理）。"""
    existing = await _load_existing_by_key(spec, db)
    hits: list[DuplicateHit] = []
    seen_in_file: set[tuple] = set()
    for row in parsed.rows:
        if row.dup_key in existing:
            hits.append(DuplicateHit(row.row_no, _dup_key_display(row.dup_key)))
        elif row.dup_key in seen_in_file:
            hits.append(DuplicateHit(row.row_no, _dup_key_display(row.dup_key)))
        else:
            seen_in_file.add(row.dup_key)
    return hits


async def precheck_import(
    spec: LedgerImportSpec,
    parsed: ParsedLedger,
    db: AsyncSession,
    allowed_departments: set[str] | None = None,
) -> dict:
    """预检：不写库，返回新增/重复/错误/越权统计及明细（明细截断 50 条防大文件刷屏）。"""
    duplicates = await find_duplicates(spec, parsed, db)
    dup_rows = {d.row_no for d in duplicates}
    scope_count = sum(
        1 for row in parsed.rows
        if allowed_departments is not None
        and row.data.get("department")
        and row.data.get("department") not in allowed_departments
    )
    return {
        "total": len(parsed.rows),
        "new_count": len(parsed.rows) - len(dup_rows) - scope_count,
        "duplicate_count": len(duplicates),
        "duplicates": [{"row": d.row_no, "key": d.key_display} for d in duplicates[:50]],
        "error_count": len(parsed.errors),
        "errors": parsed.errors[:50],
        "skipped_scope": scope_count,
        "dup_key_display": spec.dup_key_display,
    }


# ─── 落库 ───

async def commit_import(
    spec: LedgerImportSpec,
    parsed: ParsedLedger,
    duplicate_mode: str,  # overwrite / skip
    db: AsyncSession,
    allowed_departments: set[str] | None = None,
) -> dict:
    """执行导入。overwrite=覆盖命中行（非键字段以 Excel 非空值为准），skip=跳过重复行。

    返回 {created, updated, skipped, skipped_scope, errors}；逐行 SAVEPOINT，
    单行失败不影响其他行。文件内部同键多行：首行新增、后续按所选模式处理。
    """
    if duplicate_mode not in ("overwrite", "skip"):
        raise ValueError("duplicate_mode 仅支持 overwrite / skip")

    model = spec.model
    existing_by_key = await _load_existing_by_key(spec, db)
    key_fields = set(spec.dup_key_fields)
    created = updated = skipped = skipped_scope = 0
    errors: list[str] = []

    for row in parsed.rows:
        outcome = ""
        try:
            async with db.begin_nested():
                department = row.data.get("department")
                if allowed_departments is not None and department and department not in allowed_departments:
                    outcome = "scope"
                else:
                    existing = existing_by_key.get(row.dup_key)
                    if existing is not None and duplicate_mode == "skip":
                        outcome = "skipped"
                    elif existing is not None:
                        for f, v in row.data.items():
                            # 键字段与空值不动原值；updated_at 由 onupdate 自动刷新
                            if f in key_fields or v is None or v == "":
                                continue
                            if getattr(existing, f) != v:
                                setattr(existing, f, v)
                        outcome = "updated"
                    else:
                        inst = model(**row.data)
                        db.add(inst)
                        await db.flush()
                        existing_by_key[row.dup_key] = inst  # 文件内部后续同键行按重复处理
                        outcome = "created"
                    await db.flush()
        except Exception as e:  # noqa: BLE001
            errors.append(f"第 {row.row_no} 行: {e}")
            continue
        if outcome == "created":
            created += 1
        elif outcome == "updated":
            updated += 1
        elif outcome == "skipped":
            skipped += 1
        elif outcome == "scope":
            skipped_scope += 1

    await db.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "skipped_scope": skipped_scope,
        "errors": errors,
    }
