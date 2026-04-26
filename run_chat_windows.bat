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

if "%OPENAI_API_KEY%"=="" (
    findstr /R /C:"^OPENAI_API_KEY=..*" ".env" >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Введите OPENAI_API_KEY. Он будет сохранён только в локальный файл .env.
        set /p OPENAI_API_KEY=OPENAI_API_KEY: 
        if "!OPENAI_API_KEY!"=="" (
            echo [Ошибка] OPENAI_API_KEY не задан.
            pause
            exit /b 1
        )
        powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='.env'; $lines=@(); if (Test-Path $p) { $lines=Get-Content $p | Where-Object { $_ -notmatch '^OPENAI_API_KEY=' } }; $lines + 'OPENAI_API_KEY=!OPENAI_API_KEY!' | Set-Content -Encoding UTF8 $p"
    )
)

echo.
echo Открываю AI QAHelper в браузере...
python -m ai_qahelper.cli chat
pause
