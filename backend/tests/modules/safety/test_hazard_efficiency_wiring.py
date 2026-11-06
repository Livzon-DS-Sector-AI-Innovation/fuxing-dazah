"""T08 效率止血接线测试 —— A6①④（ticket 08）。

覆盖 ticket 08 验收：
- `_identify_one` 使用 `service.config.get_ai_service` 进程级单例且**不 close**：
  真实 ``get_ai_service`` + fake ``AuditedAIService`` 计数 → 两条记录只创建 1 个
  AI 客户端、0 次 close；
- `photos_to_data_uris` 走 ``asyncio.to_thread``：慢速同步编码假件（sleep 0.2s）
  期间并发心跳持续推进（事件循环未被阻塞）；
- `store_bytes` 走 ``asyncio.to_thread``：慢速同步落盘假件期间心跳持续推进；
- ① 只下缺陷图：含整改后图的记录只下载缺陷图（fake client 计数，基线 2 → 实际 1）。

全部 fake：不连真实网络 / DB / Redis / Bitable / 文件系统 / AI。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import AsyncIterator, Iterator
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
from app.modules.safety.service.hazard_direct import ai_analysis, bitable_repo

GOOD_BASIS = "《危险化学品安全管理条例》第二十条（GB 30871-2022 第5.1条）"


@pytest.fixture(autouse=True)
def _ragplus_search_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试默认按 ragplus 内核开启（quality_gate 健康集合与开关联动）。"""
    import app.modules.safety.knowledge.ragplus_client as ragplus_client

    monkeypatch.setattr(ragplus_client, "ragplus_search_enabled", lambda: True)


# ═══════════════════════════════════════════════════════════════
# 公共 fake / 辅助
# ═══════════════════════════════════════════════════════════════


def _healthy_context() -> KnowledgeContext:
    # C2：chunk 需为真实可匹配形态（GOOD_BASIS 的法规名/条号/标准号可命中）
    healthy_chunks: list[Any] = [
        SimpleNamespace(
            chunk_id="chunk-1",
            source_doc="危险化学品安全管理条例",
            source_article="第二十条",
            chunk_text=(
                "第二十条 生产、储存危险化学品的单位，应当具备下列条件："
                "有符合国家标准、行业标准的经营场所……GB 30871-2022 第5.1条"
            ),
        )
    ]
    return KnowledgeContext(
        chunks=healthy_chunks,
        degradation="ragplus",
        markdown="【法规】《危险化学品安全管理条例》第二十条……",
    )


def _good_output() -> SimpleNamespace:
    return SimpleNamespace(
        key_defect="3号罐区静电跨接断裂",
        hazard_type=HazardTypeEnum.UNSAFE_CONDITION,
        hazard_category=HazardCategoryEnum.LIGHTNING_ANTISTATIC,
        hazard_level=HazardLevelEnum.GENERAL,
        major_hazard_basis=GOOD_BASIS,
        defect_substance=DefectSubstanceEnum.SUBSTANTIVE,
        defect_substance_reasoning="跨接断裂导致静电无法导除，存在点火源风险",
        rectification_suggestion=SimpleNamespace(
            corrective="重新安装静电跨接线并检测导通",
            preventive="将跨接检查纳入月度巡检",
        ),
    )


class _Env:
    """一次测试内收集 fake 调用的容器。"""

    def __init__(self) -> None:
        self.context: KnowledgeContext | None = _healthy_context()
        self.output: Any = _good_output()
        self.photos: dict[str, list[str]] = {
            "defect": ["/tmp/a.jpg"],
            "rectification": [],
        }
        self.uris: list[str] = ["data:image/jpeg;base64,1"]
        self.description: str | None = None
        self.download_calls: list[dict[str, Any]] = []
        self.uri_paths: list[list[str]] = []
        self.uri_threads: list[str] = []
        self.plugins: list[Any] = []
        self.inputs: list[Any] = []
        self.audit_scopes: list[dict[str, Any]] = []
        self.service_types: list[str] = []
        self.services: dict[str, _FakeService] = {}


class _FakeService:
    def __init__(self, config_type: str) -> None:
        self.config_type = config_type
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


@pytest.fixture(autouse=True)
def clean_ai_service_cache() -> Iterator[None]:
    """进程级单例缓存：本文件用例前后清空，避免跨用例串味。"""
    from app.modules.safety.service import config as service_config

    service_config._ai_service_cache.clear()
    yield
    service_config._ai_service_cache.clear()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    holder = _Env()

    async def fake_load_context(
        session: Any, description: str
    ) -> tuple[KnowledgeContext | None, Any]:
        holder.description = description
        return holder.context, None

    monkeypatch.setattr(ai_analysis, "_load_knowledge_context", fake_load_context)

    import app.core.database as database

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[Any]:
        yield object()

    monkeypatch.setattr(database, "async_session_factory", fake_session_factory)

    import app.modules.safety.ai_hazard_identification as package

    class FakeIdentifier:
        def __init__(
            self,
            ai_service: Any,
            plugin_config: Any = None,
            knowledge_context: str | None = None,
            citation_evidence: Any = None,
            **kwargs: Any,
        ) -> None:
            self.ai_service = ai_service
            self.config = plugin_config
            self.knowledge_context = knowledge_context
            self.citation_evidence = citation_evidence
            self.last_citation_report = None
            holder.plugins.append(self)

        async def identify(self, input_data: Any) -> Any:
            holder.inputs.append(input_data)
            return holder.output

    monkeypatch.setattr(package, "AIHazardIdentifier", FakeIdentifier)

    import app.modules.safety.ai_audit as ai_audit

    @contextmanager
    def fake_audit_scope(**kwargs: Any) -> Any:
        holder.audit_scopes.append(kwargs)
        yield SimpleNamespace(**kwargs)

    monkeypatch.setattr(ai_audit, "ai_audit_scope", fake_audit_scope)
    return holder


def _patch_fast_download(monkeypatch: pytest.MonkeyPatch, holder: _Env) -> None:
    """fast fake：下载 + 图片编码（不真读文件）。"""

    async def fake_download_photos(
        client: Any,
        fields: dict[str, Any],
        *,
        record_id: str,
        include_rectification: bool = True,
    ) -> dict[str, list[str]]:
        holder.download_calls.append(
            {"record_id": record_id, "include_rectification": include_rectification}
        )
        return holder.photos

    monkeypatch.setattr(bitable_repo, "download_photos", fake_download_photos)

    def fake_photos_to_data_uris(paths: list[str]) -> list[str]:
        holder.uri_paths.append(list(paths))
        holder.uri_threads.append(threading.current_thread().name)
        return holder.uris if paths else []

    monkeypatch.setattr(bitable_repo, "photos_to_data_uris", fake_photos_to_data_uris)


def _patch_fake_ai_service(monkeypatch: pytest.MonkeyPatch, holder: _Env) -> None:
    """fake ``get_ai_service``：同一测试内按 config_type 复用假件，记录调用。"""
    from app.modules.safety.service import config as service_config

    def fake_get_ai_service(config_type: str = "text") -> _FakeService:
        holder.service_types.append(config_type)
        if config_type not in holder.services:
            holder.services[config_type] = _FakeService(config_type)
        return holder.services[config_type]

    monkeypatch.setattr(service_config, "get_ai_service", fake_get_ai_service)


def _view(record_id: str = "rec_1") -> bitable_repo.HazardView:
    fields: dict[str, Any] = {
        "隐患编号": "HZ-20261105-001",
        "隐患描述": "3号罐区静电跨接断裂",
        "检查日期": 1762300800000,
        "检查人员": [{"id": "u1", "name": "张三"}],
        "整改责任人.部门": ["储运部"],
    }
    return bitable_repo.to_view({"record_id": record_id, "fields": fields})


# ═══════════════════════════════════════════════════════════════
# 1. AI 客户端单例：两条记录只创建 1 个、且不 close
# ═══════════════════════════════════════════════════════════════


class _FakeAuditedAIService:
    """替换真实 AuditedAIService（真实 get_ai_service 缓存逻辑照常运行）。"""

    created = 0
    closed = 0

    def __init__(self, **kwargs: Any) -> None:
        type(self).created += 1
        self.kwargs = kwargs
        self.close_calls = 0

    def set_backup(self, **kwargs: Any) -> None:
        self.backup = kwargs

    async def close(self) -> None:
        type(self).closed += 1
        self.close_calls += 1


def _fake_ai_config() -> dict[str, Any]:
    return {
        "text": {
            "api_key": "text-key",
            "base_url": "https://ai.example/v1",
            "model": "text-model",
            "temperature": 0.1,
            "timeout": 120,
            "backup": None,
        },
        "vision": {
            "api_key": "vision-key",
            "base_url": "https://ai.example/v1",
            "model": "vision-model",
            "temperature": 0.1,
            "timeout": 120,
        },
    }


async def test_two_records_share_one_ai_client_and_never_close(
    monkeypatch: pytest.MonkeyPatch, env: _Env
) -> None:
    """真实 get_ai_service + fake AuditedAIService：两条记录 → 1 个客户端、0 次 close。"""
    from app.modules.safety.ai_audit import audited_client
    from app.modules.safety.service import config as service_config

    _patch_fast_download(monkeypatch, env)
    monkeypatch.setattr(audited_client, "AuditedAIService", _FakeAuditedAIService)
    monkeypatch.setattr(service_config, "_get_ai_config", _fake_ai_config)
    service_config._ai_service_cache.clear()
    _FakeAuditedAIService.created = 0
    _FakeAuditedAIService.closed = 0

    first = await ai_analysis._identify_one(object(), _view("rec_1"), round_id="R-1")
    second = await ai_analysis._identify_one(object(), _view("rec_2"), round_id="R-1")

    assert first["major_hazard_basis"] == GOOD_BASIS
    assert second["major_hazard_basis"] == GOOD_BASIS
    assert _FakeAuditedAIService.created == 1  # 两条记录只创建 1 个客户端
    assert _FakeAuditedAIService.closed == 0  # 不再逐条 close
    assert len(env.plugins) == 2
    assert env.plugins[0].ai_service is env.plugins[1].ai_service
    assert env.plugins[0].ai_service.close_calls == 0


# ═══════════════════════════════════════════════════════════════
# 2. to_thread：慢速同步编码期间事件循环不被阻塞
# ═══════════════════════════════════════════════════════════════


async def _run_with_heartbeat(
    coro: Any, *, interval: float = 0.01
) -> tuple[Any, int]:
    """并发心跳运行协程，返回 (协程结果, 心跳次数)。"""
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(interval)
            ticks += 1

    task = asyncio.create_task(heartbeat())
    try:
        result = await coro
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return result, ticks


async def test_slow_photo_encoding_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch, env: _Env
) -> None:
    """photos_to_data_uris 是同步慢编码（sleep 0.2s），必须在线程里跑。"""
    _patch_fake_ai_service(monkeypatch, env)

    async def fake_download_photos(
        client: Any,
        fields: dict[str, Any],
        *,
        record_id: str,
        include_rectification: bool = True,
    ) -> dict[str, list[str]]:
        return {"defect": ["/tmp/a.jpg"], "rectification": []}

    monkeypatch.setattr(bitable_repo, "download_photos", fake_download_photos)

    def slow_photos_to_data_uris(paths: list[str]) -> list[str]:
        time.sleep(0.2)  # 同步阻塞假件
        env.uri_threads.append(threading.current_thread().name)
        return ["data:image/jpeg;base64,1"] if paths else []

    monkeypatch.setattr(bitable_repo, "photos_to_data_uris", slow_photos_to_data_uris)

    _, ticks = await _run_with_heartbeat(
        ai_analysis._identify_one(object(), _view("rec_1"), round_id="R-1")
    )

    # 0.2s 阻塞若发生在事件循环线程，心跳最多 0~1 次；在线程里则约 20 次
    assert ticks >= 8
    assert env.uri_threads
    assert env.uri_threads[0] != threading.main_thread().name


# ═══════════════════════════════════════════════════════════════
# 3. to_thread：慢速同步落盘期间事件循环不被阻塞
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

    async def download_attachment(
        self, file_token: str, extra: str | None = None
    ) -> bytes:
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


async def test_slow_store_bytes_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """store_bytes 是同步落盘（sleep 0.2s），必须在线程里跑。"""
    import app.modules.safety.attachment_store as attachment_store

    stored: list[str] = []

    def slow_store_bytes(
        bucket: str, name: str, data: bytes, **kwargs: Any
    ) -> str:
        time.sleep(0.2)  # 同步阻塞假件
        stored.append(name)
        return f"/stored/{name}"

    monkeypatch.setattr(attachment_store, "store_bytes", slow_store_bytes)
    client = _FakeAttachmentClient()

    async def run() -> dict[str, list[str]]:
        return await bitable_repo.download_photos(
            client, _attachment_fields(), record_id="rec-1", include_rectification=False
        )

    saved, ticks = await _run_with_heartbeat(run())

    assert ticks >= 8
    assert len(saved["defect"]) == 1
    assert saved["rectification"] == []
    assert stored and stored[0].endswith("defect.jpg")


# ═══════════════════════════════════════════════════════════════
# 4. ① 只下缺陷图：含整改后图的记录只下载缺陷图（-44% 口径）
# ═══════════════════════════════════════════════════════════════


async def test_identify_one_downloads_only_defect_photo(
    monkeypatch: pytest.MonkeyPatch, env: _Env
) -> None:
    """真实 download_photos：记录同时有缺陷图 + 整改后图 → ① 只下载 1 个（基线 2）。"""
    import app.modules.safety.attachment_store as attachment_store

    _patch_fake_ai_service(monkeypatch, env)
    monkeypatch.setattr(attachment_store, "store_bytes", lambda *a, **k: f"/stored/{a[1]}")

    def fake_photos_to_data_uris(paths: list[str]) -> list[str]:
        env.uri_paths.append(list(paths))
        return ["data:image/jpeg;base64,1"] if paths else []

    monkeypatch.setattr(bitable_repo, "photos_to_data_uris", fake_photos_to_data_uris)

    fields = _attachment_fields()
    fields.update(
        {
            "隐患编号": "HZ-20261105-001",
            "隐患描述": "3号罐区静电跨接断裂",
            "检查日期": 1762300800000,
            "检查人员": [{"id": "u1", "name": "张三"}],
            "整改责任人.部门": ["储运部"],
        }
    )
    view = bitable_repo.to_view({"record_id": "rec_1", "fields": fields})
    client = _FakeAttachmentClient()

    await ai_analysis._identify_one(client, view, round_id="R-1")

    # 基线（① 旧行为）会下载缺陷图 + 整改后图 = 2 次；现在只下载缺陷图 = 1 次
    assert client.downloaded_urls == ["https://example.test/defect.jpg"]
    assert len(client.downloaded_urls) == 1
    assert all("rectify" not in url for url in client.downloaded_urls)
    assert len(env.uri_paths[0]) == 1
    assert env.uri_paths[0][0].endswith("defect.jpg")
    assert env.plugins[0].config.enable_vision is True


# ═══════════════════════════════════════════════════════════════
# 5. 回归：② 默认行为不变（download_photos 默认仍含整改后图）
# ═══════════════════════════════════════════════════════════════


async def test_download_photos_default_still_includes_rectification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.safety.attachment_store as attachment_store

    monkeypatch.setattr(attachment_store, "store_bytes", lambda *a, **k: f"/stored/{a[1]}")
    client = _FakeAttachmentClient()

    saved = await bitable_repo.download_photos(
        client, _attachment_fields(), record_id="rec-1"
    )

    assert len(saved["defect"]) == 1
    assert len(saved["rectification"]) == 1  # ② 初审依赖整改后图，默认行为不变
    assert len(client.downloaded_urls) == 2


# ═══════════════════════════════════════════════════════════════
# 6. 回归：run_ai_analysis_round 传 round_id 给 _identify_one（T05 接线保持）
# ═══════════════════════════════════════════════════════════════


async def test_round_passes_round_id_to_identify_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.hazard_direct import (
        config as hazard_config,
    )
    from app.modules.safety.service.hazard_direct import (
        failure_ledger,
    )

    captured: list[str | None] = []

    async def fake_identify_one(
        client: Any, view: Any, *, round_id: str | None = None
    ) -> dict[str, Any]:
        captured.append(round_id)
        return {"major_hazard_basis": GOOD_BASIS}

    monkeypatch.setattr(ai_analysis, "_identify_one", fake_identify_one)
    def _raw(record_id: str, hazard_no: str) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "fields": {
                "隐患编号": hazard_no,
                "隐患描述": "3号罐区静电跨接断裂",
                "检查日期": 1762300800000,
                "检查人员": [{"id": "u1", "name": "张三"}],
                "整改责任人.部门": ["储运部"],
            },
        }

    monkeypatch.setattr(
        bitable_repo,
        "search_pending_ai",
        lambda client, *, limit=None, keep=None: _async_list(
            [_raw("rec_1", "HZ-20261105-001"), _raw("rec_2", "HZ-20261105-002")]
        ),
    )

    @asynccontextmanager
    async def fake_record_lock(record_id: str) -> AsyncIterator[bool]:
        yield True

    monkeypatch.setattr(bitable_repo, "record_lock", fake_record_lock)

    async def fake_write(client: Any, record_id: str, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(bitable_repo, "write_ai_analysis", fake_write)
    monkeypatch.setattr(ai_analysis, "_supervision_label", lambda view: None)
    monkeypatch.setattr(ai_analysis, "_build_advice_text", lambda output: "")

    class _Ledger:
        async def next_round_seq(self) -> int:
            return 1

        async def should_retry(self, record_id: str, round_seq: int) -> bool:
            return True

        async def record_failure(self, *args: Any, **kwargs: Any) -> Any:
            return failure_ledger.FailureState(
                record_id="x", attempts=1, next_round=2, category="api_error",
                reason="", dead=False, dead_at=None, is_new=False,
            )

        async def record_success(self, record_id: str) -> None:
            return None

        async def list_dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(ai_analysis, "failure_ledger", _Ledger())
    monkeypatch.setattr(hazard_config, "alert_min_failures", lambda: 10)

    import app.modules.safety.feishu.bitable_client as bitable_client

    monkeypatch.setattr(
        bitable_client, "SafetyBitableClient", lambda *a, **k: object()
    )

    await ai_analysis.run_ai_analysis_round(notify=False)

    assert len(captured) == 2
    assert captured[0] is not None
    assert captured[0] == captured[1]


async def _async_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items


# ═══════════════════════════════════════════════════════════════
# 4. ②初审 to_thread：慢速同步图片编码期间事件循环不被阻塞（P0-B / F12）
# ═══════════════════════════════════════════════════════════════


def _review_fake_output() -> SimpleNamespace:
    level = SimpleNamespace(value="medium")
    return SimpleNamespace(
        defect_reassessment="整改后缺陷已消除",
        defect_reassessment_level="medium",
        photo_match_analysis="照片一致",
        photo_match_level=level,
        measure_quality_assessment="措施有效",
        measure_quality_level=level,
        standard_compliance="符合要求",
        standard_compliance_level=level,
        review_conclusion=SimpleNamespace(value="已通过"),
        review_comments="整改到位",
        confidence=0.9,
        reasoning="依据充分",
    )


async def test_review_photo_encoding_runs_in_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_review_one 的 photos_to_data_uris 是同步慢编码，必须在线程里跑（F12）。"""
    from app.modules.safety.service.hazard_direct import review

    threads: list[str] = []

    async def fake_download_photos(
        client: Any,
        fields: dict[str, Any],
        *,
        record_id: str,
        include_rectification: bool = True,
    ) -> dict[str, list[str]]:
        return {
            "defect": ["/tmp/a.jpg"],
            "rectification": ["/tmp/b.jpg"] if include_rectification else [],
        }

    def slow_photos_to_data_uris(paths: list[str]) -> list[str]:
        time.sleep(0.2)  # 同步阻塞假件
        threads.append(threading.current_thread().name)
        return ["data:image/jpeg;base64,1"] if paths else []

    monkeypatch.setattr(bitable_repo, "download_photos", fake_download_photos)
    monkeypatch.setattr(bitable_repo, "photos_to_data_uris", slow_photos_to_data_uris)

    async def fake_load_knowledge(session: Any, description: str) -> None:
        return None

    monkeypatch.setattr(review, "_load_knowledge_context", fake_load_knowledge)

    class _FakeAIService:
        def __init__(self, config_type: str) -> None:
            self.config_type = config_type

        async def close(self) -> None:
            return None

    import app.modules.safety.service.config as service_config

    monkeypatch.setattr(
        service_config, "create_ai_service", lambda config_type="text": _FakeAIService(config_type)
    )

    class _FakeReviewer:
        def __init__(self, ai_service: Any, plugin_config: Any, knowledge_context: Any = None) -> None:
            self.ai_service = ai_service

        async def review(self, input_data: Any) -> SimpleNamespace:
            return _review_fake_output()

    import app.modules.safety.ai_rectification_review as rectification_review

    monkeypatch.setattr(rectification_review, "AIRectificationReviewer", _FakeReviewer)

    view = bitable_repo.HazardView(
        record_id="rec1", description="隐患描述", rectify_reply="已整改"
    )
    _, ticks = await _run_with_heartbeat(review._review_one(object(), view))

    # 2 次 0.2s 同步阻塞若在事件循环线程：心跳最多 0~1 次；在线程里约 40 次。
    assert ticks >= 8
    assert len(threads) == 2
    assert threads[0] != threading.main_thread().name
