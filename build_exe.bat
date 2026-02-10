@echo off
setlocal

echo [0/5] Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist uart-tool.spec del /f /q uart-tool.spec

echo [1/5] Create venv
python -m venv .venv
if errorlevel 1 goto :error

call .venv\Scripts\activate

echo [2/5] Upgrade build tools
python -m pip install --upgrade pip wheel setuptools
if errorlevel 1 goto :error

echo [3/5] Install project (pip install .)
pip install .
if errorlevel 1 goto :error

echo [4/5] Install PyInstaller
pip install pyinstaller
if errorlevel 1 goto :error

echo [5/5] Build exe
pyinstaller --clean --onefile --noconsole -n uart-tool ^
  --collect-submodules uarttool ^
  --collect-data uarttool ^
  uarttool\main.py
if errorlevel 1 goto :error

echo.
echo Build finished. Output: dist\uart-tool.exe
goto :done

:error
echo.
echo Build failed.

:done
echo.
pause
