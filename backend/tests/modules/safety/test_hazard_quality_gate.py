"""T05 质量闸门（A3）+ A5/A7 轮级接线测试。

覆盖 ticket 05 验收：
- RAG 降级 / 0 chunks / None → ``retrieval_degraded`` / ``no_chunks``，
  **AI 客户端未创建、未调用、附件未下载**；
- 输出空依据 / 占位文案 / 无引用 → 对应 category，不产出可写结果；
- 合法输出照旧返回可写结果（happy path）；
- ① 只下缺陷图（include_rectification=False）、图片编码走线程、AI 客户端不 close；
- round_id 写入该轮所有 ``ai_audit_scope(extra=...)``；
- 轮级：闸门失败 → ``write_ai_analysis`` 未被调用、failures 带 category；
  成功路径照常写回；未到重试点计入 deferred 且不调 AI；告警只在新增失败/新死信触发。

全部使用 fake（Bitable client / `_load_knowledge_context` / AI service / 失败账本 /
audit scope），不连真实网络/DB/Redis/Bitable。
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.ai_hazard_identification.schemas import (
    DefectSubstanceEnum,
    HazardCategoryEnum,
    HazardLevelEnum,
    HazardTypeEnum,
)
from app.modules.safety.knowledge.retriever import KnowledgeContext
from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
    failure_ledger,
    quality_gate,
)
from app.modules.safety.service.hazard_direct import (
    config as hazard_config,
)
from app.modules.safety.service.hazard_direct.quality_gate import QualityGateError

# 一条「真实法规引用」依据（citations 与规则引擎共用判定）
GOOD_BASIS = "《危险化学品安全管理条例》第二十条（GB 30871-2022 第5.1条）"


@pytest.fixture(autouse=True)
def _ragplus_search_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试默认按 ragplus 内核开启（生产默认开关由 app_config 控制）。

    开关关闭场景在 TestEnsureKnowledgeRagplusSwitch 内显式覆写。
    """
    import app.modules.safety.knowledge.ragplus_client as ragplus_client

    monkeypatch.setattr(ragplus_client, "ragplus_search_enabled", lambda: True)


# ═══════════════════════════════════════════════════════════════
# 质量闸门纯函数
# ═══════════════════════════════════════════════════════════════


def _healthy_context() -> KnowledgeContext:
    return KnowledgeContext(
        chunks=[object()],  # type: ignore[list-item]
        degradation="ragplus",
        markdown="【法规】《危险化学品安全管理条例》第二十条……",
    )


class TestEnsureKnowledge:
    def test_none_context_is_retrieval_degraded(self) -> None:
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_knowledge(None)
        assert exc_info.value.category == "retrieval_degraded"

    @pytest.mark.parametrize(
        "degradation",
        ["text_only", "fallback", "graph_only", "llm_expanded", "ragplus_unavailable"],
    )
    def test_non_ragplus_degradation_is_retrieval_degraded(
        self, degradation: str
    ) -> None:
        context = KnowledgeContext(
            chunks=[object()],  # type: ignore[list-item]
            degradation=degradation,
            markdown="x",
        )
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_knowledge(context)
        assert exc_info.value.category == "retrieval_degraded"

    def test_zero_chunks_is_no_chunks(self) -> None:
        context = KnowledgeContext(chunks=[], degradation="ragplus", markdown="")
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_knowledge(context)
        assert exc_info.value.category == "no_chunks"

    def test_healthy_ragplus_context_passes(self) -> None:
        quality_gate.ensure_knowledge(_healthy_context())

    def test_error_is_exception_with_category_attribute(self) -> None:
        error = QualityGateError("no_citation", "依据无引用")
        assert isinstance(error, Exception)
        assert error.category == "no_citation"
        assert str(error) == "依据无引用"


class TestEnsureKnowledgeRagplusSwitch:
    """健康 degradation 集合与 ragplus 检索内核开关联动（不硬编码魔法串）。"""

    @staticmethod
    def _set_switch(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
        import app.modules.safety.knowledge.ragplus_client as ragplus_client

        monkeypatch.setattr(
            ragplus_client, "ragplus_search_enabled", lambda: enabled
        )

    def test_switch_off_allows_local_full(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._set_switch(monkeypatch, False)
        for degradation in ("full", "llm_expanded"):
            context = KnowledgeContext(
                chunks=[object()],  # type: ignore[list-item]
                degradation=degradation,
                markdown="x",
            )
            quality_gate.ensure_knowledge(context)  # 不抛 = 通过

    def test_switch_off_rejects_ragplus_and_degraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._set_switch(monkeypatch, False)
        for degradation in ("ragplus", "text_only", "fallback"):
            context = KnowledgeContext(
                chunks=[object()],  # type: ignore[list-item]
                degradation=degradation,
                markdown="x",
            )
            with pytest.raises(QualityGateError) as exc_info:
                quality_gate.ensure_knowledge(context)
            assert exc_info.value.category == "retrieval_degraded"

    def test_switch_on_rejects_local_full(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._set_switch(monkeypatch, True)
        context = KnowledgeContext(
            chunks=[object()],  # type: ignore[list-item]
            degradation="full",
            markdown="x",
        )
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_knowledge(context)
        assert exc_info.value.category == "retrieval_degraded"

    def test_switch_on_allows_ragplus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_switch(monkeypatch, True)
        quality_gate.ensure_knowledge(_healthy_context())


class TestEnsureOutput:
    def test_empty_basis(self) -> None:
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_output({"major_hazard_basis": ""})
        assert exc_info.value.category == "empty_basis"

    def test_whitespace_basis_is_empty(self) -> None:
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_output({"major_hazard_basis": "   "})
        assert exc_info.value.category == "empty_basis"

    def test_missing_basis_key_is_empty(self) -> None:
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_output({})
        assert exc_info.value.category == "empty_basis"

    @pytest.mark.parametrize(
        "basis",
        [
            "知识库中无相应条文，待人工补充",
            "知识库信息不足，无法判断",
            "知识库中无相应条文",
        ],
    )
    def test_placeholder_basis(self, basis: str) -> None:
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_output({"major_hazard_basis": basis})
        assert exc_info.value.category == "placeholder_basis"

    def test_basis_without_citation(self) -> None:
        with pytest.raises(QualityGateError) as exc_info:
            quality_gate.ensure_output(
                {"major_hazard_basis": "现场存在杂物堆放，需及时清理"}
            )
        assert exc_info.value.category == "no_citation"

    @pytest.mark.parametrize(
        "basis",
        [
            GOOD_BASIS,
            "《中华人民共和国安全生产法》第九十九条",
            "GB 30871-2022 第5.1条",
            "AQ 3067-2022",
            "依据《危险化学品企业特殊作业安全规范》第6.2条",
        ],
    )
    def test_valid_citation_passes(self, basis: str) -> None:
        quality_gate.ensure_output({"major_hazard_basis": basis})


# ═══════════════════════════════════════════════════════════════
# _identify_one：RAG 预检 + 输出闸门 + A6 接线（S3 接缝）
# ═══════════════════════════════════════════════════════════════


class _FakeAIService:
    def __init__(self, config_type: str) -> None:
        self.config_type = config_type
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Holder:
    def __init__(self) -> None:
        self.context: KnowledgeContext | None = _healthy_context()
        self.output: Any = _good_output()
        self.photos: dict[str, list[str]] = {
            "defect": ["/tmp/a.jpg"],
            "rectification": [],
        }
        self.loaded_description: str | None = None
        self.session_opens = 0
        self.photo_calls: list[dict[str, Any]] = []
        self.photo_result: dict[str, list[str]] = {
            "defect": ["/tmp/a.jpg"],
            "rectification": [],
        }
        self.uri_threads: list[str] = []
        self.uri_paths: list[list[str]] = []
        self.service_types: list[str] = []
        self.services: dict[str, _FakeAIService] = {}
        self.plugins: list[Any] = []
        self.inputs: list[Any] = []
        self.audit_scopes: list[dict[str, Any]] = []


def _good_output(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "key_defect": "3号罐区静电跨接断裂",
        "hazard_type": HazardTypeEnum.UNSAFE_CONDITION,
        "hazard_category": HazardCategoryEnum.LIGHTNING_ANTISTATIC,
        "hazard_level": HazardLevelEnum.GENERAL,
        "major_hazard_basis": GOOD_BASIS,
        "defect_substance": DefectSubstanceEnum.SUBSTANTIVE,
        "defect_substance_reasoning": "跨接断裂导致静电无法导除，存在点火源风险",
        "rectification_suggestion": SimpleNamespace(
            corrective="重新安装静电跨接线并检测导通",
            preventive="将跨接检查纳入月度巡检",
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _view() -> bitable_repo.HazardView:
    fields: dict[str, Any] = {
        "隐患编号": "HZ-20261105-001",
        "隐患描述": "3号罐区静电跨接断裂",
        "检查日期": 1762300800000,
        "检查人员": [{"id": "u1", "name": "张三"}],
        "整改责任人.部门": ["储运部"],
    }
    return bitable_repo.to_view({"record_id": "rec_1", "fields": fields})


def _wire_identify(monkeypatch: pytest.MonkeyPatch, holder: _Holder) -> None:
    """接线 _identify_one 的全部外部边界：DB session / RAG / Bitable / AI / 审计。"""

    async def fake_load_context(session: Any, description: str) -> KnowledgeContext | None:
        holder.loaded_description = description
        return holder.context

    monkeypatch.setattr(ai_analysis, "_load_knowledge_context", fake_load_context)

    import app.core.database as database

    @asynccontextmanager
    async def fake_session_factory() -> Any:
        holder.session_opens += 1
        yield object()

    monkeypatch.setattr(database, "async_session_factory", fake_session_factory)

    async def fake_download_photos(
        client: Any,
        fields: dict[str, Any],
        *,
        record_id: str,
        include_rectification: bool = True,
    ) -> dict[str, list[str]]:
        holder.photo_calls.append(
            {"record_id": record_id, "include_rectification": include_rectification}
        )
        return holder.photo_result

    monkeypatch.setattr(bitable_repo, "download_photos", fake_download_photos)

    def fake_photos_to_data_uris(paths: list[str]) -> list[str]:
        holder.uri_threads.append(threading.current_thread().name)
        holder.uri_paths.append(list(paths))
        return [f"data:image/jpeg;base64,{len(paths)}"] if paths else []

    monkeypatch.setattr(bitable_repo, "photos_to_data_uris", fake_photos_to_data_uris)

    import app.modules.safety.ai_hazard_identification as package

    class FakeIdentifier:
        def __init__(
            self,
            ai_service: Any,
            plugin_config: Any = None,
            knowledge_context: str | None = None,
        ) -> None:
            self.ai_service = ai_service
            self.config = plugin_config
            self.knowledge_context = knowledge_context
            holder.plugins.append(self)

        async def identify(self, input_data: Any) -> Any:
            holder.inputs.append(input_data)
            return holder.output

    monkeypatch.setattr(package, "AIHazardIdentifier", FakeIdentifier)

    from app.modules.safety.service import config as service_config

    def fake_get_ai_service(config_type: str) -> _FakeAIService:
        holder.service_types.append(config_type)
        if config_type not in holder.services:
            holder.services[config_type] = _FakeAIService(config_type)
        return holder.services[config_type]

    monkeypatch.setattr(
        service_config, "get_ai_service", fake_get_ai_service, raising=False
    )

    import app.modules.safety.ai_audit as ai_audit

    @contextmanager
    def fake_audit_scope(**kwargs: Any) -> Any:
        holder.audit_scopes.append(kwargs)
        yield SimpleNamespace(**kwargs)

    monkeypatch.setattr(ai_audit, "ai_audit_scope", fake_audit_scope)


class TestIdentifyOneRagPrecheck:
    async def test_none_context_raises_before_ai_and_download(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        holder.context = None
        _wire_identify(monkeypatch, holder)

        with pytest.raises(QualityGateError) as exc_info:
            await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert exc_info.value.category == "retrieval_degraded"
        assert holder.service_types == []  # 未创建 AI 客户端
        assert holder.plugins == []  # 未进入插件
        assert holder.photo_calls == []  # 未下载附件
        assert holder.audit_scopes == []  # 未进入审计作用域

    async def test_degraded_context_raises_before_ai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        holder.context = KnowledgeContext(
            chunks=[object()],  # type: ignore[list-item]
            degradation="text_only",
            markdown="x",
        )
        _wire_identify(monkeypatch, holder)

        with pytest.raises(QualityGateError) as exc_info:
            await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert exc_info.value.category == "retrieval_degraded"
        assert holder.service_types == []
        assert holder.photo_calls == []

    async def test_zero_chunks_raises_before_ai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        holder.context = KnowledgeContext(chunks=[], degradation="ragplus", markdown="")
        _wire_identify(monkeypatch, holder)

        with pytest.raises(QualityGateError) as exc_info:
            await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert exc_info.value.category == "no_chunks"
        assert holder.service_types == []
        assert holder.photo_calls == []


class TestIdentifyOneOutputGate:
    async def test_placeholder_basis_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        holder.output = _good_output(
            major_hazard_basis="知识库中无相应条文，待人工补充"
        )
        _wire_identify(monkeypatch, holder)

        with pytest.raises(QualityGateError) as exc_info:
            await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert exc_info.value.category == "placeholder_basis"

    async def test_empty_basis_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _Holder()
        holder.output = _good_output(major_hazard_basis="")
        _wire_identify(monkeypatch, holder)

        with pytest.raises(QualityGateError) as exc_info:
            await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert exc_info.value.category == "empty_basis"

    async def test_no_citation_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _Holder()
        holder.output = _good_output(major_hazard_basis="现场存在杂物堆放，需及时清理")
        _wire_identify(monkeypatch, holder)

        with pytest.raises(QualityGateError) as exc_info:
            await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert exc_info.value.category == "no_citation"


class TestIdentifyOneHappyPath:
    async def test_returns_writable_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder = _Holder()
        _wire_identify(monkeypatch, holder)

        result = await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert result["hazard_type"] == "unsafe_condition"
        assert result["hazard_level"] == "general"
        assert result["hazard_category"] == "lightning_antistatic"
        assert result["major_hazard_basis"] == GOOD_BASIS
        assert result["key_defect"] == "3号罐区静电跨接断裂"
        assert result["rectification_suggestion"]["corrective"].startswith("重新安装")
        assert result["defect_substance"] == "substantive"

    async def test_only_defect_photos_downloaded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        _wire_identify(monkeypatch, holder)

        await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert len(holder.photo_calls) == 1
        assert holder.photo_calls[0]["include_rectification"] is False
        assert holder.photo_calls[0]["record_id"] == "rec_1"

    async def test_photo_encoding_runs_off_event_loop_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        _wire_identify(monkeypatch, holder)

        await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert holder.uri_threads
        assert holder.uri_threads[0] != threading.main_thread().name

    async def test_strict_mode_and_knowledge_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        _wire_identify(monkeypatch, holder)

        await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        plugin = holder.plugins[0]
        assert plugin.config.strict_mode is True
        assert plugin.config.enable_vision is True
        assert plugin.config.enable_knowledge is True
        assert plugin.knowledge_context is not None
        assert "危险化学品安全管理条例" in plugin.knowledge_context
        assert holder.inputs[0].defect_photos == ["data:image/jpeg;base64,1"]

    async def test_ai_client_singleton_not_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        _wire_identify(monkeypatch, holder)

        await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert holder.service_types == ["vision"]
        assert holder.services["vision"].closed is False

    async def test_text_service_when_no_photos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        holder.photo_result = {"defect": [], "rectification": []}
        _wire_identify(monkeypatch, holder)

        await ai_analysis._identify_one(object(), _view(), round_id="R-1")

        assert holder.service_types == ["text"]
        assert holder.plugins[0].config.enable_vision is False
        assert holder.plugins[0].config.strict_mode is True

    async def test_round_id_written_to_audit_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        holder = _Holder()
        _wire_identify(monkeypatch, holder)

        await ai_analysis._identify_one(object(), _view(), round_id="20261105120000-abcd")

        assert len(holder.audit_scopes) == 1
        scope = holder.audit_scopes[0]
        assert scope["scenario"] == "hazard_identification"
        assert scope["extra"]["round_id"] == "20261105120000-abcd"
        assert scope["extra"]["bitable_record_id"] == "rec_1"
        assert scope["extra"]["source"] == "bitable_direct"


# ═══════════════════════════════════════════════════════════════
# bitable_repo.download_photos：整改后图开关（A6①）
# ═══════════════════════════════════════════════════════════════


class _FakeAttachmentClient:
    def __init__(self) -> None:
        self.table_id = "tbl_test"
        self.downloaded_urls: list[str] = []

    async def download_attachment_from_url(self, url: str) -> bytes:
        self.downloaded_urls.append(url)
        return b"image-bytes"

    async def get_field_id_by_name(self, name: str) -> str:
        return "fld_test"

    async def download_attachment(self, file_token: str, extra: str | None = None) -> bytes:
        return b"image-bytes"


def _attachment_fields() -> dict[str, Any]:
    return {
        "缺陷图片": [
            {
                "file_token": "tok_defect",
                "name": "defect.jpg",
                "url": "https://example.test/defect.jpg",
                "type": "image/jpeg",
            }
        ],
        "整改后图片": [
            {
                "file_token": "tok_rectify",
                "name": "rectify.jpg",
                "url": "https://example.test/rectify.jpg",
                "type": "image/jpeg",
            }
        ],
    }


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import app.modules.safety.attachment_store as attachment_store

    stored: list[str] = []

    def fake_store_bytes(bucket: str, name: str, data: bytes, **kwargs: Any) -> str:
        stored.append(name)
        return f"/stored/{name}"

    monkeypatch.setattr(attachment_store, "store_bytes", fake_store_bytes)
    return stored


class TestDownloadPhotosRectificationFlag:
    async def test_include_rectification_false_skips_rectification(
        self, fake_store: list[str]
    ) -> None:
        client = _FakeAttachmentClient()

        saved = await bitable_repo.download_photos(
            client, _attachment_fields(), record_id="rec-1", include_rectification=False
        )

        assert saved["rectification"] == []
        assert len(saved["defect"]) == 1
        assert client.downloaded_urls == ["https://example.test/defect.jpg"]

    async def test_default_downloads_both(self, fake_store: list[str]) -> None:
        client = _FakeAttachmentClient()

        saved = await bitable_repo.download_photos(
            client, _attachment_fields(), record_id="rec-1"
        )

        assert len(saved["defect"]) == 1
        assert len(saved["rectification"]) == 1
        assert set(client.downloaded_urls) == {
            "https://example.test/defect.jpg",
            "https://example.test/rectify.jpg",
        }


# ═══════════════════════════════════════════════════════════════
# run_ai_analysis_round：失败不写回 / deferred / 告警收敛（S4 接缝）
# ═══════════════════════════════════════════════════════════════


class _FakeLedger:
    """ai_analysis.failure_ledger 替身（记录调用、可控返回）。"""

    def __init__(self, *, retry: bool = True) -> None:
        self.retry = retry
        self.round_seq = 7
        self.states: list[failure_ledger.FailureState] = []
        self.failure_calls: list[tuple[str, int, str, str]] = []
        self.success_ids: list[str] = []
        self.dead_letters: list[dict[str, Any]] = []
        self.list_calls = 0
        self.should_retry_calls: list[tuple[str, int]] = []
        self.infra_alert_results: list[bool] = []
        self.infra_alert_calls: list[tuple[int, int]] = []

    async def next_round_seq(self) -> int:
        return self.round_seq

    async def should_retry(self, record_id: str, round_seq: int) -> bool:
        self.should_retry_calls.append((record_id, round_seq))
        return self.retry

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
        self.list_calls += 1
        return list(self.dead_letters)

    async def should_emit_infra_alert(
        self, round_seq: int, interval_seconds: int = 1800
    ) -> bool:
        self.infra_alert_calls.append((round_seq, interval_seconds))
        if self.infra_alert_results:
            return self.infra_alert_results.pop(0)
        return True


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


class _RoundEnv:
    def __init__(self) -> None:
        self.ledger = _FakeLedger()
        self.written: list[tuple[str, dict[str, Any]]] = []
        self.identify_calls: list[tuple[str, str | None]] = []
        self.identify_impl: Any = None
        self.write_ok = True
        self.notify_failures: list[dict[str, Any]] = []
        self.notify_admin: list[tuple[str, str]] = []


async def _wire_round(
    monkeypatch: pytest.MonkeyPatch,
    env: _RoundEnv,
    *,
    records: list[dict[str, Any]],
) -> None:
    async def fake_search(client: Any, *, limit: int | None = None) -> list[dict[str, Any]]:
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
    ) -> bool:
        env.written.append((record_id, output))
        return env.write_ok

    monkeypatch.setattr(bitable_repo, "write_ai_analysis", fake_write_ai_analysis)
    monkeypatch.setattr(ai_analysis, "_supervision_label", lambda view: None)

    async def fake_identify_one(
        client: Any, view: Any, *, round_id: str | None = None
    ) -> dict[str, Any]:
        env.identify_calls.append((view.record_id, round_id))
        return await env.identify_impl(view)

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


def _make_env() -> _RoundEnv:
    return _RoundEnv()


class TestRunRoundQualityGate:
    async def test_gate_failure_not_written_and_category_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()

        async def fail_identify(view: Any) -> dict[str, Any]:
            raise QualityGateError("placeholder_basis", "命中占位文案")

        env.identify_impl = fail_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 1)

        result = await ai_analysis.run_ai_analysis_round(notify=True)

        assert result.total == 1
        assert result.failed == 1
        assert result.succeeded == 0
        assert env.written == []  # 失败不写任何字段
        assert result.failures[0]["record_id"] == "rec-1"
        assert result.failures[0]["category"] == "placeholder_basis"
        assert env.ledger.failure_calls[0][2] == "placeholder_basis"
        # 新增失败告警：文案含分类计数
        assert len(env.notify_failures) == 1
        assert "分类计数" in env.notify_failures[0]["error"]
        assert "placeholder_basis=1" in env.notify_failures[0]["error"]

    async def test_rag_precheck_failure_round_does_not_call_ai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()

        async def fail_identify(view: Any) -> dict[str, Any]:
            raise QualityGateError("retrieval_degraded", "RAG 降级")

        env.identify_impl = fail_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.failed == 1
        assert result.failures[0]["category"] == "retrieval_degraded"
        assert env.written == []

    async def test_writeback_false_is_writeback_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()
        env.write_ok = False

        async def ok_identify(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = ok_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.failed == 1
        assert result.failures[0]["category"] == "writeback_error"
        assert env.ledger.failure_calls[0][2] == "writeback_error"

    async def test_success_writes_and_records_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()

        async def ok_identify(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = ok_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.succeeded == 1
        assert result.failed == 0
        assert len(env.written) == 1
        assert env.written[0][0] == "rec-1"
        assert env.written[0][1]["advice_text"].startswith("【整改措施】")
        assert env.ledger.success_ids == ["rec-1"]


class TestRunRoundFailureGovernance:
    async def test_deferred_when_backoff_not_due(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()
        env.ledger.retry = False

        async def ok_identify(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = ok_identify
        await _wire_round(
            monkeypatch, env, records=[_raw_record("rec-1"), _raw_record("rec-2")]
        )

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.deferred == 2
        assert result.failed == 0
        assert result.succeeded == 0
        assert env.identify_calls == []  # 未到重试点不调 AI
        assert env.written == []
        assert env.ledger.should_retry_calls == [("rec-1", 7), ("rec-2", 7)]

    async def test_round_id_consistent_within_round_and_changes_between_rounds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()

        async def ok_identify(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = ok_identify
        await _wire_round(
            monkeypatch, env, records=[_raw_record("rec-1"), _raw_record("rec-2")]
        )

        await ai_analysis.run_ai_analysis_round(notify=False)
        first_ids = {round_id for _, round_id in env.identify_calls}
        assert len(first_ids) == 1
        first_round_id = next(iter(first_ids))
        assert first_round_id

        env.identify_calls.clear()
        await ai_analysis.run_ai_analysis_round(notify=False)
        second_ids = {round_id for _, round_id in env.identify_calls}
        assert len(second_ids) == 1
        assert next(iter(second_ids)) != first_round_id

    async def test_alerts_only_on_new_failures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 1)

        async def fail_identify(view: Any) -> dict[str, Any]:
            raise QualityGateError("no_citation", "无引用")

        env.identify_impl = fail_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        # 第 1 轮：首次失败 → 告警
        await ai_analysis.run_ai_analysis_round(notify=True)
        assert len(env.notify_failures) == 1

        # 第 2 轮：同一记录再次失败但已是第 2 次 → 不再告警
        env.ledger.states = [
            failure_ledger.FailureState(
                record_id="rec-1",
                attempts=2,
                next_round=env.ledger.round_seq + 3,
                category="no_citation",
                reason="无引用",
                dead=False,
                dead_at=None,
                is_new=False,
            )
        ]
        await ai_analysis.run_ai_analysis_round(notify=True)
        assert len(env.notify_failures) == 1

    async def test_new_dead_letter_alerts_once_and_dead_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()

        async def fail_identify(view: Any) -> dict[str, Any]:
            raise QualityGateError("api_error", "AI 接口超时")

        env.identify_impl = fail_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])
        env.ledger.states = [
            failure_ledger.FailureState(
                record_id="rec-1",
                attempts=failure_ledger.MAX_ATTEMPTS,
                next_round=None,
                category="api_error",
                reason="AI 接口超时",
                dead=True,
                dead_at=1762300800.0,
                is_new=False,
            )
        ]

        await ai_analysis.run_ai_analysis_round(notify=True)
        assert len(env.notify_admin) == 1
        title, content = env.notify_admin[0]
        assert "死信" in title
        assert "rec-1" in content

        # 死信后不再重试：不调 AI、不再触发死信告警
        env.ledger.retry = False
        env.identify_calls.clear()
        await ai_analysis.run_ai_analysis_round(notify=True)
        assert env.identify_calls == []
        assert len(env.notify_admin) == 1

    async def test_dead_letter_query_logged_every_round(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()
        logged: list[str] = []

        class _CapturingLogger:
            def __getattr__(self, name: str) -> Any:
                def _log(*args: Any, **kwargs: Any) -> None:
                    if args:
                        try:
                            logged.append(str(args[0]) % args[1:] if args[1:] else str(args[0]))
                        except (TypeError, ValueError):
                            logged.append(str(args[0]))
                return _log

        monkeypatch.setattr(ai_analysis, "logger", _CapturingLogger())
        env.ledger.dead_letters = [
            {
                "record_id": "rec-dead",
                "attempts": 5,
                "category": "no_citation",
                "reason": "无引用",
                "last_round": 3,
                "dead_at": 1762300800.0,
            }
        ]

        async def ok_identify(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = ok_identify
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        await ai_analysis.run_ai_analysis_round(notify=False)

        assert env.ledger.list_calls == 1  # 每轮结束查询死信入口
        assert any("累计死信" in message for message in logged)

    async def test_deferred_does_not_count_as_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()
        env.ledger.retry = False
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.deferred == 1
        assert result.failures == []
        assert env.ledger.failure_calls == []


# ═══════════════════════════════════════════════════════════════
# 基础设施失败（RAG 降级/零召回）：不累计 attempts / 不进死信 / 去重告警
# ═══════════════════════════════════════════════════════════════


class TestRunRoundInfraFailures:
    async def test_five_rounds_rag_degraded_no_attempts_then_recovers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连续 5 轮 RAG 降级：attempts 不增长、无死信；第 6 轮恢复 → 正常处理。"""
        env = _make_env()

        async def rag_down(view: Any) -> dict[str, Any]:
            raise QualityGateError("retrieval_degraded", "RAG 检索降级")

        env.identify_impl = rag_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        for _ in range(5):
            result = await ai_analysis.run_ai_analysis_round(notify=False)
            assert result.failed == 1
            assert result.failures[0]["category"] == "retrieval_degraded"

        # 基础设施失败不累计 attempts、不进死信、不触发失败账本写入
        assert env.ledger.failure_calls == []
        assert env.ledger.success_ids == []
        assert env.ledger.dead_letters == []
        assert len(env.ledger.should_retry_calls) == 5  # 每轮仍重试（无退避）
        assert env.written == []

        # 第 6 轮 RAG 恢复正常 → 记录被处理并写回（说明未被退避/死信卡住）
        async def ok_identify(view: Any) -> dict[str, Any]:
            return _identified_output()

        env.identify_impl = ok_identify
        recovered = await ai_analysis.run_ai_analysis_round(notify=False)

        assert recovered.succeeded == 1
        assert recovered.failed == 0
        assert len(env.identify_calls) == 6
        assert len(env.written) == 1
        assert env.ledger.success_ids == ["rec-1"]

    async def test_infra_alert_dedup_by_redis_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RAG 失败告警：达到阈值且去重助手放行才通知，同窗口内只报一次。"""
        env = _make_env()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 1)
        env.ledger.infra_alert_results = [True, False]  # 第 1 轮放行、第 2 轮窗口内去重

        async def rag_down(view: Any) -> dict[str, Any]:
            raise QualityGateError("no_chunks", "RAG 零召回")

        env.identify_impl = rag_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        await ai_analysis.run_ai_analysis_round(notify=True)
        await ai_analysis.run_ai_analysis_round(notify=True)

        assert len(env.notify_failures) == 1
        assert "RAG 基础设施失败" in env.notify_failures[0]["error"]
        assert "no_chunks=1" in env.notify_failures[0]["error"]
        assert env.ledger.infra_alert_calls == [(7, 1800), (7, 1800)]
        # 不进失败账本
        assert env.ledger.failure_calls == []

    async def test_infra_alert_below_threshold_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = _make_env()
        monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 10)

        async def rag_down(view: Any) -> dict[str, Any]:
            raise QualityGateError("retrieval_degraded", "RAG 检索降级")

        env.identify_impl = rag_down
        await _wire_round(monkeypatch, env, records=[_raw_record("rec-1")])

        await ai_analysis.run_ai_analysis_round(notify=True)

        assert env.notify_failures == []
        assert env.ledger.infra_alert_calls == []  # 未达阈值不查去重


# ═══════════════════════════════════════════════════════════════
# 失败分类（A7）
# ═══════════════════════════════════════════════════════════════


class TestFailureCategories:
    def test_quality_gate_error_uses_its_category(self) -> None:
        assert (
            ai_analysis._categorize_failure(
                QualityGateError("placeholder_basis", "占位")
            )
            == "placeholder_basis"
        )

    def test_ai_output_error_is_json_invalid(self) -> None:
        from app.platform.integrations.ai.client import AIOutputError

        assert ai_analysis._categorize_failure(AIOutputError("bad json")) == "json_invalid"

    def test_wrapped_ai_output_error_is_json_invalid(self) -> None:
        from app.modules.safety.ai_hazard_identification import IdentificationError
        from app.platform.integrations.ai.client import AIOutputError

        try:
            try:
                raise AIOutputError("bad json")
            except AIOutputError as inner:
                raise IdentificationError("AI 文本分析失败: bad json") from inner
        except IdentificationError as exc:
            assert ai_analysis._categorize_failure(exc) == "json_invalid"

    def test_validation_error_is_validation_failed(self) -> None:
        from app.modules.safety.ai_hazard_identification import IdentificationError

        error = IdentificationError("AI 输出验证失败: 判定依据过短")
        assert ai_analysis._categorize_failure(error) == "validation_failed"

    def test_other_exception_is_api_error(self) -> None:
        assert ai_analysis._categorize_failure(RuntimeError("timeout")) == "api_error"

