# -*- coding: utf-8 -*-
"""**程序化音床**：后室的声音全部由代码合成，零外部音频素材。

沿用 3dworld 的做法（``logic/kkrieger_audio.py`` / ``liminall_audio.py``）：
首次运行离线合成一段 WAV 缓存到 ``assets/``，之后直接加载——
渲染不等合成，音画共用同一套时间常量。

三层声音（对应后室的听觉特征）
------------------------------
1. **荧光灯嗡**（50/60Hz 及其谐波 + 轻微频率漂移）——最上层、最烦人；
2. **低频嗡鸣**（亚低频 40~70Hz 缓慢拍频）——胸腔里的压迫感；
3. **远处钢琴/人声残响**（稀疏的衰减正弦 + 噪声尾巴）——"以为听见了什么"。

层级越深：灯嗡越不稳（闪烁更频繁）、低频越重、远处残响越稀疏。
"""
from __future__ import annotations

import math
import os
import struct
import wave

SR = 22050
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'assets', 'backroom_bed.wav')
DEFAULT_SECONDS = 30.0


def _synth(seconds: float = DEFAULT_SECONDS, level: int = 0) -> list[float]:
    """合成一段单声道浮点采样（[-1, 1]）。"""
    n = int(seconds * SR)
    buf = [0.0] * n
    # 层越深：灯嗡越不稳、低频越重、残响越稀疏
    hum_instability = 0.05 + 0.09 * level
    sub_gain = 0.16 + 0.05 * level
    echo_spacing = 6.5 - 0.7 * level

    # ---- 1) 荧光灯嗡：50Hz 基频 + 谐波，带缓慢漂移与随机掉拍
    phase = 0.0
    for i in range(n):
        t = i / SR
        drift = 1.0 + hum_instability * 0.02 * math.sin(t * 0.37 + 1.3)
        f = 50.0 * drift
        phase += 2.0 * math.pi * f / SR
        v = (math.sin(phase) * 0.55
             + math.sin(phase * 2.0) * 0.22
             + math.sin(phase * 3.0) * 0.10)
        # 随机掉拍（灯管老化）：短时静音
        if (i // (SR // 3)) % 37 == 0 and (i % (SR // 3)) < 900:
            v *= 0.15
        buf[i] += v * 0.085

    # ---- 2) 低频嗡鸣：两个相近低频拍频
    for i in range(n):
        t = i / SR
        beat = math.sin(2 * math.pi * 43.0 * t) * math.sin(2 * math.pi * 0.13 * t)
        buf[i] += beat * sub_gain

    # ---- 3) 远处残响：稀疏的衰减正弦（"以为听见了什么"）
    rng_state = 12345 + level * 977

    def rnd():
        nonlocal rng_state
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        return rng_state / 0x7FFFFFFF

    t0 = 2.0
    while t0 < seconds - 1.0:
        start = int(t0 * SR)
        dur = int((1.2 + rnd() * 1.8) * SR)
        f0 = 180.0 + rnd() * 520.0
        amp = 0.030 + rnd() * 0.035
        for j in range(min(dur, n - start)):
            env = math.exp(-3.2 * j / dur)
            buf[start + j] += math.sin(2 * math.pi * f0 * j / SR) * amp * env
        t0 += echo_spacing * (0.6 + rnd())

    # ---- 归一化 + 淡入淡出（首尾不能咔哒）
    peak = max(abs(v) for v in buf) or 1.0
    fade = int(SR * 0.5)
    for i in range(n):
        g = 1.0
        if i < fade:
            g = i / fade
        elif i > n - fade:
            g = (n - i) / fade
        buf[i] = (buf[i] / peak) * 0.72 * g
    return buf


def ensure_bed(level: int = 0, seconds: float = DEFAULT_SECONDS) -> str:
    """返回音床 WAV 路径（不存在就合成并缓存）。"""
    path = CACHE if level == 0 else CACHE.replace('.wav', f'_l{level}.wav')
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = _synth(seconds, level)
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = b''.join(struct.pack('<h', max(-32767, min(32767, int(v * 32767))))
                          for v in buf)
        w.writeframes(frames)
    return path


def load(path: str):
    """加载音床（pyglet 2.x：静态 Source 用 Player 包装，且没有 .player()）。"""
    import pyglet
    src = pyglet.media.load(path, streaming=False)
    player = pyglet.media.Player()
    player.queue(src)
    player.loop = True
    return player
