"""解码器基类与格式注册。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..model import DecodeResult


@dataclass(slots=True)
class DecodeOptions:
    """解码时外部可提供的密钥材料。"""

    ekey: str | None = None          # 手动指定的 QMC EKey（base64 字符串）
    ekey_db: Path | None = None      # QQ 音乐安卓端 player_process_db 路径
    kgm_key: Path | None = None      # 酷狗公钥 kugou_key.xz 路径
    extra: dict = field(default_factory=dict)


class Decoder(ABC):
    """一个加密格式的解码器。"""

    name: str = "?"
    extensions: frozenset[str] = frozenset()

    @abstractmethod
    def decode(self, path: Path, opts: DecodeOptions) -> DecodeResult:
        """解密单个文件，返回 DecodeResult。"""
        raise NotImplementedError

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions
