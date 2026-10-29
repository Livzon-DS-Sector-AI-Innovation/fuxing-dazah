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


class TestDistrictNames:
    def test_format_district_list_has_real_names(self):
        """提示词分区清单必须是真实名称——曾因生成器 f-string 转义错误
        写出整片 {did}={name} 占位符，AI 拿不到分区名全部判 null。"""
        from app.modules.safety.service.facility_map.district_names import (
            DISTRICT_PAIRS,
            format_district_list,
        )

        lines = format_district_list().split("\n")
        assert len(lines) == len(DISTRICT_PAIRS)
        assert all("{did}" not in line and "={name}" not in line for line in lines)
        assert any(name in format_district_list() for _, name in DISTRICT_PAIRS)


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

    def test_building_level_synonyms_landed(self):
        """2026-10-29 建筑级拍板同义词：真实 SEED_SYNONYMS 对含相关分区名
        的资产落行——中控室→车间一(1)/危废库族→危化品库(37)/莫昔→莫西(23)/
        非达→达巴新线(10)/动力设施族→空冷班组(76)/旧原料库→原辅料库(38)/
        罐区俗称族→罐区(9001)。"""
        dists = [
            _district(distId="1", distName="车间一达托", rails=[]),
            _district(distId="37", distName="危化品库", rails=[]),
            _district(distId="23", distName="提四莫西", rails=[]),
            _district(distId="10", distName="车间二达巴新线", rails=[]),
            _district(distId="76", distName="空冷班组", rails=[]),
            _district(distId="38", distName="原辅料库", rails=[]),
            _district(distId="9001", distName="罐区", rails=[]),
        ]
        doc = build_asset_doc(dists, fetched_at="2026-10-29T12:00:00+08:00")
        rows = seed_rows_from_asset(doc)  # 不传 synonyms → 用真实 SEED_SYNONYMS
        by_text = {row["location_text"]: row["dist_id"] for row in rows}
        assert by_text["中控室"] == "1"
        for alias in ("危废库", "危库二", "危库三"):
            assert by_text[alias] == "37"
        assert by_text["莫昔"] == "23"
        assert by_text["非达"] == "10"
        for alias in ("新动力车间", "空压站", "二期冷却塔", "二期制水"):
            assert by_text[alias] == "76"
        assert by_text["旧原料库"] == "38"
        for alias in ("庆大罐区", "妥布北侧罐区", "提二罐区"):
            assert by_text[alias] == "9001"


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


class TestAggregateKeyRisks:
    def test_counts_refs_and_merges_with_jobs(self):
        """关键风险按 area 命中分区：单列 key_risks 计数，与作业票同分区共存。"""
        out = aggregate_pins(
            jobs=[_job("hot_work", "车间一达托", "RQ-1")],
            fires=[],
            centrals=[],
            key_risks=[
                _key_risk("车间一达托", "K-1"),
                _key_risk("车间一达托新线", "K-2", status="审批中"),
                _key_risk("危化品库", "K-3"),
                _key_risk("车间四二楼合成岗位", "K-4"),  # 未映射 → unmapped
                _key_risk("", "K-5"),  # 空区域 → 占位文本
            ],
            index=build_match_index(MAP_ROWS),
        )
        pins = {p["dist_id"]: p for p in out["pins"]}
        assert pins["64"]["key_risks"] == 2
        assert pins["64"]["jobs"]["hot"] == 1  # 票计数不受影响
        kr_refs = [r for r in pins["64"]["refs"] if r["kind"] == "key_risk"]
        assert {r["report_no"] for r in kr_refs} == {"K-1", "K-2"}
        assert kr_refs[0]["apply_status"] in ("已通过", "审批中")
        assert pins["35"]["key_risks"] == 1  # 危化品库
        unmapped = {u["text"]: u for u in out["unmapped"]}
        assert unmapped["车间四二楼合成岗位"]["kinds"] == ["key_risk"]
        assert unmapped["（未填写作业地点）"]["kinds"] == ["key_risk"]

    def test_status_field_in_ref(self):
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            key_risks=[_key_risk("车间一达托", "K-9", status="审批中")],
            index=build_match_index(MAP_ROWS),
        )
        ref = out["pins"][0]["refs"][0]
        assert ref == {
            "kind": "key_risk",
            "report_no": "K-9",
            "apply_status": "审批中",
            "area": "车间一达托",
            "operation_content": "结晶收粉",
            "start_time": "2026-10-27T06:00:00+00:00",
        }


class TestAggregateOverLimits:
    def test_counts_refs_by_storage_location(self):
        """超储按 storage_location 命中：单列 over_limits 计数，未命中进 unmapped。"""
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            over_limits=[
                _over_limit("车间一达巴制备", "乙腈"),
                _over_limit("车间一达巴粗提", "乙醇"),
                _over_limit("危化品库", "氢氧化钠"),
                _over_limit("四楼危化品储柜", "浓氨水"),  # 未映射
                _over_limit("", "丙酮"),  # 空位置 → 占位文本
            ],
            index=build_match_index(MAP_ROWS),
        )
        pins = {p["dist_id"]: p for p in out["pins"]}
        assert pins["63"]["over_limits"] == 2  # 车间一达巴
        assert pins["35"]["over_limits"] == 1  # 危化品库
        ol_refs = [r for r in pins["63"]["refs"] if r["kind"] == "over_limit"]
        assert {r["material_name"] for r in ol_refs} == {"乙腈", "乙醇"}
        assert ol_refs[0]["total_quantity_t"] == 28.13
        unmapped = {u["text"]: u for u in out["unmapped"]}
        assert unmapped["四楼危化品储柜"]["kinds"] == ["over_limit"]
        assert unmapped["（未填写作业地点）"]["kinds"] == ["over_limit"]

    async def test_service_over_limit_reader_failure_degrades(self):
        """超储物料路失败仅记一条 error，其余路照常。"""

        async def boom_ol(d):
            raise RuntimeError("sheet 超时")

        t, f, c, k, _, h, fe, m = _ok_readers()
        svc = FacilityMapPinsService(readers=(t, f, c, k, boom_ol, h, fe, m))
        payload = await svc.get_pins(date(2026, 10, 27))
        assert payload["errors"] == ["超储物料拉取失败: sheet 超时"]
        assert payload["pins"] == []


def _key_risk(area: str, no: str = "20261027001", status: str = "已通过") -> dict:
    return {
        "report_no": no,
        "apply_status": status,
        "area": area,
        "operation_content": "结晶收粉",
        "start_time": "2026-10-27T06:00:00+00:00",
    }


def _over_limit(site: str, material: str = "乙腈") -> dict:
    return {
        "material_name": material,
        "department": "daba",
        "storage_location": site,
        "total_quantity_t": 28.13,
        "max_limit": 20.0,
        "unit": "kg",
    }


def _ok_readers(
    jobs=None, fires=None, centrals=None, key_risks=None, over_limits=None,
    hazards=None, fire_ext_dues=None, rows=None,
):
    async def ticket_reader(d):
        return jobs or []

    async def fire_reader(d):
        return fires or []

    async def central_reader(d):
        return centrals or []

    async def key_risk_reader(d):
        return key_risks or []

    async def over_limit_reader(d):
        return over_limits or []

    async def hazard_reader(d):
        return hazards if hazards is not None else {"new": [], "open": []}

    async def fire_ext_reader(d):
        return fire_ext_dues or []

    async def map_rows():
        return rows if rows is not None else MAP_ROWS

    return (
        ticket_reader,
        fire_reader,
        central_reader,
        key_risk_reader,
        over_limit_reader,
        hazard_reader,
        fire_ext_reader,
        map_rows,
    )


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

        t, f, c, k, o, h, fe, m = _ok_readers(jobs=[_job("hot_work", "车间一达托")])
        svc = FacilityMapPinsService(readers=(boom, f, c, k, o, h, fe, m))
        payload = await svc.get_pins(date(2026, 10, 26))
        assert len(payload["errors"]) == 1
        assert "作业票" in payload["errors"][0]
        # 其余路不受影响：无票贡献但映射/报警照常
        assert payload["pins"] == []
        assert payload["unmapped"] == []

    async def test_map_rows_failure_degrades(self):
        async def boom_rows():
            raise RuntimeError("db down")

        t, f, c, k, o, h, fe, _ = _ok_readers(jobs=[_job("hot_work", "车间一达托")])
        svc = FacilityMapPinsService(readers=(t, f, c, k, o, h, fe, boom_rows))
        payload = await svc.get_pins(date(2026, 10, 26))
        assert any("映射" in e for e in payload["errors"])
        # 映射表失败 → 全部进 unmapped（文本可见，图卡可解释）
        assert payload["unmapped"][0]["text"] == "车间一达托"

    async def test_key_risk_reader_failure_degrades(self):
        """关键风险作业路失败仅记一条 error，其余路照常。"""

        async def boom_kr(d):
            raise RuntimeError("bitable 超时")

        t, f, c, _, o, h, fe, m = _ok_readers()
        svc = FacilityMapPinsService(readers=(t, f, c, boom_kr, o, h, fe, m))
        payload = await svc.get_pins(date(2026, 10, 26))
        assert payload["errors"] == ["关键风险作业拉取失败: bitable 超时"]
        assert payload["pins"] == []


# ══════════════════════ 第七/八路：隐患双口径 + 消防设施到期 ══════════════════════

from types import SimpleNamespace  # noqa: E402

from app.modules.safety.service.facility_map.service import (  # noqa: E402
    fire_ext_due_rows,
    hazard_rows_for_day,
)


def _hazard(desc: str, no: str = "HZ-20261027-001", level: str = "general") -> dict:
    return {
        "hazard_no": no,
        "hazard_desc": desc,
        "hazard_level": level,
        "progress": "已联系仪表，待更换",
    }


def _fire_ext(
    location: str,
    workshop: str = "车间四",
    due: str = "2026-10-20",
    ext_type: str = "手提式干粉灭火器",
    ext_count: int = 2,
    is_overdue: bool = True,
) -> dict:
    return {
        "location": location,
        "workshop": workshop,
        "ext_type": ext_type,
        "ext_count": ext_count,
        "due_date": due,
        "is_overdue": is_overdue,
    }


class TestAggregateHazards:
    def test_counts_refs_by_description(self):
        """隐患位置内嵌描述：两级匹配落分区，hazard_news/hazard_opens 单列计数。"""
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            hazards_new=[
                _hazard("车间四二楼米尔贝合成岗位的加湿器漏水", no="HZ-1"),  # 无映射词
                _hazard("危化品库东侧通道堵塞", no="HZ-2"),  # 命中 35
                _hazard("", no="HZ-4"),  # 空描述 → 占位文本
            ],
            hazards_open=[_hazard("接罐站管廊渗漏", no="HZ-5")],  # 命中 28
            index=build_match_index(MAP_ROWS),
        )
        pins = {p["dist_id"]: p for p in out["pins"]}
        assert pins["35"]["hazard_news"] == 1
        assert pins["28"]["hazard_opens"] == 1
        new_ref = [r for r in pins["35"]["refs"] if r["kind"] == "hazard_new"][0]
        assert new_ref["hazard_no"] == "HZ-2"
        unmapped = {u["text"]: u for u in out["unmapped"]}
        assert unmapped["车间四二楼米尔贝合成岗位的加湿器漏水"]["kinds"] == ["hazard_new"]
        assert unmapped["（未填写作业地点）"]["kinds"] == ["hazard_new"]

    def test_desc_containment_hit_and_dedup_across_kinds(self):
        """同一描述当日新增且未闭环：new/open 各计一次，未命中去重合一条 unmapped。"""
        desc = "212罐区东阀法兰渗漏"
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            hazards_new=[_hazard(desc), _hazard(desc)],
            hazards_open=[_hazard(desc)],
            index=build_match_index(MAP_ROWS),
        )
        assert out["pins"] == []
        assert len(out["unmapped"]) == 1
        u = out["unmapped"][0]
        assert u["count"] == 3
        assert set(u["kinds"]) == {"hazard_new", "hazard_open"}

    def test_unmapped_text_capped_for_suggestion_table(self):
        """超长描述截 120 字符（建议表 location_text VARCHAR(128)，真扫回滚教训）。"""
        long_desc = "10月21日员工在车间二楼顶部测量风管尺寸涉高处临边作业" * 6  # 312 字符
        assert len(long_desc) > 128
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            hazards_new=[_hazard(long_desc)],
            index=build_match_index(MAP_ROWS),
        )
        assert len(out["unmapped"]) == 1
        assert len(out["unmapped"][0]["text"]) == 120
        assert out["unmapped"][0]["text"] == long_desc[:120]

    def test_ref_shape(self):
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            hazards_open=[_hazard("危化品库门口堆放杂物", no="HZ-9", level="major")],
            index=build_match_index(MAP_ROWS),
        )
        ref = out["pins"][0]["refs"][0]
        assert ref == {
            "kind": "hazard_open",
            "hazard_no": "HZ-9",
            "hazard_desc": "危化品库门口堆放杂物",
            "hazard_level": "major",
            "progress": "已联系仪表，待更换",
        }


class TestAggregateFireExt:
    def test_three_way_match_location_concat_workshop(self):
        """三试匹配：位置命中 / 车间+位置拼接命中 / 车间兜底。"""
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            fire_ext_dues=[
                _fire_ext("危化品库西门口", workshop="仓库一"),  # 位置直接命中 35
                _fire_ext("二楼东侧走廊", workshop="车间一达托"),  # 拼接命中 64
                _fire_ext("中控室角落", workshop="接罐站"),  # 前两试未中 → 车间兜底 28
                _fire_ext("陶瓷膜旁立柱", workshop="精制部"),  # 全未中 → unmapped
                _fire_ext("", workshop="精制部"),  # 位置空 → 车间也未中 → unmapped
            ],
            index=build_match_index(MAP_ROWS),
        )
        pins = {p["dist_id"]: p for p in out["pins"]}
        assert pins["35"]["fire_ext_dues"] == 1
        assert pins["64"]["fire_ext_dues"] == 1
        assert pins["28"]["fire_ext_dues"] == 1
        unmapped = {u["text"]: u for u in out["unmapped"]}
        assert unmapped["陶瓷膜旁立柱"]["kinds"] == ["fire_ext_due"]
        # 位置空时未映射文本取车间
        assert unmapped["精制部"]["kinds"] == ["fire_ext_due"]

    def test_ref_shape_with_overdue_flag(self):
        out = aggregate_pins(
            jobs=[],
            fires=[],
            centrals=[],
            fire_ext_dues=[_fire_ext("危化品库", due="2026-11-10", is_overdue=False)],
            index=build_match_index(MAP_ROWS),
        )
        ref = out["pins"][0]["refs"][0]
        assert ref["kind"] == "fire_ext_due"
        assert ref["location"] == "危化品库"
        assert ref["workshop"] == "车间四"
        assert ref["ext_type"] == "手提式干粉灭火器"
        assert ref["ext_count"] == 2
        assert ref["due_date"] == "2026-11-10"
        assert ref["is_overdue"] is False


def _hz_view(
    *,
    no: str = "HZ-1",
    desc: str = "某处隐患",
    status: str = "pending",
    discovered_at=None,
    progress: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        record_id="rec-1",
        hazard_no=no,
        description=desc,
        hazard_level="general",
        hazard_level_manual=None,
        progress_note=progress,
        discovered_at=discovered_at,
        rectification_status=status,
    )


class TestHazardRowsForDay:
    """第七路纯函数：new=检查日期落日（+8h 北京日界）；open=当前态仅今日。"""

    TODAY = date(2026, 10, 27)

    def test_new_by_check_date_with_bj_boundary(self):
        from datetime import UTC, datetime

        views = [
            # 北京 2026-10-27 09:30 → 归 10-27
            _hz_view(no="A", discovered_at=datetime(2026, 10, 27, 1, 30, tzinfo=UTC)),
            # UTC 10-26 17:30 = 北京 10-27 01:30 → 跨日界归 10-27
            _hz_view(no="B", discovered_at=datetime(2026, 10, 26, 17, 30, tzinfo=UTC)),
            # 北京 10-26 → 不归 10-27
            _hz_view(no="C", discovered_at=datetime(2026, 10, 26, 1, 30, tzinfo=UTC)),
            _hz_view(no="D", discovered_at=None),  # 无检查日期不进 new
        ]
        out = hazard_rows_for_day(views, date(2026, 10, 27), self.TODAY)
        assert [r["hazard_no"] for r in out["new"]] == ["A", "B"]

    def test_open_only_today_and_only_unclosed(self):
        """open=整改状态≠已关闭（未关闭/整改中），且仅 target=今日时返回。"""
        from datetime import UTC, datetime

        views = [
            _hz_view(no="P", status="pending"),      # 未关闭 → open
            _hz_view(no="I", status="in_progress"),  # 整改中 → open
            _hz_view(no="C", status="closed"),       # 已关闭 → 不进 open
            _hz_view(
                no="N", status="pending",
                discovered_at=datetime(2026, 10, 26, 1, 30, tzinfo=UTC),
            ),  # 昨日新增但未闭环 → 今日 open（当前态与发现日无关）
        ]
        out = hazard_rows_for_day(views, self.TODAY, self.TODAY)
        assert sorted(r["hazard_no"] for r in out["open"]) == ["I", "N", "P"]
        # 历史日期：当前态零贡献（防 AI 扫描回溯灌水）
        hist = hazard_rows_for_day(views, date(2026, 10, 26), self.TODAY)
        assert hist["open"] == []

    def test_row_shape_progress_kept(self):
        out = hazard_rows_for_day(
            [_hz_view(no="X", desc=" 描述 ", progress="施工中 ")],
            self.TODAY,
            self.TODAY,
        )
        assert out["open"] == [{
            "hazard_no": "X",
            "hazard_desc": " 描述 ",
            "hazard_level": "general",
            "progress": "施工中",
        }]


def _fire_record(
    *,
    due_ms: int | None,
    formula_ms: int | None = None,
    workshop: str = "车间四",
    location: str = "二楼东侧走廊",
    status: str | None = None,
    ext_count: int = 2,
    record_id: str = "recF",
) -> dict:
    fields: dict = {
        "车间": workshop,
        "位置": location,
        "灭火器类型": "手提式干粉灭火器",
        "数量": ext_count,
        "生产日期": 1600000000000,
    }
    if due_ms is not None:
        fields["到期日期"] = due_ms
    if formula_ms is not None:
        fields["到期日期（公式自动生成）"] = {"type": 5, "value": [formula_ms]}
    if status is not None:
        fields["状态"] = status
    return {"record_id": record_id, "fields": fields}


def _bj_ms(d: date) -> int:
    from datetime import UTC, datetime, timedelta

    # 造一个 +8h 后落在北京日 d 的毫秒时间戳（真实表存 d 00:00 北京时，
    # 即 UTC 前一日 16:00；提取侧只关心 +8h 后落日）
    return int((datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(hours=8)).timestamp() * 1000)


class TestFireExtDueRows:
    """第八路纯函数：到期/临期 30 天口径 + 公式列回退 + 停用剔除。"""

    TODAY = date(2026, 10, 27)

    def test_overdue_soon_excluded_ranges(self):
        records = [
            _fire_record(due_ms=_bj_ms(date(2026, 10, 20)), record_id="overdue"),
            _fire_record(due_ms=_bj_ms(date(2026, 11, 20)), record_id="soon"),   # +24d
            _fire_record(due_ms=_bj_ms(date(2026, 11, 26)), record_id="edge"),   # +30d 含
            _fire_record(due_ms=_bj_ms(date(2026, 11, 27)), record_id="far"),    # +31d 排除
            _fire_record(due_ms=_bj_ms(date(2026, 12, 15)), record_id="far2"),
        ]
        rows = fire_ext_due_rows(records, self.TODAY)
        assert [r["due_date"] for r in rows] == [
            "2026-10-20", "2026-11-20", "2026-11-26",
        ]
        assert rows[0]["is_overdue"] is True
        assert rows[1]["is_overdue"] is False
        assert rows[0]["ext_type"] == "手提式干粉灭火器"
        assert rows[0]["ext_count"] == 2
        assert rows[0]["workshop"] == "车间四"
        assert rows[0]["location"] == "二楼东侧走廊"

    def test_formula_column_fallback(self):
        """普通「到期日期」缺值时解包公式列 {'type':5,'value':[ms]}。"""
        records = [
            _fire_record(
                due_ms=None,
                formula_ms=_bj_ms(date(2026, 10, 1)),
                record_id="formula",
            ),
            _fire_record(due_ms=None, formula_ms=None, record_id="nodue"),  # 无到期值
        ]
        rows = fire_ext_due_rows(records, self.TODAY)
        assert [r["due_date"] for r in rows] == ["2026-10-01"]
        assert rows[0]["is_overdue"] is True

    def test_inactive_status_excluded(self):
        records = [
            _fire_record(due_ms=_bj_ms(date(2026, 10, 20)), status="已报废", record_id="scrapped"),
            _fire_record(due_ms=_bj_ms(date(2026, 10, 20)), status="在用", record_id="active"),
        ]
        rows = fire_ext_due_rows(records, self.TODAY)
        assert len(rows) == 1


class TestPinsServiceNewReaders:
    async def test_hazard_reader_failure_degrades(self):
        """隐患路失败仅记一条 error，其余路照常。"""

        async def boom_hz(d):
            raise RuntimeError("bitable 超时")

        t, f, c, k, o, _, fe, m = _ok_readers()
        svc = FacilityMapPinsService(readers=(t, f, c, k, o, boom_hz, fe, m))
        payload = await svc.get_pins(date(2026, 10, 27))
        assert payload["errors"] == ["隐患拉取失败: bitable 超时"]
        assert payload["pins"] == []

    async def test_fire_ext_reader_failure_degrades(self):
        """消防设施到期路失败仅记一条 error，其余路照常。"""

        async def boom_fe(d):
            raise RuntimeError("台账超时")

        t, f, c, k, o, h, _, m = _ok_readers()
        svc = FacilityMapPinsService(readers=(t, f, c, k, o, h, boom_fe, m))
        payload = await svc.get_pins(date(2026, 10, 27))
        assert payload["errors"] == ["消防设施到期拉取失败: 台账超时"]
        assert payload["pins"] == []

    async def test_hazard_dual_kinds_flow_through_service(self):
        """双口径经服务编排：描述命中/未命中进 pins/unmapped，两种 kind 各自计数。"""
        desc_hit = "危化品库门口堆放杂物"
        desc_miss = "212罐区渗漏"
        t, f, c, k, o, h, fe, m = _ok_readers(
            hazards={"new": [_hazard(desc_hit, no="N1")], "open": [_hazard(desc_miss, no="O1")]},
            fire_ext_dues=[_fire_ext("危化品库")],
        )
        svc = FacilityMapPinsService(readers=(t, f, c, k, o, h, fe, m))
        payload = await svc.get_pins(date(2026, 10, 27))
        assert payload["errors"] == []
        pin = {p["dist_id"]: p for p in payload["pins"]}["35"]
        assert pin["hazard_news"] == 1
        assert pin["hazard_opens"] == 0
        assert pin["fire_ext_dues"] == 1
        assert payload["unmapped"] == [
            {"text": desc_miss, "count": 1, "kinds": ["hazard_open"]}
        ]
