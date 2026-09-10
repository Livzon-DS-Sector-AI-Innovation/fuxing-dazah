"""WorkTicketParser 单测。

夹具基于《作业票字段映射.md》实测样例的时间点构造（动火 DH-20260826-009、
受限 2026-08-26、临电 2026-08-24、高处 2026-08-25、吊装 2026-08-20）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.workticket_review.parser import (
    WorkTicketParser,
    _extract_person_name,
)

TZ = ZoneInfo("Asia/Shanghai")
PARSER = WorkTicketParser()


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=TZ)


# ── 动火 DH-20260826-009 ──
HOT_WORK_RECORD = {
    "type": "hot_work",
    "processInstanceId": "pi-hot-20260826-009",
    "serialNumber": "DH-20260826-009",
    "createTime": "2026-08-26 08:36:49",
    "status": "已完成",
    "variables": {
        "a165650258429577527": "2026-08-26 08:36:49",  # 申请
        "a166419575104497385": "2026-08-26 08:41:58",  # 审批
        "a166452480843974469": "2026-08-26 08:41:58",  # 开始
        "a170041634227259322": "2026-08-26 18:00:00",  # 结束
        "a165630881894418049": "2026-08-26 18:30:00",  # 验收
        "a165650253075756898": "3",  # 级别
        "a165630293247793609": "精制二楼外包间",  # 作业地点
        "a17004237047999564": "传递窗焊接",  # 作业内容
        "a170252536882522756": "张三",  # 监护人
        "a165630121327216736": "精制工程一部",  # 作业申请单位
        "a172363237973025304": [
            {
                "a172363239131846707": "2026-08-26 08:39:12",
                "a178209307785154295": "可燃气体",
                "a172363241848930141": "动火点周围10米范围内",
                "a178105953631186497": "8",
                "a172363244087761084": "张三",
            }
        ],
    },
    "raw": {},
}

# ── 受限空间 2026-08-26 ──
CONFINED_SPACE_RECORD = {
    "type": "confined_space",
    "processInstanceId": "pi-confined-20260826-001",
    "serialNumber": "SX-20260826-001",
    "createTime": "2026-08-26 08:40:53",
    "status": "已完成",
    "variables": {
        "a16641060774353234": "2026-08-26 08:40:53",
        "a166410758162945511": "2026-08-26 08:47:25",
        "a166453188464160986": "2026-08-26 08:47:25",
        "a170042229891083000": "2026-08-26 09:47:43",
        "a166410776737522241": "2026-08-26 10:00:00",
        "a166410609024835397": "316罐",  # 作业地点
        "a166410613064325902": "下罐清洗",  # 作业内容
        "a166410620739930378": "李四",  # 监护人
        "a166410606207583945": "精制工程一部",  # 作业申请单位
        "a166410665378134029": [
            {
                "a178122990256724485": "5",  # CO
                "a178151594361358704": "0",  # H2S
                "a17812299375743341": "0",  # 可燃气体
                "a178122997925123872": "20.9",  # O2
                "a178151606577118213": "",  # 其他气体
                "a178123009097044840": "中",  # 分析部位
                "a16645280308068256": "2026-08-26 08:41:52",  # 取样分析时间
                "a166452702345263": "李四",  # 分析人
            }
        ],
    },
    "raw": {},
}

# ── 临时用电 2026-08-24 ──
TEMP_ELECTRICITY_RECORD = {
    "type": "temporary_electricity",
    "processInstanceId": "pi-temp-20260824-001",
    "serialNumber": "LD-20260824-001",
    "createTime": "2026-08-24 11:01:49",
    "status": "已完成",
    "variables": {
        "a166383861113656766": "2026-08-24 11:01:49",
        "a177848303150752064": "2026-08-24 14:01:24",
        "a170041805999891768": "2026-08-24 11:23:11",
        "a170041805749718609": "2026-09-10 18:00:00",
        "a166410489854421267": "2026-09-10 18:30:00",
        "a16641028864938014": "王五",  # 监护人
        "a166383857539164012": "精制工程一部",  # 作业申请单位
        "a177848236214587756": [
            {
                "a177848237194078709": "2026-08-24 11:07:43",
                "a177848239637796101": "电源接入及接出点周围10米范围内",
                "a178107199973030298": "5",
                "a177848241621543172": "王五",
            }
        ],
    },
    "raw": {},
}

# ── 高处 2026-08-25 ──
HEIGHT_WORK_RECORD = {
    "type": "height_work",
    "processInstanceId": "pi-height-20260825-001",
    "serialNumber": "GC-20260825-001",
    "createTime": "2026-08-25 09:21:12",
    "status": "已完成",
    "variables": {
        "a166408729356021698": "2026-08-25 09:21:12",
        "a166436843500716619": "2026-08-25 11:11:32",
        "a166452791850159946": "2026-08-25 11:11:32",
        "a177848359402613260": "2026-08-25 18:00:09",
        "a166409624671435562": "2026-08-25 16:56:19",
        "a16640875432179735": "1",
        "a166408737588058926": "小喷一楼外围",  # 作业地点
        "a177864973070780254": "关闭冷却水管道阀门",  # 作业内容
        "a166408791521312347": "赵六",  # 监护人
        "a166408724179080906": "精制工程一部",  # 作业申请单位
    },
    "raw": {},
}

# ── 吊装 2026-08-20 ──
LIFTING_RECORD = {
    "type": "lifting",
    "processInstanceId": "pi-lifting-20260820-001",
    "serialNumber": "DZ-20260820-001",
    "createTime": "2026-08-20 14:07:47",
    "status": "已完成",
    "variables": {
        "a166408729356021698": "2026-08-20 14:07:47",
        "a166411175918929660": "2026-08-20 14:52:07",
        "a166479946544515540": "2026-08-20 14:52:07",
        "a177848849477682484": "2026-08-20 18:00:00",
        "a166409624671435562": "2026-08-20 16:26:11",
        "a169269029480488045": "3",
        "a166408737588058926": "集装箱冷柜存放区",  # 作业地点
        "a166408741502483696": "一台5吨集装箱冷柜",  # 作业内容
        "a166408791521312347": "孙七",  # 监护人
        "a166408724179080906": "精制工程一部",  # 作业申请单位
    },
    "raw": {},
}

# ── 断路 2026-08-21（无监护人/申请单位字段，验证空值容错） ──
ROAD_BREAKING_RECORD = {
    "type": "road_breaking",
    "processInstanceId": "pi-road-20260821-001",
    "serialNumber": "DL-20260821-001",
    "createTime": "2026-08-21 09:00:00",
    "status": "已完成",
    "variables": {
        "a17785549722689677": "2026-08-21 09:00:00",
        "a166420312995199239": "2026-08-21 09:10:00",
        "a166478570334536959": "2026-08-21 09:20:00",
        "a170042270360247393": "2026-08-21 18:00:00",
        "a166409624671435562": "2026-08-21 18:30:00",
    },
    "raw": {},
}


def test_hot_work_normalizes_times_level_and_gas() -> None:
    ticket = PARSER.normalize(HOT_WORK_RECORD, "hot_work")

    assert ticket.ticket_type == "hot_work"
    assert ticket.ticket_no == "DH-20260826-009"
    assert ticket.apply_time == _dt(2026, 8, 26, 8, 36, 49)
    assert ticket.approve_time == _dt(2026, 8, 26, 8, 41, 58)
    assert ticket.start_time == _dt(2026, 8, 26, 8, 41, 58)
    assert ticket.end_time == _dt(2026, 8, 26, 18, 0, 0)
    assert ticket.finish_time == _dt(2026, 8, 26, 18, 30, 0)
    assert ticket.level == "三级"  # 原始值 '3' → 归一化 '三级'（对齐 SUBSIDY_RATES）
    assert ticket.work_site == "精制二楼外包间"
    assert ticket.work_content == "传递窗焊接"
    assert ticket.gasless is False
    assert len(ticket.gas_analysis) == 1
    gas = ticket.gas_analysis[0]
    assert gas.analysis_time == _dt(2026, 8, 26, 8, 39, 12)
    assert gas.point == "动火点周围10米范围内"
    assert gas.gas_name == "可燃气体"
    assert gas.value == "8"
    assert ticket.missing == []


def test_confined_space_normalizes_gas_columns() -> None:
    ticket = PARSER.normalize(CONFINED_SPACE_RECORD, "confined_space")

    assert ticket.ticket_type == "confined_space"
    assert ticket.apply_time == _dt(2026, 8, 26, 8, 40, 53)
    assert ticket.approve_time == _dt(2026, 8, 26, 8, 47, 25)
    assert ticket.start_time == _dt(2026, 8, 26, 8, 47, 25)
    assert ticket.end_time == _dt(2026, 8, 26, 9, 47, 43)
    assert ticket.finish_time == _dt(2026, 8, 26, 10, 0, 0)
    assert ticket.level is None
    assert ticket.work_site == "316罐"
    assert ticket.work_content == "下罐清洗"
    assert ticket.gasless is False
    assert len(ticket.gas_analysis) == 1
    gas = ticket.gas_analysis[0]
    assert gas.analysis_time == _dt(2026, 8, 26, 8, 41, 52)
    assert gas.point == "中"
    assert gas.co == "5"
    assert gas.h2s == "0"
    assert gas.lel == "0"
    assert gas.o2 == "20.9"
    assert ticket.missing == []


def test_temporary_electricity_normalizes_gas() -> None:
    ticket = PARSER.normalize(TEMP_ELECTRICITY_RECORD, "temporary_electricity")

    assert ticket.ticket_type == "temporary_electricity"
    assert ticket.apply_time == _dt(2026, 8, 24, 11, 1, 49)
    assert ticket.approve_time == _dt(2026, 8, 24, 14, 1, 24)
    assert ticket.start_time == _dt(2026, 8, 24, 11, 23, 11)
    assert ticket.end_time == _dt(2026, 9, 10, 18, 0, 0)
    assert ticket.finish_time == _dt(2026, 9, 10, 18, 30, 0)
    assert ticket.level is None
    assert ticket.gasless is False
    assert len(ticket.gas_analysis) == 1
    gas = ticket.gas_analysis[0]
    assert gas.analysis_time == _dt(2026, 8, 24, 11, 7, 43)
    assert gas.point == "电源接入及接出点周围10米范围内"
    assert gas.lel == "5"


def test_height_work_is_gasless() -> None:
    ticket = PARSER.normalize(HEIGHT_WORK_RECORD, "height_work")

    assert ticket.ticket_type == "height_work"
    assert ticket.apply_time == _dt(2026, 8, 25, 9, 21, 12)
    assert ticket.approve_time == _dt(2026, 8, 25, 11, 11, 32)
    assert ticket.start_time == _dt(2026, 8, 25, 11, 11, 32)
    assert ticket.end_time == _dt(2026, 8, 25, 18, 0, 9)
    assert ticket.finish_time == _dt(2026, 8, 25, 16, 56, 19)
    assert ticket.level == "一级"  # 原始值 '1' → 归一化 '一级'（对齐 SUBSIDY_RATES）
    assert ticket.work_site == "小喷一楼外围"
    assert ticket.work_content == "关闭冷却水管道阀门"
    assert ticket.gasless is True
    assert ticket.gas_analysis == []
    assert ticket.missing == []


def test_lifting_is_gasless() -> None:
    ticket = PARSER.normalize(LIFTING_RECORD, "lifting")

    assert ticket.ticket_type == "lifting"
    assert ticket.apply_time == _dt(2026, 8, 20, 14, 7, 47)
    assert ticket.approve_time == _dt(2026, 8, 20, 14, 52, 7)
    assert ticket.start_time == _dt(2026, 8, 20, 14, 52, 7)
    assert ticket.end_time == _dt(2026, 8, 20, 18, 0, 0)
    assert ticket.finish_time == _dt(2026, 8, 20, 16, 26, 11)
    assert ticket.level == "三级"  # 原始值 '3' → 归一化 '三级'（对齐 SUBSIDY_RATES）
    assert ticket.work_site == "集装箱冷柜存放区"
    assert ticket.work_content == "一台5吨集装箱冷柜"
    assert ticket.gasless is True
    assert ticket.gas_analysis == []
    assert ticket.missing == []


def test_hot_work_extracts_guardian_and_apply_unit() -> None:
    ticket = PARSER.normalize(HOT_WORK_RECORD, "hot_work")

    assert ticket.guardian == "张三"
    assert ticket.apply_unit == "精制工程一部"
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_confined_space_extracts_guardian_and_apply_unit() -> None:
    ticket = PARSER.normalize(CONFINED_SPACE_RECORD, "confined_space")

    assert ticket.guardian == "李四"
    assert ticket.apply_unit == "精制工程一部"
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_height_work_extracts_guardian_and_apply_unit() -> None:
    ticket = PARSER.normalize(HEIGHT_WORK_RECORD, "height_work")

    assert ticket.guardian == "赵六"
    assert ticket.apply_unit == "精制工程一部"
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_temporary_electricity_extracts_guardian_and_apply_unit() -> None:
    ticket = PARSER.normalize(TEMP_ELECTRICITY_RECORD, "temporary_electricity")

    assert ticket.guardian == "王五"
    assert ticket.apply_unit == "精制工程一部"
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_lifting_extracts_guardian_and_apply_unit() -> None:
    ticket = PARSER.normalize(LIFTING_RECORD, "lifting")

    assert ticket.guardian == "孙七"
    assert ticket.apply_unit == "精制工程一部"
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_guardian_prefers_dollar_display_value() -> None:
    record: dict[str, Any] = dict(HOT_WORK_RECORD)
    variables = dict(record["variables"])
    variables["a170252536882522756"] = "1234567"  # 原始值为人员内部 id
    variables["$a170252536882522756"] = "张三"  # $id 显示值
    record["variables"] = variables

    ticket = PARSER.normalize(record, "hot_work")

    assert ticket.guardian == "张三"
    assert ticket.apply_unit == "精制工程一部"


def test_road_breaking_missing_guardian_unit_stays_empty() -> None:
    ticket = PARSER.normalize(ROAD_BREAKING_RECORD, "road_breaking")

    assert ticket.ticket_type == "road_breaking"
    assert ticket.guardian == ""
    assert ticket.apply_unit == ""
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_blind_plate_missing_guardian_unit_stays_empty() -> None:
    record = {
        "type": "blind_plate",
        "processInstanceId": "pi-blind-20260826-002",
        "serialNumber": "MB-20260826-002",
        "createTime": "2026-08-26 10:00:00",
        "status": "进行中",
        "variables": {
            "a170042282670256499": "2026-08-26 09:00:00",
            "a177849085922113675": "2026-08-26 09:10:00",
            "a170042295009091843": "2026-08-26 09:20:00",
        },
        "raw": {},
    }

    ticket = PARSER.normalize(record, "blind_plate")

    assert ticket.guardian == ""
    assert ticket.apply_unit == ""
    assert "guardian" not in ticket.missing
    assert "apply_unit" not in ticket.missing


def test_extract_person_name_variants() -> None:
    assert _extract_person_name(None) == ""
    assert _extract_person_name("") == ""
    assert _extract_person_name("   ") == ""
    assert _extract_person_name("张三") == "张三"
    assert _extract_person_name("张三,李四") == "张三"
    assert _extract_person_name("张三 李四") == "张三"
    assert _extract_person_name("张三、李四") == "张三"
    assert _extract_person_name(["张三", "李四"]) == "张三"
    assert _extract_person_name({"name": "张三"}) == "张三"


def test_missing_apply_time_is_reported() -> None:
    record: dict[str, Any] = dict(HOT_WORK_RECORD)
    variables = dict(record["variables"])
    variables.pop("a165650258429577527")
    record["variables"] = variables

    ticket = PARSER.normalize(record, "hot_work")

    assert ticket.apply_time is None
    assert "apply_time" in ticket.missing
    assert ticket.start_time is not None


def test_milliseconds_timestamp_is_supported() -> None:
    from app.modules.safety.workticket_review.parser import _parse_datetime

    ms = 1_785_120_049_000  # 2026-08-26 08:36:49 Asia/Shanghai (约)
    parsed = _parse_datetime(ms)
    assert parsed is not None
    assert parsed.tzinfo == TZ


def test_process_definition_key_is_accepted() -> None:
    from app.modules.safety.workticket_review.client import TICKET_TYPE_KEYS

    record = dict(HEIGHT_WORK_RECORD)
    ticket = PARSER.normalize(record, TICKET_TYPE_KEYS["height_work"])

    assert ticket.ticket_type == "height_work"
    assert ticket.gasless is True


def test_blind_plate_reports_missing_end_and_finish() -> None:
    record = {
        "type": "blind_plate",
        "processInstanceId": "pi-blind-20260826-001",
        "serialNumber": "MB-20260826-001",
        "createTime": "2026-08-26 09:00:00",
        "status": "进行中",
        "variables": {
            "a170042282670256499": "2026-08-26 09:00:00",
            "a177849085922113675": "2026-08-26 09:10:00",
            "a170042295009091843": "2026-08-26 09:20:00",
        },
        "raw": {},
    }

    ticket = PARSER.normalize(record, "blind_plate")

    assert ticket.ticket_type == "blind_plate"
    assert ticket.start_time is not None
    assert ticket.end_time is None
    assert ticket.finish_time is None
    assert "end_time" in ticket.missing
    assert "finish_time" in ticket.missing
    assert ticket.gasless is True
    assert ticket.gas_analysis == []


def test_gas_type_missing_gas_table_reports_missing() -> None:
    record: dict[str, Any] = dict(HOT_WORK_RECORD)
    variables = dict(record["variables"])
    variables["a172363237973025304"] = []
    record["variables"] = variables

    ticket = PARSER.normalize(record, "hot_work")

    assert "gas_analysis" in ticket.missing
    assert ticket.gasless is False
    assert ticket.gas_analysis == []


# ── level 归一化（ticket 08 P0 修复：raw 值 → SUBSIDY_RATES 键形） ──


def test_level_prefers_dollar_display_value() -> None:
    """动火 E2E 实测：raw='2' 但 $显示='一级' → level='一级'（复用 _field_display_value）。"""
    record: dict[str, Any] = dict(HOT_WORK_RECORD)
    variables = dict(record["variables"])
    variables["a165650253075756898"] = "2"
    variables["$a165650253075756898"] = "一级"
    record["variables"] = variables

    ticket = PARSER.normalize(record, "hot_work")

    assert ticket.level == "一级"


def test_level_strips_parentheses_and_maps_roman_display() -> None:
    """高处 E2E 实测：raw='1' + $显示='Ⅰ级（2≤h≤5m）' → 剥括注并映射 'Ⅰ'→'一' → '一级'。"""
    record: dict[str, Any] = dict(HEIGHT_WORK_RECORD)
    variables = dict(record["variables"])
    variables["a16640875432179735"] = "1"
    variables["$a16640875432179735"] = "Ⅰ级（2≤h≤5m）"
    record["variables"] = variables

    ticket = PARSER.normalize(record, "height_work")

    assert ticket.level == "一级"


def test_level_normalizes_raw_digit_when_no_display() -> None:
    """吊装 E2E 实测：raw='3'（无 $显示值）→ 回退原始值并归一化 → '三级'。"""
    ticket = PARSER.normalize(LIFTING_RECORD, "lifting")

    assert ticket.level == "三级"


def test_level_chinese_passthrough() -> None:
    """已中文化的 level 原样通过（'二级'/'特级'）。"""
    for raw, expected in (("二级", "二级"), ("特级", "特级")):
        record: dict[str, Any] = dict(HOT_WORK_RECORD)
        variables = dict(record["variables"])
        variables["a165650253075756898"] = raw
        record["variables"] = variables

        ticket = PARSER.normalize(record, "hot_work")

        assert ticket.level == expected, f"raw={raw!r}"


def test_level_unrecognized_returns_empty() -> None:
    """无法识别的 level → ''（补贴侧走默认费率，不按 0 直接流失）。"""
    record: dict[str, Any] = dict(HOT_WORK_RECORD)
    variables = dict(record["variables"])
    variables["a165650253075756898"] = "XL"
    record["variables"] = variables

    ticket = PARSER.normalize(record, "hot_work")

    assert ticket.level == ""


def test_normalize_level_variants() -> None:
    """_normalize_level 规则覆盖：括注/罗马数字/阿拉伯数字/前缀/无法识别。"""
    from app.modules.safety.workticket_review.parser import _normalize_level

    # 括注剥离 + 全角罗马数字
    assert _normalize_level("Ⅰ级（2≤h≤5m）") == "一级"
    assert _normalize_level("Ⅱ级") == "二级"
    assert _normalize_level("Ⅲ级") == "三级"
    assert _normalize_level("Ⅳ级") == "四级"
    # 半角罗马数字（大小写）
    assert _normalize_level("II级") == "二级"
    assert _normalize_level("iii级") == "三级"
    assert _normalize_level("I 级") == "一级"
    # 阿拉伯数字（全/半角）
    assert _normalize_level("1级") == "一级"
    assert _normalize_level("2") == "二级"
    assert _normalize_level("３级") == "三级"
    # 前缀清洗
    assert _normalize_level("作业级别：二级") == "二级"
    assert _normalize_level("级别二级") == "二级"
    # 中文原样
    assert _normalize_level("二级") == "二级"
    assert _normalize_level("特级") == "特级"
    # 无五级费率 → 无法识别 → ''
    assert _normalize_level("5级") == ""
    # 完全无法识别 → ''
    assert _normalize_level("x") == ""
    assert _normalize_level("") == ""


# ── 规则五：动火方式 + 人员子表（2026-09-08 实测 DH-20260829-002 表单结构） ──

def _personnel_row(role: str, name: str, cert_no: str) -> dict[str, Any]:
    """按平台人员子表真实结构构造一行（原始值 + $显示值）。"""
    return {
        "a177848145226757987": "col_1778479754936",
        "$a177848145226757987": role,
        "a167100943924123367": "person-1",
        "$a167100943924123367": name,
        "a170252523934992609": "cert-1" if cert_no else "",
        "$a170252523934992609": cert_no,
    }


def test_hot_work_mode_and_personnel_parsed() -> None:
    record = {
        "type": "hot_work",
        "serialNumber": "DH-20260829-002",
        "variables": {
            **HOT_WORK_RECORD["variables"],
            "$a165630136371848108": "电焊,切割机",
            "a167100942578186627": [
                _personnel_row("特种作业人员", "刘飞云", "T410522198402010817"),
                _personnel_row("普工", "吴志刚", ""),
            ],
        },
    }
    ticket = PARSER.normalize(record, "hot_work")
    assert ticket.work_mode == "电焊,切割机"
    assert [(p.role, p.name, p.cert_no) for p in ticket.personnel] == [
        ("特种作业人员", "刘飞云", "T410522198402010817"),
        ("普工", "吴志刚", ""),
    ]


def test_personnel_absent_returns_empty_and_mode_none() -> None:
    """历史票无人员子表/动火方式字段时优雅退化，且不污染 missing。"""
    ticket = PARSER.normalize(dict(HOT_WORK_RECORD), "hot_work")
    assert ticket.personnel == []
    assert ticket.work_mode is None
    assert "work_mode" not in ticket.missing
    assert "personnel" not in ticket.missing


def test_personnel_cert_display_value_preferred_over_raw() -> None:
    """$显示值缺失时回退原始值列（姓名/证件都是 id 型字段，显示值优先）。"""
    record = {
        "type": "hot_work",
        "serialNumber": "DH-TEST-CERT",
        "variables": {
            **HOT_WORK_RECORD["variables"],
            "a165630136371848108": "电焊",
            "a167100942578186627": [
                {
                    "a177848145226757987": "col_x",
                    "a167100943924123367": "王五",
                    "a170252523934992609": "T320826197608240816",
                }
            ],
        },
    }
    ticket = PARSER.normalize(record, "hot_work")
    assert ticket.work_mode == "电焊"
    assert ticket.personnel[0].name == "王五"
    assert ticket.personnel[0].cert_no == "T320826197608240816"
