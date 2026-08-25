"""music-geshizhuanhuan —— 全平台加密音乐格式转换工具。

支持格式：网易云 NCM、QQ 音乐 QMC(v1/v2)、酷狗 KGM(v3/v4)、酷我 KWM。
全部算法均为公开格式规范的自研实现，仅依赖 pycryptodome(AES) 与 mutagen(标签)，
其余为标准库。仅用于解密自己合法拥有、有权使用的本地文件。
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
