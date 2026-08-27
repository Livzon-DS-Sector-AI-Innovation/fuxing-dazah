"""绩效多评分人：项目负责人评分权限隔离 + 部门加权总分。"""

import uuid
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import MonthlyPerformanceEvaluation, PerformanceCategory


def _rand() -> str:
    return uuid.uuid4().hex[:8].upper()


# 无 hr:performance:manage 的普通 HR 权限（仅够过路由门禁），用于验证负责人隔离
_LIMITED_PERMS = {"hr:profile:read", "hr:recruitment:read", "hr:training:read"}


async def _no_manage_perms(user_id: str, db: object) -> set[str]:
    return _LIMITED_PERMS


def _payload(ev_id, category_id, score, weight) -> dict:
    return {
        "scores": [{
            "evaluation_id": str(ev_id),
            "category_id": str(category_id),
            "score": score,
            "weight": weight,
        }]
    }


class TestPerformanceScoring:
    async def _mk(self, db_session: AsyncSession):
        cat_a = PerformanceCategory(name=f"环保{_rand()}", weight=40, evaluator="张三")
        cat_b = PerformanceCategory(name=f"安全{_rand()}", weight=60, evaluator="李四")
        db_session.add_all([cat_a, cat_b])
        await db_session.flush()
        ev = MonthlyPerformanceEvaluation(
            department="测试部门", department_head="王五", evaluation_month="2026-08"
        )
        db_session.add(ev)
        await db_session.flush()
        return cat_a, cat_b, ev

    async def _final_score(self, db_session: AsyncSession, ev_id) -> float | None:
        row = (await db_session.execute(
            select(MonthlyPerformanceEvaluation).where(
                MonthlyPerformanceEvaluation.id == ev_id
            )
        )).scalar_one()
        return row.final_score

    async def test_evaluator_isolation_and_weighted_total(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """负责人只能评自己的项目；保存后自动重算部门加权总分。"""
        cat_a, cat_b, ev = await self._mk(db_session)

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_no_manage_perms
        ):
            # HR测试员不是任何项目的负责人 → 403，并提示负责人姓名
            r = await client.post(
                f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores",
                json=_payload(ev.id, cat_a.id, 90, 40),
            )
            assert r.status_code == 403
            assert "张三" in r.json()["message"]

            # 改由 HR测试员 负责环保项目 → 评分成功
            cat_a.evaluator = "HR测试员"
            await db_session.flush()
            r = await client.post(
                f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores",
                json=_payload(ev.id, cat_a.id, 90, 40),
            )
            assert r.status_code == 200, r.text

            # 总分 = 40×90/40 = 90
            assert await self._final_score(db_session, ev.id) == 90.0

            # 李四负责的项目仍 403
            r = await client.post(
                f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores",
                json=_payload(ev.id, cat_b.id, 80, 60),
            )
            assert r.status_code == 403

    async def test_weighted_total_multi_project(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """两个项目均已评分时按该部门权重加权平均。"""
        cat_a, cat_b, ev = await self._mk(db_session)
        cat_a.evaluator = "HR测试员"
        cat_b.evaluator = "HR测试员"
        await db_session.flush()
        r = await client.post(
            f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores",
            json={
                "scores": [
                    {"evaluation_id": str(ev.id), "category_id": str(cat_a.id),
                     "score": 90, "weight": 40},
                    {"evaluation_id": str(ev.id), "category_id": str(cat_b.id),
                     "score": 80, "weight": 60},
                ]
            },
        )
        assert r.status_code == 200, r.text
        # (40×90 + 60×80) / 100 = 84
        assert await self._final_score(db_session, ev.id) == 84.0

    async def test_partial_scores_weighted_by_scored_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """部分项目未评分时，总分只按已评项目的权重归一。"""
        cat_a, cat_b, ev = await self._mk(db_session)
        cat_a.evaluator = "HR测试员"
        cat_b.evaluator = "HR测试员"
        await db_session.flush()
        r = await client.post(
            f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores",
            json=_payload(ev.id, cat_a.id, 90, 40),
        )
        assert r.status_code == 200, r.text
        # 仅环保项目已评：40×90/40 = 90（安全项目权重不参与）
        assert await self._final_score(db_session, ev.id) == 90.0

    async def test_matrix_can_edit_by_evaluator(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """评分矩阵每行带 can_edit：仅自己负责的项目可编辑。"""
        cat_a, cat_b, ev = await self._mk(db_session)
        cat_a.evaluator = "HR测试员"
        await db_session.flush()
        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_no_manage_perms
        ):
            r = await client.get(
                f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores"
            )
        assert r.status_code == 200
        rows = {row["category_id"]: row for row in r.json()["data"]}
        assert rows[str(cat_a.id)]["can_edit"] is True
        assert rows[str(cat_b.id)]["can_edit"] is False
        assert rows[str(cat_b.id)]["evaluator"] == "李四"

    async def test_report_export_per_project_sheet(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """汇总报表：xlsx 下载，按项目一张表。"""
        cat_a, cat_b, ev = await self._mk(db_session)
        cat_a.evaluator = "HR测试员"
        await db_session.flush()
        await client.post(
            f"/api/v1/hr/performance-evaluations/{ev.id}/category-scores",
            json=_payload(ev.id, cat_a.id, 90, 40),
        )
        r = await client.get("/api/v1/hr/performance-reports?month=2026-08")
        assert r.status_code == 200, r.text
        assert "spreadsheetml" in r.headers["content-type"]
        assert len(r.content) > 500  # 非空 xlsx

    async def test_report_404_for_empty_month(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """无考核数据的月份返回 404 提示。"""
        r = await client.get("/api/v1/hr/performance-reports?month=1999-01")
        assert r.status_code == 404
