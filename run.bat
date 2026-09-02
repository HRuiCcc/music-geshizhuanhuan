@echo off
chcp 65001 >nul
rem music-geshizhuanhuan Windows 启动器（网页版 / 命令行 双模式）
rem 网页版:  run.bat web                 -> 自动打开 http://127.0.0.1:8686
rem 命令行:  run.bat <文件或目录> [-o 输出目录] [--format mp3|flac|m4a|wav|ogg]
cd /d "%~dp0"

rem 首次运行自动创建虚拟环境并安装依赖
if not exist ".venv\Scripts\python.exe" (
  echo [music-geshizhuanhuan] 首次运行：创建虚拟环境并安装依赖...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  ".venv\Scripts\pip" install -q --upgrade pip
  ".venv\Scripts\pip" install -q -r requirements.txt
)

if /i "%~1"=="web" (
  shift
  ".venv\Scripts\python" web\server.py %*
) else (
  ".venv\Scripts\python" unlocker.py %*
)
