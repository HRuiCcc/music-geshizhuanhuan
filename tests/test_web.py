"""网页版 API 端到端测试（启动本地服务，上传合成样本验证全链路）。"""
from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from builders import (  # noqa: E402
    CROSS_PLAIN,
    build_kgm,
    build_kwm,
    build_ncm,
    build_qmc_v1,
    build_qmc_v2,
    load_kgm_pub_key,
    make_ekey_v1,
)

PORT = 8687
BASE = f"http://127.0.0.1:{PORT}"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="module")
def server():
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "web" / "server.py"), "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{BASE}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("服务启动失败")
    yield
    proc.terminate()
    proc.wait(timeout=10)


def upload(name: str, data: bytes, fmt: str = "", embed: str = "0", ekey: str = ""):
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode(),
        data,
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="format"\r\n\r\n{fmt}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="embed_cover"\r\n\r\n{embed}\r\n'.encode(),
    ]
    if ekey:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="ekey"\r\n\r\n{ekey}\r\n'.encode()
        )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{BASE}/api/decode",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def get(url: str) -> bytes:
    return urllib.request.urlopen(url, timeout=120).read()


def test_health_and_index(server):
    assert json.loads(get(f"{BASE}/api/health"))["ok"] is True
    assert b"music-geshizhuanhuan" in get(f"{BASE}/")


def test_all_formats_roundtrip(server):
    master = bytes(range(24))
    cases = [
        ("plain.ncm", build_ncm(CROSS_PLAIN, b"0123456789abcdef", {"format": "mp3"}), CROSS_PLAIN),
        ("song.tkm", build_qmc_v1(CROSS_PLAIN), CROSS_PLAIN),
        ("song.mflac", build_qmc_v2(CROSS_PLAIN, master, make_ekey_v1(master), tag=b"QTag"), CROSS_PLAIN),
        ("song.kgm", build_kgm(CROSS_PLAIN, load_kgm_pub_key()), CROSS_PLAIN),
        ("song.kwm", build_kwm(b"\x00" * 64 + CROSS_PLAIN), b"\x00" * 64 + CROSS_PLAIN),
    ]
    ids = []
    for name, data, expect in cases:
        resp = upload(name, data)
        assert resp["ok"], f"{name}: {resp}"
        dl = get(f"{BASE}/api/download/{resp['result']['id']}")
        assert dl == expect
        ids.append(resp["result"]["id"])

    zf = zipfile.ZipFile(io.BytesIO(get(f"{BASE}/api/zip?ids={','.join(ids)}")))
    assert len(zf.namelist()) == len(cases)


def test_cover_tags_and_transcode(server):
    meta = {"format": "mp3", "musicName": "网页测试", "artist": [["歌手A", 1]], "album": "专辑A"}
    resp = upload("cover.ncm", build_ncm(CROSS_PLAIN, b"0123456789abcdef", meta, cover=PNG), embed="1")
    assert resp["ok"]
    result = resp["result"]
    assert result["has_cover"] is True
    assert result["tags"]["title"] == "网页测试"
    assert get(f"{BASE}/api/cover/{result['id']}") == PNG

    resp2 = upload("trans.ncm", build_ncm(CROSS_PLAIN, b"0123456789abcdef", {"format": "mp3"}), fmt="flac")
    assert resp2["ok"]
    assert resp2["result"]["output_name"].endswith(".flac")
    assert get(f"{BASE}/api/download/{resp2['result']['id']}")[:4] == b"fLaC"


def test_invalid_file_rejected(server):
    resp = upload("bad.ncm", b"NOT A REAL NCM FILE" * 10)
    assert not resp["ok"]
    assert resp.get("error")
