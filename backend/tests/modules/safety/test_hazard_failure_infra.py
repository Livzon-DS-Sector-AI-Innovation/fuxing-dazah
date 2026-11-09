"""T02 · F1：AI 基础设施失败免死信化（S4/S8 接缝）。

覆盖：
- ``_categorize_failure`` 分类矩阵（S8）：结构化 ``IdentificationError.category``
  优先、异常链 httpx 状态/超时/连接/配置分类、中文子串仅兜底、未知 → api_error；
- ``run_ai_analysis_round``（S4）：连续 5 轮 401 → 不计 attempts、不进死信，
  第 6 轮恢复写回成功；record-level（validation_failed / json_invalid /
  no_chunks）仍按 1/3/9 退避、第 5 次死信；
- 基础设施失败在 ``RoundResult`` 中区分 ``infra_failed`` / ``non_infra_failed`` /
  ``infra_failures``，并按 RAG / AI 分列表聚合；
- 告警分 key 去重：RAG 用 ``INFRA_ALERT_KEY``，AI 用独立
  ``AI_INFRA_ALERT_KEY``，均 30 分钟 SET NX EX。

全部 fake（Bitable client / ``_identify_one`` / 写回 / 失败账本 / 告警）；
Redis 使用内存假件，不连真实网络/Redis/Bitable。
假件（_RoundEnv/_FakeLedger/_wire_round）沿用 test_hazard_quality_gate.py 先例并复制，改契约时三处同步。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import pytest

from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
    failure_ledger,
)
from app.modules.safety.service.hazard_direct import config as hazard_config
from app.modules.safety.service.hazard_direct.quality_gate import QualityGateError
from app.modules.safety.service.hazard_direct.round_result import RoundResult

GOOD_BASIS = "《危险化学品安全管理条例》第二十条（GB 30871-2022 第5.1条）"


# ═══════════════════════════════════════════════════════════════
# 假件：FakeRedis / _FakeLedger / _RealLedger / 单轮环境
# ═══════════════════════════════════════════════════════════════


class FakeRedis:
    """最小 RedisLike 假件（与 test_hazard_failure_ledger.py::FakeRedis 同手法）。"""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def get(self, key: str) -> Any:
        self._check()
        return self.store.get(key)

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> Any:
        self._check()
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def incr(self, key: str) -> int:
        self._check()
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> Any:
        self._check()
        self.ttls[key] = seconds
        return True

    async def hset(self, key: str, field: str, value: str) -> Any:
        self._check()
        bucket = self.store.setdefault(key, {})
        bucket[field] = value
        return 1

    async def hget(self, key: str, field: str) -> Any:
        self._check()
        bucket = self.store.get(key)
        if not isinstance(bucket, dict):
            return None
        return bucket.get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        self._check()
        bucket = self.store.get(key)
        return dict(bucket) if isinstance(bucket, dict) else {}

    async def hdel(self, key: str, field: str) -> Any:
        self._check()
        bucket = self.store.get(key)
        if not isinstance(bucket, dict):
            return 0
        return 1 if bucket.pop(field, None) is not None else 0

    async def delete(self, key: str) -> Any:
        self._check()
        return 1 if self.store.pop(key, None) is not None else 0


class _FakeLedger:
    """ai_analysis.failure_ledger 替身（可控返回 / 记录调用）。"""

    def __init__(self) -> None:
        self.round_seq = 7
        self.states: list[failure_ledger.FailureState] = []
        self.failure_calls: list[tuple[str, int, str, str]] = []
        self.success_ids: list[str] = []
        self.dead_letters: list[dict[str, Any]] = []
        self.should_retry_calls: list[tuple[str, int]] = []
        self.infra_alert_results: list[bool] = []
        self.infra_alert_calls: list[tuple[int, int, str]] = []

    async def next_round_seq(self) -> int:
        return self.round_seq

    async def should_retry(self, record_id: str, round_seq: int) -> bool:
        self.should_retry_calls.append((record_id, round_seq))
        return True

    async def retry_status(self, record_id: str, round_seq: int) -> str:
        return "ok"

    async def record_failure(
        self, record_id: str, round_seq: int, category: str, reason: str
    ) -> failure_ledger.FailureState:
        self.failure_calls.append((record_id, round_seq, category, reason))
        if self.states:
            return self.states.pop(0)
        return failure_ledger.FailureState(
            record_id=record_id,
            attempts=1,
            next_round=round_seq + 1,
            category=category,
            reason=reason,
            dead=False,
            dead_at=None,
            is_new=True,
        )

    async def record_success(self, record_id: str) -> None:
        self.success_ids.append(record_id)

    async def list_dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self.dead_letters)

    async def should_emit_infra_alert(
        self,
        round_seq: int,
        interval_seconds: int = 1800,
        *,
        key: str = failure_ledger.INFRA_ALERT_KEY,
    ) -> bool:
        self.infra_alert_calls.append((round_seq, interval_seconds, key))
        if self.infra_alert_results:
            return self.infra_alert_results.pop(0)
        return True


class _RealLedger:
    """把 ai_analysis.failure_ledger 接到真实 failure_ledger + FakeRedis。

    轮次序号由本假件自增（不写 Redis），其余行为全部走真实实现——
    用于验证「5×401 不计 attempts/不进死信」「record-level 1/3/9 死信」。
    """

    def __init__(self, redis: FakeRedis | None = None) -> None:
        self.redis = redis or FakeRedis()
        self.round_seq = 0
        self.infra_alert_calls: list[tuple[int, int, str]] = []

    async def next_round_seq(self) -> int:
        self.round_seq += 1
        return self.round_seq

    async def should_retry(self, record_id: str, round_seq: int) -> bool:
        return await failure_ledger.should_retry(
            record_id, round_seq, redis=self.redis
        )

    async def record_failure(
        self, record_id: str, round_seq: int, category: str, reason: str
    ) -> failure_ledger.FailureState:
        return await failure_ledger.record_failure(
            record_id, round_seq, category, reason, redis=self.redis
        )

    async def record_success(self, record_id: str) -> None:
        await failure_ledger.record_success(record_id, redis=self.redis)

    async def list_dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        return await failure_ledger.list_dead_letters(limit, redis=self.redis)

    async def should_emit_infra_alert(
        self,
        round_seq: int,
        interval_seconds: int = 1800,
        *,
        key: str = failure_ledger.INFRA_ALERT_KEY,
    ) -> bool:
        self.infra_alert_calls.append((round_seq, interval_seconds, key))
        return await failure_ledger.should_emit_infra_alert(
            round_seq, interval_seconds, redis=self.redis, key=key
        )


class _RoundEnv:
    def __init__(self, ledger: Any = None) -> None:
        self.ledger = ledger if ledger is not None else _FakeLedger()
        self.written: list[tuple[str, dict[str, Any]]] = []
        self.identify_calls: list[tuple[str, str | None]] = []
        self.identify_impl: Any = None
        self.write_ok = True
        self.notify_failures: list[dict[str, Any]] = []
        self.notify_admin: list[tuple[str, str]] = []


def _raw_record(record_id: str) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "fields": {
            "隐患编号": "HZ-20261105-001",
            "隐患描述": "3号罐区静电跨接断裂",
            "检查日期": 1762300800000,
            "检查人员": [{"id": "u1", "name": "张三"}],
            "整改责任人.部门": ["储运部"],
        },
    }


def _identified_output() -> dict[str, Any]:
    return {
        "key_defect": "3号罐区静电跨接断裂",
        "hazard_type": "unsafe_condition",
        "hazard_category": "lightning_antistatic",
        "hazard_level": "general",
        "major_hazard_basis": GOOD_BASIS,
        "defect_substance": "substantive",
        "defect_substance_reasoning": "跨接断裂导致静电无法导除",
        "rectification_suggestion": {"corrective": "重新安装跨接线", "preventive": "纳入巡检"},
    }


async def _wire_round(
    monkeypatch: pytest.MonkeyPatch,
    env: _RoundEnv,
    *,
    records: list[dict[str, Any]],
) -> None:
    async def fake_search(
        client: Any, *, limit: int | None = None, keep: Any = None
    ) -> list[dict[str, Any]]:
        # 本文件只测 F1 轮级语义：取数桩忽略 keep（F2 预过滤由
        # test_hazard_queue_starvation.py 用真实 search_pending_ai 覆盖）
        return list(records)

    monkeypatch.setattr(bitable_repo, "search_pending_ai", fake_search)

    @asynccontextmanager
    async def fake_record_lock(record_id: str) -> Any:
        yield True

    monkeypatch.setattr(bitable_repo, "record_lock", fake_record_lock)

    async def fake_write_ai_analysis(
        client: Any,
        record_id: str,
        *,
        hazard_no: str | None,
        output: dict[str, Any],
        supervision_label: str | None = None,
        snapshot_fields: dict[str, Any] | None = None,
    ) -> bool:
        env.written.append((record_id, output))
        return env.write_ok

    monkeypatch.setattr(bitable_repo, "write_ai_analysis", fake_write_ai_analysis)
    monkeypatch.setattr(ai_analysis, "_supervision_label", lambda view: None)

    async def fake_identify_one(
        client: Any, view: Any, *, round_id: str | None = None
    ) -> dict[str, Any]:
        env.identify_calls.append((view.record_id, round_id))
        return cast(dict[str, Any], await env.identify_impl(view))

    monkeypatch.setattr(ai_analysis, "_identify_one", fake_identify_one)
    monkeypatch.setattr(ai_analysis, "failure_ledger", env.ledger)

    import app.modules.safety.feishu.bitable_client as bitable_client

    monkeypatch.setattr(
        bitable_client, "SafetyBitableClient", lambda *args, **kwargs: object()
    )

    async def fake_notify_failures(
        job_label: str,
        *,
        failures: list[dict[str, str]],
        total: int,
        error: str = "",
    ) -> bool:
        env.notify_failures.append(
            {"failures": failures, "total": total, "error": error}
        )
        return True

    async def fake_notify_admin(title: str, content: str) -> bool:
        env.notify_admin.append((title, content))
        return True

    monkeypatch.setattr(ai_analysis, "notify_failures", fake_notify_failures)
    monkeypatch.setattr(ai_analysis, "notify_admin", fake_notify_admin)


# ═══════════════════════════════════════════════════════════════
# S8 · 失败分类矩阵（_categorize_failure 直调）
# ═══════════════════════════════════════════════════════════════


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=request, response=response
    )


def _wrap_identification_error(inner: BaseException) -> BaseException:
    """复刻插件包装：IdentificationError(category=_error_category(exc)) from exc。

    category 与 ``ai_hazard_identification.plugin._error_category`` 一致：
    链上带 category 的 IdentificationError 原样保留、链上 AIOutputError →
    ``json_invalid``、其它（网络/超时/未知）→ None 交给上层兜底。
    """
    from app.modules.safety.ai_hazard_identification import IdentificationError
    from app.modules.safety.ai_hazard_identification.plugin import _error_category

    try:
        try:
            raise inner
        except Exception as exc:
            raise IdentificationError(
                "AI 文本分析失败: 上游失败", category=_error_category(exc)
            ) from exc
    except IdentificationError as wrapped:
        return wrapped


class TestCategorizeFailureInfraMatrix:
    def test_quality_gate_error_uses_category(self) -> None:
        error = QualityGateError("retrieval_degraded", "RAG 降级")
        assert ai_analysis._categorize_failure(error) == "retrieval_degraded"

    def test_structured_category_takes_priority(self) -> None:
        from app.modules.safety.ai_hazard_identification import IdentificationError

        # 结构化 category 优先于中文子串：消息像 validation，但 category 是 json_invalid
        error = IdentificationError("AI 输出验证失败: 缺字段", category="json_invalid")
        assert ai_analysis._categorize_failure(error) == "json_invalid"
        # category 是 validation_failed 时不被消息中的「解析」干扰
        error2 = IdentificationError("AI 解析失败: x", category="validation_failed")
        assert ai_analysis._categorize_failure(error2) == "validation_failed"

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (401, "api_auth"),
            (403, "api_auth"),
            (402, "api_quota"),
            (429, "api_quota"),
            (500, "api_server"),
            (502, "api_server"),
            (503, "api_server"),
        ],
    )
    def test_http_status_matrix(self, status_code: int, expected: str) -> None:
        assert ai_analysis._categorize_failure(_http_status_error(status_code)) == expected

    def test_timeout_is_api_timeout(self) -> None:
        exc = httpx.TimeoutException("read timeout")
        assert ai_analysis._categorize_failure(exc) == "api_timeout"

    def test_connect_error_is_api_connect(self) -> None:
        exc = httpx.ConnectError("connection refused")
        assert ai_analysis._categorize_failure(exc) == "api_connect"

    def test_scenario_disabled_is_api_config(self) -> None:
        """F1-4：安全模块场景熔断（叶子异常，只继承 Exception）→ api_config。"""
        from app.modules.safety.ai_config.exceptions import ScenarioDisabledError

        exc = ScenarioDisabledError("hazard_identification")
        # 钉子：它不是 RuntimeError，救不了「靠 RuntimeError 消息兜底」的实现
        assert not isinstance(exc, RuntimeError)
        assert type(exc).__module__ == "app.modules.safety.ai_config.exceptions"
        assert ai_analysis._categorize_failure(exc) == "api_config"

    @pytest.mark.parametrize(
        "message",
        ["AI 服务未配置 API Key", "模型配置缺失", "SAFETY_AI_VISION_MODEL 未设置"],
    )
    def test_config_runtime_error_is_api_config(self, message: str) -> None:
        assert ai_analysis._categorize_failure(RuntimeError(message)) == "api_config"

    def test_wrapped_http_status_error_detected_through_chain(self) -> None:
        wrapped = _wrap_identification_error(_http_status_error(401))
        assert ai_analysis._categorize_failure(wrapped) == "api_auth"

    def test_wrapped_timeout_detected_through_chain(self) -> None:
        wrapped = _wrap_identification_error(httpx.TimeoutException("timeout"))
        assert ai_analysis._categorize_failure(wrapped) == "api_timeout"

    def test_wrapped_connect_error_detected_through_chain(self) -> None:
        wrapped = _wrap_identification_error(httpx.ConnectError("refused"))
        assert ai_analysis._categorize_failure(wrapped) == "api_connect"

    def test_wrapped_scenario_disabled_is_api_config(self) -> None:
        """F1-4：安全模块场景熔断包进 IdentificationError（cause 链）→ api_config。"""
        from app.modules.safety.ai_config.exceptions import ScenarioDisabledError
        from app.modules.safety.ai_hazard_identification import IdentificationError

        wrapped = _wrap_identification_error(
            ScenarioDisabledError("hazard_identification")
        )
        assert isinstance(wrapped, IdentificationError)
        assert ai_analysis._categorize_failure(wrapped) == "api_config"

    def test_ai_output_error_on_chain_is_json_invalid(self) -> None:
        from app.platform.integrations.ai.client import AIOutputError

        assert ai_analysis._categorize_failure(AIOutputError("bad json")) == "json_invalid"
        wrapped = _wrap_identification_error(AIOutputError("bad json"))
        assert ai_analysis._categorize_failure(wrapped) == "json_invalid"

    def test_wrapped_ai_output_error_has_structured_category(self) -> None:
        """F11：包装时 _error_category 算出的结构化 category 优先命中（非只靠链兜底）。"""
        from app.modules.safety.ai_hazard_identification import IdentificationError
        from app.platform.integrations.ai.client import AIOutputError

        wrapped = _wrap_identification_error(AIOutputError("bad json"))

        assert isinstance(wrapped, IdentificationError)
        assert wrapped.category == "json_invalid"
        assert ai_analysis._categorize_failure(wrapped) == "json_invalid"

    def test_chinese_substring_is_only_fallback(self) -> None:
        from app.modules.safety.ai_hazard_identification import IdentificationError

        # 无结构化 category 时才走中文子串兜底
        validation = IdentificationError("AI 输出验证失败: 判定依据过短")
        assert ai_analysis._categorize_failure(validation) == "validation_failed"
        parse = IdentificationError("AI 输出解析失败: 缺字段")
        assert ai_analysis._categorize_failure(parse) == "json_invalid"

    def test_unknown_error_is_api_error(self) -> None:
        assert ai_analysis._categorize_failure(RuntimeError("timeout")) == "api_error"
        assert ai_analysis._categorize_failure(ValueError("weird")) == "api_error"

    def test_not_configured_chinese_message_is_config(self) -> None:
        assert ai_analysis._categorize_failure(RuntimeError("AI 文本模型未配置")) == "api_config"


class TestInfraCategorySets:
    def test_ai_infra_categories(self) -> None:
        assert ai_analysis.AI_INFRA_CATEGORIES == frozenset(
            {
                "api_auth",
                "api_quota",
                "api_server",
                "api_timeout",
                "api_connect",
                "api_config",
            }
        )

    def test_rag_infra_categories(self) -> None:
        assert ai_analysis.RAG_INFRA_CATEGORIES == frozenset({"retrieval_degraded"})

    def test_combined_infra_categories_exclude_record_level(self) -> None:
        combined = ai_analysis._INFRA_FAILURE_CATEGORIES
        assert combined == (
            ai_analysis.AI_INFRA_CATEGORIES | ai_analysis.RAG_INFRA_CATEGORIES
        )
        # R1-3：no_chunks 属数据性零召回 → 记录级（计 attempts/死信）
        assert "no_chunks" not in combined
        assert "json_invalid" not in combined
        assert "validation_failed" not in combined


# ═══════════════════════════════════════════════════════════════
# S4 · 轮级：5×401 不计 attempts/不进死信 → 第 6 轮恢复
# ═══════════════════════════════════════════════════════════════


class TestInfraFailuresDoNotDeadLetter:
    async def test_five_rounds_401_no_attempts_then_sixth_recovers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ledger = _RealLedger()
        env = _RoundEnv(ledger=ledger)

        async def auth_down(view: Any) -> dict[str, Any]:
            raise _wrap_identification_error(_http_status_error(401))

        env.identify_impl = auth_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        for _ in range(5):
            result = await ai_analysis.run_ai_analysis_round(notify=False)
            assert result.failed == 1
            assert result.infra_failed == 1
            assert result.non_infra_failed == 0
            assert result.failures[0]["category"] == "api_auth"
            assert result.infra_failures[0]["record_id"] == "rec-1"
            assert result.infra_failures[0]["category"] == "api_auth"
            assert env.written == []

        # 不累计 attempts、不进死信（Redis 中没有任何失败状态 key）
        assert ledger.redis.store.get(failure_ledger.DEAD_LETTERS_KEY) in (None, {})
        assert not any(
            key.startswith(failure_ledger.KEY_PREFIX) for key in ledger.redis.store
        )
        # 每轮都仍被重试（无退避）：5 轮 5 次调用
        assert len(env.identify_calls) == 5

        # 第 6 轮端点恢复 → 记录立即可处理并写回（没有被死信/退避卡住）
        async def recovered(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = recovered
        result = await ai_analysis.run_ai_analysis_round(notify=True)

        assert result.succeeded == 1
        assert result.failed == 0
        assert result.infra_failed == 0
        assert env.written[0][0] == "rec-1"
        assert ledger.redis.store.get(failure_ledger.DEAD_LETTERS_KEY) in (None, {})

    @pytest.mark.parametrize(
        ("raise_exc", "expected_category"),
        [
            (
                lambda: QualityGateError("no_chunks", "RAG 零召回"),
                "no_chunks",
            ),
            (
                lambda: __import__(
                    "app.modules.safety.ai_hazard_identification",
                    fromlist=["IdentificationError"],
                ).IdentificationError("AI 输出验证失败: 判定依据过短"),
                "validation_failed",
            ),
            (
                lambda: __import__(
                    "app.platform.integrations.ai.client",
                    fromlist=["AIOutputError"],
                ).AIOutputError("bad json"),
                "json_invalid",
            ),
        ],
        ids=["no_chunks", "validation_failed", "json_invalid"],
    )
    async def test_record_level_failures_still_dead_letter_after_backoff(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raise_exc: Any,
        expected_category: str,
    ) -> None:
        """record-level 失败仍按 1/3/9 退避、第 5 次死信（R1-3：no_chunks 移出 infra）。"""
        ledger = _RealLedger()
        env = _RoundEnv(ledger=ledger)

        async def failing(view: Any) -> dict[str, Any]:
            raise raise_exc()

        env.identify_impl = failing
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        attempted_rounds: list[int] = []
        for _ in range(23):
            result = await ai_analysis.run_ai_analysis_round(notify=True)
            if len(env.identify_calls) > len(attempted_rounds):
                # 本轮调用了 AI → 尝试轮：记录级失败（非 infra）
                attempted_rounds.append(ledger.round_seq)
                assert result.failed == 1
                assert result.infra_failed == 0
                assert result.non_infra_failed == 1
                assert result.failures[0]["category"] == expected_category
            else:
                # 退避中/已死信：不调 AI，计入 deferred，不算失败
                assert result.failed == 0
                assert result.deferred == 1

        # 1/3/9/9 退避 → 只在第 1/2/5/14/23 轮调 AI；共 5 次后死信
        assert attempted_rounds == [1, 2, 5, 14, 23]
        assert len(env.written) == 0

        dead_letters = await failure_ledger.list_dead_letters(redis=ledger.redis)
        assert len(dead_letters) == 1
        assert dead_letters[0]["record_id"] == "rec-1"
        assert dead_letters[0]["category"] == expected_category
        assert dead_letters[0]["attempts"] == failure_ledger.MAX_ATTEMPTS
        assert any("死信" in title for title, _ in env.notify_admin)


# ═══════════════════════════════════════════════════════════════
# S4 · 轮级：infra 计数 + 分 key 去重告警
# ═══════════════════════════════════════════════════════════════


class TestRunRoundInfraAlerts:
    async def test_ai_infra_alert_uses_dedicated_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _RoundEnv()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 1)
        env.ledger.infra_alert_results = [True, False]  # 第 1 轮放行、第 2 轮窗口内去重

        async def auth_down(view: Any) -> dict[str, Any]:
            raise _wrap_identification_error(_http_status_error(401))

        env.identify_impl = auth_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        await ai_analysis.run_ai_analysis_round(notify=True)
        await ai_analysis.run_ai_analysis_round(notify=True)

        assert len(env.notify_failures) == 1
        error = env.notify_failures[0]["error"]
        assert "AI 基础设施失败" in error
        assert "不累计 attempts" in error
        assert "不进死信" in error
        assert "恢复后可直接重试" in error
        assert "api_auth=1" in error
        # AI infra 用独立去重 key，30 分钟窗口
        assert env.ledger.infra_alert_calls == [
            (7, 1800, failure_ledger.AI_INFRA_ALERT_KEY),
            (7, 1800, failure_ledger.AI_INFRA_ALERT_KEY),
        ]
        # 不进失败账本
        assert env.ledger.failure_calls == []

    async def test_rag_infra_alert_keeps_original_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _RoundEnv()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 1)

        async def rag_down(view: Any) -> dict[str, Any]:
            raise QualityGateError("retrieval_degraded", "RAG 检索降级")

        env.identify_impl = rag_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        await ai_analysis.run_ai_analysis_round(notify=True)

        assert len(env.notify_failures) == 1
        assert "RAG 基础设施失败" in env.notify_failures[0]["error"]
        assert env.ledger.infra_alert_calls == [
            (7, 1800, failure_ledger.INFRA_ALERT_KEY)
        ]
        assert env.ledger.failure_calls == []

    async def test_ai_and_rag_infra_use_independent_keys_in_same_round(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _RoundEnv()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 1)

        async def failing(view: Any) -> dict[str, Any]:
            if view.record_id == "rec-ai":
                raise _wrap_identification_error(_http_status_error(503))
            raise QualityGateError("retrieval_degraded", "RAG 降级")

        env.identify_impl = failing
        await _wire_round(
            monkeypatch, env, records=[_raw_record("rec-ai"), _raw_record("rec-rag")]
        )

        result = await ai_analysis.run_ai_analysis_round(notify=True)

        assert result.failed == 2
        assert result.infra_failed == 2
        assert result.non_infra_failed == 0
        assert {item["category"] for item in result.infra_failures} == {
            "api_server",
            "retrieval_degraded",
        }
        # 两路告警各一次、各用独立 key
        assert len(env.notify_failures) == 2
        assert env.ledger.infra_alert_calls == [
            (7, 1800, failure_ledger.INFRA_ALERT_KEY),
            (7, 1800, failure_ledger.AI_INFRA_ALERT_KEY),
        ] or env.ledger.infra_alert_calls == [
            (7, 1800, failure_ledger.AI_INFRA_ALERT_KEY),
            (7, 1800, failure_ledger.INFRA_ALERT_KEY),
        ]
        assert env.ledger.failure_calls == []

    async def test_infra_alert_below_threshold_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _RoundEnv()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 10)

        async def auth_down(view: Any) -> dict[str, Any]:
            raise _wrap_identification_error(_http_status_error(402))

        env.identify_impl = auth_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        await ai_analysis.run_ai_analysis_round(notify=True)

        assert env.notify_failures == []
        assert env.ledger.infra_alert_calls == []  # 未达阈值不查去重
        assert env.ledger.failure_calls == []


# ═══════════════════════════════════════════════════════════════
# F1-3 · 去重 key 相互隔离（真实 failure_ledger + FakeRedis）
# ═══════════════════════════════════════════════════════════════


class TestInfraAlertKeysIsolated:
    async def test_rag_and_ai_keys_dedup_independently(self) -> None:
        redis = FakeRedis()

        assert await failure_ledger.should_emit_infra_alert(11, redis=redis) is True
        # RAG 同窗口第二次 → 去重
        assert await failure_ledger.should_emit_infra_alert(12, redis=redis) is False
        # AI infra 独立 key → 不受 RAG 窗口影响
        assert (
            await failure_ledger.should_emit_infra_alert(
                13, redis=redis, key=failure_ledger.AI_INFRA_ALERT_KEY
            )
            is True
        )
        assert (
            await failure_ledger.should_emit_infra_alert(
                14, redis=redis, key=failure_ledger.AI_INFRA_ALERT_KEY
            )
            is False
        )
        assert failure_ledger.INFRA_ALERT_KEY == "safety:hazard:ai:infra_alert_at"
        assert (
            failure_ledger.AI_INFRA_ALERT_KEY
            == "safety:hazard:ai:ai_infra_alert_at"
        )
        assert redis.ttls[failure_ledger.INFRA_ALERT_KEY] == 1800
        assert redis.ttls[failure_ledger.AI_INFRA_ALERT_KEY] == 1800


# ═══════════════════════════════════════════════════════════════
# RoundResult · infra 字段与非 infra 派生
# ═══════════════════════════════════════════════════════════════


class TestRoundResultInfraFields:
    def test_defaults_and_derived_non_infra(self) -> None:
        result = RoundResult(job_label="隐患AI分析轮询")

        assert result.infra_failed == 0
        assert result.infra_failures == []
        assert result.non_infra_failed == 0

        result.failed = 5
        result.infra_failed = 3
        assert result.non_infra_failed == 2

    def test_as_dict_contains_infra_keys(self) -> None:
        result = RoundResult(job_label="隐患AI分析轮询")
        result.failed = 4
        result.infra_failed = 4
        result.infra_failures = [
            {"record_id": "rec-1", "category": "api_auth", "reason": "401"}
        ]

        payload = result.as_dict()

        assert payload["infra_failed"] == 4
        assert payload["non_infra_failed"] == 0
        assert payload["failures"] == []
        # 明细仍保留在属性上（as_dict 按 spec 只加 infra_failed/non_infra_failed 两键）
        assert result.infra_failures == [
            {"record_id": "rec-1", "category": "api_auth", "reason": "401"}
        ]
        # 旧键保持
        for key in ("job_label", "total", "succeeded", "failed", "deferred"):
            assert key in payload, key

    def test_legacy_result_without_infra_fields_is_compatible(self) -> None:
        """②③④⑤ 老构造方式（不传 infra 字段）仍可用，non_infra 回退 failed。"""
        result = RoundResult(job_label="隐患整改审核轮询", failed=2)
        assert result.infra_failed == 0
        assert result.non_infra_failed == 2
