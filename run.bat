@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1 || (
  echo Python Launcher ^(py^) tidak ditemukan. Install Python 3.12 dari python.org
  pause & exit /b 1
)

py -3.12 -c "import torch, faster_whisper, whisperx, dotenv; assert torch.__version__.startswith('2.8')" >nul 2>&1
if errorlevel 1 (
  echo === Instalasi dependensi pertama kali ^(beberapa menit, butuh ~6 GB^) ===
  set "PIP_NO_CACHE_DIR=1"
  set "TMP=%~dp0.piptmp"
  set "TEMP=%~dp0.piptmp"
  if not exist "%~dp0.piptmp" mkdir "%~dp0.piptmp"
  py -3.12 -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128 || goto :fail
  py -3.12 -m pip install -r requirements-app.txt || goto :fail
  rmdir /s /q "%~dp0.piptmp" 2>nul
)

if not exist .env if exist env.example copy /Y env.example .env >nul

py -3.12 run.py
if errorlevel 1 pause
exit /b 0

:fail
echo Instalasi gagal. Lihat pesan di atas.
pause
exit /b 1
