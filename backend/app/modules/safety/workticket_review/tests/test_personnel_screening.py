"""ContractorPersonnelScreeningService 直读筛查单测。

FakeScreenClient 直接覆写 list_tickets_for_date_range / list_contractor_users
（不触发真实鉴权与 HTTP），覆盖：ID 精确命中 / 雪花未命中 / 内部员工小 id /
动火文本行姓名命中、未命中、同名多条 / 敏感字段打码 / 汇总计数 / 窗口守卫。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.safety.workticket_review.client import WorkTicketPlatformClient
from app.modules.safety.workticket_review.parser import (
    PERSONNEL_ARRAY_KEYS,
    PERSONNEL_COLUMNS,
)
from app.modules.safety.workticket_review.personnel_screening import (
    STATUS_AMBIGUOUS,
    STATUS_ID_MATCHED,
    STATUS_INTERNAL_USER,
    STATUS_NAME_MATCHED,
    STATUS_NOT_REGISTERED,
    ContractorPersonnelScreeningService,
    mask_secret,
)

# parser 已登记的动火人员子表列（避免与 parser 常量漂移）
_HW_COLS = PERSONNEL_COLUMNS["hot_work"]
_HW_KEY = PERSONNEL_ARRAY_KEYS["hot_work"]

# 台账：何胜（id 精确命中样本）+ 两个同名王五（ambiguous 样本）
REGISTRY: list[dict[str, Any]] = [
    {
        "id": "2066813165726253069",
        "name": "何胜",
        "contractorName": "江苏空间新盛建设工程有限公司",
        "workTypeName": "焊工",
        "cardNo": "320321198501011234",
        "telphone": "15812345678",
    },
    {"id": "9001", "name": "王五", "contractorName": "甲公司", "workTypeName": "普工",
     "cardNo": "110101199001011111", "telphone": "13900000001"},
    {"id": "9002", "name": "王五", "contractorName": "乙公司", "workTypeName": "普工",
     "cardNo": "110101199001012222", "telphone": "13900000002"},
]


def _hw_row(role: str, name: str, cert: str = "") -> dict[str, Any]:
    """动火人员子表行：原始值 + $ 显示值双形态（与平台实测一致）。"""
    row: dict[str, Any] = {}
    for col, val in (
        (_HW_COLS["role"], role),
        (_HW_COLS["name"], name),
        (_HW_COLS["cert_no"], cert),
    ):
        row[col] = val
        row[f"${col}"] = val
    return row


def _ticket(
    ticket_type: str,
    serial: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": ticket_type,
        "processInstanceId": f"pid-{serial}",
        "serialNumber": serial,
        "createTime": "2026-09-28 09:00:00",
        "endTime": "2026-09-28 18:00:00",
        "status": "已完成",
        "variables": variables,
        "raw": {},
    }


class FakeScreenClient(WorkTicketPlatformClient):
    """内存客户端：不建真实连接，不触发鉴权（同 test_client_range.FakeClient 约定）。"""

    def __init__(
        self,
        tickets: list[dict[str, Any]],
        registry: list[dict[str, Any]],
    ) -> None:
        self._platform_token = "fake-platform-token"
        self._lcp_token = "fake-lcp-token"
        self._client = None
        self._owns_client = False
        self._tickets = tickets
        self._registry = registry
        self.range_calls: list[tuple[date, date]] = []

    async def list_tickets_for_date_range(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        self.range_calls.append((start_date, end_date))
        return self._tickets

    async def list_contractor_users(
        self,
        *,
        name: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        return self._registry


def _sample_tickets() -> list[dict[str, Any]]:
    height_key = "a177848463469993852"
    lift_a = "a178149178305678016"
    lift_b = "a17784882584521751"
    return [
        # 动火：何胜（姓名唯一命中）+ 陌生人李四（未命中）+ 同名王五（ambiguous）
        _ticket(
            "hot_work",
            "DH-20260928-001",
            {
                _HW_KEY: [
                    _hw_row("特种作业人员", "何胜", "320321199001011234"),
                    _hw_row("普工", "李四"),
                    _hw_row("普工", "王五"),
                ]
            },
        ),
        # 高处：何胜（选择器 id 精确命中；同一人两列去重）+ 张国东（内部员工小 id）
        _ticket(
            "height_work",
            "GC-20260928-001",
            {
                height_key: [
                    {
                        "a177848470015039484": "熔化焊接与热切割作业",
                        "a167098403454514933": "2066813165726253069",
                        "$a167098403454514933": "何胜",
                        "a168570612205386039": "2066813165726253069",
                        "$a168570612205386039": "何胜",
                    },
                    {
                        "a167098403454514933": "8212",
                        "$a167098403454514933": "张国东",
                    },
                ]
            },
        ),
        # 吊装：指挥刘荣春（雪花 id 未命中台账）+ 司机毛江伟（命中）
        _ticket(
            "lifting",
            "DZ-20260926-001",
            {
                lift_a: [
                    {
                        "a17814917830577454": "起重机指挥",
                        "a178149178305786753": "2084086970637029378",
                        "$a178149178305786753": "刘荣春",
                        # 证件号列：显示值为数字，应被人员抽取排除
                        "a178149178305725438": "2084087152715960322",
                        "$a178149178305725438": "321088199001013333",
                    }
                ],
                lift_b: [
                    {
                        "a177848831213986377": "起重机司机（限流动式起重机）",
                        "a166408792793480160": "2066813165726253069",
                        "$a166408792793480160": "毛江伟",
                    }
                ],
            },
        ),
        # 受限空间：无人员子表，应跳过（计入 scanned 不计入 with_personnel）
        _ticket("confined_space", "SX-20260928-001", {}),
    ]


@pytest.mark.asyncio
async def test_screen_full_matrix() -> None:
    client = FakeScreenClient(_sample_tickets(), REGISTRY)
    result = await ContractorPersonnelScreeningService(client).screen(
        date(2026, 9, 26), date(2026, 9, 28)
    )

    assert result["success"] is True
    assert result["registry_total"] == 3
    assert result["tickets_scanned"] == 4
    assert result["tickets_with_personnel"] == 3
    assert result["covered_types"] == ["height_work", "hot_work", "lifting"]
    assert result["ticket_types_scanned"]["confined_space"] == 1

    stats = result["stats"]
    # 何胜(name)+毛江伟(id)+何胜(id) = 2 id_matched + 1 name_matched
    assert stats[STATUS_ID_MATCHED] == 2
    assert stats[STATUS_NAME_MATCHED] == 1
    # 李四(name 0 命中)+刘荣春(id 未命中) = 2
    assert stats[STATUS_NOT_REGISTERED] == 2
    assert stats[STATUS_AMBIGUOUS] == 1
    assert stats[STATUS_INTERNAL_USER] == 1

    # abnormal 只含未命中与同名
    abnormal = result["abnormal"]
    assert {item["person"] for item in abnormal} == {"李四", "刘荣春", "王五"}
    ambiguous = next(i for i in abnormal if i["person"] == "王五")
    assert len(ambiguous["candidates"]) == 2

    # 敏感字段打码：命中档案与票面证件号都不出明文
    hot = next(t for t in result["per_ticket"] if t["ticket_no"] == "DH-20260928-001")
    he = next(p for p in hot["persons"] if p["name"] == "何胜")
    assert he["registry"]["card_no_masked"] == mask_secret("320321198501011234")
    assert "***" in he["registry"]["card_no_masked"]
    assert "320321198501011234" not in str(result)
    li = next(p for p in hot["persons"] if p["name"] == "李四")
    assert li["status"] == STATUS_NOT_REGISTERED
    assert li.get("cert_no_masked", "") == ""

    # 高处票：选择器同人多列去重后 2 行
    height = next(t for t in result["per_ticket"] if t["ticket_no"] == "GC-20260928-001")
    assert len(height["persons"]) == 2

    # 台账拉取走了一次全量（不带 name 过滤参数语义由 client 测试覆盖）
    assert client.range_calls == [(date(2026, 9, 26), date(2026, 9, 28))]


@pytest.mark.asyncio
async def test_screen_window_guards() -> None:
    client = FakeScreenClient([], [])
    service = ContractorPersonnelScreeningService(client)
    with pytest.raises(ValueError):
        await service.screen(date(2026, 9, 28), date(2026, 9, 27))
    with pytest.raises(ValueError):
        await service.screen(date(2026, 1, 1), date(2026, 9, 28))
    # 恰好 31 天允许
    ok = await service.screen(date(2026, 9, 1), date(2026, 10, 1))
    assert ok["success"] is True
    assert ok["tickets_scanned"] == 0


def test_mask_secret_shapes() -> None:
    assert mask_secret(None) == ""
    assert mask_secret("") == ""
    assert mask_secret("123456") == "***"
    assert mask_secret("320321198501011234") == "320***34"
    assert mask_secret("15812345678") == "158***78"
