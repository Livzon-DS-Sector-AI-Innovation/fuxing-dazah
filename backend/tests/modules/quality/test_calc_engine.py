"""色谱计算引擎测试：归一化法与外标法的数值正确性、未检出、RSD。"""

from app.modules.quality import calc_engine

NORM_CFG = {
    "mode": "normalization",
    "rrf": 25,
    "samples": 2,
    "main_item": {"label": "万古霉素B", "std_name": "万古霉素B"},
    "impurities": [
        {"key": "杂质F", "label": "杂质F（AF）", "std_name": "杂质F"},
        {"key": "杂质I", "label": "杂质I（AI）", "std_name": "杂质I"},
    ],
    "total_std_name": "总杂质",
}

EXT_CFG = {
    "mode": "external_std",
    "samples": 2,
    "std_injections": 5,
    "dilution_factor": 5,
    "ppm_scale": 1000000,
    "solvents": [
        {"key": "乙醛", "label": "乙醛", "std_name": "乙醛", "limit": "乙醛≤440ppm"},
    ],
}


def test_normalization_math():
    # 主峰 1,000,000；总峰 1,010,000 → At=10,000；分母 = 25×1e6+1e4
    inputs = {
        "total_peak_1": 1010000, "main_peak_1": 1000000,
        "total_peak_2": 1008000, "main_peak_2": 1000000,
        "杂质F_1": 5000, "杂质F_2": 4000,
        "杂质I_1": "",  # 未检出 → 0%
        "杂质I_2": 0,
    }
    result = calc_engine.compute_normalization(NORM_CFG, inputs)
    by_name = {i["std_name"]: i for i in result["items"]}
    # 分母1 = 25,010,000；分母2 = 25,008,000；万古霉素B% = 双份平均
    b1 = 25_000_000 / 25_010_000 * 100
    b2 = 25_000_000 / 25_008_000 * 100
    assert abs(by_name["万古霉素B"]["value"] - (b1 + b2) / 2) < 1e-9
    # 杂质F：第1份 5000/25,010,000×100，第2份 4000/25,008,000×100，取平均
    f1 = 5000 / 25_010_000 * 100
    f2 = 4000 / 25_008_000 * 100
    assert abs(by_name["杂质F"]["value"] - (f1 + f2) / 2) < 1e-9
    # 未检出：0%
    assert by_name["杂质I"]["value"] == 0.0 and by_name["杂质I"]["nd"] is True
    # 总杂质 = 杂质F 平均 + 杂质I 平均
    assert abs(by_name["总杂质"]["value"] - by_name["杂质F"]["value"]) < 1e-9


def test_normalization_missing_main_peak_skipped():
    result = calc_engine.compute_normalization(NORM_CFG, {"total_peak_1": 1010000, "main_peak_1": ""})
    assert result["denom"] == [None, None]
    by_name = {i["std_name"]: i for i in result["items"]}
    assert by_name["万古霉素B"]["value"] is None


def test_external_std_math_and_rsd():
    inputs = {
        "乙醛_std_mass": 50, "乙醛_std_vol": 10, "乙醛_std_purity": 0.99,
        "乙醛_std_area_1": 1000, "乙醛_std_area_2": 1010, "乙醛_std_area_3": 990,
        "乙醛_std_area_4": 1005, "乙醛_std_area_5": 995,
        "乙醛_sample_mass_1": 500, "乙醛_sample_area_1": 800,
        "乙醛_sample_mass_2": 500, "乙醛_sample_area_2": 800,
    }
    result = calc_engine.compute_external_std(EXT_CFG, inputs)
    item = result["items"][0]
    # ppm = 800×50×0.99×5/(1000×500×10)×1e6 = 39600
    assert abs(item["value"] - 39600.0) < 1e-6
    assert item["std_avg"] == 1000.0
    # 对照 RSD：std=sqrt((0+100+100+25+25)/4)=7.906 → 0.7906%
    assert abs((item["std_rsd"] or 0) - 0.79) < 0.01


def test_external_std_content_math():
    cfg = {"mode": "external_std_content", "samples": 3, "main_std_name": "含量"}
    # 达托霉素公式：含量% = 标准1质量×标准品含量×样面积/样质量/标准1平均面积/(1-水分%)×100
    inputs = {
        "std1_mass": 25.2, "std_content": 0.955,
        "std_area_1": 1000000, "std_area_2": 1002000, "std_area_3": 998000,
        "std_area_4": 1001000, "std_area_5": 999000,
        "sample_area_1": 980000, "sample_mass_1": 25.0,
        "sample_area_2": 985000, "sample_mass_2": 25.1,
        "sample_area_3": 978000, "sample_mass_3": 25.0,
        "moisture": 0.5,
    }
    result = calc_engine.compute_external_std_content(cfg, inputs)
    item = result["items"][0]
    std_avg = (1000000 + 1002000 + 998000 + 1001000 + 999000) / 5
    c1 = 25.2 * 0.955 * 980000 / 25.0 / std_avg / (1 - 0.5 / 100) * 100
    c2 = 25.2 * 0.955 * 985000 / 25.1 / std_avg / (1 - 0.5 / 100) * 100
    c3 = 25.2 * 0.955 * 978000 / 25.0 / std_avg / (1 - 0.5 / 100) * 100
    assert abs(item["value"] - (c1 + c2 + c3) / 3) < 1e-9
    assert item["std_avg"] == std_avg
    assert item["std_rsd"] is not None and item["std_rsd"] < 0.2


def test_content_multi_math():
    cfg = {
        "mode": "external_std_content_multi", "samples": 3,
        "components": [
            {"key": "A3", "label": "A3", "std_name": "米尔贝肟A3"},
            {"key": "A4", "label": "A4", "std_name": "米尔贝肟A4"},
        ],
        "total_std_name": "总含量",
    }
    # 米尔贝肟公式（输出百分数）：A3% = 标准1质量×A3含量×样面积/样质量/标准1平均面积/(1-水分%)×100
    inputs = {
        "std1_mass": 25.0, "std_content_A3": 0.2, "std_content_A4": 0.8,
        "std_area_A3_1": 100000, "std_area_A3_2": 100200, "std_area_A3_3": 99900,
        "std_area_A3_4": 100100, "std_area_A3_5": 100000,
        "std_area_A4_1": 400000, "std_area_A4_2": 400500, "std_area_A4_3": 399800,
        "std_area_A4_4": 400200, "std_area_A4_5": 400000,
        "sample_mass_1": 25.1, "sample_area_A3_1": 100300, "sample_area_A4_1": 401200,
        "sample_mass_2": 25.0, "sample_area_A3_2": 100100, "sample_area_A4_2": 400400,
        "sample_mass_3": 25.2, "sample_area_A3_3": 100500, "sample_area_A4_3": 402000,
        "moisture": 0.3,
    }
    result = calc_engine.compute_content_multi(cfg, inputs)
    by_name = {i["std_name"]: i for i in result["items"]}
    a3_avg = (100000 + 100200 + 99900 + 100100 + 100000) / 5
    a4_avg = (400000 + 400500 + 399800 + 400200 + 400000) / 5
    a3_1 = 25.0 * 0.2 * 100300 / 25.1 / a3_avg / (1 - 0.3 / 100) * 100
    a3_2 = 25.0 * 0.2 * 100100 / 25.0 / a3_avg / (1 - 0.3 / 100) * 100
    a3_3 = 25.0 * 0.2 * 100500 / 25.2 / a3_avg / (1 - 0.3 / 100) * 100
    assert abs(by_name["米尔贝肟A3"]["value"] - (a3_1 + a3_2 + a3_3) / 3) < 1e-9
    a4_1 = 25.0 * 0.8 * 401200 / 25.1 / a4_avg / (1 - 0.3 / 100) * 100
    a4_2 = 25.0 * 0.8 * 400400 / 25.0 / a4_avg / (1 - 0.3 / 100) * 100
    a4_3 = 25.0 * 0.8 * 402000 / 25.2 / a4_avg / (1 - 0.3 / 100) * 100
    assert abs(by_name["米尔贝肟A4"]["value"] - (a4_1 + a4_2 + a4_3) / 3) < 1e-9
    # 总含量 = A3+A4 平均
    assert abs(
        by_name["总含量"]["value"] - (by_name["米尔贝肟A3"]["value"] + by_name["米尔贝肟A4"]["value"])
    ) < 1e-9


def test_impurity_vs_std_math():
    cfg = {
        "mode": "impurity_vs_std", "samples": 2,
        "components": [{"key": "A3", "label": "A3", "std_name": "A3"}, {"key": "A4", "label": "A4", "std_name": "A4"}],
        "impurities": [
            {"key": "D", "label": "杂质D", "std_name": "杂质D"},
            {"key": "other", "label": "其他最大未知杂质", "std_name": "其他最大未知杂质"},
        ],
        "total_std_name": "总杂",
    }
    inputs = {
        "std_c_area_A3": 50000, "std_c_area_A4": 200000,
        "sample_total_1": 260000, "sample_main_A3_1": 10000, "sample_main_A4_1": 240000,
        "sample_total_2": 262000, "sample_main_A3_2": 10100, "sample_main_A4_2": 241000,
        "imp_D_1": 125, "imp_D_2": 100, "imp_other_1": "", "imp_other_2": 50,
    }
    result = calc_engine.compute_impurity_vs_std(cfg, inputs)
    by_name = {i["std_name"]: i for i in result["items"]}
    std_c = 250000
    # 杂质D% = (125/250000×100 + 100/250000×100)/2
    assert abs(by_name["杂质D"]["value"] - (225 / std_c * 100) / 2) < 1e-9
    # 未检出 → 0
    assert by_name["其他最大未知杂质"]["value"] == 50 / std_c * 100 / 2
    # 总杂 = (260000-250000 + 262000-251100)/250000×100/2
    t1 = 260000 - 10000 - 240000
    t2 = 262000 - 10100 - 241000
    assert abs(by_name["总杂"]["value"] - (t1 + t2) / std_c * 100 / 2) < 1e-9


def test_impurity_std_ratio_math():
    cfg = {
        "mode": "impurity_std_ratio", "samples": 2,
        "std_vol": 50, "sample_vol": 50, "std_dilution": 10, "sample_dilution": 5,
        "impurities": [
            {"key": "D", "label": "杂质D", "std_name": "杂质D"},
            {"key": "F", "label": "杂质F", "std_name": "杂质F"},
        ],
        "total_from": ["D", "F"],
        "total_std_name": "总杂质",
    }
    # Cs1 = 12.5/50/10/100×1000 = 0.25 μg/ml；Cu = 25/50/5×1000 = 100 μg/ml；rs1 = 1000000
    inputs = {
        "std1_mass": 12.5,
        "std_area_1": 1000000, "std_area_2": 1002000, "std_area_3": 998000,
        "std_area_4": 1001000, "std_area_5": 999000,
        "sample_mass_1": 25.0, "sample_mass_2": 25.1,
        "imp_D_1": 500, "imp_D_2": 400,
        "imp_F_1": "", "imp_F_2": 300,
    }
    result = calc_engine.compute_impurity_std_ratio(cfg, inputs)
    by_name = {i["std_name"]: i for i in result["items"]}
    rs1 = (1000000 + 1002000 + 998000 + 1001000 + 999000) / 5
    cs1 = 12.5 / 50 / 10 / 100 * 1000
    cu1 = 25.0 / 50 / 5 * 1000
    cu2 = 25.1 / 50 / 5 * 1000
    d1 = cs1 * 500 * 100 / (cu1 * rs1)
    d2 = cs1 * 400 * 100 / (cu2 * rs1)
    assert abs(by_name["杂质D"]["value"] - (d1 + d2) / 2) < 1e-12
    # 未检出 F 第1份=0
    f2 = cs1 * 300 * 100 / (cu2 * rs1)
    assert abs(by_name["杂质F"]["value"] - f2 / 2) < 1e-12
    # 总杂 = D+F 求和
    t1 = cs1 * 500 * 100 / (cu1 * rs1)
    t2 = cs1 * 700 * 100 / (cu2 * rs1)
    assert abs(by_name["总杂质"]["value"] - (t1 + t2) / 2) < 1e-12


def test_std_curve_math():
    import math

    cfg = {
        "mode": "std_curve",
        "dilutions": [20, 10, 5], "volume": 50, "conc_factor": 100 / 6,
        "items": [
            {"key": "max_single", "label": "最大单一杂质", "std_name": "最大单一杂质"},
            {"key": "other", "label": "其他单个杂质", "std_name": "其他单个杂质"},
        ],
    }
    inputs = {
        "std_mass": 10.0,
        "std_area_1": 1000, "std_area_2": 10000, "std_area_3": 50000,
        "imp_max_single_1": 3000,
    }
    result = calc_engine.compute_std_curve(cfg, inputs)
    concs = [10.0 / 50 / (100 / 6) / d * 1000 for d in (20, 10, 5)]
    log_c = [math.log10(c) for c in concs]
    log_a = [math.log10(a) for a in (1000, 10000, 50000)]
    b = calc_engine._slope(log_a, log_c)
    a_int = calc_engine._intercept(log_a, log_c)
    expect = 10 ** (b * math.log10(3000) + a_int)
    item = result["items"][0]
    assert abs(item["value"] - expect) < 1e-9
    assert result["correl"] is not None and result["correl"] > 0.99
    # 未填面积 → 缺数据
    assert result["items"][1]["value"] is None


def test_group_rrf_math():
    cfg = {
        "mode": "group_rrf", "rrf": 0.83,
        "rrf_group": ["S3"],
        "main_std_name": "A2系",
        "items": [
            {"key": "S3", "label": "A3系（S3）", "std_name": "A3系"},
            {"key": "S2_1", "label": "A2-1系", "std_name": "A2-1系"},
        ],
    }
    inputs = {
        "main_total": 900000,  # A2系总峰面积
        "area_S3": 100000,
        "area_S2_1": 100000,
    }
    result = calc_engine.compute_group_rrf(cfg, inputs)
    by_name = {i["std_name"]: i for i in result["items"]}
    denom = 900000 + 0.83 * 100000  # 983000
    # A3系% = 0.83×100000/983000×100
    assert abs(by_name["A3系"]["value"] - 0.83 * 100000 / denom * 100) < 1e-9
    # A2-1系% = 100000/983000×100
    assert abs(by_name["A2-1系"]["value"] - 100000 / denom * 100) < 1e-9
    # 主组 = 900000/983000×100
    assert abs(by_name["A2系"]["value"] - 900000 / denom * 100) < 1e-9
