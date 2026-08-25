"""合成测试文件生成器：按各格式规范从明文音频构造加密样本。

这些构造器与此前部署的参考工具（ncmdump-py / qmc_decrypt / QKK kugou / kwm_decrypt）
交叉验证过：它们能正确解密本模块生成的样本，因此可作为"已知正确"的编码器。
"""
from __future__ import annotations

import base64
import json
import lzma
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from music_unlock.ciphers import (
    EKEY_V2_KEY1,
    EKEY_V2_KEY2,
    TEA_DELTA,
    TEA_ROUNDS,
    compress_key,
    qmc1_transform,
    tea_cbc_decrypt,
)
from music_unlock.formats.kgm import HEADER_LEN, KGM_MAGIC, MEND_TABLE, _scramble
from music_unlock.formats.qmc import V1_STATIC_KEY

from _fixture_mp3_b64 import CROSS_PLAIN_B64, FIXTURE_MP3_B64

FIXTURE_MP3 = base64.b64decode(FIXTURE_MP3_B64)
CROSS_PLAIN = base64.b64decode(CROSS_PLAIN_B64)  # 参考工具要求 >=4096B 才能探测容器

# ---------------------------------------------------------------------------
# TEA 加密（tweaked CBC），供构造 EKey 使用
# ---------------------------------------------------------------------------


def _tea_mix(value, s, k1, k2):
    return (((value << 4) & 0xFFFFFFFF) + k1) ^ ((value >> 5) + k2) ^ ((s + value) & 0xFFFFFFFF) & 0xFFFFFFFF


def _tea_encrypt_block(block: int, words) -> int:
    hi = (block >> 32) & 0xFFFFFFFF
    lo = block & 0xFFFFFFFF
    s = 0
    for _ in range(TEA_ROUNDS):
        s = (s + TEA_DELTA) & 0xFFFFFFFF
        hi = (hi + _tea_mix(lo, s, words[0], words[1])) & 0xFFFFFFFF
        lo = (lo + _tea_mix(hi, s, words[2], words[3])) & 0xFFFFFFFF
    return (hi << 32) | lo


def tea_cbc_encrypt(plaintext: bytes, key16: bytes, salt: bytes) -> bytes:
    words = struct.unpack(">IIII", key16)
    out_len = 10 + len(plaintext)
    pad_len = (8 - (out_len & 7)) & 7
    header_len = 1 + pad_len + 2
    out_len += pad_len

    header = bytearray(16)
    header[:header_len] = salt[:header_len]
    header[0] = (header[0] & ~7) | pad_len
    copy_len = min(16 - header_len, len(plaintext))
    header[header_len : header_len + copy_len] = plaintext[:copy_len]
    rest = plaintext[copy_len:]

    iv1 = 0
    iv2 = 0
    out = bytearray(out_len)

    def round_enc(block: bytes) -> bytes:
        nonlocal iv1, iv2
        b = int.from_bytes(block, "big")
        iv2_next = (b ^ iv1) & 0xFFFFFFFFFFFFFFFF
        c = (_tea_encrypt_block(iv2_next, words) ^ iv2) & 0xFFFFFFFFFFFFFFFF
        iv1 = c
        iv2 = iv2_next
        return c.to_bytes(8, "big")

    out[0:8] = round_enc(bytes(header[0:8]))
    out[8:16] = round_enc(bytes(header[8:16]))
    pos = 16
    while len(rest) >= 8:
        out[pos : pos + 8] = round_enc(rest[:8])
        rest = rest[8:]
        pos += 8
    if rest:
        out[pos : pos + 8] = round_enc(rest + b"\x00" * (8 - len(rest)))
    return bytes(out[:out_len])


def _simple_key() -> bytes:
    import math

    def f32(x):
        return struct.unpack("f", struct.pack("f", x))[0]

    out = bytearray()
    for i in range(8):
        value = abs(math.tan(f32(106.0 + f32(i * f32(0.1)))))
        out.append(max(0, min(int(f32(f32(value) * 100.0)), 255)))
    return bytes(out)


def make_ekey_v1(master_key: bytes, salt: bytes = b"\x00" * 10) -> str:
    """构造 PcV1Legacy 风格 EKey（无 V2 前缀）。"""
    header = master_key[:8]
    tea_key = bytearray()
    for sk, hk in zip(_simple_key(), header):
        tea_key += bytes((sk, hk))
    cipher = tea_cbc_encrypt(master_key[8:], bytes(tea_key), salt)
    return base64.b64encode(header + cipher).decode()


def make_ekey_v2(master_key: bytes, salt: bytes = b"\x00" * 10) -> str:
    """构造双层 EKey：文件里存 base64 前缀 + base64(KEY1(KEY2(inner)))。"""
    import base64

    inner = make_ekey_v1(master_key, salt)
    layer = tea_cbc_encrypt(inner.encode(), EKEY_V2_KEY2, salt)  # 先 KEY2
    layer = tea_cbc_encrypt(layer, EKEY_V2_KEY1, salt)           # 再 KEY1
    prefix = base64.b64encode(b"QQMusic EncV2,Key:").decode()
    return prefix + base64.b64encode(layer).decode()


# ---------------------------------------------------------------------------
# 各格式构造器
# ---------------------------------------------------------------------------

NCM_CORE_KEY = b"hzHRAmso5kInbaxW"
NCM_META_KEY = b"#14ljk_!\\]&0U<'("


def build_ncm(plain: bytes, rc4_key: bytes, meta: dict, cover: bytes | None = None) -> bytes:
    key_plain = pad(b"neteasecloudmusic" + rc4_key, 16)
    key_blob = bytes(b ^ 0x64 for b in AES.new(NCM_CORE_KEY, AES.MODE_ECB).encrypt(key_plain))
    meta_json = json.dumps(meta, separators=(",", ":")).encode()
    meta_enc = AES.new(NCM_META_KEY, AES.MODE_ECB).encrypt(pad(b"music:" + meta_json, 16))
    meta_blob = bytes(b ^ 0x63 for b in (b"163 key(Don't modify):" + base64.b64encode(meta_enc)))
    if cover is None:
        image = struct.pack("<II", 0, 0)  # 真实 NCM 始终带 8 字节封面字段
    else:
        image = struct.pack("<II", len(cover), len(cover)) + cover

    # NCM 音频流加密（与解密互逆）
    sbox = bytearray(range(256))
    j = 0
    for i in range(256):
        j = (j + sbox[i] + rc4_key[i % len(rc4_key)]) & 0xFF
        sbox[i], sbox[j] = sbox[j], sbox[i]
    box = bytes(sbox[(sbox[i] + sbox[(i + sbox[i]) & 0xFF]) & 0xFF] for i in range(256))
    reps = (len(plain) + 256) // 256 + 1
    stream = (box * reps)[1 : 1 + len(plain)]
    audio = (int.from_bytes(plain, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(plain), "little")

    out = bytearray(b"CTENFDAM\x00\x00")
    out += struct.pack("<I", len(key_blob)) + key_blob
    out += struct.pack("<I", len(meta_blob)) + meta_blob
    out += b"\x00" * 5
    out += image
    out += audio
    return bytes(out)


def build_qmc_v1(plain: bytes) -> bytes:
    return qmc1_transform(plain, V1_STATIC_KEY)


def build_qmc_v2(plain: bytes, master_key: bytes, ekey: str, tag: bytes = b"QTag", resource_id: int = 1) -> bytes:
    from music_unlock.ciphers import make_qmc2_stream

    enc = make_qmc2_stream(master_key).decrypt(plain)  # 流密码可逆
    footer = f"{ekey},{resource_id},2".encode() + struct.pack(">I", len(f"{ekey},{resource_id},2"))
    return enc + footer + tag


def build_stag(plain: bytes, master_key: bytes, resource_id: int = 123, media_mid: str = "003TestMid") -> bytes:
    from music_unlock.ciphers import make_qmc2_stream

    enc = make_qmc2_stream(master_key).decrypt(plain)
    csv = f"{resource_id},2,{media_mid}".encode()
    return enc + csv + struct.pack(">I", len(csv)) + b"STag"


def build_kgm(plain: bytes, pub_key: bytes, crypto_test: bytes = bytes(range(16))) -> bytes:
    own_key = crypto_test + b"\x00"
    mend = len(MEND_TABLE)
    own_inv = []
    for k in own_key:
        table = [0] * 256
        for y in range(256):
            low = y & 0x0F
            high = (y >> 4) & 0x0F
            table[y] = (((high ^ low) << 4) | low) ^ k
        own_inv.append(table)
    enc = bytearray(len(plain))
    for i, b in enumerate(plain):
        pub_value = pub_key[i >> 4]
        masked = b ^ _scramble(pub_value ^ MEND_TABLE[i % mend])
        enc[i] = own_inv[i % 17][masked]
    header = bytearray(HEADER_LEN)
    header[:16] = KGM_MAGIC
    struct.pack_into("<III", header, 0x10, HEADER_LEN, 3, 1)
    header[0x1C:0x2C] = crypto_test
    return bytes(header) + bytes(enc)


def build_kwm(plain: bytes, key: bytes = bytes(range(1, 33))) -> bytes:
    head = b"yeelion-kuwo" + b"\x00" * (1024 - len(b"yeelion-kuwo"))
    enc = bytes(b ^ key[i & 31] for i, b in enumerate(plain))
    return head + enc


def load_kgm_pub_key() -> bytes:
    return lzma.decompress(Path(__file__).resolve().parents[1].joinpath("assets", "kugou_key.xz").read_bytes())
