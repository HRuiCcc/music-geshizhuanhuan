"""交叉验证：用已部署的参考工具解密本项目的合成样本，逐字节比对。

参考工具：
  - NCM    -> ncmdump-py（QQKWKG venv 内，用底层 dump 不嵌标签）
  - QMC    -> qqmusic-decrypt/qmc_decrypt.py（纯 Python）
  - KGM    -> QQKWKG-TriMusicDecrypt（kugou 子命令）
  - KWM    -> kwmusic-kwm-decrypt/sources/kwm_decrypt（C 编译产物）

运行: .venv/bin/python tests/crosscheck.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT.parent
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
    make_ekey_v2,
)

QKK = WS / "QQKWKG-TriMusicDecrypt"
QMC_TOOL = WS / "qqmusic-decrypt" / "qmc_decrypt.py"
KWM_TOOL = WS / "kwmusic-kwm-decrypt" / "sources" / "kwm_decrypt"

results: list[tuple[str, bool]] = []


def check(name: str, plain: bytes, got: bytes) -> None:
    ok = got == plain
    results.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: 参考输出 {len(got)}B（明文 {len(plain)}B）")
    if not ok:
        for i, (a, b) in enumerate(zip(got, plain)):
            if a != b:
                print(f"    首个差异 @{i}: 0x{a:02x} vs 0x{b:02x}")
                break


with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)

    # ---- NCM：用 ncmdump-py 内部三步解密拿原始字节流 ----
    ncm = tmp / "t.ncm"
    ncm.write_bytes(build_ncm(CROSS_PLAIN, b"0123456789abcdef", {"format": "mp3", "musicName": "x"}))
    ncm_out = tmp / "ncm_out.mp3"
    proc = subprocess.run(
        [str(QKK / ".venv" / "bin" / "python"), "-c",
         "from ncmdump import NeteaseCloudMusicFile; import pathlib;"
         f"f=NeteaseCloudMusicFile('{ncm}');"
         "f._decrypt_rc4_key(); f._decrypt_metadata(); f._decrypt_music_data();"
         f"pathlib.Path('{ncm_out}').write_bytes(f._music_data)"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print("[FAIL] NCM: 参考工具报错", proc.stderr[-200:])
        results.append(("NCM", False))
    else:
        check("NCM", CROSS_PLAIN, ncm_out.read_bytes())

    # ---- QMC v1 ----
    q1 = tmp / "t.bkcmp3"
    q1.write_bytes(build_qmc_v1(CROSS_PLAIN))
    subprocess.run([sys.executable, str(QMC_TOOL), str(q1), "-o", str(tmp / "q1out")], capture_output=True)
    check("QMC v1", CROSS_PLAIN, (tmp / "q1out" / "t.mp3").read_bytes())

    # ---- QMC v2 Map（QTag）----
    master_map = bytes(range(24))
    q2 = tmp / "t.mflac"
    q2.write_bytes(build_qmc_v2(CROSS_PLAIN, master_map, make_ekey_v1(master_map), tag=b"QTag"))
    subprocess.run([sys.executable, str(QMC_TOOL), str(q2), "-o", str(tmp / "q2out")], capture_output=True)
    check("QMC v2 Map/QTag", CROSS_PLAIN, (tmp / "q2out" / "t.mp3").read_bytes())

    # ---- QMC v2 RC4 ----
    master_rc4 = bytes((i * 7 + 3) & 0xFF for i in range(512))
    q3 = tmp / "t.mgg"
    q3.write_bytes(build_qmc_v2(CROSS_PLAIN, master_rc4, make_ekey_v2(master_rc4), tag=b"QTag"))
    subprocess.run([sys.executable, str(QMC_TOOL), str(q3), "-o", str(tmp / "q3out")], capture_output=True)
    check("QMC v2 RC4", CROSS_PLAIN, (tmp / "q3out" / "t.mp3").read_bytes())

    # ---- KGM v3 ----
    kgm = tmp / "t.kgm"
    kgm.write_bytes(build_kgm(CROSS_PLAIN, load_kgm_pub_key()))
    subprocess.run(
        [str(QKK / "run.sh"), "kugou", "decrypt", "--input", str(kgm),
         "--output", str(tmp / "kgmout"), "--no-transcode", "--no-embed-cover"],
        capture_output=True,
    )
    kgm_outputs = list((tmp / "kgmout").glob("*.mp3"))
    check("KGM v3", CROSS_PLAIN, kgm_outputs[0].read_bytes() if kgm_outputs else b"")

    # ---- KWM ----
    kwm = tmp / "t.kwm"
    kwm.write_bytes(build_kwm(b"\x00" * 64 + CROSS_PLAIN))
    kwm_out = tmp / "kwm_out.mp3"
    subprocess.run([str(KWM_TOOL), str(kwm), str(kwm_out)], capture_output=True)
    check("KWM", b"\x00" * 64 + CROSS_PLAIN, kwm_out.read_bytes())

print()
print(f"交叉验证: {sum(1 for _, ok in results if ok)}/{len(results)} 通过")
sys.exit(0 if all(ok for _, ok in results) else 1)
