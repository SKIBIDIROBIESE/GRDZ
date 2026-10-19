@echo off
title GRDZ-SNIPE // Konfiguracja Domeny Lokalnej
cd /d "%~dp0"

echo ====================================================================
echo   GRDZ-SNIPE - AUTOMATYCZNA KONFIGURACJA DOMENY GRDZSNIPE.COM
echo ====================================================================
echo.

:: Sprawdzenie uprawnien administratora
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :add_hosts
) else (
    echo [!] Wymagane uprawnienia administratora do edycji pliku hosts.
    echo [*] Proba uruchomienia w trybie Administratora...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:add_hosts
set HOSTS=%WINDIR%\System32\drivers\etc\hosts

:: Sprawdzenie czy domena juz istnieje w hosts
findstr /I "grdzsnipe.com" "%HOSTS%" >nul 2>&1
if %errorLevel% == 0 (
    echo [*] Domena grdzsnipe.com jest juz skonfigurowana w pliku hosts.
) else (
    echo [*] Dodawanie wpisow domeny do %HOSTS%...
    echo. >> "%HOSTS%"
    echo # Domena lokalna GRDZ_SNIPE Portal >> "%HOSTS%"
    echo 127.0.0.1 grdzsnipe.com >> "%HOSTS%"
    echo 127.0.0.1 www.grdzsnipe.com >> "%HOSTS%"
    echo 127.0.0.1 grdz-snipe.com >> "%HOSTS%"
    echo [OK] Wpisy dodane pomyslnie!
)

:: Wyczyszczenie pamieci podrecznej DNS
ipconfig /flushdns >nul 2>&1
echo.
echo ====================================================================
echo   SUKCES! Mozesz teraz wchodzic na: http://grdzsnipe.com
echo ====================================================================
echo.
pause
