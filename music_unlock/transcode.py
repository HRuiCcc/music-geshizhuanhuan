"""输出容器与 ffmpeg 转码。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import UnlockError

TARGETS = ("mp3", "flac", "m4a", "wav", "ogg")

_ENCODER_ARGS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"],
    "flac": ["-c:a", "flac"],
    "m4a": ["-c:a", "aac", "-b:a", "256k"],
    "wav": ["-c:a", "pcm_s16le"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
}


def _windows_ffmpeg_candidates() -> list[Path]:
    found: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe")
        packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if packages.is_dir():
            found.extend(packages.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            found.append(Path(base) / "ffmpeg" / "bin" / "ffmpeg.exe")
    return found


def resolve_ffmpeg(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    for path in _windows_ffmpeg_candidates():
        if path.is_file():
            return str(path)
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return bundled
    except Exception:
        pass
    return None


def transcode(src: Path, dst: Path, target: str, ffmpeg: str | None = None) -> None:
    """用 ffmpeg 把 src 转成 target 容器写到 dst。只保留音轨，避免封面流导致 mp3 封装失败。"""
    binary = resolve_ffmpeg(ffmpeg)
    if binary is None:
        raise UnlockError("未找到 ffmpeg，请安装或通过 --ffmpeg 指定路径")
    args = _ENCODER_ARGS.get(target)
    if args is None:
        raise UnlockError(f"不支持的转码目标: {target}")
    cmd = [binary, "-y", "-v", "error", "-i", str(src), "-map", "0:a:0", "-map_metadata", "0", *args, str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        raise UnlockError(f"ffmpeg 转码失败: {detail or '无输出'}")
