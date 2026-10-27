"""色谱计算引擎：归一化法（含量/有关物质）与外标法（残留溶剂 ppm）。

由表号配置的 config.calc 驱动，把计算表 Excel 里的公式搬到系统内：
- normalization：含量% = RRF×主峰面积/(RRF×主峰面积+杂质总峰面积)×100；
  杂质% = 杂质峰面积/(RRF×主峰面积+杂质总峰面积)×100（面积空/0 = 未检出，按 0% 计）；
  双份取平均；总杂质 = 各杂质%之和。
- external_std：残留溶剂 ppm = 样面积×对照质量×含量P×稀释倍数
  /(对照平均面积×样品质量×对照稀释体积)×1e6；对照 5 针平均+RSD 校验。

纯函数模块，不访问数据库；输入输出均为普通 dict/list。
"""

import math
from typing import Any


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rsd(values: list[float]) -> float | None:
    """相对标准偏差（%）。不足 2 个有效值返回 None。"""
    if len(values) < 2 or not sum(values):
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var) / mean * 100


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        f: float = float(v)
    except (TypeError, ValueError):
        return default
    return f if f > 0 else default


def compute_normalization(cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """归一化法计算。

    inputs 键约定：total_peak_1/2（总峰面积）、main_peak_1/2（主峰面积）、
    <impurity key>_1/2（各杂质峰面积，空/0 视为未检出=0%）。
    返回 items：[{std_name, label, value, nd, detail}]，value 为双份平均（%）。
    """
    rrf = float(cfg.get("rrf") or 1)
    samples = int(cfg.get("samples") or 2)
    main_item: dict[str, Any] = cfg["main_item"]
    impurities: list[dict[str, Any]] = cfg.get("impurities") or []

    def _area(v: Any) -> float:
        """杂质峰面积：空/0/非数 = 未检出（0）。"""
        f = _num(v)
        return f if f is not None else 0.0

    at: list[float | None] = []
    denom: list[float | None] = []
    for i in range(1, samples + 1):
        tp = _num(inputs.get(f"total_peak_{i}"))
        mp = _num(inputs.get(f"main_peak_{i}"))
        if tp is None or mp is None:
            at.append(None)
            denom.append(None)
            continue
        at_i = tp - mp
        at_val = at_i if at_i > 0 else 0.0
        at.append(at_val)
        denom.append(rrf * mp + at_val)

    items: list[dict[str, Any]] = []

    def _item(std_name: str, label: str, vals: list[float | None], nd: bool) -> dict[str, Any]:
        present = [v for v in vals if v is not None]
        avg = sum(present) / len(present) if present else None
        detail = " / ".join(
            f"第{i}份 {v:.4g}%{'（未检出）' if nd else ''}" if v is not None else f"第{i}份 缺数据"
            for i, v in enumerate(vals, start=1)
        )
        return {"std_name": std_name, "label": label, "value": avg, "nd": nd, "detail": detail}

    def _main_pct(i: int) -> float | None:
        mp = _num(inputs.get(f"main_peak_{i}"))
        d = denom[i - 1]
        if mp is None or d is None or d == 0:
            return None
        return rrf * mp / d * 100

    def _imp_pct(key: str, i: int) -> float | None:
        d = denom[i - 1]
        if d is None or d == 0:
            return None
        return _area(inputs.get(f"{key}_{i}")) / d * 100

    # 主成分（如 万古霉素B）
    main_pct = [_main_pct(i) for i in range(1, samples + 1)]
    items.append(_item(main_item["std_name"], main_item["label"], main_pct, False))

    # 各杂质：面积 0/空 = 未检出（0%）
    for imp in impurities:
        key = str(imp["key"])
        areas = [_area(inputs.get(f"{key}_{i}")) for i in range(1, samples + 1)]
        vals = [_imp_pct(key, i) for i in range(1, samples + 1)]
        items.append(_item(imp["std_name"], imp["label"], vals, nd=all(a == 0 for a in areas)))

    # 总杂质 = 各杂质%之和（不含主成分），双份平均
    tot: list[float | None] = []
    for i in range(1, samples + 1):
        d = denom[i - 1]
        if d is None or d == 0:
            tot.append(None)
            continue
        tot.append(sum(_area(inputs.get(f"{imp['key']}_{i}")) for imp in impurities) / d * 100)
    items.append(_item(cfg.get("total_std_name") or "总杂质", "总杂质", tot, False))

    return {"mode": "normalization", "items": items, "denom": denom, "at": at}


def compute_external_std(cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """外标法计算（残留溶剂 ppm）。

    inputs 键约定：<key>_std_mass（对照质量 mg）、<key>_std_area_1..6（对照峰面积）、
    <key>_std_vol（对照稀释体积）、<key>_std_purity（对照含量P，缺省 1）、
    <key>_sample_mass_1/2（样品质量 mg）、<key>_sample_area_1/2（样品峰面积）。
    返回 items：[{std_name, label, value(ppm 双份平均), detail, std_rsd, std_avg}]。
    """
    factor = float(cfg.get("dilution_factor") or 1)
    scale = float(cfg.get("ppm_scale") or 1e6)
    samples = int(cfg.get("samples") or 2)

    items: list[dict[str, Any]] = []
    for solvent in cfg.get("solvents") or []:
        key = str(solvent["key"])
        std_mass = _num(inputs.get(f"{key}_std_mass"))
        std_areas = [_num(inputs.get(f"{key}_std_area_{i}")) for i in range(1, 7)]
        std_present = [a for a in std_areas if a is not None]
        std_avg = sum(std_present) / len(std_present) if std_present else None
        std_rsd = _rsd(std_present)
        std_vol = _num(inputs.get(f"{key}_std_vol"))
        purity = _num(inputs.get(f"{key}_std_purity")) or 1.0
        ppm_vals: list[float | None] = []
        for i in range(1, samples + 1):
            s_area = _num(inputs.get(f"{key}_sample_area_{i}"))
            s_mass = _num(inputs.get(f"{key}_sample_mass_{i}"))
            if s_area is None or s_mass is None or std_mass is None or std_avg is None or std_vol is None:
                ppm_vals.append(None)
                continue
            ppm_vals.append(s_area * std_mass * purity * factor / (std_avg * s_mass * std_vol) * scale)
        present_ppm = [v for v in ppm_vals if v is not None]
        avg_ppm = sum(present_ppm) / len(present_ppm) if present_ppm else None
        detail = " / ".join(
            f"第{i}份 {v:.0f}ppm" if v is not None else f"第{i}份 缺数据"
            for i, v in enumerate(ppm_vals, start=1)
        )
        items.append({
            "std_name": solvent["std_name"],
            "label": solvent["label"],
            "value": avg_ppm,
            "detail": detail,
            "std_avg": std_avg,
            "std_rsd": round(std_rsd, 2) if std_rsd is not None else None,
        })
    return {"mode": "external_std", "items": items}


def compute_external_std_content(cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """外标法含量计算（对照品 + 水分折算，照达托霉素含量表公式）。

    含量% = 标准1质量 × 标准品含量 × 供试品面积 / 供试品质量
            / 标准1平均面积 / (1 - 水分%/100) × 100
    inputs 键约定：std1_mass（标准1质量 mg）、std_content（标准品含量，分数如 0.955）、
    std_area_1..6（标准1峰面积，含回针可选）、sample_area_1..N / sample_mass_1..N（供试品，N=cfg.samples）、
    moisture（水分%，如 0.5 表示 0.5%，缺省 0）。
    """
    samples = int(cfg.get("samples") or 3)
    std_mass = _num(inputs.get("std1_mass"))
    std_content = _num(inputs.get("std_content")) or 1.0
    std_areas = [_num(inputs.get(f"std_area_{i}")) for i in range(1, 7)]
    std_present = [a for a in std_areas if a is not None]
    std_avg = sum(std_present) / len(std_present) if std_present else None
    std_rsd = _rsd(std_present)
    moisture = _num(inputs.get("moisture")) or 0.0
    content_vals: list[float | None] = []
    for i in range(1, samples + 1):
        s_area = _num(inputs.get(f"sample_area_{i}"))
        s_mass = _num(inputs.get(f"sample_mass_{i}"))
        if s_area is None or s_mass is None or std_mass is None or std_avg is None:
            content_vals.append(None)
            continue
        content_vals.append(
            std_mass * std_content * s_area / s_mass / std_avg / (1 - moisture / 100) * 100
        )
    present = [v for v in content_vals if v is not None]
    avg = sum(present) / len(present) if present else None
    detail = " / ".join(
        f"样{i} {v:.2f}%" if v is not None else f"样{i} 缺数据"
        for i, v in enumerate(content_vals, start=1)
    )
    return {
        "mode": "external_std_content",
        "items": [{
            "std_name": cfg.get("main_std_name") or "含量",
            "label": "含量",
            "value": avg,
            "detail": detail,
            "std_avg": std_avg,
            "std_rsd": round(std_rsd, 2) if std_rsd is not None else None,
        }],
    }


def compute_content_multi(cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """外标法含量·多组分（照米尔贝肟含量表公式，输出百分数）。

    组分含量% = 标准1质量 × 组分含量 × 样面积 / 样质量
              / 标准1该组分平均面积 / (1 - 水分%/100) × 100
    总含量% = Σ组分含量%；标准1 峰面积 5 针 + 回针可选（回针仅计入 RSD 校验口径）。
    inputs 键约定：std1_mass、std_content_<comp>、std_area_<comp>_1..6、
    sample_mass_1..N、sample_area_<comp>_1..N、moisture。
    """
    samples = int(cfg.get("samples") or 3)
    components: list[dict[str, Any]] = cfg.get("components") or []
    std_mass = _num(inputs.get("std1_mass"))
    moisture = _num(inputs.get("moisture")) or 0.0
    items: list[dict[str, Any]] = []
    for comp in components:
        key = str(comp["key"])
        std_content = _num(inputs.get(f"std_content_{key}"))
        std_areas = [_num(inputs.get(f"std_area_{key}_{i}")) for i in range(1, 7)]
        std_present = [a for a in std_areas if a is not None]
        std_avg = sum(std_present) / len(std_present) if std_present else None
        std_rsd = _rsd(std_present)
        vals: list[float | None] = []
        for i in range(1, samples + 1):
            s_area = _num(inputs.get(f"sample_area_{key}_{i}"))
            s_mass = _num(inputs.get(f"sample_mass_{i}"))
            if s_area is None or s_mass is None or std_mass is None or std_content is None or std_avg is None:
                vals.append(None)
                continue
            vals.append(
                std_mass * std_content * s_area / s_mass / std_avg / (1 - moisture / 100) * 100
            )
        present = [v for v in vals if v is not None]
        avg = sum(present) / len(present) if present else None
        detail = " / ".join(
            f"样{i} {v:.2f}%" if v is not None else f"样{i} 缺数据"
            for i, v in enumerate(vals, start=1)
        )
        items.append({
            "std_name": comp["std_name"],
            "label": comp["label"],
            "value": avg,
            "detail": detail,
            "std_avg": std_avg,
            "std_rsd": round(std_rsd, 2) if std_rsd is not None else None,
        })
    # 总含量 = Σ组分（按样品维度从原始输入聚合）
    total_by_sample: list[float | None] = []
    for i in range(1, samples + 1):
        s = 0.0
        ok = True
        for comp in components:
            key = str(comp["key"])
            s_area = _num(inputs.get(f"sample_area_{key}_{i}"))
            s_mass = _num(inputs.get(f"sample_mass_{i}"))
            std_content = _num(inputs.get(f"std_content_{key}"))
            std_area_vals = [_num(inputs.get(f"std_area_{key}_{j}")) for j in range(1, 7)]
            std_present2: list[float] = [a for a in std_area_vals if a is not None]
            std_avg = sum(std_present2) / len(std_present2) if std_present2 else None
            if s_area is None or s_mass is None or std_content is None or std_avg is None or std_mass is None:
                ok = False
                break
            s += std_mass * std_content * s_area / s_mass / std_avg / (1 - moisture / 100) * 100
        total_by_sample.append(s if ok else None)
    present_t = [v for v in total_by_sample if v is not None]
    items.append({
        "std_name": cfg.get("total_std_name") or "总含量",
        "label": "总含量",
        "value": sum(present_t) / len(present_t) if present_t else None,
        "detail": " / ".join(
            f"样{i} {v:.2f}%" if v is not None else f"样{i} 缺数据"
            for i, v in enumerate(total_by_sample, start=1)
        ),
        "nd": False,
    })
    return {"mode": "external_std_content_multi", "items": items}


def compute_impurity_vs_std(cfg: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """有关物质·对标准溶液归一（照米尔贝肟有关物质公式，输出百分数）。

    杂质% = 杂质峰面积 / 标准溶液c总面积 × 100；
    总杂% = (供试品总峰面积 - Σ主组分面积) / 标准溶液c总面积 × 100。
    inputs 键约定：std_c_area_<comp>（标准溶液c 各主组分峰面积）、
    sample_total_1/2、sample_main_<comp>_1/2、imp_<key>_1/2（杂质面积，空/0=未检出）。
    """
    samples = int(cfg.get("samples") or 2)
    components: list[dict[str, Any]] = cfg.get("components") or []
    impurities: list[dict[str, Any]] = cfg.get("impurities") or []

    def _area(v: Any) -> float:
        f = _num(v)
        return f if f is not None else 0.0

    std_factor = float(cfg.get("std_factor") or 1)
    std_c = sum(_area(inputs.get(f"std_c_area_{c['key']}")) for c in components) * std_factor
    if std_c <= 0:
        return {"mode": "impurity_vs_std", "items": [], "error": "标准溶液c面积未填写"}

    items: list[dict[str, Any]] = []
    for imp in impurities:
        key = str(imp["key"])
        vals: list[float] = []
        for i in range(1, samples + 1):
            vals.append(_area(inputs.get(f"imp_{key}_{i}")) / std_c * 100)
        avg = sum(vals) / len(vals)
        nd = all(v == 0 for v in vals)
        detail = " / ".join(
            f"第{i}份 {v:.4g}%{'（未检出）' if nd else ''}"
            for i, v in enumerate(vals, start=1)
        )
        items.append({"std_name": imp["std_name"], "label": imp["label"], "value": avg, "nd": nd, "detail": detail})
    # 总杂：总峰面积 - 主组分面积
    tot_vals: list[float] = []
    for i in range(1, samples + 1):
        total = _area(inputs.get(f"sample_total_{i}"))
        mains = sum(_area(inputs.get(f"sample_main_{c['key']}_{i}")) for c in components)
        tot_vals.append(max(total - mains, 0.0) / std_c * 100)
    avg_t = sum(tot_vals) / len(tot_vals)
    items.append({
        "std_name": cfg.get("total_std_name") or "总杂",
        "label": "总杂",
        "value": avg_t,
        "nd": all(v == 0 for v in tot_vals),
        "detail": " / ".join(f"第{i}份 {v:.4g}%" for i, v in enumerate(tot_vals, start=1)),
    })
    return {"mode": "impurity_vs_std", "items": items}
