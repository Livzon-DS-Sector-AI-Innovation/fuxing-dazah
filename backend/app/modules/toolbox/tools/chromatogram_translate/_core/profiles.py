"""版式模板参数：全部检测阈值与词汇表集中于此，支持未来注册其他报告模板族。

数值来源：达托霉素专属性（13 页 HPLC）+ 图谱（46 个荧光报告）两批真实文件
调参得到的经验值，改动前先跑 tests 的真实样本回归。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    # ── 图区检测（长横线对）──
    chart_pair_gap: tuple[float, float] = (100.0, 220.0)  # 上下框间距范围
    chart_x0_min: float = 60.0  # 绘图框 x 起点（页眉线从 35 起被排除）
    chart_width: tuple[float, float] = (380.0, 500.0)  # 绘图框宽度范围
    # ── 表区检测（横线组）──
    table_line_min_w: float = 150.0  # 行线最小宽度（窄表 305pt 宽也要命中）
    wide_line_min_w: float = 350.0  # 图区配对只认宽线
    table_group_gap: float = 60.0  # 行线间距超过此值视为不同表区
    table_min_height: float = 25.0  # 表区最小高度（过滤页眉线对）
    vline_dedup: float = 2.0  # 列边界竖线去重容差
    # ── 信息区/页脚聚簇 ──
    cluster_gap: float = 78.0  # 标签→值列间隙(42-66)与字段→字段间隙(94+)的分界
    label_gap: float = 8.0  # 遇新标签 span 时，超过此间隙即断簇
    right_margin: float = 36.0  # 聚簇右边界 = 页宽 - 此值
    vline_right_gap: float = 5.0  # 行右侧竖线再内收，防撞框线
    alone_width_factor: float = 3.2  # 单 span 标题允许的最大放宽倍数
    # ── 字号适配 ──
    fs_floor: float = 6.3  # 表格单元格字号下限
    header_split_min: float = 6.8  # 表头低于此字号触发两行拆分/缩写梯
    info_fs_floor: float = 6.8  # 信息区字号下限
    info_abbr_below: float = 9.0  # 信息区低于此字号触发缩写梯
    baseline_ratio: float = 0.8  # 基线 = y0 + ratio * 字号
    # ── 名称列（峰结果表第一数据列）──
    name_fs_floor: float = 6.0
    name_fs_cap: float = 10.0
    # ── 色谱图竖排标注 ──
    chart_label_width: float = 10.5  # 图内标注列的最大宽度（更宽的是普通文字）
    chart_col_tol: float = 1.6  # 同列 span 的 x0 容差
    chart_neighbor_cap: float = 7.0  # 邻列中心距小于此值时按净距限字号
    chart_fs_cap: float = 7.9  # 竖排标注字号上限（取源标注字号）
    chart_fs_floor: float = 5.5
    # ── 词汇 ──
    header_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "名称",
                "保留时间",
                "面积",
                "理论塔板数",
                "高度",
                "拖尾因子",
                "分离度",
                "分钟",
                "微伏",
                "秒",
                "拖尾因子分离度",
                "分离度拖尾因子",
                "微伏秒",
            }
        )
    )
    abbrev: dict[str, str] = field(
        default_factory=lambda: {
            "Theoretical Plates": "Plates",
            "Tailing Factor": "Tailing",
            "Retention Time": "RT",
            "Resolution": "Rs",
        }
    )
    info_abbrev: tuple[tuple[str, str], ...] = (
        ("Acquisition Method Set:", "Method Set:"),
        ("Processing Channel Comment:", "Channel Comment:"),
    )


EMPOWER_CN = Profile(key="empower-cn", name="Waters Empower 中文报告")
