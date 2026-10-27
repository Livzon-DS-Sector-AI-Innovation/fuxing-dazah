"""岗位字典（3.x 平台全员主档去重，F1）——service 与端点测试。

接缝：build_post_rows 纯函数（输入主档内存行，输出去重岗位清单）与
OrgPostsService.get_payload（client 构造注入替身；日级 TTL 缓存 +
live/degraded/empty 三态，同 contractor_workers 信封口径）。
个人明细不落库不返回（隐私口径，spec §Implementation Decisions）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.safety.service.org_directory import (
    OrgPostsService,
    build_post_rows,
)


def _user(post: str | None, dept: str | None = "精制工程一部") -> dict:
    return {
        "id": str(abs(hash(f"{post}{dept}")) % 10_000_000),
        "nickname": "张三",
        "jobNo": "A0001",
        "accountName": "zhangsan",
        "deptName": dept,
        "postName": post,
        "idCardNo": "",
    }


class TestBuildPostRows:
    def test_dedupe_and_aggregate_depts(self) -> None:
        rows = build_post_rows(
            [
                _user("1#冻干线冻干出料操作工"),
                _user("1#冻干线冻干出料操作工", dept="精制工程二部"),
                _user("电工", dept="动力部"),
            ]
        )
        assert len(rows) == 2
        freeze = next(r for r in rows if "冻干" in r["post_name"])
        assert freeze["dept_names"] == ["精制工程一部", "精制工程二部"]
        assert freeze["headcount"] == 2
        electrician = next(r for r in rows if r["post_name"] == "电工")
        assert electrician["dept_names"] == ["动力部"]
        assert electrician["headcount"] == 1

    def test_empty_post_name_skipped(self) -> None:
        rows = build_post_rows([_user(None), _user(""), _user("操作工")])
        assert [r["post_name"] for r in rows] == ["操作工"]

    def test_no_personal_fields_in_output(self) -> None:
        import json

        rows = build_post_rows([_user("操作工")])
        raw = json.dumps(rows, ensure_ascii=False)
        for personal in ("nickname", "jobNo", "accountName", "张三", "A0001"):
            assert personal not in raw


class TestOrgPostsService:
    def _service(
        self, users: list[dict], *, fail: bool = False, clock_times: list[float] | None = None
    ) -> tuple[OrgPostsService, _FakeOrgClient]:
        client = _FakeOrgClient(users, fail=fail)
        times = list(clock_times or [0.0])

        def clock() -> float:
            return times.pop(0) if len(times) > 1 else times[0]

        svc = OrgPostsService(
            client=client,
            ttl_seconds=86_400,
            clock=clock,
            now_fn=lambda: datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc),
        )
        return svc, client

    async def test_live_payload_with_filters(self) -> None:
        svc, _ = self._service(
            [
                _user("1#冻干线冻干出料操作工"),
                _user("1#冻干线冻干出料操作工", dept="精制工程二部"),
                _user("电工", dept="动力部"),
            ]
        )
        payload = await svc.get_payload()
        assert payload["status"] == "live"
        assert payload["fetched_at"].startswith("2026-10-26T10:00")
        # 岗位字典按 post_name 分组（冻干聚合两个部门 + 电工）
        assert len(payload["posts"]) == 2

        filtered = await svc.get_payload(dept="精制")
        assert [p["post_name"] for p in filtered["posts"]] == [
            "1#冻干线冻干出料操作工"
        ]
        assert filtered["posts"][0]["dept_names"] == [
            "精制工程一部", "精制工程二部",
        ]

        by_keyword = await svc.get_payload(keyword="电工")
        assert [p["post_name"] for p in by_keyword["posts"]] == ["电工"]

    async def test_ttl_hit_no_refetch(self) -> None:
        svc, client = self._service([_user("操作工")], clock_times=[0.0, 100.0])
        await svc.get_payload()
        await svc.get_payload()
        assert client.calls == 1

    async def test_empty_when_first_fetch_fails(self) -> None:
        svc, _ = self._service([], fail=True)
        payload = await svc.get_payload()
        assert payload["status"] == "empty"
        assert payload["posts"] == []
        assert payload["message"]

    async def test_degraded_after_failure_with_cache(self) -> None:
        svc, client = self._service([_user("操作工")], clock_times=[0.0, 99_999.0])
        live = await svc.get_payload()
        client.fail = True
        degraded = await svc.get_payload()
        assert degraded["status"] == "degraded"
        assert degraded["posts"] == live["posts"]
        assert degraded["fetched_at"] == live["fetched_at"]


class _FakeOrgClient:
    def __init__(self, users: list[dict], *, fail: bool = False) -> None:
        self._users = users
        self.fail = fail
        self.calls = 0

    async def list_org_users(self) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("平台接口不可用")
        return self._users


class TestEndpoint:
    async def test_org_posts_envelope_passthrough(self, client, monkeypatch) -> None:
        from app.modules.safety.api import contractor_workers as api_module

        class _StubService:
            async def get_payload(
                self, dept: str | None = None, keyword: str | None = None
            ) -> dict:
                return {
                    "status": "live",
                    "fetched_at": "2026-10-26T10:00:00+08:00",
                    "message": None,
                    "posts": [{"post_name": "电工", "dept_names": ["动力部"], "headcount": 3}],
                }

            def cached_all_posts(self) -> list[dict] | None:
                # #4 族聚合的全厂口径来源（无缓存时 API 回退过滤后的 posts）
                return [{"post_name": "电工", "dept_names": ["动力部"], "headcount": 3}]

        monkeypatch.setattr(api_module, "open_org_posts_service", lambda: _StubService())
        resp = await client.get("/api/v1/safety/contractor-workers/org-posts")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["status"] == "live"
        assert body["data"]["posts"][0]["post_name"] == "电工"
