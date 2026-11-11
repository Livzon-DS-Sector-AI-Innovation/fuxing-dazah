# -*- coding: utf-8 -*-
"""生成飞书机器人头像的评审图 / 效果图。

用法：先跑 generate.py 产出 PNG，再：
    .venv/bin/python preview.py

输出（preview/）：
    contact-sheet.png   评审板：方形 / 圆形 / 小尺寸 / 暗色模式 / 色板 / 设计口径
    chat-mock.png       飞书会话中的实际显示效果（44px 头像）
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ASSET_DIR = HERE.parent
PNG_DIR = ASSET_DIR / "png"
PREVIEW_DIR = ASSET_DIR / "preview"

# 品牌中性色（与 frontend DESIGN.md 对齐）
SURFACE = (246, 245, 244)
CARD = (255, 255, 255)
INK = (26, 26, 26)
SLATE = (93, 91, 84)
STEEL = (120, 118, 113)
HAIR = (229, 227, 223)
DARK = (31, 35, 41)
DARK_MUTED = (164, 160, 151)
BLUE = (86, 69, 212)
FEISHU_BLUE = (46, 115, 242)

FONT_PATHS = ["/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]

BOTS = {
    "safety": dict(cn="安全助手", en="SAFETY ASSISTANT",
                   tagline="安全模块 · 隐患 / 检查 / 培训 / 知识问答",
                   accent=(255, 197, 61)),
    "warehouse": dict(cn="仓储助手", en="WAREHOUSE ASSISTANT",
                      tagline="仓储模块 · 入库 / 出库 / 领料 / 盘点",
                      accent=(245, 140, 60)),
}
PALETTE = {
    "safety": ["#C9DEF8", "#92B9EA", "#FFC53D", "#DE9A0D"],
    "warehouse": ["#FFDFC2", "#EFA96E", "#F58C3C", "#B9571A"],
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _font(size: int, bold: bool = False):
    for path in FONT_PATHS:
        try:
            index = 2 if (bold and path.endswith(".ttc")) else 0
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def load(key: str) -> Image.Image:
    return Image.open(PNG_DIR / f"{key}-assistant-1024.png").convert("RGBA")


def img_at(key: str, size: int) -> Image.Image:
    return load(key).resize((size, size), Image.LANCZOS)


def circle(key: str, size: int) -> Image.Image:
    im = img_at(key, size)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def paste(canvas: Image.Image, im: Image.Image, x, y) -> None:
    canvas.paste(im, (int(x), int(y)), im)


def soft_shadow(canvas: Image.Image, box, radius: int, alpha: int = 20,
                blur: int = 22, dy: int = 8) -> None:
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0, y0 + dy, x1, y1 + dy), radius=radius, fill=(0, 0, 0, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def text(draw: ImageDraw.ImageDraw, xy, s: str, size: int, color,
         bold: bool = False, anchor=None) -> None:
    draw.text(xy, s, font=_font(size, bold), fill=color, anchor=anchor)


def wrap(draw: ImageDraw.ImageDraw, s: str, size: int, width: int) -> list[str]:
    f = _font(size)
    lines, cur = [], ""
    for ch in s:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if draw.textlength(cur + ch, font=f) <= width:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# 评审板
# ---------------------------------------------------------------------------

CARD_W, CARD_H = 712, 600
CARD_Y = 210
CARD_X = {"safety": 72, "warehouse": 816}


def _card_avatar_column(card: Image.Image, key: str) -> None:
    """方形 + 圆形大图以及说明。"""
    d = ImageDraw.Draw(card)
    big = 280
    left, right = 64, 368
    paste(card, img_at(key, big), left, 100)
    paste(card, circle(key, big), right, 100)
    text(d, (left + big // 2, 390), "满幅方形 · 上传源文件", 15, STEEL, anchor="ma")
    text(d, (right + big // 2, 390), "圆形裁切 · 会话显示", 15, STEEL, anchor="ma")


def _card_small_sizes(card: Image.Image, key: str) -> None:
    d = ImageDraw.Draw(card)
    text(d, (26, 430), "小尺寸实测（圆形）", 15, SLATE, bold=True)
    sx = 26
    for size in (96, 64, 48, 32):
        paste(card, circle(key, size), sx, 458)
        text(d, (sx + size // 2, 458 + size + 8), f"{size}px", 13, STEEL, anchor="ma")
        sx += size + (28 if size > 32 else 0)

    # 暗底对比块
    strip = Image.new("RGBA", (196, 116), (0, 0, 0, 0))
    ImageDraw.Draw(strip).rounded_rectangle((0, 0, 195, 115), radius=14, fill=DARK + (255,))
    dx = 18
    for size in (64, 48, 32):
        im = circle(key, size)
        strip.paste(im, (dx, (116 - size) // 2), im)
        dx += size + 14
    card.alpha_composite(strip, (CARD_W - 26 - 196, 458))
    text(d, (CARD_W - 26 - 98, 580), "暗色模式", 13, STEEL, anchor="ma")


def build_contact_sheet() -> Image.Image:
    W, H = 1600, 1240
    canvas = Image.new("RGBA", (W, H), SURFACE + (255,))
    d = ImageDraw.Draw(canvas)

    # ---- 页眉 ----
    text(d, (72, 54), "DAZAH   ·   FEISHU BOT AVATARS   ·   V1.0", 15, STEEL, bold=True)
    text(d, (72, 86), "飞书机器人头像 · 机器人助手系列", 46, INK, bold=True)
    text(d, (72, 154),
         "同一副机器人底盘 + 角色道具：安全助手（安全帽 / 盾牌 · 冷蓝）· 仓储助手（天线 / 纸箱 · 暖橙）　512×512 母版",
         19, SLATE)
    text(d, (W - 72, 58), "2026-11-06", 15, STEEL, anchor="ra")
    text(d, (W - 72, 84), "circle-safe   ·   24–48px legible", 14, STEEL, anchor="ra")

    # ---- 两张角色卡 ----
    for key, x in CARD_X.items():
        soft_shadow(canvas, (x, CARD_Y, x + CARD_W, CARD_Y + CARD_H), 22)
        card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        dc = ImageDraw.Draw(card)
        dc.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=22, fill=CARD + (255,))
        b = BOTS[key]
        dc.rounded_rectangle((22, 20, 28, 76), radius=3, fill=b["accent"] + (255,))
        text(dc, (42, 18), b["cn"], 30, INK, bold=True)
        text(dc, (42, 62), b["tagline"], 16, STEEL)
        text(dc, (CARD_W - 24, 24), b["en"], 13, STEEL, bold=True, anchor="ra")

        _card_avatar_column(card, key)
        dc.line((26, 418, CARD_W - 26, 418), fill=HAIR, width=1)
        _card_small_sizes(card, key)
        canvas.alpha_composite(card, (x, CARD_Y))

    # ---- 底部：设计口径 ----
    py, ph = 846, 320
    soft_shadow(canvas, (72, py, 72 + 880, py + ph), 20)
    spec = Image.new("RGBA", (880, ph), (0, 0, 0, 0))
    ds = ImageDraw.Draw(spec)
    ds.rounded_rectangle((0, 0, 879, ph - 1), radius=20, fill=CARD + (255,))
    text(ds, (30, 24), "设计口径", 22, INK, bold=True)
    lines = [
        ("安全区", "内容外接半径 ≤ 228 / 512，圆形裁切不丢元素（帽檐、天线、箱角均已验算）"),
        ("小尺寸", "48px 可辨识：安全帽 vs 纸箱、冷蓝 vs 暖橙、盾与箱的上下关系"),
        ("无文字", "飞书端 24–48px 展示，不放文字与细线；细节全部用面与渐变表达"),
        ("同族规范", "同一底盘 / 构图 / 光效，只替换道具与色板，群内并排不打架"),
    ]
    y = 64
    for tag, desc in lines:
        ds.ellipse((30, y + 7, 38, y + 15), fill=(255, 197, 61) if tag == "小尺寸" else BLUE)
        text(ds, (48, y), tag, 15, INK, bold=True)
        text(ds, (116, y), desc, 15, SLATE)
        y += 44

    # 色板
    ds.line((30, 246, 850, 246), fill=HAIR, width=1)
    text(ds, (30, 262), "色板", 13, SLATE, bold=True)
    x = 86
    for key in ("safety", "warehouse"):
        text(ds, (x, 262), BOTS[key]["cn"][:2], 12, STEEL)
        x += 30
        for hexv in PALETTE[key]:
            rgb = tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))
            ds.rounded_rectangle((x, 260, x + 14, 274), radius=4, fill=rgb + (255,),
                                 outline=(0, 0, 0, 16))
            text(ds, (x + 19, 258), hexv, 11, STEEL)
            x += 76
        x += 14
    canvas.alpha_composite(spec, (72, py))

    # ---- 底部：暗色模式 / 实际像素 ----
    x0, w0 = 984, 544
    soft_shadow(canvas, (x0, py, x0 + w0, py + ph), 20)
    dark = Image.new("RGBA", (w0, ph), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dark)
    dd.rounded_rectangle((0, 0, w0 - 1, ph - 1), radius=20, fill=DARK + (255,))
    text(dd, (30, 22), "飞书暗色模式 · 实际像素", 20, (255, 255, 255), bold=True)
    text(dd, (30, 56), "私聊 44–48px　·　群聊 @ 32px　·　资料页 96px", 13, DARK_MUTED)

    for i, key in enumerate(("safety", "warehouse")):
        yy = 100 + i * 112
        text(dd, (30, yy + 8), BOTS[key]["cn"], 15, (255, 255, 255), bold=True)
        text(dd, (30, yy + 32), "安全模块" if key == "safety" else "仓储模块", 11, DARK_MUTED)
        xx = 150
        for size in (88, 64, 48, 32):
            im = circle(key, size)
            dark.paste(im, (xx, yy + (88 - size) // 2), im)
            xx += size + 18
    canvas.alpha_composite(dark, (x0, py))

    # ---- 页脚 ----
    text(ImageDraw.Draw(canvas), (72, H - 36),
         "源文件 src/*.svg　·　导出 png/*.png（1024 / 512 / 240 / 128 / 96 / 48）+ transparent/　·　生成脚本 src/generate.py",
         13, STEEL)
    return canvas.convert("RGB")


# ---------------------------------------------------------------------------
# 飞书会话效果图
# ---------------------------------------------------------------------------

def _bubble(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def build_chat_mock() -> Image.Image:
    W, H = 1400, 878
    canvas = Image.new("RGBA", (W, H), (237, 238, 240, 255))
    d = ImageDraw.Draw(canvas)

    # 顶栏
    d.rectangle((0, 0, W, 72), fill=(255, 255, 255, 255))
    d.line((0, 72, W, 72), fill=HAIR, width=1)
    d.rounded_rectangle((36, 28, 52, 44), radius=5, fill=FEISHU_BLUE)
    text(d, (64, 24), "飞书 · 会话效果预览", 19, INK, bold=True)
    text(d, (W - 36, 28), "消息头像 44px　·　2026-11-06", 14, STEEL, anchor="ra")

    conv = {
        "safety": [
            ("bot", "早上好，今日 3 条隐患待复核，已按风险等级排好序。"),
            ("card", ("高风险 · 动火作业", "2# 车间未挂警戒牌；监护人：李工；整改截止 16:00")),
            ("user", "生成整改单"),
            ("bot", "已生成《安全整改单》S-2026-1106-07，回复「确认」下发责任人。"),
            ("user", "本周隐患统计"),
            ("bot", "本周新增 12 条、闭环 9 条，闭环率 75%（上周 68%）。"),
        ],
        "warehouse": [
            ("bot", "五金库 A-03 货架低于安全库存：M8×40 螺栓 12 盒（安全库存 40 盒）。"),
            ("card", ("补货建议", "补货 40 盒 · 鑫盛紧固件 · 单价 ¥0.42 / 盒")),
            ("user", "提交领料"),
            ("bot", "领料单 WL-2026-1106-12 已创建，待仓管确认出库。"),
            ("user", "库存预警"),
            ("bot", "3 个货架低于安全库存：A-03、B-12、C-07。"),
        ],
    }

    cw, cy, ch = 652, 104, 712
    for key, x0 in (("safety", 36), ("warehouse", 712)):
        soft_shadow(canvas, (x0, cy, x0 + cw, cy + ch), 16)
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        dc = ImageDraw.Draw(card)
        dc.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=16, fill=(255, 255, 255, 255))

        # 会话头
        paste(card, circle(key, 44), 22, 18)
        text(dc, (78, 17), BOTS[key]["cn"], 18, INK, bold=True)
        dc.rounded_rectangle((78 + 84, 22, 78 + 84 + 58, 42), radius=5, fill=(240, 241, 243, 255))
        text(dc, (78 + 84 + 11, 24), "机器人", 12, STEEL)
        dc.line((0, 74, cw, 74), fill=HAIR, width=1)

        # 时间分隔
        text(dc, (cw // 2, 90), "今天 09:41", 11, (164, 160, 151), anchor="ma")
        y = 118
        for kind, payload in conv[key]:
            if kind == "bot":
                paste(card, circle(key, 44), 22, y)
                lines = wrap(dc, payload, 15, 404)
                bh = 20 + len(lines) * 24
                bw = max(90, 24 + max(dc.textlength(s, font=_font(15)) for s in lines))
                _bubble(dc, (78, y, 78 + bw, y + bh), 10, (242, 243, 245, 255))
                ty = y + 10
                for s in lines:
                    text(dc, (90, ty), s, 15, (31, 35, 41))
                    ty += 24
                y += bh + 22
            elif kind == "card":
                title, desc = payload
                paste(card, circle(key, 44), 22, y)
                _bubble(dc, (78, y, 78 + 470, y + 120), 10, (255, 255, 255, 255), HAIR, 1)
                dc.rounded_rectangle((78, y, 84, y + 120), radius=3, fill=BOTS[key]["accent"] + (255,))
                text(dc, (102, y + 14), title, 16, (31, 35, 41), bold=True)
                for i, s in enumerate(wrap(dc, desc, 14, 396)):
                    text(dc, (102, y + 44 + i * 22), s, 14, SLATE)
                dc.rounded_rectangle((102, y + 86, 204, y + 108), radius=5, fill=(237, 233, 248, 255))
                text(dc, (112, y + 89), "查看详情", 13, BLUE)
                y += 120 + 22
            else:
                f = _font(15)
                bw = dc.textlength(payload, font=f) + 32
                x1 = cw - 22 - bw
                _bubble(dc, (x1, y, x1 + bw, y + 38), 10, FEISHU_BLUE + (255,))
                text(dc, (x1 + 16, y + 9), payload, 15, (255, 255, 255))
                y += 38 + 26

        # 输入框
        dc.rounded_rectangle((22, ch - 62, cw - 22, ch - 20), radius=10, fill=(245, 246, 247, 255))
        text(dc, (40, ch - 52), "发送消息给 " + BOTS[key]["cn"] + " …", 14, (164, 160, 151))
        canvas.alpha_composite(card, (x0, cy))

    text(ImageDraw.Draw(canvas), (36, H - 38),
         "注：会话模型为示意，用来说明 44px 圆形头像在信息流中的辨识度与配色关系。", 13, STEEL)
    return canvas.convert("RGB")


def main() -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    sheet = build_contact_sheet()
    sheet.save(PREVIEW_DIR / "contact-sheet.png", optimize=True)
    print(f"  PNG  preview/contact-sheet.png  ({sheet.width}×{sheet.height})")

    mock = build_chat_mock()
    mock.save(PREVIEW_DIR / "chat-mock.png", optimize=True)
    print(f"  PNG  preview/chat-mock.png  ({mock.width}×{mock.height})")


if __name__ == "__main__":
    main()
