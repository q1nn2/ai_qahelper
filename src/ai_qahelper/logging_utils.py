from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(session_dir: Path) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    log_file = session_dir / "qahelper.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )
