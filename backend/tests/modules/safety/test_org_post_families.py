"""#4 岗位 AI 归一：插件解析 + 批量归类 upsert + 确认/修正 + 族聚合测试。

接缝：org_client 替身（list_org_users 返回固定主档）与 ai_service 替身
（chat_parsed 假返回）构造注入；PG 走 db_session（dev 库），测试行用
「ZZ-P-」前缀岗位名隔离并显式清行（服务内 commit，回滚不生效）。
规格：docs/DESIGN-3x平台关联-…-20261026.md §13。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import delete

from app.modules.safety.ai_org_post_classify import (
    OrgPostClassifyError,
    OrgPostClassifyPlugin,
)
from app.modules.safety.models.org_post_families import OrgPostFamily
from app.modules.safety.service import org_post_families as svc

_PREFIX = "ZZ-P-"


class _FakeOrgClient:
    def __init__(self, posts: list[str]):
        self._users = [{"postName": p, "deptName": "测试部"} for p in posts]

    async def list_org_users(self) -> list[dict[str, Any]]:
        return self._users


class _FakeAI:
    def __init__(self, mapping: dict[str, dict[str, Any]]):
        self._mapping = mapping

    async def chat_parsed(self, messages, expected_keys, temperature=0.1):
        assert expected_keys == ["items"]
        items = [
            {"post_name": k, "family": v["family"], "confidence": v.get("confidence", "high"),
             "note": v.get("note", "")}
            for k, v in self._mapping.items()
        ]
        return {"items": items}


async def _cleanup(db) -> None:
    await db.execute(
        delete(OrgPostFamily).where(
            OrgPostFamily.post_name.like(f"{_PREFIX}%")
        )
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _isolation(db_session):
    await _cleanup(db_session)
    yield
    await _cleanup(db_session)


def _posts() -> list[str]:
    return [
        f"{_PREFIX}冻干出料操作工",
        f"{_PREFIX}QC化验员",
        f"{_PREFIX}机修电工",
        f"{_PREFIX}仓库管理员",
    ]


def _ai_map() -> dict[str, dict[str, Any]]:
    return {
        f"{_PREFIX}冻干出料操作工": {"family": "危化工艺操作", "confidence": "high",
                              "note": "冻干出料为工艺操作"},
        f"{_PREFIX}QC化验员": {"family": "质检与实验", "confidence": "high",
                        "note": "QC 化验"},
        f"{_PREFIX}机修电工": {"family": "特种作业相关", "confidence": "medium",
                        "note": "电工持特种证"},
        f"{_PREFIX}仓库管理员": {"family": "物流仓储", "confidence": "high",
                         "note": "仓库"},
    }


# ═══════════════════════════ 插件解析 ═══════════════════════════


class TestPluginParse:
    async def test_parse_drops_invalid_family_and_hallucination(self):
        plugin = OrgPostClassifyPlugin(_FakeAI({
            "冻干工": {"family": "危化工艺操作", "confidence": "high"},
            "不存在岗": {"family": "管理职能", "confidence": "high"},
            "神秘岗": {"family": "不存在的族", "confidence": "high"},
            "另岗": {"family": "其他", "confidence": "medium"},
        }))
        out = await plugin.classify(["冻干工", "神秘岗", "另岗"])
        assert [(i.post_name, i.family, i.confidence) for i in out] == [
            ("冻干工", "危化工艺操作", "high"),
            ("另岗", "其他", "mid"),  # medium 归一 mid；越界族行丢弃
        ]

    async def test_ai_failure_raises(self):
        class _Boom:
            async def chat_parsed(self, **kw):
                raise RuntimeError("down")

        with pytest.raises(OrgPostClassifyError):
            await OrgPostClassifyPlugin(_Boom()).classify(["x"])


# ═══════════════════════════ 批量归类与 manual 保护 ═══════════════════════════


class TestRunClassify:
    async def test_classify_inserts_and_rerun_overwrites_ai_only(self, db_session):
        result = await svc.run_classify(
            db_session,
            org_client=_FakeOrgClient(_posts()),
            ai_service=_FakeAI(_ai_map()),
        )
        assert result["posts_total"] == 4
        assert result["classified"] == 4
        assert result["inserted"] == 4
        rows = {r["post_name"]: r for r in await svc.list_families(db_session)}
        assert rows[f"{_PREFIX}机修电工"]["family"] == "特种作业相关"
        assert rows[f"{_PREFIX}QC化验员"]["confidence"] == "high"

        # 人工修正一条 → manual；重跑（AI 给出不同族）不覆盖 manual，覆盖其余 ai
        target = f"{_PREFIX}机修电工"
        row_id = rows[target]["id"]
        await svc.update_family(db_session, row_id, family="设备维护", note="人工改定")

        new_map = dict(_ai_map())
        new_map[target] = {"family": "物流仓储", "confidence": "high", "note": "AI 新判"}
        new_map[f"{_PREFIX}冻干出料操作工"] = {
            "family": "一般生产操作", "confidence": "mid", "note": "AI 改判",
        }
        result2 = await svc.run_classify(
            db_session,
            org_client=_FakeOrgClient(_posts()),
            ai_service=_FakeAI(new_map),
        )
        # manual_kept 统计全表（含真实验收行），只断言本用例行不被覆盖
        assert result2["manual_kept"] >= 1
        all_rows = await svc.list_families(db_session)
        rows2 = {
            r["post_name"]: r for r in all_rows
            if r["post_name"].startswith(_PREFIX)
        }
        assert rows2[target]["family"] == "设备维护"      # manual 不被覆盖
        assert rows2[target]["source"] == "manual"
        assert rows2[f"{_PREFIX}冻干出料操作工"]["family"] == "一般生产操作"  # ai 覆盖
        assert result2["updated"] == 3  # 其余三条 ai 行 upsert

    async def test_classify_skips_ai_unreturned_new_post(self, db_session):
        # AI 只返回一半：未返回的新岗位不落行
        partial = {k: v for k, v in _ai_map().items() if "QC" not in k}
        result = await svc.run_classify(
            db_session,
            org_client=_FakeOrgClient(_posts()),
            ai_service=_FakeAI(partial),
        )
        assert result["classified"] == 3
        names = {r["post_name"] for r in await svc.list_families(db_session)}
        assert f"{_PREFIX}QC化验员" not in names


# ═══════════════════════════ 确认与修正 ═══════════════════════════


class TestConfirmAndFix:
    async def _seed(self, db) -> str:
        await svc.run_classify(
            db,
            org_client=_FakeOrgClient(_posts()),
            ai_service=_FakeAI(_ai_map()),
        )
        rows = {r["post_name"]: r for r in await svc.list_families(db)}
        return rows[f"{_PREFIX}QC化验员"]["id"]

    async def test_confirm_ai_to_manual(self, db_session):
        row_id = await self._seed(db_session)
        data = await svc.confirm_family(db_session, row_id)
        assert data["source"] == "manual"
        assert data["family"] == "质检与实验"
        with pytest.raises(svc.FamilyStateError):
            await svc.confirm_family(db_session, row_id)  # 重复确认拒绝

    async def test_update_validates_family_enum(self, db_session):
        row_id = await self._seed(db_session)
        with pytest.raises(svc.FamilyStateError):
            await svc.update_family(db_session, row_id, family="不存在族")
        data = await svc.update_family(db_session, row_id, family="管理职能")
        assert (data["family"], data["source"]) == ("管理职能", "manual")


# ═══════════════════════════ 族聚合 ═══════════════════════════


class TestAggregation:
    async def test_aggregation_counts_and_unclassified(self, db_session):
        await svc.run_classify(
            db_session,
            org_client=_FakeOrgClient(_posts() + [f"{_PREFIX}新岗"]),
            ai_service=_FakeAI(_ai_map()),  # 新岗 AI 未返回 → 未归类
        )
        family_map = await svc.family_map_for_posts(db_session)
        posts = [
            {"post_name": p, "headcount": 1} for p in _posts() + [f"{_PREFIX}新岗"]
        ]
        agg = svc.build_family_aggregation(posts, family_map)
        by_family = {row["family"]: row["headcount"] for row in agg}
        assert by_family["危化工艺操作"] == 1
        assert by_family["未归类"] == 1
        assert sum(by_family.values()) == 5
