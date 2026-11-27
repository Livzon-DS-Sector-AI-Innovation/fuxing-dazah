"""液相计算表模板「简易维护」：上传文件自动识别同版式 + 一键生成新表号配置。

从 api/_lc.py 收敛的业务逻辑（API 层不写业务）：列偏移搜索、候选打分、
按偏移复制模板配置。
"""

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.lc_template_parser import (
    detect_table_no,
    open_sheet_cached,
    parse_with_config,
)
from app.modules.quality.repository import (
    create_lc_template_config,
    get_lc_template_by_table_no,
    list_lc_template_configs,
)


class TemplateConfigExistsError(Exception):
    """表号已存在配置（HTTP 409）。"""


class TemplateConfigNotFoundError(Exception):
    """模板表号不存在（HTTP 404）。"""


def _shift_col(col: str, delta: int) -> str | None:
    """列字母平移（A+1=B），越界返回 None。"""
    num = 0
    for ch in col.upper():
        if not ch.isalpha():
            return None
        num = num * 26 + (ord(ch) - 64)
    num += delta
    if num < 1 or num > 702:
        return None
    out = ""
    while num:
        num, rem = divmod(num - 1, 26)
        out = chr(65 + rem) + out
    return out


def shifted_config(
    cfg: dict[str, Any], dn: int, dv: int, step: int | None = None,
) -> dict[str, Any]:
    """按列偏移/步长复制配置：blocks 的 name_col 平移 dn、value/fallback 平移 dv、step 可覆盖。"""
    c = copy.deepcopy(cfg)
    for b in c.get("blocks", []) or []:
        if b.get("name_col"):
            b["name_col"] = _shift_col(str(b["name_col"]), dn) or str(b["name_col"])
        if b.get("value_col"):
            b["value_col"] = _shift_col(str(b["value_col"]), dv) or str(b["value_col"])
        if b.get("fallback_col"):
            b["fallback_col"] = _shift_col(str(b["fallback_col"]), dv) or str(b["fallback_col"])
        if step is not None:
            b["step"] = step
    limits = c.get("limits")
    if limits:
        if limits.get("name_col"):
            limits["name_col"] = _shift_col(str(limits["name_col"]), dn) or str(limits["name_col"])
        if limits.get("value_col"):
            limits["value_col"] = _shift_col(str(limits["value_col"]), dv) or str(limits["value_col"])
    return c


# 同家族版式的全量搜索空间：列偏移 × 步长；跨家族仅原版式直试
_SHIFT_COMBOS = [
    (dn, dv, step)
    for dn in (-8, -6, -4, -2, -1, 0, 1, 2)
    for dv in (-4, -2, -1, 0, 1, 2, 4)
    for step in (1, 2, 4)
]


async def auto_detect_templates(db: AsyncSession, data: bytes, filename: str) -> dict[str, Any]:
    """把上传的计算表和库里全部配置逐一「试版式」：能提取出≥3个有效值的即视为同版式候选。

    返回 {table_no, candidates[]}（候选含 name_shift/value_shift/step，生成时需回传）。
    文件无法打开/未识别到表号抛 ValueError。
    """
    get, max_row, max_col = open_sheet_cached(data, filename)
    table_no = detect_table_no(get, max_row, max_col)
    if not table_no:
        raise ValueError("未识别到表号（EX-xx-xxxx-vvv），请确认文件为计算表")
    cfgs = await list_lc_template_configs(db)
    family = table_no[:5] if len(table_no) >= 5 else ""  # 如 EX-TA / EX-HA
    family_cfgs = [c for c in cfgs if family and (c.table_no or "").startswith(family)]
    trial_cfgs = family_cfgs or cfgs
    candidates: list[dict[str, Any]] = []
    for cfg in trial_cfgs:
        same_family = bool(family_cfgs) and cfg in family_cfgs
        combos = _SHIFT_COMBOS if same_family else [(0, 0, None)]
        best: tuple[tuple[int, int], int, int, int | None, Any] | None = None
        for dn, dv, step in combos:
            try:
                parsed = parse_with_config(
                    data, filename,
                    shifted_config(cfg.config or {}, dn, dv, step), table_no,
                    get=get, max_row=max_row, max_col=max_col,
                )
            except Exception:  # noqa: BLE001 — 版式不符直接跳过
                continue
            value_n = len([c for c in parsed.components if c.report_value is not None])
            # 有值候选永远优先（rank=1）；空白模板（公式未填值）按标签行数匹配版式（rank=0）
            if value_n >= 3:
                rank = (1, value_n)
            elif len(parsed.components) >= 10:
                rank = (0, len(parsed.components))
            else:
                continue
            if best is None or rank > best[0]:
                best = (rank, dn, dv, step, parsed)
        if best is None:
            continue
        _rank, dn, dv, step, parsed = best
        values = [c for c in parsed.components if c.report_value is not None]
        candidates.append({
            "template_table_no": cfg.table_no,
            "product_name": cfg.product_name or "",
            "description": cfg.description or "",
            "component_count": len(parsed.components),
            "value_count": len(values),
            "blank": len(values) == 0,
            "name_shift": dn,
            "value_shift": dv,
            "step": step,
            "samples": [
                {"name": c.name, "value": c.report_value}
                for c in (values or parsed.components)[:8]
            ],
        })
    candidates.sort(key=lambda x: (x["blank"], -x["value_count"]))
    return {"table_no": table_no, "candidates": candidates}


async def auto_create_from_template(
    db: AsyncSession,
    *,
    table_no: str,
    template_no: str,
    name_shift: int = 0,
    value_shift: int = 0,
    step: int | None = None,
) -> dict[str, Any]:
    """复制模板配置生成新表号配置（不改 JSON）；表号已存在抛 TemplateConfigExistsError。"""
    if not table_no or not template_no:
        raise ValueError("缺少表号/模板表号")
    if await get_lc_template_by_table_no(db, table_no):
        raise TemplateConfigExistsError(f"表号 {table_no} 已存在配置（可先删除旧配置或联系管理员）")
    template = await get_lc_template_by_table_no(db, template_no)
    if not template:
        raise TemplateConfigNotFoundError(f"模板表号 {template_no} 不存在")
    if name_shift or value_shift or step:
        config = shifted_config(
            template.config or {}, name_shift, value_shift,
            int(step) if step else None,
        )
    else:
        config = template.config or {}
    shift_note = (
        f"，标签列偏移 {name_shift:+d}/值列偏移 {value_shift:+d}"
        if (name_shift or value_shift) else ""
    )
    cfg = await create_lc_template_config(
        db, table_no=table_no, product_name=template.product_name,
        sop_no=template.sop_no,
        description=f"自动生成（版式同 {template_no}{shift_note}，请用「测试计算」验证后启用）",
        config=config,
    )
    return {"id": str(cfg.id), "table_no": cfg.table_no}
