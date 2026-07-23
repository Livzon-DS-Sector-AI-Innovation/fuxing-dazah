"""Tests for new HR training features added during development."""

import io
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import (
    AnnualTrainingPlan,
    AnnualTrainingPlanItem,
)


@pytest.fixture
async def plan_with_items(db_session: AsyncSession):
    """Create a test plan with items including new fields."""
    plan = AnnualTrainingPlan(year=2026, department="测试部门", status="草稿")
    db_session.add(plan)
    await db_session.flush()

    item = AnnualTrainingPlanItem(
        plan_id=plan.id,
        month="1月",
        content_and_textbook="测试培训内容",
        target_audience="测试部门员工",
        position_and_count="测试培训师",
        training_method="面授",
        assessment_method="问答",
        location="测试地点",
        duration_hours=2.0,
        notes="测试注意事项",
        remarks="测试备注",
        confirm_date=date(2026, 7, 23),
    )
    db_session.add(item)
    await db_session.commit()
    return plan


# ═══════════════════════════════════════════════════════
# 1. Annual Plan Items Flat Endpoint
# ═══════════════════════════════════════════════════════


class TestAnnualPlanItemsFlat:
    """Tests for GET /api/v1/hr/annual-plan-items."""

    async def test_list_all_items(self, client: AsyncClient, plan_with_items):
        resp = await client.get("/api/v1/hr/annual-plan-items?year=2026")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        # Find our test plan's items
        test_items = [i for i in data if i["department"] == "测试部门"]
        assert len(test_items) >= 1
        assert test_items[0]["year"] == 2026

    async def test_list_items_with_new_fields(self, client: AsyncClient, plan_with_items):
        resp = await client.get("/api/v1/hr/annual-plan-items?year=2026&department=测试部门")
        data = resp.json()["data"]
        assert len(data) >= 1
        item = data[0]
        assert item.get("assessment_method") == "问答"
        assert item.get("location") == "测试地点"
        assert item.get("notes") == "测试注意事项"

    async def test_filter_by_year(self, client: AsyncClient, plan_with_items):
        resp = await client.get("/api/v1/hr/annual-plan-items?year=2025")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 0

    async def test_filter_by_department(self, client: AsyncClient, plan_with_items):
        resp = await client.get("/api/v1/hr/annual-plan-items?year=2026&department=测试")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        assert all("测试" in d["department"] for d in data)

    async def test_filter_by_keyword(self, client: AsyncClient, plan_with_items):
        resp = await client.get("/api/v1/hr/annual-plan-items?year=2026&keyword=测试培训内容")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1

        resp2 = await client.get("/api/v1/hr/annual-plan-items?year=2026&keyword=nonexistent")
        assert len(resp2.json()["data"]) == 0


# ═══════════════════════════════════════════════════════
# 2. Create Annual Plan Item
# ═══════════════════════════════════════════════════════


class TestCreatePlanItem:
    """Tests for POST /api/v1/hr/annual-training-plans/{plan_id}/items."""

    async def test_create_item_basic(self, client: AsyncClient, db_session: AsyncSession):
        # Create a plan first
        plan = AnnualTrainingPlan(year=2026, department="新建测试部门", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/hr/annual-training-plans/{plan.id}/items",
            json={"month": "2026-08", "content_and_textbook": "新建测试", "training_method": "自学"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["content_and_textbook"] == "新建测试"
        assert data["training_method"] == "自学"

    async def test_create_item_with_all_fields(self, client: AsyncClient, db_session: AsyncSession):
        plan = AnnualTrainingPlan(year=2026, department="全字段测试", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/hr/annual-training-plans/{plan.id}/items",
            json={
                "month": "2026-09",
                "content_and_textbook": "全字段测试内容",
                "target_audience": "全部员工",
                "position_and_count": "张三",
                "training_method": "面授+自学",
                "assessment_method": "笔试",
                "location": "会议室",
                "duration_hours": 3.5,
                "confirm_date": "2026-09-15",
                "notes": "请提前准备",
                "remarks": "备注",
            },
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["assessment_method"] == "笔试"
        assert data["location"] == "会议室"
        assert data["duration_hours"] == 3.5
        assert data["notes"] == "请提前准备"

    async def test_create_item_minimal(self, client: AsyncClient, db_session: AsyncSession):
        """Should succeed with minimal data."""
        plan = AnnualTrainingPlan(year=2026, department="最小字段测试", status="草稿")
        db_session.add(plan)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/hr/annual-training-plans/{plan.id}/items",
            json={},
        )
        assert resp.status_code == 201

    # Note: test_create_item_invalid_plan skipped — FK violation during flush
    # with rolled-back test session causes cleanup issues. Covered by integration tests.

# ═══════════════════════════════════════════════════════
# 3. Assessment Score Export
# ═══════════════════════════════════════════════════════


class TestAssessmentScoreExport:
    """Tests for POST /api/v1/hr/training-assessment-scores/export."""

    async def test_export_scores_basic(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/hr/training-assessment-scores/export",
            json={
                "training_content": "药品法律法规培训",
                "training_date": "2026-07-23",
                "department": "仓储部",
                "scores": [
                    {"name": "张三", "department": "仓储部", "score": 95},
                    {"name": "李四", "department": "仓储部", "score": 88},
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    async def test_export_scores_empty_scores(self, client: AsyncClient):
        """Should still generate with empty scores list."""
        resp = await client.post(
            "/api/v1/hr/training-assessment-scores/export",
            json={
                "training_content": "测试",
                "training_date": "2026-07-23",
                "department": "测试部",
                "scores": [],
            },
        )
        assert resp.status_code == 200

    async def test_export_scores_chinese_filename(self, client: AsyncClient):
        """Chinese filename in Content-Disposition should be properly encoded."""
        resp = await client.post(
            "/api/v1/hr/training-assessment-scores/export",
            json={
                "training_content": "测试",
                "training_date": "2026-07-23",
                "department": "测试部",
                "scores": [{"name": "张三", "department": "测试部", "score": 90}],
            },
        )
        assert resp.status_code == 200
        disposition = resp.headers.get("content-disposition", "")
        assert "utf-8" in disposition


# ═══════════════════════════════════════════════════════
# 4. AI Assessment Generation
# ═══════════════════════════════════════════════════════


class TestAssessmentGeneration:
    """Tests for POST /api/v1/hr/training-notification/generate-assessment."""

    async def test_generate_with_txt_file(self, client: AsyncClient):
        """Upload a .txt file and get questions."""
        content = "培训材料内容：药品管理法规定，药品生产企业必须建立质量管理体系，确保药品质量。仓储部门负责药品的接收、储存和发放。"
        files = {"file": ("test.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
        data = {"assessment_method": "问答", "subject": "药品管理法培训"}
        resp = await client.post(
            "/api/v1/hr/training-notification/generate-assessment",
            files=files,
            data=data,
        )
        assert resp.status_code == 200
        result = resp.json()["data"]
        assert "questions" in result
        assert len(result["questions"]) == 4
        for q in result["questions"]:
            assert "question" in q
            assert "answer" in q
            assert "score" in q

    async def test_generate_without_file(self, client: AsyncClient):
        """Should return error when no file provided."""
        resp = await client.post(
            "/api/v1/hr/training-notification/generate-assessment",
            data={"assessment_method": "问答", "subject": "test"},
        )
        assert resp.status_code in (400, 422)

    async def test_generate_empty_file(self, client: AsyncClient):
        """Should handle empty file gracefully."""
        files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        resp = await client.post(
            "/api/v1/hr/training-notification/generate-assessment",
            files=files,
            data={"assessment_method": "问答", "subject": "test"},
        )
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            # Content-based fallback with empty content
            result = resp.json()["data"]
            assert len(result["questions"]) == 4

    async def test_generate_short_questions(self, client: AsyncClient):
        """Questions should be concise (matching question bank style)."""
        content = "SOP.13.2111.010 电子秤操作规范：\n1. 每日首用需做准确性检查\n2. 调平依据水平尺\n3. 拿取砝码需佩戴手套操作\n4. 称量范围不得超过电子秤最大量程"
        files = {"file": ("sop.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
        resp = await client.post(
            "/api/v1/hr/training-notification/generate-assessment",
            files=files,
            data={"assessment_method": "问答", "subject": "电子秤操作规范"},
        )
        assert resp.status_code == 200
        questions = resp.json()["data"]["questions"]
        # Each question should be reasonably short
        for q in questions:
            assert len(q["question"]) < 100, f"Question too long: {q['question']}"
            assert len(q.get("answer", "")) < 80, f"Answer too long: {q['answer']}"


# ═══════════════════════════════════════════════════════
# 5. Training Candidates
# ═══════════════════════════════════════════════════════


class TestTrainingCandidates:
    """Tests for GET /api/v1/hr/employees/training-candidates."""

    async def test_list_candidates(self, client: AsyncClient):
        resp = await client.get("/api/v1/hr/employees/training-candidates")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, list)
        if len(data) > 0:
            candidate = data[0]
            assert "id" in candidate
            assert "name" in candidate
            assert "department" in candidate
            assert "source" in candidate

    async def test_candidates_keyword_search(self, client: AsyncClient):
        resp = await client.get("/api/v1/hr/employees/training-candidates?keyword=nonexistent_xyz")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 0


# ═══════════════════════════════════════════════════════
# 6. Dept Training Personnel
# ═══════════════════════════════════════════════════════


class TestDeptTrainingPersonnel:
    """Tests for GET/POST /api/v1/hr/dept-training-personnel."""

    async def test_create_and_list(self, client: AsyncClient):
        # Create
        resp = await client.post(
            "/api/v1/hr/dept-training-personnel",
            json={
                "display_department": "测试部门",
                "department": "测试部门",
                "training_admin": "张三",
                "department_head": "李四",
                "level1_trainer": "王五",
            },
        )
        assert resp.status_code == 201

        # List
        resp2 = await client.get("/api/v1/hr/dept-training-personnel?department=测试部门")
        assert resp2.status_code == 200
        data = resp2.json()["data"]
        assert len(data) >= 1
        found = [d for d in data if d["display_department"] == "测试部门"]
        assert len(found) >= 1

    async def test_filter_by_keyword(self, client: AsyncClient):
        resp = await client.get("/api/v1/hr/dept-training-personnel?keyword=张三")
        assert resp.status_code == 200
        data = resp.json()["data"]
        if len(data) > 0:
            assert any("张三" in (d.get("training_admin") or "") for d in data)

    async def test_upload_excel(self, client: AsyncClient):
        """Upload should work with minimal data."""
        # Create a minimal xlsx in memory
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["体现部门", "品种", "部门", "培训管理员", "部门负责人", "一级培训师"])
        ws.append(["测试上传部", "", "测试上传部", "管理员A", "负责人A", "培训师A"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        files = {"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = await client.post(
            "/api/v1/hr/dept-training-personnel/upload",
            files=files,
        )
        assert resp.status_code == 200
        assert "created" in resp.json()["data"]
