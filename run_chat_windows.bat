@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo AI QAHelper - запуск chat mode
echo.

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [Ошибка] Python не найден.
        echo Установите Python 3.11+ с https://www.python.org/downloads/ и включите Add Python to PATH.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение .venv...
    %PYTHON_CMD% -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [Ошибка] Не удалось создать .venv.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -e .
if %ERRORLEVEL% NEQ 0 (
    echo [Ошибка] Не удалось установить зависимости.
    pause
    exit /b 1
)

if not exist "ai-tester.config.yaml" (
    copy "ai-tester.config.example.yaml" "ai-tester.config.yaml" >nul
    echo Создан ai-tester.config.yaml из примера.
)

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
    ) else (
        type nul > ".env"
    )
)

python -c "from ai_qahelper.config import get_openai_api_key; raise SystemExit(0 if get_openai_api_key() else 1)" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Введите OPENAI_API_KEY. Он будет сохранён только в локальный файл .env.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$secure=Read-Host 'OPENAI_API_KEY' -AsSecureString; $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); try { $key=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr); if ([string]::IsNullOrWhiteSpace($key)) { exit 1 }; $trimmed=$key.Trim(); $lower=$trimmed.ToLowerInvariant(); if ($lower -eq 'your_key_here' -or $lower -eq 'sk-...' -or $lower.Contains('changeme') -or $lower.Contains('placeholder') -or $lower.Contains('example') -or $trimmed.Length -lt 20) { exit 2 }; $p='.env'; $lines=@(); if (Test-Path $p) { $lines=Get-Content $p | Where-Object { $_ -notmatch '^OPENAI_API_KEY=' } }; $lines + ('OPENAI_API_KEY=' + $trimmed) | Set-Content -Encoding UTF8 $p } finally { if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) } }"
    if !ERRORLEVEL! EQU 1 (
        echo [Ошибка] OPENAI_API_KEY не задан.
        pause
        exit /b 1
    )
    if !ERRORLEVEL! EQU 2 (
        echo [Ошибка] OPENAI_API_KEY похож на placeholder.
        pause
        exit /b 1
    )
    if !ERRORLEVEL! NEQ 0 (
        echo [Ошибка] Не удалось сохранить OPENAI_API_KEY.
        pause
        exit /b 1
    )
)

echo.
echo Открываю AI QAHelper в браузере...
python -m ai_qahelper.cli chat
pause
