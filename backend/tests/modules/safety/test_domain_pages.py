"""四新域页面骨架三态测试（3.0 四期 1-B）。

口径：docs/DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md §6。
2026-10-21：goals 域改走体系标准核查引擎（test_standard_check_*.py），
本文件只覆盖 training-behavior/facilities/incidents 三域。

接缝（照 cert_direct test_reader 手法）：
- opener 注入（domain, kind -> BitablePageClient 协议替身）验证 live/degraded；
- not_connected 走真 store 路径（registry 默认连接=None → BitableConfigError，
  conftest app_config DB stub 与 bitable store fail-open 都不改变该结局）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.service.bitable_direct.errors import BitableQueryError
from app.modules.safety.service.domain_pages import (
    DOMAIN_PAGE_KEYS,
    build_domain_page,
    collect_domain_health,
)


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


class FakePageClient:
    """BitablePageClient 协议替身：预置记录一次性返回。"""

    def __init__(self, items: list[dict[str, Any]], *, boom: bool = False) -> None:
        self._items = items
        self._boom = boom

    async def search_records(self, **kwargs: Any) -> dict[str, Any]:
        if self._boom:
            raise BitableQueryError("Bitable 查询失败: code=1254043")
        return {"items": self._items, "has_more": False, "page_token": None}


def _rec(record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"record_id": record_id, "fields": fields}


class TestRegistryPlaceholderDomains:
    def test_four_domains_registered_without_connections(self) -> None:
        from app.modules.safety.bitable_config import registry

        for domain_key in ("goals", "training_behavior", "facilities", "incidents"):
            info = registry.get_domain(domain_key)
            assert info.subscribe == "record"
            assert info.kinds, f"{domain_key} 应有 kind"
            assert all(k.default_connection is None for k in info.kinds), (
                f"{domain_key} 占位域不应带默认连接（防播种/订阅）"
            )

    def test_placeholder_kinds_not_seeded(self) -> None:
        from app.modules.safety.bitable_config import registry

        seeded = {(d.key, k.kind) for d, k in registry.iter_connection_kinds()}
        assert not any(k in seeded for k in (
            ("goals", "goal_indicator"), ("training_behavior", "violation"),
            ("facilities", "equipment_ledger"), ("incidents", "capa"),
        ))


class TestBuildDomainPage:
    async def test_not_connected_is_default_state(self) -> None:
        """未接入（真路径）：registry 连接位空 → not_connected 信封。"""
        data = await build_domain_page("training-behavior")
        assert data["status"] == "not_connected"
        assert data["stats"] is None
        assert data["ledger"]["data"] == []
        assert data["ledger"]["meta"] == {"total": 0, "page": 1, "page_size": 20}
        assert data["errors"] == []

    async def test_degraded_on_query_error(self) -> None:
        """降级：连接有效但读取失败 → degraded + errors 标注。"""
        data = await build_domain_page(
            "training-behavior", opener=lambda d, k: FakePageClient([], boom=True)
        )
        assert data["status"] == "degraded"
        assert data["stats"] is None
        assert data["ledger"]["data"] == []
        assert data["errors"] and "training" in data["errors"][0]

    async def test_unknown_domain_key_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="未知"):
            await build_domain_page("no-such-domain")


class TestCollectDomainHealth:
    async def test_not_connected(self) -> None:
        part = await collect_domain_health("training-behavior")
        assert part == {"connected": False}

class TestDomainPageKeys:
    def test_keys_align_frontend_menu(self) -> None:
        assert DOMAIN_PAGE_KEYS == ("training-behavior", "facilities", "incidents")


class TestTrainingAndIncidentsLive:
    """training-behavior / incidents 的 live 统计口径（蓝本 §3.4/§5.4）。"""

    async def test_training_behavior_stats_and_health(self) -> None:
        today = _bj_today()
        training_items = [
            _rec("t1", {"培训名称": "入厂三级教育", "计划日期": _ms(today - timedelta(days=5)),
                        "状态": "已完成", "考核方式": "考试", "实到人数": "10",
                        "考核合格人数": "9"}),
            _rec("t2", {"培训名称": "年度复训", "计划日期": _ms(today + timedelta(days=10)),
                        "状态": "未开始", "考核方式": "考试", "实到人数": "8",
                        "考核合格人数": "4"}),
            _rec("t3", {"培训名称": "专项培训", "计划日期": _ms(today - timedelta(days=1)),
                        "状态": "进行中"}),  # 计划逾期未实施 → warn 判据之一
            _rec("t4", {"培训名称": "去年培训", "计划日期": _ms(today - timedelta(days=400)),
                        "状态": "已完成"}),
            _rec("t5", {"培训名称": "取消的培训", "计划日期": _ms(today), "状态": "已取消"}),
        ]
        violation_items = [
            _rec("v1", {"违章日期": _ms(today - timedelta(days=2)), "状态": "已纠正"}),
            _rec("v2", {"违章日期": _ms(today - timedelta(days=1)), "状态": "纠正中"}),
            # 往年违章：不计入年度次数，但「未纠正」是存量口径仍计入
            _rec("v3", {"违章日期": _ms(today - timedelta(days=400)), "状态": "纠正中"}),
        ]
        fixtures = {
            "training": FakePageClient(training_items),
            "violation": FakePageClient(violation_items),
        }
        data = await build_domain_page("training-behavior", opener=lambda d, k: fixtures[k])
        assert data["status"] == "live"
        stats = data["stats"]
        assert stats["training_total"] == 3  # 当年且非取消
        assert stats["completion_rate"] == 33  # 1/3
        assert stats["pass_rate"] == 72  # 13/18（考试场次合计）
        assert stats["retraining_due_30d"] == 0
        assert stats["violation_total"] == 2
        assert stats["violation_open"] == 2

        part = await collect_domain_health(
            "training-behavior", opener=lambda d, k: fixtures[k]
        )
        assert part["health_status"] == "warn"  # 未纠正 2 + 逾期未实施 1
        assert "培训 1/3" in part["health_metric"]
        assert "未纠正 2" in part["health_metric"]

    async def test_incidents_stats_and_health(self) -> None:
        today = _bj_today()
        incident_items = [
            _rec("x1", {"事件编号": "EV-01", "发生日期": _ms(today - timedelta(days=2)),
                        "事件类别": "事故", "状态": "调查中"}),
            _rec("x2", {"事件编号": "EV-02", "发生日期": _ms(today - timedelta(days=1)),
                        "事件类别": "未遂事件", "状态": "已结案"}),
            _rec("x3", {"事件编号": "EV-03", "发生日期": _ms(today - timedelta(days=40)),
                        "事件类别": "事故", "状态": "调查中"}),  # 超 30 天未结案 → warn 判据之一
            _rec("x4", {"事件编号": "EV-00", "发生日期": _ms(today - timedelta(days=400)),
                        "事件类别": "事故", "状态": "已结案"}),  # 去年不计
        ]
        capa_items = [
            _rec("c1", {"关联事件编号": "EV-01", "措施类型": "纠正", "状态": "已完成"}),
            _rec("c2", {"关联事件编号": "EV-02", "措施类型": "预防", "状态": "已逾期"}),
            _rec("c3", {"关联事件编号": "EV-03", "措施类型": "纠正", "状态": "进行中"}),
        ]
        fixtures = {
            "incident": FakePageClient(incident_items),
            "capa": FakePageClient(capa_items),
        }
        data = await build_domain_page("incidents", opener=lambda d, k: fixtures[k])
        assert data["status"] == "live"
        stats = data["stats"]
        assert stats["incident_total"] == 3
        assert stats["accident_count"] == 2
        assert stats["near_miss_count"] == 1
        assert stats["investigating_count"] == 2
        assert stats["capa_open"] == 2
        assert stats["capa_overdue"] == 1

        part = await collect_domain_health("incidents", opener=lambda d, k: fixtures[k])
        assert part["health_status"] == "warn"  # CAPA 逾期 1 + 超30天调查 1
        assert "今年事件 3" in part["health_metric"]
        assert "CAPA 未闭环 2" in part["health_metric"]
