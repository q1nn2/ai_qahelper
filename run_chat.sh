#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "AI QAHelper - запуск chat mode"
echo

if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="python"
else
  echo "[Ошибка] Python не найден."
  echo "Установите Python 3.11+ и повторите запуск."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Создаю виртуальное окружение .venv..."
  "$PYTHON_CMD" -m venv .venv
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

python -m pip install --upgrade pip
python -m pip install -e .

if [ ! -f "ai-tester.config.yaml" ]; then
  cp "ai-tester.config.example.yaml" "ai-tester.config.yaml"
  echo "Создан ai-tester.config.yaml из примера."
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp ".env.example" ".env"
  else
    touch ".env"
  fi
fi

if [ -z "${OPENAI_API_KEY:-}" ] && ! grep -Eq '^OPENAI_API_KEY=..+' ".env"; then
  echo
  echo "Введите OPENAI_API_KEY. Он будет сохранён только в локальный файл .env."
  read -r -p "OPENAI_API_KEY: " OPENAI_API_KEY
  if [ -z "$OPENAI_API_KEY" ]; then
    echo "[Ошибка] OPENAI_API_KEY не задан."
    exit 1
  fi
  tmp_env="$(mktemp)"
  grep -Ev '^OPENAI_API_KEY=' ".env" > "$tmp_env" || true
  printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY" >> "$tmp_env"
  mv "$tmp_env" ".env"
fi

echo
echo "Открываю AI QAHelper в браузере..."
python -m ai_qahelper.cli chat
