"""Vercel's entrypoint (it looks for an `app` in a root app.py): the web app from src/fall_zero/server.py.
Locally run `uv run fall-zero serve` instead."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))  # the package's own files, wherever deps were installed

from fall_zero.server import app  # noqa: E402

__all__ = ["app"]
