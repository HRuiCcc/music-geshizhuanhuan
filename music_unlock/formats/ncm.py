"""网易云音乐 NCM 解密器。"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from ..ciphers import ncm_decrypt_audio, ncm_stream_bytes
from ..errors import FormatError
from ..model import DecodeResult, sniff_container
from .base import DecodeOptions, Decoder

MAGIC = b"CTENFDAM"
CORE_KEY = b"hzHRAmso5kInbaxW"          # "neteasecloudmusic" 前缀的 AES 密钥
META_KEY = b"#14ljk_!\\]&0U<'("          # 元数据 AES 密钥
META_PREFIX = b"163 key(Don't modify):"


def _u32le(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 4], "little")


class NcmDecoder(Decoder):
    name = "网易云音乐 NCM"
    extensions = frozenset({".ncm"})

    def decode(self, path: Path, opts: DecodeOptions) -> DecodeResult:
        data = path.read_bytes()
        if len(data) < 0x2C or data[:8] != MAGIC:
            raise FormatError(f"{path.name}: 不是合法的 NCM 文件")

        pos = 10  # 跳过 magic(8) + 2 字节间隙

        # ---- 密钥区：XOR 0x64 后 AES-ECB 解密，去掉 17 字节前缀 ----
        key_len = _u32le(data, pos)
        pos += 4
        key_blob = bytes(b ^ 0x64 for b in data[pos : pos + key_len])
        pos += key_len
        key_plain = unpad(AES.new(CORE_KEY, AES.MODE_ECB).decrypt(key_blob), 16)
        rc4_key = key_plain[17:]

        # ---- 元数据区：XOR 0x63、base64、AES-ECB、JSON ----
        meta_len = _u32le(data, pos)
        pos += 4
        meta = {}
        if meta_len:
            meta_xor = bytes(b ^ 0x63 for b in data[pos : pos + meta_len])
            pos += meta_len
            if meta_xor.startswith(META_PREFIX):
                payload = base64.b64decode(meta_xor[len(META_PREFIX) :])
                plain = unpad(AES.new(META_KEY, AES.MODE_ECB).decrypt(payload), 16)
                meta = json.loads(plain[6:].decode("utf-8", "replace"))  # 去掉 "music:"
        else:
            pos += meta_len

        # ---- 封面区 ----
        pos += 5  # 5 字节间隙
        cover: bytes | None = None
        if pos + 8 <= len(data):
            image_space = _u32le(data, pos)
            pos += 4
            image_size = _u32le(data, pos)
            pos += 4
            if image_size and pos + image_size <= len(data):
                cover = data[pos : pos + image_size]
            if pos + image_space <= len(data):
                pos += image_space
            else:
                pos = len(data)

        # ---- 音频流 ----
        box = ncm_stream_bytes(rc4_key)
        audio = ncm_decrypt_audio(data[pos:], box)

        container = str(meta.get("format") or sniff_container(audio[:64]) or "mp3").lower()
        tags = {}
        if meta.get("musicName"):
            tags["title"] = str(meta["musicName"])
        artists = meta.get("artist") or []
        if artists and isinstance(artists[0], (list, tuple)):
            tags["artist"] = str(artists[0][0])
        if meta.get("album"):
            tags["album"] = str(meta["album"])

        return DecodeResult(payload=audio, container=container, tags=tags, cover=cover, source="ncm")
