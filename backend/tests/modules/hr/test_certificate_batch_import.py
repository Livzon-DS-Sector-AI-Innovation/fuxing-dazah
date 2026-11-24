"""证件批量导入：ZIP 预检（文件名解析+员工匹配）+ 确认提交（版本化归档）。

匹配走两条路：文件名里的纯数字段精确命中工号 > 纯中文姓名唯一命中。
姓名要求 2~4 个纯汉字，故员工名用「前缀+中文数字后缀」构造（每轮运行唯一）；
结束后软删员工，避免脏名影响后续轮次的姓名匹配。
"""

import io
import zipfile
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, update

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

_CN_DIGITS = "零壹贰叁肆伍陆柒捌玖金木水火土日"


def _cn_tag(n: int = 3) -> str:
    """中文数字后缀：保证测试员工名（2~4 纯汉字）每轮唯一。"""
    h = uuid4().hex
    return "".join(_CN_DIGITS[int(h[i], 16) % len(_CN_DIGITS)] for i in range(n))


def _digit_number() -> str:
    """纯数字工号：供文件名数字段精确匹配路径使用。"""
    return str(100000 + uuid4().int % 899999)


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _commit_row(row: dict, **overrides) -> dict:
    """precheck 行 → commit 行（补选员工/改类别走 overrides）。"""
    payload = {
        "storage_key": row["storage_key"],
        "filename": row["filename"],
        "employee_id": (row["employee"] or {}).get("id") if row["employee"] else None,
        "category": row["category"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_batch_import_parse_filename():
    """文件名解析：姓名/类别关键词/默认「其他」。"""
    from app.modules.hr.certificate_batch_import import parse_certificate_filename as parse

    assert parse("张三_身份证.png")["category"] == "id_card"
    assert parse("张三_身份证.png")["name"] == "张三"
    assert parse("李四-特种作业操作证.pdf")["category"] == "special_operation"
    assert parse("王五健康证.png")["name"] == "王五"
    assert parse("子文件夹/赵六_毕业证书.jpeg")["category"] == "graduation"
    other = parse("IMG_20240101_123456.jpg")
    assert other["category"] == "other" and other["category_matched"] is False
    assert other["name"] is None


@pytest.mark.asyncio
async def test_batch_import_precheck_and_commit(db_session, client):
    """预检：自动匹配/未匹配/非法文件分类正确；提交：确认行归档+补选员工生效。"""
    from app.modules.hr.models import Employee, EmployeeCertificate

    name_a, name_b = f"批{_cn_tag()}", f"证{_cn_tag()}"
    number_a = _digit_number()
    emp_a = Employee(
        employee_number=number_a, name=name_a, department="人力资源部",
        position="专员", status="在职", hire_date=date.today(),
    )
    emp_b = Employee(
        employee_number=_digit_number(), name=name_b, department="人力资源部",
        position="专员", status="在职", hire_date=date.today(),
    )
    db_session.add_all([emp_a, emp_b])
    await db_session.flush()

    zip_bytes = _make_zip({
        # 甲走工号精确匹配路径（文件名带工号数字段）
        f"{name_a}_{number_a}_身份证.png": PNG,
        # 乙走姓名唯一匹配路径
        f"{name_b}_健康证.png": PNG,
        "无名文件IMG999.png": PNG,
        "说明文档.txt": b"not an image",
    })
    try:
        res = await client.post(
            "/api/v1/hr/certificates/batch-import/precheck",
            files={"file": ("证件.zip", zip_bytes, "application/zip")},
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        by_name = {r["filename"]: r for r in data["rows"]}

        row_a = by_name[f"{name_a}_{number_a}_身份证.png"]
        assert row_a["status"] == "ok"
        assert row_a["employee"]["id"] == str(emp_a.id)
        assert row_a["category"] == "id_card"
        assert row_a["storage_key"].startswith("certificates/_batch/")

        row_b = by_name[f"{name_b}_健康证.png"]
        assert row_b["status"] == "ok" and row_b["employee"]["id"] == str(emp_b.id)

        row_unknown = by_name["无名文件IMG999.png"]
        assert row_unknown["status"] == "unmatched" and row_unknown["employee"] is None

        row_txt = by_name["说明文档.txt"]
        assert row_txt["status"] == "invalid" and row_txt["storage_key"] is None

        assert data["summary"] == {
            "total": 4, "ok": 2, "unmatched": 1, "ambiguous": 0, "invalid": 1, "replaces": 0,
        }

        # 提交：自动匹配两行 + 未匹配行人工补选 emp_a（类别改「其他」）
        rows = [
            _commit_row(row_a),
            _commit_row(row_b),
            _commit_row(row_unknown, employee_id=str(emp_a.id), category="other"),
        ]
        res = await client.post(
            "/api/v1/hr/certificates/batch-import/commit", json={"rows": rows},
        )
        assert res.status_code == 200, res.text
        result = res.json()["data"]
        assert result["summary"] == {"imported": 3, "failed": 0}
        assert all(r["ok"] for r in result["results"])

        certs = (await db_session.execute(
            select(EmployeeCertificate).where(
                EmployeeCertificate.employee_id.in_([emp_a.id, emp_b.id]),
                EmployeeCertificate.is_current.is_(True),
                EmployeeCertificate.is_deleted.is_(False),
            )
        )).scalars().all()
        got = {(c.employee_id, c.category): c for c in certs}
        assert got[(emp_a.id, "id_card")].version_no == 1
        assert got[(emp_b.id, "health")].version_no == 1
        assert got[(emp_a.id, "other")].version_no == 1
    finally:
        await db_session.execute(
            update(Employee).where(Employee.id.in_([emp_a.id, emp_b.id])).values(is_deleted=True)
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_batch_import_ambiguous_and_duplicate_rejected(db_session, client):
    """重名 → ambiguous 待人工选人；同批同「员工×类别」重复 → 提交拒绝后者。"""
    from app.modules.hr.models import Employee

    same_name = f"重{_cn_tag()}"
    single_name = f"单{_cn_tag()}"
    emp1 = Employee(
        employee_number=_digit_number(), name=same_name, department="人力资源部",
        position="专员", status="在职", hire_date=date.today(),
    )
    emp2 = Employee(
        employee_number=_digit_number(), name=same_name, department="人力资源部",
        position="专员", status="在职", hire_date=date.today(),
    )
    emp3 = Employee(
        employee_number=_digit_number(), name=single_name, department="人力资源部",
        position="专员", status="在职", hire_date=date.today(),
    )
    db_session.add_all([emp1, emp2, emp3])
    await db_session.flush()

    zip_bytes = _make_zip({
        f"{same_name}_身份证.png": PNG,
        f"{single_name}_身份证.png": PNG,
        f"{single_name}_身份证_背面.png": PNG,
    })
    try:
        res = await client.post(
            "/api/v1/hr/certificates/batch-import/precheck",
            files={"file": ("证件.zip", zip_bytes, "application/zip")},
        )
        assert res.status_code == 200, res.text
        by_name = {r["filename"]: r for r in res.json()["data"]["rows"]}

        dup_row = by_name[f"{same_name}_身份证.png"]
        assert dup_row["status"] == "ambiguous"
        assert {c["id"] for c in dup_row["candidates"]} == {str(emp1.id), str(emp2.id)}

        single = by_name[f"{single_name}_身份证.png"]
        assert single["status"] == "ok" and not single["dup_in_batch"]
        back = by_name[f"{single_name}_身份证_背面.png"]
        assert back["status"] == "ok" and back["dup_in_batch"] is True, "同批同员工同类别的第二个文件应标重"

        res = await client.post(
            "/api/v1/hr/certificates/batch-import/commit",
            json={"rows": [_commit_row(single), _commit_row(back)]},
        )
        assert res.status_code == 200, res.text
        result = res.json()["data"]
        assert result["summary"] == {"imported": 1, "failed": 1}
        assert result["results"][0]["ok"] is True
        assert "同员工同类别" in result["results"][1]["error"]
    finally:
        await db_session.execute(
            update(Employee).where(Employee.id.in_([emp1.id, emp2.id, emp3.id])).values(is_deleted=True)
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_batch_import_replaces_and_employee_options(db_session, client):
    """已有同类别当前版本 → 预检标 replaces；补选搜索接口按姓名/工号匹配。"""
    from app.modules.hr.models import Employee

    name = f"换{_cn_tag()}"
    number = _digit_number()
    emp = Employee(
        employee_number=number, name=name, department="人力资源部",
        position="专员", status="在职", hire_date=date.today(),
    )
    db_session.add_all([emp])
    await db_session.flush()

    zip_bytes = _make_zip({f"{name}_健康证.png": PNG})
    try:
        res = await client.post(
            "/api/v1/hr/certificates/batch-import/precheck",
            files={"file": ("证件.zip", zip_bytes, "application/zip")},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["summary"]["replaces"] == 0
        row = res.json()["data"]["rows"][0]

        # 首次提交后，同类别再预检应有 v1 的 replaces 提示（升版本换证）
        res = await client.post(
            "/api/v1/hr/certificates/batch-import/commit",
            json={"rows": [_commit_row(row)]},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["summary"]["imported"] == 1

        res2 = await client.post(
            "/api/v1/hr/certificates/batch-import/precheck",
            files={"file": ("证件.zip", zip_bytes, "application/zip")},
        )
        assert res2.status_code == 200, res2.text
        row2 = res2.json()["data"]["rows"][0]
        assert row2["replaces"] is not None
        assert row2["replaces"]["version_no"] == 1

        # 补选搜索：工号/姓名关键字都能命中
        for kw in (number, name):
            res3 = await client.get(
                f"/api/v1/hr/certificates/batch-import/employee-options?keyword={kw}"
            )
            assert res3.status_code == 200, res3.text
            options = res3.json()["data"]
            assert len(options) == 1 and options[0]["id"] == str(emp.id), f"keyword={kw}"
    finally:
        await db_session.execute(
            update(Employee).where(Employee.id == emp.id).values(is_deleted=True)
        )
        await db_session.commit()
