"""location_district_map 初灌 seed 数据（人工同义词 + 由资产生成原文行）。

- SEED_SYNONYMS：人工维护的 分区名→同义词 清单（distName 为键，同义词列表为值）；
  键必须与资产 distName 原文一致，否则该组同义词整体跳过（防错别字灌错分区）。
- seed_rows_from_asset()：资产 doc → 灌表行（64 分区名原文 + 同义词，按
  location_text 去重，全部 source='manual'）。seed 脚本据此以
  ON CONFLICT DO NOTHING 幂等写入，重跑不重复、不覆盖既有行。
"""

from __future__ import annotations

from typing import Any

__all__ = ["SEED_SYNONYMS", "seed_rows_from_asset"]

# 人工同义词（2026-10-26 首灌；来源见注释，后续随未映射摸底逐步补充）
SEED_SYNONYMS: dict[str, list[str]] = {
    # 消防报警楼栋实测值（building=原料库）
    "原辅料库": ["原料库"],
    # 常见简称/易写法（票面与报警部位实测口径）
    "消防控制室": ["消控室"],
    "危化品库": ["危化品仓库", "危化库"],
    "成品包材库": ["包材库"],
    "提炼技术精进中心": ["精进中心"],
    # 环保RTO：票面实测「发酵背后RTO主体」含 RTO
    "环保RTO": ["RTO"],
    # 动力车间/综合泵房是空冷班组分区内的 rail 轮廓（资产几何实证），
    # 票面以建筑名指位时归入所属分区
    "空冷班组": ["动力车间", "综合泵房"],
    # 中控报警车间+产线写法（2026-10-26 实测 unmapped 高频文本）：
    # 分区名是「…新线」而中控写「车间二达托/达巴」短形
    "车间二达托新线": ["车间二达托"],
    "车间二达巴新线": ["车间二达巴"],
    # 替考线：中控写「车间二替考（精烘包）」
    "替考线": ["车间二替考"],
    # 提四溶剂回收区：中控车间名短形（酒精=乙醇）
    "提四乙腈回收": ["乙腈回收"],
    "提四异丙醇回收": ["异丙醇回收"],
    "提四丙醇回收": ["丙醇回收"],
    "提四乙醇回收": ["乙醇回收", "酒精回收"],
    # 提四药名产线：中控写「车间X+药名」（药名全厂唯一，短词供包含命中）
    "提四莫西": ["莫西", "车间二莫西"],
    "提四雷帕": ["雷帕", "车间一雷帕"],
    # 2026-10-27 未映射清单补充（名称/工艺确定性映射）
    # 提炼技术中心=提炼技术精进中心少写「精进」二字（票面实测）
    "提炼技术精进中心": ["精进中心", "提炼技术中心"],
    # 小喷=小喷喷雾线简称（全厂唯一，「小喷一楼冻干机房」包含命中）
    "小喷喷雾": ["小喷"],
    # 气浮池是污水处理工艺单元，全厂仅环保水处理分区（票面「环保A/C池气浮」）
    "环保水处理": ["A池气浮", "C池气浮"],
    # 2026-10-27 用户拍板：塞拉产线在米尔贝车间（车间四（甲类）厂房，
    # 资产 rail 轮廓实证）；「塞拉」全厂唯一短词兜「塞拉线/塞拉车间」变体
    "米尔贝": ["车间四塞拉", "塞拉"],
    # 2026-10-27 本地补建罐区分区（9001，用户圈选位置）：中控「新罐区」
    # 与「旧罐区」均指该罐区（新=主区 136 次/30 天，旧=2 次，如归属有误
    # 改映射表即可）
    "罐区": ["新罐区", "旧罐区"],
}


def seed_rows_from_asset(
    asset_doc: dict[str, Any],
    *,
    synonyms: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """资产 doc（或 normalize_districts 结果）→ seed 行列表。

    行：{location_text, dist_id, source='manual'}；64 分区名原文全量 +
    人工同义词；同义词键不在资产分区名集合时整组跳过；按 location_text
    去重（原文优先于同义词）。
    """
    syn = synonyms if synonyms is not None else SEED_SYNONYMS
    districts = asset_doc.get("districts") or asset_doc
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    by_name: dict[str, str] = {}
    for district in districts:
        name = str(district.get("distName") or "").strip()
        dist_id = str(district.get("distId") or "")
        if not name or not dist_id or name in seen:
            continue
        seen.add(name)
        by_name[name] = dist_id
        rows.append({"location_text": name, "dist_id": dist_id, "source": "manual"})
    for name, aliases in syn.items():
        dist_id = by_name.get(str(name).strip())
        if dist_id is None:
            continue
        for alias in aliases:
            text = str(alias).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            rows.append({"location_text": text, "dist_id": dist_id, "source": "manual"})
    return rows
