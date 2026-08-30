# music-geshizhuanhuan（音乐格式转换）Docker 镜像
# Python 3.11 + Flask + 系统 ffmpeg（转码必需；requirements.txt 不含 ffmpeg，
# 原流程依赖宿主机已安装，这里在镜像内一并装好）
FROM python:3.11-slim-bookworm

# 无缓冲输出，容器日志实时可见
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# 系统依赖：ffmpeg 用于 mp3/flac/m4a/wav/ogg 转码
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 先拷依赖清单，利用 Docker 层缓存
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 拷贝全部源码
COPY . .

# 网页版默认端口
EXPOSE 8686

# 健康检查：复用镜像内 Python 访问自带的健康接口（无额外依赖）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8686/api/health').status==200 else 1)"

# 启动网页版，监听所有网卡（容器内需 0.0.0.0 才能从宿主机访问）
# 仅解密、保持原格式时不需要 ffmpeg；需要转码时镜像内已自带
CMD ["python", "web/server.py", "--host", "0.0.0.0", "--port", "8686"]
