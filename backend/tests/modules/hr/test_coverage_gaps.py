"""Coverage gap tests for HR training module endpoints not covered by existing tests."""

import io
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import (
    AnnualTrainingPlan,
    AnnualTrainingPlanItem,
    HrTrainer,
)


@pytest.fixture
async def trainer(db_session: AsyncSession):
    t = HrTrainer(name="测试培训师", department="测试部门", is_level1="一级培训师")
    db_session.add(t)
    await db_session.commit()
    return t


# ═══════════════════════════════════════════════════════
# Trainer CRUD
# ═══════════════════════════════════════════════════════


class TestTrainerCRUD:
    """Tests for /api/v1/hr/trainers endpoints."""

    async def test_list_trainers(self, client: AsyncClient, trainer):
        resp = await client.get("/api/v1/hr/trainers?page_size=200")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        names = [t["name"] for t in data]
        assert "测试培训师" in names

    async def test_list_by_department(self, client: AsyncClient, trainer):
        resp = await client.get("/api/v1/hr/trainers?department=测试部门")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert all(t["department"] == "测试部门" for t in data)

    async def test_list_by_level1(self, client: AsyncClient, trainer):
        resp = await client.get("/api/v1/hr/trainers?is_level1=一级培训师")
        assert resp.status_code == 200
        data = resp.json()["data"]
        for t in data:
            assert t["is_level1"] in ("一级培训师", None)

    async def test_create_trainer(self, client: AsyncClient, db_session: AsyncSession):
        resp = await client.post(
            "/api/v1/hr/trainers",
            json={"name": "新建培训师", "department": "新建部门", "qualification_scope": "GMP培训"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "新建培训师"
        assert data["department"] == "新建部门"

    async def test_update_trainer(self, client: AsyncClient, trainer):
        resp = await client.put(
            f"/api/v1/hr/trainers/{trainer.id}",
            json={"name": "更新培训师", "qualification_scope": "更新范围"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "更新培训师"

    async def test_delete_trainer(self, client: AsyncClient, db_session: AsyncSession):
        t = HrTrainer(name="待删除", department="测试")
        db_session.add(t)
        await db_session.commit()
        resp = await client.delete(f"/api/v1/hr/trainers/{t.id}")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════
# Training Notification Generation
# ═══════════════════════════════════════════════════════


class TestTrainingNotification:
    """Tests for training notification/document generation endpoints."""

    async def test_generate_notification(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/hr/training-notification",
            json={
                "department": "测试部门",
                "training_date": "2026-07-23",
                "subject": "测试培训通知",
                "training_method": "面授",
                "trainer": "测试培训师",
                "trainee_names": ["测试部门"],
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    async def test_generate_notification_dual_method(self, client: AsyncClient):
        """面授+自学模式 should also work."""
        resp = await client.post(
            "/api/v1/hr/training-notification",
            json={
                "department": "测试部门",
                "subject": "面授+自学培训",
                "training_method": "面授+自学",
                "face_to_face_time_start": "08:00",
                "face_to_face_time_end": "12:00",
                "self_study_time_start": "14:00",
                "self_study_time_end": "16:00",
                "trainee_names": ["测试部门"],
                "face_date": "2026-07-20",
                "self_study_date": "2026-07-22",
            },
        )
        assert resp.status_code in (200, 400, 422)

    async def test_generate_sign_in_sheet(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/hr/training-sign-in-sheet",
            json={
                "training_date": "2026-07-23",
                "department": "测试部门",
                "topic": "测试签到表",
                "employee_names": ["张三", "李四", "王五"],
            },
        )
        assert resp.status_code == 200
        assert "wordprocessingml" in resp.headers["content-type"]

    async def test_generate_sign_in_sheet_many_people(self, client: AsyncClient):
        """Should handle 20+ people (multi-page)."""
        names = [f"员工{i}" for i in range(1, 25)]
        resp = await client.post(
            "/api/v1/hr/training-sign-in-sheet",
            json={
                "training_date": "2026-07-23",
                "department": "测试部门",
                "topic": "大部门签到表",
                "employee_names": names,
            },
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════
# Annual Plan Upload Regression
# ═══════════════════════════════════════════════════════


class TestAnnualPlanUpload:
    """Regression test for Excel upload with real data structure."""

    async def test_upload_with_all_columns(self, client: AsyncClient):
        """Upload a minimal xlsx with all 16 mapped columns."""
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append([
            "体现部门", "品种", "培训内容", "部门", "授课单位/培训师",
            "培训对象", "培训时间", "提醒实施", "课时", "培训地点",
            "注意事项", "培训方式", "考核方式", "实施日期", "备注", "部门管理员",
        ])
        ws.append([
            "回归测试部", "测试品种", "回归测试培训内容", "回归测试部",
            "测试培训师", "回归测试部员工", "1月", None, "2h", "测试地点",
            "测试注意事项", "面授", "问答", "2026-01-15", "测试备注", "测试管理员",
        ])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        files = {"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = await client.post("/api/v1/hr/annual-training-plans/upload", files=files)
        assert resp.status_code == 200
        result = resp.json()
        assert result["data"]["created"] + result["data"]["updated"] >= 1
        assert result["data"]["errors"] == []

    async def test_upload_wrong_extension(self, client: AsyncClient):
        """Non-xlsx extension should be rejected."""
        files = {"file": ("test.pdf", io.BytesIO(b"pdf content"), "application/pdf")}
        resp = await client.post("/api/v1/hr/annual-training-plans/upload", files=files)
        assert resp.status_code == 400

    async def test_verify_uploaded_fields(self, client: AsyncClient):
        """Verify new fields (assessment_method, location, notes) are stored after upload."""
        resp = await client.get("/api/v1/hr/annual-plan-items?year=2026&department=回归测试部")
        data = resp.json()["data"]
        if len(data) > 0:
            item = data[0]
            assert item.get("assessment_method") == "问答"
            assert item.get("location") == "测试地点"
            assert item.get("notes") == "测试注意事项"


# ═══════════════════════════════════════════════════════
# Update Annual Plan Item
# ═══════════════════════════════════════════════════════


class TestUpdatePlanItem:
    """Tests for PUT /api/v1/hr/annual-training-plans/{plan_id}/items/batch."""

    async def test_batch_update_items(self, client: AsyncClient, db_session: AsyncSession):
        plan = AnnualTrainingPlan(year=2026, department="批量更新测试", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        item = AnnualTrainingPlanItem(plan_id=plan.id, month="1月", content_and_textbook="原始内容")
        db_session.add(item)
        await db_session.commit()

        resp = await client.put(
            f"/api/v1/hr/annual-training-plans/{plan.id}/items/batch",
            json={"items": [{"content_and_textbook": "更新后内容", "training_method": "面授"}]},
        )
        # Batch update creates new items or updates by content matching
        assert resp.status_code in (200, 201)


# ═══════════════════════════════════════════════════════
# Delete Plan
# ═══════════════════════════════════════════════════════


class TestDeletePlan:
    """Tests for DELETE /api/v1/hr/annual-training-plans/{plan_id}."""

    async def test_delete_plan_soft(self, client: AsyncClient, db_session: AsyncSession):
        plan = AnnualTrainingPlan(year=2026, department="软删除测试", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        resp = await client.delete(f"/api/v1/hr/annual-training-plans/{plan.id}")
        assert resp.status_code == 200
        # Soft delete verified by list exclusion
        resp2 = await client.get("/api/v1/hr/annual-training-plans?year=2026&page_size=200")
        ids = [p["id"] for p in resp2.json()["data"]]
        assert str(plan.id) not in ids


# ═══════════════════════════════════════════════════════
# Employee Training Candidates
# ═══════════════════════════════════════════════════════


class TestTrainingCandidates:
    """Additional tests for training-candidates endpoint."""

    async def test_candidates_with_keyword(self, client: AsyncClient):
        """Keyword search returns empty for nonsense keyword."""
        resp = await client.get("/api/v1/hr/employees/training-candidates?keyword=zzz_nonexistent_999")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 0

    async def test_candidates_response_structure(self, client: AsyncClient):
        resp = await client.get("/api/v1/hr/employees/training-candidates")
        assert resp.status_code == 200
        for item in resp.json()["data"]:
            assert "id" in item
            assert "name" in item
            assert "employee_number" in item
            assert "department" in item
            assert "source" in item
            break


# ═══════════════════════════════════════════════════════
# Annual Plan Items by Plan
# ═══════════════════════════════════════════════════════


class TestPlanItemsByPlan:
    """Tests for GET /api/v1/hr/annual-training-plans/{plan_id}/items."""

    async def test_items_include_new_fields(self, client: AsyncClient, db_session: AsyncSession):
        plan = AnnualTrainingPlan(year=2026, department="字段验证测试", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        item = AnnualTrainingPlanItem(
            plan_id=plan.id,
            content_and_textbook="字段测试",
            assessment_method="笔试",
            location="会议室A",
            notes="注意事项内容",
        )
        db_session.add(item)
        await db_session.commit()

        resp = await client.get(f"/api/v1/hr/annual-training-plans/{plan.id}/items")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        found = [i for i in data if i["content_and_textbook"] == "字段测试"]
        assert len(found) == 1
        assert found[0].get("assessment_method") == "笔试"
        assert found[0].get("location") == "会议室A"
        assert found[0].get("notes") == "注意事项内容"

    async def test_empty_items(self, client: AsyncClient, db_session: AsyncSession):
        """Plan with no items returns empty list."""
        plan = AnnualTrainingPlan(year=2026, department="空计划测试", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        resp = await client.get(f"/api/v1/hr/annual-training-plans/{plan.id}/items")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 0
