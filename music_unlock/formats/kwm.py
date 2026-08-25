"""酷我音乐 KWM 解密器（老版格式：1024 字节头 + 32 字节循环异或密钥）。"""
from __future__ import annotations

from pathlib import Path

from ..errors import FormatError
from ..model import DecodeResult, sniff_container
from .base import DecodeOptions, Decoder

HEADER_LEN = 1024
KEY_LEN = 32
MAX_SCAN_CHUNKS = 2048  # 密钥恢复扫描的 32 字节块数上限


def _try_key(data: bytes, key: bytes) -> str:
    """用候选密钥解密文件头若干字节并嗅探容器，返回容器名或 'bin'。

    解密头可能以静音（0x00）开头（如 mp3 前导静音），嗅探前先跳过前导零字节。
    """
    probe = bytes(b ^ key[i & (KEY_LEN - 1)] for i, b in enumerate(data[HEADER_LEN : HEADER_LEN + 4096]))
    stripped = probe.lstrip(b"\x00")[:64]
    return sniff_container(stripped)


class KwmDecoder(Decoder):
    name = "酷我音乐 KWM"
    extensions = frozenset({".kwm"})

    def decode(self, path: Path, opts: DecodeOptions) -> DecodeResult:
        data = path.read_bytes()
        if len(data) < HEADER_LEN + KEY_LEN * 2:
            raise FormatError(f"{path.name}: 文件过短")

        body = data[HEADER_LEN:]
        candidates: list[bytes] = []
        # 候选 1：相邻两个相同的 32 字节块（对应明文全零区，密文即密钥）
        prev = body[:KEY_LEN]
        for i in range(1, min(MAX_SCAN_CHUNKS, len(body) // KEY_LEN)):
            chunk = body[i * KEY_LEN : (i + 1) * KEY_LEN]
            if chunk == prev:
                candidates.append(chunk)
            prev = chunk
        # 候选 2：扫描到的最后一块前后 16 字节交换（老工具的回退方案）
        tail = prev
        candidates.append(tail[KEY_LEN // 2 :] + tail[: KEY_LEN // 2])

        # 用容器嗅探挑选真正能解出音频头的密钥
        chosen: bytes | None = None
        for key in candidates:
            if _try_key(data, key) != "bin":
                chosen = key
                break
        if chosen is None:
            # 再扩大范围：把前 64 块全部当候选试一遍
            for i in range(min(64, len(body) // KEY_LEN)):
                key = body[i * KEY_LEN : (i + 1) * KEY_LEN]
                if _try_key(data, key) != "bin":
                    chosen = key
                    break
        if chosen is None:
            chosen = candidates[0]  # 兜底：仍按第一候选输出

        payload = bytes(
            b ^ chosen[i & (KEY_LEN - 1)] for i, b in enumerate(body)
        )
        # 输出可能以静音（0x00）开头，嗅探前先剥掉前导零
        container = sniff_container(payload.lstrip(b"\x00")[:64])
        return DecodeResult(payload=payload, container=container, source="kwm")
