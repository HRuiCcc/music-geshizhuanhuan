"""标签与封面嵌入（mutagen）。"""
from __future__ import annotations

from pathlib import Path


def _image_mime(cover: bytes) -> str:
    return "image/png" if cover[:4] == b"\x89PNG" else "image/jpeg"


def embed(container: str, path: Path, tags: dict[str, str], cover: bytes | None) -> None:
    """按容器类型写入标签与封面；不支持的容器静默跳过。"""
    if not tags and not cover:
        return
    try:
        if container == "mp3":
            from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1

            audio = ID3()  # 新建对象：无 ID3 头的 mp3 也能在文件头插入标签
            for frame, value in ((TIT2, tags.get("title")), (TPE1, tags.get("artist")), (TALB, tags.get("album"))):
                if value:
                    audio.add(frame(encoding=3, text=value))
            if cover:
                audio.add(APIC(encoding=3, mime=_image_mime(cover), type=3, desc="cover", data=cover))
            audio.save(path)
        elif container == "flac":
            from mutagen.flac import FLAC, Picture

            audio = FLAC(path)
            for key, tag in (("title", "title"), ("artist", "artist"), ("album", "album")):
                if tags.get(tag):
                    audio[key] = tags[tag]
            if cover:
                pic = Picture()
                pic.type = 3
                pic.mime = _image_mime(cover)
                pic.data = cover
                audio.clear_pictures()
                audio.add_picture(pic)
            audio.save()
        elif container == "m4a":
            from mutagen.mp4 import MP4, MP4Cover

            audio = MP4(path)
            mapping = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb"}
            for tag, atom in mapping.items():
                if tags.get(tag):
                    audio[atom] = [tags[tag]]
            if cover:
                fmt = MP4Cover.FORMAT_PNG if cover[:4] == b"\x89PNG" else MP4Cover.FORMAT_JPEG
                audio["covr"] = [MP4Cover(cover, imageformat=fmt)]
            audio.save()
    except Exception:
        pass  # 标签失败不影响主流程
