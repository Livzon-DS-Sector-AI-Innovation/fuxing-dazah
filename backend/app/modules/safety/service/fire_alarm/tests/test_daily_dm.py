"""消防报警日报私发 — 单测（无 DB / 无飞书依赖）。

覆盖：
- build_alarm_card：模板 v2 字段齐全/缺省省略、部位兜底、链接兜底、red header
- dept_recipients：DEPT_CONFIG 权威名单优先、DEPT_NORMALIZE 归一化、
  未命中配置回退记录自带负责人、安全员未配置只发负责人
- send_daily_alarm_dms：开关关闭跳过；union_id 解析/发送成败统计（mock）
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.safety.service.fire_alarm.daily_dm import (
    build_alarm_card,
    collect_recipient_plans,
    dept_recipients,
    send_daily_alarm_dms,
)
from app.modules.safety.service.fire_alarm.service import (
    FireAlarmService,
    run_daily_fire_alarm_dm,
)


def make_record(**kw) -> MagicMock:
    """构造最小 FireAlarmRecord 替身（仅暴露私发用到的属性）。"""
    r = MagicMock()
    r.id = kw.get("id", "uuid-1")
    r.alarm_time = kw.get("alarm_time", datetime(2026, 8, 28, 1, 8, tzinfo=UTC))
    r.alarm_type = kw.get("alarm_type", "火灾报警")
    r.alarm_nature = kw.get("alarm_nature", "误报")
    r.department = kw.get("department", "提炼工程二部")
    r.building = kw.get("building", "妥布车间")
    r.location = kw.get("location", "一层洁净传递室103号感烟")
    r.cause_description = kw.get("cause_description", "收粉粉尘引发报警。")
    r.ai_reason_analysis = kw.get("reason", "车间收粉作业产生粉尘，触发感烟探测器报警。")
    r.ai_rectification_direction = kw.get("direction", "优化收粉除尘措施，定期清洁感烟探测器。")
    r.department_leader_name = kw.get("leader_name", "蔡万进")
    r.feishu_record_id = kw.get("record_id", "recvtv123")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# build_alarm_card — 模板 v2
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildAlarmCard:
    def test_full_template(self):
        content, card = build_alarm_card(make_record())
        assert content.startswith("**提炼工程二部** ｜ 🚨 **火灾报警**｜误报")
        assert "⏰ 报警时间：08/28 09:08" in content
        assert "📍 部位：妥布车间一层洁净传递室103号感烟" in content
        assert "① **报警原因**：收粉粉尘引发报警。" in content
        assert "② **原因分析（AI）**：车间收粉作业产生粉尘" in content
        assert "③ **整改建议（AI）**：优化收粉除尘措施" in content
        assert "部门负责人：蔡万进" in content
        assert "🔗 [查看记录](https://j0eukrlohu.feishu.cn/base/MGX1bLhasaRx6usKOodcVpXGnTb?table=tblgtwoBn4SMBSGj&record=recvtv123)" in content

    def test_card_header(self):
        _, card = build_alarm_card(make_record())
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "red"
        assert card["header"]["title"]["content"] == "🚨 消防报警 · 提炼工程二部"
        assert card["body"]["elements"][0]["tag"] == "markdown"

    def test_leader_name_arg_wins(self):
        content, _ = build_alarm_card(make_record(), leader_name="王五")
        assert "部门负责人：王五" in content
        assert "部门负责人：蔡万进" not in content

    def test_service_no_ai_omits_lines(self):
        rec = make_record(reason=None, direction=None, cause_description=None)
        content, _ = build_alarm_card(rec)
        assert "① **报警原因**" not in content
        assert "② **原因分析（AI）**" not in content
        assert "③ **整改建议（AI）**" not in content
        assert "⏰ 报警时间：08/28 09:08" in content

    def test_place_fallback(self):
        rec = make_record(building=None, location=None)
        content, _ = build_alarm_card(rec)
        assert "📍 部位：待确认" in content

    def test_no_record_id_link_fallback(self):
        rec = make_record(record_id=None)
        content, _ = build_alarm_card(rec)
        assert "🔗 查看记录（无原表链接）" in content


# ═══════════════════════════════════════════════════════════════════════════
# dept_recipients / collect_recipient_plans
# ═══════════════════════════════════════════════════════════════════════════


class TestDeptRecipients:
    def test_config_hit(self):
        roles = dept_recipients(make_record(department="提炼工程二部"))
        assert roles == {"部门负责人": "蔡万进", "分管安全员": "李伟豪"}

    def test_normalize_department(self):
        # 「设备工程部, 项目部」→ DEPT_NORMALIZE → 「设备工程部」
        roles = dept_recipients(make_record(department="设备工程部, 项目部"))
        assert roles == {"部门负责人": "杨银杉", "分管安全员": "林恒"}

    def test_fallback_to_record_leader_when_no_config(self):
        rec = make_record(department="未知新部门", leader_name="赵六")
        roles = dept_recipients(rec)
        assert roles == {"部门负责人": "赵六"}

    def test_no_safety_officer_only_leader(self):
        # 法规注册部（RA部）未配置 safety_officer
        roles = dept_recipients(make_record(department="法规注册部（RA部）", leader_name="蔡榕斌"))
        assert roles == {"部门负责人": "蔡榕斌"}

    def test_all_missing_returns_empty(self):
        rec = make_record(department="未知新部门", leader_name=None)
        assert dept_recipients(rec) == {}

    def test_extra_recipient_for_extraction_1(self):
        # 提炼工程一部：现有 林礼枫+郑雅杰 之外追加分管领导吴志华
        roles = dept_recipients(make_record(department="提炼工程一部"))
        assert roles == {
            "部门负责人": "林礼枫",
            "分管安全员": "郑雅杰",
            "分管领导": "吴志华",
        }

    def test_extra_recipient_only_for_configured_dept(self):
        # 提炼工程三部（分管领导同为吴志华）不追加；提炼工程二部默认不受影响
        roles = dept_recipients(make_record(department="提炼工程三部"))
        assert roles == {"部门负责人": "林礼枫", "分管安全员": "郑雅杰"}
        roles = dept_recipients(make_record(department="提炼工程二部"))
        assert roles == {"部门负责人": "蔡万进", "分管安全员": "李伟豪"}

    def test_collect_recipient_plans(self):
        records = [make_record(), make_record(department="提炼工程五部", leader_name="林东态")]
        plans = collect_recipient_plans(records)
        assert len(plans) == 2
        record, roles = plans[0]
        assert "分管安全员" in roles


# ═══════════════════════════════════════════════════════════════════════════
# send_daily_alarm_dms — 编排统计（mock 身份查询 / union_id / 发送）
# ═══════════════════════════════════════════════════════════════════════════


def _patch_deps(emails: dict[str, str], uid_map: dict[str, str], send_ok: bool = True):
    """mock 身份邮箱查询、union_id 解析、DM 发送（含飞书 client/token）。"""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch(
        "app.modules.safety.service.fire_alarm.daily_dm.load_identity_emails",
        new=AsyncMock(return_value=emails),
    ))
    stack.enter_context(patch(
        "app.modules.safety.service.fire_alarm.daily_dm.resolve_union_ids",
        new=AsyncMock(return_value=uid_map),
    ))
    stack.enter_context(patch(
        "app.modules.safety.service.fire_alarm.daily_dm.send_user_card",
        new=AsyncMock(return_value=send_ok),
    ))
    stack.enter_context(patch(
        "app.modules.safety.feishu.client.get_safety_feishu_client",
        new=AsyncMock(return_value=MagicMock()),
    ))
    stack.enter_context(patch(
        "app.modules.safety.feishu.client.get_safety_tenant_token",
        new=AsyncMock(return_value="test-token"),
    ))
    return stack


class TestSendDailyAlarmDms:
    def test_disabled_by_switch(self, monkeypatch):
        import app.modules.safety.service.fire_alarm.daily_dm as daily_dm

        monkeypatch.setattr(daily_dm, "DM_ENABLED", False)
        stats = _run([make_record()], {}, {})
        assert stats == {"disabled": 1, "sent": 0, "skipped": 0, "errors": 0, "unresolved": 0}

    def test_empty_records(self, monkeypatch):
        import app.modules.safety.service.fire_alarm.daily_dm as daily_dm

        monkeypatch.setattr(daily_dm, "DM_ENABLED", True)
        stats = _run([], {}, {})
        assert stats == {"sent": 0, "skipped": 0, "errors": 0, "unresolved": 0}

    def test_send_to_leader_and_officer(self, monkeypatch):
        import app.modules.safety.service.fire_alarm.daily_dm as daily_dm

        monkeypatch.setattr(daily_dm, "DM_ENABLED", True)
        stats = _run(
            [make_record(department="提炼工程二部")],
            {"蔡万进": "caiwanjin@livzon.cn", "李伟豪": "liweihao@livzon.cn"},
            {"caiwanjin@livzon.cn": "uni_cai", "liweihao@livzon.cn": "uni_li"},
        )
        assert stats == {"sent": 2, "skipped": 0, "errors": 0, "unresolved": 0}

    def test_send_with_extra_recipient_same_card_content(self, monkeypatch):
        # 提炼工程一部：3 人 3 卡（林礼枫/郑雅杰/吴志华），卡片内容完全一致
        import app.modules.safety.service.fire_alarm.daily_dm as daily_dm

        monkeypatch.setattr(daily_dm, "DM_ENABLED", True)
        emails = {
            "林礼枫": "linlifeng@livzon.cn",
            "郑雅杰": "zhengyajie01@livzon.cn",
            "吴志华": "wuzhihua@livzon.cn",
        }
        uid_map = {
            "linlifeng@livzon.cn": "uni_lin",
            "zhengyajie01@livzon.cn": "uni_zheng",
            "wuzhihua@livzon.cn": "uni_wu",
        }
        # mock 需在 with 上下文内保持生效：await_args_list 要在撤销前读取
        with _patch_deps(emails, uid_map):
            stats = asyncio_run(send_daily_alarm_dms(
                MagicMock(),
                records=[make_record(department="提炼工程一部")],
            ))
            calls = daily_dm.send_user_card.await_args_list
        assert stats == {"sent": 3, "skipped": 0, "errors": 0, "unresolved": 0}
        # 卡片不区分收件人：3 次发送传入的 content 相同
        assert len(calls) == 3
        assert len({c.kwargs["content"] for c in calls}) == 1

    def test_unresolved_union_id_counts(self, monkeypatch):
        import app.modules.safety.service.fire_alarm.daily_dm as daily_dm

        monkeypatch.setattr(daily_dm, "DM_ENABLED", True)
        stats = _run(
            [make_record(department="提炼工程二部")],
            {"蔡万进": "caiwanjin@livzon.cn", "李伟豪": "liweihao@livzon.cn"},
            {"caiwanjin@livzon.cn": "uni_cai"},  # 李伟豪未解析
        )
        assert stats == {"sent": 1, "skipped": 0, "errors": 0, "unresolved": 1}

    def test_send_failure_counts_skipped(self, monkeypatch):
        import app.modules.safety.service.fire_alarm.daily_dm as daily_dm

        monkeypatch.setattr(daily_dm, "DM_ENABLED", True)
        stats = _run(
            [make_record(department="提炼工程二部")],
            {"蔡万进": "caiwanjin@livzon.cn", "李伟豪": "liweihao@livzon.cn"},
            {"caiwanjin@livzon.cn": "uni_cai", "liweihao@livzon.cn": "uni_li"},
            send_ok=False,
        )
        assert stats == {"sent": 0, "skipped": 2, "errors": 0, "unresolved": 0}


# ═══════════════════════════════════════════════════════════════════════════
# run_daily_fire_alarm_dm — 定时任务入口（同步 → 生成复用 AI → 私发）
# ═══════════════════════════════════════════════════════════════════════════


class _AsyncSessionCtx:
    """async_session_factory 的 async 上下文替身（返回预置 session）。"""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class TestRunDailyFireAlarmDm:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.fire_alarm.daily_dm.DM_ENABLED", False,
        )
        assert asyncio_run(run_daily_fire_alarm_dm()) is None

    def test_enabled_full_flow(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.fire_alarm.daily_dm.DM_ENABLED", True,
        )
        stats = {"sent": 2, "skipped": 0, "errors": 0, "unresolved": 0}
        session = AsyncMock()
        factory = MagicMock(return_value=_AsyncSessionCtx(session))
        with (
            patch("app.core.database.async_session_factory", new=factory),
            patch.object(
                FireAlarmService, "sync_from_bitable",
                AsyncMock(return_value=(3, 0)),
            ),
            patch.object(
                FireAlarmService, "generate_daily_report", AsyncMock()
            ),
            patch.object(
                FireAlarmService, "_get_records_by_rolling_window",
                AsyncMock(return_value=([], None, None)),
            ),
            patch(
                "app.modules.safety.service.fire_alarm.daily_dm.send_daily_alarm_dms",
                AsyncMock(return_value=stats),
            ),
        ):
            result = asyncio_run(run_daily_fire_alarm_dm())
        assert result == stats


def _run(records, emails, uid_map, send_ok: bool = True) -> dict[str, int]:
    """执行 send_daily_alarm_dms（带 deps mock），返回统计。"""
    session = MagicMock()
    with _patch_deps(emails, uid_map, send_ok):
        return asyncio_run(send_daily_alarm_dms(session, records=records))


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
