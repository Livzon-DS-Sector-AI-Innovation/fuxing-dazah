"""②-b 已关闭自动通过单测 — 判据形状 + 轮询分支行为（不烧 AI）。

接缝：``run_review_round`` 对 ``bitable_repo`` 检索/锁/写回的调用面
（monkeypatch 注入，不发真请求）。核心断言：
- 已关闭未初审记录被写「已通过 + AUTOPASS_NOTE」，不调 AI（``_review_one`` 不触发）；
- 开关关（REVIEW_AUTOPASS_ENABLED=false）→ 分支整体跳过；
- 写回失败 → 计入 failures（下轮重试语义）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.modules.safety.service.hazard_direct import bitable_repo, review
from app.modules.safety.service.hazard_direct.review import (
    AUTOPASS_NOTE,
    ReviewRoundResult,
    run_review_round,
)


def _record(rid: str) -> dict:
    return {"record_id": rid, "fields": {}}


@pytest.fixture(autouse=True)
def _common(monkeypatch):
    """公共桩：记录锁恒真 + 三个检索默认空（各用例再覆写需要的一支）。"""
    monkeypatch.setattr(
        bitable_repo,
        "record_lock",
        lambda rid: _always_lock(),
    )
    monkeypatch.setattr(
        bitable_repo, "search_pending_review", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        bitable_repo, "search_autopass_review", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        bitable_repo, "search_override_review", AsyncMock(return_value=[])
    )
    # 轮询入口构造 SafetyBitableClient —— 桩掉
    import app.modules.safety.service.hazard_direct.review as rv

    monkeypatch.setattr(
        "app.modules.safety.feishu.bitable_client.SafetyBitableClient",
        lambda: object(),
    )
    yield


@asynccontextmanager
async def _always_lock():
    yield True


def _enable_autopass(monkeypatch, enabled: bool = True):
    monkeypatch.setattr(review.config, "review_autopass_enabled", lambda: enabled)


def _stub_write(monkeypatch) -> AsyncMock:
    m = AsyncMock(return_value=True)
    monkeypatch.setattr(bitable_repo, "write_review", m)
    return m


# ── 判据形状 ────────────────────────────────────────────────────


def test_autopass_criteria_shape():
    assert bitable_repo.COND_REVIEW_AUTOPASS == [
        {"field_name": "AI初审结果", "operator": "isEmpty", "value": []},
        {"field_name": "整改状态", "operator": "is", "value": ["已关闭"]},
    ]


def test_autopass_criteria_covers_closed_without_reply():
    """② 主判据要求回复非空；②-b 不要求（关闭即视为整改被接受）。"""
    names = [c["field_name"] for c in bitable_repo.COND_REVIEW_AUTOPASS]
    assert "纠正预防措施" not in names


# ── 轮询分支 ────────────────────────────────────────────────────


async def test_autopass_writes_without_ai(monkeypatch):
    _enable_autopass(monkeypatch)
    monkeypatch.setattr(
        bitable_repo,
        "search_autopass_review",
        AsyncMock(return_value=[_record("recA"), _record("recB")]),
    )
    ai_review = AsyncMock()
    monkeypatch.setattr(review, "_review_one", ai_review)
    write = _stub_write(monkeypatch)

    result = await run_review_round()

    assert write.await_count == 2
    # 每次写回都是「已通过 + 固定说明」
    for call in write.await_args_list:
        assert call.kwargs.get("conclusion") == "已通过"
        assert call.kwargs.get("summary") == AUTOPASS_NOTE
        assert "未走AI初审" in call.kwargs.get("summary", "")
    ai_review.assert_not_awaited()  # 关键：不烧 AI
    assert result.autopassed == 2
    assert result.succeeded == 2
    assert result.failed == 0


async def test_autopass_disabled_skips_branch(monkeypatch):
    _enable_autopass(monkeypatch, enabled=False)
    monkeypatch.setattr(
        bitable_repo,
        "search_autopass_review",
        AsyncMock(return_value=[_record("recA")]),
    )
    write = _stub_write(monkeypatch)

    result = await run_review_round()

    write.assert_not_awaited()
    assert result.autopassed == 0


async def test_autopass_write_failure_counted(monkeypatch):
    _enable_autopass(monkeypatch)
    monkeypatch.setattr(
        bitable_repo,
        "search_autopass_review",
        AsyncMock(return_value=[_record("recBad")]),
    )
    monkeypatch.setattr(
        bitable_repo, "write_review", AsyncMock(return_value=False)
    )

    result = await run_review_round()

    assert result.autopassed == 0
    assert result.failed == 1
    assert result.failures[0]["record_id"] == "recBad"


async def test_result_dict_includes_autopassed():
    r = ReviewRoundResult(succeeded=3, autopassed=2)
    d = r.as_dict()
    assert d["autopassed"] == 2 and d["succeeded"] == 3


# ── ②-c 已关闭跟随改写（人工关闭优先）──────────────────────────


def _closed_review_record(rid: str, conclusion: str, note: str = "") -> dict:
    return {
        "record_id": rid,
        "fields": {"AI初审结果": [conclusion], "AI初审说明": note},
    }


def test_override_criteria_shape():
    """②-c 判据（嵌套非法拆两支）：AI初审=未通过/无需整改 各 AND 已关闭。"""
    assert bitable_repo.COND_REVIEW_OVERRIDE_FAILED == [
        {"field_name": "AI初审结果", "operator": "is", "value": ["未通过"]},
        {"field_name": "整改状态", "operator": "is", "value": ["已关闭"]},
    ]
    assert bitable_repo.COND_REVIEW_OVERRIDE_NA == [
        {"field_name": "AI初审结果", "operator": "is", "value": ["无需整改"]},
        {"field_name": "整改状态", "operator": "is", "value": ["已关闭"]},
    ]


async def test_override_rewrites_failed_to_passed(monkeypatch):
    """未通过+已关闭 → 改写已通过，说明含原结论与原原因摘要。"""
    _enable_autopass(monkeypatch)
    monkeypatch.setattr(
        bitable_repo,
        "search_override_review",
        AsyncMock(return_value=[
            _closed_review_record(
                "recF", "未通过",
                "AI初审不通过，需重新整改。整改后图片与原始缺陷不符。",
            ),
        ]),
    )
    write = _stub_write(monkeypatch)

    result = await run_review_round()

    write.assert_awaited_once()
    kw = write.await_args.kwargs
    assert kw["conclusion"] == "已通过"
    assert "「未通过」" in kw["summary"]
    assert "改写为已通过" in kw["summary"]
    assert "整改后图片与原始缺陷不符" in kw["summary"]  # 原因摘要保留
    assert result.overridden == 1 and result.succeeded == 1


async def test_override_long_note_truncated(monkeypatch):
    """超长原说明截断（字段不刷爆）。"""
    _enable_autopass(monkeypatch)
    monkeypatch.setattr(
        bitable_repo,
        "search_override_review",
        AsyncMock(return_value=[
            _closed_review_record("recL", "无需整改", "长" * 500),
        ]),
    )
    write = _stub_write(monkeypatch)

    result = await run_review_round()

    summary = write.await_args.kwargs["summary"]
    assert "「无需整改」" in summary
    assert len(summary) < 400  # 模板 + 200 截断
    assert result.overridden == 1


async def test_override_disabled_skips(monkeypatch):
    _enable_autopass(monkeypatch, enabled=False)
    monkeypatch.setattr(
        bitable_repo,
        "search_override_review",
        AsyncMock(return_value=[_closed_review_record("recF", "未通过")]),
    )
    write = _stub_write(monkeypatch)

    result = await run_review_round()

    write.assert_not_awaited()
    assert result.overridden == 0
