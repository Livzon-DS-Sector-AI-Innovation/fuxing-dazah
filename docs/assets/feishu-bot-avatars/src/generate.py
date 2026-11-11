# -*- coding: utf-8 -*-
"""飞书机器人头像生成器 —— 「机器人助手」系列。

同一副机器人底盘（白色软壳 + 深蓝面屏 + 左右彩色耳罩），用角色道具区分业务：
  · 安全助手：黄色安全帽 + 胸前盾牌（蓝色系背景）
  · 仓储助手：橙色天线 + 手捧纸箱（暖橙系背景）

用法（需要 cairosvg；macOS / Linux 均可无头运行）：
    python3 -m venv .venv && .venv/bin/pip install cairosvg
    .venv/bin/python generate.py

输出：
    src/*.svg                 矢量源文件（512 画布）
    png/*-{1024,512,240,128,96,48}.png
    png/transparent/*-transparent-1024.png
"""

from __future__ import annotations

import os
from pathlib import Path

import cairosvg

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent          # .../feishu-bot-avatars/src
ASSET_DIR = HERE.parent                         # .../feishu-bot-avatars
PNG_DIR = ASSET_DIR / "png"
TRANSPARENT_DIR = PNG_DIR / "transparent"

CANVAS = 512          # 母版画布边长（1:1，飞书圆形裁切）
NAVY = "#0E1B31"      # 面屏 / 剪影用的品牌深蓝

SIZES = (1024, 512, 240, 128, 96, 48)   # 1024 = 上传/印刷用大图，512 = 飞书推荐
EXPORT_SIZE = 1024                       # 透明底导出尺寸

# 每个机器人 = 同一套底盘 + 一组调色板 + 一个道具
BOTS = {
    "safety": {
        "name_cn": "安全助手",
        "tagline": "安全模块 · 隐患 / 检查 / 培训 / 知识问答",
        "bg1": "#C9DEF8", "bg2": "#92B9EA",          # 冷蓝：安全、巡查
        "accent": "#FFC53D",                          # 安全帽黄
        "accent_light": "#FFDC80",
        "accent_dark": "#DE9A0D",
    },
    "warehouse": {
        "name_cn": "仓储助手",
        "tagline": "仓储模块 · 入库 / 出库 / 领料 / 盘点",
        "bg1": "#FFDFC2", "bg2": "#EFA96E",          # 暖橙：纸箱、库房
        "accent": "#F58C3C",
        "accent_light": "#FFB067",
        "accent_dark": "#B9571A",
        "box_body": "#C8813F",
        "box_lid": "#A95F29",
        "box_tape": "#F4E3CA",
    },
}


# ---------------------------------------------------------------------------
# SVG 片段
# ---------------------------------------------------------------------------

def svg_defs(b: dict) -> str:
    """渐变定义。全部使用纯 SVG 形状/渐变，不依赖滤镜，保证 cairosvg 无损渲染。"""
    return f'''
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.8" y2="1">
      <stop offset="0" stop-color="{b['bg1']}"/><stop offset="1" stop-color="{b['bg2']}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.6"/>
      <stop offset="0.55" stop-color="#FFFFFF" stop-opacity="0.16"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="shell" x1="0.1" y1="0" x2="0.85" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/><stop offset="0.6" stop-color="#F4F9FF"/><stop offset="1" stop-color="#DCE7F4"/>
    </linearGradient>
    <linearGradient id="shellshade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0.55" stop-color="{NAVY}" stop-opacity="0"/><stop offset="1" stop-color="{NAVY}" stop-opacity="0.10"/>
    </linearGradient>
    <linearGradient id="bodyg" x1="0.15" y1="0" x2="0.8" y2="1">
      <stop offset="0" stop-color="#F8FBFF"/><stop offset="1" stop-color="#CBD9EB"/>
    </linearGradient>
    <linearGradient id="armg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#EEF5FD"/><stop offset="1" stop-color="#D3E0EF"/>
    </linearGradient>
    <linearGradient id="visor" x1="0.15" y1="0" x2="0.85" y2="1">
      <stop offset="0" stop-color="#0A1526"/><stop offset="1" stop-color="#22395C"/>
    </linearGradient>
    <radialGradient id="eyeg" cx="0.36" cy="0.3" r="0.85">
      <stop offset="0" stop-color="#FFFFFF"/><stop offset="0.5" stop-color="#E9F8FF"/><stop offset="1" stop-color="#86D0FF"/>
    </radialGradient>
    <linearGradient id="acc" x1="0.15" y1="0" x2="0.85" y2="1">
      <stop offset="0" stop-color="{b['accent_light']}"/><stop offset="1" stop-color="{b['accent']}"/>
    </linearGradient>
    <linearGradient id="accdeep" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{b['accent']}"/><stop offset="1" stop-color="{b['accent_dark']}"/>
    </linearGradient>
    <radialGradient id="propshadow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{NAVY}" stop-opacity="0.20"/><stop offset="1" stop-color="{NAVY}" stop-opacity="0"/>
    </radialGradient>
  </defs>'''


def svg_backdrop() -> str:
    """满幅背景：斜向渐变 + 中心柔光 + 一枚极淡的同心圆环（家族统一元素）。"""
    return f'''
  <rect width="512" height="512" fill="url(#bg)"/>
  <circle cx="256" cy="200" r="216" fill="url(#glow)"/>
  <circle cx="256" cy="250" r="190" fill="none" stroke="#FFFFFF" stroke-opacity="0.15" stroke-width="16"/>'''


def svg_chassis(b: dict) -> str:
    """两个机器人共用的底盘：肩、颈、手臂、头、耳罩、面屏、眼睛、微笑。"""
    return f'''
  <!-- 肩/上身 -->
  <rect x="140" y="342" width="232" height="120" rx="48" fill="url(#bodyg)"/>
  <rect x="140" y="342" width="232" height="120" rx="48" fill="url(#shellshade)" opacity="0.55"/>
  <!-- 颈 -->
  <rect x="214" y="312" width="84" height="46" rx="14" fill="#DCE7F3"/>
  <rect x="214" y="334" width="84" height="14" fill="#C4D3E4" opacity="0.9"/>
  <!-- 手臂：从肩内侧伸向道具，末端被道具遮住，形成“捧着”的姿势 -->
  <path d="M 166 362 L 206 394" stroke="url(#armg)" stroke-width="38" stroke-linecap="round"/>
  <path d="M 346 362 L 306 394" stroke="url(#armg)" stroke-width="38" stroke-linecap="round"/>
  <!-- 头 -->
  <rect x="124" y="104" width="264" height="226" rx="80" fill="url(#shell)"/>
  <rect x="124" y="104" width="264" height="226" rx="80" fill="url(#shellshade)" opacity="0.7"/>
  <!-- 左右耳罩 -->
  <circle cx="104" cy="216" r="31" fill="url(#acc)"/>
  <circle cx="104" cy="216" r="31" fill="none" stroke="#FFFFFF" stroke-opacity="0.22" stroke-width="3"/>
  <circle cx="104" cy="216" r="12" fill="{b['accent_dark']}"/>
  <circle cx="104" cy="208" r="6.5" fill="#FFFFFF" opacity="0.32"/>
  <circle cx="408" cy="216" r="31" fill="url(#acc)"/>
  <circle cx="408" cy="216" r="31" fill="none" stroke="#FFFFFF" stroke-opacity="0.22" stroke-width="3"/>
  <circle cx="408" cy="216" r="12" fill="{b['accent_dark']}"/>
  <circle cx="408" cy="208" r="6.5" fill="#FFFFFF" opacity="0.32"/>
  <!-- 下巴投影 -->
  <ellipse cx="256" cy="344" rx="92" ry="16" fill="{NAVY}" opacity="0.10"/>
  <!-- 面屏 -->
  <rect x="168" y="152" width="176" height="132" rx="42" fill="url(#visor)"/>
  <rect x="178" y="160" width="156" height="24" rx="12" fill="#FFFFFF" opacity="0.06"/>
  <path d="M 168 152 L 262 152 L 196 284 L 168 284 Z" fill="#FFFFFF" opacity="0.035"/>
  <rect x="168" y="152" width="176" height="132" rx="42" fill="none" stroke="#3E5C82" stroke-opacity="0.35" stroke-width="3"/>
  <!-- 眼睛（发光圆眼 + 高光） -->
  <circle cx="212" cy="214" r="27" fill="url(#eyeg)"/>
  <circle cx="300" cy="214" r="27" fill="url(#eyeg)"/>
  <circle cx="203" cy="203" r="6.5" fill="#FFFFFF" opacity="0.95"/>
  <circle cx="291" cy="203" r="6.5" fill="#FFFFFF" opacity="0.95"/>
  <!-- 微笑 -->
  <path d="M 240 256 Q 256 268 272 256" fill="none" stroke="#63B9EC" stroke-width="8" stroke-linecap="round"/>'''


def svg_safety_prop(b: dict) -> str:
    """安全助手道具：黄色安全帽（六点式帽壳 + 帽檐 + 中脊 + 顶扣）+ 胸前盾牌。"""
    return f'''
  <!-- 安全帽 -->
  <path d="M 142 150 C 140 92 190 62 256 62 C 322 62 372 92 370 150 Z" fill="url(#acc)"/>
  <path d="M 244 68 L 268 68 L 268 150 L 244 150 Z" fill="{b['accent_light']}" opacity="0.5"/>
  <path d="M 176 150 C 172 104 204 78 256 78" fill="none" stroke="#FFFFFF" stroke-opacity="0.22" stroke-width="7" stroke-linecap="round"/>
  <rect x="118" y="146" width="276" height="30" rx="15" fill="url(#accdeep)"/>
  <rect x="118" y="146" width="276" height="11" rx="5.5" fill="#FFFFFF" opacity="0.30"/>
  <circle cx="256" cy="66" r="12" fill="{b['accent_light']}"/>
  <rect x="152" y="168" width="208" height="8" rx="4" fill="{NAVY}" opacity="0.12"/>
  <!-- 道具投影 -->
  <ellipse cx="256" cy="440" rx="110" ry="46" fill="url(#propshadow)"/>
  <!-- 盾牌（安全标识） -->
  <path d="M 197 352 L 315 352 L 315 402 Q 315 446 256 464 Q 197 446 197 402 Z" fill="{b['accent_dark']}"/>
  <path d="M 207 361 L 305 361 L 305 402 Q 305 438 256 454 Q 207 438 207 402 Z" fill="url(#acc)"/>
  <path d="M 207 361 L 305 361 L 305 402 Q 305 438 256 454 Q 207 438 207 402 Z" fill="none" stroke="#FFFFFF" stroke-opacity="0.5" stroke-width="4"/>
  <path d="M 231 405 L 249 423 L 287 383" fill="none" stroke="#FFFFFF" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>'''


def svg_warehouse_prop(b: dict) -> str:
    """仓储助手道具：橙色信号天线 + 手捧的封箱胶带纸箱（含面单条码）。"""
    return f'''
  <!-- 天线 -->
  <rect x="247" y="62" width="18" height="52" rx="9" fill="#DCE7F3"/>
  <rect x="243" y="102" width="26" height="12" rx="6" fill="#C4D3E4"/>
  <circle cx="256" cy="54" r="19" fill="url(#acc)"/>
  <circle cx="249" cy="47" r="6" fill="#FFFFFF" opacity="0.85"/>
  <!-- 道具投影 -->
  <ellipse cx="256" cy="440" rx="120" ry="46" fill="url(#propshadow)"/>
  <!-- 纸箱 -->
  <rect x="163" y="348" width="186" height="114" rx="13" fill="{b['box_body']}"/>
  <path d="M 163 361 Q 163 348 176 348 L 336 348 Q 349 348 349 361 L 349 378 L 163 378 Z" fill="{b['box_lid']}"/>
  <rect x="243" y="348" width="26" height="114" fill="{b['box_tape']}"/>
  <rect x="243" y="348" width="8" height="114" fill="#FFFFFF" opacity="0.30"/>
  <rect x="184" y="392" width="52" height="38" rx="4" fill="#FFF7EA"/>
  <rect x="197" y="400" width="3" height="22" fill="{NAVY}" opacity="0.7"/>
  <rect x="203" y="400" width="2" height="22" fill="{NAVY}" opacity="0.7"/>
  <rect x="208" y="400" width="4" height="22" fill="{NAVY}" opacity="0.7"/>
  <rect x="215" y="400" width="2" height="22" fill="{NAVY}" opacity="0.7"/>
  <rect x="220" y="400" width="3" height="22" fill="{NAVY}" opacity="0.7"/>'''


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------

def build_svg(key: str, transparent: bool = False) -> str:
    b = BOTS[key]
    prop = svg_safety_prop(b) if key == "safety" else svg_warehouse_prop(b)
    backdrop = "" if transparent else svg_backdrop()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <title>{b["name_cn"]} · 飞书机器人头像</title>{svg_defs(b)}{backdrop}
  <g>{svg_chassis(b)}</g>
  {prop}
</svg>
'''


def render(svg: str, out_path: Path, size: int) -> None:
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(out_path),
                     output_width=size, output_height=size)


def main() -> None:
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    TRANSPARENT_DIR.mkdir(parents=True, exist_ok=True)

    for key in BOTS:
        svg = build_svg(key)
        svg_path = HERE / f"{key}-assistant.svg"
        svg_path.write_text(svg, encoding="utf-8")
        print(f"  SVG  {svg_path.relative_to(ASSET_DIR)}")

        for size in SIZES:
            out = PNG_DIR / f"{key}-assistant-{size}.png"
            render(svg, out, size)
            print(f"  PNG  {out.relative_to(ASSET_DIR)}  ({size}×{size})")

        out = TRANSPARENT_DIR / f"{key}-assistant-transparent-{EXPORT_SIZE}.png"
        render(build_svg(key, transparent=True), out, EXPORT_SIZE)
        print(f"  PNG  {out.relative_to(ASSET_DIR)}  (transparent)")

    print("完成。运行 preview.py 生成评审图。")


if __name__ == "__main__":
    main()
