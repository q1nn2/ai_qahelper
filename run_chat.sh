#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REINSTALL=0
if [ "${1:-}" = "--reinstall" ]; then
  REINSTALL=1
fi

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

if [ ! -f ".venv/.ai_qahelper_installed" ]; then
  REINSTALL=1
fi

if [ "$REINSTALL" -eq 1 ]; then
  python -m pip install --upgrade pip --timeout 60 --retries 10
  python -m pip install -e . --timeout 60 --retries 10
  touch ".venv/.ai_qahelper_installed"
else
  echo "Зависимости уже установлены. Для переустановки запустите ./run_chat.sh --reinstall"
fi

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
  echo "Введите OPENAI_API_KEY или нажмите Enter, чтобы добавить ключ позже через браузер:"
  read -r -s -p "OPENAI_API_KEY: " OPENAI_API_KEY
  echo
  if is_placeholder_api_key "$OPENAI_API_KEY"; then
    echo "OPENAI_API_KEY не введён. Приложение откроется, вы сможете добавить ключ через браузер."
  else
    tmp_env="$(mktemp)"
    grep -Ev '^OPENAI_API_KEY=' ".env" > "$tmp_env" || true
    printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY" >> "$tmp_env"
    mv "$tmp_env" ".env"
  fi
fi

echo
echo "Открываю AI QAHelper в браузере..."
python -m ai_qahelper.cli chat
