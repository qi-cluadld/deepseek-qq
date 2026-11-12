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


def main() -> int:
    a = cover_a()
    b = cover_b()
    a.save(OUT / "deepseek-qq-cover-9x16.png")
    b.save(OUT / "cover-B.png")
    # 缩略图预览：模拟信息流里的小图，检查文字是否还看得清
    a.resize((270, 480), Image.LANCZOS).save(OUT / "_thumb_A.png")
    b.resize((270, 480), Image.LANCZOS).save(OUT / "_thumb_B.png")
    print("cover A ->", OUT / "deepseek-qq-cover-9x16.png")
    print("cover B ->", OUT / "cover-B.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
