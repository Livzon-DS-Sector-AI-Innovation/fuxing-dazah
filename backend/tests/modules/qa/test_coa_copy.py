"""COA「复制到其它模板」：把一条出具记录的若干格登记到同产品另一模板的同批号记录。

沿用 test_coa_api 的 harness（整条用例共用一个最终回滚的会话）。来源模板
叫 pH / 水分 / 炽灼残渣 / 性状，目标模板叫 酸碱度 / 干燥失重 / 硫酸灰分 /
溶液澄清度 / 氯化物鉴别——名字故意对不上，对应关系全靠载荷指定。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.models import CoaCopyLink
from tests.modules.qa.test_coa_api import (
    ISSUE,
    MANAGE,
    READ,
    _client,
    _mk_product_with_batch_fields,
    _mk_report,
    _mk_standard,
    _uniq,
)

pytestmark = pytest.mark.anyio

ISSUE_AND_MANAGE = MANAGE | ISSUE


def _item(standard: dict[str, Any], name_cn: str) -> dict[str, Any]:
    return next(i for i in standard["items"] if i["name_cn"] == name_cn)


async def _mk_source_standard(ac: AsyncClient, product_id: str) -> dict[str, Any]:
    return await _mk_standard(
        ac,
        product_id,
        items=[
            {"name_cn": "pH", "value_type": "number", "spec_text": "2.5～4.5"},
            {"name_cn": "水分", "value_type": "number", "spec_text": "≤5.0%"},
            {"name_cn": "炽灼残渣", "value_type": "number", "spec_text": "≤1.0%"},
            {"name_cn": "性状", "value_type": "text", "spec_text": "白色粉末"},
        ],
    )


async def _mk_target_standard(ac: AsyncClient, product_id: str) -> dict[str, Any]:
    return await _mk_standard(
        ac,
        product_id,
        code=_uniq("B"),
        name=_uniq("目标模板 "),
        items=[
            {"name_cn": "酸碱度", "value_type": "number", "spec_text": "2.5～4.5"},
            {"name_cn": "干燥失重", "value_type": "number", "spec_text": "≤5.0%"},
            {"name_cn": "硫酸灰分", "value_type": "number", "spec_text": "≤1.0%"},
            {"name_cn": "溶液澄清度", "value_type": "text", "default_value": "符合规定"},
            {"name_cn": "氯化物鉴别", "value_type": "text", "default_value": "符合规定"},
        ],
    )


async def _mk_product_and_standards(
    ac: AsyncClient,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """产品带两个批次字段（一个镜像生产日期固定列，一个纯自定义）。"""
    product = await _mk_product_with_batch_fields(
        ac,
        [
            {"key": "manufacturing_date", "label_cn": "生产日期", "field_type": "date"},
            {"key": "appearance", "label_cn": "性状", "field_type": "text"},
        ],
    )
    return (
        product,
        await _mk_source_standard(ac, product["id"]),
        await _mk_target_standard(ac, product["id"]),
    )


async def _copy(ac: AsyncClient, source: dict[str, Any], payload: dict[str, Any]):
    return await ac.post(f"/api/v1/qa/coa/reports/{source['id']}/copy", json=payload)


def _item_cell(source_item: dict[str, Any], target_item: dict[str, Any], **value: Any) -> dict[str, Any]:
    return {"kind": "item", "source": source_item["id"], "target": target_item["id"], **value}


def _batch_cell(source_key: str, target_key: str, value: str) -> dict[str, Any]:
    return {"kind": "batch", "source": source_key, "target": target_key, "value": value}


def _values_by_item(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {v["item_id"]: v for v in detail["values"]}


async def _logs(ac: AsyncClient, report_id: str) -> list[dict[str, Any]]:
    resp = await ac.get(
        "/api/v1/qa/operation-logs",
        params={"resource_type": "qa.coa_report", "report_id": report_id},
    )
    assert resp.status_code == 200, resp.text[:200]
    return list(resp.json()["data"])


async def _links_of(session: AsyncSession, target_report_id: str) -> list[CoaCopyLink]:
    result = await session.execute(
        select(CoaCopyLink).where(CoaCopyLink.target_report_id == UUID(target_report_id))
    )
    return list(result.scalars())


class TestCopyCreatesTargetReport:
    async def test_copy_creates_report_under_same_batch_with_given_values(self):
        """目标模板下没有这个批号 → 新建：批号沿用来源，值用载荷给的（可改过）。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(
                ac,
                product["id"],
                source_std,
                batch_data={"manufacturing_date": "2026-07-01", "appearance": "白色粉末"},
            )
            resp = await _copy(
                ac,
                source,
                {
                    "standard_id": target_std["id"],
                    "serial_no": "26081216",
                    "cells": [
                        _item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85, value_text="2.85"),
                        # 个别项目值不同：载荷里直接给改过的值
                        _item_cell(
                            _item(source_std, "水分"), _item(target_std, "干燥失重"),
                            value_num=0.23, value_text="0.23",
                        ),
                        _batch_cell("manufacturing_date", "manufacturing_date", "2026-07-01"),
                    ],
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["created"] is True
            assert data["standard_id"] == target_std["id"]
            assert data["batch_no"] == source["batch_no"]
            assert data["serial_no"] == "26081216"
            assert data["mfg_date"] == "2026-07-01"
            values = _values_by_item(data)
            assert values[_item(target_std, "酸碱度")["id"]]["value_text"] == "2.85"
            assert values[_item(target_std, "干燥失重")["id"]]["value_num"] == 0.23
            # 来源记录原样不动
            origin = (await ac.get(f"/api/v1/qa/coa/reports/{source['id']}")).json()["data"]
            assert origin["standard_id"] == source_std["id"]
            assert len(origin["values"]) == 2

    async def test_copy_fills_defaults_of_items_not_copied(self):
        """新建时没被复制覆盖、配了默认值的检测项目自动填默认值；被复制覆盖的用复制值；
        没默认值又没复制的项目不落值。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(
                ac,
                product["id"],
                source_std,
                values=[{"item_id": _item(source_std, "性状")["id"], "value_text": "类白色粉末"}],
            )
            resp = await _copy(
                ac,
                source,
                {
                    "standard_id": target_std["id"],
                    "serial_no": "26081217",
                    "cells": [
                        _item_cell(
                            _item(source_std, "性状"), _item(target_std, "氯化物鉴别"),
                            value_text="类白色粉末",
                        )
                    ],
                },
            )
            assert resp.status_code == 200, resp.text
            values = _values_by_item(resp.json()["data"])
            assert values[_item(target_std, "氯化物鉴别")["id"]]["value_text"] == "类白色粉末"
            assert values[_item(target_std, "溶液澄清度")["id"]]["value_text"] == "符合规定"
            assert _item(target_std, "硫酸灰分")["id"] not in values


class TestCopyIntoExistingReport:
    async def test_copy_overwrites_only_copied_cells(self):
        """目标模板下已有这个批号 → 只覆盖载荷里的格，其余值（含备注、批次字段、
        流水号）原样保留；已存在的记录不补默认值。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            # 目标模板的项目名和 _mk_report 写死的对不上，这里直接登记
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product["id"],
                    "standard_id": target_std["id"],
                    "batch_no": source["batch_no"],
                    "serial_no": "OLD-1",
                    "batch_data": {"manufacturing_date": "2026-01-01", "appearance": "旧性状"},
                    "values": [
                        {"item_id": _item(target_std, "酸碱度")["id"], "value_num": 3.0, "value_text": "3.0", "remark": "复测"},
                        {"item_id": _item(target_std, "硫酸灰分")["id"], "value_num": 0.5, "value_text": "0.5"},
                    ],
                },
            )
            assert resp.status_code == 201, resp.text
            existing = resp.json()["data"]
            resp = await _copy(
                ac,
                source,
                {
                    "standard_id": target_std["id"],
                    "cells": [
                        _item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85, value_text="2.85"),
                        _batch_cell("manufacturing_date", "manufacturing_date", "2026-07-01"),
                    ],
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["created"] is False
            assert data["id"] == existing["id"]
            assert data["serial_no"] == "OLD-1"
            values = _values_by_item(data)
            # 覆盖格整格替换；没碰的格连同备注原样保留
            assert values[_item(target_std, "酸碱度")["id"]]["value_text"] == "2.85"
            assert values[_item(target_std, "酸碱度")["id"]]["remark"] is None
            assert values[_item(target_std, "硫酸灰分")["id"]]["value_num"] == 0.5
            assert values[_item(target_std, "硫酸灰分")["id"]]["remark"] is None
            # 已存在的记录不补默认值
            assert _item(target_std, "溶液澄清度")["id"] not in values
            assert data["mfg_date"] == "2026-07-01"
            assert data["batch_info"]["appearance"] == "旧性状"


class TestCopyRecordsSources:
    async def test_each_copied_cell_records_its_source(self):
        """每复制一格记一条来源（哪条记录的哪个格 → 目标的哪个格）。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, session):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            resp = await _copy(
                ac,
                source,
                {
                    "standard_id": target_std["id"],
                    "serial_no": "26081218",
                    "cells": [
                        _item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85, value_text="2.85"),
                        _item_cell(
                            _item(source_std, "炽灼残渣"), _item(target_std, "硫酸灰分"),
                            value_num=0.08, value_text="0.08",
                        ),
                        _batch_cell("manufacturing_date", "manufacturing_date", "2026-07-01"),
                    ],
                },
            )
            assert resp.status_code == 200, resp.text
            links = await _links_of(session, resp.json()["data"]["id"])
            assert {
                (link.source_report_id, link.kind, link.source_key, link.target_key)
                for link in links
            } == {
                (UUID(source["id"]), "item", _item(source_std, "pH")["id"], _item(target_std, "酸碱度")["id"]),
                (
                    UUID(source["id"]),
                    "item",
                    _item(source_std, "炽灼残渣")["id"],
                    _item(target_std, "硫酸灰分")["id"],
                ),
                (UUID(source["id"]), "batch", "manufacturing_date", "manufacturing_date"),
            }

    async def test_recopy_keeps_single_source_per_target_cell(self):
        """再复制一次同一格：来源换成最新的，一个目标格始终只有一条。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, session):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            target_item = _item(target_std, "酸碱度")
            first = {
                "standard_id": target_std["id"],
                "serial_no": "26081219",
                "cells": [_item_cell(_item(source_std, "pH"), target_item, value_num=2.85, value_text="2.85")],
            }
            assert (await _copy(ac, source, first)).status_code == 200
            target_id = (await _copy(ac, source, first | {"serial_no": None})).json()["data"]["id"]
            assert (await _links_of(session, target_id))[0].source_key == _item(source_std, "pH")["id"]

            second = {
                "standard_id": target_std["id"],
                "cells": [_item_cell(_item(source_std, "水分"), target_item, value_num=2.3, value_text="2.3")],
            }
            assert (await _copy(ac, source, second)).status_code == 200
            links = await _links_of(session, target_id)
            assert [(link.kind, link.source_key, link.target_key) for link in links] == [
                ("item", _item(source_std, "水分")["id"], target_item["id"])
            ]


class TestCopyGuards:
    async def test_requires_issue_permission(self):
        async with _client(READ) as (ac, _):
            resp = await ac.post(
                "/api/v1/qa/coa/reports/00000000-0000-0000-0000-000000000000/copy",
                json={"standard_id": "x", "cells": []},
            )
            assert resp.status_code == 403

    async def test_unknown_source_report_is_404(self):
        """来源记录不存在 → 404。先放一条正常来源的 200 做对照，排除「路由不存在也是 404」。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            payload = {
                "standard_id": target_std["id"],
                "serial_no": "26081220",
                "cells": [
                    _item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85)
                ],
            }
            assert (await _copy(ac, source, payload)).status_code == 200
            resp = await _copy(ac, {"id": "00000000-0000-0000-0000-000000000000"}, payload)
            assert resp.status_code == 404

    async def test_rejects_standard_of_another_product(self):
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, _target_std = await _mk_product_and_standards(ac)
            other_product = await _mk_product_with_batch_fields(ac, [])
            foreign = await _mk_target_standard(ac, other_product["id"])
            source = await _mk_report(ac, product["id"], source_std)
            resp = await _copy(
                ac,
                source,
                {
                    "standard_id": foreign["id"],
                    "serial_no": "1",
                    "cells": [_item_cell(_item(source_std, "pH"), _item(foreign, "酸碱度"), value_num=2.85)],
                },
            )
            assert resp.status_code == 400
            assert "同一产品" in resp.json()["message"]

    async def test_rejects_same_standard(self):
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, _target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            resp = await _copy(
                ac,
                source,
                {
                    "standard_id": source_std["id"],
                    "serial_no": "1",
                    "cells": [_item_cell(_item(source_std, "pH"), _item(source_std, "水分"), value_num=2.85)],
                },
            )
            assert resp.status_code == 400
            assert "同一个模板" in resp.json()["message"]

    async def test_rejects_items_outside_their_standards(self):
        """来源项目必须属于来源模板、目标项目必须属于目标模板（拿来源项目当目标会被拦）。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            base = {"standard_id": target_std["id"], "serial_no": "1"}
            resp = await _copy(
                ac,
                source,
                {
                    **base,
                    "cells": [
                        _item_cell(_item(source_std, "pH"), _item(source_std, "水分"), value_num=2.85)
                    ],
                },
            )
            assert resp.status_code == 400
            assert "目标项目" in resp.json()["message"]
            resp = await _copy(
                ac,
                source,
                {
                    **base,
                    "cells": [
                        _item_cell(_item(target_std, "酸碱度"), _item(target_std, "硫酸灰分"), value_num=2.85)
                    ],
                },
            )
            assert resp.status_code == 400
            assert "来源项目" in resp.json()["message"]

            # 格式不对的 id 报 400，不是 500
            resp = await _copy(ac, source, {**base, "cells": [_item_cell({"id": "not-a-uuid"}, _item(target_std, "酸碱度"), value_num=2.85)]})
            assert resp.status_code == 400

    async def test_rejects_batch_keys_outside_field_sets(self):
        """批次字段的来源/目标键都必须在各自模板的字段集里，内置字段不能当格复制。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            base = {"standard_id": target_std["id"], "serial_no": "1"}
            for cell, word in (
                (_batch_cell("no_such_field", "manufacturing_date", "2026-07-01"), "来源批次字段"),
                (_batch_cell("manufacturing_date", "no_such_field", "2026-07-01"), "目标批次字段"),
                (_batch_cell("batch_no", "batch_no", "X"), "内置字段"),
            ):
                resp = await _copy(ac, source, {**base, "cells": [cell]})
                assert resp.status_code == 400, cell
                assert word in resp.json()["message"], cell

    async def test_rejects_empty_or_duplicated_cells(self):
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            base = {"standard_id": target_std["id"], "serial_no": "1"}
            resp = await _copy(
                ac,
                source,
                {
                    **base,
                    "cells": [
                        _item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=None, value_text="  ")
                    ],
                },
            )
            assert resp.status_code == 400
            assert "不能为空" in resp.json()["message"]
            resp = await _copy(
                ac,
                source,
                {
                    **base,
                    "cells": [
                        _item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85),
                        _item_cell(_item(source_std, "水分"), _item(target_std, "酸碱度"), value_num=2.3),
                    ],
                },
            )
            assert resp.status_code == 400
            assert "重复" in resp.json()["message"]
            resp = await _copy(ac, source, {**base, "cells": [_batch_cell("manufacturing_date", "manufacturing_date", "")]})
            assert resp.status_code == 400
            assert "不能为空" in resp.json()["message"]

    async def test_serial_no_is_optional(self):
        """流水号选填：新建时不传或纯空白都按没填登记，填了照常落库；
        目标已有记录时不看流水号（不会被改）。"""
        async with _client(ISSUE_AND_MANAGE) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            first = await _mk_report(ac, product["id"], source_std)
            cells = [_item_cell(_item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85)]
            # 不传
            resp = await _copy(ac, first, {"standard_id": target_std["id"], "cells": cells})
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["created"] is True
            assert data["serial_no"] is None
            # 已有记录：载荷带不带流水号都不改
            resp = await _copy(ac, first, {"standard_id": target_std["id"], "serial_no": "NEW-1", "cells": cells})
            assert resp.json()["data"]["serial_no"] is None

            # 另一个批号：纯空白 = 没填
            second = await _mk_report(ac, product["id"], source_std)
            resp = await _copy(ac, second, {"standard_id": target_std["id"], "serial_no": "  ", "cells": cells})
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["serial_no"] is None
            # 再一个批号：填了照常落库
            third = await _mk_report(ac, product["id"], source_std)
            resp = await _copy(ac, third, {"standard_id": target_std["id"], "serial_no": "NEW-1", "cells": cells})
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["serial_no"] == "NEW-1"


class TestCopyLogs:
    async def test_copy_leaves_normal_create_and_edit_logs(self):
        """操作日志里就是普通的新建/编辑记录：新建记一条「登记」，覆盖改了值记一条
        「编辑」，值没变不记；没有专门的复制动作。"""
        # 读操作日志要独立的审计读权限
        async with _client(ISSUE_AND_MANAGE | {"qa:audit:read"}) as (ac, _):
            product, source_std, target_std = await _mk_product_and_standards(ac)
            source = await _mk_report(ac, product["id"], source_std)
            cell = _item_cell(
                _item(source_std, "pH"), _item(target_std, "酸碱度"), value_num=2.85, value_text="2.85"
            )
            created = (
                await _copy(
                    ac, source, {"standard_id": target_std["id"], "serial_no": "NEW-2", "cells": [cell]}
                )
            ).json()["data"]
            assert [log["action"] for log in await _logs(ac, created["id"])] == ["report_created"]

            # 原样再复制一次：值没变，不记
            resp = await _copy(ac, source, {"standard_id": target_std["id"], "cells": [cell]})
            assert resp.status_code == 200
            assert [log["action"] for log in await _logs(ac, created["id"])] == ["report_created"]

            changed = cell | {"value_num": 3.1, "value_text": "3.1"}
            resp = await _copy(ac, source, {"standard_id": target_std["id"], "cells": [changed]})
            assert resp.status_code == 200
            logs = await _logs(ac, created["id"])
            # 用例里几条日志写在同一事务，时间戳相同，顺序不作数：按动作各找各的
            assert sorted(log["action"] for log in logs) == ["report_created", "report_updated"]
            edited = next(log for log in logs if log["action"] == "report_updated")
            assert edited["old_value"] and edited["new_value"]
