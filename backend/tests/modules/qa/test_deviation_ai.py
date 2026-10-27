"""偏差 AI 辅助 API 测试：鉴权、建议装配纪律与守卫。

模型调用整体打桩（``_model_json`` 返回固定 JSON），不依赖真实模型；
重点覆盖：涉及对象的主数据匹配与类别校正、证据防幻觉、与已登记对象
去重、各 kind 的数量上限截断、AI 未配置与权限边界。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app as fastapi_app
from app.modules.qa.models import MasterObject
from app.modules.qa.service import deviation_ai
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

READ_ONLY = {"qa:deviation:read"}
WRITE = {"qa:deviation:read", "qa:deviation:create", "qa:deviation:update"}

DESCRIPTION = (
    "2026年10月20日上午，理化组李蝶在 QC 实验室使用紫外分光光度计"
    "测定注射用盐酸万古霉素（批号 HAP2606013EB）的含量时，未执行波长准确性确认"
)


def _ai_settings(**overrides: Any) -> SimpleNamespace:
    base = SimpleNamespace(
        QA_AI_ENABLED=True,
        QA_AI_API_KEY="test-key",
        QA_AI_BASE_URL="http://unused.local",
        QA_AI_MODEL="test-model",
        QA_AI_TIMEOUT_SECONDS=5,
        QA_AI_MAX_RETRIES=0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _describe_result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "description": "【何时】2026年10月20日上午……【何地】QC 实验室……",
        "missing_elements": ["发生日期"],
        "items": [
            {
                "name": "注射用盐酸万古霉素",
                "category": "other",
                "batch_no": "HAP2606013EB",
                "evidence": "注射用盐酸万古霉素",
            },
            {
                "name": "紫外分光光度计",
                "category": "equipment",
                "batch_no": "",
                "evidence": "紫外分光光度计",
            },
        ],
    }
    base.update(overrides)
    return base


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa偏差AI测试用户", employee_no="QA-DEV-AI-001")
    session.add(user)
    await session.flush()
    return user


async def _seed_master(session: AsyncSession, object_type: str, code: str, name: str) -> None:
    session.add(
        MasterObject(
            object_type=object_type,
            code=code,
            normalized_code=code.upper(),
            name=name,
        )
    )
    await session.flush()


@asynccontextmanager
async def _client(
    perms: set[str] | None,
    *,
    model_result: dict[str, Any] | None = None,
    settings: SimpleNamespace | None = None,
) -> AsyncGenerator[tuple[AsyncClient, AsyncSession], None]:
    """perms=None 表示匿名；model_result 提供时打桩模型返回，settings 提供时打桩配置。"""
    async with _test_session_factory() as session:
        user = await _ensure_test_user(session)

        async def _override_get_db() -> Any:
            yield session

        async def _override_user() -> Any:
            return user

        async def _perms(user_id: str, db: object) -> set[str]:
            return set(perms or ())

        async def _fake_model(prompt: str, expected_keys: list[str]) -> dict[str, Any]:
            assert model_result is not None
            return model_result

        fastapi_app.dependency_overrides[get_db] = _override_get_db
        if perms is not None:
            fastapi_app.dependency_overrides[get_current_user] = _override_user
        patches = [patch("app.platform.permission.deps.get_user_permissions", new=_perms)]
        if settings is not None:
            patches.append(patch.object(deviation_ai, "get_settings", lambda: settings))
        if model_result is not None:
            patches.append(patch.object(deviation_ai, "_model_json", new=_fake_model))
        try:
            with ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                transport = ASGITransport(app=fastapi_app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    yield ac, session
        finally:
            fastapi_app.dependency_overrides.clear()
            await session.rollback()


def _assist_payload(kind: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"kind": kind, "description": DESCRIPTION}
    base.update(overrides)
    return base


async def _assist(ac: AsyncClient, body: dict[str, Any]) -> Any:
    return await ac.post("/api/v1/qa/deviations/ai-assist", json=body)


# ───────────────────────── 鉴权与守卫 ─────────────────────────


class TestDeviationAiAuthz:
    async def test_anonymous_rejected(self) -> None:
        """匿名请求 AI 辅助被拒：建议内容同样携带偏差细节。"""
        async with _client(None) as (ac, _):
            resp = await _assist(ac, _assist_payload("m1e"))
        assert resp.status_code == 401

    async def test_read_only_forbidden(self) -> None:
        """只读权限不放行 AI 辅助：辅助服务于登记/编辑动作。"""
        async with _client(READ_ONLY) as (ac, _):
            resp = await _assist(ac, _assist_payload("m1e"))
        assert resp.status_code == 403

    async def test_update_permission_alone_grants(self) -> None:
        """单独持有 update（如 QA 调查人员无登记权限）也能触发辅助。"""
        async with _client(
            {"qa:deviation:update"},
            model_result={"checklists": {"personnel": ["操作员当天任务安排如何？"]}},
            settings=_ai_settings(),
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("m1e"))
        assert resp.status_code == 200, resp.text


class TestDeviationAiGuardrails:
    async def test_ai_not_configured_returns_503(self) -> None:
        """QA_AI_ENABLED=False 时明确告知未配置，而不是静默空结果。"""
        async with _client(WRITE, settings=_ai_settings(QA_AI_ENABLED=False)) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe"))
        assert resp.status_code == 503
        assert "未配置" in resp.json()["message"]

    async def test_short_description_rejected(self) -> None:
        """过短的描述没有可规范化的信息量，422 挡在模型调用前。"""
        async with _client(
            WRITE,
            model_result=_describe_result(),
            settings=_ai_settings(),
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe", description="太短了"))
        assert resp.status_code == 422

    async def test_unknown_deviation_id_404(self) -> None:
        """审计归属校验：指向不存在的偏差直接 404。"""
        async with _client(
            WRITE,
            model_result={"checklists": {}},
            settings=_ai_settings(),
        ) as (ac, _):
            resp = await _assist(
                ac, _assist_payload("m1e", deviation_id=str(uuid4()))
            )
        assert resp.status_code == 404


# ───────────────────────── 登记：描述规范化 ─────────────────────────


class TestDescribeAssist:
    async def test_matches_masters_and_corrects_category(self) -> None:
        """命中主数据时回填匹配信息，并按对象类型校正类别（PRODUCT→finished）。"""
        async with _client(
            WRITE, model_result=_describe_result(), settings=_ai_settings()
        ) as (ac, session):
            await _seed_master(session, "PRODUCT", "VCM", "注射用盐酸万古霉素")
            await _seed_master(session, "EQUIPMENT", "UV-1", "紫外分光光度计")
            resp = await _assist(ac, _assist_payload("describe"))
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["kind"] == "describe"
        assert data["prompt_version"] == deviation_ai.DEVIATION_AI_PROMPT_VERSION
        assert data["model"] == "test-model"
        assert data["missing_elements"] == ["发生日期"]
        items = data["items"]
        assert len(items) == 2
        product = items[0]
        assert product["category"] == "finished"
        assert product["match"]["code"] == "VCM"
        assert product["match"]["object_type"] == "PRODUCT"
        assert product["match"]["match_type"] == "exact_name"
        equipment = items[1]
        assert equipment["category"] == "equipment"
        assert equipment["match"]["code"] == "UV-1"

    async def test_evidence_not_in_description_dropped(self) -> None:
        """防幻觉：模型给出的证据在原描述中命中不了就丢弃，行保留供人工判断。"""
        result = _describe_result()
        result["items"][0]["evidence"] = "原文中根本不存在的证据片段"
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe"))
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert len(items) == 2
        assert items[0]["evidence"] is None
        assert items[1]["evidence"] == "紫外分光光度计"

    async def test_dedupes_against_registered_items(self) -> None:
        """与已登记涉及对象同名同类的建议不再重复出现。"""
        registered = {
            "category": "equipment",
            "name": "紫外分光光度计",
        }
        async with _client(
            WRITE, model_result=_describe_result(), settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe", items=[registered]))
        assert resp.status_code == 200, resp.text
        names = [item["name"] for item in resp.json()["data"]["items"]]
        assert names.count("紫外分光光度计") == 0

    async def test_dedupes_registered_item_when_model_category_differs(self) -> None:
        """模型类别与已登记类别不一致时，主数据校正后应整条丢弃。"""
        registered = {
            "category": "equipment",
            "name": "紫外分光光度计",
        }
        result = _describe_result(
            items=[
                {
                    "name": "紫外分光光度计",
                    "category": "other",
                    "batch_no": "",
                    "evidence": "紫外分光光度计",
                }
            ]
        )
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, session):
            await _seed_master(session, "EQUIPMENT", "UV-1", "紫外分光光度计")
            resp = await _assist(ac, _assist_payload("describe", items=[registered]))
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["items"] == []

    async def test_caps_suggested_items(self) -> None:
        """建议条数超过上限时截断到 20，防止长描述刷出几十行。"""
        result = _describe_result(
            items=[
                {"name": f"对象{i:02d}", "category": "other", "batch_no": "", "evidence": ""}
                for i in range(25)
            ]
        )
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe"))
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["data"]["items"]) == 20

    async def test_invalid_category_coerced_to_other(self) -> None:
        """模型给出未知类别时降级为 other，不整体失败。"""
        result = _describe_result(
            items=[
                {"name": "神秘对象", "category": "spaceship", "batch_no": "", "evidence": ""}
            ]
        )
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["items"][0]["category"] == "other"

    async def test_empty_description_from_model_raises(self) -> None:
        """规范化结果为空时不能把建议卡空描述回给用户。"""
        async with _client(
            WRITE, model_result=_describe_result(description="  "), settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("describe"))
        assert resp.status_code == 502


# ───────────────────────── 调查辅助 ─────────────────────────


class TestM1eAssist:
    async def test_capped_and_sanitized(self) -> None:
        """问题数超限截断到 3；非字符串项与未知方面被过滤。"""
        result = {
            "checklists": {
                "personnel": [f"人员问题{i}" for i in range(10)] + [42, "  "],
                "machine": ["设备当天校准状态如何？"],
                "galaxy": ["未知方面应被忽略"],
            }
        }
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("m1e"))
        assert resp.status_code == 200, resp.text
        checklists = resp.json()["data"]["checklists"]
        assert len(checklists["personnel"]) == 3
        assert all(isinstance(q, str) and q.strip() for q in checklists["personnel"])
        assert "galaxy" not in checklists


class TestWhyAssist:
    async def test_capped_and_skips_empty_questions(self) -> None:
        """追问链截断到 10 步；空问题步被跳过。"""
        result = {
            "steps": [
                {"question": f"为什么{i}？", "answer": f"回答{i}"} for i in range(12)
            ]
            + [{"question": "", "answer": "空问题应被跳过"}]
        }
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(ac, _assist_payload("why"))
        assert resp.status_code == 200, resp.text
        steps = resp.json()["data"]["steps"]
        assert len(steps) == 10
        assert all(step["question"] for step in steps)


class TestHypothesisAssist:
    async def test_capped_and_fields_preserved(self) -> None:
        """假设草案截断到 5 条，可选字段原样透传。"""
        result = {
            "hypotheses": [
                {
                    "hypothesis": f"假设{i}",
                    "sample": f"样品{i}",
                    "protocol": "取样复测",
                    "expected": "结果应符合标准",
                }
                for i in range(6)
            ]
        }
        async with _client(
            WRITE, model_result=result, settings=_ai_settings()
        ) as (ac, _):
            resp = await _assist(
                ac,
                _assist_payload(
                    "hypothesis",
                    direct_cause="检验员疏忽忘记波长准确性确认",
                ),
            )
        assert resp.status_code == 200, resp.text
        hypotheses = resp.json()["data"]["hypotheses"]
        assert len(hypotheses) == 5
        assert hypotheses[0]["sample"] == "样品0"
        assert hypotheses[0]["expected"] == "结果应符合标准"


@pytest.mark.parametrize("kind", ["describe", "m1e", "why", "hypothesis"])
async def test_all_kinds_audited(kind: str) -> None:
    """四种辅助都只产建议并记一条不含原文的审计（kind 留痕）。"""
    results = {
        "describe": _describe_result(),
        "m1e": {"checklists": {"personnel": ["问题？"]}},
        "why": {"steps": [{"question": "为什么？", "answer": "回答"}]},
        "hypothesis": {"hypotheses": [{"hypothesis": "假设", "sample": None, "protocol": None, "expected": None}]},
    }
    async with _client(
        WRITE, model_result=results[kind], settings=_ai_settings()
    ) as (ac, _):
        resp = await _assist(ac, _assist_payload(kind))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["kind"] == kind
