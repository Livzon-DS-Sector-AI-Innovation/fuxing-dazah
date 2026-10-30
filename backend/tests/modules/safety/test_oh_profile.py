"""个人完整档案聚合（OhProfileService）— 五源身份匹配口径 + 降级。

覆盖：
- 人员解析 UUID / feishu_record_id 双入口；
- DB 四区块：体检/随访走 person_id，申请=姓名+身份证兜底排除（空身份证
  不算失配、明确不同才排除），参训=OCR 姓名等值；
- 违章 open_id 强匹配：同 open_id 命中 / 无 open_id 姓名兜底 / open_id
  不同=同名不同人排除；源失败与未接入降级不阻塞；
- 违章投影 person_open_id 字段映射（fields.py + _VIOLATION_KIND）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.safety.models import (
    OhExamApplication,
    OhFollowup,
    OhHealthExam,
    OhPerson,
    TrainingAttendee,
)
from app.modules.safety.service import domain_pages, oh_profile as oh_profile_mod
from app.modules.safety.service.oh_direct import config as od_config
from app.modules.safety.service.oh_direct import ledger as od_ledger
from app.modules.safety.service.oh_profile import OhProfileService

NAME = "档案测试甲"
ID_CARD = "330000199001010000"


@pytest.fixture
def mirror_mode(monkeypatch: pytest.MonkeyPatch):
    """钉住镜像模式（dev 配置中心 OH 直读已开，测试进程会读到 true）。"""
    monkeypatch.setattr(od_config, "direct_enabled", lambda: False)


def _person(**kw) -> OhPerson:
    base = dict(
        name=NAME, id_card_no=ID_CARD, open_id="ou_profile_test_1",
        department="提炼一部", feishu_record_id="recPersonProfile1",
    )
    base.update(kw)
    return OhPerson(**base)


async def _seed(db_session) -> OhPerson:
    person = _person()
    db_session.add(person)
    await db_session.flush()
    db_session.add_all([
        OhHealthExam(
            person_id=person.id, employee_name=NAME,
            exam_type="periodic", exam_no="Z20260930PROF1",
        ),
        OhFollowup(person_id=person.id, person_name=NAME, indicator_name="听力"),
    ])
    db_session.add_all([
        # 申请：身份证匹配 / 空身份证（命中）/ 身份证明确不同（排除）/ 他人（排除）
        OhExamApplication(
            employee_name=NAME, id_card_no=ID_CARD,
            transfer_type="transfer", apply_status="已通过",
        ),
        OhExamApplication(
            employee_name=NAME, id_card_no=None, transfer_type="post_employment",
        ),
        OhExamApplication(
            employee_name=NAME, id_card_no="330000199001019999",
            transfer_type="transfer",
        ),
        OhExamApplication(employee_name="档案测试乙", transfer_type="transfer"),
    ])
    db_session.add_all([
        TrainingAttendee(
            training_record_id="recProfT1", person_name=NAME,
            training_name="档案联测培训", held_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        TrainingAttendee(
            training_record_id="recProfT2", person_name="档案测试乙",
            training_name="他人培训",
        ),
    ])
    await db_session.flush()
    return person


def _vio_rows() -> list[dict[str, Any]]:
    return [
        {  # open_id 强匹配命中
            "record_id": "vProf1", "person_name": NAME,
            "person_open_id": "ou_profile_test_1",
            "occurred_at": "2026-10-01T00:00:00+00:00", "department": ["提炼一部"],
            "category": "操作违章", "level": "一般", "description": "未戴耳塞",
            "handling": "批评教育", "status": "已纠正",
        },
        {  # 无 open_id（如三违回流人工补录行）→ 姓名兜底命中
            "record_id": "vProf2", "person_name": NAME, "person_open_id": None,
            "occurred_at": "2026-10-05T00:00:00+00:00", "department": [],
            "category": "纪律违章", "level": "一般", "description": "迟到",
            "handling": "批评教育", "status": "纠正中",
        },
        {  # open_id 不同 + 姓名相同 = 同名不同人，必须排除
            "record_id": "vProf3", "person_name": NAME,
            "person_open_id": "ou_somebody_else",
            "occurred_at": "2026-10-06T00:00:00+00:00",
            "category": "操作违章", "level": "严重", "description": "冒名行",
            "handling": "罚款", "status": "已纠正",
        },
        {  # 无关人员
            "record_id": "vProf4", "person_name": "档案测试乙",
            "person_open_id": None, "occurred_at": "2026-10-07T00:00:00+00:00",
        },
    ]


@pytest.fixture
def vio_rows(monkeypatch: pytest.MonkeyPatch):
    async def _fake(url_key: str, kind: str, **kw):
        assert (url_key, kind) == ("training-behavior", "violation")
        return _vio_rows()

    monkeypatch.setattr(domain_pages, "fetch_kind_rows", _fake)


# ── 人员解析 ──


async def test_resolve_person_by_uuid_then_feishu_record_id(db_session) -> None:
    person = await _seed(db_session)
    svc = OhProfileService(db_session)
    assert (await svc._resolve_person(str(person.id))) is not None
    assert (await svc._resolve_person("recPersonProfile1")) is not None
    assert (await svc._resolve_person("00000000-0000-0000-0000-000000000000")) is None


# ── 五源聚合 ──


async def test_profile_aggregates_five_sources(db_session, vio_rows, mirror_mode) -> None:
    person = await _seed(db_session)
    profile = await OhProfileService(db_session).build_profile(str(person.id))
    assert profile is not None
    assert profile["person"].id == person.id
    assert len(profile["exams"]) == 1
    assert len(profile["followups"]) == 1
    # 申请：身份证明确不同的「档案测试甲」行被排除，剩 2 条
    assert sorted(a.transfer_type for a in profile["applications"]) == [
        "post_employment", "transfer",
    ]
    # 参训：OCR 姓名等值，只命中本人行
    assert [t.training_name for t in profile["trainings"]] == ["档案联测培训"]
    # 违章：open_id 命中 + 姓名兜底命中；同名不同人（vProf3）与无关人排除
    assert [v["record_id"] for v in profile["violations"]] == ["vProf1", "vProf2"]
    assert {v["match_basis"] for v in profile["violations"]} == {"open_id", "name"}
    assert profile["match_notes"] == {
        "trainings": "name", "violations": "mixed",
    }
    assert profile["errors"] == []


async def test_violations_without_open_id_all_name_basis(
    db_session, vio_rows, mirror_mode
) -> None:
    person = await _seed(db_session)
    person.open_id = None
    await db_session.flush()
    profile = await OhProfileService(db_session).build_profile(str(person.id))
    # 本人无 open_id：vProf1（行有 open_id 但本人没有）走姓名兜底命中；
    # vProf3 同理命中（无强键可辨同名，姓名级即上限）；vProf4 仍排除
    ids = [v["record_id"] for v in profile["violations"]]
    assert ids == ["vProf1", "vProf2", "vProf3"]
    assert profile["match_notes"]["violations"] == "name"


# ── 违章源降级 ──


async def test_violations_source_failure_degrades(
    db_session, monkeypatch, mirror_mode
) -> None:
    person = await _seed(db_session)

    async def _boom(*a, **kw):
        raise RuntimeError("bitable down")

    monkeypatch.setattr(domain_pages, "fetch_kind_rows", _boom)
    profile = await OhProfileService(db_session).build_profile(str(person.id))
    assert profile["violations"] is None
    assert profile["errors"] and profile["errors"][0].startswith("violations")
    # 其余区块不受影响
    assert len(profile["exams"]) == 1
    assert len(profile["trainings"]) == 1


async def test_violations_domain_not_connected(
    db_session, monkeypatch, mirror_mode
) -> None:
    person = await _seed(db_session)

    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(domain_pages, "fetch_kind_rows", _none)
    profile = await OhProfileService(db_session).build_profile(str(person.id))
    assert profile["violations"] is None
    assert profile["errors"] == []
    assert profile["match_notes"]["violations"] is None


# ── 直读模式（当前线上形态：镜像表空，人员/体检走 ledger）──


@pytest.fixture
def direct_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(od_config, "direct_enabled", lambda: True)


def _dperson(rid: str = "recDirectP1", **mapped):
    from app.modules.safety.service.oh_direct.ledger import OhRowView

    base = {
        "name": NAME, "id_card_no": ID_CARD, "open_id": "ou_profile_test_1",
        "department": "提炼一部", "hazard_factors": ["噪声"],
    }
    base.update(mapped)
    return OhRowView(rid, base)


def _dexam(rid: str, **mapped):
    from app.modules.safety.service.oh_direct.ledger import OhRowView

    return OhRowView(rid, {"employee_name": NAME, **mapped})


async def test_direct_mode_profile(
    db_session, direct_mode, vio_rows, monkeypatch
) -> None:
    persons = [_dperson(), _dperson("recOther", name="档案测试乙", open_id=None)]
    exams = [
        _dexam("recE1", id_card_no=ID_CARD, exam_no="Z1",
               exam_date=datetime(2026, 10, 2, tzinfo=UTC)),
        _dexam("recE2", id_card_no=None, exam_no="Z2",
               exam_date=datetime(2026, 10, 5, tzinfo=UTC)),  # 空身份证命中
        _dexam("recE3", id_card_no="330000199001019999"),     # 明确不同排除
        _dexam("recE4", employee_name="档案测试乙"),            # 他人排除
        _dexam("recE5", exam_no="Z5"),                        # 日期缺失不炸排序
    ]

    async def _fake_persons():
        return persons

    async def _fake_exams():
        return exams

    monkeypatch.setattr(od_ledger, "fetch_persons", _fake_persons)
    monkeypatch.setattr(od_ledger, "fetch_exams", _fake_exams)
    await _seed(db_session)  # PG 申请/参训按姓名关联，不受模式影响

    profile = await OhProfileService(db_session).build_profile("recDirectP1")
    assert profile is not None
    assert profile["person"].id == "recDirectP1"
    assert profile["person"].name == NAME
    # 体检：姓名+身份证口径命中 3（Z2 最新在前，缺日期垫底），他人/证不同排除
    assert [e.mapped["exam_no"] for e in profile["exams"]] == ["Z2", "Z1", "Z5"]
    # 随访：平台侧表无直读源
    assert profile["followups"] == []
    assert len(profile["applications"]) == 2
    assert [t.training_name for t in profile["trainings"]] == ["档案联测培训"]
    assert [v["record_id"] for v in profile["violations"]] == ["vProf1", "vProf2"]


async def test_direct_mode_unknown_person(
    db_session, direct_mode, monkeypatch
) -> None:
    async def _empty():
        return []

    monkeypatch.setattr(od_ledger, "fetch_persons", _empty)
    assert await OhProfileService(db_session).build_profile("recNope") is None


# ── 违章投影 person_open_id 字段映射 ──


def test_violation_kind_maps_person_open_id() -> None:
    assert oh_profile_mod  # 模块可导入（占位防未用导入）
    record = {
        "record_id": "vMap",
        "fields": {"违章人员": [{"id": "ou_map_1", "name": "映射测试丙"}]},
    }
    row = domain_pages._map_row(record, domain_pages._VIOLATION_KIND)
    assert row["person_name"] == "映射测试丙"
    assert row["person_open_id"] == "ou_map_1"
    # 旧格式无 id：person_open_id 为 None，姓名照常
    row2 = domain_pages._map_row(
        {"record_id": "vMap2", "fields": {"违章人员": [{"name": "无ID丁"}]}},
        domain_pages._VIOLATION_KIND,
    )
    assert row2["person_name"] == "无ID丁"
    assert row2["person_open_id"] is None
