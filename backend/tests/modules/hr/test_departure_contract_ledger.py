"""离职合同台账（P3）：终止方式判定 / 筛选与聚合视图兜底 / 人工项维护 / 情况说明导出 / 接口范围。

终止方式的离职类型取值用离职台账的真实数据（个人原因/实习结束/退休/部门劝退/调合成公司…）。
测试跑在共享本地库的事务里；离职页签上传的扫描件在 finally 里物理清理。
"""

import io
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.exceptions import AppException
from app.core.file_storage import cleanup_object
from app.modules.hr.labor_contract import archive_service, departure_service
from app.modules.hr.labor_contract import departure_ledger as ledger
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import ContractArchiveVersion, LaborContract
from app.modules.hr.models import DepartureRecord
from tests.modules.hr.test_labor_contract_archive import prune_empty_archive_dirs

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
API = "/api/v1/hr"


def _number() -> str:
    return str(100000 + uuid4().int % 899999)


async def _departure(
    db, *, department: str, offboarding_type: str = "个人原因",
    offboarding_date: date | None = date.today(),
    contract_start: date | None = date(2026, 1, 1),
    contract_end: date | None = date(2029, 1, 1),
) -> DepartureRecord:
    departure = DepartureRecord(
        name=f"离{uuid4().hex[:4]}", employee_number=_number(), department=department,
        position="专员", offboarding_type=offboarding_type, offboarding_date=offboarding_date,
        contract_start_date=contract_start, contract_end_date=contract_end,
    )
    db.add(departure)
    await db.flush()
    return departure


# ─── 判定规则（纯函数）───


@pytest.mark.parametrize(("offboarding_type", "leave", "contract_end", "has_contract", "expected"), [
    ("个人原因", date(2026, 6, 1), date(2028, 7, 1), True, "resign"),    # 期内离职 = 辞职解除
    ("个人原因", date(2026, 7, 1), date(2026, 7, 1), True, "expiry"),    # 到期日当天离开 = 到期终止
    ("个人原因", date(2026, 8, 1), date(2026, 7, 1), True, "expiry"),    # 合同期满后才离开
    ("个人原因", None, date(2026, 7, 1), True, "resign"),                # 无离职日期：按离职类型
    ("实习结束", date(2026, 6, 1), date(2026, 9, 1), True, "expiry"),
    ("退休", date(2026, 6, 1), date(2028, 7, 1), True, "retire"),
    ("退休返聘到期", date(2026, 6, 1), date(2026, 7, 1), True, "expiry"),
    ("部门劝退", date(2026, 6, 1), date(2028, 7, 1), True, "employer"),
    ("辞退", date(2026, 6, 1), None, True, "employer"),                  # 无固定期限合同被辞退
    ("调合成公司", date(2026, 6, 1), None, True, "transfer"),
    ("2026-06", date(2026, 6, 1), date(2028, 7, 1), True, "other"),      # 源表脏取值归「其他」
    (None, date(2026, 6, 1), date(2028, 7, 1), True, "other"),
    ("其他", date(2026, 6, 1), None, False, "none"),                     # 没有任何合同信息
    ("个人原因", None, None, False, "none"),
    ("退休", date(2026, 6, 1), date(2028, 7, 1), False, "none"),        # 没有合同就谈不上怎么终止
])
def test_derive_termination_type_rules(offboarding_type, leave, contract_end, has_contract, expected):
    """无合同信息 > 退休 > 到期类类型 > 离职日不早于合同到期日 > 辞职类 > 公司解除类 > 调动转签 > 其他。"""
    assert departure_service.derive_termination_type(
        offboarding_type, leave, contract_end, has_contract=has_contract,
    ) == expected


def test_term_from_dates():
    """离职记录按起止日期建档：整 3/6 年按标准期限，其余记实际年数，不足一年如实标注。"""
    assert departure_service.term_from_dates(date(2023, 1, 1), date(2026, 1, 1)) == ("fixed_3y", 3)
    assert departure_service.term_from_dates(date(2020, 1, 1), date(2026, 1, 1)) == ("fixed_6y", 6)
    assert departure_service.term_from_dates(date(2022, 7, 1), date(2031, 7, 1)) == ("fixed", 9)
    assert departure_service.term_from_dates(date(2026, 1, 1), date(2026, 8, 1)) == ("fixed", None)
    assert departure_service.term_label("fixed", None) == "不足 1 年"
    assert departure_service.term_from_dates(date(2026, 1, 1), None) == ("open", None)


def test_derive_certificate_status_prefers_offboarding_case():
    """证明开具/送达：有办结单以办结单为准，否则看台账签字/开具字段。"""
    def record(sign_status=None, issued=None):
        return SimpleNamespace(cert_sign_status=sign_status, cert_issued_at=issued)

    pending_case = SimpleNamespace(status="approving", cert_issued_at=None, paper_signed_at=None)
    assert departure_service.derive_certificate_status(record(), pending_case) == "pending"
    issuing = SimpleNamespace(status="cert_issuing", cert_issued_at=None, paper_signed_at=None)
    assert departure_service.derive_certificate_status(record(), issuing) == "pending"
    issued = SimpleNamespace(
        status="cert_issuing", cert_issued_at="2026-11-01 10:00", paper_signed_at=None,
    )
    assert departure_service.derive_certificate_status(record(), issued) == "issued"
    delivering = SimpleNamespace(
        status="delivering", cert_issued_at="2026-11-01 10:00", paper_signed_at=None,
    )
    assert departure_service.derive_certificate_status(record(), delivering) == "delivering"
    signed = SimpleNamespace(
        status="signed", cert_issued_at="2026-11-01 10:00", paper_signed_at=None,
    )
    assert departure_service.derive_certificate_status(record(), signed) == "signed"
    # 没有办结单：台账自己的开具/签字字段
    assert departure_service.derive_certificate_status(record()) == "pending"
    assert departure_service.derive_certificate_status(record(issued="x")) == "issued"
    assert departure_service.derive_certificate_status(record(sign_status="signed")) == "signed"


# ─── 筛选（SQL 判定）与聚合视图 ───


@pytest.mark.asyncio
async def test_sql_termination_filter_matches_python_rule(db_session):
    """按终止方式筛选走 SQL 表达式，必须与 Python 判定逐条一致；人工更正优先；导出与列表同口径。"""
    department = f"合同台账测试{uuid4().hex[:6]}"
    resigned = await _departure(db_session, department=department)  # 2026-01 ~ 2029-01，今天离职
    intern = await _departure(
        db_session, department=department, offboarding_type="实习结束",
        contract_start=date(2026, 1, 1), contract_end=date(2026, 3, 1),
    )  # 到期后才离开 → 到期终止
    retiree = await _departure(db_session, department=department, offboarding_type="退休")
    transfer = await _departure(
        db_session, department=department, offboarding_type="调合成公司", contract_end=None,
    )
    no_record = await _departure(
        db_session, department=department, contract_start=None, contract_end=None,
    )  # 没有任何合同信息：即使离职类型是「个人原因」也不给合同判终止方式
    overridden = await _departure(
        db_session, department=department, offboarding_type="个人原因",
    )
    overridden.contract_termination_type = "employer"
    # 有合同行：以合同行的到期日为准（与离职记录自带到期日不同）
    with_rows = await _departure(
        db_session, department=department,
        contract_start=date(2020, 1, 1), contract_end=date(2020, 6, 1),
    )
    db_session.add(LaborContract(
        employee_number=with_rows.employee_number, name=with_rows.name,
        department=with_rows.department, position="专员", seq_no=1,
        term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=date(2026, 1, 1), end_date=date(2029, 1, 1),
        status=LaborContract.STATUS_TERMINATED,
    ))
    await db_session.flush()

    async def typed(departure: DepartureRecord) -> str:
        _, rows = await ledger.page_rows(db_session, department=department, keyword=departure.employee_number)
        [row] = [r for r in rows if r["id"] == str(departure.id)]
        return row["termination_type"]

    assert await typed(resigned) == "resign"
    assert await typed(intern) == "expiry"
    assert await typed(retiree) == "retire"
    assert await typed(transfer) == "transfer"
    assert await typed(no_record) == "none"
    assert await typed(overridden) == "employer"  # 人工更正压过自动判定
    assert await typed(with_rows) == "resign"    # 合同行到期日 2029 > 离职日

    expected_by_id = {
        str(resigned.id): "resign", str(intern.id): "expiry", str(retiree.id): "retire",
        str(transfer.id): "transfer", str(no_record.id): "none",
        str(overridden.id): "employer", str(with_rows.id): "resign",
    }
    mine_total = 0
    for termination_type in departure_service.TERMINATION_LABELS:
        total, rows = await ledger.page_rows(db_session, department=department, termination_type=termination_type)
        for row in rows:
            assert expected_by_id[row["id"]] == termination_type
        exported = await ledger.export_rows(db_session, department=department, termination_type=termination_type)
        assert len(exported) == total
        mine_total += total
    assert mine_total == len(expected_by_id) == 7

    # 离职时间筛选（七条都是今天离职）+ 全量导出
    total, _ = await ledger.page_rows(
        db_session, department=department, date_from=date.today() - timedelta(days=1),
    )
    assert total == len(expected_by_id)
    lines = await ledger.export_rows(db_session, department=department)
    assert all(len(line) == len(ledger.STATEMENT_HEADERS) for line in lines)


@pytest.mark.asyncio
async def test_build_view_fallback_and_contract_rows(db_session):
    """无合同行退回离职记录自带起止日期；有合同行以合同为准；办结单提供流程单号与证明状态。"""
    from app.modules.hr.offboarding.models import OffboardingCase

    department = f"合同台账视图{uuid4().hex[:6]}"
    fallback = await _departure(
        db_session, department=department, offboarding_type="实习结束",
        contract_start=date(2023, 2, 1), contract_end=date(2026, 2, 1),
    )
    with_rows = await _departure(
        db_session, department=department,
        contract_start=date(2020, 1, 1), contract_end=date(2020, 6, 1),
    )
    contract = LaborContract(
        employee_number=with_rows.employee_number, name=with_rows.name,
        department=with_rows.department, position="专员", seq_no=1,
        term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=date(2023, 2, 1), end_date=date(2029, 2, 1),
        status=LaborContract.STATUS_TERMINATED, terminated_reason="员工辞职解除",
    )
    db_session.add(contract)
    await db_session.flush()
    db_session.add(OffboardingCase(
        case_no=f"LB-TEST-{uuid4().hex[:8].upper()}", employee_id=uuid4(),
        departure_record_id=with_rows.id, employee_number=with_rows.employee_number,
        name=with_rows.name, department=with_rows.department,
        offboarding_date=with_rows.offboarding_date, status="closed",
        cert_issued_at=None,
    ))
    await db_session.flush()

    _, rows = await ledger.page_rows(db_session, department=department, keyword=fallback.employee_number)
    [view] = rows
    assert view["has_contract_rows"] is False and view["contract_count_known"] is False
    assert view["contract_periods_text"] == "2023-02-01~2026-02-01"
    assert view["term_label_last"] == "3 年"
    assert view["termination_type"] == "expiry" and view["termination_type_overridden"] is False
    assert view["termination_date"] == "2026-02-01"  # 到期终止以合同到期日为准
    assert view["archive_status_label"] == "未归档"
    assert view["process_no_source"] is None and view["certificate_status"] == "pending"
    assert view["contract_original_status_label"] == "未回收"

    _, rows = await ledger.page_rows(db_session, department=department, keyword=with_rows.employee_number)
    [view] = rows
    assert view["has_contract_rows"] is True and view["contract_count"] == 1
    assert view["contract_periods_text"] == "第1次 2023-02-01~2029-02-01"
    assert view["termination_type"] == "resign" and view["termination_date"] == date.today().isoformat()
    assert view["separation_process_no"].startswith("LB-TEST-") and view["process_no_source"] == "case"
    assert view["certificate_status"] == "signed"  # 办结单已办结：签收状态压过空的证明开具时间
    assert ledger.statement_line(1, view)[13] == view["separation_process_no"]


@pytest.mark.asyncio
async def test_ensure_departure_contract_and_update_procedure(db_session):
    """无合同行的离职人员按离职记录建档（幂等）；人工项可维护、清空更正即恢复自动判定。"""
    departure = await _departure(db_session, department="建档测试")
    built = await departure_service.ensure_departure_contract(db_session, departure)
    assert (await departure_service.ensure_departure_contract(db_session, departure)).id == built.id
    assert built.status == LaborContract.STATUS_TERMINATED
    assert (built.term_type, built.term_years) == (LaborContract.TERM_FIXED_3Y, 3)
    assert built.departure_record_id == departure.id

    missing_start = await _departure(db_session, department="建档测试", contract_start=None, contract_end=None)
    with pytest.raises(AppException, match="缺少合同起始日期"):
        await departure_service.ensure_departure_contract(db_session, missing_start)

    await departure_service.update_procedure(
        db_session, departure, termination_type="employer", approval_ref="审批单 123",
        separation_process_no="LC-001", original_status="recovered",
    )
    assert (departure.contract_termination_type, departure.contract_approval_ref) == ("employer", "审批单 123")
    assert departure.contract_original_status == "recovered"
    await departure_service.update_procedure(
        db_session, departure, termination_type="", approval_ref=None,
        separation_process_no=None, original_status="waived",
    )
    assert departure.contract_termination_type is None
    assert departure.separation_process_no is None
    with pytest.raises(AppException, match="终止方式取值不合法"):
        await departure_service.update_procedure(
            db_session, departure, termination_type="none", approval_ref=None,
            separation_process_no=None, original_status="recovered",
        )
    with pytest.raises(AppException, match="原件回收状态取值不合法"):
        await departure_service.update_procedure(
            db_session, departure, termination_type=None, approval_ref=None,
            separation_process_no=None, original_status="lost",
        )


# ─── HTTP ───


@pytest.mark.asyncio
async def test_departure_ledger_endpoints(db_session, client):
    department = f"合同台账接口{uuid4().hex[:6]}"
    departure = await _departure(db_session, department=department)
    base = f"{API}/departure-records/{departure.id}"
    try:
        res = await client.get(f"{API}/departure-contracts/filter-options")
        assert res.status_code == 200, res.text
        assert {o["value"] for o in res.json()["data"]["termination_types"]} == set(
            departure_service.TERMINATION_LABELS
        )

        res = await client.get(
            f"{API}/departure-contracts",
            params={"department": department, "termination_type": "resign"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["meta"]["total"] == 1 and body["data"][0]["id"] == str(departure.id)
        assert body["data"][0]["termination_type_label"] == "员工辞职解除"

        # 情况说明导出：标题 + 导出信息 + 表头 + 数据行
        res = await client.get(f"{API}/departure-contracts/export", params={"department": department})
        assert res.status_code == 200 and "spreadsheetml" in res.headers["content-type"]
        ws = load_workbook(io.BytesIO(res.content)).active
        assert ws["A1"].value == "离职人员合同情况说明"
        assert "共 1 人" in ws["A2"].value
        assert [c.value for c in ws[4]] == ledger.STATEMENT_HEADERS
        row = [c.value for c in ws[5]]
        assert row[10] == "员工辞职解除" and row[15] == "未回收"

        res = await client.put(
            f"{base}/contract-procedure",
            json={
                "termination_type": "employer", "approval_ref": "审批单 123",
                "separation_process_no": "LC-001", "contract_original_status": "recovered",
            },
        )
        assert res.status_code == 200, res.text
        _, rows = await ledger.page_rows(db_session, department=department)
        assert rows[0]["termination_type_label"] == "公司解除"
        assert rows[0]["termination_type_overridden"] is True
        assert rows[0]["separation_process_no"] == "LC-001" and rows[0]["process_no_source"] == "manual"
        assert rows[0]["approval_refs"] == ["审批单 123"]
        assert rows[0]["contract_original_status_label"] == "已回收"

        # 离职页签直接归档：无合同行时先按离职记录建档，再挂扫描件
        res = await client.post(f"{base}/contract-archive", files={"file": ("a.png", PNG, "image/png")})
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["contract"]["status"] == "terminated"
        assert data["contract"]["archive_status"] == "archived"
        assert [v["version_no"] for v in data["versions"]] == [1]
        _, rows = await ledger.page_rows(db_session, department=department)
        assert rows[0]["archive_status_label"] == "已归档"
        assert rows[0]["has_contract_rows"] is True
    finally:
        contract_ids = [
            c.id for c in await repo.list_by_employee(db_session, departure.employee_number)
        ]
        keys = (await db_session.execute(
            select(ContractArchiveVersion.storage_key).where(
                ContractArchiveVersion.contract_id.in_(contract_ids)
            )
        )).scalars().all()
        for key in keys:
            cleanup_object(archive_service.MODULE, key)
        prune_empty_archive_dirs()
