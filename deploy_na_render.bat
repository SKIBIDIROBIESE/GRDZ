@echo off
chcp 65001 >nul
title GRDZ_SNIPE // Deployment do Chmury (Render / Railway)
cls
echo =====================================================================
echo    ⚡ GRDZ_SNIPE - WDROŻENIE STRONY DO CHMURY 24/7 (HTTPS + SSL)
echo =====================================================================
echo.
echo Twoja strona jest gotowa do uruchomienia na zewnętrznym serwerze,
echo dzięki czemu:
echo  1. Będzie działać 24/7 bez potrzeby włączania Twojego komputera.
echo  2. Będzie miała oficjalny certyfikat SSL (bezpieczna zielona kłódka).
echo  3. Każdy użytkownik na świecie będzie mógł na nią wejść.
echo.
echo =====================================================================
echo KROK 1: Utwórz darmowe prywatne/publiczne repozytorium na GitHub:
echo         https://github.com/new
echo.
echo KROK 2: Wklej poniżej adres URL Twojego nowego repozytorium GitHub
echo         (np. https://github.com/twoj-nick/grdzsnipe.git):
echo =====================================================================
echo.
set /p REPO_URL="Wklej adres repozytorium GitHub: "

if "%REPO_URL%"=="" (
    echo [!] Nie podano adresu URL. Anulowano.
    pause
    exit /b
)

echo.
echo [*] Konfigurowanie zdalnego repozytorium...
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git branch -M main
echo [*] Wypychanie plików do GitHub...
git push -u origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Błąd podczas wysyłania do GitHuba. Upewnij się, że jesteś zalogowany w Git.
    pause
    exit /b
)

echo.
echo =====================================================================
echo  ✓ SUKCES! Pliki znajdują się w Twoim GitHubie.
echo.
echo KROK 3: Wejdź na https://dashboard.render.com (lub railway.app)
echo  1. Kliknij "New +" -> "Web Service"
echo  2. Wybierz swoje repozytorium GitHub
echo  3. Render automatycznie odczyta plik "render.yaml" i uruchomi stronę!
echo  4. Otrzymasz gotowy publiczny adres z HTTPS (zielona kłódka)!
echo =====================================================================
echo.
pause
