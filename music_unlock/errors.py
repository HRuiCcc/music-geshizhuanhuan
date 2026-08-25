"""统一异常类型。"""
from __future__ import annotations


class UnlockError(Exception):
    """所有解锁错误的基类。"""


class FormatError(UnlockError):
    """文件头/结构不符合预期格式。"""


class KeyError_(UnlockError):
    """密钥缺失或无法推导（例如新版 MusicEx 无内嵌 EKey）。"""


class UnsupportedError(UnlockError):
    """已知但尚未支持的格式变体。"""
