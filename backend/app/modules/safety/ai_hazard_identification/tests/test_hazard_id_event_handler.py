"""Ticket 06 — 危险源辨识 Bitable 事件处理器薄包装测试。

覆盖：app_token/table_id 过滤（防串表）、状态级去重（同节点重复投递跳过、
节点推进不误去重）、记录级互斥（120s）、事件→服务→回写→镜像全链路、
record_deleted → 镜像软删除、Redis 不可用降级。
全部用 fake client / fake service / fake redis / fake mirror 注入，无 DB/无网络。
"""

from app.modules.safety.bitable_config.registry import get_domain
from app.modules.safety.feishu.hazard_identification_bitable_handler import (
    _handle_delete,
    _handle_upsert,
    _node_of,
    _review_fingerprint,
    advance_bitable_record,
    handle_hazard_id_record_changed,
)

# 测试用目标表连接（registry 默认值 = handler 配置中心 fallback 值）
_HAZARD_ID_DEFAULT = (
    get_domain("hazard_id").get_kind("identification").default_connection
)
HAZARD_ID_APP_TOKEN = _HAZARD_ID_DEFAULT.app_token
HAZARD_ID_TABLE_ID = _HAZARD_ID_DEFAULT.table_id

_RECORD_ID = "rec1234567890"

# 一条「待AI危险源辨识」节点（脚本2 就绪）的记录
_READY_FIELDS = {
    "AI流程节点进度": "待AI危险源辨识",
    "岗位（人工）": "发酵车间主操",
    "生产步骤（人工）": "发酵罐灭菌操作",
    "具体作业活动（AI）": "人工投料",
    "设备设施（AI）": "发酵罐",
    "原辅料（AI）": "培养基",
}

# 该记录无审核字段 → 审核指纹为空串拼接（8 个空段）；去重键 = record_id:节点:指纹
_FP = _review_fingerprint(_READY_FIELDS)


def _event(record_id: str = _RECORD_ID, action: str = "record_edited") -> dict:
    """构造 v2 action_list 事件 payload（dispatch 剥离信封后的内层数据）。"""
    return {
        "file_token": HAZARD_ID_APP_TOKEN,
        "table_id": HAZARD_ID_TABLE_ID,
        "action_list": [
            {"action": action, "record_id": record_id, "after_value": []},
        ],
    }


# ── fake 协作对象 ──


class _FakeClient:
    def __init__(self, fields: dict | None = None):
        self.fields = fields or {}
        self.get_calls: list[str] = []
        self.update_calls: list[tuple[str, dict]] = []

    async def get_record(self, record_id: str) -> dict:
        self.get_calls.append(record_id)
        return dict(self.fields)

    async def update_record(self, record_id: str, writeback: dict) -> None:
        self.update_calls.append((record_id, dict(writeback)))


class _FakeService:
    def __init__(self, writeback: dict | None = None):
        self.writeback = writeback
        self.advance_calls: list[dict] = []
        self.advance_records: list[str] = []

    async def advance_record(self, fields: dict, *, record_id: str | None = None) -> dict | None:
        self.advance_calls.append(dict(fields))
        self.advance_records.append(record_id)
        return self.writeback


class _FakeRedis:
    """状态化 fake redis：seen_keys 预置即视为重复；可配置 set 抛异常（模拟 Redis 不可用）。"""

    def __init__(self, seen_keys: set | None = None, raise_on_set: bool = False):
        self.seen_keys = set(seen_keys or [])
        self.raise_on_set = raise_on_set
        self.deleted: list[str] = []

    async def set(self, key, value, ex=None, nx=False):
        if self.raise_on_set:
            raise ConnectionError("redis down")
        if key in self.seen_keys:
            return False
        self.seen_keys.add(key)
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.seen_keys.discard(key)


def _make_mirror(store: list):
    async def _mirror(record_id: str, fields: dict):
        store.append((record_id, dict(fields)))
    return _mirror


class TestFilter:
    async def test_other_table_ignored(self):
        client = _FakeClient(_READY_FIELDS)
        redis = _FakeRedis()
        # 非目标表：早退，不读记录不触发任何逻辑
        ev = {
            "file_token": "other_token",
            "table_id": "tblOther",
            "action_list": [{"action": "record_edited", "record_id": _RECORD_ID, "after_value": []}],
        }
        await handle_hazard_id_record_changed(ev)
        assert client.get_calls == []
        assert redis.seen_keys == set()

    async def test_missing_record_id_ignored(self):
        ev = {
            "file_token": HAZARD_ID_APP_TOKEN,
            "table_id": HAZARD_ID_TABLE_ID,
            "action_list": [{"action": "record_edited", "record_id": "", "after_value": []}],
        }
        await handle_hazard_id_record_changed(ev)  # 不应抛异常


class TestHandleUpsert:
    async def test_full_chain_writeback(self):
        """事件 → 服务推进 → 写回 Bitable → 更新镜像。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={
            "危险类型（AI）": "设备设施缺陷", "AI流程节点进度": "待AI固有风险评价",
        })
        redis = _FakeRedis()
        mirror_store: list = []

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror(mirror_store),
        )

        assert service.advance_calls[0]["AI流程节点进度"] == "待AI危险源辨识"
        assert client.update_calls == [(_RECORD_ID, {
            "危险类型（AI）": "设备设施缺陷", "AI流程节点进度": "待AI固有风险评价",
        })]
        # 镜像收到合并后的完整字段（原字段 + 回写字段）
        assert mirror_store[0][0] == _RECORD_ID
        assert mirror_store[0][1]["AI流程节点进度"] == "待AI固有风险评价"
        assert mirror_store[0][1]["岗位（人工）"] == "发酵车间主操"
        # 互斥释放
        assert any("lock" in k for k in redis.deleted)

    async def test_no_writeback_mirrors_only(self):
        """服务返回 None（未达触发/附件缺失/AI 失败）→ 不动 Bitable，仅镜像。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback=None)
        redis = _FakeRedis()
        mirror_store: list = []

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror(mirror_store),
        )

        assert client.update_calls == []
        assert mirror_store[0][0] == _RECORD_ID
        assert mirror_store[0][1]["AI流程节点进度"] == "待AI危险源辨识"

    async def test_dedup_same_node_skips(self):
        """同节点重复投递 → 状态级去重命中，跳过（服务不执行）。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        # 预置去重 key（record_id:节点:审核指纹）→ set 返回 False → _is_duplicate=True
        dup_key = f"bitable:event:hazard_id:{_RECORD_ID}:待AI危险源辨识:{_FP}"
        redis = _FakeRedis(seen_keys={dup_key})

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]),
        )

        assert service.advance_calls == []
        assert client.update_calls == []

    async def test_node_advance_not_deduped(self):
        """节点推进后 key 变化 → 级联事件不被误去重。"""
        # 第一次事件在 node A 已被处理（seen key = node A，含审核指纹）
        node_a_key = f"bitable:event:hazard_id:{_RECORD_ID}:待危险源信息AI提取:{_FP}"
        client = _FakeClient(_READY_FIELDS)  # 现在是 node B（待AI危险源辨识）
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        redis = _FakeRedis(seen_keys={node_a_key})
        mirror_store: list = []

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror(mirror_store),
        )

        # node B 的 key 未命中 → 正常执行
        assert len(service.advance_calls) == 1
        assert client.update_calls != []

    async def test_record_mutex_skips_concurrent(self):
        """记录级互斥命中（120s 窗口内已处理）→ 跳过。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        lock_key = f"bitable:lock:hazard_id:advance:{_RECORD_ID}"
        redis = _FakeRedis(seen_keys={lock_key})

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]),
        )

        assert service.advance_calls == []
        assert client.update_calls == []

    async def test_redis_down_still_processes(self):
        """Redis 不可用（去重/互斥都降级）→ 业务仍执行，不阻塞。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        redis = _FakeRedis(raise_on_set=True)
        mirror_store: list = []

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror(mirror_store),
        )

        assert len(service.advance_calls) == 1
        assert client.update_calls != []

    async def test_empty_record_read_returns_early(self):
        client = _FakeClient(fields={})
        service = _FakeService(writeback={"X": 1, "AI流程节点进度": "Y"})
        redis = _FakeRedis()

        await _handle_upsert(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]),
        )

        assert service.advance_calls == []
        assert client.update_calls == []


class TestHandleDelete:
    async def test_delete_calls_mirror(self):
        mirror_store: list = []

        async def _mirror(record_id: str):
            mirror_store.append(record_id)

        await _handle_delete(_RECORD_ID, mirror=_mirror)
        assert mirror_store == [_RECORD_ID]


class TestNodeOf:
    async def test_plain_string(self):
        assert _node_of({"AI流程节点进度": "待AI危险源辨识"}) == "待AI危险源辨识"

    async def test_rich_text_list(self):
        fields = {"AI流程节点进度": [{"text": "待AI", "type": "text"}, {"text": "危险源辨识"}]}
        assert _node_of(fields) == "待AI危险源辨识"

    async def test_missing_returns_empty(self):
        assert _node_of({}) == ""
        assert _node_of({"AI流程节点进度": None}) == ""


class TestTopLevelHandler:
    async def test_deleted_event_routes_to_delete(self):
        """顶层事件入口：deleted 事件路由到删除分支。"""
        import app.modules.safety.feishu.hazard_identification_bitable_handler as mod

        calls: list[str] = []

        async def _fake_delete(record_id):
            calls.append(("delete", record_id))

        async def _fake_upsert(record_id):
            calls.append(("upsert", record_id))

        mod._handle_delete = _fake_delete
        mod._handle_upsert = _fake_upsert
        try:
            await handle_hazard_id_record_changed(_event(action="record_deleted"))
        finally:
            mod._handle_delete = _handle_delete
            mod._handle_upsert = _handle_upsert
        assert calls == [("delete", _RECORD_ID)]

    async def test_edited_event_routes_to_upsert(self):
        """顶层事件入口：edited 事件路由到 upsert 分支。"""
        import app.modules.safety.feishu.hazard_identification_bitable_handler as mod

        calls: list[str] = []

        async def _fake_upsert(record_id):
            calls.append(record_id)

        mod._handle_upsert = _fake_upsert
        try:
            await handle_hazard_id_record_changed(_event(action="record_edited"))
        finally:
            mod._handle_upsert = _handle_upsert
        assert calls == [_RECORD_ID]

    async def test_other_app_token_ignored(self):
        """app_token 不匹配 → 早退，不调用任何分支。"""
        import app.modules.safety.feishu.hazard_identification_bitable_handler as mod

        calls: list[str] = []

        async def _fake_upsert(record_id):
            calls.append(record_id)

        async def _fake_delete(record_id):
            calls.append(record_id)

        mod._handle_upsert = _fake_upsert
        mod._handle_delete = _fake_delete
        try:
            ev = {
                "file_token": "other_token",
                "table_id": HAZARD_ID_TABLE_ID,
                "action_list": [{"action": "record_edited", "record_id": _RECORD_ID, "after_value": []}],
            }
            await handle_hazard_id_record_changed(ev)
        finally:
            mod._handle_upsert = _handle_upsert
            mod._handle_delete = _handle_delete
        assert calls == []

    async def test_action_list_multiple_items_routes_each(self):
        """v2 action_list 含多条 → 逐条分发到对应分支（加/删混合）。"""
        import app.modules.safety.feishu.hazard_identification_bitable_handler as mod

        calls: list[tuple[str, str]] = []

        async def _fake_delete(record_id):
            calls.append(("delete", record_id))

        async def _fake_upsert(record_id):
            calls.append(("upsert", record_id))

        mod._handle_delete = _fake_delete
        mod._handle_upsert = _fake_upsert
        try:
            ev = {
                "file_token": HAZARD_ID_APP_TOKEN,
                "table_id": HAZARD_ID_TABLE_ID,
                "action_list": [
                    {"action": "record_edited", "record_id": "recAAA", "after_value": []},
                    {"action": "record_deleted", "record_id": "recBBB", "after_value": []},
                    {"action": "record_added", "record_id": "recCCC", "after_value": []},
                ],
            }
            await handle_hazard_id_record_changed(ev)
        finally:
            mod._handle_delete = _handle_delete
            mod._handle_upsert = _handle_upsert
        assert calls == [
            ("upsert", "recAAA"), ("delete", "recBBB"), ("upsert", "recCCC"),
        ]

    async def test_flat_legacy_format_still_supported(self):
        """旧 flat 格式（record_id/action 顶层字段）→ 兼容分发。"""
        import app.modules.safety.feishu.hazard_identification_bitable_handler as mod

        calls: list[tuple[str, str]] = []

        async def _fake_delete(record_id):
            calls.append(("delete", record_id))

        async def _fake_upsert(record_id):
            calls.append(("upsert", record_id))

        mod._handle_delete = _fake_delete
        mod._handle_upsert = _fake_upsert
        try:
            ev = {
                "file_token": HAZARD_ID_APP_TOKEN,
                "table_id": HAZARD_ID_TABLE_ID,
                "record_id": _RECORD_ID,
                "action": "record_deleted",
            }
            await handle_hazard_id_record_changed(ev)
        finally:
            mod._handle_delete = _handle_delete
            mod._handle_upsert = _handle_upsert
        assert calls == [("delete", _RECORD_ID)]


class TestAdvanceBitableRecord:
    """Ticket 09 — 手动触发路径（advance_bitable_record）结果分类 + skip_dedup。

    手动触发与事件驱动共用同一路径；区别仅在 channel=web + skip_dedup=True。
    """

    async def test_advanced_returns_status(self):
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={
            "危险类型（AI）": "设备设施缺陷", "AI流程节点进度": "待AI固有风险评价",
        })
        redis = _FakeRedis()
        mirror_store: list = []

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror(mirror_store), channel="web", skip_dedup=True,
        )

        assert result["status"] == "advanced"
        assert result["next_node"] == "待AI固有风险评价"
        assert result["script"] == 2  # 待AI危险源辨识 → 脚本2
        assert client.update_calls != []
        assert mirror_store != []

    async def test_skip_dedup_forces_retry(self):
        """手动触发跳过 60s 状态级去重：同节点已处理过仍强制尝试。"""
        dup_key = f"bitable:event:hazard_id:{_RECORD_ID}:待AI危险源辨识:{_FP}"
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        redis = _FakeRedis(seen_keys={dup_key})

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]), skip_dedup=True,
        )

        assert result["status"] == "advanced"
        assert len(service.advance_calls) == 1

    async def test_dedup_hit_without_skip(self):
        """事件驱动（skip_dedup=False）仍受 60s 去重约束。"""
        dup_key = f"bitable:event:hazard_id:{_RECORD_ID}:待AI危险源辨识:{_FP}"
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        redis = _FakeRedis(seen_keys={dup_key})

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]),
        )

        assert result["status"] == "noop"
        assert result["reason"] == "dedup"
        assert service.advance_calls == []

    async def test_mutex_busy_returns_noop(self):
        """记录级互斥（120s）手动触发也保留，防止重复 AI 调用。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback={"危险类型（AI）": "X", "AI流程节点进度": "待AI固有风险评价"})
        lock_key = f"bitable:lock:hazard_id:advance:{_RECORD_ID}"
        redis = _FakeRedis(seen_keys={lock_key})

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]), skip_dedup=True,
        )

        assert result["status"] == "noop"
        assert result["reason"] == "busy"
        assert service.advance_calls == []

    async def test_completed_node_returns_noop_completed(self):
        """节点为「AI 流程结束」→ 无脚本可执行，返回 completed。"""
        fields = {**_READY_FIELDS, "AI流程节点进度": "AI 流程结束"}
        client = _FakeClient(fields)
        service = _FakeService(writeback=None)
        redis = _FakeRedis()

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]), skip_dedup=True,
        )

        assert result["status"] == "noop"
        assert result["reason"] == "completed"
        assert client.update_calls == []

    async def test_precondition_no_writeback_returns_noop(self):
        """服务返回 None（未达触发/附件缺失/AI 失败）→ precondition。"""
        client = _FakeClient(_READY_FIELDS)
        service = _FakeService(writeback=None)
        redis = _FakeRedis()

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]), skip_dedup=True,
        )

        assert result["status"] == "noop"
        assert result["reason"] == "precondition"
        assert client.update_calls == []

    async def test_empty_record_returns_noop(self):
        client = _FakeClient(fields={})
        service = _FakeService(writeback={"X": 1, "AI流程节点进度": "Y"})
        redis = _FakeRedis()

        result = await advance_bitable_record(
            _RECORD_ID, client=client, service=service, redis=redis,
            mirror=_make_mirror([]),
        )

        assert result["status"] == "noop"
        assert result["reason"] == "empty_record"
        assert service.advance_calls == []
