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
