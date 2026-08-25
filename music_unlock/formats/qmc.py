"""QQ 音乐 QMC 解密器（v1 静态密钥 / v2 内嵌或外部 EKey）。"""
from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from ..ciphers import derive_master_key, make_qmc2_stream, qmc1_transform
from ..errors import FormatError, KeyError_, UnsupportedError
from ..model import DecodeResult, sniff_container
from .base import DecodeOptions, Decoder

# 公开的 v1 静态密钥（128 字节）
V1_STATIC_KEY = bytes(
    [
        0xC3, 0x4A, 0xD6, 0xCA, 0x90, 0x67, 0xF7, 0x52, 0xD8, 0xA1, 0x66, 0x62, 0x9F, 0x5B, 0x09, 0x00,
        0xC3, 0x5E, 0x95, 0x23, 0x9F, 0x13, 0x11, 0x7E, 0xD8, 0x92, 0x3F, 0xBC, 0x90, 0xBB, 0x74, 0x0E,
        0xC3, 0x47, 0x74, 0x3D, 0x90, 0xAA, 0x3F, 0x51, 0xD8, 0xF4, 0x11, 0x84, 0x9F, 0xDE, 0x95, 0x1D,
        0xC3, 0xC6, 0x09, 0xD5, 0x9F, 0xFA, 0x66, 0xF9, 0xD8, 0xF0, 0xF7, 0xA0, 0x90, 0xA1, 0xD6, 0xF3,
        0xC3, 0xF3, 0xD6, 0xA1, 0x90, 0xA0, 0xF7, 0xF0, 0xD8, 0xF9, 0x66, 0xFA, 0x9F, 0xD5, 0x09, 0xC6,
        0xC3, 0x1D, 0x95, 0xDE, 0x9F, 0x84, 0x11, 0xF4, 0xD8, 0x51, 0x3F, 0xAA, 0x90, 0x3D, 0x74, 0x47,
        0xC3, 0x0E, 0x74, 0xBB, 0x90, 0xBC, 0x3F, 0x92, 0xD8, 0x7E, 0x11, 0x13, 0x9F, 0x23, 0x95, 0x5E,
        0xC3, 0x00, 0x09, 0x5B, 0x9F, 0x62, 0x66, 0xA1, 0xD8, 0x52, 0xF7, 0x67, 0x90, 0xCA, 0xD6, 0x4A,
    ]
)

V1_EXTS = {
    ".tkm", ".bkcmp3", ".bkcm4a", ".bkcflac", ".bkcwav", ".bkcape", ".bkcogg", ".bkcwma",
    ".666c6163", ".6d7033", ".6f6767", ".6d3461", ".776176",  # 十六进制扩展名
}
V2_EXTS = {
    ".mflac", ".mflac0", ".mgg", ".mgg0", ".mgg1", ".mggl", ".mmp4",
    ".qmcflac", ".qmcogg", ".qmc0", ".qmc2", ".qmc3", ".qmc4", ".qmc6", ".qmc8",
}
MAX_EKEY_LEN = 0x500
MUSICEX_BLOCK = 0xC0


class Footer:
    """QMC v2 文件尾部的元数据/EKey 包。"""

    __slots__ = ("size", "ekey", "kind", "resource_id", "mid", "media_filename")

    def __init__(self, size: int, ekey: str | None, kind: str, **extra):
        self.size = size
        self.ekey = ekey
        self.kind = kind
        self.resource_id = extra.get("resource_id")
        self.mid = extra.get("mid")
        self.media_filename = extra.get("media_filename")


def _is_base64_text(s: bytes) -> bool:
    for c in s:
        if c not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=":
            return False
    return bool(s)


def _read_utf16le(data: bytes) -> str:
    """ASCII 范围内的 UTF-16LE 字符串读取（遇非 ASCII 或结尾停止）。"""
    out = []
    for i in range(0, len(data) - 1, 2):
        lo, hi = data[i], data[i + 1]
        if lo == 0 and hi == 0:
            break
        if hi == 0 and 0 < lo < 128:
            out.append(chr(lo))
        else:
            break
    return "".join(out)


def parse_footer(tail: bytes) -> Footer | None:
    """解析文件末尾片段（取最后 1024 字节），失败返回 None。"""
    if len(tail) < 8:
        return None

    # Android STag：无 EKey，只有资源元数据（结构: [csv][4B 大端长度][STag]）
    if tail.endswith(b"STag"):
        body = tail[:-4]
        payload, size_bytes = body[:-4], body[-4:]
        payload_len = int.from_bytes(size_bytes, "big")
        if len(payload) < payload_len:
            raise FormatError("STag 长度不一致")
        parts = payload[len(payload) - payload_len :].decode("utf-8", "replace").split(",")
        if len(parts) != 3 or parts[1] != "2" or not parts[0].isdigit():
            raise FormatError("STag 内容非法")
        return Footer(payload_len + 8, None, "STag", resource_id=int(parts[0]), mid=parts[2])

    # Android QTag：含内嵌 EKey（结构: [csv][4B 大端长度][QTag]）
    if tail.endswith(b"QTag"):
        body = tail[:-4]
        payload, size_bytes = body[:-4], body[-4:]
        payload_len = int.from_bytes(size_bytes, "big")
        if len(payload) < payload_len:
            raise FormatError("QTag 长度不一致")
        parts = payload[len(payload) - payload_len :].decode("utf-8", "replace").split(",")
        if len(parts) != 3 or parts[2] != "2" or not parts[1].isdigit():
            raise FormatError("QTag 内容非法")
        ekey = parts[0]
        if not _is_base64_text(ekey.encode("latin-1")):
            raise FormatError("QTag EKey 非法")
        return Footer(payload_len + 8, ekey, "QTag", resource_id=int(parts[1]))

    # PC 新版 MusicEx：无 EKey（需外部密钥库/在线取钥）
    if tail.endswith(b"musicex\x00"):
        payload = tail[:-8]
        if len(payload) < 4:
            raise FormatError("MusicEx 过短")
        data, version_bytes = payload[:-4], payload[-4:]
        if int.from_bytes(version_bytes, "little") != 1:
            raise UnsupportedError("MusicEx 版本不支持")
        if len(data) < 4:
            raise FormatError("MusicEx 过短")
        inner_src, len_bytes = data[:-4], data[-4:]
        payload_len = int.from_bytes(len_bytes, "little")
        if payload_len != MUSICEX_BLOCK:
            raise FormatError(f"MusicEx 长度非法 0x{payload_len:X}")
        inner = inner_src[len(inner_src) - (payload_len - 0x10) :]
        mid = _read_utf16le(inner[12 : 12 + 60])
        media_filename = _read_utf16le(inner[12 + 60 : 12 + 60 + 100])
        return Footer(MUSICEX_BLOCK + 12, None, "MusicEx", mid=mid, media_filename=media_filename)

    # PC 经典 PcV1Legacy：小端长度 + base64 EKey
    payload, size_bytes = tail[:-4], tail[-4:]
    payload_len = int.from_bytes(size_bytes, "little")
    if payload_len > MAX_EKEY_LEN:
        return None  # 大概率不是 QMC 文件
    if len(payload) < payload_len:
        raise FormatError("PcV1Legacy 长度不一致")
    ekey_bytes = payload[len(payload) - payload_len :]
    zero = ekey_bytes.find(b"\x00")
    if zero != -1:
        ekey_bytes = ekey_bytes[:zero]
    if not _is_base64_text(ekey_bytes):
        raise FormatError("PcV1Legacy EKey 非法")
    return Footer(payload_len + 4, ekey_bytes.decode("latin-1"), "PcV1Legacy")


# ---------------------------------------------------------------------------
# 本地密钥库（QQ 音乐安卓端 player_process_db，SQLite）
# ---------------------------------------------------------------------------

_DB_TABLES = (
    ("audio_file_ekey_table", "file_path", "ekey"),
    ("EKeyFileInfo", "filePath", "eKey"),
    ("p2p_cache_info_table", "file_id", "ekey"),
)


def list_ekeys(db_path: Path, find: str | None = None) -> list[tuple[str, str]]:
    """列出密钥库中所有 (文件名, EKey)。"""
    out: list[tuple[str, str]] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, path_col, key_col in _DB_TABLES:
            if table not in tables:
                continue
            for path, ekey in conn.execute(f"SELECT {path_col}, {key_col} FROM {table}"):
                if path is None or ekey is None:
                    continue
                base = Path(str(path)).name
                if find and find not in base and find not in str(path):
                    continue
                out.append((base, str(ekey).strip()))
    finally:
        conn.close()
    return out


def lookup_ekey(db_path: Path, *names: str | None) -> str | None:
    """按文件名/资源 id 在密钥库中查找 EKey。"""
    candidates = [Path(str(n)).name for n in names if n] if names else []
    candidates += [str(n) for n in names if n]
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, path_col, key_col in _DB_TABLES:
            if table not in tables:
                continue
            for path, ekey in conn.execute(f"SELECT {path_col}, {key_col} FROM {table}"):
                if path is None or ekey is None:
                    continue
                path_s = str(path)
                if Path(path_s).name in candidates:
                    return str(ekey).strip()
                for cand in candidates:
                    if len(cand) >= 8 and cand in path_s:
                        return str(ekey).strip()
    finally:
        conn.close()
    return None


# ---------------------------------------------------------------------------
# 解码器
# ---------------------------------------------------------------------------


class QmcDecoder(Decoder):
    name = "QQ 音乐 QMC"
    extensions = frozenset(V1_EXTS | V2_EXTS)

    def decode(self, path: Path, opts: DecodeOptions) -> DecodeResult:
        data = path.read_bytes()
        ext = path.suffix.lower()

        if ext in V1_EXTS:
            payload = qmc1_transform(data, V1_STATIC_KEY)
            return DecodeResult(payload=payload, container=sniff_container(payload[:64]), source="qmc-v1")

        # v2：先解析文件尾包
        footer = None
        try:
            footer = parse_footer(data[-1024:])
        except FormatError:
            footer = None

        if footer is None:
            # 可能是被改名的 v1 文件：用静态密钥试解后嗅探
            head = qmc1_transform(data[:64], V1_STATIC_KEY)
            if sniff_container(head) != "bin":
                payload = qmc1_transform(data, V1_STATIC_KEY)
                return DecodeResult(payload=payload, container=sniff_container(payload[:64]), source="qmc-v1")
            raise FormatError(f"{path.name}: 未找到 QMC 尾包或静态密钥特征")

        ekey = footer.ekey
        if not ekey:
            ekey = opts.ekey
        if not ekey and opts.ekey_db is not None:
            ekey = lookup_ekey(
                opts.ekey_db,
                path.name,
                footer.mid,
                footer.media_filename,
                str(footer.resource_id) if footer.resource_id else None,
            )
        if not ekey:
            raise KeyError_(
                f"{path.name}: {footer.kind} 类型无内嵌密钥。"
                "请用 --ekey 提供 EKey，或用 --ekey-db 提供安卓端 player_process_db；"
                "或将 QQ 音乐客户端降到 19.51 及以下重新下载（密钥内嵌于文件）。"
            )

        master = derive_master_key(ekey.encode("latin-1"))
        stream = make_qmc2_stream(master)
        payload = stream.decrypt(data[: len(data) - footer.size])
        return DecodeResult(payload=payload, container=sniff_container(payload[:64]), source=f"qmc-v2:{footer.kind}")
