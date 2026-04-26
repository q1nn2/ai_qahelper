from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_chat() -> None:
    """Launch the local Streamlit chat UI."""
    app_path = Path(__file__).with_name("chat_app.py")
    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)]))


if __name__ == "__main__":
    run_chat()
