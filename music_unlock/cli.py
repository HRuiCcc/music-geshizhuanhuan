"""命令行入口。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .batch import BatchOptions, run_batch, summarize
from .errors import UnlockError
from .formats.base import DecodeOptions
from .formats.qmc import list_ekeys
from .transcode import TARGETS

BANNER = """music-geshizhuanhuan —— 全平台加密音乐格式转换工具
支持: 网易云 .ncm | QQ音乐 .mflac/.mgg/.qmc*/.tkm | 酷狗 .kgm/.kgma/.vpr | 酷我 .kwm
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unlocker",
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="*", type=Path, help="加密文件或目录（可多个）")
    parser.add_argument("-o", "--output", type=Path, default=Path("unlocked"), help="输出目录（默认 ./unlocked）")
    parser.add_argument("--format", choices=TARGETS, default=None, help="转码目标格式（默认保持解密后原容器）")
    parser.add_argument("--embed-cover", action="store_true", default=True, help="嵌入标签与封面（默认）")
    parser.add_argument("--no-embed-cover", dest="embed_cover", action="store_false", help="不嵌入标签与封面")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的输出文件")
    parser.add_argument("--no-recursive", dest="recursive", action="store_false", help="目录输入不递归扫描")
    parser.add_argument("--ekey", help="手动指定 QMC EKey（base64 字符串，用于无内嵌密钥的文件）")
    parser.add_argument("--ekey-db", type=Path, help="QQ 音乐安卓端 player_process_db 密钥库路径")
    parser.add_argument("--kgm-key", type=Path, help="酷狗公钥 kugou_key.xz 路径（默认使用内置）")
    parser.add_argument("--ffmpeg", help="ffmpeg 可执行文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只列出计划，不写文件")
    parser.add_argument("--list-ekey-db", metavar="DB", help="列出密钥库内容后退出（可配合 --find）")
    parser.add_argument("--find", help="与 --list-ekey-db 配合，按名字过滤")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    parser.add_argument("--version", action="version", version=f"music-geshizhuanhuan {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_ekey_db:
        try:
            rows = list_ekeys(args.list_ekey_db, args.find)
        except Exception as exc:
            print(f"读取密钥库失败: {exc}", file=sys.stderr)
            return 2
        if not rows:
            print("（空）")
            return 0
        for name, ekey in rows:
            print(f"{name}  ->  {ekey}")
        return 0

    if not args.inputs:
        parser.print_help()
        return 1

    decode_opts = DecodeOptions(ekey=args.ekey, ekey_db=args.ekey_db, kgm_key=args.kgm_key)
    opts = BatchOptions(
        output_dir=args.output,
        target=args.format,
        embed_cover=args.embed_cover,
        force=args.force,
        recursive=args.recursive,
        dry_run=args.dry_run,
        ffmpeg=args.ffmpeg,
        decode=decode_opts,
    )

    def report(outcome):
        if outcome.status == "ok":
            print(f"[OK] {outcome.input.name} -> {outcome.output}  ({outcome.note})")
        elif outcome.status == "skipped":
            print(f"[SKIP] {outcome.input.name}: {outcome.note}")
        else:
            print(f"[FAIL] {outcome.input.name}: {outcome.note}", file=sys.stderr)

    results = run_batch(args.inputs, opts, on_event=report)
    ok, skipped, failed = summarize(results)
    print(f"完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
