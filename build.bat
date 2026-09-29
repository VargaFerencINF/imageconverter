@echo off
rem ---------------------------------------------------------------------------
rem  WebKep Konverter - helyi Windows build
rem  Eredmeny: dist\WebKepKonverter\ (mappas), dist\WebKepKonverter-Portable.exe,
rem            dist\webkep-cli.exe es (ha van Inno Setup) installer_output\*.exe
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

if not exist .venv (
    echo [1/5] Virtualis kornyezet letrehozasa...
    %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo [2/5] Fuggosegek telepitese...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-build.txt || goto :error

echo [3/5] Tesztek futtatasa...
set QT_QPA_PLATFORM=offscreen
python -m pytest -q || goto :error
set QT_QPA_PLATFORM=

echo [4/5] PyInstaller build...
pyinstaller --noconfirm --clean packaging\webkep.spec || goto :error

echo [5/5] Telepito keszitese (Inno Setup)...
for /f "delims=" %%v in ('python -c "import webkep; print(webkep.__version__)"') do set "VER=%%v"
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" /DAppVersion=%VER% packaging\installer.iss || goto :error
) else (
    echo   Inno Setup nem talalhato - a telepito kimarad. Letoltes: https://jrsoftware.org/isdl.php
)

echo.
echo Kesz! Verzio: %VER%
echo   dist\WebKepKonverter-Portable.exe   - hordozhato, egyetlen exe
echo   dist\WebKepKonverter\               - mappas valtozat
echo   dist\webkep-cli.exe                 - parancssor
if defined ISCC echo   installer_output\WebKepKonverter-Setup-%VER%.exe - telepito
exit /b 0

:error
echo.
echo HIBA tortent a build soran (kod: %errorlevel%).
exit /b 1
