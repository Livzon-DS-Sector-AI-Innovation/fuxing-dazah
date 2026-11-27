"""劳动合同电子档案库（P2）：扫描件版本流转 / 三级调阅权限 / 两本台账隔离 / 批量挂接。

测试跑在共享本地库的事务里（HR conftest 把 commit 换成 flush，结束统一回滚）；
扫描件落到本地对象存储的文件不随事务回滚，每个上传用例在 finally 里物理清理。
"""

import io
import re
import zipfile
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.core import file_storage
from app.core import storage as object_storage
from app.core.exceptions import ForbiddenException
from app.core.file_storage import cleanup_object, read_object, store_object
from app.modules.hr.deps import HrAccessContext
from app.modules.hr.labor_contract import (
    archive_batch_import,
    archive_scheduled,
    archive_service,
    departure_service,
    service,
)
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import (
    ContractAccessLog,
    ContractArchiveVersion,
    LaborContract,
)
from app.modules.hr.labor_contract.routes import _ensure_in_scope, _list_scope
from app.modules.hr.models import DepartureRecord, Employee

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
API = "/api/v1/hr"


def _number() -> str:
    return str(100000 + uuid4().int % 899999)


def _name() -> str:
    return f"档{uuid4().hex[:4]}"


async def _employee(
    db, *, department: str = "人力资源部", status: str = "在职",
    name: str | None = None, number: str | None = None,
) -> Employee:
    employee = Employee(
        employee_number=number or _number(), name=name or _name(),
        department=department, position="专员", status=status, hire_date=date.today(),
    )
    db.add(employee)
    await db.flush()
    return employee


async def _contract(
    db, employee: Employee, *, seq_no: int = 1, status: str = "active",
    end_date: date | None = None,
) -> LaborContract:
    start = date.today() - timedelta(days=400)
    contract = LaborContract(
        employee_number=employee.employee_number, name=employee.name,
        department=employee.department, position=employee.position,
        seq_no=seq_no, term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=start, end_date=end_date or (start + timedelta(days=365 * 3)),
        status=status,
    )
    db.add(contract)
    await db.flush()
    return contract


async def _cleanup(db, contract_ids=(), keys=()) -> None:
    """物理删除测试写进本地对象存储的文件（DB 行随事务回滚，文件不会）。"""
    stored = (await db.execute(
        select(ContractArchiveVersion.storage_key).where(
            ContractArchiveVersion.contract_id.in_([i for i in contract_ids if i])
        )
    )).scalars().all() if any(contract_ids) else []
    for key in [*stored, *keys]:
        cleanup_object(archive_service.MODULE, key)
    prune_empty_archive_dirs()


def prune_empty_archive_dirs() -> None:
    """本地回退存储删完文件会留下空目录，顺手移除（MinIO 没有目录概念）。"""
    if object_storage.is_enabled():
        return
    root = file_storage.local_root(archive_service.MODULE) / "contracts"
    dirs = sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for path in dirs:
        if not any(path.iterdir()):
            path.rmdir()


def _ctx(user, scope: str, *, department: str | None = None) -> HrAccessContext:
    """构造指定数据范围的访问上下文（HR conftest 默认全是 all，三级权限要分别验证）。"""
    return HrAccessContext(
        user=user, data_scope=scope, department=department,
        employee_number=user.employee_no,
        scoped_departments=frozenset({department}) if department else frozenset(),
    )


# ─── 命名规则 ───


def test_archive_display_name_follows_requirement():
    """需求命名规则：工号+姓名+签订次数+起止日期；无固定期限写「无固定期限」。"""
    fixed = LaborContract(
        employee_number="111003118", name="刘双玲", department="行政后勤部", seq_no=2,
        term_type=LaborContract.TERM_FIXED_6Y, term_years=6,
        start_date=date(2023, 1, 1), end_date=date(2029, 1, 1),
    )
    assert archive_service.archive_display_name(fixed, "pdf") == (
        "111003118_刘双玲_第2次_2023-01-01至2029-01-01.pdf"
    )
    open_ended = LaborContract(
        employee_number="111003118", name="刘双玲", department="行政后勤部", seq_no=3,
        term_type=LaborContract.TERM_OPEN, start_date=date(2029, 1, 2),
    )
    assert archive_service.archive_display_name(open_ended, "png") == (
        "111003118_刘双玲_第3次_2029-01-02至无固定期限.png"
    )


# ─── 上传 / 版本 / 原件调阅 / 留痕 ───


@pytest.mark.asyncio
async def test_upload_versions_file_and_access_log(db_session, client):
    """上传两次升版本（旧版保留）→ 预览/下载留痕 → 删当前版由历史版顶替 → 删空回到未归档。"""
    employee = await _employee(db_session)
    contract = await _contract(db_session, employee)
    base = f"{API}/labor-contracts/{contract.id}"
    try:
        res = await client.post(
            f"{base}/archive", files={"file": ("扫描件.png", PNG, "image/png")},
            data={"remark": "首版"},
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["contract"]["archive_status"] == "archived"
        assert data["contract"]["archive_status_label"] == "已归档"
        assert data["contract"]["archive_uploaded_at"] is not None
        version_1 = data["versions"][0]
        assert version_1["version_no"] == 1 and version_1["is_current"] is True
        assert version_1["remark"] == "首版" and version_1["size"] == len(PNG)
        assert version_1["file_name"] == archive_service.archive_display_name(contract, "png")
        # 存储 key 只用英文安全字符，中文与日期只在展示名里
        stored = await repo.list_versions(db_session, contract.id)
        assert re.fullmatch(r"contracts/[0-9a-f-]{36}/[0-9a-f]{32}\.png", stored[0].storage_key)

        # 已有当前版本再上传 = 换传：必须写明原因，原因存到新版本行上
        res = await client.post(
            f"{base}/archive", files={"file": ("第二版.pdf", PDF, "application/pdf")},
        )
        assert res.status_code == 422 and "原因" in res.json()["message"]
        res = await client.post(
            f"{base}/archive", files={"file": ("第二版.pdf", PDF, "application/pdf")},
            data={"reason": "重扫：补签字页"},
        )
        assert res.status_code == 200, res.text
        versions = res.json()["data"]["versions"]
        assert [v["version_no"] for v in versions] == [2, 1]  # 旧版保留可查
        assert [v["is_current"] for v in versions] == [True, False]
        assert (versions[0]["reason"], versions[1]["reason"]) == ("重扫：补签字页", None)

        # 原件预览 / 下载：内容原样返回，文件名按需求规则
        old_file = f"{base}/archive/{versions[1]['id']}/file"
        res = await client.get(old_file)
        assert res.status_code == 200 and res.content == PNG
        assert "filename*=UTF-8''" in res.headers["content-disposition"]
        res = await client.get(f"{old_file}?download=true")
        assert res.status_code == 200 and res.content == PNG

        # 每次调阅都留痕（view / download 各一条，带版本号）
        res = await client.get(f"{base}/access-logs")
        assert res.status_code == 200, res.text
        logs = res.json()
        assert logs["meta"]["total"] == 2
        assert [x["action"] for x in logs["data"]] == ["download", "view"]
        assert {x["version_no"] for x in logs["data"]} == {1}
        assert all(x["viewer_name"] for x in logs["data"])

        # 删当前版 v2：最新历史版本 v1 顶替
        res = await client.delete(f"{base}/archive/{versions[0]['id']}")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert [v["version_no"] for v in data["versions"]] == [1]
        assert data["versions"][0]["is_current"] is True
        assert data["contract"]["archive_file_name"] == version_1["file_name"]

        # 删到空：合同回到未归档
        res = await client.delete(f"{base}/archive/{versions[1]['id']}")
        assert res.status_code == 200, res.text
        contract_data = res.json()["data"]["contract"]
        assert contract_data["archive_status"] == "unarchived"
        assert contract_data["archive_file_name"] is None
        assert res.json()["data"]["versions"] == []
    finally:
        await _cleanup(db_session, [contract.id])


@pytest.mark.asyncio
async def test_upload_rejects_invalid_files(db_session, client):
    """扩展名不支持 / 内容与扩展名不符 / 空文件 → 422，且不产生任何版本。"""
    employee = await _employee(db_session)
    contract = await _contract(db_session, employee)
    url = f"{API}/labor-contracts/{contract.id}/archive"
    cases = [
        ("说明.txt", b"plain text", "text/plain"),
        ("假的.pdf", PNG, "application/pdf"),  # PNG 内容冒充 PDF
        ("空.png", b"", "image/png"),
    ]
    for filename, content, mime in cases:
        res = await client.post(url, files={"file": (filename, content, mime)})
        assert res.status_code == 422, (filename, res.text)
    assert (await repo.list_versions(db_session, contract.id)) == []
    assert contract.archive_status == LaborContract.ARCHIVE_UNARCHIVED
    await _cleanup(db_session, [contract.id])


# ─── 调阅权限三级 ───


@pytest.mark.asyncio
async def test_file_access_three_tiers(db_session, test_user):
    """HR 全部原件；员工本人仅本人合同；部门范围（即使同部门）拿不到原件。"""
    own = await _contract(db_session, await _employee(db_session, number=test_user.employee_no))
    other = await _contract(db_session, await _employee(db_session))
    try:
        own_version = await archive_service.create_archive_version(
            db_session, contract=own, file_bytes=PNG, filename="own.png", user=test_user,
        )
        other_version = await archive_service.create_archive_version(
            db_session, contract=other, file_bytes=PNG, filename="other.png", user=test_user,
        )

        assert archive_service.can_access_file(_ctx(test_user, "all"), other) is True
        assert archive_service.can_access_file(_ctx(test_user, "self_only"), own) is True
        assert archive_service.can_access_file(_ctx(test_user, "self_only"), other) is False
        assert archive_service.can_access_file(
            _ctx(test_user, "department", department=other.department), other,
        ) is False

        # 部门范围 / 本人范围看他人合同：直接 403，且不留「已调阅」痕迹
        dept_ctx = _ctx(test_user, "department", department=other.department)
        with pytest.raises(ForbiddenException):
            await archive_service.get_archive_file(db_session, dept_ctx, other, other_version)
        with pytest.raises(ForbiddenException):
            await archive_service.get_archive_file(
                db_session, _ctx(test_user, "self_only"), other, other_version,
            )
        assert (await db_session.execute(select(ContractAccessLog))).scalars().all() == []

        # 员工本人看自己合同：放行并留痕
        data, headers = await archive_service.get_archive_file(
            db_session, _ctx(test_user, "self_only"), own, own_version,
        )
        assert data == PNG and "filename*=UTF-8''" in headers["Content-Disposition"]
        logs = (await db_session.execute(select(ContractAccessLog))).scalars().all()
        assert len(logs) == 1
        assert logs[0].action == "view" and logs[0].viewer_name
    finally:
        await _cleanup(db_session, [own.id, other.id])


@pytest.mark.asyncio
async def test_ledger_isolates_departed_and_supports_self_only(db_session, test_user):
    """两本台账不交叉：在职台账不出现离职人员合同；self_only 只见本人；部门范围看不到离职人员合同。"""
    in_service = await _contract(db_session, await _employee(db_session, department="甲部门"))
    departed = await _contract(
        db_session, await _employee(db_session, department="甲部门"), seq_no=2,
    )
    db_session.add(DepartureRecord(
        name="离职者", employee_number=departed.employee_number, department="甲部门",
        position="专员", offboarding_type="个人原因", offboarding_date=date.today(),
    ))
    await db_session.flush()
    own = await _contract(
        db_session, await _employee(db_session, department="乙部门", number=test_user.employee_no),
        seq_no=3,
    )

    async def visible(population: str, employee_number: str) -> bool:
        # 按工号过滤再判断：共享库里有一千多份合同，不能假设测试数据落在第一页
        _, rows = await repo.list_page(
            db_session, population=population, keyword=employee_number,
        )
        return any(c.employee_number == employee_number for c in rows)

    assert await visible("in_service", in_service.employee_number)
    assert await visible("in_service", own.employee_number)
    assert not await visible("in_service", departed.employee_number)
    assert await visible("departed", departed.employee_number)
    assert not await visible("departed", in_service.employee_number)

    # self_only：列表按工号收敛到本人
    number, departments = _list_scope(_ctx(test_user, "self_only"), None)
    assert (number, departments) == (test_user.employee_no, None)
    _, rows = await repo.list_page(
        db_session, employee_number=number, departments=departments, limit=100,
    )
    assert rows and all(c.employee_number == test_user.employee_no for c in rows)

    # 单条校验：本人合同放行、他人合同 403
    await _ensure_in_scope(db_session, _ctx(test_user, "self_only"), own)
    with pytest.raises(ForbiddenException):
        await _ensure_in_scope(db_session, _ctx(test_user, "self_only"), in_service)

    # 部门范围：本部门在职合同可访问；同部门的离职人员合同 403（归离职台账，仅 HR）
    dept_ctx = _ctx(test_user, "department", department="甲部门")
    await _ensure_in_scope(db_session, dept_ctx, in_service)
    with pytest.raises(ForbiddenException, match="离职人员合同"):
        await _ensure_in_scope(db_session, dept_ctx, departed)
    with pytest.raises(ForbiddenException):
        await _ensure_in_scope(
            db_session, _ctx(test_user, "department", department="丙部门"), in_service,
        )


@pytest.mark.asyncio
async def test_department_scope_over_http(db_session, client, test_user):
    """部门范围的 HTTP 口径：台账只见本部门在职合同，原件 403，归档写操作与补扫清单 403。"""
    test_user.department = "甲部门"
    employee = await _employee(db_session, department="甲部门")
    contract = await _contract(db_session, employee)
    await _contract(db_session, await _employee(db_session, department="乙部门"))
    try:
        with patch(
            "app.platform.permission.repository.PermissionRepository"
            ".get_effective_data_scope",
            new_callable=AsyncMock, return_value="department",
        ):
            res = await client.get(f"{API}/labor-contracts", params={"page_size": 100})
            assert res.status_code == 200, res.text
            assert {c["employee_number"] for c in res.json()["data"]} == {employee.employee_number}

            # 档案库即使传 population=all 也被收敛到在职 + 本部门
            res = await client.get(f"{API}/labor-contracts-archive", params={"population": "all"})
            assert {c["employee_number"] for c in res.json()["data"]} == {employee.employee_number}

            res = await client.get(f"{API}/labor-contracts/{contract.id}/archive/versions")
            assert res.status_code == 200
            res = await client.post(
                f"{API}/labor-contracts/{contract.id}/archive",
                files={"file": ("x.png", PNG, "image/png")},
            )
            assert res.status_code == 403
            res = await client.get(f"{API}/labor-contracts-archive/export-unarchived")
            assert res.status_code == 403
            res = await client.get(f"{API}/labor-contracts-archive/stats")
            assert res.status_code == 403
            res = await client.get(f"{API}/departure-contracts")
            assert res.status_code == 403
        assert (await repo.list_versions(db_session, contract.id)) == []
    finally:
        await _cleanup(db_session, [contract.id])


# ─── 档案库台账 / 概览 / 补扫清单 / 员工合同视图 ───


@pytest.mark.asyncio
async def test_archive_library_list_stats_and_export(db_session, client):
    employee = await _employee(db_session)
    unarchived = await _contract(db_session, employee, seq_no=2)
    archived = await _contract(db_session, employee, seq_no=1, status="superseded")
    try:
        await archive_service.create_archive_version(
            db_session, contract=archived, file_bytes=PNG, filename="v1.png",
        )
        res = await client.get(
            f"{API}/labor-contracts-archive",
            params={"archive_status": "unarchived", "keyword": employee.employee_number},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert [c["id"] for c in body["data"]] == [str(unarchived.id)]
        assert body["data"][0]["archive_status_label"] == "未归档"
        assert body["data"][0]["is_departed"] is False

        res = await client.get(f"{API}/labor-contracts-archive/stats")
        assert res.status_code == 200, res.text
        stats = res.json()["data"]
        assert {"in_service_unarchived", "in_service_archived",
                "departed_unarchived", "departed_archived"} <= set(stats)
        assert stats["in_service_archived"] >= 1
        assert stats["can_archive"] is True  # 全量范围：前端据此显示批量挂接等 HR 入口

        # 补扫清单：未归档合同按部门分组导出，表头与归档规则一致（学历列取员工档案）
        res = await client.get(f"{API}/labor-contracts-archive/export-unarchived")
        assert res.status_code == 200
        assert "spreadsheetml" in res.headers["content-type"]
        ws = load_workbook(io.BytesIO(res.content)).active
        assert [c.value for c in ws[1]] == archive_service.UNARCHIVED_EXPORT_HEADERS
        rows = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
        hit = next(r for r in rows if r[1] == employee.employee_number and r[5] == "第二次续签")
        assert not hit[4]  # 该员工档案未填学历
        # 补扫清单去掉了「签字确认时间」列：领取时间之后直接是人员状态、合同状态
        assert hit[11] == "在职" and hit[12] == "生效中"

        res = await client.get(f"{API}/labor-contracts/by-employee/{employee.employee_number}")
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert [c["seq_no"] for c in body["contracts"]] == [1, 2]
        assert body["can_access_file"] is True
    finally:
        await _cleanup(db_session, [archived.id])


# ─── 批量挂接 ───


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _xlsx(header: list[str], rows: list[list[str]]) -> bytes:
    wb = Workbook()
    wb.active.append(header)
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_contract_filename():
    """工号取命中已知工号的数字段（日期段不干扰），签订次数取「第N次」。"""
    known = {"111003118", "111003255"}
    assert archive_batch_import.parse_contract_filename("111003118_刘双玲_第2次.pdf", known) == (
        "111003118", 2,
    )
    assert archive_batch_import.parse_contract_filename("刘双玲-111003118.png", known) == (
        "111003118", None,
    )
    # 日期段不是工号；未知的数字段也不当工号
    assert archive_batch_import.parse_contract_filename("20250701合同.pdf", known) == (None, None)
    assert archive_batch_import.parse_contract_filename("999999999.pdf", known) == (None, None)


@pytest.mark.asyncio
async def test_batch_import_precheck_and_commit(db_session, client):
    """清单优先于文件名；未知工号未匹配；离职人员无合同行可建档后挂接；同份合同一批只挂一个。"""
    one_contract = await _employee(db_session)
    first = await _contract(db_session, one_contract, seq_no=1)
    two_contracts = await _employee(db_session)
    await _contract(db_session, two_contracts, seq_no=1)
    second = await _contract(db_session, two_contracts, seq_no=2)
    # 历史离职人员：不在员工档案，只有离职记录（合同 2026-01-01 ~ 2029-01-01，离职早于到期日）
    departed_number = _number()
    db_session.add(DepartureRecord(
        name=_name(), employee_number=departed_number, department="原部门", position="专员",
        offboarding_type="个人原因", offboarding_date=date.today(),
        contract_start_date=date(2026, 1, 1), contract_end_date=date(2029, 1, 1),
    ))
    await db_session.flush()
    staged_keys: list[str] = []
    built_id = None
    try:
        zip_bytes = _make_zip({
            "清单.xlsx": _xlsx(
                ["工号", "签订次数", "文件名", "备注"],
                [
                    # 清单指定第 2 份（文件名没写签订次数，单靠文件名会「多份待选」）
                    [two_contracts.employee_number, "2", f"子目录/{two_contracts.name}.pdf", "清单行"],
                    ["999999999", "", "999999999_查无此人.pdf", ""],
                ],
            ),
            f"子目录/{two_contracts.name}.pdf": PDF,
            # 无清单行：该员工仅一份合同，自动命中
            f"{one_contract.employee_number}_{one_contract.name}.png": PNG,
            # 有工号无合同行：离职记录可建档
            f"{departed_number}_离职者.png": PNG,
            "999999999_查无此人.pdf": PDF,
        })
        res = await client.post(
            f"{API}/labor-contracts-archive/batch-import/precheck",
            files={"file": ("scans.zip", zip_bytes, "application/zip")},
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        staged_keys.extend(r["storage_key"] for r in body["rows"] if r["storage_key"])
        by_name = {r["filename"]: r for r in body["rows"]}
        manifest_row = by_name[f"子目录/{two_contracts.name}.pdf"]
        assert manifest_row["status"] == "ok" and manifest_row["seq_hint"] == 2
        assert manifest_row["contract"]["id"] == str(second.id)
        assert manifest_row["remark"] == "清单行"
        auto_row = by_name[f"{one_contract.employee_number}_{one_contract.name}.png"]
        assert auto_row["status"] == "ok" and auto_row["contract"]["seq_no"] == 1
        departed_row = by_name[f"{departed_number}_离职者.png"]
        assert departed_row["status"] == "ok" and departed_row["build_from_departure"] is True
        assert departed_row["contract"] is None
        unknown_row = by_name["999999999_查无此人.pdf"]
        assert unknown_row["status"] == "unmatched" and "不存在" in unknown_row["error"]
        assert body["summary"]["ok"] == 3 and body["summary"]["unmatched"] == 1
        assert body["summary"]["builds"] == 1

        rows = [
            {
                "storage_key": r["storage_key"], "filename": r["filename"],
                "contract_id": r["contract"]["id"] if r["contract"] else None,
                "employee_number": (
                    r["employee"]["employee_number"] if r["build_from_departure"] else None
                ),
                "remark": r["remark"] or None,
            }
            for r in body["rows"] if r["status"] == "ok"
        ]
        res = await client.post(
            f"{API}/labor-contracts-archive/batch-import/commit", json={"rows": rows},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["summary"] == {"imported": 3, "failed": 0}

        # 离职人员：按离职记录合同信息建了一份已终止合同（整 3 年 → 标准期限）并挂上扫描件
        built = await repo.list_by_employee(db_session, departed_number)
        built_id = built[0].id
        assert len(built) == 1
        assert built[0].status == LaborContract.STATUS_TERMINATED
        assert built[0].term_type == LaborContract.TERM_FIXED_3Y
        assert built[0].terminated_reason == "员工辞职解除"
        assert built[0].archive_status == LaborContract.ARCHIVE_ARCHIVED
        # 暂存文件搬正式后清掉
        assert read_object(archive_service.MODULE, manifest_row["storage_key"]) is None
        versions = await repo.list_versions(db_session, second.id)
        assert len(versions) == 1 and versions[0].source == ContractArchiveVersion.SOURCE_BATCH

        # 同一份合同一批只能挂一个文件：第一个成功升版（换传须写原因），第二个被拒
        restaged = f"{archive_batch_import.STAGING_PREFIX}test/{uuid4().hex}.pdf"
        store_object(archive_service.MODULE, restaged, PDF, "application/pdf")
        res = await client.post(
            f"{API}/labor-contracts-archive/batch-import/commit",
            json={"rows": [
                {"storage_key": restaged, "filename": "a.pdf", "contract_id": str(second.id),
                 "reason": "重扫"},
                {"storage_key": restaged, "filename": "b.pdf", "contract_id": str(second.id)},
            ]},
        )
        result = res.json()["data"]
        assert result["summary"] == {"imported": 1, "failed": 1}
        assert "同一份合同" in result["results"][1]["error"]

        res = await client.get(
            f"{API}/labor-contracts-archive/batch-import/options",
            params={"keyword": one_contract.name},
        )
        options = res.json()["data"]
        assert options[0]["employee_number"] == one_contract.employee_number
        assert [c["id"] for c in options[0]["contracts"]] == [str(first.id)]
    finally:
        await _cleanup(db_session, [first.id, second.id, built_id], keys=staged_keys)


@pytest.mark.asyncio
async def test_batch_import_rejects_bad_zip_and_bad_manifest(db_session, client):
    res = await client.post(
        f"{API}/labor-contracts-archive/batch-import/precheck",
        files={"file": ("scans.zip", b"not a zip", "application/zip")},
    )
    assert res.status_code == 400
    res = await client.post(
        f"{API}/labor-contracts-archive/batch-import/precheck",
        files={"file": ("only.txt.zip", _make_zip({"说明.txt": b"x"}), "application/zip")},
    )
    assert res.status_code == 400 and "没有可导入的扫描件" in res.json()["message"]
    # 清单缺「工号」列：在写任何暂存文件之前就拒绝
    res = await client.post(
        f"{API}/labor-contracts-archive/batch-import/precheck",
        files={"file": ("bad.zip", _make_zip({
            "清单.xlsx": _xlsx(["姓名", "文件名"], [["张三", "a.pdf"]]), "a.pdf": PDF,
        }), "application/zip")},
    )
    assert res.status_code == 400 and "缺少「工号」" in res.json()["message"]


# ─── 办结衔接：离职人员合同归入离职台账 ───


@pytest.mark.asyncio
async def test_reconcile_departed_contracts_excludes_them_from_renewal_scan(db_session):
    """预警排除验证：离职日期已到的人员，其生效合同归入离职台账（terminated）；
    离职日期未到（办理中）的合同状态不动。两种人的合同都不再出现在到期扫描里。"""
    soon = date.today() + timedelta(days=10)
    leaving = await _employee(db_session)
    leaving_contract = await _contract(db_session, leaving, end_date=soon)
    staying = await _employee(db_session)
    staying_contract = await _contract(db_session, staying, end_date=soon)
    in_clearance = await _employee(db_session)
    clearance_contract = await _contract(db_session, in_clearance, end_date=soon)
    db_session.add_all([
        DepartureRecord(
            name=leaving.name, employee_number=leaving.employee_number,
            department=leaving.department, position="专员",
            offboarding_type="个人原因", offboarding_date=date.today(),
        ),
        DepartureRecord(
            name=in_clearance.name, employee_number=in_clearance.employee_number,
            department=in_clearance.department, position="专员",
            offboarding_type="个人原因", offboarding_date=date.today() + timedelta(days=30),
        ),
    ])
    await db_session.flush()

    async def scanned(contract_id) -> bool:
        return contract_id in {
            c.id for c in await service.find_expiring_active(db_session, days_ahead=50)
        }

    # 台账里登记了将要离职（离职日期 ≥ 今天）的人，扫描前就不再进入公告期
    assert not await scanned(leaving_contract.id)
    assert await scanned(staying_contract.id)
    assert not await scanned(clearance_contract.id)

    reconciled = await departure_service.reconcile_departed_contracts(db_session)

    assert [c.id for c in reconciled] == [leaving_contract.id]
    assert leaving_contract.status == LaborContract.STATUS_TERMINATED
    assert leaving_contract.terminated_reason == "员工辞职解除"  # 离职日早于到期日 = 辞职解除
    assert leaving_contract.departure_record_id is not None
    assert staying_contract.status == LaborContract.STATUS_ACTIVE
    assert clearance_contract.status == LaborContract.STATUS_ACTIVE  # 办理中不动

    assert not await scanned(leaving_contract.id)
    assert await scanned(staying_contract.id)
    assert not await scanned(clearance_contract.id)
    # 幂等：再跑一次没有可归入的合同
    assert await departure_service.reconcile_departed_contracts(db_session) == []


# ─── 周提醒 / 暂存清理 ───


def test_cleanup_stale_staging_keeps_recent_files(tmp_path, monkeypatch):
    """按暂存路径的日期段清理超期文件，未超期的保留；在临时目录里跑，不碰真实 uploads。"""
    monkeypatch.setattr(
        file_storage, "get_settings", lambda: SimpleNamespace(UPLOAD_DIR=str(tmp_path)),
    )
    prefix = archive_batch_import.STAGING_PREFIX
    old_key = f"{prefix}20260101/{uuid4().hex}/{uuid4().hex}.pdf"
    recent_key = f"{prefix}20261120/{uuid4().hex}/{uuid4().hex}.pdf"
    store_object(archive_service.MODULE, old_key, PDF, "application/pdf")
    store_object(archive_service.MODULE, recent_key, PDF, "application/pdf")

    assert archive_batch_import.cleanup_stale_staging(today=date(2026, 11, 25)) == 1
    assert read_object(archive_service.MODULE, old_key) is None
    assert read_object(archive_service.MODULE, recent_key)[0] == PDF
    assert not (tmp_path / "hr" / prefix / "20260101").exists()  # 空目录一并移除
    assert archive_batch_import.cleanup_stale_staging(today=date(2026, 11, 25)) == 0  # 幂等


@pytest.mark.asyncio
async def test_archive_reminder_counts_before_rollback(monkeypatch):
    """周提醒是只读汇总：回滚会让 ORM 实例过期，各项计数必须在回滚前算完
    （否则异步下再读属性抛 MissingGreenlet）。发送与接收人解析全部打桩，不触达飞书。"""
    captured: dict = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)
        return len(kwargs["receivers"])

    async def fake_receivers(db, entries):
        return ["ou_test"]

    monkeypatch.setattr(archive_scheduled.notify, "send_archive_summary", fake_send)
    monkeypatch.setattr(archive_scheduled, "resolve_receivers", fake_receivers)

    await archive_scheduled.run_archive_reminder()

    if captured:  # 库里有未归档合同才发；空库走提前返回
        total = captured["in_service_count"] + captured["departed_count"]
        assert total > 0
        assert sum(count for _, count in captured["department_counts"]) == total
        assert captured["receivers"] == ["ou_test"]
