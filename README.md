# music-geshizhuanhuan 🔓

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![Tests](https://img.shields.io/badge/tests-18%2F18%20passed-brightgreen)
![Cross-check](https://img.shields.io/badge/cross--check-6%2F6%20passed-brightgreen)

全平台加密音乐解锁器（网页版 + 命令行版），**代码从零自研**，按公开格式规范实现四个平台的解密与格式转换，
跨平台（macOS / Linux / Windows），仅依赖 pycryptodome、mutagen 与 flask，其余全部标准库。

```
网易云 .ncm → mp3/flac
QQ音乐 .mflac/.mgg/.qmc*/.tkm/.bkc* → mp3/flac/ogg 等
酷狗  .kgm/.kgma/.vpr → mp3/flac 等
酷我  .kwm → mp3/flac 等
```

## ✨ 特性

- **网页版**：拖拽文件/文件夹、并发队列、封面与标签预览、单文件下载 / zip 打包（`./run.sh web`）
- **命令行版**：批量递归、统一转码（ffmpeg）、标签与封面嵌入、命名冲突自动处理
- **四平台九类格式**：一个引擎全解析，自动识别无需指定格式
- **零上传**：网页版仅监听 127.0.0.1，文件在本地解密
- **可验证的正确性**：18 项单元测试 + 与四个独立开源参考工具逐字节交叉验证

## 快速开始

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# —— 网页版（推荐）——
./run.sh web                    # 浏览器打开 http://127.0.0.1:8686
# 拖拽文件/文件夹 → 自动排队解密 → 单个下载或打包 zip
# 可选参数: --host 127.0.0.1 --port 8686

# —— 命令行版 ——
./run.sh 歌曲.ncm                          # 解密，输出到 ./unlocked
./run.sh 音乐目录/ -o out                  # 批量（目录默认递归）
./run.sh a.mflac b.kgm -o out --format flac     # 解密并统一转码为 flac
./run.sh a.ncm -o out --no-embed-cover          # 不写标签/封面
./run.sh a.ncm --dry-run                        # 只列计划
```

网页版说明：文件**只在你的电脑本地解密**，服务仅监听 `127.0.0.1`，不会上传到任何服务器；
支持文件夹拖入、并发队列、封面/标签预览、单文件下载与 zip 打包、转码格式选择、EKey 输入。

### 常用参数

| 参数 | 说明 |
|---|---|
| `-o DIR` | 输出目录（默认 `./unlocked`） |
| `--format mp3/flac/m4a/wav/ogg` | 统一转码目标（需要 ffmpeg，`--ffmpeg` 可指定路径） |
| `--embed-cover` / `--no-embed-cover` | 是否嵌入标签与封面（默认嵌入） |
| `--force` | 覆盖已存在的输出；否则自动加 `(1)` 后缀 |
| `--no-recursive` | 目录输入不递归 |
| `--ekey STR` | QMC 无内嵌密钥文件手动指定 EKey |
| `--ekey-db PATH` | QQ 音乐安卓端 `player_process_db` 密钥库 |
| `--kgm-key PATH` | 酷狗公钥（默认内置 `assets/kugou_key.xz`） |
| `--list-ekey-db PATH [--find 名字]` | 列出密钥库条目 |
| `--dry-run` | 只列计划不写文件 |

## 支持矩阵与限制

| 格式 | 变体 | 说明 |
|---|---|---|
| NCM | 全部 | 离线，含歌名/歌手/专辑/封面提取 |
| QMC v1 | .tkm / .bkc* / 十六进制扩展名 | 静态密钥，离线 |
| QMC v2 | .mflac/.mgg/.qmc*（QTag / PcV1Legacy 内嵌 EKey） | 离线；Map(≤300B) 与 RC4(>300B) 两种流密码 |
| QMC v2 | 新版 MusicEx / STag（无内嵌密钥） | 需 `--ekey` 或 `--ekey-db`（安卓端密钥库）；或客户端降级 19.51 重下 |
| KGM | v1~v4（.kgm/.kgma/.vpr） | 离线，内置公钥 |
| KGG | v5 | 暂不支持（需客户端 KGMusicV3.db） |
| KWM | 老版 .kwm | 离线；密钥恢复带容器嗅探校验 |

## 架构

```
music_unlock/
├── cli.py            # argparse 入口
├── batch.py          # 输入收集 / 批量处理 / 命名冲突 / 落盘
├── transcode.py      # ffmpeg 转码
├── tags.py           # mutagen 标签与封面嵌入
├── model.py          # DecodeResult / 容器嗅探
├── ciphers.py        # TEA / RC4 / QMC v1-v2 流密码 / NCM 密钥流
└── formats/
    ├── base.py       # Decoder 协议与 DecodeOptions
    ├── ncm.py        # 网易云
    ├── qmc.py        # QQ 音乐（尾包解析 + EKey 派生 + 密钥库查询）
    ├── kgm.py        # 酷狗（17 相位组合查表）
    └── kwm.py        # 酷我（密钥恢复）
web/
├── server.py         # Flask API（上传/解码/下载/zip/封面，复用同一套核心）
└── static/index.html # 原生 JS 前端（拖拽、队列、进度、预览）
```

## 测试

```bash
./.venv/bin/pip install pytest
./.venv/bin/python -m pytest tests/ -v          # 14 项单元测试（四格式往返 + 边界）
./.venv/bin/python tests/crosscheck.py          # 与参考开源工具逐字节交叉验证（6 项）
```

交叉验证会把本项目构造器生成的样本交给四个独立参考工具
（ncmdump-py / qmc_decrypt / QKKDecrypt-kugou / kwm_decrypt）解密并逐字节比对，
证明实现与真实格式完全兼容。测试样本全部为自建合成数据（正弦波），不含任何版权内容。

## 合规声明

本项目按 MIT 协议发布，仅面向学习研究与个人本地文件处理：使用者应仅解密
**自己合法下载、有权使用**的文件，并自行确认行为符合当地法律与平台协议。
禁止用于批量分发、倒卖或规避付费授权。

内置密钥材料（QMC v1 静态密钥、酷狗公钥 `kugou_key.xz`）为公开数据，
源自 MIT 协议的 unlock-music / um-crypto 项目，仅作数据使用，不包含其代码。
