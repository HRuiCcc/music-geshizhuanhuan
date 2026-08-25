"""批量处理：输入收集、解码、输出落盘、命名冲突处理。"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UnlockError
from .formats import pick_decoder, supported_extensions
from .formats.base import DecodeOptions
from .tags import embed
from .transcode import transcode


@dataclass(slots=True)
class BatchOptions:
    output_dir: Path
    target: str | None = None          # None = 保持解密后原容器
    embed_cover: bool = True
    force: bool = False
    recursive: bool = True
    dry_run: bool = False
    ffmpeg: str | None = None
    decode: DecodeOptions = field(default_factory=DecodeOptions)


@dataclass(slots=True)
class FileOutcome:
    input: Path
    output: Path | None = None
    status: str = "ok"                 # ok / skipped / failed
    note: str = ""
    source: str = ""


def collect_inputs(inputs: list[Path], recursive: bool) -> list[Path]:
    """把文件/目录输入展开为候选文件列表（按扩展名过滤）。"""
    known = supported_extensions()
    files: list[Path] = []
    seen: set[Path] = set()
    for item in inputs:
        if item.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(item.glob(pattern)):
                if child.is_file() and child.suffix.lower() in known and child not in seen:
                    seen.add(child)
                    files.append(child)
        elif item.is_file() and item not in seen:
            seen.add(item)
            files.append(item)
    return files


def _unique_path(directory: Path, stem: str, ext: str, force: bool) -> Path | None:
    """解决输出命名冲突；已存在且未强制覆盖时返回 None（跳过）。"""
    candidate = directory / f"{stem}.{ext}"
    if not candidate.exists() or force:
        return candidate
    for i in range(1, 1000):
        candidate = directory / f"{stem} ({i}).{ext}"
        if not candidate.exists():
            return candidate
    return None


def process_one(path: Path, opts: BatchOptions) -> FileOutcome:
    outcome = FileOutcome(input=path)
    try:
        decoder = pick_decoder(path)
        result = decoder.decode(path, opts.decode)
        if not result.payload:
            raise UnlockError("解密结果为空")

        ext = opts.target or result.suggested_extension
        final = _unique_path(opts.output_dir, path.stem, ext, opts.force)
        if final is None:
            outcome.status = "skipped"
            outcome.note = "输出已存在（--force 可覆盖）"
            return outcome
        outcome.output = final
        outcome.source = result.source
        if opts.dry_run:
            outcome.note = f"dry-run: 将输出 {final.name}"
            return outcome

        opts.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=opts.output_dir, suffix=f".{ext}", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            need_transcode = bool(opts.target) and result.container != opts.target
            if need_transcode:
                raw = tmp_path.with_suffix(".raw")
                raw.write_bytes(result.payload)
                try:
                    transcode(raw, tmp_path, opts.target, opts.ffmpeg)
                finally:
                    raw.unlink(missing_ok=True)
            else:
                tmp_path.write_bytes(result.payload)
            if opts.embed_cover and (result.tags or result.cover):
                embed(ext if ext in ("mp3", "flac", "m4a") else result.container, tmp_path, result.tags, result.cover)
            shutil.move(str(tmp_path), final)
        finally:
            tmp_path.unlink(missing_ok=True)
        outcome.note = f"{result.container} -> {ext}"
        return outcome
    except UnlockError as exc:
        outcome.status = "failed"
        outcome.note = str(exc)
        return outcome
    except Exception as exc:  # 单文件失败不中断批次
        outcome.status = "failed"
        outcome.note = f"{type(exc).__name__}: {exc}"
        return outcome


def run_batch(inputs: list[Path], opts: BatchOptions, on_event=None) -> list[FileOutcome]:
    """处理一批输入，逐个回调 on_event(outcome)。"""
    files = collect_inputs(inputs, opts.recursive)
    results = []
    for path in files:
        outcome = process_one(path, opts)
        results.append(outcome)
        if on_event:
            on_event(outcome)
    return results


def summarize(results: list[FileOutcome]) -> tuple[int, int, int]:
    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    return ok, skipped, failed
