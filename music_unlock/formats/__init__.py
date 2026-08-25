"""格式注册与自动识别。"""
from __future__ import annotations

from pathlib import Path

from ..errors import UnsupportedError
from .base import DecodeOptions, Decoder
from .kgm import KGM_MAGIC, KgmDecoder, VPR_MAGIC
from .kwm import KwmDecoder
from .ncm import MAGIC as NCM_MAGIC
from .ncm import NcmDecoder
from .qmc import QmcDecoder, parse_footer

DECODERS: list[Decoder] = [NcmDecoder(), QmcDecoder(), KgmDecoder(), KwmDecoder()]

# 扩展名 -> 解码器 的快速索引
_EXT_INDEX: dict[str, Decoder] = {}
for _d in DECODERS:
    for _ext in _d.extensions:
        _EXT_INDEX[_ext] = _d


def pick_decoder(path: Path) -> Decoder:
    """按扩展名选择解码器；未知扩展名时用魔数嗅探兜底。"""
    dec = _EXT_INDEX.get(path.suffix.lower())
    if dec is not None:
        return dec
    with path.open("rb") as fp:
        head = fp.read(16)
        tail = None
        fp.seek(0)
        size = path.stat().st_size
        if size >= 8:
            fp.seek(max(0, size - 1024))
            tail = fp.read(1024)
    if head[:8] == NCM_MAGIC:
        return _EXT_INDEX[".ncm"]
    if head[:16] in (KGM_MAGIC, VPR_MAGIC):
        return _EXT_INDEX[".kgm"]
    if tail and parse_footer(tail) is not None:
        return _EXT_INDEX[".mflac"]
    raise UnsupportedError(f"{path.name}: 无法识别的加密格式（扩展名 {path.suffix or '未知'}）")


def supported_extensions() -> frozenset[str]:
    return frozenset(_EXT_INDEX)
