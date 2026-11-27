"""SOP 合并登记（一条记录含多份培训文件）测试。

带 files 的登记为合并登记：file_name/file_no 存「；」连接的展示串，
结构化访问（题库匹配等）走 files JSON；历史单文件数据无 files 时回落单列。
"""

import io
import json
import zipfile
from uuid import uuid4

import pytest
from sqlalchemy import text


def _rand() -> str:
    return uuid4().hex[:8]


def _zip_names(content: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return set(zf.namelist())


async def _db_row(db_session, rid: str) -> dict:
    row = (await db_session.execute(
        text("SELECT file_name, file_no, files FROM hr.sop_training_records WHERE id = :rid"),
        {"rid": rid},
    )).fetchone()
    assert row is not None
    return {"file_name": row[0], "file_no": row[1], "files": json.loads(row[2]) if row[2] else None}


class TestMergedCreateAndUpdate:
    @pytest.mark.asyncio
    async def test_create_merged_stores_files_and_joined_display(self, db_session, client):
        fname = f"合并登记{_rand()}"
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026", "method": "T",
            "files": [
                {"file_name": f"{fname}甲", "file_no": f"SOP-M-{_rand()}"},
                {"file_name": f"{fname}乙", "file_no": f"SOP-M-{_rand()}"},
            ],
            "involved_departments": ["甲部门"], "initiator_department": "甲部门",
        })
        assert res.status_code == 201, res.text
        rid = res.json()["data"]["id"]
        row = await _db_row(db_session, rid)
        assert "；".join([f"{fname}甲", f"{fname}乙"]) == row["file_name"]
        assert row["file_no"] and "；" in row["file_no"]
        assert len(row["files"]) == 2
        # 列表接口返回结构化 files
        listing = await client.get("/api/v1/hr/sop-training-records", params={"keyword": fname})
        rec = next(r for r in listing.json()["data"] if r["id"] == rid)
        assert len(rec["files"]) == 2
        assert rec["file_name"] == row["file_name"]

    @pytest.mark.asyncio
    async def test_create_rejects_oversized_joined_name(self, client):
        long_name = "长" * 200
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026",
            "files": [{"file_name": long_name, "file_no": None} for _ in range(4)],
        })
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_update_with_files_rejoins_display(self, db_session, client):
        fname = f"改合并{_rand()}"
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026", "file_name": fname,
        })
        assert res.status_code == 201, res.text
        rid = res.json()["data"]["id"]

        res2 = await client.put(f"/api/v1/hr/sop-training-records/{rid}", json={
            "files": [
                {"file_name": f"{fname}一", "file_no": "SOP-U-1"},
                {"file_name": f"{fname}二", "file_no": None},
            ],
        })
        assert res2.status_code == 200, res2.text
        row = await _db_row(db_session, rid)
        assert row["file_name"] == f"{fname}一；{fname}二"
        assert row["file_no"] == "SOP-U-1"
        assert len(row["files"]) == 2

        # 空 files 不清历史
        res3 = await client.put(f"/api/v1/hr/sop-training-records/{rid}", json={"files": []})
        assert res3.status_code == 200, res3.text
        row = await _db_row(db_session, rid)
        assert row["files"] is not None and len(row["files"]) == 2

    @pytest.mark.asyncio
    async def test_empty_rows_dropped(self, db_session, client):
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026",
            "files": [{"file_name": "有名字", "file_no": None}, {"file_name": "", "file_no": "SOP-X"}],
        })
        assert res.status_code == 201, res.text
        rid = res.json()["data"]["id"]
        row = await _db_row(db_session, rid)
        assert len(row["files"]) == 1
        assert row["file_name"] == "有名字"


class TestMergedMaterials:
    @pytest.mark.asyncio
    async def test_written_exam_matches_second_file_question(self, db_session, client):
        """合并登记的题库匹配走 files JSON：只有第二份文件配题也能出卷。"""
        from app.modules.hr.models import QuestionBank, SopTrainingRecord

        no1, no2 = f"SOP-ME-{_rand()}", f"SOP-ME-{_rand()}"
        db_session.add(QuestionBank(
            file_no=no2, question=f"{no2} 的责任部门是谁？", answer="见第 3 章", score=10, source="手工录入",
        ))
        rec = SopTrainingRecord(
            year="2026", file_name=f"合并卷{_rand()}甲；合并卷{_rand()}乙",
            file_no=f"{no1}；{no2}", method="T", assessment_method="笔试",
            files=json.dumps([
                {"file_name": f"合并卷{_rand()}甲", "file_no": no1},
                {"file_name": f"合并卷{_rand()}乙", "file_no": no2},
            ]),
            involved_departments=json.dumps(["甲部门"]), status="已提交",
            initiator_department="甲部门",
        )
        db_session.add(rec)
        await db_session.flush()

        res = await client.post(f"/api/v1/hr/sop-training-records/{rec.id}/materials")
        assert res.status_code == 200, res.text
        assert "培训试卷.docx" in _zip_names(res.content)

    @pytest.mark.asyncio
    async def test_batch_materials_reads_merged_files(self, db_session, client):
        from app.modules.hr.models import SopTrainingEntry, SopTrainingRecord

        no1, no2 = f"SOP-MB-{_rand()}", f"SOP-MB-{_rand()}"
        rec = SopTrainingRecord(
            year="2026", file_name=f"批量合并{_rand()}甲；批量合并{_rand()}乙",
            file_no=f"{no1}；{no2}", method="R", assessment_method="问答",
            files=json.dumps([
                {"file_name": f"批量合并{_rand()}甲", "file_no": no1},
                {"file_name": f"批量合并{_rand()}乙", "file_no": no2},
            ]),
            involved_departments=json.dumps(["甲部门"]), status="已提交",
            initiator_department="甲部门",
        )
        db_session.add(rec)
        await db_session.flush()
        entry = SopTrainingEntry(
            record_id=str(rec.id), department="甲部门",
            personnel=json.dumps([{"name": "张三", "employee_number": f"T{_rand()}"}]),
        )
        db_session.add(entry)
        await db_session.flush()

        res = await client.post(
            "/api/v1/hr/sop-training-entries/batch-materials",
            json={"ids": [str(entry.id)]},
        )
        assert res.status_code == 200, res.text
        assert "问答实操记录表.docx" in _zip_names(res.content)
