"""密码学基础件：XOR 流变换、QMC v1/v2 流密码、Tencent TEA、NCM 密钥流。

全部为公开格式规范的自研实现，仅依赖标准库。
"""
from __future__ import annotations

import math
import struct
from typing import Callable

# ---------------------------------------------------------------------------
# 通用 XOR 工具
# ---------------------------------------------------------------------------

KEY128 = 128
BOUNDARY = 0x7FFF  # QMC v1 变换的偏移边界


def xor_repeat(data: bytearray, key: bytes, phase: int = 0, *, start: int = 0, length: int | None = None) -> None:
    """data[start:start+length] 与按 key 循环的密钥流异或（就地）。"""
    end = len(data) if length is None else start + length
    klen = len(key)
    for i in range(start, end):
        data[i] ^= key[(phase + i - start) % klen]


def xor_key_stream(data: bytes, key: bytes) -> bytes:
    """整段数据与循环密钥流异或，返回新 bytes。"""
    reps = (len(data) + len(key) - 1) // len(key)
    stream = (key * reps)[: len(data)]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(
        len(data), "little"
    )


# ---------------------------------------------------------------------------
# QMC v1 静态变换（QQ 音乐老格式 .tkm / .bkc* / 十六进制扩展名）
# ---------------------------------------------------------------------------


def qmc1_transform(data: bytes, key: bytes, offset_start: int = 0) -> bytes:
    """按公开的 qmc1 规则变换整段数据。

    规则：绝对偏移 <= 0x7FFF 时密钥索引为 offset % 128；
    超过 0x7FFF 时先把 offset 对 0x7FFF 取模再 % 128。
    """
    out = bytearray(data)
    pos = offset_start
    i = 0
    total = len(out)
    while i < total:
        if pos <= BOUNDARY:
            take = min(BOUNDARY + 1 - pos, total - i)
            phase = pos % KEY128
        else:
            r = pos % BOUNDARY
            take = min(BOUNDARY - r, total - i)
            phase = r % KEY128
        base = key if phase == 0 else key[phase:] + key[:phase]
        out[i : i + take] = xor_key_stream(bytes(out[i : i + take]), base)
        i += take
        pos += take
    return bytes(out)


# ---------------------------------------------------------------------------
# Tencent TEA（16 轮，带 "tweaked CBC" 链式模式）
# ---------------------------------------------------------------------------

TEA_DELTA = 0x9E3779B9
TEA_ROUNDS = 16
TEA_SALT_LEN = 2
TEA_ZERO_LEN = 7


def _tea_mix(value: int, s: int, k1: int, k2: int) -> int:
    left = ((value << 4) & 0xFFFFFFFF) + k1
    right = (value >> 5) + k2
    mid = (s + value) & 0xFFFFFFFF
    return (left ^ mid ^ right) & 0xFFFFFFFF


def tea_decrypt_block(block: int, key_words: tuple[int, int, int, int]) -> int:
    """解密一个 64 位大端块。"""
    hi = (block >> 32) & 0xFFFFFFFF
    lo = block & 0xFFFFFFFF
    s = (TEA_DELTA * TEA_ROUNDS) & 0xFFFFFFFF
    for _ in range(TEA_ROUNDS):
        lo = (lo - _tea_mix(hi, s, key_words[2], key_words[3])) & 0xFFFFFFFF
        hi = (hi - _tea_mix(lo, s, key_words[0], key_words[1])) & 0xFFFFFFFF
        s = (s - TEA_DELTA) & 0xFFFFFFFF
    return (hi << 32) | lo


def tea_cbc_decrypt(ciphertext: bytes, key16: bytes) -> bytes:
    """Tencent TEA 变种 CBC 解密，剥掉头部与尾部填充后返回明文。"""
    words = struct.unpack(">IIII", key16)
    if len(ciphertext) % 8 != 0 or len(ciphertext) < 10:
        raise ValueError(f"TEA: 非法密文长度 {len(ciphertext)}")
    iv_prev = 0
    iv_cur = 0
    plain = bytearray()
    for i in range(0, len(ciphertext), 8):
        block = int.from_bytes(ciphertext[i : i + 8], "big")
        mixed = (block ^ iv_cur) & 0xFFFFFFFFFFFFFFFF
        next_iv = tea_decrypt_block(mixed, words)
        chunk = (next_iv ^ iv_prev) & 0xFFFFFFFFFFFFFFFF
        plain += chunk.to_bytes(8, "big")
        iv_prev = block
        iv_cur = next_iv
    pad = plain[0] & 0b111
    body_start = 1 + pad + TEA_SALT_LEN
    body_end = len(ciphertext) - TEA_ZERO_LEN
    if any(plain[body_end:]):
        raise ValueError("TEA: 尾部校验失败")
    return bytes(plain[body_start:body_end])


# ---------------------------------------------------------------------------
# QMC v2 EKey 派生（TEA 双版本）
# ---------------------------------------------------------------------------

EKEY_V2_PREFIX = __import__("base64").b64encode(b"QQMusic EncV2,Key:")  # 文件里存的是 base64 形式
EKEY_V2_KEY1 = bytes(
    [0x33, 0x38, 0x36, 0x5A, 0x4A, 0x59, 0x21, 0x40, 0x23, 0x2A, 0x24, 0x25, 0x5E, 0x26, 0x29, 0x28]
)
EKEY_V2_KEY2 = bytes(
    [0x2A, 0x2A, 0x23, 0x21, 0x28, 0x23, 0x24, 0x25, 0x26, 0x5E, 0x61, 0x31, 0x63, 0x5A, 0x2C, 0x54]
)


def _f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def simple_key_8() -> bytes:
    """EKey v1 使用的 8 字节固定表（f32 语义）。"""
    out = bytearray()
    for i in range(8):
        value = abs(math.tan(_f32(106.0 + _f32(i * _f32(0.1)))))
        out.append(max(0, min(int(_f32(_f32(value) * 100.0)), 255)))
    return bytes(out)


_SIMPLE_KEY = simple_key_8()


def _b64(s: bytes) -> bool:
    from base64 import b64decode

    try:
        b64decode(s, validate=True)
        return True
    except Exception:
        return False


def derive_master_key(ekey: bytes) -> bytes:
    """从 EKey 字符串派生 QMC v2 主密钥。"""
    import base64

    if ekey.startswith(EKEY_V2_PREFIX):
        payload = base64.b64decode(ekey[len(EKEY_V2_PREFIX) :])
        payload = tea_cbc_decrypt(payload, EKEY_V2_KEY1)
        payload = tea_cbc_decrypt(payload, EKEY_V2_KEY2)
        zero = payload.find(b"\x00")
        return _ekey_v1(payload if zero == -1 else payload[:zero])
    return _ekey_v1(ekey)


def _ekey_v1(ekey: bytes) -> bytes:
    import base64

    decoded = base64.b64decode(ekey)
    if len(decoded) < 8:
        raise ValueError("EKey v1: 解码后不足 8 字节")
    header, cipher = decoded[:8], decoded[8:]
    tea_key = bytearray()
    for sk, hk in zip(_SIMPLE_KEY, header):
        tea_key += bytes((sk, hk))
    return header + tea_cbc_decrypt(cipher, bytes(tea_key))


# ---------------------------------------------------------------------------
# QMC v2 流密码（Map / RC4）
# ---------------------------------------------------------------------------

MAP_LEN = 128
MAP_MAGIC = 71214
RC4_FIRST_SEGMENT = 0x80
RC4_SEGMENT = 0x1400
RC4_STREAM_CACHE = RC4_SEGMENT + 512


def compress_key(long_key: bytes) -> bytes:
    """把长密钥压缩为 128 字节的 Map 密钥。"""
    n = len(long_key)
    if n == 0:
        raise ValueError("Map 密钥为空")
    out = bytearray(MAP_LEN)
    for i in range(MAP_LEN):
        idx = (i * i + MAP_MAGIC) % n
        shift = (idx + 4) % 8
        out[i] = ((long_key[idx] << shift) | (long_key[idx] >> shift)) & 0xFF
    return bytes(out)


def qmc2_hash(key: bytes) -> float:
    """长密钥的散列（浮点语义，与公开实现一致）。"""
    h = 1
    for value in key:
        if value == 0:
            continue
        nxt = (h * value) & 0xFFFFFFFF
        if nxt == 0 or nxt <= h:
            break
        h = nxt
    return float(h)


def segment_key(seg_id: int, seed: int, h: float) -> int:
    """RC4 分段密钥推导。"""
    if seed == 0:
        return 0
    denom = ((seg_id + 1) * seed) & 0xFFFFFFFFFFFFFFFF
    return int(h / float(denom) * 100.0)


class MapStream:
    """短主密钥（<=300 字节）的 Map 流密码。"""

    def __init__(self, master_key: bytes):
        self.key = compress_key(master_key)

    def decrypt(self, data: bytes, offset: int = 0) -> bytes:
        return qmc1_transform(data, self.key, offset)


class Rc4Stream:
    """长主密钥（>300 字节）的分段 RC4 流密码。"""

    def __init__(self, master_key: bytes):
        self.key = bytes(master_key)
        n = len(self.key)
        state = [i & 0xFF for i in range(n)]
        j = 0
        for i in range(n):
            j = (j + state[i] + self.key[i % n]) % n
            state[i], state[j] = state[j], state[i]
        self.state = state
        self.n = n
        self._i = 0
        self._j = 0
        self.hash = qmc2_hash(self.key)
        self.key_stream = bytes(self._next_byte() for _ in range(RC4_STREAM_CACHE))

    def _next_byte(self) -> int:
        n = self.n
        self._i = (self._i + 1) % n
        self._j = (self._j + self.state[self._i]) % n
        self.state[self._i], self.state[self._j] = self.state[self._j], self.state[self._i]
        return self.state[(self.state[self._i] + self.state[self._j]) % n]

    def decrypt(self, data: bytes, offset: int = 0) -> bytes:
        out = bytearray(data)
        n = len(self.key)
        total = len(out)
        pos = offset
        start = 0
        # 首段（offset < 0x80）逐字节用段密钥打表
        if pos < RC4_FIRST_SEGMENT:
            take = min(RC4_FIRST_SEGMENT - pos, total)
            for j in range(take):
                p = pos + j
                out[j] ^= self.key[segment_key(p, self.key[p % n], self.hash) % n]
            start += take
            pos += take
        # 其余按 0x1400 分段，用预生成的密钥流切片
        while start < total:
            seg_id = pos // RC4_SEGMENT
            block_off = pos % RC4_SEGMENT
            seed = self.key[seg_id % n]
            skip = segment_key(seg_id, seed, self.hash) & 0x1FF
            take = min(RC4_SEGMENT - block_off, total - start)
            stream = self.key_stream[skip + block_off : skip + block_off + take]
            out[start : start + take] = xor_key_stream(bytes(out[start : start + take]), stream)
            start += take
            pos += take
        return bytes(out)


def make_qmc2_stream(master_key: bytes):
    """按主密钥长度选择 Map 或 RC4 流密码。"""
    if not master_key:
        raise ValueError("主密钥为空")
    if len(master_key) <= 300:
        return MapStream(master_key)
    return Rc4Stream(master_key)


# ---------------------------------------------------------------------------
# NCM（网易云）密钥流：RC4 KSA + box 派生
# ---------------------------------------------------------------------------


def ncm_stream_bytes(key: bytes) -> bytes:
    """生成 256 字节的 NCM box 密钥流（音频字节 i 用 box[(i+1) % 256]）。"""
    sbox = bytearray(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + sbox[i] + key[i % klen]) & 0xFF
        sbox[i], sbox[j] = sbox[j], sbox[i]
    box = bytearray(256)
    for i in range(256):
        box[i] = sbox[(sbox[i] + sbox[(i + sbox[i]) & 0xFF]) & 0xFF]
    return bytes(box)


def ncm_decrypt_audio(data: bytes, box: bytes) -> bytes:
    """NCM 音频流解密（跳过 box[0] 的经典语义）。"""
    reps = (len(data) + 256) // 256 + 1
    stream = (box * reps)[1 : 1 + len(data)]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(
        len(data), "little"
    )


XorFunc = Callable[[bytes, int], bytes]
