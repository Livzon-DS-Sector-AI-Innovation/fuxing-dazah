"""合同扫描件批量挂接（P2-5）：存量电子档（如本科以上已有扫描件）一次性挂到对应合同。

两步预检式（与证件批量导入同模式）：
- precheck：上传 ZIP（扫描件 + 可选 Excel 清单），逐文件匹配「工号 + 签订次数」；
  合法文件先存暂存区（contracts/_batch/<批次>/），返回逐行状态供确认页修正
- commit：按确认行正式归档，版本化规则同单个上传（已有扫描件的升为新版本）

匹配优先级：Excel 清单 > 文件名解析。文件名取命中已知工号的数字段为工号、「第N次」
为签订次数；未写签订次数时该员工仅一份合同自动命中、多份待选。离职记录有工号但
无合同行的，可在提交时按离职记录合同信息建档后挂接。

Excel 清单列：工号 | 签订次数（选填）| 文件名（ZIP 内文件名，有子文件夹时可写相对路径）
文件名约定：111003118_张三_第1次.pdf、张三-111003118.pdf 等（分隔符随意，日期段不干扰）
"""

import io
import logging
import re
import uuid as uuid_mod
import zipfile
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.file_storage import (
    cleanup_object,
    is_safe_key,
    read_object,
    store_object,
    validate_upload,
)
from app.modules.hr.deps import HrAccessContext
from app.modules.hr.labor_contract import archive_service, departure_service
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import ContractArchiveVersion, LaborContract
from app.modules.hr.models import DepartureRecord, Employee

logger = logging.getLogger(__name__)

STAGING_PREFIX = "contracts/_batch/"
STAGING_MAX_AGE_DAYS = 7  # 预检后这么久仍未提交的暂存文件，由周任务清掉
MAX_ZIP_SIZE = 200 * 1024 * 1024
MAX_UNCOMPRESSED = 400 * 1024 * 1024  # 防压缩炸弹：解压总量上限
MAX_BATCH_FILES = 200
MAX_MANIFEST_SIZE = 5 * 1024 * 1024
MAX_OPTIONS = 20

MANIFEST_HEADERS = ["工号", "签订次数（选填）", "文件名", "备注（选填）"]
MANIFEST_EXAMPLES = [
    ["111003118", "1", "刘双玲_劳动合同.pdf", "存量扫描件"],
    ["111003255", "", "扫描件/刘天清.pdf", ""],
]

# 清单表头别名（包含匹配；同一列命中多个字段时先到先得）
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "number": ("工号", "员工编号"),
    "seq": ("签订次数", "合同次序", "第几次", "次数"),
    "filename": ("文件名", "扫描件", "附件", "文件"),
    "remark": ("备注",),
}

_DIGIT_TOKEN = re.compile(r"\d{4,}")
_SEQ_RE = re.compile(r"第\s*(\d{1,2})\s*次")


# ═══════════════════════════════════════════════════════════════
# ZIP / Excel 清单 / 文件名解析
# ═══════════════════════════════════════════════════════════════

def _member_name(info: zipfile.ZipInfo) -> str:
    """ZIP 成员名：未打 UTF-8 标记（Windows 简中常见 GBK）时尝试转码。"""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            name = name.encode("cp437").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def _is_junk_member(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(p in ("__MACOSX",) or p.startswith(".") for p in parts[:-1]) or \
        parts[-1].startswith(".")


def _is_manifest(name: str) -> bool:
    return name.lower().endswith(".xlsx")


def _is_scan_like(name: str) -> bool:
    """扩展名像是扫描件（内容是否合法由 validate_upload 再判）。"""
    return PurePosixPath(name).suffix.lower() in archive_service._ALLOWED_EXTENSIONS


def _norm_key(filename: str) -> str:
    """清单文件名匹配键：统一分隔符与大小写（清单里路径分隔符与 ZIP 不一致也能对上）。"""
    return filename.strip().replace("\\", "/").lower()


def _find_manifest_entry(
    entries: dict[str, dict[str, str]], filename: str,
) -> dict[str, str] | None:
    """清单行查找：相对路径精确命中优先，退到主文件名（清单没写子文件夹也能对上）。"""
    key = _norm_key(filename)
    if key in entries:
        return entries[key]
    base = PurePosixPath(key).name
    return next((v for k, v in entries.items() if PurePosixPath(k).name == base), None)


def _cell_str(value) -> str:
    """Excel 单元格转字符串：数值型工号/次数去掉小数尾巴。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_contract_filename(filename: str, known_numbers: set[str]) -> tuple[str | None, int | None]:
    """文件名 → (工号, 签订次数)。工号取命中已知工号的数字段（日期段自然排除）。"""
    stem = PurePosixPath(filename.replace("\\", "/")).name.rsplit(".", 1)[0]
    seq_match = _SEQ_RE.search(stem)
    seq_no = int(seq_match.group(1)) if seq_match else None
    number = next((tok for tok in _DIGIT_TOKEN.findall(stem) if tok in known_numbers), None)
    return number, seq_no


def read_manifest(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> dict[str, dict[str, str]]:
    """读取 Excel 清单：{文件名匹配键: {number, seq, remark}}。"""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(zf.read(info)), read_only=True, data_only=True)
    except Exception:
        raise ValueError("Excel 清单无法读取，请使用 .xlsx 格式并从导入模板另存")
    ws = wb.active
    columns: dict[str, int] = {}
    entries: dict[str, dict[str, str]] = {}
    header_found = False
    for values in ws.iter_rows(values_only=True):
        if not header_found:
            for idx, cell in enumerate(values):
                text = _cell_str(cell)
                for field, aliases in _HEADER_ALIASES.items():
                    if field not in columns and any(alias in text for alias in aliases):
                        columns[field] = idx
            if "number" in columns and "filename" in columns:
                header_found = True
            continue
        filename = _cell_str(values[columns["filename"]])
        if not filename:
            continue
        seq_raw = _cell_str(values[columns["seq"]]) if "seq" in columns else ""
        entries[_norm_key(filename)] = {
            "number": _cell_str(values[columns["number"]]),
            "seq": seq_raw if seq_raw.isdigit() else "",
            "remark": _cell_str(values[columns["remark"]]) if "remark" in columns else "",
        }
    if not header_found:
        raise ValueError("Excel 清单缺少「工号」或「文件名」列，请使用导入模板")
    return entries


# ═══════════════════════════════════════════════════════════════
# 索引与选项
# ═══════════════════════════════════════════════════════════════

async def _load_departures(db: AsyncSession) -> dict[str, DepartureRecord]:
    """离职台账索引：{工号: 最新一条离职记录}（历史离职人员多不在员工档案，须单独建索引）。"""
    rows = (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.is_deleted.is_(False),
            DepartureRecord.employee_number.is_not(None),
        ).order_by(
            DepartureRecord.offboarding_date.desc().nulls_last(),
            DepartureRecord.created_at.desc(),
        )
    )).scalars().all()
    result: dict[str, DepartureRecord] = {}
    for row in rows:
        if row.employee_number:
            result.setdefault(row.employee_number, row)
    return result


def _contract_brief(contract: LaborContract) -> dict[str, Any]:
    return {
        "id": str(contract.id),
        "seq_no": contract.seq_no,
        "seq_label": contract.seq_label,
        "period": f"{contract.start_date}~{contract.end_date or '无固定'}",
        "status_label": contract.status_label,
        "archive_status": contract.archive_status,
    }


def _person(employee_number: str | None, name: str, department: str, source: str) -> dict[str, Any]:
    return {"employee_number": employee_number, "name": name, "department": department, "source": source}


async def search_options(db: AsyncSession, keyword: str | None) -> list[dict[str, Any]]:
    """批量导入补选：按姓名/工号搜员工档案与离职台账，返回各自的合同清单（供选合同）。"""
    kw = (keyword or "").strip()
    if not kw:
        return []
    like = f"%{kw}%"
    employees = (await db.execute(
        select(Employee.employee_number, Employee.name, Employee.department).where(
            Employee.is_deleted.is_(False),
            or_(Employee.name.ilike(like), Employee.employee_number.ilike(like)),
        ).limit(MAX_OPTIONS)
    )).all()
    departed = (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.is_deleted.is_(False),
            DepartureRecord.employee_number.is_not(None),
            or_(DepartureRecord.name.ilike(like), DepartureRecord.employee_number.ilike(like)),
        ).order_by(
            DepartureRecord.offboarding_date.desc().nulls_last(),
            DepartureRecord.created_at.desc(),
        )
    )).scalars().all()

    persons: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in employees:
        seen.add(row.employee_number)
        persons.append(_person(row.employee_number, row.name, row.department, "employee"))
    for row in departed:
        if row.employee_number in seen:
            continue
        seen.add(row.employee_number)
        persons.append(_person(row.employee_number, row.name, row.department, "departure"))
    persons = persons[:MAX_OPTIONS]

    departure_by_number = {d.employee_number: d for d in departed}
    contracts_map = await repo.map_contracts_for_numbers(db, [p["employee_number"] for p in persons])
    return [
        {
            **person,
            "contracts": [_contract_brief(c) for c in contracts_map.get(person["employee_number"], [])],
            # 离职记录有工号但无合同行：提交时按离职记录合同信息建档
            "build_from_departure": departure_service.can_build_from_departure(
                departure_by_number.get(person["employee_number"])
            ) and not contracts_map.get(person["employee_number"]),
        }
        for person in persons
    ]


# ═══════════════════════════════════════════════════════════════
# 预检
# ═══════════════════════════════════════════════════════════════

async def precheck_import(db: AsyncSession, *, zip_bytes: bytes) -> dict[str, Any]:
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValueError(f"ZIP 包大小不能超过 {MAX_ZIP_SIZE // (1024 * 1024)}MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("不是有效的 ZIP 文件，请重新打包上传")

    members = [
        i for i in zf.infolist()
        if not i.is_dir() and not _is_junk_member(i.filename)
    ]
    manifests = [i for i in members if _is_manifest(_member_name(i))]
    if len(manifests) > 1:
        raise ValueError("ZIP 内只能有一个 Excel 清单文件")
    scans = [i for i in members if not _is_manifest(_member_name(i))]
    scan_count = sum(1 for i in scans if _is_scan_like(_member_name(i)))
    if not scan_count:
        raise ValueError("ZIP 内没有可导入的扫描件（图片/PDF）")
    if scan_count > MAX_BATCH_FILES:
        raise ValueError(f"单批最多 {MAX_BATCH_FILES} 个文件，请分批导入")
    if sum(i.file_size for i in members) > MAX_UNCOMPRESSED:
        raise ValueError("ZIP 解压后总大小超限，请分批导入")

    manifest_info = manifests[0] if manifests else None
    if manifest_info is not None and manifest_info.file_size > MAX_MANIFEST_SIZE:
        raise ValueError("Excel 清单文件过大")
    manifest_entries = (
        read_manifest(zf, manifest_info) if manifest_info is not None else {}
    )

    employees = (await db.execute(
        select(Employee.employee_number, Employee.name, Employee.department)
        .where(Employee.is_deleted.is_(False))
    )).all()
    employee_index = {e.employee_number: e for e in employees}
    departure_index = await _load_departures(db)
    known_numbers = set(employee_index) | set(departure_index)

    # 第一遍：确定每个文件的工号/签订次数，再一次性取合同，避免逐文件查库
    parsed: list[tuple[zipfile.ZipInfo, str, str | None, int | None, str]] = []
    for info in sorted(scans, key=_member_name):
        filename = _member_name(info)
        entry = _find_manifest_entry(manifest_entries, filename)
        if entry is not None:
            number = entry["number"] or None
            seq_no = int(entry["seq"]) if entry["seq"] else None
            remark = entry["remark"]
        else:
            number, seq_no = parse_contract_filename(filename, known_numbers)
            remark = ""
        parsed.append((info, filename, number, seq_no, remark))

    contracts_map = await repo.map_contracts_for_numbers(
        db, sorted({n for _, _, n, _, _ in parsed if n})
    )
    current_versions = await _map_current_versions(db, [
        c.id for contracts in contracts_map.values() for c in contracts
    ])

    rows: list[dict[str, Any]] = []
    batch_id = uuid_mod.uuid4().hex
    staged_day = date.today().strftime("%Y%m%d")
    for info, filename, number, seq_no, remark in parsed:
        row: dict[str, Any] = {
            "filename": filename, "status": "ok", "error": None,
            "number_hint": number, "seq_hint": seq_no, "remark": remark,
            "employee": None, "contract": None, "candidates": [],
            "build_from_departure": False,
            "storage_key": None, "content_type": None, "size": 0,
            "replaces": None, "dup_in_batch": False,
        }
        try:
            data = zf.read(info)
            _, ext, mime = validate_upload(
                filename, data,
                allowed=archive_service._ALLOWED_EXTENSIONS,
                max_size=archive_service._MAX_SIZE,
                kind_label="图片/PDF 扫描件", default_name="contract",
            )
        except AppException as e:
            row["status"], row["error"] = "invalid", str(e.message)
            rows.append(row)
            continue
        except Exception:
            row["status"], row["error"] = "invalid", "文件读取失败，可能已损坏"
            rows.append(row)
            continue

        contracts = contracts_map.get(number, []) if number else []
        contract: LaborContract | None = None
        if not number:
            row["status"], row["error"] = "unmatched", "未识别到工号，请手动选择员工与合同"
        elif not contracts and number not in employee_index and number not in departure_index:
            row["status"], row["error"] = "unmatched", f"工号 {number} 不存在"
        elif not contracts:
            departure = departure_index.get(number)
            if departure_service.can_build_from_departure(departure):
                # 离职人员无合同行：提交时按离职记录合同信息建档
                row["build_from_departure"] = True
                row["employee"] = _person(number, departure.name, departure.department, "departure")
            else:
                row["status"] = "unmatched"
                row["error"] = "该离职记录缺少合同起始日期，无法建档，请先在离职台账补录"
        elif seq_no is not None:
            contract = next((c for c in contracts if c.seq_no == seq_no), None)
            if contract is None:
                row["status"], row["error"] = "unmatched", f"工号 {number} 无第 {seq_no} 份合同"
        elif len(contracts) == 1:
            contract = contracts[0]
        else:
            row["status"] = "ambiguous"
            row["error"] = "该员工有多份合同，请选择签订次数"
            row["candidates"] = [_contract_brief(c) for c in contracts]
        if contract is not None:
            row["employee"] = _person(
                number, contract.name, contract.department, "employee",
            )
            row["contract"] = _contract_brief(contract)
            current = current_versions.get(contract.id)
            if current is not None:
                row["replaces"] = {"version_no": current.version_no, "file_name": current.file_name}

        # 暂存目录带日期段：周任务按日期段清理超期未提交的暂存文件
        key = f"{STAGING_PREFIX}{staged_day}/{batch_id}/{uuid_mod.uuid4().hex}.{ext}"
        store_object(archive_service.MODULE, key, data, mime)
        row.update({"storage_key": key, "content_type": mime, "size": len(data)})
        rows.append(row)

    # 同批多个文件指向同一份合同：每个版本只能对一个文件，预检阶段先亮出来
    seen_contracts: dict[str, str] = {}
    for row in rows:
        contract = row["contract"]
        if contract is None:
            continue
        if contract["id"] in seen_contracts:
            row["dup_in_batch"] = True
        seen_contracts.setdefault(contract["id"], row["filename"])

    return {"rows": rows, "summary": {
        "total": len(rows),
        "ok": sum(r["status"] == "ok" for r in rows),
        "ambiguous": sum(r["status"] == "ambiguous" for r in rows),
        "unmatched": sum(r["status"] == "unmatched" for r in rows),
        "invalid": sum(r["status"] == "invalid" for r in rows),
        "replaces": sum(bool(r["replaces"]) for r in rows),
        "builds": sum(r["build_from_departure"] for r in rows),
    }}


async def _map_current_versions(
    db: AsyncSession, contract_ids: list[UUID],
) -> dict[UUID, ContractArchiveVersion]:
    if not contract_ids:
        return {}
    rows = (await db.execute(
        select(ContractArchiveVersion).where(
            ContractArchiveVersion.contract_id.in_(contract_ids),
            ContractArchiveVersion.is_current.is_(True),
            ContractArchiveVersion.is_deleted.is_(False),
        )
    )).scalars().all()
    return {v.contract_id: v for v in rows}


# ═══════════════════════════════════════════════════════════════
# 暂存区清理
# ═══════════════════════════════════════════════════════════════

def cleanup_stale_staging(*, today: date | None = None) -> int:
    """清理超期未提交的暂存文件（预检后未匹配/被放弃的行留下的孤儿对象）。返回清理数量。

    暂存路径 contracts/_batch/<YYYYMMDD>/<批次>/…，按日期段判断是否超过
    STAGING_MAX_AGE_DAYS；MinIO 与本地目录回退两种存储都适用。
    """
    from app.core import storage as object_storage
    from app.core.file_storage import delete_object, local_root

    today = today or date.today()
    cutoff = (today - timedelta(days=STAGING_MAX_AGE_DAYS)).strftime("%Y%m%d")
    if object_storage.is_enabled():
        keys = object_storage.list_objects(archive_service.MODULE, STAGING_PREFIX)
    else:
        root = local_root(archive_service.MODULE) / STAGING_PREFIX
        keys = [str(p.relative_to(local_root(archive_service.MODULE))) for p in root.rglob("*") if p.is_file()]
    removed = 0
    for key in keys:
        parts = key.removeprefix(STAGING_PREFIX).split("/", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[0] < cutoff:
            delete_object(archive_service.MODULE, key)
            removed += 1
    if removed and not object_storage.is_enabled():
        # 本地回退：删完文件顺手移除空目录
        root = local_root(archive_service.MODULE) / STAGING_PREFIX
        for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(path.iterdir()):
                path.rmdir()
    return removed


# ═══════════════════════════════════════════════════════════════
# 提交
# ═══════════════════════════════════════════════════════════════

class ArchiveImportCommitRow(BaseModel):
    storage_key: str
    filename: str
    contract_id: UUID | None = None
    # 离职人员无合同行时传工号：按离职记录合同信息建档后挂接
    employee_number: str | None = None
    remark: str | None = None


class ArchiveImportCommitPayload(BaseModel):
    rows: list[ArchiveImportCommitRow]


async def commit_import(
    db: AsyncSession, ctx: HrAccessContext, rows: list[ArchiveImportCommitRow],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("没有可导入的行")

    results: list[dict[str, Any]] = []
    imported = 0
    seen_contracts: dict[UUID, str] = {}
    for r in rows:
        result: dict[str, Any] = {
            "filename": r.filename, "employee_name": None, "seq_label": None,
            "version_no": None, "ok": False, "error": None,
        }
        contract: LaborContract | None = None
        try:
            if r.contract_id is not None:
                contract = await repo.get(db, r.contract_id)
                if contract is None:
                    raise ValueError("合同不存在，请重新预检")
            elif r.employee_number:
                departure = await repo.get_departure_record(db, r.employee_number)
                if departure is None:
                    raise ValueError("未找到离职记录，请重新预检")
                contract = await departure_service.ensure_departure_contract(
                    db, departure, user=ctx.user,
                )
            else:
                raise ValueError("未指定合同")
        except (AppException, ValueError) as e:
            results.append(result | {"error": e.message if isinstance(e, AppException) else str(e)})
            continue

        result["employee_name"] = contract.name
        result["seq_label"] = contract.seq_label
        if contract.id in seen_contracts:
            results.append(result | {
                "error": f"与「{seen_contracts[contract.id]}」指向同一份合同，每份合同一批只能挂一个文件",
            })
            continue
        seen_contracts[contract.id] = r.filename

        if not is_safe_key(r.storage_key) or not r.storage_key.startswith(STAGING_PREFIX):
            results.append(result | {"error": "附件暂存键不合法，请重新上传 ZIP 预检"})
            continue
        staged = read_object(archive_service.MODULE, r.storage_key)
        if staged is None:
            results.append(result | {"error": "暂存附件已失效，请重新上传 ZIP 预检"})
            continue
        data, _mime = staged

        try:
            version = await archive_service.create_archive_version(
                db, contract=contract, file_bytes=data, filename=r.filename,
                remark=r.remark, user=ctx.user,
                source=ContractArchiveVersion.SOURCE_BATCH,
            )
        except AppException as e:
            results.append(result | {"error": str(e.message)})
            continue

        cleanup_object(archive_service.MODULE, r.storage_key)  # 暂存搬正式后清掉
        from app.platform.audit.service import record_audit_log

        await record_audit_log(
            db, action="hr.contract.archive_upload", user=ctx.user,
            resource_type=archive_service.RESOURCE_TYPE, resource_id=contract.id,
            new_value={"version_no": version.version_no, "filename": version.file_name,
                       "batch_import": True},
        )
        results.append(result | {"ok": True, "version_no": version.version_no})
        imported += 1

    return {
        "results": results,
        "summary": {"imported": imported, "failed": len(rows) - imported},
    }
