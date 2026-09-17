"""提示音生成与播放。

用标准库 wave 模块在本地生成一个简短的双音“叮咚”提示音（原创，无版权问题），
首次使用时生成到 data/reminder.wav，之后复用。播放失败静默忽略——声音是提醒的
增强项，绝不能因为声音异常影响提醒本身。
"""
from __future__ import annotations

import logging
import math
import struct
import sys
import wave
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# 保持播放器的 Python 引用，防止函数返回后被垃圾回收导致声音中断
_last_player = None
_last_effect = None


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        frames = b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples
        )
        w.writeframes(frames)


def generate(path: Path | None = None) -> Path:
    """生成提示音 wav 并返回路径。"""
    target = path or config.SOUND_FILE
    if target.exists():
        return target

    samples: list[float] = []
    # 第一段：880Hz，0.35 秒，淡入淡出避免爆音
    n1 = int(SAMPLE_RATE * 0.35)
    for i in range(n1):
        t = i / SAMPLE_RATE
        env = min(1.0, i / (SAMPLE_RATE * 0.01), (n1 - i) / (SAMPLE_RATE * 0.05))
        samples.append(0.45 * math.sin(2 * math.pi * 880 * t) * env)
    # 第二段：1320Hz，0.45 秒
    n2 = int(SAMPLE_RATE * 0.45)
    for i in range(n2):
        t = i / SAMPLE_RATE
        env = min(1.0, i / (SAMPLE_RATE * 0.01), (n2 - i) / (SAMPLE_RATE * 0.08))
        samples.append(0.45 * math.sin(2 * math.pi * 1320 * t) * env)

    _write_wav(target, samples)
    return target


def play() -> None:
    """播放提示音（best-effort，失败不影响调用方）。优先用用户自定义铃声。"""
    try:
        path = _resolve_sound_path()
        if sys.platform == "win32":
            _play_windows_mci(path)
        elif path.suffix.lower() == ".wav":
            _play_qsoundeffect(path)
        else:
            _play_qmediaplayer(path)
    except Exception as exc:
        log.warning("播放提示音失败: %s", exc)


def _play_windows_mci(path: Path) -> None:
    """Windows 原生 MCI 播放（支持 wav / mp3，最可靠，不依赖 QtMultimedia）。"""
    import ctypes

    winmm = ctypes.windll.winmm
    winmm.mciSendStringW("close lablog_sound", None, 0, 0)
    mtype = "mpegvideo" if path.suffix.lower() == ".mp3" else "waveaudio"
    r = winmm.mciSendStringW(
        f'open "{path}" type {mtype} alias lablog_sound', None, 0, 0)
    if r != 0:
        buf = ctypes.create_unicode_buffer(256)
        winmm.mciGetErrorStringW(r, buf, 256)
        raise RuntimeError(f"MCI open 失败({r}): {buf.value}")
    winmm.mciSendStringW("play lablog_sound", None, 0, 0)


def _resolve_sound_path() -> Path:
    """解析要播放的铃声：用户自定义（settings）优先，否则用默认生成的。"""
    from ..database import get_setting

    custom = get_setting("remind_sound_path", "") or ""
    if custom:
        p = Path(custom)
        if p.exists():
            return p
    return generate()


def _play_qmediaplayer(path: Path) -> None:
    """用 QMediaPlayer 播放 mp3 等格式（需 QtMultimedia）。"""
    global _last_player
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    player = QMediaPlayer()
    audio = QAudioOutput()
    player.setAudioOutput(audio)
    audio.setVolume(0.9)
    player.setSource(QUrl.fromLocalFile(str(path)))
    player.play()
    _last_player = player  # 保持引用直到播放结束


def _play_qsoundeffect(path: Path) -> None:
    """非 Windows 平台的回退：QSoundEffect。"""
    global _last_effect
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QSoundEffect

    effect = QSoundEffect()
    effect.setSource(QUrl.fromLocalFile(str(path)))
    effect.setVolume(0.9)
    effect.play()
    _last_effect = effect  # 保持引用直到播放结束
