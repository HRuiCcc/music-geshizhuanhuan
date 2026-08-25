#!/usr/bin/env python3
"""music-geshizhuanhuan 入口（薄封装）。用法: python3 unlocker.py <文件或目录> ..."""
import sys

from music_unlock.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
