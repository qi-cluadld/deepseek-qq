"""生成 9:16 视频封面（1080x1920）。

    python promo/make_cover.py

复用 make_promo 的背景/光晕/字体，出两个版式：
  cover-A：大标题 + 高亮条（缩略图下最抓眼）
  cover-B：大标题 + 手机聊天截图感
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

import make_promo as P  # noqa: E402

OUT = Path(__file__).resolve().parent


def canvas(glow_blue=(-380, -260), glow_purple=(430, 880)) -> tuple[Image.Image, ImageDraw.Draw, Image.Image]:
    img = P.BASE.copy()
    P.blit(img, P.GLOW_BLUE, *glow_blue)
    P.blit(img, P.GLOW_PURPLE, *glow_purple)
    ov = Image.new("RGBA", (P.W, P.H), (0, 0, 0, 0))
    return img, ImageDraw.Draw(ov), ov


def pill(d: ImageDraw.Draw, cx: int, cy: int, text: str, size: int = 34,
         fg=P.WHITE, bg=(255, 255, 255, 26), border=(255, 255, 255, 70)):
    f = P.font(size, True)
    tw = d.textlength(text, font=f)
    w, h = tw + size * 1.6, size + 34
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                        radius=h / 2, fill=bg, outline=border, width=2)
    d.text((cx, cy - 2), text, font=f, fill=fg, anchor="mm")


def cover_a() -> Image.Image:
    img, d, ov = canvas()

    pill(d, P.W // 2, 470, "开源 · 免费 · 5 分钟接入", 34)

    d.text((P.W / 2, 700), "把 DeepSeek", font=P.font(136, True),
           fill=(*P.WHITE, 255), anchor="mm")
    d.text((P.W / 2, 858), "塞进 QQ", font=P.font(136, True),
           fill=(*P.WHITE, 255), anchor="mm")

    # 高亮条：缩略图里最抓眼的一块
    label = "只要一个 EXE"
    f = P.font(90, True)
    tw = d.textlength(label, font=f)
    bw, bh = tw + 120, 158
    d.rounded_rectangle([P.W / 2 - bw / 2, 1000, P.W / 2 + bw / 2, 1000 + bh],
                        radius=36, fill=(*P.ACCENT, 255))
    d.text((P.W / 2, 1000 + bh / 2 - 4), label, font=f, fill=(255, 255, 255, 255), anchor="mm")

    d.text((P.W / 2, 1250), "不用服务器 · 不用公网 IP · 不用装 Python",
           font=P.font(36), fill=(*P.MUTED, 255), anchor="mm")

    # 底部：仓库地址放进描边胶囊，视觉上收住画面
    url = "github.com/qi-cluadld/deepseek-qq"
    fu = P.font(34, True)
    uw = d.textlength(url, font=fu)
    d.rounded_rectangle([P.W / 2 - uw / 2 - 56, 1660, P.W / 2 + uw / 2 + 56, 1764],
                        radius=52, fill=(255, 255, 255, 14),
                        outline=(*P.ACCENT, 150), width=2)
    d.text((P.W / 2, 1712), url, font=fu, fill=(215, 224, 250, 245), anchor="mm")

    img.alpha_composite(ov)
    img.alpha_composite(P.VIGNETTE)
    return img.convert("RGB")


def cover_b() -> Image.Image:
    img, d, ov = canvas(glow_blue=(-420, -320), glow_purple=(360, 1180))

    d.text((P.W / 2, 470), "在 QQ 里", font=P.font(104, True), fill=(*P.WHITE, 255), anchor="mm")
    d.text((P.W / 2, 590), "直接问 DeepSeek", font=P.font(104, True),
           fill=(*P.ACCENT, 255), anchor="mm")

    # 手机 + 两条气泡 + 输入框
    d.rounded_rectangle([210, 740, 870, 1400], radius=56,
                        fill=(255, 255, 255, 12), outline=(255, 255, 255, 40), width=3)
    d.rectangle([390, 766, 690, 780], fill=(255, 255, 255, 30))  # 刘海

    def bubble(text, y, mine, size=38):
        f = P.font(size)
        tw = d.textlength(text, font=f)
        w, h = tw + 64, size + 56
        x0 = 810 - w if mine else 250
        x1 = x0 + w
        fill = (*P.ACCENT, 240) if mine else (255, 255, 255, 28)
        d.rounded_rectangle([x0, y, x1, y + h], radius=24, fill=fill)
        d.text((x0 + 32, y + h / 2), text, font=f, fill=(255, 255, 255, 255), anchor="lm")
        return y + h

    y = bubble("帮我把这批文件改名", 840, True)
    y = bubble("可以，用 os.rename 就行", y + 26, False)
    bubble("要连子文件夹吗？", y + 26, False)

    d.rounded_rectangle([250, 1290, 830, 1358], radius=34,
                        fill=(255, 255, 255, 18), outline=(255, 255, 255, 34), width=2)
    d.text((286, 1324), "说点什么…", font=P.font(32), fill=(150, 158, 185, 255), anchor="lm")

    pill(d, P.W // 2, 1530, "一个 exe  ·  双击就能跑", 38, fg=P.WHITE)
    d.text((P.W / 2, 1690), "github.com/qi-cluadld/deepseek-qq",
           font=P.font(32, True), fill=(180, 190, 220, 225), anchor="mm")

    img.alpha_composite(ov)
    img.alpha_composite(P.VIGNETTE)
    return img.convert("RGB")


# ---------------------------------------------------------------- 16:10 横版

WW, WH = 1920, 1200


def build_wide_assets():
    """16:10 画布的背景 / 光晕 / 暗角（尺寸不同，单独生成一次）。"""
    import numpy as np

    yy = np.linspace(0, 1, WH)[:, None, None]
    top = np.array(P.BG_TOP, dtype=np.float32)
    bottom = np.array(P.BG_BOTTOM, dtype=np.float32)
    arr = np.repeat(top * (1 - yy) + bottom * yy, WW, axis=1)
    base = Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")

    grid = Image.new("RGBA", (WW, WH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, WW, 72):
        gd.line([(x, 0), (x, WH)], fill=(255, 255, 255, 7), width=1)
    for y in range(0, WH, 72):
        gd.line([(0, y), (WW, y)], fill=(255, 255, 255, 6), width=1)
    base.alpha_composite(grid)

    rng = np.random.default_rng(11)
    dots = Image.new("RGBA", (WW, WH), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for _ in range(140):
        x, y = int(rng.integers(0, WW)), int(rng.integers(0, WH))
        r = int(rng.integers(1, 3))
        dd.ellipse([x, y, x + r, y + r], fill=(255, 255, 255, int(rng.integers(18, 65))))
    base.alpha_composite(dots)

    yy2, xx2 = np.mgrid[0:WH, 0:WW].astype(np.float32)
    nx = (xx2 - WW / 2) / (WW / 2)
    ny = (yy2 - WH / 2) / (WH / 2)
    dd_ = np.sqrt(nx ** 2 + ny ** 2) / 1.4142
    alpha = (np.clip((dd_ - 0.55) / 0.45, 0, 1) ** 1.6 * 190).astype(np.uint8)
    vig_arr = np.zeros((WH, WW, 4), dtype=np.uint8)
    vig_arr[..., 3] = alpha
    vignette = Image.fromarray(vig_arr, "RGBA")

    return base, P.build_glow(1700, P.ACCENT), P.build_glow(1500, P.ACCENT2), vignette


def cover_wide() -> Image.Image:
    base, glow_b, glow_p, vignette = build_wide_assets()
    img = base.copy()
    P.blit(img, glow_b, -560, -640)
    P.blit(img, glow_p, 1180, 520)

    ov = Image.new("RGBA", (WW, WH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    left = 132

    # 顶部标签：左对齐
    label = "开源 · 免费 · 5 分钟接入"
    f = P.font(34, True)
    tw = d.textlength(label, font=f)
    d.rounded_rectangle([left, 268, left + tw + 76, 268 + 70], radius=35,
                        fill=(255, 255, 255, 26), outline=(255, 255, 255, 70), width=2)
    d.text((left + 38, 301), label, font=f, fill=(*P.WHITE, 255), anchor="lm")

    # 主标题
    d.text((left, 470), "把 DeepSeek", font=P.font(124, True), fill=(*P.WHITE, 255), anchor="lm")
    d.text((left, 612), "塞进 QQ", font=P.font(124, True), fill=(*P.WHITE, 255), anchor="lm")

    # 高亮条
    hl = "只要一个 EXE"
    f2 = P.font(78, True)
    hw = d.textlength(hl, font=f2)
    d.rounded_rectangle([left, 742, left + hw + 96, 742 + 150], radius=32, fill=(*P.ACCENT, 255))
    d.text((left + 48, 742 + 71), hl, font=f2, fill=(255, 255, 255, 255), anchor="lm")

    d.text((left, 986), "不用服务器 · 不用公网 IP · 不用装 Python",
           font=P.font(38), fill=(*P.MUTED, 255), anchor="lm")

    url = "github.com/qi-cluadld/deepseek-qq"
    d.text((left, 1082), url, font=P.font(34, True), fill=(196, 206, 236, 240), anchor="lm")

    # 右侧：聊天演示
    px0, py0, px1, py1 = 1150, 165, 1790, 1080
    d.rounded_rectangle([px0, py0, px1, py1], radius=64,
                        fill=(255, 255, 255, 12), outline=(255, 255, 255, 42), width=3)
    d.rectangle([1450, 196, 1690, 210], fill=(255, 255, 255, 30))

    d.text((px0 + 44, 272), "DeepSeek 助手", font=P.font(34, True), fill=(*P.WHITE, 240), anchor="lm")
    d.ellipse([px0 + 44, 314, px0 + 58, 328], fill=(*P.GREEN, 240))
    d.text((px0 + 68, 321), "在线", font=P.font(24), fill=(*P.MUTED, 255), anchor="lm")
    d.line([(px0, 360), (px1, 360)], fill=(255, 255, 255, 26), width=2)

    def bubble(text, y, mine, size=32):
        bf = P.font(size)
        btw = d.textlength(text, font=bf)
        w, h = btw + 56, size + 50
        x0 = px1 - 40 - w if mine else px0 + 40
        fill = (*P.ACCENT, 240) if mine else (255, 255, 255, 28)
        d.rounded_rectangle([x0, y, x0 + w, y + h], radius=22, fill=fill)
        d.text((x0 + 28, y + h / 2), text, font=bf, fill=(255, 255, 255, 255), anchor="lm")
        return y + h

    yy = bubble("帮我把这批文件改名", 400, True)
    yy = bubble("可以，用 os.rename 就行", yy + 24, False)
    yy = bubble("要连子文件夹吗？", yy + 24, False)
    bubble("好嘞，脚本发你", yy + 24, False)

    d.rounded_rectangle([px0 + 40, 972, px1 - 40, 1036], radius=32,
                        fill=(255, 255, 255, 18), outline=(255, 255, 255, 34), width=2)
    d.text((px0 + 72, 1004), "说点什么…", font=P.font(28), fill=(150, 158, 185, 255), anchor="lm")

    img.alpha_composite(ov)
    img.alpha_composite(vignette)
    return img.convert("RGB")


def main() -> int:
    a = cover_a()
    b = cover_b()
    a.save(OUT / "deepseek-qq-cover-9x16.png")
    b.save(OUT / "cover-B.png")
    w = cover_wide()
    w.save(OUT / "deepseek-qq-cover-16x10.png")
    # 缩略图预览：模拟信息流里的小图，检查文字是否还看得清
    a.resize((270, 480), Image.LANCZOS).save(OUT / "_thumb_A.png")
    b.resize((270, 480), Image.LANCZOS).save(OUT / "_thumb_B.png")
    w.resize((480, 300), Image.LANCZOS).save(OUT / "_thumb_W.png")
    print("cover A ->", OUT / "deepseek-qq-cover-9x16.png")
    print("cover B ->", OUT / "cover-B.png")
    print("cover W ->", OUT / "deepseek-qq-cover-16x10.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
