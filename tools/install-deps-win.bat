@echo off
rem ============================================================
rem  MaaCR - install the .NET 10 Desktop Runtime (Windows x64)
rem
rem  MFAAvalonia is published as "framework-dependent"
rem  (<SelfContained>false</SelfContained>), so the bundled
rem  MFAAvalonia.exe will NOT start until this runtime is installed.
rem
rem  This file is intentionally ASCII-only: cmd.exe may be running
rem  under a non-UTF-8 code page, and non-ASCII text would show up
rem  garbled. The Chinese explanation lives in README.md.
rem ============================================================
setlocal

echo.
echo   MaaCR needs the .NET 10 Desktop Runtime.
echo.

where winget >nul 2>nul
if errorlevel 1 goto manual

echo   Installing via winget ...
echo.
winget install --id Microsoft.DotNet.DesktopRuntime.10 -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto manual

echo.
echo   Done. Please REBOOT, then run MFAAvalonia.exe again.
echo.
pause
exit /b 0

:manual
echo   winget is unavailable, or the install failed.
echo   Opening the official download page instead.
echo.
echo   1) Download ".NET Desktop Runtime 10.x - Windows x64"
echo   2) Install it
echo   3) REBOOT, then run MFAAvalonia.exe again
echo.
start "" "https://dotnet.microsoft.com/download/dotnet/10.0"
pause
exit /b 1
