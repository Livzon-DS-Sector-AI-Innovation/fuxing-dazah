"""厂区风险分区图卡（F2）——资产归一化与 seed 行构建纯函数测试。

接缝：service/facility_map 纯函数（平台原始 payload → 归一化资产 / seed 行）。
形状以 2026-10-26 真机探针为准（.scratch/f2-facility-map/districts_raw_sample.json）：
rail.pointDTOS=[{x:lng,y:lat,z}]（经纬度，主坐标源）、rail.pointsList=本地米制
平面坐标嵌套 JSON 字符串（同点数，回退源）；分区带 riskLevel/riskLevelDesc。
口径见 .scratch/f2-facility-map/spec.md。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.facility_map.asset import (
    build_asset_doc,
    build_frontend_doc,
    normalize_districts,
    rail_polygon,
)
from app.modules.safety.service.facility_map.mapping import (
    build_match_index,
    match_location,
    normalize_location_text,
)
from app.modules.safety.service.facility_map.pins import (
    aggregate_pins,
    central_location_text,
)
from app.modules.safety.service.facility_map.seed_data import seed_rows_from_asset
from app.modules.safety.service.facility_map.service import FacilityMapPinsService


def _rail(
    *,
    name: str = "综合泵房",
    point_dtos: list | None = None,
    points_list: str | None = None,
) -> dict:
    return {
        "id": "2",
        "name": name,
        "pointDTOS": point_dtos,
        "pointsList": points_list,
    }


def _district(**overrides) -> dict:
    base = {
        "distId": "77",
        "distName": "消防控制室",
        "riskLevel": 1,
        "riskLevelDesc": "低风险",
        "rails": [
            _rail(
                point_dtos=[
                    {"x": 119.28653608926888, "y": 25.46341590747086, "z": 0.0},
                    {"x": 119.28653631672049, "y": 25.463415834714453, "z": 0.0},
                    {"x": 119.28653638594488, "y": 25.463415752863494, "z": 0.0},
                ],
                points_list=(
                    '[{"x":161931,"y":283581,"z":0.0},'
                    '{"x":161954,"y":283589,"z":0.0},'
                    '{"x":161961,"y":283598,"z":0.0}]'
                ),
            )
        ],
    }
    base.update(overrides)
    return base


class TestRailPolygon:
    def test_prefers_point_dtos_lng_lat(self):
        """主坐标源 pointDTOS（经纬度），输出按 6 位小数舍入的 (x, y) 序列。"""
        poly = rail_polygon(
            _rail(
                point_dtos=[
                    {"x": 119.28653608926888, "y": 25.46341590747086, "z": 0.0},
                    {"x": 119.28653631672049, "y": 25.463415834714453, "z": 0.0},
                    {"x": 119.28653638594488, "y": 25.463415752863494, "z": 0.0},
                ],
                points_list="[]",
            )
        )
        assert poly == [
            (119.286536, 25.463416),
            (119.286536, 25.463416),
            (119.286536, 25.463416),
        ]

    def test_falls_back_to_points_list_json_string(self):
        """pointDTOS 为空时解析 pointsList 本地米制坐标（整数字符串 JSON）。"""
        rail = _rail(
            point_dtos=None,
            points_list=(
                '[{"x":161931,"y":283581,"z":0.0},'
                '{"x":161954,"y":283589,"z":0.0},'
                '{"x":161961,"y":283598,"z":0.0}]'
            ),
        )
        assert rail_polygon(rail) == [
            (161931.0, 283581.0),
            (161954.0, 283589.0),
            (161961.0, 283598.0),
        ]

    def test_returns_none_when_points_lt_3(self):
        assert rail_polygon(_rail(point_dtos=[{"x": 1, "y": 2, "z": 0}])) is None

    def test_returns_none_when_unparseable(self):
        rail = _rail(point_dtos=None, points_list="not-json")
        assert rail_polygon(rail) is None
        assert rail_polygon(_rail(point_dtos=None, points_list=None)) is None


class TestNormalizeDistricts:
    def test_maps_fields_and_keeps_all_districts(self):
        records = [
            _district(),
            _district(
                distId="76",
                distName="空冷班组",
                riskLevel=None,
                riskLevelDesc="",
                rails=[],
            ),
        ]
        out = normalize_districts(records)
        assert len(out) == 2
        first = out[0]
        assert first["distId"] == "77"
        assert first["distName"] == "消防控制室"
        assert first["riskLevel"] == 1
        assert first["riskLevelDesc"] == "低风险"
        assert first["rails"][0]["name"] == "综合泵房"
        assert first["rails"][0]["polygon"] == [
            [119.286536, 25.463416],
            [119.286536, 25.463416],
            [119.286536, 25.463416],
        ]
        # 零 rail 的分区保留（名称进 seed，前端渲染跳过）
        assert out[1]["rails"] == []

    def test_skips_invalid_rails_keeps_valid(self):
        records = [
            _district(
                rails=[
                    _rail(name="坏轮廓", point_dtos=None, points_list="not-json"),
                    _rail(
                        name="好轮廓",
                        point_dtos=[
                            {"x": 1.0, "y": 2.0, "z": 0},
                            {"x": 3.0, "y": 4.0, "z": 0},
                            {"x": 5.0, "y": 6.0, "z": 0},
                        ],
                        points_list="[]",
                    ),
                ]
            )
        ]
        out = normalize_districts(records)
        assert [r["name"] for r in out[0]["rails"]] == ["好轮廓"]


class TestAssetDocs:
    def test_build_asset_doc_meta(self):
        doc = build_asset_doc([_district()], fetched_at="2026-10-26T15:00:00+08:00")
        meta = doc["_meta"]
        assert meta["count"] == 1
        assert "pointDTOS" in meta["coordinate_system"]
        assert "米制" in meta["fallback_note"]
        assert meta["fetched_at"] == "2026-10-26T15:00:00+08:00"
        assert doc["districts"][0]["distName"] == "消防控制室"

    def test_frontend_doc_strips_meta(self):
        doc = build_asset_doc([_district()], fetched_at="2026-10-26T15:00:00+08:00")
        fe = build_frontend_doc(doc)
        assert "_meta" not in fe
        assert fe["districts"][0]["distName"] == "消防控制室"


class TestSeedRows:
    def test_distname_rows_plus_synonyms_deduped(self):
        doc = build_asset_doc(
            [
                _district(),
                _district(distId="35", distName="危化品库", riskLevel=None, riskLevelDesc="", rails=[]),
            ],
            fetched_at="2026-10-26T15:00:00+08:00",
        )
        rows = seed_rows_from_asset(
            doc, synonyms={"危化品库": ["危化品仓库", "危化库"], "消防控制室": ["消控室"]}
        )
        by_text = {row["location_text"]: row for row in rows}
        # 64 分区名原文全部成行
        assert by_text["消防控制室"]["dist_id"] == "77"
        assert by_text["危化品库"]["dist_id"] == "35"
        # 同义词指向同分区
        assert by_text["危化品仓库"]["dist_id"] == "35"
        assert by_text["危化库"]["dist_id"] == "35"
        assert by_text["消控室"]["dist_id"] == "77"
        # 全部 manual、无重复文本
        assert len(rows) == len(by_text)
        assert all(row["source"] == "manual" for row in rows)

    def test_unknown_synonym_dist_skipped(self):
        doc = build_asset_doc([_district()], fetched_at="2026-10-26T15:00:00+08:00")
        rows = seed_rows_from_asset(doc, synonyms={"不存在分区": ["某处"]})
        assert [r["location_text"] for r in rows] == ["消防控制室"]


# ══════════════════════ T2：映射匹配 / pins 聚合 / 服务编排 ══════════════════════

from datetime import date  # noqa: E402

from app.modules.safety.service.facility_map.mapping import (  # noqa: E402
    build_match_index,
    match_location,
    normalize_location_text,
)
from app.modules.safety.service.facility_map.pins import (  # noqa: E402
    aggregate_pins,
    central_location_text,
)
from app.modules.safety.service.facility_map.service import (  # noqa: E402
    FacilityMapPinsService,
)

MAP_ROWS = [
    {"location_text": "车间一达托", "dist_id": "64"},
    {"location_text": "车间一达巴", "dist_id": "63"},
    {"location_text": "危化品库", "dist_id": "35"},
    {"location_text": "危化品仓库", "dist_id": "35"},
    {"location_text": "接罐站", "dist_id": "28"},
]


class TestMapping:
    def test_exact_match(self):
        idx = build_match_index(MAP_ROWS)
        assert match_location("车间一达托", idx) == "64"
        assert match_location("危化品库", idx) == "35"

    def test_normalization_fullwidth_case_space(self):
        idx = build_match_index(MAP_ROWS)
        # 全角字母/数字/空格 + 大小写均归一后精确命中
        assert match_location("　车间一达托　", idx) == "64"

    def test_containment_longest_first(self):
        idx = build_match_index(MAP_ROWS)
        # 票面文本包含映射词 → 命中；多词可命中时取最长（危化品仓库 > 危化品库 同 dist 无感，
        # 用「接罐站东南侧管廊」验证包含；「车间一达托2-30」验证前缀包含）
        assert match_location("接罐站东南侧管廊", idx) == "28"
        assert match_location("车间一达托2-30", idx) == "64"

    def test_no_match_and_empty(self):
        idx = build_match_index(MAP_ROWS)
        assert match_location("212罐", idx) is None
        assert match_location("", idx) is None
        assert match_location(None, idx) is None


def _job(ticket_type: str, site: str, no: str = "PK-1") -> dict:
    return {
        "ticket_type": ticket_type,
        "ticket_no": no,
        "work_site": site,
        "work_content": "检修",
    }


def _fire(location: str, building: str | None = "车间一") -> dict:
    return {
        "alarm_time": "2026-10-26T08:30:00+08:00",
        "alarm_type": "气体报警",
        "location": location,
        "building": building,
    }


def _central(workshop: str = "车间一", line: str | None = "达托") -> dict:
    return {
        "alarm_date": "2026-10-26",
        "alarm_description": "P0405A氯化钠泵出口温度高",
        "workshop": workshop,
        "line": line,
    }


class TestCentralLocationText:
    def test_workshop_plus_line(self):
        """中控位置文本=车间+产线（车间一+达托 → 恰合分区名「车间一达托」）。"""
        assert central_location_text("车间一", "达托") == "车间一达托"

    def test_workshop_only(self):
        assert central_location_text("发酵一部", None) == "发酵一部"
        assert central_location_text(None, None) == ""


class TestAggregatePins:
    def test_job_buckets_and_counts(self):
        out = aggregate_pins(
            jobs=[
                _job("hot_work", "车间一达托", "RQ-1"),
                _job("hot_work", "车间一达托2-30", "RQ-2"),
                _job("confined_space", "车间一达托", "SX-1"),
                _job("lifting", "危化品库", "QZ-1"),
            ],
            fires=[],
            centrals=[],
            index=build_match_index(MAP_ROWS),
        )
        pins = {p["dist_id"]: p for p in out["pins"]}
        assert pins["64"]["jobs"] == {"hot": 2, "confined": 1, "other": 0}
        assert pins["35"]["jobs"] == {"hot": 0, "confined": 0, "other": 1}
        assert pins["64"]["refs"][0]["ticket_no"] == "RQ-1"
        assert out["unmapped"] == []

    def test_alarm_fallback_and_central_compose(self):
        out = aggregate_pins(
            jobs=[],
            fires=[
                _fire(location="一层感烟009", building="原料库"),  # 部位不命中→楼栋兜底
                _fire(location=None, building=None),  # 全空 → unmapped 占位
            ],
            centrals=[_central()],  # 车间一达托 → 精确命中
            index=build_match_index(
                MAP_ROWS + [{"location_text": "原料库", "dist_id": "33"}]
            ),
        )
        pins = {p["dist_id"]: p for p in out["pins"]}
        assert pins["33"]["alarms"]["fire"] == 1
        assert pins["64"]["alarms"]["central"] == 1
        unmapped = {u["text"]: u for u in out["unmapped"]}
        assert "（未填写作业地点）" in unmapped
        assert unmapped["（未填写作业地点）"]["count"] == 1
        assert unmapped["（未填写作业地点）"]["kinds"] == ["fire"]

    def test_unmapped_dedup_with_kinds(self):
        out = aggregate_pins(
            jobs=[
                _job("hot_work", "212罐", "RQ-1"),
                _job("hot_work", "212罐", "RQ-2"),
                _job("confined_space", "212罐", "SX-1"),
            ],
            fires=[_fire(location="212罐", building=None)],
            centrals=[],
            index=build_match_index(MAP_ROWS),
        )
        assert len(out["unmapped"]) == 1
        u = out["unmapped"][0]
        assert u["text"] == "212罐"
        assert u["count"] == 4
        assert set(u["kinds"]) == {"job", "fire"}
        assert out["pins"] == []

    def test_refs_cap_50_with_truncated_flag(self):
        jobs = [
            _job("hot_work" if i % 2 else "confined_space", "车间一达托", f"T-{i}")
            for i in range(60)
        ]
        out = aggregate_pins(
            jobs=jobs, fires=[], centrals=[], index=build_match_index(MAP_ROWS)
        )
        pin = out["pins"][0]
        assert len(pin["refs"]) == 50
        assert pin["truncated"] is True
        assert pin["jobs"]["hot"] + pin["jobs"]["confined"] == 60


def _ok_readers(jobs=None, fires=None, centrals=None, rows=None):
    async def ticket_reader(d):
        return jobs or []

    async def fire_reader(d):
        return fires or []

    async def central_reader(d):
        return centrals or []

    async def map_rows():
        return rows if rows is not None else MAP_ROWS

    return ticket_reader, fire_reader, central_reader, map_rows


class TestPinsService:
    async def test_happy_path(self):
        svc = FacilityMapPinsService(
            readers=_ok_readers(
                jobs=[_job("hot_work", "车间一达托", "RQ-9")],
                fires=[_fire("车间一达托东侧", "车间一")],
                centrals=[_central("车间一", "达巴")],
            )
        )
        payload = await svc.get_pins(date(2026, 10, 26))
        assert payload["date"] == "2026-10-26"
        assert payload["errors"] == []
        pins = {p["dist_id"]: p for p in payload["pins"]}
        assert pins["64"]["jobs"]["hot"] == 1
        assert pins["64"]["alarms"] == {"fire": 1, "central": 0}
        assert pins["63"]["alarms"]["central"] == 1
        assert payload["unmapped"] == []

    async def test_single_source_failure_degrades(self):
        async def boom(d):
            raise RuntimeError("平台超时")

        t, f, c, m = _ok_readers(jobs=[_job("hot_work", "车间一达托")])
        svc = FacilityMapPinsService(readers=(boom, f, c, m))
        payload = await svc.get_pins(date(2026, 10, 26))
        assert len(payload["errors"]) == 1
        assert "作业票" in payload["errors"][0]
        # 其余路不受影响：无票贡献但映射/报警照常
        assert payload["pins"] == []
        assert payload["unmapped"] == []

    async def test_map_rows_failure_degrades(self):
        async def boom_rows():
            raise RuntimeError("db down")

        t, f, c, _ = _ok_readers(jobs=[_job("hot_work", "车间一达托")])
        svc = FacilityMapPinsService(readers=(t, f, c, boom_rows))
        payload = await svc.get_pins(date(2026, 10, 26))
        assert any("映射" in e for e in payload["errors"])
        # 映射表失败 → 全部进 unmapped（文本可见，图卡可解释）
        assert payload["unmapped"][0]["text"] == "车间一达托"
