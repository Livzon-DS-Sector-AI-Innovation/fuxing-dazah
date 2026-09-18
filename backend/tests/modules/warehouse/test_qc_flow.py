"""QC 请验放行闭环测试（V3.0 分期B，设计 §4.1）。

接缝（spec Testing Decisions，沿用分期A）：服务函数级 + FakeBaseAdapter /
dry_run / monkeypatch 开关与 runtime 参数；共享库有真机数据，精确断言前
事务内清表（_hermetic_qc_tables 模式）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import qc_flow
from app.modules.warehouse.models import WarehouseQcStatus
from app.modules.warehouse.push_center.events import get_event_renderer
from app.modules.warehouse.push_center.registry import iter_tasks


def _card_text(card: dict[str, Any]) -> str:
    """卡片 markdown 元素拼接（断言用；元素结构见 build_card）。"""
    parts = []
    for el in (card.get("body") or {}).get("elements", []):
        if isinstance(el, dict) and el.get("tag") == "markdown":
            parts.append(str(el.get("content") or ""))
    return "\n".join(parts)


# ── Ticket 01：基座（registry / 渲染器 / 运行参数 / 镜像表）──


class TestQcPushRegistry:
    def test_three_qc_event_tasks_registered(self) -> None:
        tasks = {t.task_name: t for t in iter_tasks()}
        for name in ("arrival_inspection", "qc_progress_alert", "release_notify"):
            info = tasks[name]
            assert info.scene == name, name
            assert info.trigger == "event", name
            assert info.default_schedule is None, name
            assert info.target_env_var == "WAREHOUSE_TEST_CHAT_ID", name


class TestQcEventRenderers:
    def test_arrival_inspection_card_fields(self) -> None:
        renderer = get_event_renderer("arrival_inspection")
        assert renderer is not None
        card = renderer(
            {
                "material_name": "无水碳酸钾",
                "batch_no": "10307-251201",
                "supplier": "杭州昇昇医药科技有限公司",
                "quantity": "500",
                "unit": "Kg",
                "record_url": "https://example.feishu.cn/base/xxx?table=t1&record=rec1",
            }
        )
        text = _card_text(card)
        assert "无水碳酸钾" in text
        assert "10307-251201" in text
        assert "杭州昇昇医药科技有限公司" in text
        assert "500" in text
        assert "rec1" in text  # 台账记录链接

    def test_arrival_inspection_card_tolerates_missing_fields(self) -> None:
        renderer = get_event_renderer("arrival_inspection")
        assert renderer is not None
        card = renderer({"material_name": "硫酸", "batch_no": "H25091801"})
        text = _card_text(card)
        assert "硫酸" in text and "H25091801" in text
        assert "-" in text  # 缺失字段容错占位

    def test_qc_progress_alert_card_lists_items(self) -> None:
        renderer = get_event_renderer("qc_progress_alert")
        assert renderer is not None
        card = renderer(
            {
                "items": [
                    {"material_name": "硫酸", "batch_no": "H1", "waited_days": 5, "kind": "sample"},
                    {"material_name": "丙酮", "batch_no": "H2", "waited_days": 12, "kind": "report"},
                ]
            }
        )
        text = _card_text(card)
        assert "硫酸" in text and "H1" in text and "5" in text
        assert "丙酮" in text and "H2" in text and "12" in text
        assert "取样" in text and "出报" in text

    def test_release_notify_card(self) -> None:
        renderer = get_event_renderer("release_notify")
        assert renderer is not None
        card = renderer(
            {"material_name": "硫酸", "batch_no": "H25091801", "release_type": "放行"}
        )
        text = _card_text(card)
        assert "H25091801" in text and "硫酸" in text
        assert "放行" in text and "上架" in text


class TestQcRuntimeParams:
    def test_writeback_switch_on_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.warehouse.ops_config.runtime_store import runtime_store

        monkeypatch.setattr(runtime_store, "get_value", lambda key: "0")
        assert qc_flow.qc_writeback_enabled() is False
        monkeypatch.setattr(runtime_store, "get_value", lambda key: "1")
        assert qc_flow.qc_writeback_enabled() is True

    def test_writeback_switch_fail_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """读取异常/非法值一律按关（kill switch 语义，对齐 A 期总开关）。"""
        from app.modules.warehouse.ops_config.runtime_store import runtime_store

        def _boom(key: str) -> Any:
            raise RuntimeError("db down")

        monkeypatch.setattr(runtime_store, "get_value", _boom)
        assert qc_flow.qc_writeback_enabled() is False
        monkeypatch.setattr(runtime_store, "get_value", lambda key: "abc")
        assert qc_flow.qc_writeback_enabled() is False
        monkeypatch.setattr(runtime_store, "get_value", lambda key: None)
        assert qc_flow.qc_writeback_enabled() is False

    def test_qa_confirm_target_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core.config import get_settings
        from app.modules.warehouse.ops_config.runtime_store import runtime_store

        monkeypatch.setattr(runtime_store, "get_value", lambda key: "")
        monkeypatch.setattr(
            get_settings(), "WAREHOUSE_TEST_CHAT_ID", "oc_test", raising=False
        )
        assert qc_flow.qa_confirm_target() == "oc_test"
        monkeypatch.setattr(runtime_store, "get_value", lambda key: "oc_real")
        assert qc_flow.qa_confirm_target() == "oc_real"


class TestQcStatusMirrorModel:
    async def test_roundtrip_and_unique_record_id(self, db_session: AsyncSession) -> None:

        row = WarehouseQcStatus(
            record_id="recA1",
            batch_no="10307-251201",
            material_name="无水碳酸钾",
            receipt_date=None,
            sample_status="未取样",
            report_status="未出报",
            release_status=None,
            scanned_at=datetime.now(UTC),
        )
        db_session.add(row)
        await db_session.flush()

        saved = (
            await db_session.execute(
                select(WarehouseQcStatus).where(WarehouseQcStatus.record_id == "recA1")
            )
        ).scalar_one()
        assert saved.sample_status == "未取样"
        assert saved.report_status == "未出报"
        assert saved.release_status is None

        dup = WarehouseQcStatus(
            record_id="recA1", batch_no="x", scanned_at=datetime.now(UTC)
        )
        db_session.add(dup)
        with pytest.raises(Exception, match=r"(?i)unique|duplicate|重复"):
            await db_session.flush()
        await db_session.rollback()


# ── Ticket 02：到货请验推送（链路1）──


class TestArrivalInspectionHook:
    def test_arrival_payload_fields_and_url(self) -> None:
        from app.modules.warehouse.agent.pipeline import submit as submit_mod

        payload = submit_mod._arrival_payload(
            {
                "物料名称(API)": "无水碳酸钾",
                "物料批号": "10307-251201",
                "供应商": "杭州昇昇医药科技有限公司",
                "入库数量": 500,
                "单位": "Kg",
                "件数": "20",  # 不进请验卡
            },
            "rec123",
            {"base_token": "btok", "table_id": "tbl1"},
        )
        assert payload["material_name"] == "无水碳酸钾"
        assert payload["batch_no"] == "10307-251201"
        assert payload["supplier"] == "杭州昇昇医药科技有限公司"
        assert payload["quantity"] == 500
        assert payload["unit"] == "Kg"
        assert "件数" not in payload
        assert payload["record_url"].endswith("/base/btok?table=tbl1&record=rec123")

    def test_arrival_payload_tolerates_missing_fields(self) -> None:
        from app.modules.warehouse.agent.pipeline import submit as submit_mod

        payload = submit_mod._arrival_payload(
            {}, "rec1", {"base_token": "b", "table_id": "t"}
        )
        assert "material_name" not in payload
        assert payload["record_url"].endswith("record=rec1")

    async def test_fire_arrival_swallows_errors(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """推送通道异常不影响入库登记主流程。"""
        from app.modules.warehouse.agent.pipeline import submit as submit_mod
        from app.modules.warehouse.push_center import events

        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("推送通道异常")

        monkeypatch.setattr(events, "fire_push_event", _boom)
        assert (
            await submit_mod._fire_arrival_inspection(
                db_session,
                {"物料名称(API)": "硫酸"},
                "rec1",
                {"base_token": "b", "table_id": "t"},
            )
            is False
        )

    async def test_fire_arrival_success(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.agent.pipeline import submit as submit_mod
        from app.modules.warehouse.push_center import events
        from app.modules.warehouse.push_center.engine import PushRunResult

        async def _fake_fire(db: Any, scene: str, payload: Any, **kwargs: Any):
            assert scene == "arrival_inspection"
            assert payload["material_name"] == "硫酸"
            return [PushRunResult("arrival_inspection", scene, "executed", None, 1)]

        monkeypatch.setattr(events, "fire_push_event", _fake_fire)
        assert (
            await submit_mod._fire_arrival_inspection(
                db_session,
                {"物料名称(API)": "硫酸"},
                "rec1",
                {"base_token": "b", "table_id": "t"},
            )
            is True
        )


# ── Ticket 03：QC 扫描核心与状态镜像（链路4 后端）──


class FakeQcBase:
    """零网络假 Base：material_receipt / material_master / unqualified_stock。

    记录 fields 值形态刻意混杂（单选类型包裹 / 富文本 / 裸毫秒时间戳），
    验证扫描一律走 bitable_cells 规范解析。master_records 模拟物料级出报
    天数覆盖行；unqualified_records 模拟不合格台账（按 SourceID 过滤）；
    create_record 捕获生成调用。
    """

    def __init__(
        self,
        records: list[dict[str, Any]],
        master_records: list[dict[str, Any]] | None = None,
        unqualified_records: list[dict[str, Any]] | None = None,
    ) -> None:
        self.records = records
        self.master_records = master_records or []
        self.unqualified_records = unqualified_records or []
        self.created_records: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []

    async def search_records_page(
        self,
        table_key: str,
        *,
        filter_json: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        limit: int = 500,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        self.search_calls.append({"table": table_key, "filter": filter_json})
        if page_token:
            return {"records": [], "page_token": None}
        if table_key == "material_master":
            source = self.master_records
        elif table_key == "unqualified_stock":
            source = self.unqualified_records
            # 模拟 Base 侧 SourceID 过滤（不合格去重查询）
            conditions = (filter_json or {}).get("conditions") or []
            for cond in conditions:
                if cond.get("field_name") == "SourceID":
                    matched = str((cond.get("value") or [""])[0])
                    source = [
                        r
                        for r in source
                        if str((r.get("fields") or {}).get("SourceID")) == matched
                    ]
        else:
            source = self.records
        return {"records": [dict(r) for r in source], "page_token": None}

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        record = {
            "record_id": f"unq-created-{len(self.created_records) + 1}",
            "fields": dict(fields),
        }
        self.created_records.append({"table": table_key, "record": record})
        return dict(record)


def _ms(days_ago: float) -> int:

    return int((datetime.now(UTC) - timedelta(days=days_ago)).timestamp() * 1000)


def _receipt_record(
    record_id: str,
    *,
    batch_no: str = "10307-251201",
    material_name: str = "无水碳酸钾",
    receipt_days_ago: float = 10,
    sample: Any = None,
    report: Any = None,
    release: Any = None,
    vendor_batch_no: str = "V-260901",
    quantity: float = 500,
) -> dict[str, Any]:
    """构造 material_receipt 记录（未指定状态 = 空值，即未开始流程）。"""
    return {
        "record_id": record_id,
        "fields": {
            "物料批号": batch_no,
            "物料名称(API)": [{"text": material_name, "type": "text"}],
            "入库日期": _ms(receipt_days_ago),
            "QC取样情况": sample,
            "QC出报": report,
            "QA放行": release,
            "厂家批号": vendor_batch_no,
            "入库数量": quantity,
        },
    }


class TestQcScanMirror:
    async def test_scan_mirrors_receipt_records(
        self, db_session: AsyncSession
    ) -> None:


        adapter = FakeQcBase(
            [
                _receipt_record(
                    "rec_open",
                    sample={"type": 3, "value": ["未取样"]},
                    report={"type": 3, "value": ["未出报"]},
                ),
                _receipt_record(
                    "rec_released",
                    sample="已取样",
                    report="已出报（合格）",
                    release={"type": 3, "value": ["放行"]},
                ),
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["pulled"] == 2
        assert summary["mirrored"] == 2

        rows = {
            r.record_id: r
            for r in (
                await db_session.execute(select(WarehouseQcStatus))
            ).scalars().all()
            if r.record_id in ("rec_open", "rec_released")
        }
        assert rows["rec_open"].sample_status == "未取样"
        assert rows["rec_open"].report_status == "未出报"
        assert rows["rec_open"].release_status is None
        assert rows["rec_open"].material_name == "无水碳酸钾"
        assert rows["rec_open"].batch_no == "10307-251201"
        assert rows["rec_released"].release_status == "放行"

    async def test_scan_idempotent_rerun(
        self, db_session: AsyncSession
    ) -> None:
        """重复扫描：无状态变化的行不重复写（created/updated 均为 0）。"""


        adapter = FakeQcBase([_receipt_record("rec_a", sample="已取样")])
        now = datetime.now(UTC)
        first = await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert first["created"] == 1
        second = await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert second["created"] == 0
        assert second["updated"] == 0
        assert second["mirrored"] == 1

    async def test_scan_updates_changed_state(
        self, db_session: AsyncSession
    ) -> None:
        """Base 侧状态变化后，镜像随扫描同步（变迁检测基础）。"""


        adapter = FakeQcBase([_receipt_record("rec_a", sample="未取样")])
        now = datetime.now(UTC)
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)

        adapter.records[0]["fields"]["QC取样情况"] = "已取样"
        adapter.records[0]["fields"]["QC出报"] = "已出报（合格）"
        summary = await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert summary["updated"] == 1

        row = (
            await db_session.execute(
                select(WarehouseQcStatus).where(WarehouseQcStatus.record_id == "rec_a")
            )
        ).scalar_one()
        assert row.sample_status == "已取样"
        assert row.report_status == "已出报（合格）"

    async def test_scan_window_excludes_old_records(
        self, db_session: AsyncSession
    ) -> None:
        """入库超 120 天的历史记录不进镜像（本地窗口过滤；真机实测日期
        filter 不支持，全量分页为正式路径）。"""

        adapter = FakeQcBase(
            [
                _receipt_record("rec_recent", receipt_days_ago=10),
                _receipt_record("rec_old", receipt_days_ago=200),
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["pulled"] == 1
        # 全量拉取（无 Base 侧过滤；本地窗口过滤兜底）
        assert adapter.search_calls[0]["filter"] is None
        record_ids = {
            r.record_id
            for r in (await db_session.execute(select(WarehouseQcStatus))).scalars().all()
        }
        assert "rec_old" not in record_ids


class TestQcScanTaskRegistration:
    def test_task_definition_registered(self) -> None:
        """扫描任务定义存在且为 60min interval（main.py lifespan 注册见集成层）。"""
        from app.modules.warehouse.scheduled import QC_SCAN_TASK

        assert QC_SCAN_TASK.name == "warehouse.qc_scan"
        assert QC_SCAN_TASK.schedule.interval_seconds == 3600


# ── Ticket 04：状态展示（链路4 前台）──


def _mirror_row(
    record_id: str,
    batch_no: str,
    *,
    material_name: str = "硫酸",
    receipt_days_ago: float = 5,
    sample: Any = None,
    report: Any = None,
    release: Any = None,
    scanned_hours_ago: float = 0,
) -> WarehouseQcStatus:

    return WarehouseQcStatus(
        record_id=record_id,
        batch_no=batch_no,
        material_name=material_name,
        receipt_date=(datetime.now(UTC) - timedelta(days=receipt_days_ago)).date(),
        sample_status=sample,
        report_status=report,
        release_status=release,
        scanned_at=datetime.now(UTC) - timedelta(hours=scanned_hours_ago),
    )


class TestQcStatusLookup:
    async def test_get_qc_status_by_batches_prefers_open(self, db_session: AsyncSession) -> None:
        """同批号多条 receipt：未放行（可操作）优先；无镜像批号缺席。"""

        db_session.add_all(
            [
                _mirror_row("rec1", "B1", release="放行", scanned_hours_ago=2),
                _mirror_row(
                    "rec2", "B1", sample="已取样", report="已出报（合格）"
                ),
                _mirror_row("rec3", "B2", release="放行"),
            ]
        )
        await db_session.flush()

        result = await qc_flow.get_qc_status_by_batches(db_session, ["B1", "B2", "B3"])
        assert result["B1"].record_id == "rec2"  # 未放行优先于更早扫描的已放行行
        assert result["B2"].release_status == "放行"
        assert "B3" not in result

    async def test_get_qc_status_by_batches_empty_input(self, db_session: AsyncSession) -> None:

        assert await qc_flow.get_qc_status_by_batches(db_session, []) == {}


class TestDashboardQcTodos:
    async def test_todos_qc_pending_counts_and_items(self, db_session: AsyncSession) -> None:
        """三计数 + top 条目（入库最早优先）；已闭环/免检/不合格不进待办。"""
        from sqlalchemy import delete

        from app.modules.warehouse.dashboard import get_todos

        await db_session.execute(delete(WarehouseQcStatus))
        db_session.add_all(
            [
                _mirror_row("r1", "B-S", receipt_days_ago=6, sample="未取样"),
                _mirror_row(
                    "r2", "B-R", receipt_days_ago=4, sample="已取样", report="未出报"
                ),
                _mirror_row(
                    "r3",
                    "B-G",
                    receipt_days_ago=2,
                    sample="已取样",
                    report="已出报（合格）",
                ),
                _mirror_row("r4", "B-Done", report="已出报（合格）", release="放行"),
                _mirror_row("r5", "B-Free", report="免检物料"),
                _mirror_row(
                    "r6", "B-Rej", report="已出报（不合格）"
                ),
            ]
        )
        await db_session.flush()

        todos = await get_todos(db_session)
        qc = todos["qc_pending"]
        assert qc["await_sample_count"] == 1
        assert qc["await_report_count"] == 1
        assert qc["await_release_count"] == 1
        assert [i["batch_no"] for i in qc["items"]] == ["B-S", "B-R", "B-G"]
        assert qc["items"][0]["stage"] == "待取样"
        assert qc["items"][2]["stage"] == "待放行"

    async def test_todos_qc_pending_all_closed(self, db_session: AsyncSession) -> None:
        from sqlalchemy import delete

        from app.modules.warehouse.dashboard import get_todos

        await db_session.execute(delete(WarehouseQcStatus))
        db_session.add(_mirror_row("r1", "B-Done", report="已出报（合格）", release="放行"))
        await db_session.flush()

        todos = await get_todos(db_session)
        qc = todos["qc_pending"]
        assert qc["await_sample_count"] == 0
        assert qc["await_report_count"] == 0
        assert qc["await_release_count"] == 0
        assert qc["items"] == []


class TestStockListQcEnrichment:
    async def test_list_stocks_with_qc_fields(self, db_session: AsyncSession) -> None:
        """库存分页列表响应带 QC 三列（镜像按批号关联；无镜像行三列为 None）。"""
        from decimal import Decimal
        from uuid import uuid4

        from app.modules.warehouse import service
        from app.modules.warehouse.models import (
            WarehouseLocation,
            WarehouseMaterial,
            WarehouseStock,
        )

        suffix = uuid4().hex[:6]
        material = WarehouseMaterial(
            code=f"QC-T-{suffix}",
            name="QC展示物料",
            category="raw",
            unit="kg",
            safety_stock=Decimal("0"),
        )
        location = WarehouseLocation(code=f"QC-T-L{suffix}", name="QC展示库位")
        db_session.add_all([material, location])
        await db_session.flush()
        db_session.add_all(
            [
                WarehouseStock(
                    material_id=material.id,
                    material_code=material.code,
                    material_name=material.name,
                    batch_no=f"QCB1-{suffix}",
                    location_id=location.id,
                    location_code=location.code,
                    location_name=location.name,
                    quantity=Decimal("10"),
                ),
                WarehouseStock(
                    material_id=material.id,
                    material_code=material.code,
                    material_name=material.name,
                    batch_no=f"QCB2-{suffix}",
                    location_id=location.id,
                    location_code=location.code,
                    location_name=location.name,
                    quantity=Decimal("20"),
                ),
            ]
        )
        db_session.add(
            _mirror_row(
                f"rq-{suffix}",
                f"QCB1-{suffix}",
                sample="已取样",
                report="已出报（合格）",
                release="放行",
            )
        )
        await db_session.flush()

        items, total = await service.list_stocks_with_qc(
            db_session, page=1, page_size=20, batch_no=suffix
        )
        assert total == 2
        by_batch = {r["batch_no"]: r for r in items}
        assert by_batch[f"QCB1-{suffix}"]["qc_sample_status"] == "已取样"
        assert by_batch[f"QCB1-{suffix}"]["qc_report_status"] == "已出报（合格）"
        assert by_batch[f"QCB1-{suffix}"]["qc_release_status"] == "放行"
        assert by_batch[f"QCB2-{suffix}"]["qc_sample_status"] is None
        assert by_batch[f"QCB2-{suffix}"]["qc_release_status"] is None


# ── Ticket 05：QC 超期提醒（链路2）──

QC_RULES = ("qc_sample_overdue", "qc_report_overdue")


async def _hermetic_alerts(db_session: AsyncSession) -> None:
    """封闭性：清 QC 规则的镜像与异常记录（事务内删除随回滚撤销）。"""
    from sqlalchemy import delete

    from app.modules.warehouse.models import WarehouseAlertRecord

    await db_session.execute(delete(WarehouseQcStatus))
    await db_session.execute(
        delete(WarehouseAlertRecord).where(WarehouseAlertRecord.rule_key.in_(QC_RULES))
    )


def _push_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """捕获 qc_progress_alert 事件推送 payload（monkeypatch 事件入口）。"""
    from app.modules.warehouse.push_center import events
    from app.modules.warehouse.push_center.engine import PushRunResult

    fired: list[dict[str, Any]] = []

    async def _fake_fire(db: Any, scene: str, payload: Any, **kwargs: Any) -> list[Any]:
        fired.append({"scene": scene, "payload": payload})
        return [PushRunResult("qc_progress_alert", scene, "executed", None, 1)]

    monkeypatch.setattr(events, "fire_push_event", _fake_fire)
    return fired


class TestQcOverdueAlerts:
    async def test_overdue_sample_and_report_alert_and_push(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未取样超 3 天 / 已取样未出报超 7 天 → 开单 + 一次推送（两条目）。"""

        from app.modules.warehouse.models import WarehouseAlertRecord

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        adapter = FakeQcBase(
            [
                _receipt_record("r_s", batch_no="B-S", receipt_days_ago=5, sample="未取样"),
                _receipt_record(
                    "r_r",
                    batch_no="B-R",
                    receipt_days_ago=10,
                    sample="已取样",
                    report="未出报",
                ),
                _receipt_record("r_new", batch_no="B-N", receipt_days_ago=1, sample="未取样"),
                _receipt_record(
                    "r_ok",
                    batch_no="B-K",
                    receipt_days_ago=3,
                    sample="已取样",
                    report="未出报",
                ),
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )

        assert summary["alert_sample"] == 1
        assert summary["alert_report"] == 1
        assert summary["alert_pushed"] == 2
        assert len(fired) == 1
        assert fired[0]["scene"] == "qc_progress_alert"
        items = fired[0]["payload"]["items"]
        assert {i["kind"] for i in items} == {"sample", "report"}
        assert {i["batch_no"] for i in items} == {"B-S", "B-R"}

        alerts = (
            await db_session.execute(
                select(WarehouseAlertRecord).where(
                    WarehouseAlertRecord.rule_key.in_(QC_RULES),
                    WarehouseAlertRecord.status == "open",
                )
            )
        ).scalars().all()
        assert len(alerts) == 2

    async def test_no_repush_when_state_unchanged(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同一超期状态重复扫描：不重复推送、不重复开单。"""

        from app.modules.warehouse.models import WarehouseAlertRecord

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        adapter = FakeQcBase(
            [_receipt_record("r_s", batch_no="B-S", receipt_days_ago=5, sample="未取样")]
        )
        now = datetime.now(UTC)
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)

        assert len(fired) == 1  # 只推第一次
        alerts = (
            await db_session.execute(
                select(WarehouseAlertRecord).where(
                    WarehouseAlertRecord.rule_key.in_(QC_RULES)
                )
            )
        ).scalars().all()
        assert len(alerts) == 1  # 幂等开单

    async def test_alert_auto_resolved_when_closed(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """取样完成后条件消除 → 异常自动解决，不再推送。"""

        from app.modules.warehouse.models import WarehouseAlertRecord

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        adapter = FakeQcBase(
            [_receipt_record("r_s", batch_no="B-S", receipt_days_ago=5, sample="未取样")]
        )
        now = datetime.now(UTC)
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)

        adapter.records[0]["fields"]["QC取样情况"] = "已取样"
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)

        assert len(fired) == 1
        alerts = (
            await db_session.execute(
                select(WarehouseAlertRecord).where(
                    WarehouseAlertRecord.rule_key.in_(QC_RULES)
                )
            )
        ).scalars().all()
        assert [r.status for r in alerts] == ["resolved"]
        assert all(r.resolved_by is None for r in alerts)  # 系统自动解决

    async def test_material_level_report_days_override(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """名录表物料级出报天数覆盖全局：长周期物料不误报。"""


        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_slow",
                    batch_no="B-SLOW",
                    material_name="慢检物料",
                    receipt_days_ago=10,
                    sample="已取样",
                    report="未出报",
                ),
                _receipt_record(
                    "r_fast",
                    batch_no="B-FAST",
                    material_name="快检物料",
                    receipt_days_ago=10,
                    sample="已取样",
                    report="未出报",
                ),
            ],
            master_records=[
                {
                    "record_id": "m1",
                    "fields": {
                        "物料名称": "慢检物料",
                        "实际物料：请检后出报天数": 15,
                    },
                }
            ],
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )

        assert summary["alert_report"] == 1  # 只有快检物料（全局 7 天）超期
        items = fired[0]["payload"]["items"]
        assert [i["batch_no"] for i in items] == ["B-FAST"]

    async def test_manual_resolved_not_revived(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """人工已解决的异常不复活、不推送（apply_alert_records 语义）。"""
        from uuid import UUID

        from app.modules.warehouse.models import WarehouseAlertRecord
        from app.modules.warehouse.qc_flow import _alert_material_id

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        manual = WarehouseAlertRecord(
            rule_key="qc_sample_overdue",
            status="resolved",
            material_id=_alert_material_id("r_s"),
            material_code="B-S",
            material_name="无水碳酸钾",
            batch_no="B-S",
            detail={},
            resolved_by=UUID("00000000-0000-0000-0000-000000000001"),
        )
        db_session.add(manual)
        await db_session.flush()

        adapter = FakeQcBase(
            [_receipt_record("r_s", batch_no="B-S", receipt_days_ago=5, sample="未取样")]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )

        assert summary["alert_pushed"] == 0
        assert fired == []
        alerts = (
            await db_session.execute(
                select(WarehouseAlertRecord).where(
                    WarehouseAlertRecord.rule_key.in_(QC_RULES),
                    WarehouseAlertRecord.status == "open",
                )
            )
        ).scalars().all()
        assert alerts == []

    async def test_disabled_rule_skips_alerts(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """规则停用 → 不开单不推送（阈值读回落但整体跳过）。"""

        from app.modules.warehouse.models import WarehouseAlertRule

        await _hermetic_alerts(db_session)
        # 迁移已播种规则行：事务内置停用（随回滚还原）
        rules = (
            await db_session.execute(
                select(WarehouseAlertRule).where(
                    WarehouseAlertRule.rule_key.in_(QC_RULES)
                )
            )
        ).scalars().all()
        for rule in rules:
            rule.enabled = False
        await db_session.flush()
        fired = _push_capture(monkeypatch)

        adapter = FakeQcBase(
            [_receipt_record("r_s", batch_no="B-S", receipt_days_ago=5, sample="未取样")]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["alert_sample"] == 0
        assert fired == []


# ── Ticket 06：QA 放行确认门与放行通知（链路3 主线）──


def _qc_switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认开启 QC 回写开关（生产默认关；门创建依赖开关）。"""

    monkeypatch.setattr(qc_flow, "qc_writeback_enabled", lambda: True)


def _qc_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr(qc_flow, "qc_writeback_enabled", lambda: False)


def _gate_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """捕获确认门创建（monkeypatch confirm_request.send_request_card）。"""
    from app.modules.warehouse import confirm_request as cr

    created: list[dict[str, Any]] = []

    async def _fake_send(request: Any, *, dry_run: bool | None = None) -> bool:
        created.append(
            {
                "request_no": request.request_no,
                "business_type": request.business_type,
                "ref_table": request.ref_table,
                "ref_record_ids": list(request.ref_record_ids),
                "writeback": dict(request.writeback or {}),
                "target": request.target,
                "summary": request.summary,
            }
        )
        return True

    monkeypatch.setattr(cr, "send_request_card", _fake_send)
    return created


class TestReleaseConfirmGate:
    async def test_gate_created_for_qualified_unreleased(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """出报合格且未放行 → 建 QA 放行确认门（映射三字段 + @confirmer）。"""

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)
        _push_capture(monkeypatch)
        monkeypatch.setattr(qc_flow, "qa_confirm_target", lambda: "oc_qa_group")

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_g",
                    batch_no="B-G",
                    sample="已取样",
                    report="已出报（合格）",
                )
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["gates_created"] == 1
        assert len(gates) == 1
        gate = gates[0]
        assert gate["business_type"] == "qa_release"
        assert gate["ref_table"] == "material_receipt"
        assert gate["ref_record_ids"] == ["r_g"]
        assert gate["target"] == "oc_qa_group"
        assert gate["writeback"] == {
            "QA放行": "放行",
            "QA放行人": "@confirmer",
            "放行提交时间": "@today",
        }
        assert "B-G" in gate["summary"]

    async def test_gate_skipped_when_switch_off(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        await _hermetic_alerts(db_session)
        _qc_switch_off(monkeypatch)
        gates = _gate_capture(monkeypatch)

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_g", batch_no="B-G", sample="已取样", report="已出报（合格）"
                )
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["gates_created"] == 0
        assert gates == []

    async def test_gate_skipped_when_release_filled(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QA 在 Base 直接选了否决/条件放行 → 不建门（release 非空即闭环）。"""

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_v",
                    batch_no="B-V",
                    sample="已取样",
                    report="已出报（合格）",
                    release="否决",
                ),
                _receipt_record(
                    "r_c",
                    batch_no="B-C",
                    sample="已取样",
                    report="已出报（合格）",
                    release="条件放行",
                ),
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["gates_created"] == 0
        assert gates == []

    async def test_gate_dedup_pending_and_rate_limit(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pending 门存在不重建；近期（24h 内）建过门（过期/取消）限频不重建。"""

        from app.modules.warehouse import confirm_request as cr
        from app.modules.warehouse.models import WarehouseConfirmRequest

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)

        # pending 门（防重复）+ 1 小时前取消的门（限频窗口内）
        db_session.add_all(
            [
                await cr.create_request(
                    db_session,
                    business_type="qa_release",
                    title="QA 放行确认",
                    summary="pending 门",
                    ref_table="material_receipt",
                    ref_record_ids=["r_pending"],
                    target="oc_qa",
                    writeback={"QA放行": "放行"},
                ),
                await cr.create_request(
                    db_session,
                    business_type="qa_release",
                    title="QA 放行确认",
                    summary="近期取消的门",
                    ref_table="material_receipt",
                    ref_record_ids=["r_recent"],
                    target="oc_qa",
                    writeback={"QA放行": "放行"},
                ),
            ]
        )
        await db_session.flush()
        recent = (
            await db_session.execute(
                select(WarehouseConfirmRequest).where(
                    WarehouseConfirmRequest.ref_record_ids.contains(["r_recent"])
                )
            )
        ).scalar_one()
        recent.status = "cancelled"
        recent.created_at = datetime.now(UTC) - timedelta(hours=1)
        await db_session.flush()

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_pending",
                    batch_no="B-P",
                    sample="已取样",
                    report="已出报（合格）",
                ),
                _receipt_record(
                    "r_recent", batch_no="B-R", sample="已取样", report="已出报（合格）"
                ),
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["gates_created"] == 0
        assert gates == []

    async def test_gate_recreated_after_rate_window(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """限频窗口（24h）外的旧门 → 重建（过期/取消不遗漏）。"""

        from app.modules.warehouse import confirm_request as cr
        from app.modules.warehouse.models import WarehouseConfirmRequest

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)

        db_session.add(
            await cr.create_request(
                db_session,
                business_type="qa_release",
                title="QA 放行确认",
                summary="25 小时前过期的门",
                ref_table="material_receipt",
                ref_record_ids=["r_old"],
                target="oc_qa",
                writeback={"QA放行": "放行"},
            )
        )
        await db_session.flush()
        old = (
            await db_session.execute(
                select(WarehouseConfirmRequest).where(
                    WarehouseConfirmRequest.ref_record_ids.contains(["r_old"])
                )
            )
        ).scalar_one()
        old.status = "expired"
        old.created_at = datetime.now(UTC) - timedelta(hours=25)
        await db_session.flush()

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_old", batch_no="B-O", sample="已取样", report="已出报（合格）"
                )
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["gates_created"] == 1
        assert gates[0]["ref_record_ids"] == ["r_old"]


class TestReleaseNotification:
    async def test_release_transition_fires_notify_once(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """镜像旧值未放行 → 新值放行：推一次上架通知；再扫描不重复。"""

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_g", batch_no="B-G", sample="已取样", report="已出报（合格）"
                )
            ]
        )
        now = datetime.now(UTC)
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert fired == []  # 首扫建镜像，未放行无通知

        adapter.records[0]["fields"]["QA放行"] = "放行"
        summary = await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert summary["release_notified"] == 1
        assert fired[0]["scene"] == "release_notify"
        assert fired[0]["payload"]["batch_no"] == "B-G"
        assert fired[0]["payload"]["release_type"] == "放行"

        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert len(fired) == 1  # 变迁只触发一次

    async def test_first_scan_bootstrap_no_notify(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """部署前已放行的历史记录：首扫无旧镜像 → 不补发通知。"""

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_done",
                    batch_no="B-D",
                    sample="已取样",
                    report="已出报（合格）",
                    release="放行",
                )
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["release_notified"] == 0
        assert fired == []

    async def test_conditional_release_notifies(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QA 在 Base 直接选条件放行 → 照常通知（release_type=条件放行）。"""

        await _hermetic_alerts(db_session)
        fired = _push_capture(monkeypatch)
        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_c", batch_no="B-C", sample="已取样", report="已出报（合格）"
                )
            ]
        )
        now = datetime.now(UTC)
        await qc_flow.run_qc_scan(db_session, now, adapter=adapter)

        adapter.records[0]["fields"]["QA放行"] = "条件放行"
        summary = await qc_flow.run_qc_scan(db_session, now, adapter=adapter)
        assert summary["release_notified"] == 1
        assert fired[0]["payload"]["release_type"] == "条件放行"


# ── Ticket 07：否决分支（不合格记录生成 + 处理方案确认门，链路3 支线）──


class TestRejectedUnqualifiedBranch:
    async def test_rejected_generates_unqualified_and_gate(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """出报不合格 → 生成 unqualified_stock 记录（字段映射 + SourceID 去重键）
        + 即时处理方案确认门（回写处理日期=@today）。"""

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)
        _push_capture(monkeypatch)
        monkeypatch.setattr(qc_flow, "qa_confirm_target", lambda: "oc_qa_group")

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_rej",
                    batch_no="B-REJ",
                    material_name="硫酸",
                    sample="已取样",
                    report="已出报（不合格）",
                    vendor_batch_no="V-9901",
                    quantity=300,
                )
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["unqualified_created"] == 1
        assert summary["rejected_gates"] == 1

        # 生成记录字段映射（Base 权威去重键 SourceID + 业务字段）
        assert len(adapter.created_records) == 1
        created = adapter.created_records[0]
        assert created["table"] == "unqualified_stock"
        fields = created["record"]["fields"]
        assert fields["SourceID"] == "r_rej"
        assert fields["物料名称"] == "硫酸"
        assert fields["厂家批号"] == "V-9901"
        assert fields["内部批号"] == "B-REJ"
        assert fields["到货数量"] == 300
        assert isinstance(fields["到货日期"], int)  # 毫秒时间戳
        assert isinstance(fields["登记时间"], int)
        assert "登记人" not in fields  # 留空人工后补

        assert len(gates) == 1
        gate = gates[0]
        assert gate["business_type"] == "qc_rejected_disposition"
        assert gate["ref_table"] == "unqualified_stock"
        assert gate["ref_record_ids"] == [created["record"]["record_id"]]
        assert gate["writeback"] == {"处理日期": "@today"}
        assert gate["target"] == "oc_qa_group"

    async def test_existing_source_skips_generation_heals_gate(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SourceID 已存在（Base 权威去重）不重建记录；门缺失时自愈补门。"""

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_rej", batch_no="B-REJ", sample="已取样", report="已出报（不合格）"
                )
            ],
            unqualified_records=[
                {
                    "record_id": "unq_existing",
                    "fields": {"SourceID": "r_rej", "物料名称": "硫酸"},
                }
            ],
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["unqualified_created"] == 0
        assert summary["rejected_gates"] == 1
        assert adapter.created_records == []
        assert gates[0]["ref_record_ids"] == ["unq_existing"]

    async def test_pending_gate_no_recreate(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """记录与 pending 门都在 → 什么都不做。"""

        from app.modules.warehouse import confirm_request as cr

        await _hermetic_alerts(db_session)
        _qc_switch_on(monkeypatch)
        gates = _gate_capture(monkeypatch)

        db_session.add(
            await cr.create_request(
                db_session,
                business_type="qc_rejected_disposition",
                title="处理方案确认",
                summary="既有门",
                ref_table="unqualified_stock",
                ref_record_ids=["unq_existing"],
                target="oc_qa",
                writeback={"处理日期": "@today"},
            )
        )
        await db_session.flush()

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_rej", batch_no="B-REJ", sample="已取样", report="已出报（不合格）"
                )
            ],
            unqualified_records=[
                {
                    "record_id": "unq_existing",
                    "fields": {"SourceID": "r_rej", "物料名称": "硫酸"},
                }
            ],
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["unqualified_created"] == 0
        assert summary["rejected_gates"] == 0
        assert gates == []

    async def test_switch_off_skips_generation(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        await _hermetic_alerts(db_session)
        _qc_switch_off(monkeypatch)
        gates = _gate_capture(monkeypatch)

        adapter = FakeQcBase(
            [
                _receipt_record(
                    "r_rej", batch_no="B-REJ", sample="已取样", report="已出报（不合格）"
                )
            ]
        )
        summary = await qc_flow.run_qc_scan(
            db_session, datetime.now(UTC), adapter=adapter
        )
        assert summary["unqualified_created"] == 0
        assert summary["rejected_gates"] == 0
        assert adapter.created_records == []
        assert gates == []

