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

is_placeholder_api_key() {
  key="$(printf '%s' "${1:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  lower="$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')"
  [ -z "$key" ] && return 0
  [ "$lower" = "your_key_here" ] && return 0
  [ "$lower" = "sk-..." ] && return 0
  case "$lower" in
    *changeme*|*placeholder*|*example*) return 0 ;;
  esac
  [ "${#key}" -lt 20 ] && return 0
  return 1
}

env_file_key=""
if [ -f ".env" ]; then
  env_file_key="$(grep -E '^OPENAI_API_KEY=' ".env" | tail -n 1 | sed 's/^OPENAI_API_KEY=//')"
fi

if is_placeholder_api_key "${OPENAI_API_KEY:-}" && is_placeholder_api_key "$env_file_key"; then
  echo
  echo "Введите OPENAI_API_KEY. Он будет сохранён только в локальный файл .env."
  read -r -s -p "OPENAI_API_KEY: " OPENAI_API_KEY
  echo
  if is_placeholder_api_key "$OPENAI_API_KEY"; then
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
