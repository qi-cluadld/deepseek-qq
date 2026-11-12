"""生成 9:16 竖屏宣传视频（1080x1920, 30fps, 30s）。

    python promo/make_promo.py

逐帧用 Pillow 绘制，再用 ffmpeg 编码成 H.264 MP4。
无外部素材依赖：背景渐变、光晕、手机外壳、气泡全部程序绘制。
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- 基础参数

W, H = 1080, 1920
FPS = 30
DUR = 30.0
TOTAL = int(FPS * DUR)

OUT_DIR = Path(__file__).resolve().parent
FRAME_DIR = OUT_DIR / "_frames"
VIDEO = OUT_DIR / "deepseek-qq-promo-9x16.mp4"
POSTER = OUT_DIR / "deepseek-qq-cover-9x16.png"

BG_TOP = (9, 12, 26)
BG_BOTTOM = (20, 17, 46)
ACCENT = (77, 107, 254)
ACCENT2 = (124, 92, 255)
WHITE = (245, 248, 255)
MUTED = (139, 148, 176)
GREEN = (52, 199, 123)

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"

_fonts: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    return _fonts[key]


# ---------------------------------------------------------------- 缓动函数

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease_out(p: float) -> float:
    return 1 - (1 - clamp(p)) ** 3


def ease_in_out(p: float) -> float:
    p = clamp(p)
    return 3 * p * p - 2 * p * p * p


def ease_back(p: float, s: float = 1.9) -> float:
    p = clamp(p) - 1
    return 1 + p * p * ((s + 1) * p + s)


def seg(t: float, start: float, dur: float = 0.55) -> float:
    """某个元素在 start 开始、dur 秒内完成的进度（0→1）。"""
    return clamp((t - start) / dur)


# ---------------------------------------------------------------- 静态素材

def build_base() -> Image.Image:
    """垂直渐变 + 极细网格 + 星点，一次生成。"""
    yy = np.linspace(0, 1, H)[:, None, None]
    top = np.array(BG_TOP, dtype=np.float32)
    bottom = np.array(BG_BOTTOM, dtype=np.float32)
    grad = top * (1 - yy) + bottom * yy           # H,1,3
    arr = np.repeat(grad, W, axis=1)              # H,W,3
    img = Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")

    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 72):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 7), width=1)
    for y in range(0, H, 72):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, 6), width=1)
    img.alpha_composite(grid)

    # 固定星点（用固定种子保证可复现）
    rng = np.random.default_rng(7)
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for _ in range(160):
        x = int(rng.integers(0, W))
        y = int(rng.integers(0, H))
        r = int(rng.integers(1, 3))
        a = int(rng.integers(18, 70))
        dd.ellipse([x, y, x + r, y + r], fill=(255, 255, 255, a))
    img.alpha_composite(dots)
    return img


def build_glow(size: int, color: tuple[int, int, int], power: float = 2.6) -> Image.Image:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2
    dist = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / c
    alpha = (np.clip(1 - dist, 0, 1) ** power * 255).astype(np.uint8)
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = color
    arr[..., 3] = alpha
    return Image.fromarray(arr, "RGBA")


def build_vignette() -> Image.Image:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx - W / 2) / (W / 2)
    ny = (yy - H / 2) / (H / 2)
    d = np.sqrt(nx ** 2 + ny ** 2) / math.sqrt(2)
    alpha = (np.clip((d - 0.55) / 0.45, 0, 1) ** 1.6 * 190).astype(np.uint8)
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    arr[..., 3] = alpha
    return Image.fromarray(arr, "RGBA")


BASE = build_base()
GLOW_BLUE = build_glow(1500, ACCENT)
GLOW_PURPLE = build_glow(1300, ACCENT2)
VIGNETTE = build_vignette()


def blit(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """支持负坐标的 alpha 合成。"""
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(src.width - sx0, dst.width - dx0)
    h = min(src.height - sy0, dst.height - dy0)
    if w <= 0 or h <= 0:
        return
    dst.alpha_composite(src.crop((sx0, sy0, sx0 + w, sy0 + h)), (dx0, dy0))


# ---------------------------------------------------------------- 绘图封装

class Frame:
    def __init__(self, t: float):
        self.t = t
        self.img = BASE.copy()
        # 两个缓慢漂移的光晕
        blit(self.img, GLOW_BLUE, int(-420 + 60 * math.sin(t * 0.35)), int(-380 + 40 * math.cos(t * 0.3)))
        blit(self.img, GLOW_PURPLE, int(480 + 50 * math.cos(t * 0.28)), int(900 + 60 * math.sin(t * 0.33)))
        self.ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.ov)

    def flush(self) -> None:
        self.img.alpha_composite(self.ov)
        self.ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.ov)

    def text(self, xy, s, size, color, bold=False, alpha=255, anchor="la", align="left"):
        if alpha <= 0 or not s:
            return
        self.d.text(xy, s, font=font(size, bold), fill=(*color, int(alpha)), anchor=anchor, align=align)

    def rect(self, box, radius=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def pill(self, cx, cy, text, size=34, pad_x=44, pad_y=20, fg=WHITE, bg=(255, 255, 255, 22), alpha=255):
        f = font(size, True)
        tw = self.d.textlength(text, font=f)
        w = tw + pad_x * 2
        h = size + pad_y * 2
        self.rect([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=h / 2,
                  fill=(bg[0], bg[1], bg[2], int(bg[3] * alpha / 255)),
                  outline=(255, 255, 255, int(60 * alpha / 255)), width=2)
        self.d.text((cx, cy - 2), text, font=f, fill=(*fg, alpha), anchor="mm")

    def check(self, cx, cy, r, color=GREEN, alpha=255):
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*color, alpha), width=4)
        self.d.line([(cx - r * 0.42, cy + r * 0.04), (cx - r * 0.08, cy + r * 0.4),
                     (cx + r * 0.48, cy - r * 0.36)], fill=(*color, alpha), width=5, joint="curve")

    def finish(self) -> Image.Image:
        self.flush()
        self.img.alpha_composite(VIGNETTE)
        return self.img.convert("RGB")


# ---------------------------------------------------------------- 各场景

def scene_intro(f: Frame, t: float) -> None:
    p = seg(t, 0.0, 0.7)
    dy = (1 - ease_out(p)) * 70

    f.pill(W / 2, 570 + dy, "OPEN SOURCE · 免费 · 5 分钟接入", size=32, alpha=int(255 * ease_out(seg(t, 0.1))))

    f.text((W / 2, 790 + dy), "DeepSeek", 132, ACCENT, bold=True, alpha=int(255 * p), anchor="mm")
    f.text((W / 2, 940 + dy), "接入 QQ", 132, WHITE, bold=True, alpha=int(255 * p), anchor="mm")

    line = "一个 exe，让 AI 住进你的 QQ"
    shown = int(len(line) * clamp((t - 1.25) / 1.15))
    if shown > 0:
        f.text((W / 2, 1090), line[:shown], 46, MUTED, alpha=235, anchor="mm")
        if int(t * 2.6) % 2 == 0 and shown < len(line):
            x = W / 2 + f.d.textlength(line[:shown], font=font(46)) / 2 + 6
            f.d.rectangle([x, 1090 - 24, x + 4, 1090 + 24], fill=(*ACCENT, 230))

    if t > 2.5:
        a = int(255 * ease_out(seg(t, 2.5, 0.6)))
        f.text((W / 2, 1175), "支持 NapCat / OneBot  ·  QQ 官方机器人", 34, MUTED, alpha=a, anchor="mm")

    # 底部三个小标签，填满下半屏并保持画面有持续变化
    chips = ["群聊私聊都行", "记得上下文", "长文自动分条"]
    f26 = font(28, True)
    widths = [f.d.textlength(c, font=f26) + 64 for c in chips]
    total = sum(widths) + 20 * (len(chips) - 1)
    x = (W - total) / 2
    for i, (chip, w) in enumerate(zip(chips, widths)):
        q = ease_out(seg(t, 2.75 + i * 0.16, 0.45))
        if q > 0:
            f.pill(x + w / 2, 1330 + (1 - q) * 24, chip, size=28, pad_x=32, pad_y=16,
                   fg=MUTED, bg=(255, 255, 255, int(16 * q)), alpha=int(255 * q))
        x += w + 20


def scene_value(f: Frame, t: float) -> None:
    f.text((W / 2, 620), "部署成本几乎为零", 40, MUTED, alpha=int(255 * ease_out(seg(t, 0.1, 0.5))), anchor="mm")

    lines = ["不用服务器", "不用公网 IP", "不用装 Python"]
    for i, text in enumerate(lines):
        start = 0.45 + i * 0.55
        p = ease_out(seg(t, start, 0.5))
        if p <= 0:
            continue
        y = 800 + i * 170
        dx = (1 - p) * -70
        a = int(255 * p)
        f.check(210 + dx, y, 30, ACCENT, a)
        f.text((280 + dx, y), text, 72, WHITE, bold=True, alpha=a, anchor="lm")

    if t > 2.9:
        a = int(255 * ease_out(seg(t, 2.9, 0.6)))
        f.text((W / 2, 1420), "双击 exe 就能跑", 40, ACCENT, alpha=a, anchor="mm")


def scene_chat(f: Frame, t: float) -> None:
    # 手机外壳
    box = [150, 340, 930, 1360]
    f.rect(box, radius=64, fill=(255, 255, 255, 10), outline=(255, 255, 255, 34), width=3)
    f.rect([300, 372, 780, 390], radius=9, fill=(255, 255, 255, 26))  # 刘海

    f.text((210, 460), "DeepSeek 助手", 38, WHITE, bold=True, anchor="lm", alpha=240)
    f.d.ellipse([210, 500, 226, 516], fill=(*GREEN, 240))
    f.text((238, 508), "在线", 26, MUTED, anchor="lm")
    f.d.line([(150, 550), (930, 550)], fill=(255, 255, 255, 26), width=2)

    def bubble(text, y, mine: bool, p: float, size=34):
        if p <= 0:
            return
        a = int(255 * clamp(p * 1.4))
        dy = (1 - ease_out(p)) * 34
        tw = f.d.textlength(text, font=font(size))
        w = tw + 64
        h = size + 56
        if mine:
            x1, x0 = 890, 890 - w
        else:
            x0, x1 = 186, 186 + w
        f.rect([x0, y + dy, x1, y + h + dy], radius=26,
               fill=(*ACCENT, int(225 * clamp(p * 1.6))) if mine else (255, 255, 255, int(26 * clamp(p * 1.6))))
        f.d.text((x0 + 32, y + h / 2 + dy), text, font=font(size), fill=(255, 255, 255, a), anchor="lm")
        return y + h + dy

    y = 590
    y1 = bubble("在吗？帮我把这批文件批量改名", y, True, seg(t, 0.45, 0.45))
    if y1:
        y = y1 + 30

    # 正在输入
    if 1.45 < t < 2.55:
        dots = int((t - 1.45) * 6) % 3
        f.rect([186, y, 300, y + 74], radius=24, fill=(255, 255, 255, 26))
        for i in range(3):
            cx = 216 + i * 30
            r = 7 if i == dots else 5
            f.d.ellipse([cx - r, y + 37 - r, cx + r, y + 37 + r], fill=(255, 255, 255, 200 if i == dots else 110))

    b2 = bubble("可以，用 os.rename 遍历就行", y, False, seg(t, 2.55, 0.45))
    if b2:
        y = b2 + 26
        b3 = bubble("要连子文件夹一起处理吗？", y, False, seg(t, 3.2, 0.45))
        if b3:
            y = b3 + 30
            b4 = bubble("要！", y, True, seg(t, 4.2, 0.4))
            if b4:
                y = b4 + 26
                bubble("好嘞，脚本马上发你", y, False, seg(t, 5.0, 0.45))

    # 输入框
    inp_y = 1210
    f.rect([186, inp_y, 894, inp_y + 82], radius=41, fill=(255, 255, 255, 16), outline=(255, 255, 255, 30), width=2)
    f.text((222, inp_y + 41), "说点什么…", 32, (150, 158, 185), anchor="lm")

    if t > 1.2:
        a = int(255 * ease_out(seg(t, 1.2, 0.6)))
        f.text((W / 2, 1450), "上下文记得住，聊多久都不会断", 38, MUTED, alpha=a, anchor="mm")


def scene_features(f: Frame, t: float) -> None:
    f.text((W / 2, 700), "它能做什么", 40, MUTED, alpha=int(255 * ease_out(seg(t, 0.1, 0.5))), anchor="mm")

    rows = [
        "多轮对话，记得上下文",
        "群里 @ 才说话，不打扰",
        "长文自动分条发送",
        "出错会用人话解释",
    ]
    for i, text in enumerate(rows):
        start = 0.4 + i * 0.42
        p = ease_out(seg(t, start, 0.5))
        if p <= 0:
            continue
        y = 880 + i * 150
        a = int(255 * p)
        dx = (1 - p) * 60
        f.rect([130 + dx, y - 62, 950 + dx, y + 62], radius=26,
               fill=(255, 255, 255, int(14 * p)), outline=(255, 255, 255, int(34 * p)), width=2)
        f.check(196 + dx, y, 26, GREEN, a)
        f.text((260 + dx, y), text, 44, WHITE, bold=True, alpha=a, anchor="lm")


def scene_modes(f: Frame, t: float) -> None:
    f.text((W / 2, 680), "两种接入方式，改一行就能切", 40, MUTED,
           alpha=int(255 * ease_out(seg(t, 0.1, 0.5))), anchor="mm")

    def card(y, p, title, sub, tag, accent):
        if p <= 0:
            return
        a = clamp(p)
        dy = (1 - ease_out(p)) * 46
        f.rect([110, y + dy, 970, y + 300 + dy], radius=36,
               fill=(255, 255, 255, int(16 * a)), outline=(*accent, int(120 * a)), width=3)
        f.text((160, y + 78 + dy), title, 60, WHITE, bold=True, alpha=int(255 * a), anchor="lm")
        f.text((160, y + 160 + dy), sub, 36, MUTED, alpha=int(240 * a), anchor="lm")
        f.pill(160 + 0, y + 236 + dy, tag, size=26, pad_x=26, pad_y=12, fg=accent, alpha=int(255 * a))

    card(760, seg(t, 0.4, 0.55), "NapCat / OneBot", "普通 QQ 号 · 群聊私聊都行", "推荐", ACCENT)
    f.text((W / 2, 1120), "或", 40, MUTED, alpha=int(255 * seg(t, 1.0, 0.4)), anchor="mm")
    card(1180, seg(t, 1.25, 0.55), "QQ 官方机器人", "appid + secret · 不用挂 QQ", "官方", ACCENT2)

    if t > 2.4:
        f.text((W / 2, 1570), "配置文件里一行 backend 搞定", 34, MUTED,
               alpha=int(255 * ease_out(seg(t, 2.4, 0.6))), anchor="mm")


REPO_URL = "https://github.com/qi-cluadld/deepseek-qq"
_qr_cache: Image.Image | None = None


def qr_image(px: int = 240) -> Image.Image | None:
    """仓库二维码（装不上 qrcode 就跳过）。"""
    global _qr_cache
    if _qr_cache is not None:
        return _qr_cache
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(border=1, box_size=12)
    qr.add_data(REPO_URL)
    qr.make(fit=True)
    img = qr.make_image(fill_color=(10, 13, 28), back_color=(255, 255, 255)).convert("RGBA")
    _qr_cache = img.resize((px, px), Image.NEAREST)
    return _qr_cache


def scene_outro(f: Frame, t: float) -> None:
    p = ease_out(seg(t, 0.1, 0.7))
    f.text((W / 2, 740 + (1 - p) * 60), "开源 · 免费 · 5 分钟接入", 68, WHITE, bold=True,
           alpha=int(255 * p), anchor="mm")

    if t > 0.9:
        q = ease_out(seg(t, 0.9, 0.55))
        cx, cy = W / 2, 950
        tw = f.d.textlength("github.com/qi-cluadld/deepseek-qq", font=font(36, True))
        w = tw + 100
        f.rect([cx - w / 2, cy - 56, cx + w / 2, cy + 56], radius=56,
               fill=(255, 255, 255, int(18 * q)), outline=(*ACCENT, int(190 * q)), width=3)
        f.text((cx, cy), "github.com/qi-cluadld/deepseek-qq", 36, WHITE, bold=True,
               alpha=int(255 * q), anchor="mm")

    if t > 1.6:
        a = int(255 * ease_out(seg(t, 1.6, 0.6)))
        f.text((W / 2, 1090), "让 AI 住进你的 QQ", 52, ACCENT, bold=True, alpha=a, anchor="mm")

    qr = qr_image(240)
    if qr is not None and t > 2.2:
        k = ease_out(seg(t, 2.2, 0.55))
        px = 240
        cx, cy = W / 2, 1320
        f.rect([cx - px / 2 - 20, cy - px / 2 - 20, cx + px / 2 + 20, cy + px / 2 + 20],
               radius=28, fill=(255, 255, 255, int(255 * k)))
        f.flush()
        f.img.alpha_composite(qr, (int(cx - px / 2), int(cy - px / 2)))
        f.ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        f.d = ImageDraw.Draw(f.ov)

    if t > 2.7:
        a = int(255 * ease_out(seg(t, 2.7, 0.5)))
        f.text((W / 2, 1520), "扫码看源码 · 点个 Star 支持一下", 34, MUTED, alpha=a, anchor="mm")


SCENES = [
    (0.0, 4.0, scene_intro),
    (4.0, 9.0, scene_value),
    (9.0, 15.5, scene_chat),
    (15.5, 20.5, scene_features),
    (20.5, 25.5, scene_modes),
    (25.5, 30.0, scene_outro),
]


def render_frame(index: int) -> Image.Image:
    t = index / FPS
    f = Frame(t)
    scene_start = 0.0
    for start, end, fn in SCENES:
        if start <= t < end:
            fn(f, t - start)
            scene_start = start
            break
    img = f.finish()

    # 场景切换时压一下黑，缓和硬切
    local = t - scene_start
    if scene_start > 0 and local < 0.2:
        k = 0.55 + 0.45 * (local / 0.2)
        img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, k)

    # 全局淡入淡出
    if t < 0.45:
        k = t / 0.45
        img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, k)
    elif t > DUR - 0.7:
        k = clamp((DUR - t) / 0.7)
        img = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), img, k)
    return img


def main() -> int:
    if FRAME_DIR.exists():
        shutil.rmtree(FRAME_DIR)
    FRAME_DIR.mkdir(parents=True)

    print(f"渲染 {TOTAL} 帧（{W}x{H} @ {FPS}fps，{DUR:.0f}s）...")
    for i in range(TOTAL):
        render_frame(i).save(FRAME_DIR / f"f{i:05d}.png", compress_level=1)
        if i % 90 == 0:
            print(f"  {i}/{TOTAL}")

    ffmpeg = shutil.which("ffmpeg") or r"D:\ffmpeg-n9.0.2-37-gae19868753-win64-gpl-shared-9.0\ffmpeg-n9.0.2-37-gae19868753-win64-gpl-shared-9.0\bin\ffmpeg.exe"
    cmd = [
        ffmpeg, "-y", "-framerate", str(FPS), "-i", str(FRAME_DIR / "f%05d.png"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-r", str(FPS), str(VIDEO),
    ]
    print("编码中...")
    subprocess.run(cmd, check=True, capture_output=True)

    render_frame(int(11.2 * FPS)).save(POSTER)
    shutil.rmtree(FRAME_DIR, ignore_errors=True)

    size = VIDEO.stat().st_size / 1024 / 1024
    print(f"完成：{VIDEO}（{size:.1f} MB）")
    print(f"封面：{POSTER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
