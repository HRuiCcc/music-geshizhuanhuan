"""四个格式解码器的往返测试（合成样本）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_unlock.errors import KeyError_, UnsupportedError
from music_unlock.formats.base import DecodeOptions
from music_unlock.formats.kgm import KgmDecoder
from music_unlock.formats.kwm import KwmDecoder
from music_unlock.formats.ncm import NcmDecoder
from music_unlock.formats.qmc import QmcDecoder
from music_unlock.model import sniff_container

from builders import (
    FIXTURE_MP3,
    build_kgm,
    build_kwm,
    build_ncm,
    build_qmc_v1,
    build_qmc_v2,
    build_stag,
    load_kgm_pub_key,
    make_ekey_v1,
    make_ekey_v2,
)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------------------
# NCM
# ---------------------------------------------------------------------------


def test_ncm_roundtrip(tmp_path):
    meta = {"format": "mp3", "musicId": 1, "musicName": "测试歌", "artist": [["测试歌手", 1]], "album": "测试专辑"}
    blob = build_ncm(FIXTURE_MP3, b"0123456789abcdef", meta)
    result = NcmDecoder().decode(_write(tmp_path, "t.ncm", blob), DecodeOptions())
    assert result.payload == FIXTURE_MP3
    assert result.container == "mp3"
    assert result.tags == {"title": "测试歌", "artist": "测试歌手", "album": "测试专辑"}


def test_ncm_rejects_garbage(tmp_path):
    with pytest.raises(Exception):
        NcmDecoder().decode(_write(tmp_path, "x.ncm", b"NOTANCMFILE"), DecodeOptions())


# ---------------------------------------------------------------------------
# QMC v1
# ---------------------------------------------------------------------------


def test_qmc_v1_roundtrip(tmp_path):
    blob = build_qmc_v1(FIXTURE_MP3)
    result = QmcDecoder().decode(_write(tmp_path, "t.bkcmp3", blob), DecodeOptions())
    assert result.payload == FIXTURE_MP3
    assert result.container == "mp3"


def test_qmc_v1_large_boundary(tmp_path):
    """超过 0x7FFF 边界的数据也要正确还原。"""
    plain = FIXTURE_MP3 + b"\x00" * (0x9000 - len(FIXTURE_MP3)) + b"tail-marker"
    blob = build_qmc_v1(plain)
    result = QmcDecoder().decode(_write(tmp_path, "t.tkm", blob), DecodeOptions())
    assert result.payload == plain


# ---------------------------------------------------------------------------
# QMC v2（Map / RC4 / 无内嵌密钥）
# ---------------------------------------------------------------------------


def test_qmc_v2_map_qtag(tmp_path):
    master = bytes(range(24))
    ekey = make_ekey_v1(master)
    blob = build_qmc_v2(FIXTURE_MP3, master, ekey, tag=b"QTag")
    result = QmcDecoder().decode(_write(tmp_path, "t.mflac", blob), DecodeOptions())
    assert result.payload == FIXTURE_MP3


def test_qmc_v2_map_pcv1legacy(tmp_path):
    import struct

    from music_unlock.ciphers import make_qmc2_stream

    master = b"map-key-0123456789abcdef"
    ekey = make_ekey_v1(master)
    enc = make_qmc2_stream(master).decrypt(FIXTURE_MP3)
    blob = enc + ekey.encode() + struct.pack("<I", len(ekey.encode()))  # 无 QTag，经典 PC 尾部
    result = QmcDecoder().decode(_write(tmp_path, "t.mgg", blob), DecodeOptions())
    assert result.payload == FIXTURE_MP3


def test_qmc_v2_rc4(tmp_path):
    master = bytes((i * 7 + 3) & 0xFF for i in range(512))
    ekey = make_ekey_v2(master)
    blob = build_qmc_v2(FIXTURE_MP3, master, ekey, tag=b"QTag")
    result = QmcDecoder().decode(_write(tmp_path, "t.mflac", blob), DecodeOptions())
    assert result.payload == FIXTURE_MP3


def test_qmc_v2_stag_needs_external_key(tmp_path):
    master = bytes(range(24))
    blob = build_stag(FIXTURE_MP3, master)
    path = _write(tmp_path, "t.mflac", blob)
    with pytest.raises(KeyError_):
        QmcDecoder().decode(path, DecodeOptions())
    # 提供 --ekey 后应成功
    result = QmcDecoder().decode(path, DecodeOptions(ekey=make_ekey_v1(master)))
    assert result.payload == FIXTURE_MP3


# ---------------------------------------------------------------------------
# KGM v3
# ---------------------------------------------------------------------------

PUB_KEY = load_kgm_pub_key()


def test_kgm_roundtrip(tmp_path):
    blob = build_kgm(FIXTURE_MP3, PUB_KEY)
    result = KgmDecoder().decode(_write(tmp_path, "t.kgm", blob), DecodeOptions())
    assert result.payload == FIXTURE_MP3
    assert result.container == "mp3"


def test_kgm_big_file(tmp_path):
    plain = FIXTURE_MP3 + b"\xab" * 200000
    blob = build_kgm(plain, PUB_KEY)
    result = KgmDecoder().decode(_write(tmp_path, "t.kgma", blob), DecodeOptions())
    assert result.payload == plain


def test_kgm_rejects_garbage(tmp_path):
    with pytest.raises(Exception):
        KgmDecoder().decode(_write(tmp_path, "x.kgm", b"garbage" * 300), DecodeOptions())


# ---------------------------------------------------------------------------
# KWM
# ---------------------------------------------------------------------------


def test_kwm_roundtrip(tmp_path):
    blob = build_kwm(b"\x00" * 64 + FIXTURE_MP3)
    result = KwmDecoder().decode(_write(tmp_path, "t.kwm", blob), DecodeOptions())
    assert result.payload == b"\x00" * 64 + FIXTURE_MP3
    assert result.container == "mp3"


def test_kwm_rejects_short(tmp_path):
    with pytest.raises(Exception):
        KwmDecoder().decode(_write(tmp_path, "x.kwm", b"short"), DecodeOptions())


# ---------------------------------------------------------------------------
# 容器嗅探
# ---------------------------------------------------------------------------


def test_sniff_container():
    assert sniff_container(b"fLaC\x00\x00\x00\x22") == "flac"
    assert sniff_container(b"ID3\x04\x00\x00\x00") == "mp3"
    assert sniff_container(b"OggS\x00\x02") == "ogg"
    assert sniff_container(b"RIFF\x00\x00\x00\x00WAVE") == "wav"
    assert sniff_container(b"\x00\x00\x00\x18ftypM4A ") == "m4a"
    assert sniff_container(b"\xde\xad\xbe\xef") == "bin"
