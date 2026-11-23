"""设施摘除红色预警提醒单测——记录解析/卡面/编排节奏/调度接线。

零真机：bitable 拉取、Redis、推送层全 stub（conftest autouse 已钉推送隔离，
本文件再对 interlock_warning 自身引用点显式打桩，防 DM 真发）。
数据形态实测 2026-11-18（base FGUHbF1DJamdjJskoKhcj7kbngf / tblWlELZ5YiKMB95，49 行）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.safety.service.interlock_warning import cards
from app.modules.safety.service.interlock_warning import records as iw_records


@pytest.fixture(autouse=True)
def _pin_notification_send(monkeypatch: pytest.MonkeyPatch):
    """兜底钉死真发（spec 测试决策；seam 注入 send 桩已隔离，此处防旁路）。"""
    import app.modules.safety.feishu.notification as notification

    async def _refuse(*a, **kw):
        raise AssertionError("测试不得真发飞书消息")

    monkeypatch.setattr(notification, "send_user_card", _refuse)
    monkeypatch.setattr(notification, "send_user_card_dict", _refuse)

# ═══════════════════════════════════════════════════════════
# 工具：真实形态字段样例（2026-11-18 实测导出回放）
# ═══════════════════════════════════════════════════════════

_APPLINK = (
    "https://applink.feishu.cn/client/mini_program/open?appId=cli_9cb844403dbb9108"
    "&mode=appCenter&path_pc=pc/pages/in-process/index%3FinstanceId%3D7708668647694339073"
)


def _red_fields(**override: Any) -> dict[str, Any]:
    """202611160468（安全阀·压缩空气/氮气储罐）实测 raw API 形态（2026-11-18）。"""
    fields: dict[str, Any] = {
        # 申请编号=单 dict 段（首版误按 list 段实现致卡面显示 record_id/缺链接）
        "申请编号": {"text": "202611160468", "link": _APPLINK, "type": "url"},
        "部门": ["提炼工程四部"],              # 单选 list[str] 形态
        "安全设施类型": "安全阀",
        "是否为关键装置、重点部位": "是",
        "岗位及设备设施名称": [
            {"type": "text", "text": "车间二一区北侧室外 压缩空气储罐和氮气储罐"}
        ],
        "变更时间": 1794758400000,    # 2026-11-16 北京零点
        "预计恢复时间": 1794844800000,  # 2026-11-17 北京零点
        "预警状态": {"type": 3, "value": ["二级红色报警"]},  # 公式 dict
        "审批节点": "恢复确认",
        "当前处理人": [{"id": "ou_a0b8317208bcfea168aec27f5aa2f2bc", "name": "林建水"}],
        "发起人": [{"id": "ou_d271e8941997ce93090b29010b89f318", "name": "徐家树"}],
        "工艺负责人": [{"id": "ou_4cbf57b78687dfad6f5f11eeb798617c", "name": "陈熙捷"}],
        "安全负责人": [{"id": "ou_0a634b9915f38f668094ebb2666c723f", "name": "杨昆"}],
    }
    fields.update(override)
    return fields


def _normal_fields() -> dict[str, Any]:
    return _red_fields(
        预警状态=[{"type": "text", "text": "正常"}],
        申请状态="已通过",
    )


# ═══════════════════════════════════════════════════════════
# Ticket 01 · 数据源注册 + 记录解析纯函数
# ═══════════════════════════════════════════════════════════

class TestRegistryConnection:
    def test_default_connection_resolves(self):
        from app.modules.safety.bitable_config.store import store

        view = store.get_connection("interlock_change", "approval")
        assert view.status == "default"
        assert view.enabled is True
        assert view.app_token == "FGUHbF1DJamdjJskoKhcj7kbngf"
        assert view.table_id == "tblWlELZ5YiKMB95"


class TestParseHelpers:
    def test_flat_text_variants(self):
        from app.modules.safety.service.interlock_warning.records import flat_text

        assert flat_text("审批中") == "审批中"
        assert flat_text([{"type": "text", "text": "二级红色报警"}]) == "二级红色报警"
        # 公式列 dict 形态（{"type":3,"value":[str]} / {"type":1,"value":[{"text":...}]}）
        assert flat_text({"type": 3, "value": ["二级红色报警"]}) == "二级红色报警"
        assert flat_text({"type": 1, "value": [{"text": "正常"}]}) == "正常"
        # 单 dict 段（申请编号 raw 实测形态）
        assert flat_text({"text": "202611160468", "link": _APPLINK, "type": "url"}) == "202611160468"
        assert flat_text(["是"]) == "是"          # select 兜底（str 元素）
        assert flat_text(None) is None
        assert flat_text([]) is None

    def test_parse_person_list(self):
        from app.modules.safety.service.interlock_warning.records import parse_person_list

        got = parse_person_list(
            [{"id": "ou_a", "name": "张三"}, {"id": "ou_b", "name": "李四"}]
        )
        assert got == (("张三", "ou_a"), ("李四", "ou_b"))
        assert parse_person_list(None) == ()
        assert parse_person_list([]) == ()
        assert parse_person_list(["脏数据"]) == ()
        # 缺 id 的成员跳过（有名字没 open_id 无法私发）
        assert parse_person_list([{"id": "", "name": "王五"}]) == ()

    def test_extract_applink(self):
        from app.modules.safety.service.interlock_warning.records import extract_applink

        # 单 dict 段（raw API 实测）
        assert extract_applink(
            {"text": "202611160468", "link": _APPLINK, "type": "url"}
        ) == _APPLINK
        # list 段兼容形态
        assert extract_applink(
            [{"type": "text", "text": "202611160468", "link": _APPLINK}]
        ) == _APPLINK
        # 富文本无链接段 → None
        assert extract_applink([{"type": "text", "text": "202611160468"}]) is None
        assert extract_applink(None) is None

    def test_ms_to_date(self):
        from app.modules.safety.service.interlock_warning.records import ms_to_date

        # 1794758400000 = 2026-11-16 北京零点（实测换算）
        assert ms_to_date(1794758400000) == "2026-11-16"
        assert ms_to_date(None) is None
        assert ms_to_date("脏") is None

    def test_overdue_days(self):
        from app.modules.safety.service.interlock_warning.records import overdue_days

        assert overdue_days(date(2026, 11, 18), "2026-11-17") == 1
        assert overdue_days(date(2026, 11, 18), "2026-06-28") == 143
        assert overdue_days(date(2026, 11, 18), None) is None


class TestFilterRedRecords:
    def test_red_record_parsed(self):
        from app.modules.safety.service.interlock_warning.records import (
            filter_red_records,
        )

        got = filter_red_records(
            [{"record_id": "recA", "fields": _red_fields()}],
            today=date(2026, 11, 18),
        )
        assert len(got) == 1
        rec = got[0]
        assert rec.record_id == "recA"
        assert rec.code == "202611160468"
        assert rec.approval_url == _APPLINK
        assert rec.department == "提炼工程四部"
        assert rec.facility_type == "安全阀"
        assert rec.is_critical is True
        assert rec.location.startswith("车间二一区北侧室外")
        assert rec.changed_on == "2026-11-16"
        assert rec.expected_recovery_on == "2026-11-17"
        assert rec.overdue_days == 1
        assert rec.node == "恢复确认"
        assert rec.handler_name == "林建水"
        assert rec.applicants == (("徐家树", "ou_d271e8941997ce93090b29010b89f318"),)
        assert rec.process_owners == (("陈熙捷", "ou_4cbf57b78687dfad6f5f11eeb798617c"),)
        assert rec.safety_owners == (("杨昆", "ou_0a634b9915f38f668094ebb2666c723f"),)

    def test_normal_and_empty_excluded(self):
        from app.modules.safety.service.interlock_warning.records import (
            filter_red_records,
        )

        rows = [
            {"record_id": "recN", "fields": _normal_fields()},
            {"record_id": "recE", "fields": {"部门": "提炼工程四部"}},
        ]
        assert filter_red_records(rows, today=date(2026, 11, 18)) == []

    def test_location_truncated_and_not_critical(self):
        from app.modules.safety.service.interlock_warning.records import (
            filter_red_records,
        )

        long_loc = "长" * 120
        fields = _red_fields(岗位及设备设施名称=[{"type": "text", "text": long_loc}])
        fields["是否为关键装置、重点部位"] = "否"
        got = filter_red_records(
            [{"record_id": "recL", "fields": fields}],
            today=date(2026, 11, 18),
        )
        assert len(got[0].location) == 80
        assert got[0].is_critical is False


# ═══════════════════════════════════════════════════════════
# Ticket 02 · 卡面构建 + 编排（节奏锚/轮次/聚合/发送）
# ═══════════════════════════════════════════════════════════

def _red_record(**kw) -> iw_records.RedRecord:
    """与 _red_fields() 对齐的 RedRecord 直造件（卡面/编排测试用）。"""
    base = dict(
        record_id="recA",
        code="202611160468",
        approval_url=_APPLINK,
        department="提炼工程四部",
        facility_type="安全阀",
        is_critical=True,
        location="车间二一区北侧室外 压缩空气储罐和氮气储罐",
        changed_on="2026-11-16",
        expected_recovery_on="2026-11-17",
        overdue_days=1,
        node="恢复确认",
        handler_name="林建水",
        applicants=(("徐家树", "ou_xujiashu"),),
        process_owners=(("陈熙捷", "ou_chenxijie"),),
        safety_owners=(("杨昆", "ou_yangkun"),),
    )
    base.update(kw)
    return iw_records.RedRecord(**base)


class TestBuildCard:
    def test_card_content_fields(self):
        title, content = cards.build_warning_card(
            "陈熙捷",
            [(_red_record(), ("工艺负责人",))],
            rounds={"recA": 2},
        )
        assert title == "🔴 安全设施摘除超期·红色预警提醒"
        for expect in (
            "202611160468", "提炼工程四部", "安全阀（关键装置/重点部位）",
            "压缩空气储罐和氮气储罐", "2026-11-16", "2026-11-17",
            "已超期：**1 天**", "恢复确认（处理人：林建水）",
            "您的角色：工艺负责人", "第2次提醒",
            f"[查看审批详情]({_APPLINK})",
            "base/FGUHbF1DJamdjJskoKhcj7kbngf?table=tblWlELZ5YiKMB95&record=recA",
        ):
            assert expect in content, f"卡面缺字段: {expect}"

    def test_overdue_escalation_and_missing(self):
        _, heavy = cards.build_warning_card(
            "高伟祺", [(_red_record(overdue_days=143, record_id="recB"), ("工艺负责人",))],
            rounds={"recB": 72},
        )
        assert "已超期：**143 天** ⚠️⚠️⚠️" in heavy and "第72次提醒" in heavy
        _, blank = cards.build_warning_card(
            "张三", [(_red_record(overdue_days=None, expected_recovery_on=None), ("发起人",))],
            rounds={},
        )
        assert "未填预计恢复时间" in blank and "第" not in blank.split("未填预计恢复时间")[0]

    def test_multi_records_one_card_and_roles_merged(self):
        rec2 = _red_record(record_id="recC", code="202610260673", overdue_days=8)
        _, content = cards.build_warning_card(
            "蔡嘉旺",
            [(_red_record(), ("发起人", "安全负责人")), (rec2, ("安全负责人",))],
            rounds={},
        )
        assert content.count("202611160468") == 1 and "202610260673" in content
        assert "您的角色：发起人、安全负责人" in content


class _FakeRedis:
    """内存 Redis 假件（对齐 daily_report FakeRedis，补 incr/scan/delete）。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def incr(self, key):
        self.data[key] = str(int(self.data.get(key, "0")) + 1)
        return int(self.data[key])

    async def scan_iter(self, match=None):
        for key in list(self.data):
            if match is None or key.startswith(match.rstrip("*")):
                yield key

    async def delete(self, *keys):
        n = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                n += 1
        return n


class TestRunInterlockRedWarning:
    @staticmethod
    def _seam_fields() -> dict[str, Any]:
        """seam 测试字段：三角色换短 ou（便于断言），其余同 _red_fields()。"""
        return _red_fields(
            发起人=[{"id": "ou_xujiashu", "name": "徐家树"}],
            工艺负责人=[{"id": "ou_chenxijie", "name": "陈熙捷"}],
            安全负责人=[{"id": "ou_yangkun", "name": "杨昆"}],
        )

    async def test_first_round_sends_and_increments(self, monkeypatch):
        from app.modules.safety.service.interlock_warning import service

        sent: list[tuple] = []

        async def _send(open_id, title, content, **kw):
            sent.append((open_id, title, content, kw))
            return "om_ok"

        rows = [
            {"record_id": "recA", "fields": self._seam_fields()},
            {   # 三角色全空 → skip
                "record_id": "recEmpty",
                "fields": _red_fields(
                    发起人=None, 工艺负责人=None, 安全负责人=None,
                ),
            },
            {"record_id": "recN", "fields": _normal_fields()},
        ]

        async def _fetch():
            return rows

        redis = _FakeRedis()
        stats = await service.run_interlock_red_warning(
            fetch=_fetch, redis=redis, send=_send, now=date(2026, 11, 18),
        )
        assert stats == {
            "red": 2, "recipients": 3, "sent": 3, "failed": 0,
            "skipped_no_recipient": 1, "dry_run": False,
        }
        assert {s[0] for s in sent} == {"ou_xujiashu", "ou_chenxijie", "ou_yangkun"}
        assert all(s[3].get("header_template") == "red" for s in sent)
        # 轮次=1、锚=执行日
        assert redis.data["safety:interlock_red:round:recA"] == "1"
        assert redis.data["safety:interlock_red:last_sent"] == "2026-11-18"
        # 空收件人记录不 INCR
        assert "safety:interlock_red:round:recEmpty" not in redis.data

    async def test_gap_anchor_skips_until_two_days(self):
        from app.modules.safety.service.interlock_warning import service

        async def _fetch():
            return [{"record_id": "recA", "fields": self._seam_fields()}]

        async def _send(*a, **kw):
            return "om_ok"

        redis = _FakeRedis()
        redis.data["safety:interlock_red:last_sent"] = "2026-11-17"  # 昨日 → 跳过
        stats = await service.run_interlock_red_warning(
            fetch=_fetch, redis=redis, send=_send, now=date(2026, 11, 18),
        )
        assert stats == {"skipped_gap": True, "last_sent": "2026-11-17"}

        redis.data["safety:interlock_red:last_sent"] = "2026-11-16"  # 前天 → 发
        stats = await service.run_interlock_red_warning(
            fetch=_fetch, redis=redis, send=_send, now=date(2026, 11, 18),
        )
        assert stats["sent"] == 3  # 三角色各一卡

    async def test_redis_failure_fail_closed(self):
        from app.modules.safety.service.interlock_warning import service

        class _BrokenRedis:
            async def get(self, key):
                raise ConnectionError("redis down")

        stats = await service.run_interlock_red_warning(
            fetch=None, redis=_BrokenRedis(), send=None, now=date(2026, 11, 18),
        )
        assert stats == {"skipped_redis": True}

    async def test_round_increments_and_stale_cleanup(self):
        from app.modules.safety.service.interlock_warning import service

        async def _fetch():
            return [{"record_id": "recA", "fields": self._seam_fields()}]

        sent_contents: list[str] = []

        async def _send(open_id, title, content, **kw):
            sent_contents.append(content)
            return "om_ok"

        redis = _FakeRedis()
        redis.data["safety:interlock_red:round:recA"] = "1"
        redis.data["safety:interlock_red:round:recGone"] = "9"  # 已非红 → 清键

        await service.run_interlock_red_warning(
            fetch=_fetch, redis=redis, send=_send, now=date(2026, 11, 18),
        )
        assert redis.data["safety:interlock_red:round:recA"] == "2"
        assert "第2次提醒" in sent_contents[0]
        assert "safety:interlock_red:round:recGone" not in redis.data

    async def test_dry_run_no_send_no_write(self, capsys):
        from app.modules.safety.service.interlock_warning import service

        async def _fetch():
            return [{"record_id": "recA", "fields": self._seam_fields()}]

        async def _boom(*a, **kw):
            raise AssertionError("dry_run 不得发送")

        redis = _FakeRedis()
        stats = await service.run_interlock_red_warning(
            dry_run=True, fetch=_fetch, redis=redis, send=_boom,
            now=date(2026, 11, 18),
        )
        assert stats["dry_run"] is True and stats["sent"] == 0
        assert redis.data == {}  # 零写入（锚/轮次都不落）
        out = capsys.readouterr().out
        assert "ou_xujiashu" in out and "202611160468" in out

    async def test_send_failure_counted_no_raise(self):
        from app.modules.safety.service.interlock_warning import service

        async def _fetch():
            return [{"record_id": "recA", "fields": self._seam_fields()}]

        async def _send(open_id, title, content, **kw):
            return open_id == "ou_xujiashu" and "om_ok"  # 两人失败一人成功

        redis = _FakeRedis()
        stats = await service.run_interlock_red_warning(
            fetch=_fetch, redis=redis, send=_send, now=date(2026, 11, 18),
        )
        assert stats["sent"] == 1 and stats["failed"] == 2
        # 有 ≥1 成功即计轮次（该记录第 1 轮成立）
        assert redis.data["safety:interlock_red:round:recA"] == "1"


# ═══════════════════════════════════════════════════════════
# Ticket 03 · 调度接线 + 开关
# ═══════════════════════════════════════════════════════════

JOB_NAME = "设施摘除红色预警提醒"


class TestSchedulerWiring:
    def test_job_registered_fields(self):
        from app.modules.safety.scheduler import SCHEDULED_JOBS

        matches = [j for j in SCHEDULED_JOBS if j["name"] == JOB_NAME]
        assert len(matches) == 1
        job = matches[0]
        assert job["hour"] == 9 and job["minute"] == 0
        assert job.get("target_type") == "person"
        assert job.get("retry_until_hour") == 12
        assert "SAFETY_INTERLOCK_RED_WARNING_ENABLED" in job["description"]

    def test_app_config_flag_default_on(self):
        from app.modules.safety.app_config.registry import get_item

        item = get_item("SAFETY_INTERLOCK_RED_WARNING_ENABLED")
        assert item.default is True
        assert item.category == "feature_flag"

    async def test_wrapper_disabled_silent(self, monkeypatch):
        from app.modules.safety import scheduler
        from app.modules.safety.service.interlock_warning import (
            config as iw_config,
            service as iw_service,
        )

        monkeypatch.setattr(iw_config, "enabled", lambda: False)

        async def _boom(**kw):
            raise AssertionError("开关关闭不得触达 service")

        monkeypatch.setattr(iw_service, "run_interlock_red_warning", _boom)
        assert await scheduler._run_interlock_red_warning() is False

    async def test_wrapper_calls_service(self, monkeypatch):
        from app.modules.safety import scheduler
        from app.modules.safety.service.interlock_warning import (
            config as iw_config,
            service as iw_service,
        )

        monkeypatch.setattr(iw_config, "enabled", lambda: True)
        seen: list[dict] = []

        async def _fake_run(**kw):
            seen.append(kw)
            return {"red": 4, "sent": 8}

        monkeypatch.setattr(iw_service, "run_interlock_red_warning", _fake_run)
        assert await scheduler._run_interlock_red_warning() is False
        assert seen == [{}]  # 无参调用（dry_run 默认 False=真发路径）

    async def test_wrapper_no_source_sentinel(self, monkeypatch):
        from app.modules.safety import scheduler
        from app.modules.safety.service.bitable_direct.errors import (
            BitableConfigError,
        )
        from app.modules.safety.service.interlock_warning import (
            config as iw_config,
            service as iw_service,
        )

        monkeypatch.setattr(iw_config, "enabled", lambda: True)

        async def _raise(**kw):
            raise BitableConfigError("interlock_change/approval 未登记")

        monkeypatch.setattr(iw_service, "run_interlock_red_warning", _raise)
        assert await scheduler._run_interlock_red_warning() is True  # no_source

    async def test_dispatch_branch_wired(self, monkeypatch):
        from app.modules.safety import scheduler

        called: list[str] = []
        monkeypatch.setattr(scheduler, "_matches_day", lambda job, today: True)

        async def _should_run(job, today, now=None):
            return True

        async def _load_state(job_name):
            return None

        async def _save_state(job_name, state):
            return None

        async def _wrapper():
            called.append(JOB_NAME)
            return False  # 非 no_source

        monkeypatch.setattr(scheduler, "_should_run", _should_run)
        monkeypatch.setattr(scheduler, "_load_state", _load_state)
        monkeypatch.setattr(scheduler, "_save_state", _save_state)
        monkeypatch.setattr(scheduler, "_run_interlock_red_warning", _wrapper)
        got = await scheduler._run_scheduled_job(
            {"name": JOB_NAME, "hour": 9, "minute": 0}
        )
        assert got is True and called == [JOB_NAME]

