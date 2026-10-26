"""承包商在册人员（3.x 平台台账）F1——交叉规则与三态信封测试。

接缝：service 纯函数（build_rows/build_stats 等，输入三源内存数据 + today）
与 ContractorWorkersService.get_payload（读取器全部构造注入替身）。
口径见 .scratch/f1-contractor-workers/spec.md 附录 A（2026-10-26 拍板）。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

from app.modules.safety.service.cert_direct.reader import CertWarningView
from app.modules.safety.service.contractor_workers import (
    ContractorWorkersService,
    build_rows,
    build_stats,
    is_special_work_type,
    match_notice_company,
    split_name_pool,
)
from app.modules.safety.service.visitor_insurance.reader import VisitorNoticeView

TODAY = date(2026, 10, 26)


def _worker(
    name: str,
    contractor: str,
    *,
    work_type: str | None = "普工",
    age: int | None = 40,
    card: str = "350100199001016592",
    phone: str = "13900001667",
) -> dict:
    return {
        "id": f"211017584179515392{abs(hash(name)) % 10}",
        "name": name,
        "beforeName": name,
        "contractorId": 11,
        "contractorName": contractor,
        "workTypeId": 2,
        "workTypeName": work_type,
        "cardType": "居民身份证",
        "cardNo": card,
        "telphone": phone,
        "birthDate": f"{2026 - (age or 40)}-05-22",
        "age": age,
        "sex": 1,
        "health": "良好",
        "education": "小学",
        "major": "无",
        "joinJobDate": "2025-12-01",
        "bind": False,
        "certificateStatus": None,
        "status": None,
    }


def _notice(
    company: str,
    names: str,
    insurance_end: date | None,
    *,
    status: str = "已通过",
) -> VisitorNoticeView:
    return VisitorNoticeView(
        record_id=f"rec{abs(hash(company + names)) % 10000}",
        company=company,
        names=names,
        people_count=len(names.split("，")),
        work_content="检修",
        work_scope="全厂",
        status=status,
        entry_start=TODAY,
        entry_end=TODAY,
        insurance_end=insurance_end,
    )


def _cert(person: str, project: str, review: date | None) -> CertWarningView:
    return CertWarningView(
        cert_category="special_op",
        person_name=person,
        project=project,
        next_review_date=review,
    )


class _SequenceClock:
    """按序列吐出单调时钟读数（耗尽后停最后一个值），测试推进 TTL 用。"""

    def __init__(self, times: list[float]) -> None:
        self._times = list(times)

    def __call__(self) -> float:
        if len(self._times) > 1:
            return self._times.pop(0)
        return self._times[0]


class _FakePlatform:
    """list_contractor_users 替身；fail 置位后抛错模拟平台不可用。"""

    def __init__(self, workers: list[dict], *, fail: bool = False) -> None:
        self._workers = workers
        self.fail = fail
        self.calls = 0

    async def list_contractor_users(self) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("平台接口不可用")
        return self._workers


class _FakeNoticeReader:
    def __init__(self, notices: list[VisitorNoticeView]) -> None:
        self._notices = notices

    async def fetch_all(self) -> list[VisitorNoticeView]:
        return self._notices


class _FakeCertReader:
    def __init__(self, certs: list[CertWarningView]) -> None:
        self._certs = certs

    async def get_all_active(self, *, strict: bool = False) -> list[CertWarningView]:
        return self._certs


class TestSplitNamePool:
    def test_mixed_separators(self) -> None:
        assert split_name_pool("郭天宇，许梦辰、韩伟, 罗辉\n李四") == {
            "郭天宇", "许梦辰", "韩伟", "罗辉", "李四",
        }

    def test_empty(self) -> None:
        assert split_name_pool("") == set()
        assert split_name_pool(None) == set()  # type: ignore[arg-type]


class TestMatchNoticeCompany:
    def test_exact_beats_contains(self) -> None:
        companies = {"福清市一建建筑工程有限公司", "一建建筑工程有限公司"}
        assert (
            match_notice_company("福清市一建建筑工程有限公司", companies)
            == "福清市一建建筑工程有限公司"
        )

    def test_contains_fallback(self) -> None:
        companies = {"福清市馨福园农业科技有限公司"}
        assert (
            match_notice_company("馨福园", companies)
            == "福清市馨福园农业科技有限公司"
        )

    def test_no_match(self) -> None:
        assert match_notice_company("河北航越机电", {"福清市一建建筑工程有限公司"}) is None


class TestSpecialWorkType:
    def test_keywords(self) -> None:
        assert is_special_work_type("焊工")
        assert is_special_work_type("电工")
        assert is_special_work_type("架子工")
        assert is_special_work_type("电工,焊工")

    def test_non_special(self) -> None:
        assert not is_special_work_type("普工")
        assert not is_special_work_type("驾驶员")
        assert not is_special_work_type(None)
        assert not is_special_work_type("")


class TestInsuranceCross:
    def _row(self, notices, name="施瑞国", contractor="福清市一建建筑工程有限公司"):
        rows = build_rows([_worker(name, contractor)], notices, [], TODAY)
        assert len(rows) == 1
        return rows[0]

    def test_covered(self) -> None:
        row = self._row(
            [_notice("福清市一建建筑工程有限公司", "施瑞国", date(2027, 6, 1))]
        )
        assert row["insurance_status"] == "covered"
        assert row["insurance_expire_date"] == "2027-06-01"

    def test_expiry_today_counts_as_expiring_last_day(self) -> None:
        # 边界口径对齐 visitor_insurance：有效期至=当天仍有效，属临期最后一天
        row = self._row([_notice("福清市一建建筑工程有限公司", "施瑞国", TODAY)])
        assert row["insurance_status"] == "expiring"
        assert row["insurance_days_left"] == 0

    def test_expiring_boundary_30_days(self) -> None:
        row = self._row(
            [_notice("福清市一建建筑工程有限公司", "施瑞国", date(2026, 11, 25))]
        )
        assert row["insurance_status"] == "expiring"
        assert row["insurance_days_left"] == 30
        row31 = self._row(
            [_notice("福清市一建建筑工程有限公司", "施瑞国", date(2026, 11, 26))]
        )
        assert row31["insurance_status"] == "covered"

    def test_expired(self) -> None:
        row = self._row(
            [_notice("福清市一建建筑工程有限公司", "施瑞国", date(2026, 10, 25))]
        )
        assert row["insurance_status"] == "expired"

    def test_unfiled_when_notice_without_expiry(self) -> None:
        row = self._row([_notice("福清市一建建筑工程有限公司", "施瑞国", None)])
        assert row["insurance_status"] == "unfiled"

    def test_uncovered_when_person_not_on_notice(self) -> None:
        row = self._row([_notice("福清市一建建筑工程有限公司", "张三", TODAY)])
        assert row["insurance_status"] == "uncovered"

    def test_uncovered_when_company_unmatched(self) -> None:
        row = self._row(
            [_notice("江苏天目建设集团有限公司", "施瑞国", TODAY)],
            contractor="河北航越机电设备安装工程有限公司",
        )
        assert row["insurance_status"] == "uncovered"

    def test_latest_expiry_wins_among_matched_notices(self) -> None:
        row = self._row(
            [
                _notice("福清市一建建筑工程有限公司", "施瑞国", date(2026, 11, 1)),
                _notice("福清市一建建筑工程有限公司", "施瑞国", date(2027, 6, 1)),
            ]
        )
        assert row["insurance_expire_date"] == "2027-06-01"

    def test_non_approved_notice_ignored(self) -> None:
        row = self._row(
            [
                replace(
                    _notice("福清市一建建筑工程有限公司", "施瑞国", TODAY),
                    status="审批中",
                )
            ]
        )
        assert row["insurance_status"] == "uncovered"

    def test_company_contains_match(self) -> None:
        row = self._row(
            [_notice("福清市馨福园农业科技有限公司", "施瑞国", date(2027, 6, 1))],
            contractor="馨福园",
        )
        assert row["insurance_status"] == "covered"


class TestCertCross:
    def test_hit_shows_project_and_review(self) -> None:
        rows = build_rows(
            [_worker("许垚鹏", "江苏天目建设集团有限公司", work_type="焊工")],
            [],
            [_cert("许垚鹏", "熔化焊接与热切割作业", date(2027, 3, 1))],
            TODAY,
        )
        row = rows[0]
        assert row["cert_status"] == "hit"
        assert row["cert_project"] == "熔化焊接与热切割作业"
        assert row["cert_next_review_date"] == "2027-03-01"

    def test_hit_joins_multiple_certs_and_nearest_review(self) -> None:
        rows = build_rows(
            [_worker("李伟", "江苏天目建设集团有限公司", work_type="电工,焊工")],
            [],
            [
                _cert("李伟", "低压电工作业", date(2028, 1, 1)),
                _cert("李伟", "熔化焊接与热切割作业", date(2027, 1, 1)),
            ],
            TODAY,
        )
        row = rows[0]
        assert row["cert_status"] == "hit"
        assert row["cert_project"] == "低压电工作业、熔化焊接与热切割作业"
        assert row["cert_next_review_date"] == "2027-01-01"

    def test_missing_for_special(self) -> None:
        rows = build_rows(
            [_worker("王五", "江苏天目建设集团有限公司", work_type="焊工")],
            [],
            [_cert("赵六", "熔化焊接与热切割作业", None)],
            TODAY,
        )
        assert rows[0]["cert_status"] == "missing"

    def test_nonspecial(self) -> None:
        rows = build_rows(
            [_worker("王五", "江苏天目建设集团有限公司", work_type="普工")],
            [],
            [_cert("王五", "熔化焊接与热切割作业", None)],
            TODAY,
        )
        assert rows[0]["cert_status"] == "nonspecial"

    def test_non_special_op_category_ignored(self) -> None:
        rows = build_rows(
            [_worker("许垚鹏", "江苏天目建设集团有限公司", work_type="焊工")],
            [],
            [
                replace(
                    _cert("许垚鹏", "监护人A证", None),
                    cert_category="guardian_a",
                )
            ],
            TODAY,
        )
        assert rows[0]["cert_status"] == "missing"


class TestAgeCross:
    def test_flags(self) -> None:
        def flag(age: int | None) -> str:
            rows = build_rows(
                [_worker("甲", "某公司", age=age)], [], [], TODAY
            )
            return rows[0]["age_flag"]

        assert flag(54) == "none"
        assert flag(55) == "yellow"
        assert flag(59) == "yellow"
        assert flag(60) == "red"
        assert flag(72) == "red"
        assert flag(None) == "none"


class TestMasking:
    def test_card_and_phone_masked_no_plaintext(self) -> None:
        import json

        rows = build_rows(
            [_worker("施瑞国", "福清市一建建筑工程有限公司", card="350100199001016592")],
            [],
            [],
            TODAY,
        )
        row = rows[0]
        # mask_secret 口径：保前 3 后 2，固定三颗星
        assert row["card_no_masked"] == "350***92"
        assert row["phone_masked"] == "139***67"
        # 全量明文不得出现在行数据任何位置
        assert "350100199001016592" not in json.dumps(row, ensure_ascii=False)
        assert "13900001667" not in json.dumps(row, ensure_ascii=False)


class TestStats:
    def test_worked_example(self) -> None:
        rows = build_rows(
            [
                _worker("甲", "甲公司", work_type="焊工", age=61),          # 特种无证/超龄/未覆盖
                _worker("乙", "甲公司", work_type="焊工", age=30),          # 特种有证/覆盖
                _worker("丙", "乙公司", work_type="普工", age=56),          # 非特种/黄龄/临期
            ],
            [
                _notice("甲公司", "乙", date(2027, 1, 1)),
                _notice("乙公司", "丙", date(2026, 11, 10)),  # 距 TODAY 15 天 → 临期
            ],
            [_cert("乙", "熔化焊接与热切割作业", None)],
            TODAY,
        )
        stats = build_stats(rows)
        assert stats["total"] == 3
        assert stats["contractors"] == 2
        # 有效覆盖 = covered+expiring = 乙+丙 = 2/3 → 67
        assert stats["insurance_covered_pct"] == 67
        # 特种 2 人（甲乙），命中 1 → 50
        assert stats["special_total"] == 2
        assert stats["cert_covered_pct"] == 50
        assert stats["overage_count"] == 1
        assert stats["overage_warn_count"] == 1


class TestServiceEnvelope:
    def _service(
        self,
        workers: list[dict],
        notices: list[VisitorNoticeView],
        certs: list[CertWarningView],
        *,
        clock_times: list[float] | None = None,
    ) -> tuple[ContractorWorkersService, "_FakePlatform"]:
        platform = _FakePlatform(workers)
        svc = ContractorWorkersService(
            platform_client=platform,
            notice_reader=_FakeNoticeReader(notices),
            cert_reader=_FakeCertReader(certs),
            ttl_seconds=600,
            clock=_SequenceClock(clock_times or [0.0]),
            now_fn=lambda: datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc),
            today_fn=lambda: TODAY,
        )
        return svc, platform

    async def test_live_payload(self) -> None:
        svc, _ = self._service(
            [_worker("施瑞国", "福清市一建建筑工程有限公司")],
            [_notice("福清市一建建筑工程有限公司", "施瑞国", TODAY)],
            [],
        )
        payload = await svc.get_payload()
        assert payload["status"] == "live"
        assert payload["fetched_at"].startswith("2026-10-26T10:00")
        assert payload["stats"]["total"] == 1
        assert len(payload["workers"]) == 1
        assert payload["workers"][0]["name"] == "施瑞国"

    async def test_ttl_hit_serves_cache_without_refetch(self) -> None:
        svc, platform = self._service(
            [_worker("甲", "甲公司")], [], [], clock_times=[0.0, 100.0, 200.0]
        )
        await svc.get_payload()
        await svc.get_payload()  # TTL 窗口内（100s < 600s）
        assert platform.calls == 1

    async def test_degraded_after_failure_with_cache(self) -> None:
        svc, platform = self._service(
            [_worker("甲", "甲公司")], [], [], clock_times=[0.0, 9999.0]
        )
        live = await svc.get_payload()
        assert live["status"] == "live"

        platform.fail = True  # 第二次调用时钟已越过 TTL → 强制重拉 → 失败
        degraded = await svc.get_payload()
        assert degraded["status"] == "degraded"
        assert degraded["workers"] == live["workers"]
        assert degraded["fetched_at"] == live["fetched_at"]
        assert degraded["message"]

    async def test_empty_when_first_fetch_fails(self) -> None:
        platform = _FakePlatform([], fail=True)
        svc = ContractorWorkersService(
            platform_client=platform,
            notice_reader=_FakeNoticeReader([]),
            cert_reader=_FakeCertReader([]),
            ttl_seconds=600,
            clock=_SequenceClock([0.0]),
            now_fn=lambda: datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc),
            today_fn=lambda: TODAY,
        )
        payload = await svc.get_payload()
        assert payload["status"] == "empty"
        assert payload["workers"] == []
        assert payload["stats"] is None
        assert payload["message"]


class TestEndpoint:
    async def test_get_contractor_workers_envelope_passthrough(
        self, client, monkeypatch
    ) -> None:
        from httpx import AsyncClient

        from app.modules.safety.api import contractor_workers as api_module

        rows = build_rows(
            [_worker("施瑞国", "福清市一建建筑工程有限公司", work_type="焊工", age=61)],
            [],
            [],
            TODAY,
        )

        class _StubService:
            async def get_payload(self) -> dict:
                return {
                    "status": "live",
                    "fetched_at": "2026-10-26T10:00:00+08:00",
                    "message": None,
                    "stats": build_stats(rows),
                    "workers": rows,
                }

        monkeypatch.setattr(api_module, "open_service", lambda: _StubService())
        resp = await client.get("/api/v1/safety/contractor-workers")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert data["status"] == "live"
        assert data["stats"]["total"] == 1
        assert data["workers"][0]["card_no_masked"] == "350***92"
        assert body["meta"]["source"] == "tiji-platform"
