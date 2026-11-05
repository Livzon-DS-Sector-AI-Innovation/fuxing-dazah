"""T05 AI 写白名单断言 + ① 停写督办守卫（spec B1 写 + B3）— TDD 测试。

接缝 S7（与 ``test_hazard_direct_writeback.py`` 同款）：
- FakeWriter 只实现底座写入协议 ``update_record(record_id, fields)``，捕获真实 payload；
- ③ 督办轮询开关的运行期边界是 ``hazard_direct.config.supervision_poll_enabled``
  （field_authority 惰性读取），测试 monkeypatch 该配置函数覆盖两配置；
- 白名单钉子用 ``field_authority.writer_whitelist`` / ``assert_no_human_fields``
  对捕获 payload 做断言（registry 单一事实源），不 mock 私有实现。

覆盖：
- ③ 开启 → ``write_ai_analysis`` payload 不含「督办等级」（① 只算不写）；
- ③ 未开 → 含「督办等级」+ 节流 WARNING（≥300s 一次）；
- 三类写回（ai_analysis / scoring / review）写前都经 ``assert_write_allowed``，
  越权时在触碰 writer 之前抛 ``FieldAuthorityError``；
- FakeWriter 捕获的 payload 均落在各自写链白名单内、无人工列。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.service.hazard_direct import bitable_repo
from app.modules.safety.service.hazard_direct import config as hazard_config
from app.modules.safety.service.hazard_direct import field_authority as fa

_LOGGER_NAME = "app.modules.safety.service.hazard_direct.bitable_repo"


class FakeWriter:
    """替身：只实现底座写入协议 update_record(record_id, fields)。"""

    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        self.calls.append((record_id, fields))
        return self.ok


def _as_client(writer: FakeWriter) -> SafetyBitableClient:
    """FakeWriter 只实现底座写协议；类型上转到真实签名以复用严格 mypy 检查。"""
    return cast(SafetyBitableClient, writer)


def _output() -> dict[str, Any]:
    """① 识别输出（6 个 AI 字段全非空）。"""
    return {
        "hazard_type": "unsafe_action",
        "hazard_level": "general",
        "hazard_category": "equipment",
        "key_defect": "缺陷描述",
        "major_hazard_basis": "判定依据",
        "advice_text": "整改建议",
    }


_AI_FIELDS_WITHOUT_SUPERVISION = {
    "隐患分类（AI）",
    "隐患级别（AI）",
    "隐患类别（AI）",
    "隐患描述（AI）",
    "隐患判定依据（AI）",
    "整改建议（AI）",
    "隐患编号",
}


def _set_poll_enabled(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """③ 督办轮询开关的运行期配置边界。"""
    monkeypatch.setattr(
        hazard_config, "supervision_poll_enabled", lambda: enabled
    )


@pytest.fixture(autouse=True)
def reset_supervision_fallback_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """节流状态是进程级模块变量，用例间必须隔离。"""
    monkeypatch.setattr(
        bitable_repo, "_last_supervision_fallback_warn_at", None, raising=False
    )


@pytest.fixture
def log_capture(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """捕获 bitable_repo 日志（app 日志配置 propagate=False，caplog 直挂 handler）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


# ═══════════════════════════════════════════════════════════════
# B3：③ 开启 → ① 只算不写督办等级
# ═══════════════════════════════════════════════════════════════


async def test_ai_analysis_skips_supervision_when_poll_enabled(
    monkeypatch: pytest.MonkeyPatch,
    log_capture: pytest.LogCaptureFixture,
) -> None:
    _set_poll_enabled(monkeypatch, True)
    writer = FakeWriter()

    ok = await bitable_repo.write_ai_analysis(
        _as_client(writer),
        "rec-1",
        hazard_no="HZ-20261105-001",
        output=_output(),
        supervision_label="一般预警",
    )

    assert ok is True
    assert len(writer.calls) == 1
    _, fields = writer.calls[0]
    assert "督办等级" not in fields
    assert set(fields) == _AI_FIELDS_WITHOUT_SUPERVISION
    # ① 仍计算 label（入参存在），只是不写；日志可辨识「只算不写」
    assert any(
        record.levelno == logging.DEBUG
        and "只算不写" in record.getMessage()
        and "record_id=rec-1" in record.getMessage()
        for record in log_capture.records
    )


async def test_ai_analysis_supervision_only_payload_is_skipped_when_poll_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """③ 开启时若只有督办等级可写 → ① 无字段可写，不落 update_record。"""
    _set_poll_enabled(monkeypatch, True)
    writer = FakeWriter()

    ok = await bitable_repo.write_ai_analysis(
        _as_client(writer), "rec-2", hazard_no=None, output={}, supervision_label="一般预警"
    )

    assert ok is False
    assert writer.calls == []


# ═══════════════════════════════════════════════════════════════
# B3：③ 未开 → ① 保留写督办等级 + 节流 WARNING
# ═══════════════════════════════════════════════════════════════


async def test_ai_analysis_writes_supervision_when_poll_disabled_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    log_capture: pytest.LogCaptureFixture,
) -> None:
    _set_poll_enabled(monkeypatch, False)
    writer = FakeWriter()

    ok = await bitable_repo.write_ai_analysis(
        _as_client(writer),
        "rec-3",
        hazard_no="HZ-20261105-002",
        output=_output(),
        supervision_label="一般预警",
    )

    assert ok is True
    _, fields = writer.calls[0]
    assert fields["督办等级"] == "一般预警"
    assert any(
        record.levelno == logging.WARNING
        and "③督办轮询未开启" in record.getMessage()
        and "①回退写督办等级" in record.getMessage()
        for record in log_capture.records
    )


async def test_supervision_fallback_warning_is_throttled(
    monkeypatch: pytest.MonkeyPatch,
    log_capture: pytest.LogCaptureFixture,
) -> None:
    """③ 未开启时回退告警 ≥300s 一条（避免每轮刷告警）。"""
    _set_poll_enabled(monkeypatch, False)
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        bitable_repo, "_monotonic", lambda: clock["now"], raising=False
    )
    writer = FakeWriter()

    def _warn_count() -> int:
        return sum(
            1
            for record in log_capture.records
            if "③督办轮询未开启" in record.getMessage()
        )

    await bitable_repo.write_ai_analysis(
        _as_client(writer), "rec-4", hazard_no=None, output=_output(), supervision_label="一般预警"
    )
    assert _warn_count() == 1

    # 间隔内（<300s）不重复告警，但督办列仍写
    clock["now"] += 299.0
    await bitable_repo.write_ai_analysis(
        _as_client(writer), "rec-5", hazard_no=None, output=_output(), supervision_label="一般预警"
    )
    assert _warn_count() == 1
    assert writer.calls[-1][1]["督办等级"] == "一般预警"

    # 达到节流窗口（≥300s）后再次告警
    clock["now"] += fa.SUPERVISION_FALLBACK_WARN_INTERVAL_SECONDS
    await bitable_repo.write_ai_analysis(
        _as_client(writer), "rec-6", hazard_no=None, output=_output(), supervision_label="一般预警"
    )
    assert _warn_count() == 2


# ═══════════════════════════════════════════════════════════════
# B1：写链白名单（FakeWriter payload ⊆ registry 白名单；无人工列）
# ═══════════════════════════════════════════════════════════════


async def test_ai_analysis_payload_is_within_whitelist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_poll_enabled(monkeypatch, False)
    writer = FakeWriter()

    await bitable_repo.write_ai_analysis(
        _as_client(writer),
        "rec-7",
        hazard_no="HZ-20261105-003",
        output=_output(),
        supervision_label="一般预警",
    )

    fields = set(writer.calls[0][1])
    assert fields <= fa.writer_whitelist("ai_analysis")
    fa.assert_write_allowed("ai_analysis", fields)
    fa.assert_no_human_fields(fields)


async def test_scoring_payload_is_within_whitelist() -> None:
    writer = FakeWriter()

    ok = await bitable_repo.write_scoring(
        _as_client(writer), "rec-8", total=86.44, note="说明"
    )

    assert ok is True
    fields = set(writer.calls[0][1])
    assert fields == {"评分结果", "评分说明"}
    assert fields <= fa.writer_whitelist("scoring")
    fa.assert_no_human_fields(fields)


async def test_review_payload_is_within_whitelist() -> None:
    writer = FakeWriter()

    ok = await bitable_repo.write_review(
        _as_client(writer), "rec-9", conclusion="已通过", summary="说明"
    )

    assert ok is True
    fields = set(writer.calls[0][1])
    assert fields <= fa.writer_whitelist("review")
    fa.assert_no_human_fields(fields)


async def test_write_paths_abort_before_writer_on_authority_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """写前断言一旦抛 FieldAuthorityError，不得触碰 writer（不写任何列）。"""

    def _deny(writer_name: str, fields: Any) -> None:
        raise fa.FieldAuthorityError(f"测试越权: {writer_name}")

    monkeypatch.setattr(fa, "assert_write_allowed", _deny)
    writer = FakeWriter()

    with pytest.raises(fa.FieldAuthorityError):
        await bitable_repo.write_ai_analysis(
            _as_client(writer), "rec-10", hazard_no=None, output=_output()
        )
    with pytest.raises(fa.FieldAuthorityError):
        await bitable_repo.write_scoring(_as_client(writer), "rec-10", total=60.0, note="说明")
    with pytest.raises(fa.FieldAuthorityError):
        await bitable_repo.write_review(
            _as_client(writer), "rec-10", conclusion="已通过", summary="说明"
        )

    assert writer.calls == []
