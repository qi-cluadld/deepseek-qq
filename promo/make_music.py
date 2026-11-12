"""生成 30 秒无版权 BGM（纯合成，numpy 手写）。

    python promo/make_music.py

Am - F - C - G 的四和弦环境垫 + 低音 + 轻琶音 + 转场噪声上升音。
输出 promo/bgm.wav（44.1kHz / 16bit / 立体声）。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
DUR = 30.0
N = int(SR * DUR)
OUT = Path(__file__).resolve().parent / "bgm.wav"

# 每段和弦 7.5s，四段共 30s：Am - F - C - G
CHORDS = [
    (110.00, [220.00, 261.63, 329.63, 440.00]),   # Am
    (87.31, [174.61, 261.63, 349.23, 440.00]),    # F
    (130.81, [261.63, 329.63, 392.00, 523.25]),   # C
    (98.00, [196.00, 293.66, 392.00, 493.88]),    # G
]
CHORD_LEN = 7.5
CUTS = [4.0, 9.0, 15.5, 20.5, 25.5]


def fft_lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    # 一阶滚降，避免硬切产生铃音
    gain = 1.0 / (1.0 + (freqs / cutoff) ** 2)
    return np.fft.irfft(spec * gain, n=len(x))


def pad_note(freq: float, start: float, length: float, amp: float) -> np.ndarray:
    buf = np.zeros(N)
    i0 = int(start * SR)
    n = min(int(length * SR), N - i0)
    if n <= 0:
        return buf
    tt = np.arange(n) / SR

    # 轻微失谐的两层 + 泛音，听感更厚
    wave_f = (
        np.sin(2 * np.pi * freq * tt)
        + 0.55 * np.sin(2 * np.pi * freq * 1.004 * tt + 1.1)
        + 0.22 * np.sin(2 * np.pi * 2 * freq * tt)
        + 0.08 * np.sin(2 * np.pi * 3 * freq * tt)
    )
    env = np.ones(n)
    a = min(int(1.3 * SR), n)
    r = min(int(1.6 * SR), n)
    env[:a] = np.linspace(0, 1, a) ** 1.6
    env[n - r:] *= np.linspace(1, 0, r) ** 1.2
    buf[i0:i0 + n] += wave_f * env * amp * 0.25
    return buf


def pluck(freq: float, start: float, amp: float = 0.10) -> np.ndarray:
    buf = np.zeros(N)
    i0 = int(start * SR)
    n = min(int(0.9 * SR), N - i0)
    if n <= 0:
        return buf
    tt = np.arange(n) / SR
    env = np.exp(-tt * 6.5)
    tone = np.sin(2 * np.pi * freq * tt) + 0.3 * np.sin(2 * np.pi * 2 * freq * tt)
    buf[i0:i0 + n] += tone * env * amp
    return buf


def riser(start: float, amp: float = 0.06) -> np.ndarray:
    buf = np.zeros(N)
    i0 = int(start * SR)
    n = min(int(1.0 * SR), N - i0)
    if n <= 0:
        return buf
    rng = np.random.default_rng(int(start * 100))
    noise = rng.standard_normal(n)
    env = np.linspace(0, 1, n) ** 2.2
    sweep = np.sin(2 * np.pi * np.linspace(200, 900, n) * np.arange(n) / SR)
    buf[i0:i0 + n] += (0.6 * noise + 0.4 * sweep) * env * amp
    return buf


def main() -> int:
    mix = np.zeros(N)

    for i, (bass, tones) in enumerate(CHORDS):
        start = i * CHORD_LEN
        for tone in tones:
            mix += pad_note(tone, start, CHORD_LEN + 1.2, 1.0)
        mix += pad_note(bass, start, CHORD_LEN + 1.2, 1.3)

    # 琶音：每 0.5s 一个音，按和弦音循环
    step = 0.5
    t = 0.0
    idx = 0
    while t < DUR - 0.6:
        chord_i = min(int(t / CHORD_LEN), len(CHORDS) - 1)
        tones = CHORDS[chord_i][1]
        f = tones[idx % len(tones)] * 2
        mix += pluck(f, t, 0.09)
        t += step
        idx += 1

    # 转场前的轻微上升音
    for cut in CUTS:
        mix += riser(cut - 1.0, 0.05)

    mix = fft_lowpass(mix, 5200)          # 去掉刺耳高频
    mix = mix - fft_lowpass(mix, 70)      # 70Hz 高通：手机外放听不到的浑浊低频
    mix = mix + 0.28 * (mix - fft_lowpass(mix, 900))  # 中频提一点存在感
    mix *= (1 + 0.05 * np.sin(2 * np.pi * 0.13 * np.arange(N) / SR))  # 缓慢呼吸感

    # 立体声：右声道延迟 12ms（Haas），拉开宽度
    delay = int(0.012 * SR)
    left = mix.copy()
    right = np.concatenate([np.zeros(delay), mix[:N - delay]])
    stereo = np.stack([left, right * 0.95], axis=1)

    # 淡入淡出 + 归一化到 -6 dBFS 峰值
    fade_in = int(0.6 * SR)
    fade_out = int(1.8 * SR)
    stereo[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    stereo[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = np.max(np.abs(stereo))
    stereo = stereo / peak * 0.5
    stereo = np.tanh(stereo * 1.1) / np.tanh(1.1) * 0.5

    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(str(OUT), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())

    rms = np.sqrt(np.mean(stereo ** 2))
    print(f"写出 {OUT}（{OUT.stat().st_size / 1024 / 1024:.1f} MB）")
    print(f"峰值 {20 * np.log10(np.max(np.abs(stereo)) + 1e-9):.1f} dBFS，"
          f"RMS {20 * np.log10(rms + 1e-9):.1f} dBFS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
