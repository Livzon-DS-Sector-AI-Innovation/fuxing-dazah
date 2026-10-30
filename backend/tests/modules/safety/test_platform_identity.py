"""3.x 平台身份卡（PlatformIdentityService / F3）— 匹配链五态 + 三态降级。

覆盖：
- 纯函数 match_platform_user：零行/单行/多行部门收窄/多行放弃；
- 匹配链：工号命中（job_no）→ 姓名单命中（name_dept）→ 姓名多命中收窄 →
  多命中放弃（P3 不猜测）→ 零命中 → 平台字段全容空；
- 三态信封：live（TTL 缓存复用）/ degraded（平台失败回退缓存时点，含缓存
  结论为 unmatched 的复合态）/ empty（失败且无缓存）；unmatched 同样进缓存；
- 隐私红线：payload 不含 idCardNo 等敏感键；无工号无姓名直接 unmatched；
- 缓存返回拷贝：消费方改写不污染共享缓存。

样本数据全部合成（字段形态对齐 2026-10-30 实弹探测的响应结构，
不含任何真实员工个人信息）。
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.safety.service.platform_identity import (
    PlatformIdentityService,
    build_identity_person,
    match_platform_user,
)


class _Person:
    """duck-type 匹配入参（直读 OhRowView / 镜像 OhPerson 同形）。"""

    def __init__(
        self, name: str = "", employee_no: str = "", department: str = ""
    ) -> None:
        self.name = name
        self.employee_no = employee_no
        self.department = department


class _StubClient:
    """account/query + user/detail 替身：按查询键回放行、计数、可切换故障。"""

    def __init__(
        self,
        account_rows: dict[str, list[dict[str, Any]]] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._account_rows = account_rows or {}
        self._detail = detail or {}
        self.fail = False
        self.account_calls: list[dict[str, str]] = []
        self.detail_calls: list[str] = []

    async def query_account(self, params: dict[str, str]) -> list[dict[str, Any]]:
        self.account_calls.append(dict(params))
        if self.fail:
            raise RuntimeError("platform down")
        key = params.get("jobNo") or params.get("nickname") or ""
        return [dict(r) for r in self._account_rows.get(key, [])]

    async def user_detail(self, user_id: str) -> dict[str, Any]:
        self.detail_calls.append(user_id)
        if self.fail:
            raise RuntimeError("platform down")
        return dict(self._detail)


def _detail_row(**over: Any) -> dict[str, Any]:
    """user/detail 合成样本（形态对齐实弹探测：张国东锚定例的字段轮廓）。"""
    base = {
        "id": "9001", "postName": "电焊工", "deptName": "合成厂一部",
        "deptWholeName": "测试公司/合成厂一部",
        "directLeaderId": "8001", "directLeaderName": "李班组长",
        "jobNo": "900000001", "telephone": "13900000001",
        "email": "pingce@test.example", "status": 1, "entryDate": None,
        "idCardNo": "",  # 平台恒空；投影层必须剔除
    }
    base.update(over)
    return base


def _svc(client: _StubClient, **kw: Any) -> PlatformIdentityService:
    return PlatformIdentityService(client=client, **kw)


# ── 纯函数 match_platform_user ──


def test_match_zero_rows() -> None:
    assert match_platform_user({"department": "合成厂一部"}, []) is None


def test_match_single_row() -> None:
    row = {"id": "9001", "deptName": ""}
    assert match_platform_user({"department": "合成厂一部"}, [row]) is row


def test_match_multi_rows_narrowed_by_dept() -> None:
    a = {"id": "1", "deptName": "合成厂二部"}
    b = {"id": "2", "deptName": "合成厂一部"}
    got = match_platform_user(
        {"department": "合成厂一部"}, [a, b],
    )
    assert got is b


def test_match_multi_rows_dept_empty_gives_up() -> None:
    # 实测形态：account/query 行内 deptName 恒空 → 收窄失败 → 放弃（P3）
    rows = [{"id": "1", "deptName": ""}, {"id": "2", "deptName": ""}]
    assert match_platform_user({"department": "合成厂一部"}, rows) is None


def test_match_multi_rows_same_dept_gives_up() -> None:
    rows = [{"id": "1", "deptName": "合成厂一部"}, {"id": "2", "deptName": "合成厂一部"}]
    assert match_platform_user({"department": "合成厂一部"}, rows) is None


# ── 匹配链（service + 替身）──


async def test_job_no_hit() -> None:
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001", "nickname": "平测甲", "jobNo": "900000001"}]},
        detail=_detail_row(),
    )
    payload = await _svc(client).get_identity(
        _Person(name="平测甲", employee_no="900000001", department="合成厂一部")
    )
    assert payload["status"] == "live"
    assert payload["match_basis"] == "job_no"
    assert payload["person"]["platform_id"] == "9001"
    assert payload["person"]["post_name"] == "电焊工"
    assert payload["person"]["status"] == "在职"
    # 只打 jobNo 查询 + detail 两跳
    assert client.account_calls == [{"jobNo": "900000001"}]
    assert client.detail_calls == ["9001"]


async def test_name_single_hit_after_job_no_miss() -> None:
    client = _StubClient(
        account_rows={"平测乙": [{"id": "9002", "nickname": "平测乙", "jobNo": "900000002"}]},
        detail=_detail_row(
            id="9002", postName="粗提操作工", deptName="合成厂二部",
            jobNo="900000002", directLeaderName="周班组长", email="", telephone="13900000002",
        ),
    )
    payload = await _svc(client).get_identity(
        _Person(name="平测乙", employee_no="900000009", department="合成厂一部")
    )
    assert payload["status"] == "live"
    assert payload["match_basis"] == "name_dept"
    assert payload["person"]["dept_name"] == "合成厂二部"
    # 工号 miss 后回退姓名查询
    assert client.account_calls == [
        {"jobNo": "900000009"}, {"nickname": "平测乙"},
    ]


async def test_name_multi_hit_narrowed_by_dept() -> None:
    client = _StubClient(
        account_rows={
            "王五": [
                {"id": "1", "nickname": "王五", "deptName": "合成厂二部"},
                {"id": "2", "nickname": "王五", "deptName": "合成厂一部"},
            ],
        },
        detail=_detail_row(id="2", postName="操作工", deptName="合成厂一部"),
    )
    payload = await _svc(client).get_identity(
        _Person(name="王五", department="合成厂一部")
    )
    assert payload["status"] == "live"
    assert payload["match_basis"] == "name_dept"
    assert payload["person"]["platform_id"] == "2"


async def test_name_multi_hit_gives_up_unmatched() -> None:
    client = _StubClient(
        account_rows={"王五": [{"id": "1"}, {"id": "2"}]},
    )
    payload = await _svc(client).get_identity(_Person(name="王五", department="合成厂一部"))
    assert payload["status"] == "unmatched"
    assert payload["match_basis"] is None
    assert payload["person"] is None
    assert client.detail_calls == []


async def test_zero_hit_unmatched() -> None:
    client = _StubClient(account_rows={})
    payload = await _svc(client).get_identity(
        _Person(name="赵六", employee_no="900000000", department="合成厂一部")
    )
    assert payload["status"] == "unmatched"
    assert payload["person"] is None
    assert payload["fetched_at"] is not None


async def test_platform_fields_all_empty_tolerated() -> None:
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001"}]},
        detail={"id": "9001"},  # 平台大面积空：除 id 外全空
    )
    payload = await _svc(client).get_identity(
        _Person(name="平测甲", employee_no="900000001")
    )
    assert payload["status"] == "live"
    person = payload["person"]
    assert person["platform_id"] == "9001"
    for field in (
        "post_name", "dept_name", "dept_whole_name", "direct_leader",
        "job_no", "telephone", "email", "status", "entry_date",
    ):
        assert person[field] is None


# ── 隐私红线 ──


async def test_payload_never_contains_id_card() -> None:
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001", "idCardNo": "330000199001010000"}]},
        detail=_detail_row(idCardNo="330000199001010000"),
    )
    payload = await _svc(client).get_identity(
        _Person(name="平测甲", employee_no="900000001")
    )
    assert "id_card_no" not in payload["person"]
    assert "idCardNo" not in json.dumps(payload, ensure_ascii=False)
    assert set(payload["person"]) == {
        "platform_id", "post_name", "dept_name", "dept_whole_name",
        "direct_leader", "job_no", "telephone", "email", "status", "entry_date",
    }


def test_build_identity_person_status_mapping() -> None:
    assert build_identity_person({"id": "1", "status": 1})["status"] == "在职"
    assert build_identity_person({"id": "1", "status": 0})["status"] == "离职"
    assert build_identity_person({"id": "1", "status": None})["status"] is None


# ── 缓存与三态 ──


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_live_payload_cached_within_ttl() -> None:
    clock = _Clock()
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001"}]}, detail=_detail_row(),
    )
    svc = _svc(client, ttl_seconds=600, clock=clock)
    person = _Person(name="平测甲", employee_no="900000001")
    first = await svc.get_identity(person)
    clock.now += 100  # TTL 窗口内
    second = await svc.get_identity(person)
    assert second == first
    assert second is not first  # 返回拷贝，不是共享缓存引用
    assert len(client.account_calls) == 1  # 未重打平台
    assert len(client.detail_calls) == 1


async def test_cached_payload_not_polluted_by_consumer() -> None:
    # 消费方原地改写返回值，不得污染缓存（下次命中仍是干净数据）
    clock = _Clock()
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001"}]}, detail=_detail_row(),
    )
    svc = _svc(client, ttl_seconds=600, clock=clock)
    person = _Person(name="平测甲", employee_no="900000001")
    first = await svc.get_identity(person)
    first["person"]["post_name"] = "被改写"
    first["status"] = "被改写"
    clock.now += 100
    again = await svc.get_identity(person)
    assert again["status"] == "live"
    assert again["person"]["post_name"] == "电焊工"


async def test_degraded_after_ttl_with_cached_person() -> None:
    clock = _Clock()
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001"}]}, detail=_detail_row(),
    )
    svc = _svc(client, ttl_seconds=600, clock=clock)
    person = _Person(name="平测甲", employee_no="900000001")
    live = await svc.get_identity(person)
    clock.now += 700  # 过期
    client.fail = True
    degraded = await svc.get_identity(person)
    assert degraded["status"] == "degraded"
    assert degraded["fetched_at"] == live["fetched_at"]
    assert degraded["person"] == live["person"]
    assert degraded["match_basis"] == "job_no"
    assert "缓存时点" in degraded["message"]


async def test_degraded_with_cached_unmatched_conclusion() -> None:
    # 缓存的是 unmatched 结论、TTL 过期后平台故障 → degraded + person=None
    clock = _Clock()
    client = _StubClient(account_rows={"王五": [{"id": "1"}, {"id": "2"}]})
    svc = _svc(client, ttl_seconds=600, clock=clock)
    person = _Person(name="王五", department="合成厂一部")
    first = await svc.get_identity(person)
    assert first["status"] == "unmatched"
    clock.now += 700
    client.fail = True
    degraded = await svc.get_identity(person)
    assert degraded["status"] == "degraded"
    assert degraded["person"] is None
    assert degraded["fetched_at"] == first["fetched_at"]
    assert degraded["message"]


async def test_empty_when_platform_down_without_cache() -> None:
    client = _StubClient()
    client.fail = True
    payload = await _svc(client).get_identity(
        _Person(name="平测甲", employee_no="900000001")
    )
    assert payload["status"] == "empty"
    assert payload["fetched_at"] is None
    assert payload["person"] is None
    assert payload["message"]


async def test_unmatched_cached_no_repeat_calls() -> None:
    clock = _Clock()
    client = _StubClient(account_rows={"王五": [{"id": "1"}, {"id": "2"}]})
    svc = _svc(client, ttl_seconds=600, clock=clock)
    person = _Person(name="王五", department="合成厂一部")
    first = await svc.get_identity(person)
    clock.now += 100
    second = await svc.get_identity(person)
    assert second == first
    assert first["status"] == "unmatched"
    assert len(client.account_calls) == 1


async def test_ttl_zero_disables_cache() -> None:
    client = _StubClient(
        account_rows={"900000001": [{"id": "9001"}]}, detail=_detail_row(),
    )
    svc = _svc(client, ttl_seconds=0)
    person = _Person(name="平测甲", employee_no="900000001")
    await svc.get_identity(person)
    await svc.get_identity(person)
    assert len(client.account_calls) == 2


async def test_no_name_no_employee_no_directly_unmatched() -> None:
    client = _StubClient()
    payload = await _svc(client).get_identity(_Person(department="合成厂一部"))
    assert payload["status"] == "unmatched"
    assert client.account_calls == []


async def test_match_input_composite_cache_key() -> None:
    # 工号空 vs 工号有值是不同匹配入参 → 不同缓存键，各自打平台
    clock = _Clock()
    client = _StubClient(
        account_rows={
            "900000001": [{"id": "9001"}],
            "平测甲": [{"id": "9001"}],
        },
        detail=_detail_row(),
    )
    svc = _svc(client, ttl_seconds=600, clock=clock)
    with_no = _Person(name="平测甲", employee_no="900000001")
    without_no = _Person(name="平测甲")
    first = await svc.get_identity(with_no)
    second = await svc.get_identity(without_no)
    assert first["match_basis"] == "job_no"
    assert second["match_basis"] == "name_dept"
    assert len(client.account_calls) == 2
