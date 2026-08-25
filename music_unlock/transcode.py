"""输出容器与 ffmpeg 转码。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import UnlockError

TARGETS = ("mp3", "flac", "m4a", "wav", "ogg")

_ENCODER_ARGS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
    "flac": ["-c:a", "flac"],
    "m4a": ["-c:a", "aac", "-b:a", "256k"],
    "wav": ["-c:a", "pcm_s16le"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
}


def resolve_ffmpeg(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() else None
    return shutil.which("ffmpeg")


def transcode(src: Path, dst: Path, target: str, ffmpeg: str | None = None) -> None:
    """用 ffmpeg 把 src 转成 target 容器写到 dst。"""
    binary = resolve_ffmpeg(ffmpeg)
    if binary is None:
        raise UnlockError("未找到 ffmpeg，请安装或通过 --ffmpeg 指定路径")
    args = _ENCODER_ARGS.get(target)
    if args is None:
        raise UnlockError(f"不支持的转码目标: {target}")
    cmd = [binary, "-y", "-v", "error", "-i", str(src), *args, str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dst.exists():
        raise UnlockError(f"ffmpeg 转码失败: {proc.stderr.strip()[:200]}")
