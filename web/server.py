"""music-unlock 网页版服务端（仅监听本机 127.0.0.1）。

API:
  GET  /api/health                健康检查
  POST /api/decode                上传并解密（multipart: file + format + embed_cover + ekey）
  GET  /api/cover/<id>            封面预览
  GET  /api/download/<id>         下载单个结果
  GET  /api/zip?ids=a,b,c         批量打包下载
  POST /api/clear                 清空结果缓存
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from flask import Flask, jsonify, request, send_file

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_unlock.batch import process_one, BatchOptions, DecodeOptions  # noqa: E402
from music_unlock.formats import supported_extensions  # noqa: E402
from music_unlock.transcode import TARGETS  # noqa: E402

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 单文件 1GB

STORE_DIR = Path(tempfile.gettempdir()) / "music-unlock-web"
STORE_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_results: dict[str, dict] = {}


def _store_put(meta: dict) -> str:
    rid = uuid.uuid4().hex[:12]
    with _lock:
        _results[rid] = meta
    return rid


def _store_get(rid: str) -> dict | None:
    with _lock:
        return _results.get(rid)


def _cleanup_expired(ttl_sec: int = 24 * 3600) -> None:
    cutoff = time.time() - ttl_sec
    with _lock:
        stale = [k for k, v in _results.items() if v.get("created", 0) < cutoff]
        for k in stale:
            path = _results.pop(k).get("path")
            if path:
                Path(path).unlink(missing_ok=True)


@app.get("/")
def index():
    return send_file(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "formats": sorted(supported_extensions()), "targets": list(TARGETS)})


@app.post("/api/decode")
def decode():
    _cleanup_expired()
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "缺少文件"}), 400

    format_target = (request.form.get("format") or "").strip() or None
    if format_target not in TARGETS:
        format_target = None
    embed_cover = request.form.get("embed_cover", "1") != "0"
    ekey = (request.form.get("ekey") or "").strip() or None

    original_name = Path(upload.filename).name
    safe_stem = "".join(c if c not in '\\/:*?"<>|' else "_" for c in Path(original_name).stem) or "audio"

    work = STORE_DIR / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)
    src = work / f"in{Path(original_name).suffix}"
    upload.save(src)

    opts = BatchOptions(
        output_dir=work,
        target=format_target,
        embed_cover=embed_cover,
        force=True,
        decode=DecodeOptions(ekey=ekey),
    )
    outcome = process_one(src, opts)

    if outcome.status != "ok" or outcome.output is None:
        shutil.rmtree(work, ignore_errors=True)
        return jsonify({"ok": False, "error": outcome.note or "解码失败", "name": original_name})

    out_path = outcome.output
    # 解码/转码后的容器（从输出扩展名推断）
    container = out_path.suffix.lstrip(".") or "bin"
    rid = _store_put(
        {
            "id": "",
            "path": str(out_path),
            "name": original_name,
            "output_name": f"{safe_stem}.{container}",
            "container": container,
            "size": out_path.stat().st_size,
            "source": outcome.source,
            "has_cover": False,
            "tags": {},
            "created": time.time(),
        }
    )
    meta = _store_get(rid)
    meta["id"] = rid
    meta["has_cover"] = _extract_cover(out_path, container) is not None
    # 尝试读回标签（embed 已写入文件内）
    try:
        if container == "mp3":
            from mutagen.id3 import ID3

            tags = ID3(out_path)
            meta["tags"] = {
                "title": str(tags.get("TIT2")),
                "artist": str(tags.get("TPE1")),
                "album": str(tags.get("TALB")),
            }
        elif container == "flac":
            from mutagen.flac import FLAC

            f = FLAC(out_path)
            meta["tags"] = {k: f.get(k, [None])[0] for k in ("title", "artist", "album") if f.get(k)}
        elif container == "m4a":
            from mutagen.mp4 import MP4

            f = MP4(out_path)
            mapping = {"\xa9nam": "title", "\xa9ART": "artist", "\xa9alb": "album"}
            meta["tags"] = {v: (f.get(k) or [None])[0] for k, v in mapping.items() if f.get(k)}
    except Exception:
        pass
    meta["tags"] = {k: str(v) for k, v in (meta.get("tags") or {}).items() if v}
    return jsonify({"ok": True, "result": meta})


def _extract_cover(path: Path, container: str) -> bytes | None:
    """从输出音频文件里读回内嵌封面。"""
    try:
        if container == "mp3":
            from mutagen.id3 import ID3

            tags = ID3(path)
            for key in tags.keys():
                if key.startswith("APIC"):
                    return bytes(tags[key].data)
        elif container == "flac":
            from mutagen.flac import FLAC

            pics = FLAC(path).pictures
            if pics:
                return bytes(pics[0].data)
        elif container == "m4a":
            from mutagen.mp4 import MP4

            covr = MP4(path).get("covr") or []
            if covr:
                return bytes(covr[0])
    except Exception:
        pass
    return None


@app.get("/api/cover/<rid>")
def cover(rid: str):
    meta = _store_get(rid)
    if not meta:
        return jsonify({"ok": False, "error": "不存在"}), 404
    path = Path(meta["path"])
    data = _extract_cover(path, meta.get("container", "bin")) if path.exists() else None
    if not data:
        return jsonify({"ok": False, "error": "无封面"}), 404
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return send_file(io.BytesIO(data), mimetype=mime)


@app.get("/api/download/<rid>")
def download(rid: str):
    meta = _store_get(rid)
    if not meta:
        return jsonify({"ok": False, "error": "不存在"}), 404
    path = Path(meta["path"])
    if not path.exists():
        return jsonify({"ok": False, "error": "文件已过期"}), 410
    return send_file(path, as_attachment=True, download_name=meta.get("output_name", path.name))


@app.get("/api/zip")
def zip_batch():
    ids = [i for i in (request.args.get("ids") or "").split(",") if i]
    if not ids:
        return jsonify({"ok": False, "error": "未选择文件"}), 400
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rid in ids:
            meta = _store_get(rid)
            if not meta:
                continue
            path = Path(meta["path"])
            if path.exists():
                zf.write(path, arcname=meta.get("output_name", path.name))
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="unlocked.zip", mimetype="application/zip")


@app.post("/api/clear")
def clear():
    with _lock:
        for meta in _results.values():
            work_dir = Path(meta["path"]).parent
            shutil.rmtree(work_dir, ignore_errors=True)
        _results.clear()
    return jsonify({"ok": True})


def main():
    import argparse

    parser = argparse.ArgumentParser(description="music-unlock 网页版")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8686)
    args = parser.parse_args()
    print(f"music-unlock 网页版已启动: http://{args.host}:{args.port}")
    print("仅监听本机；文件在你的电脑上本地解密，不会上传到任何服务器。")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
