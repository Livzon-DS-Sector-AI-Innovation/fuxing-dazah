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
