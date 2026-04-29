from pathlib import Path


def load_knowledge_base() -> str:
    root_dirs = [
        Path("knowledge_base"),
        # Path("training_data"),  # disabled until curated
    ]

    parts: list[str] = []

    for root_dir in root_dirs:
        if not root_dir.exists():
            continue

        for path in sorted(root_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8").strip()

            if not text:
                continue

            parts.append(
                f"\n\n### SOURCE: {path.as_posix()}\n{text}"
            )

    return "\n".join(parts)
