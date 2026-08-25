"""解码结果与输出容器识别。"""
from __future__ import annotations

from dataclasses import dataclass, field

# 常见音频容器魔数，用于解密后嗅探真实格式
_SNIFFERS = (
    (b"fLaC", "flac"),
    (b"OggS", "ogg"),
    (b"ID3", "mp3"),
    (b"RIFF", "wav"),
)


@dataclass(slots=True)
class DecodeResult:
    """一个文件解码后的结果。

    payload: 解密后的原始音频字节流
    container: 嗅探得到的容器格式（flac/mp3/ogg/m4a/wav）
    tags: 可选标签（title/artist/album）
    cover: 可选封面图片字节（png/jpeg）
    """

    payload: bytes
    container: str
    tags: dict[str, str] = field(default_factory=dict)
    cover: bytes | None = None
    source: str = ""

    @property
    def suggested_extension(self) -> str:
        """容器格式对应的文件扩展名。"""
        if self.container == "m4a":
            return "m4a"
        if self.container == "ogg":
            return "ogg"
        return self.container  # flac / mp3 / wav


def sniff_container(head: bytes) -> str:
    """根据文件头若干字节识别音频容器，无法识别返回 'bin'。"""
    for magic, name in _SNIFFERS:
        if head.startswith(magic):
            if magic == b"RIFF" and len(head) >= 12 and head[8:12] != b"WAVE":
                continue
            return name
    # MP4/M4A：第 5~8 字节为 ftyp
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "m4a"
    # MP3 无 ID3 头时可能直接以帧同步字开始
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3"
    return "bin"
