#!/usr/bin/env python3
"""Create a minimal non-destructive Youtube video output folder."""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path


def safe_title(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title).strip()
    normalized = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-. ")
    return normalized[:120].rstrip("-. ") or "untitled-video"


def versioned_directory(root: Path, title: str) -> Path:
    candidate = root / title
    if not candidate.exists():
        return candidate

    version = 2
    while True:
        candidate = root / f"{title}-v{version}"
        if not candidate.exists():
            return candidate
        version += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Video title used as the folder name")
    parser.add_argument(
        "--root",
        default="Youtube",
        help="Youtube output root; defaults to ./Youtube",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    project_dir = versioned_directory(root, safe_title(args.title))
    project_dir.mkdir(parents=True)
    (project_dir / "scenes").mkdir()
    (project_dir / "thumbnails").mkdir()
    print(project_dir)


if __name__ == "__main__":
    main()
