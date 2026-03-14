@echo off
setlocal

cd /d %~dp0

if not exist .venv (
  py -3.11 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller --noconfirm --clean file_organizer.spec

echo.
echo Build finished.
echo EXE path: %cd%\dist\FileOrganizer.exe
pause
